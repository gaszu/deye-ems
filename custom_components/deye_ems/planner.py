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

Outputs: status ok/unreachable/fallback, quality valid/invalid, generated_at,
season, targets night/peak, central projection rows and p10/p50 metrics.
They are model predictions and requested deadline targets, never device ACKs.
Invalid inputs return explicit fallback targets and EMPTY projections.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import math
from zoneinfo import ZoneInfo


DEFAULTS = {
    "timezone": "Europe/Warsaw", "capacity_kwh": 66.0,
    "minimum_soc_percent": 40.0, "margin_soc_percent": 5.0,
    "winter_weather_soc_percent": 75.0,
    "grid_max_soc_percent": 95.0, "charge_max_kw": 5.3,
    "grid_current_max_a": 108.0,
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


def _settings(raw):
    if not isinstance(raw, dict):
        raise ValueError("invalid_config")
    cfg = dict(DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS})
    try:
        cfg["zone"] = ZoneInfo(cfg["timezone"])
    except (ValueError, TypeError, KeyError):
        raise ValueError("invalid_timezone") from None
    for key in DEFAULTS:
        if key not in ("timezone", "pv_forecast_mode"):
            if key in ("pv_peak_kwp", "pv_forecast_reference_kwp"):
                if cfg[key] is not None:
                    cfg[key] = _value(cfg[key], key, .1, 1000)
                continue
            cfg[key] = _value(cfg[key], key)
    if cfg["pv_forecast_mode"] not in ("whole_system", "specific_profile"):
        raise ValueError("invalid_pv_forecast_mode")
    if not (1 <= cfg["capacity_kwh"] <= 1000
            and 40 <= cfg["minimum_soc_percent"] <= 90
            and cfg["minimum_soc_percent"] < cfg["grid_max_soc_percent"] <= 95
            and 0 <= cfg["margin_soc_percent"] <= 20
            and 45 <= cfg["winter_weather_soc_percent"] <= 95
            and 0 <= cfg["grid_current_max_a"] <= 108):
        raise ValueError("invalid_soc_configuration")
    for key in ("eta_charge", "eta_discharge", "eta_ac_dc", "eta_dc_ac"):
        if not .01 <= cfg[key] <= 1:
            raise ValueError("invalid_" + key)
    if not (0 <= cfg["charge_max_kw"] <= 100 and 0 <= cfg["discharge_max_kw"] <= 100
            and 0 < cfg["grid_import_max_kw"] <= 100
            and 0 <= cfg["grid_export_max_kw"] <= 100
            and 0 < cfg["inverter_max_kw"] <= 100):
        raise ValueError("invalid_power_configuration")
    # 5.3 kW/108 A is the explicitly adopted grid-charger model, not a
    # measured conversion curve. A high PV charge limit never enlarges Grid.
    cfg["grid_charge_max_kw"] = min(cfg["charge_max_kw"], 5.3 * cfg["grid_current_max_a"] / 108)
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
        hours = max(0., min(row["epoch"] + 1800, end) - max(row["epoch"], begin)) / 3600
        deficit = row["load_kw"] / cfg["eta_dc_ac"] - row["pv_p10_kw"]
        debt += (deficit / cfg["eta_discharge"] if deficit >= 0 else
                 -min(-deficit, cfg["charge_max_kw"]) * cfg["eta_charge"]) * hours
        maximum = max(maximum, debt)
    return maximum


def _weather(rows, item, cfg):
    begin = item["at"].timestamp()
    end = begin + 86400
    clear = cfg["minimum_soc_percent"] + cfg["margin_soc_percent"]
    weak = max(cfg["winter_weather_soc_percent"], clear)
    if rows[-1]["epoch"] + 1800 < end:
        # Tail projection only: no invented post-horizon PV. The two public
        # upcoming deadlines always have the full following 24h in the input.
        return weak, None, "tail_conservative_weather"
    pv = load = 0.
    for row in rows:
        hours = max(0., min(row["epoch"] + 1800, end) - max(row["epoch"], begin)) / 3600
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
        hours = (row["epoch"] + 1800 - ts) / 3600
        if hours <= 0:
            continue
        dt = datetime.fromtimestamp(ts, cfg["zone"])
        protected = _protected(dt)
        forthcoming = next((t for t in targets or [] if t["at"].timestamp() > ts), None)
        charge_allowed = (not protected and forthcoming is not None
                          and forthcoming["grid_charge_allowed"])
        threshold = (forthcoming["soc_percent"] / 100 * cfg["capacity_kwh"]
                     if charge_allowed else floor)
        before = energy
        pv = row[quantile]
        pv_load = min(row["load_kw"], pv * cfg["eta_dc_ac"], cfg["inverter_max_kw"])
        surplus = max(pv - pv_load / cfg["eta_dc_ac"], 0.)
        pv_charge = min(surplus, cfg["charge_max_kw"],
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
                              max(cfg["charge_max_kw"] - pv_charge, 0.),
                              max(cfg["grid_import_max_kw"] - grid_load, 0.) * cfg["eta_ac_dc"])
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
        for target in targets or []:
            key = target["at"].isoformat()
            observed = observations.setdefault(key, {"deadline_soc_percent": None,
                                                     "minimum_soc_percent": 100.,
                                                     "protected_import_kwh": 0.})
            if abs(row["epoch"] + 1800 - target["at"].timestamp()) < .1:
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
    try:
        cfg = _settings(inputs.get("config", {}))
        now = _time(inputs.get("now"), cfg["zone"])
    except ValueError as exc:
        try:
            safe_config = {}
            raw_config = inputs.get("config", {})
            if isinstance(raw_config, dict):
                for name, lo, hi in (("minimum_soc_percent", 40, 90),
                                     ("winter_weather_soc_percent", 45, 95),
                                     ("margin_soc_percent", 0, 20),
                                     ("pv_peak_kwp", .1, 1000),
                                     ("pv_forecast_reference_kwp", .1, 1000)):
                    value = raw_config.get(name)
                    if (not isinstance(value, bool) and isinstance(value, (float, int))
                            and math.isfinite(value) and lo <= value <= hi):
                        safe_config[name] = value
            cfg = _settings(safe_config)
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
                                 "Grid charging uses the assumed5.3kW/108A model and the configured current cap",
                                 "Whole-system PV is unchanged; only explicit specific-profile mode normalizes by reference then multiplies by installed kWp; raw peak1.5x nominal is a sanity assumption",
                                 "Beyond complete24h weather coverage, winter tail uses the configured weak-PV target conservatively"])
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return _fallback(now, cfg, inputs, str(exc))
