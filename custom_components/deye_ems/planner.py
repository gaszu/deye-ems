"""Deterministic Deye energy planning, independent of HA and EMHASS.

``plan_energy`` accepts ``now`` (aware datetime or ISO string), ``soc_percent``,
and exactly 96 chronological half-hour ``forecast`` records with ``timestamp``,
``pv_p10_kw``, ``pv_p50_kw`` and ``load_kw``. LOAD already includes the complete
heat pump: this module never adds PC/today/yesterday energy a second time.
The first timestamp is the Unix half-hour containing now. Explicit offsets
disambiguate DST. A dated Solcast cache is acceptable when it covers this axis;
retrieval age alone never makes a covered forecast stale.

Default ``pv_forecast_mode=whole_system`` preserves site-specific source kW
exactly. Only explicit ``specific_profile`` mode normalizes by the source's
``pv_forecast_reference_kwp`` and multiplies by installed ``pv_peak_kwp``.
The runtime must not scale source powers a second time. Installed capacity is
required; a reference capacity is required only for explicit normalization.

Optional inputs: ``soc_valid`` (runtime freshness verdict), ``retained_targets``
(night/peak numbers or records containing soc_percent), and ``config`` using
DEFAULTS keys. Runtime owns entity/unit/restored/freshness checks. Optional
``soc_updated_at`` is checked when supplied, with a fresh same-BMS
``voltage_updated_at`` serving only as a communication anchor.
Projection requires live ``battery_charge_max_a`` (total Deye/BMS ceiling),
``grid_current_max_a`` (separate grid-only ceiling), and battery voltage.
The obsolete fixed ``charge_max_kw`` option is ignored, including saved values.

Outputs: status ok/unreachable/fallback, quality valid/invalid, generated_at,
season, targets night/peak, central projection rows and p10/p50 metrics.
They are model predictions and requested deadline targets, never device ACKs.
Invalid inputs return explicit fallback targets and EMPTY projections.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import math
from zoneinfo import ZoneInfo

if __package__:
    from .tariff_calendar import calendar_context, describe_calendar, intervals_between


DEFAULTS = {
    "timezone": "Europe/Warsaw", "capacity_kwh": 66.0,
    "minimum_soc_percent": 40.0, "margin_soc_percent": 5.0,
    "minimum_soc_lower_bound": 40.0,
    "winter_weather_soc_percent": 75.0,
    "grid_max_soc_percent": 95.0,
    "battery_charge_max_a": None, "grid_current_max_a": None,
    "battery_voltage_v": None,
    "discharge_max_kw": 10.0, "grid_import_max_kw": 12.0,
    "grid_export_max_kw": 9.0, "inverter_max_kw": 12.0,
    "eta_charge": .95, "eta_discharge": .95,
    "eta_ac_dc": .96, "eta_dc_ac": .96,
    "pv_peak_kwp": None, "pv_forecast_reference_kwp": None,
    "pv_forecast_mode": "whole_system",
}
TOLERANCE_KWH = .005


def _value(value, name, low=0, high=None):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < low
            or high is not None and value > high):
        raise ValueError("invalid_" + name)
    return float(value)


def _time(value, zone):
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError
        return dt.astimezone(zone)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("invalid_aware_timestamp") from None


def _settings(raw, *, target_only=False):
    if not isinstance(raw, dict):
        raise ValueError("invalid_config")
    cfg = dict(DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS})
    try:
        cfg["zone"] = ZoneInfo(cfg["timezone"])
    except (ValueError, TypeError, KeyError):
        raise ValueError("invalid_timezone") from None
    for key in DEFAULTS:
        if key not in ("timezone", "pv_forecast_mode"):
            if key in ("battery_voltage_v", "battery_charge_max_a", "grid_current_max_a") and cfg[key] is None and target_only:
                # Fallback may choose a reserve target without inventing
                # measured voltage/current. It returns no energy projection.
                continue
            if key in ("pv_peak_kwp", "pv_forecast_reference_kwp"):
                if cfg[key] is not None:
                    cfg[key] = _value(cfg[key], key, .1, 1000)
                continue
            cfg[key] = _value(cfg[key], key)
    if cfg["pv_forecast_mode"] not in ("whole_system", "specific_profile"):
        raise ValueError("invalid_pv_forecast_mode")
    if not (1 <= cfg["capacity_kwh"] <= 1000
            and 5 <= cfg["minimum_soc_lower_bound"] <= cfg["minimum_soc_percent"] <= 90
            and cfg["minimum_soc_percent"] < cfg["grid_max_soc_percent"] <= 95
            and 0 <= cfg["margin_soc_percent"] <= 20
            and 45 <= cfg["winter_weather_soc_percent"] <= 95
            and (target_only and cfg["battery_charge_max_a"] is None
                 or cfg["battery_charge_max_a"] is not None and 0 <= cfg["battery_charge_max_a"] <= 1000)
            and (target_only and cfg["grid_current_max_a"] is None
                 or cfg["grid_current_max_a"] is not None and 0 <= cfg["grid_current_max_a"] <= 1000)
            and (target_only and cfg["battery_voltage_v"] is None
                 or cfg["battery_voltage_v"] is not None and 40 <= cfg["battery_voltage_v"] <= 65)):
        raise ValueError("invalid_soc_configuration")
    for key in ("eta_charge", "eta_discharge", "eta_ac_dc", "eta_dc_ac"):
        if not .01 <= cfg[key] <= 1:
            raise ValueError("invalid_" + key)
    if not (0 <= cfg["discharge_max_kw"] <= 100
            and 0 < cfg["grid_import_max_kw"] <= 100
            and 0 <= cfg["grid_export_max_kw"] <= 100
            and 0 < cfg["inverter_max_kw"] <= 100):
        raise ValueError("invalid_power_configuration")
    # Both current inputs are validated live limits, never the old fixed kW
    # option. Total charging shares the Deye/BMS budget between PV and grid;
    # the separate grid setting may impose a lower grid-only ceiling.
    # These are DC terminal powers. Conversion and storage efficiencies are
    # each applied exactly once in _simulate. Target-only fallback invents no
    # measured current or voltage and returns no energy projection.
    cfg["battery_charge_max_kw"] = (min(cfg["inverter_max_kw"],
                                        cfg["battery_voltage_v"] * cfg["battery_charge_max_a"] / 1000)
                                    if cfg["battery_voltage_v"] is not None and cfg["battery_charge_max_a"] is not None else 0.)
    cfg["grid_charge_max_kw"] = (min(cfg["battery_charge_max_kw"],
                                     cfg["battery_voltage_v"] * cfg["grid_current_max_a"] / 1000)
                                 if cfg["battery_voltage_v"] is not None and cfg["grid_current_max_a"] is not None else 0.)
    return cfg


def _winter(dt):
    return dt.month in (10, 11, 12, 1, 2, 3)


def _protected(dt):
    return 7 <= dt.hour < 13 or (16 <= dt.hour < 21 if _winter(dt)
                                 else 19 <= dt.hour < 22)


def _deadlines(now, zone):
    result = []
    for day in range(4):
        date = now.date() + timedelta(days=day)
        afternoon = 16 if date.month in (10, 11, 12, 1, 2, 3) else 19
        for key, hour in (("night", 7), ("peak", afternoon)):
            at = datetime.combine(date, datetime.min.time(), tzinfo=zone).replace(hour=hour)
            if at.timestamp() > now.timestamp():
                end = at.replace(hour=13 if key == "night" else 21 if _winter(at) else 22)
                result.append({"key": key, "at": at, "end": end})
    return sorted(result, key=lambda item: item["at"].timestamp())


def _forecast(inputs, now, cfg):
    installed, reference = cfg["pv_peak_kwp"], cfg["pv_forecast_reference_kwp"]
    specific = cfg["pv_forecast_mode"] == "specific_profile"
    if installed is None or specific and reference is None:
        raise ValueError("pv_capacity_missing")
    rows = inputs.get("forecast")
    if not isinstance(rows, (list, tuple)) or len(rows) != 96:
        raise ValueError("incomplete_48h_forecast")
    start = int(now.timestamp() // 1800) * 1800
    result = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("invalid_forecast_row")
        at = _time(row.get("timestamp"), cfg["zone"])
        if abs(at.timestamp() - (start + i * 1800)) > .1:
            raise ValueError("stale_or_discontinuous_forecast_axis")
        p10 = _value(row.get("pv_p10_kw"), "pv_p10_kw", high=1000)
        p50 = _value(row.get("pv_p50_kw"), "pv_p50_kw", high=1000)
        load = _value(row.get("load_kw"), "load_kw", high=1000)
        if p10 > p50 + 1e-7:
            raise ValueError("pv_p10_exceeds_p50")
        if p50 > (reference if specific else installed) * 1.5 + 1e-7:
            raise ValueError("forecast_capacity_mismatch")
        # A correctly configured site-specific source already embeds capacity.
        # Normalize only when the user explicitly selects specific-profile mode.
        if specific:
            p10, p50 = p10 / reference * installed, p50 / reference * installed
        result.append({"timestamp": at.isoformat(), "epoch": at.timestamp(),
                       "pv_p10_kw": p10, "pv_p50_kw": p50, "load_kw": load})
    return result


def _prefix_need(rows, item, cfg):
    debt = maximum = 0.
    begin, end = item["at"].timestamp(), item["end"].timestamp()
    for row in rows:
        hours = max(0., min(row.get("end_epoch", row["epoch"] + 1800), end) - max(row["epoch"], begin)) / 3600
        deficit = row["load_kw"] / cfg["eta_dc_ac"] - row["pv_p10_kw"]
        debt += (deficit / cfg["eta_discharge"] if deficit >= 0 else
                 -min(-deficit, cfg["battery_charge_max_kw"]) * cfg["eta_charge"]) * hours
        maximum = max(maximum, debt)
    return maximum


def _weather(rows, item, cfg):
    begin = item["at"].timestamp()
    end = begin + 86400
    clear = cfg["minimum_soc_percent"] + cfg["margin_soc_percent"]
    weak = max(cfg["winter_weather_soc_percent"], clear)
    if rows[-1].get("end_epoch", rows[-1]["epoch"] + 1800) < end:
        # Tail projection only: no invented post-horizon PV. The two public
        # upcoming deadlines always have the full following 24h in the input.
        return weak, None, "tail_conservative_weather"
    pv = load = 0.
    for row in rows:
        hours = max(0., min(row.get("end_epoch", row["epoch"] + 1800), end) - max(row["epoch"], begin)) / 3600
        pv += row["pv_p50_kw"] * cfg["eta_dc_ac"] * hours
        load += row["load_kw"] * hours
    coverage = pv / load if load > 0 else 1.
    strength = min(1., max(0., (coverage - .5) / .5))
    return weak - (weak - clear) * strength, coverage, "weather_and_protected_energy"


def _simulate(rows, now, soc, cfg, targets=None, quantile="pv_p10_kw"):
    energy = soc / 100 * cfg["capacity_kwh"]
    floor = cfg["minimum_soc_percent"] / 100 * cfg["capacity_kwh"]
    totals = dict(import_kwh=0., export_kwh=0., protected_import_kwh=0.,
                  grid_charge_kwh=0., throughput_kwh=0., curtailed_kwh=0.,
                  grid_limit_excess_kwh=0., minimum_soc_percent=soc,
                  maximum_soc_percent=soc)
    output, observations = [], {}
    for row in rows:
        ts = max(row["epoch"], now.timestamp())
        row_end = row.get("end_epoch", row["epoch"] + 1800)
        hours = (row_end - ts) / 3600
        if hours <= 0:
            continue
        dt = datetime.fromtimestamp(ts, cfg["zone"])
        protected = row.get("tariff_protected", _protected(dt))
        forthcoming = next((t for t in targets or [] if t["at"].timestamp() > ts), None)
        charge_allowed = (not protected and forthcoming is not None
                          and forthcoming["grid_charge_allowed"])
        threshold = (forthcoming["soc_percent"] / 100 * cfg["capacity_kwh"]
                     if charge_allowed else floor)
        before = energy
        pv = row[quantile]
        pv_load = min(row["load_kw"], pv * cfg["eta_dc_ac"], cfg["inverter_max_kw"])
        surplus = max(pv - pv_load / cfg["eta_dc_ac"], 0.)
        pv_charge = min(surplus, cfg["battery_charge_max_kw"],
                        max(cfg["capacity_kwh"] - energy, 0.) / cfg["eta_charge"] / hours)
        energy += pv_charge * cfg["eta_charge"] * hours
        deficit = max(row["load_kw"] - pv_load, 0.)
        discharge = min(deficit / cfg["eta_dc_ac"], cfg["discharge_max_kw"],
                        max(energy - threshold, 0.) * cfg["eta_discharge"] / hours,
                        max(cfg["inverter_max_kw"] - pv_load, 0.) / cfg["eta_dc_ac"])
        energy -= discharge / cfg["eta_discharge"] * hours
        grid_load = max(deficit - discharge * cfg["eta_dc_ac"], 0.)
        grid_charge = 0.
        if charge_allowed:
            remaining = (forthcoming["at"].timestamp() - ts) / 3600
            paced = max(threshold - energy, 0.) / cfg["eta_charge"] / remaining
            grid_charge = min(paced, cfg["grid_charge_max_kw"],
                              max(cfg["battery_charge_max_kw"] - pv_charge, 0.),
                              max(cfg["grid_import_max_kw"] - grid_load, 0.) * cfg["eta_ac_dc"],
                              max(cfg["inverter_max_kw"] - grid_load, 0.) * cfg["eta_ac_dc"])
            energy += grid_charge * cfg["eta_charge"] * hours
        imported = grid_load + grid_charge / cfg["eta_ac_dc"]
        exported = min(max(surplus - pv_charge, 0.) * cfg["eta_dc_ac"],
                       cfg["grid_export_max_kw"], max(cfg["inverter_max_kw"] - pv_load, 0.))
        totals["import_kwh"] += imported * hours
        totals["export_kwh"] += exported * hours
        totals["protected_import_kwh"] += imported * hours if protected else 0.
        totals["grid_charge_kwh"] += grid_charge * hours
        totals["throughput_kwh"] += (pv_charge + grid_charge + discharge) * hours
        totals["curtailed_kwh"] += max(surplus - pv_charge - exported / cfg["eta_dc_ac"], 0.) * hours
        totals["grid_limit_excess_kwh"] += max(imported - cfg["grid_import_max_kw"], 0.) * hours
        final_soc = energy / cfg["capacity_kwh"] * 100
        totals["minimum_soc_percent"] = min(totals["minimum_soc_percent"], final_soc)
        totals["maximum_soc_percent"] = max(totals["maximum_soc_percent"], final_soc)
        output.append(dict(timestamp=row["timestamp"], duration_h=hours,
                           pv_kw=pv, load_kw=row["load_kw"], soc_percent=final_soc,
                           grid_import_kw=imported, grid_export_kw=exported,
                           grid_charge_kw=grid_charge, pv_charge_kw=pv_charge,
                           battery_discharge_kw=discharge, protected=protected))
        if "tariff_protected" in row:
            output[-1].update(timestamp=datetime.fromtimestamp(ts, cfg["zone"]).isoformat(),
                              end=datetime.fromtimestamp(row_end, cfg["zone"]).isoformat(),
                              soc_start_percent=before / cfg["capacity_kwh"] * 100)
        for target in targets or []:
            key = target["at"].isoformat()
            observed = observations.setdefault(key, {"deadline_soc_percent": None,
                                                     "minimum_soc_percent": 100.,
                                                     "protected_import_kwh": 0.})
            if abs(row_end - target["at"].timestamp()) < .1:
                observed["deadline_soc_percent"] = final_soc
            if target["at"].timestamp() <= row["epoch"] < target["end"].timestamp():
                observed["minimum_soc_percent"] = min(observed["minimum_soc_percent"],
                                                        before / cfg["capacity_kwh"] * 100, final_soc)
                observed["protected_import_kwh"] += imported * hours
    totals["final_soc_percent"] = energy / cfg["capacity_kwh"] * 100
    totals["zero_import_feasible"] = totals["import_kwh"] <= TOLERANCE_KWH
    return totals, output, observations


def _public(target):
    return {k: v for k, v in target.items() if k not in ("at", "end", "key")}


def _cache_time(value, zone):
    if not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value):
        try:
            return datetime.fromtimestamp(value, zone)
        except (ValueError, OverflowError, OSError):
            raise ValueError("invalid_cache_timestamp") from None
    return _time(value, zone)


def _cached_target(record, item, now, cfg):
    """Accept only original, dated own-plan records for this exact target."""
    if (not isinstance(record, dict) or record.get("source") != "own_deterministic_planner"
            or record.get("unreachable") is not False):
        return None
    try:
        if record.get("pv_forecast_mode") != cfg["pv_forecast_mode"]:
            return None
        for key in ("pv_peak_kwp", "pv_forecast_reference_kwp"):
            if key == "pv_forecast_reference_kwp" and cfg[key] is None and cfg["pv_forecast_mode"] == "whole_system":
                if key not in record or record[key] is not None:
                    return None
                continue
            if cfg[key] is None or _value(record.get(key), "cached_" + key, .1, 1000) != cfg[key]:
                return None
        percent = _value(record.get("soc_percent"), "cached_soc_percent",
                         cfg["minimum_soc_percent"], cfg["grid_max_soc_percent"])
        if (percent != cfg["minimum_soc_percent"] or _winter(now)) and percent < cfg["minimum_soc_percent"] + cfg["margin_soc_percent"]:
            return None
        deadline = _cache_time(record.get("deadline"), cfg["zone"])
        created = _cache_time(record.get("generated_at"), cfg["zone"])
        if (deadline.timestamp() != item["at"].timestamp()
                or not 0 <= now.timestamp() - created.timestamp() <= 86400
                or created.timestamp() >= deadline.timestamp()
                or record.get("season") != ("winter" if _winter(now) else "summer")
                or _winter(created) != _winter(now)):
            return None
        origin = next(t for t in _deadlines(created, cfg["zone"]) if t["key"] == item["key"])
        if origin["at"].timestamp() != deadline.timestamp():
            return None
        expected_emergency = not _winter(now) and percent > cfg["minimum_soc_percent"]
        if (record.get("emergency") is not expected_emergency
                or record.get("grid_charge_allowed") is not (_winter(now) or expected_emergency)):
            return None
        result = dict(record)
        result.update(selection_source="validated_cache", reason="dated_same_deadline_cache")
        return result
    except (ValueError, TypeError, StopIteration):
        return None


def _fallback(now, cfg, inputs, reason):
    winter = _winter(now)
    retained = inputs.get("retained_targets", {})
    targets = {}
    for item in _deadlines(now, cfg["zone"]):
        key = item["key"]
        if key in targets:
            continue
        prior = retained.get(key) if isinstance(retained, dict) else None
        cached = _cached_target(prior, item, now, cfg)
        if cached is not None:
            targets[key] = cached
            if len(targets) == 2:
                break
            continue
        # A caller may retain an actual winter hardware setting as a number.
        # It can only raise the conservative fallback; it is never a cache.
        if isinstance(prior, dict):
            prior = None
        if isinstance(prior, bool) or not isinstance(prior, (int, float)) or not math.isfinite(prior):
            prior = 0
        percent = (min(cfg["grid_max_soc_percent"], max(cfg["winter_weather_soc_percent"], cfg["minimum_soc_percent"] + cfg["margin_soc_percent"], prior))
                   if winter else cfg["grid_max_soc_percent"])
        targets[key] = dict(soc_percent=percent, deadline=item["at"].isoformat(),
                            protected_until=item["end"].isoformat(), emergency=not winter,
                            grid_charge_allowed=True, unreachable=True,
                            required_soc_percent=None, reason="unverified_fallback",
                            source="own_conservative_fallback", generated_at=now.isoformat(),
                            pv_peak_kwp=cfg["pv_peak_kwp"],
                            pv_forecast_reference_kwp=cfg["pv_forecast_reference_kwp"],
                            pv_forecast_mode=cfg["pv_forecast_mode"],
                            season="winter" if winter else "summer",
                            selection_source="conservative_fallback")
        if len(targets) == 2:
            break
    nearest = min(targets.values(), key=lambda t: _cache_time(t["deadline"], cfg["zone"]).timestamp())
    return dict(status="fallback", quality="invalid", reason=reason,
                source="own_conservative_fallback", generated_at=now.isoformat(),
                season="winter" if winter else "summer", targets=targets, rows=[],
                p10=None, p50=None, unreachable=True,
                summer_emergency_window=None if winter else dict(
                    active=not _protected(now) and nearest["emergency"], deadline=nearest["deadline"],
                    soc_percent=nearest["soc_percent"], reason=nearest["reason"]),
                assumptions=["Fallback is not a forecast or confirmation of feasibility"])


def plan_energy(inputs: dict) -> dict:
    """Build reproducible deadline decisions and physical forward projections.

    It is a forecast-based receding-horizon heuristic, not global optimization.
    Forward rows pace grid charging to the deadline; a separate live controller
    must apply AC/phase/BMS limits and verify all hardware writes.
    """
    if not isinstance(inputs, dict):
        inputs = {}
    if isinstance(inputs.get("config"), dict) and inputs["config"].get("tariff_profile", "legacy_g13") != "legacy_g13":
        return _plan_tariff(inputs)
    try:
        cfg = _settings(inputs.get("config", {}))
        now = _time(inputs.get("now"), cfg["zone"])
    except ValueError as exc:
        try:
            safe_config = {}
            raw_config = inputs.get("config", {})
            if isinstance(raw_config, dict):
                for name, lo, hi in (("minimum_soc_percent", 5, 90),
                                     ("minimum_soc_lower_bound", 5, 90),
                                     ("winter_weather_soc_percent", 45, 95),
                                     ("grid_max_soc_percent", 45, 95),
                                     ("margin_soc_percent", 0, 20),
                                     ("pv_peak_kwp", .1, 1000),
                                     ("pv_forecast_reference_kwp", .1, 1000)):
                    value = raw_config.get(name)
                    if (not isinstance(value, bool) and isinstance(value, (float, int))
                            and math.isfinite(value) and lo <= value <= hi):
                        safe_config[name] = value
            cfg = _settings(safe_config, target_only=True)
            now = _time(inputs.get("now"), cfg["zone"])
        except ValueError:
            return dict(status="fallback", quality="invalid", reason="invalid_clock",
                        source="own_conservative_fallback", generated_at=None,
                        season=None, targets={}, rows=[], p10=None, p50=None,
                        unreachable=True, summer_emergency_window=None)
        return _fallback(now, cfg, inputs, str(exc))
    try:
        soc = _value(inputs.get("soc_percent"), "soc_percent", high=100)
        if inputs.get("soc_valid", True) is not True:
            raise ValueError("invalid_soc_freshness")
        if "soc_updated_at" in inputs:
            age = now.timestamp() - _time(inputs["soc_updated_at"], cfg["zone"]).timestamp()
            voltage_age = (now.timestamp() - _time(inputs["voltage_updated_at"], cfg["zone"]).timestamp()
                           if "voltage_updated_at" in inputs else float("inf"))
            if age < 0 or not (age <= 1200 or 0 <= voltage_age <= 120):
                raise ValueError("stale_soc_without_bms_communication")
        if inputs.get("load_includes_heatpump", True) is not True:
            raise ValueError("load_must_include_heatpump_once")
        rows = _forecast(inputs, now, cfg)
        horizon_end = rows[-1]["epoch"] + 1800
        all_items = [t for t in _deadlines(now, cfg["zone"])
                     if t["end"].timestamp() <= horizon_end]
        if not all_items:
            raise ValueError("forecast_missing_protected_window")
        season_winter = _winter(now)
        # Solar-only observations deliberately precede emergency intervention.
        observation_items = [dict(t, soc_percent=cfg["minimum_soc_percent"], grid_charge_allowed=False)
                             for t in all_items]
        base10, base_rows10, observed = _simulate(rows, now, soc, cfg, observation_items)
        base50, _, _ = _simulate(rows, now, soc, cfg, observation_items, "pv_p50_kw")
        targets = []
        for item in all_items:
            need = _prefix_need(rows, item, cfg)
            energy_target = cfg["minimum_soc_percent"] + cfg["margin_soc_percent"] + need / cfg["capacity_kwh"] * 100
            observation = observed[item["at"].isoformat()]
            if _winter(item["at"]):
                weather, coverage, reason = _weather(rows, item, cfg)
                required = math.ceil(max(energy_target, weather) - 1e-7)
                emergency = False
                allowed = True
            else:
                weather = coverage = None
                emergency = (observation["protected_import_kwh"] > TOLERANCE_KWH
                             or observation["minimum_soc_percent"] < cfg["minimum_soc_percent"] + cfg["margin_soc_percent"] - 1e-7)
                required = math.ceil(energy_target - 1e-7) if emergency else cfg["minimum_soc_percent"]
                allowed = emergency
                reason = ("predicted_protected_import" if observation["protected_import_kwh"] > TOLERANCE_KWH
                          else "predicted_buffer_deficit" if emergency else "solar_reserve_sufficient")
            target = dict(item, soc_percent=min(required, cfg["grid_max_soc_percent"]),
                          required_soc_percent=required, deadline=item["at"].isoformat(),
                          protected_until=item["end"].isoformat(), emergency=emergency,
                          grid_charge_allowed=allowed, unreachable=required > cfg["grid_max_soc_percent"],
                          reason=reason, weather_target_percent=weather, pv_coverage=coverage,
                          maximum_prefix_deficit_kwh=need, generated_at=now.isoformat(),
                          pv_peak_kwp=cfg["pv_peak_kwp"],
                          pv_forecast_reference_kwp=cfg["pv_forecast_reference_kwp"],
                          pv_forecast_mode=cfg["pv_forecast_mode"],
                          season="winter" if _winter(now) else "summer",
                          source="own_deterministic_planner", selection_source="live_plan")
            targets.append(target)
        risk, _, checked = _simulate(rows, now, soc, cfg, targets)
        central, projection, _ = _simulate(rows, now, soc, cfg, targets, "pv_p50_kw")
        public = {}
        for target in targets:
            obs = checked[target["at"].isoformat()]
            deadline_soc = obs["deadline_soc_percent"]
            if target["grid_charge_allowed"] and (deadline_soc is None or deadline_soc + .01 < target["soc_percent"]):
                target["unreachable"] = True
                target["reason"] = "target_unreachable_before_deadline"
            if obs["protected_import_kwh"] > TOLERANCE_KWH:
                target["unreachable"] = True
                target["reason"] = "protected_energy_or_power_deficit"
            target["projected_p10_deadline_soc_percent"] = deadline_soc
            target["projected_p10_protected_import_kwh"] = obs["protected_import_kwh"]
            if target["key"] not in public:
                public[target["key"]] = _public(target)
        if set(public) != {"night", "peak"}:
            raise ValueError("missing_next_night_or_peak_deadline")
        unreachable = (any(t["unreachable"] for t in public.values())
                       or risk["protected_import_kwh"] > TOLERANCE_KWH
                       or risk["grid_limit_excess_kwh"] > TOLERANCE_KWH)
        nearest = min(public.values(), key=lambda t: _time(t["deadline"], cfg["zone"]).timestamp())
        return dict(status="unreachable" if unreachable else "ok", quality="valid",
                    reason="forecast_energy_or_power_deficit" if unreachable else "planned",
                    source="own_deterministic_planner", generated_at=now.isoformat(),
                    season="winter" if season_winter else "summer", targets=public,
                    rows=projection, p10=risk, p50=central,
                    forecast_normalization=dict(installed_kwp=cfg["pv_peak_kwp"],
                        reference_kwp=cfg["pv_forecast_reference_kwp"],
                        mode=cfg["pv_forecast_mode"],
                        factor=(cfg["pv_peak_kwp"] / cfg["pv_forecast_reference_kwp"]
                                if cfg["pv_forecast_mode"] == "specific_profile" else 1.),
                        input_unit="whole_system_kw"),
                    warnings=(["pv_reference_differs_whole_system_not_scaled"]
                              if cfg["pv_forecast_mode"] == "whole_system" and cfg["pv_forecast_reference_kwp"] is not None
                              and cfg["pv_forecast_reference_kwp"] != cfg["pv_peak_kwp"] else []),
                    baseline_p10=base10, baseline_p50=base50,
                    unreachable=unreachable, summer_emergency_window=None if season_winter else dict(
                        active=not _protected(now) and nearest["emergency"],
                        deadline=nearest["deadline"], soc_percent=nearest["soc_percent"],
                        reason=nearest["reason"]),
                    assumptions=["Deterministic P10/P50 scenarios, not a statistical guarantee",
                                 "PV serves LOAD then battery to physical100% then surplus export",
                                 "Grid charge only in cheap windows; no grid charging for export",
                                 "Phase LOAD is not forecast; live AC/phase/BMS limits and device ACK belong to the controller",
                                 "Grid DC charging power uses live battery voltage times the validated dynamic current limit; AC/DC and storage efficiencies each apply once",
                                 "Without a future native LOAD/CT-branch split, the entire forecast house demand conservatively reserves inverter GRID-import headroom",
                                 "Whole-system PV is unchanged; only explicit specific-profile mode normalizes by reference then multiplies by installed kWp; raw peak1.5x nominal is a sanity assumption",
                                 "Beyond complete24h weather coverage, winter tail uses the configured weak-PV target conservatively"])
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return _fallback(now, cfg, inputs, str(exc))


def tariff_context(now, options):
    """Fail-closed calendar boundary; a bad real profile never becomes legacy."""
    try:
        return calendar_context(now, options)
    except (ValueError, TypeError, KeyError, OverflowError):
        return dict(valid=False, issue="invalid_tariff_configuration", metadata={},
                    current_interval=None, charge_window=None, next_charge_window=None,
                    protected_windows=[], deadlines=[], next_deadline=None)


def tariff_identity(options, context):
    metadata = context.get("metadata", {})
    return dict(tariff_profile=options.get("tariff_profile", "legacy_g13"),
                tariff_clock_basis=options.get("tariff_clock_basis", "local"),
                tariff_version=metadata.get("version"))


def tariff_target_items(now, options, *, horizon_end=None):
    """Reserve deadlines are the starts of complete noncheap periods.

    An all-cheap period still needs an outage/weather reserve. Its explicitly
    labelled next-07:00 checkpoint belongs to the planner, not to the OSD.
    """
    context = tariff_context(now, options)
    if context.get("valid") is not True:
        return []
    result = []
    for row in context.get("protected_windows", []):
        at, end = _time(row["start"], now.tzinfo), _time(row["end"], now.tzinfo)
        if at.timestamp() <= now.timestamp():
            continue
        if horizon_end is not None and end.timestamp() > horizon_end:
            continue
        result.append(dict(key=f"tariff_{int(at.timestamp())}", at=at, end=end,
                           virtual_checkpoint=False))
    result.sort(key=lambda item: item["at"].timestamp())
    if horizon_end is None:
        result = result[:4]
    # During a long all-cheap weekend, the next real deadline can fall outside
    # the 48h forecast. Do not invent post-horizon energy to size its reserve.
    if not result or (horizon_end is None and result[0]["at"].timestamp() - now.timestamp() > 86400):
        at = now.replace(hour=7, minute=0, second=0, microsecond=0)
        if at.timestamp() <= now.timestamp():
            at += timedelta(days=1)
        result.insert(0, dict(key=f"tariff_{int(at.timestamp())}", at=at,
                              end=at + timedelta(days=1), virtual_checkpoint=True))
    return result


def physical_tariff_tou(now, options):
    """Compile one circular day to six strictly increasing Deye start clocks.

    Operator intervals remain separate. Identical first/last classes are one
    circular interval, so six transitions do not become seven at midnight.
    Padding splits only an existing interval and never changes eligibility.
    """
    context = tariff_context(now, options)
    if context.get("valid") is not True:
        return dict(valid=False, issue=context.get("issue") or "invalid_tariff", rows=[])
    try:
        day = describe_calendar(now, options.get("tariff_profile", "legacy_g13"),
                                options.get("tariff_clock_basis", "local"))["today"]
        rows = []
        for row in day:
            at = _time(row["start"], now.tzinfo)
            minute = at.hour * 60 + at.minute
            kind = (row["zone"], row.get("tier"), row["grid_charge_allowed"])
            if rows and rows[-1]["kind"] == kind:
                continue
            rows.append(dict(minute=minute, kind=kind))
        if len(rows) > 1 and rows[0]["kind"] == rows[-1]["kind"]:
            rows.pop(0)
        if not rows or len(rows) > 6 or len({r["minute"] for r in rows}) != len(rows):
            raise ValueError("tariff_exceeds_six_tou_slots")
        while len(rows) < 6:
            ordered = sorted(rows, key=lambda r: r["minute"])
            spans = [((ordered[(i + 1) % len(ordered)]["minute"] - r["minute"]) % 1440 or 1440, r)
                     for i, r in enumerate(ordered)]
            length, largest = max(spans, key=lambda pair: (pair[0], -pair[1]["minute"]))
            if length < 2:
                raise ValueError("tariff_exceeds_six_tou_slots")
            rows.append(dict(minute=(largest["minute"] + length // 2) % 1440,
                             kind=largest["kind"], padding=True))
        rows.sort(key=lambda r: r["minute"])
        output = [dict(slot=index, time=f"{r['minute']//60:02}:{r['minute']%60:02}:00",
                       zone=r["kind"][0], tier=r["kind"][1], grid_charge_allowed=r["kind"][2],
                       padding=r.get("padding", False), minute=r["minute"])
                  for index, r in enumerate(rows, 1)]
        minute = now.hour * 60 + now.minute + now.second / 60
        active = next((r["slot"] for r in reversed(output) if r["minute"] <= minute), 6)
        return dict(valid=True, issue=None, rows=output, active_slot=active,
                    **tariff_identity(options, context))
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        return dict(valid=False, issue=str(error), rows=[])


def _tariff_forecast(rows, now, options):
    result = []
    for row in rows:
        begin = max(row["epoch"], now.timestamp())
        end = row["epoch"] + 1800
        if begin >= end:
            continue
        for interval in intervals_between(datetime.fromtimestamp(begin, now.tzinfo),
                datetime.fromtimestamp(end, now.tzinfo), options["tariff_profile"],
                options.get("tariff_clock_basis", "local")):
            if interval.get("within_validity", True) is not True:
                raise ValueError("tariff_forecast_outside_validity")
            a, b = interval["start_ts"], interval["end_ts"]
            result.append({**row, "epoch": a, "end_epoch": b,
                           "timestamp": datetime.fromtimestamp(a, now.tzinfo).isoformat(),
                           "tariff_protected": interval["grid_charge_allowed"] is not True})
    return result


def _tariff_cache(record, item, now, cfg, identity):
    if (not isinstance(record, dict) or any(record.get(k) != v for k, v in identity.items())
            or record.get("source") != "own_deterministic_planner"
            or record.get("unreachable") is not False):
        return None
    try:
        value = _value(record.get("soc_percent"), "cached_soc", cfg["minimum_soc_percent"], cfg["grid_max_soc_percent"])
        created = _time(record.get("generated_at"), now.tzinfo)
        deadline = _time(record.get("deadline"), now.tzinfo)
        if (deadline.timestamp() != item["at"].timestamp() or not 0 <= now.timestamp() - created.timestamp() <= 86400
                or created.timestamp() >= deadline.timestamp() or record.get("protected_until") != item["end"].isoformat()
                or record.get("season") != ("winter" if _winter(now) else "summer")
                or record.get("pv_forecast_mode") != cfg["pv_forecast_mode"]
                or any(record.get(key) != cfg[key] for key in ("pv_peak_kwp", "pv_forecast_reference_kwp"))
                or not isinstance(record.get("emergency"), bool)
                or not isinstance(record.get("grid_charge_allowed"), bool)
                or value < cfg["minimum_soc_percent"] + cfg["margin_soc_percent"]
                    and (_winter(now) or value != cfg["minimum_soc_percent"] or record["emergency"])):
            return None
        return {**record, "selection_source": "validated_cache"}
    except (ValueError, TypeError, KeyError):
        return None


def tariff_slot_targets(now, options, plan, soc, reserve):
    """Logical operator rows, with nullable forecasts and separate charge goals."""
    try:
        calendar = describe_calendar(now, options.get("tariff_profile", "legacy_g13"),
                                     options.get("tariff_clock_basis", "local"))
    except (ValueError, TypeError, KeyError):
        return []
    targets = sorted((t for t in plan.get("targets", {}).values() if isinstance(t, dict)),
                     key=lambda t: _time(t["deadline"], now.tzinfo).timestamp())
    projection = plan.get("rows", []) if plan.get("quality") == "valid" else []
    def projected(at):
        if not projection:
            return None
        if at == now.timestamp() and isinstance(soc, (int, float)) and not isinstance(soc, bool):
            return soc
        for row in projection:
            a = _time(row["timestamp"], now.tzinfo).timestamp()
            b = a + row["duration_h"] * 3600
            if a <= at <= b and row.get("soc_start_percent") is not None:
                return row["soc_start_percent"] + (row["soc_percent"] - row["soc_start_percent"]) * (at-a)/(b-a)
        return None
    result = []
    for interval in [*calendar["today"], *calendar["tomorrow"]]:
        start, end = _time(interval["start"], now.tzinfo).timestamp(), _time(interval["end"], now.tzinfo).timestamp()
        past = end <= now.timestamp()
        begin = max(now.timestamp(), start)
        selected = next((t for t in targets if _time(t["deadline"], now.tzinfo).timestamp() >= begin), None)
        a, b = (None, None) if past else (projected(begin), projected(end))
        if start <= now.timestamp() < end and soc is None:
            a = b = None
        fallback = plan.get("quality") != "valid"
        result.append(dict(start=interval["start"], end=interval["end"], zone=interval["zone"],
            tier=interval.get("tier"), grid_charge_allowed=interval["grid_charge_allowed"],
            charge_target_soc_percent=(selected.get("soc_percent") if selected and not past
                                       and interval["grid_charge_allowed"] else None),
            reserve_soc_percent=reserve, projected_soc_start_percent=a,
            projected_soc_end_percent=b, projection_from=None if past or a is None else datetime.fromtimestamp(begin, now.tzinfo).isoformat(),
            deadline=selected.get("deadline") if selected and not past else None,
            quality="past" if past else "fallback" if fallback and selected else "forecast" if a is not None and b is not None else "unavailable",
            reason="past_interval" if past else "conservative_target_no_projection" if fallback and selected else
                   "forecast_projection" if a is not None and b is not None else "outside_complete_forecast"))
    return result


def _plan_tariff(inputs):
    raw = inputs.get("config", {})
    try:
        now = _time(inputs.get("now"), ZoneInfo(raw.get("timezone", "Europe/Warsaw")))
    except (ValueError, TypeError, KeyError):
        return dict(status="fallback", quality="invalid", reason="invalid_clock", generated_at=None,
                    source="own_conservative_fallback", targets={}, rows=[], p10=None, p50=None,
                    tariff_slot_targets=[], unreachable=True)
    context = tariff_context(now, raw)
    identity = tariff_identity(raw, context)
    try:
        cfg = _settings(raw)
    except ValueError:
        try:
            cfg = _settings(raw, target_only=True)
        except ValueError:
            cfg = _settings({}, target_only=True)
    def fallback(reason):
        targets = {}
        if context.get("valid") is True:
            for item in tariff_target_items(now, raw):
                cached = _tariff_cache(inputs.get("retained_targets", {}).get(item["key"]), item, now, cfg, identity)
                targets[item["key"]] = cached or dict(soc_percent=min(cfg["grid_max_soc_percent"],
                    max(cfg["winter_weather_soc_percent"], cfg["minimum_soc_percent"] + cfg["margin_soc_percent"]))
                    if _winter(now) else cfg["grid_max_soc_percent"], deadline=item["at"].isoformat(),
                    protected_until=item["end"].isoformat(), virtual_checkpoint=item["virtual_checkpoint"],
                    emergency=not _winter(now), grid_charge_allowed=True, unreachable=True,
                    source="own_conservative_fallback", reason="unverified_fallback", generated_at=now.isoformat(),
                    season="winter" if _winter(now) else "summer", **identity,
                    **{k: cfg[k] for k in ("pv_forecast_mode", "pv_peak_kwp", "pv_forecast_reference_kwp")})
        result = dict(status="fallback", quality="invalid", reason=reason, generated_at=now.isoformat(),
            source="own_conservative_fallback", season="winter" if _winter(now) else "summer",
            targets=targets, rows=[], p10=None, p50=None, unreachable=True,
            summer_emergency_window=None, **identity)
        result["tariff_slot_targets"] = tariff_slot_targets(now, raw, result, inputs.get("soc_percent"), cfg["minimum_soc_percent"])
        return result
    if context.get("valid") is not True:
        return fallback(context.get("issue") or "invalid_tariff_configuration")
    try:
        cfg = _settings(raw)
        soc = _value(inputs.get("soc_percent"), "soc_percent", high=100)
        if inputs.get("soc_valid", True) is not True:
            raise ValueError("invalid_soc_freshness")
        if "soc_updated_at" in inputs:
            age = now.timestamp() - _time(inputs["soc_updated_at"], cfg["zone"]).timestamp()
            voltage_age = (now.timestamp() - _time(inputs["voltage_updated_at"], cfg["zone"]).timestamp()
                           if "voltage_updated_at" in inputs else float("inf"))
            if age < 0 or not (age <= 1200 or 0 <= voltage_age <= 120):
                raise ValueError("stale_soc_without_bms_communication")
        if inputs.get("load_includes_heatpump", True) is not True:
            raise ValueError("load_must_include_heatpump_once")
        rows = _tariff_forecast(_forecast(inputs, now, cfg), now, raw)
        horizon = rows[-1]["end_epoch"]
        items = tariff_target_items(now, raw, horizon_end=horizon)
        baseline_items = [dict(t, soc_percent=cfg["minimum_soc_percent"], grid_charge_allowed=False) for t in items]
        base10, _, observed = _simulate(rows, now, soc, cfg, baseline_items)
        base50, _, _ = _simulate(rows, now, soc, cfg, baseline_items, "pv_p50_kw")
        targets = []
        for item in items:
            need = _prefix_need(rows, item, cfg)
            energy = cfg["minimum_soc_percent"] + cfg["margin_soc_percent"] + need/cfg["capacity_kwh"]*100
            observation = observed[item["at"].isoformat()]
            weather, coverage, reason = _weather(rows, item, cfg) if _winter(item["at"]) else (None, None, "solar_reserve_sufficient")
            emergency = (not _winter(item["at"]) and (observation["protected_import_kwh"] > TOLERANCE_KWH
                         or observation["minimum_soc_percent"] < cfg["minimum_soc_percent"] + cfg["margin_soc_percent"] - 1e-7))
            required = math.ceil(max(energy, weather or 0)-1e-7) if _winter(item["at"]) or emergency else cfg["minimum_soc_percent"]
            targets.append(dict(item, soc_percent=min(required, cfg["grid_max_soc_percent"]),
                required_soc_percent=required, deadline=item["at"].isoformat(), protected_until=item["end"].isoformat(),
                emergency=emergency, grid_charge_allowed=_winter(item["at"]) or emergency,
                unreachable=required>cfg["grid_max_soc_percent"], reason="predicted_buffer_deficit" if emergency else reason,
                weather_target_percent=weather, pv_coverage=coverage, maximum_prefix_deficit_kwh=need,
                source="own_deterministic_planner", selection_source="live_plan", generated_at=now.isoformat(),
                season="winter" if _winter(now) else "summer", **identity,
                **{k: cfg[k] for k in ("pv_forecast_mode", "pv_peak_kwp", "pv_forecast_reference_kwp")}))
        risk, _, checked = _simulate(rows, now, soc, cfg, targets)
        central, projection, _ = _simulate(rows, now, soc, cfg, targets, "pv_p50_kw")
        public = {}
        for target in targets:
            obs = checked[target["at"].isoformat()]
            reached = obs["deadline_soc_percent"]
            if target["grid_charge_allowed"] and (reached is None or reached + .01 < target["soc_percent"]):
                target.update(unreachable=True, reason="target_unreachable_before_deadline")
            if obs["protected_import_kwh"] > TOLERANCE_KWH:
                target.update(unreachable=True, reason="protected_energy_or_power_deficit")
            target.update(projected_p10_deadline_soc_percent=reached,
                          projected_p10_protected_import_kwh=obs["protected_import_kwh"])
            public[target["key"]] = _public(target)
        unreachable = any(t["unreachable"] for t in public.values()) or risk["protected_import_kwh"] > TOLERANCE_KWH or risk["grid_limit_excess_kwh"] > TOLERANCE_KWH
        summary = list(public.values())
        result = dict(status="unreachable" if unreachable else "ok", quality="valid", reason="forecast_energy_or_power_deficit" if unreachable else "planned",
            source="own_deterministic_planner", generated_at=now.isoformat(), season="winter" if _winter(now) else "summer",
            targets=public, target_summary={"night": summary[0], "peak": summary[min(1,len(summary)-1)]} if summary else {},
            rows=projection, p10=risk, p50=central, baseline_p10=base10, baseline_p50=base50,
            unreachable=bool(unreachable), summer_emergency_window=None,
            assumptions=["Tariff eligibility is separate from BMS, reserve and physical device acknowledgement",
                         "A virtual weather checkpoint is a planning boundary, not an operator tariff slot"], **identity)
        result["tariff_slot_targets"] = tariff_slot_targets(now, raw, result, soc, cfg["minimum_soc_percent"])
        return result
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        return fallback(str(error))
