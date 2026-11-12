"""Load-priority grid-charge limiter and deadline current ramp.

No Home Assistant calls.  This standalone standard-library module is bundled with the HA integration.
Measurements and the attempt ledger must
come from a single validated snapshot.  A proposed value is not a device ACK.

The balanced model is available only with the coordinator's explicit confirmed
Asymmetric Phase Feeding / Zero Export To Load signal. Otherwise the fallback
allows the whole incremental charger power on any phase. LOAD budgets ignore PV so
a sudden loss of PV cannot create additional charging headroom.
``load_w`` and ``load_phases_w`` are native LOAD measurements. Optional
``outside_load_w`` is additional demand outside LOAD: added once to the total
and conservatively once to each candidate phase budget, never to measured GRID.
"""
from __future__ import annotations

import math


ORDINARY_INTERVAL_SECONDS = 600
ORDINARY_RETRY_BACKOFF_SECONDS = 60
ORDINARY_DEADBAND_A = 5
ORDINARY_MAX_STEP_A = 20


def _number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def _vector(value):
    return (isinstance(value, (list, tuple)) and len(value) == 3
            and all(_number(v) for v in value))


def calculate_grid_charge_cap(g: dict) -> dict:
    """Return an instantaneous upper bound; never grant a time-based override."""
    balanced = g.get("grid_charge_balanced") is True
    result = dict(cap_a=0, planning_cap_a=0, bms_cap_a=0, converter_cap_a=0,
                  deye_cap_a=0, actuator_cap_a=0, inverter_port_planning_cap_a=0,
                  inverter_port_excess_w=None, connection_grid_excess_w=None,
                  inverter_port_within_limits=False,
                  hard_current_cap_a=0, feedback_cap_a=0,
                  grid_excess_w=None, grid_within_limits=False,
                  phase_model="balanced" if balanced else "conservative",
                  telemetry_ok=False, reason="telemetry_invalid", power_per_a_w=0.0)
    values = [g.get(k) for k in ("load_w", "grid_w", "battery_voltage_v", "current_a")]
    loads, grids = g.get("load_phases_w"), g.get("grid_phases_w")
    port, port_load = g.get("grid_port_w"), g.get("grid_port_load_w")
    ports, port_loads = g.get("grid_port_phases_w"), g.get("grid_port_load_phases_w")
    if not (g.get("telemetry_valid") is True and all(_number(v) for v in values)
            and all(_number(v) for v in (port, port_load))
            and _vector(loads) and _vector(grids) and _vector(ports) and _vector(port_loads)):
        return result
    load, grid, voltage, current = values
    if not (-200 <= load <= 60000 and -60000 <= grid <= 60000
            and all(-200 <= v <= 30000 for v in loads)
            and all(-30000 <= v <= 30000 for v in grids)
            and -60000 <= port <= 60000 and -200 <= port_load <= 60000
            and all(-30000 <= v <= 30000 for v in ports)
            and all(-200 <= v <= 30000 for v in port_loads)
            and 40 <= voltage <= 65 and 0 <= current <= 1000):
        return result
    total = g.get("total_limit_w", 12000)
    phase = g.get("phase_limit_w", 5000)
    margin = g.get("headroom_w", 500)
    phase_margin = g.get("phase_headroom_w", 250)
    eta = g.get("charge_efficiency", .9)
    storage_eta = g.get("charge_storage_efficiency", .95)
    bms = g.get("bms_cap_a", 0)
    deye, actuator = g.get("deye_cap_a"), g.get("actuator_cap_a")
    outside = g.get("outside_load_w", 0)
    converter_total = g.get("conversion_total_limit_w", 12000)
    converter_phase = g.get("conversion_phase_limit_w", 5000)
    port_total = g.get("inverter_grid_import_limit_w")
    port_phase = g.get("inverter_grid_phase_limit_w")
    if not (all(_number(v) for v in (total, phase, margin, phase_margin, eta, bms, outside,
                                     converter_total, converter_phase, deye, actuator,
                                     port_total, port_phase, storage_eta))
            and 0 < total <= 30000 and 0 < phase <= 15000
            and 0 <= margin < total and 0 <= phase_margin < phase
            and .5 <= eta <= 1 and 0 <= bms <= 1000 and 0 <= outside <= 60000
            and .5 <= storage_eta <= 1
            and 0 <= deye <= 1000 and 0 <= actuator <= 1000
            and margin < port_total <= 1000000 and phase_margin < port_phase <= 500000
            and 0 < converter_total <= 1000000 and 0 < converter_phase <= 500000):
        return result
    per_amp = voltage / eta
    whole_load = max(load, sum(max(v, 0) for v in loads), 0) + outside
    phase_budget = (3 * (phase - phase_margin) - whole_load if balanced else
                    phase - phase_margin - max(max(loads), 0) - outside)
    load_budget = min(total - margin - whole_load, phase_budget)
    grid_excess = max(grid - (total - margin), sum(grids) - (total - margin),
                 (3 if balanced else 1) * (max(grids) - (phase - phase_margin)), 0)
    # The inverter GRID port is a separate bottleneck from the utility CT.
    # Only native LOAD traverses that port when utility power supplies LOAD;
    # passive loads between CT and GRID are already in the utility budget.
    native_load = max(port_load, sum(max(v, 0) for v in port_loads), 0)
    port_phase_budget = (3 * (port_phase - phase_margin) - native_load if balanced else
                         port_phase - phase_margin - max(max(port_loads), 0))
    port_budget = min(port_total - margin - native_load, port_phase_budget)
    port_excess = max(port - (port_total - margin), sum(ports) - (port_total - margin),
                      (3 if balanced else 1) * (max(ports) - (port_phase - phase_margin)), 0)
    excess = max(grid_excess, port_excess)
    load_cap = math.floor(max(load_budget, 0) / per_amp)
    port_cap = math.floor(max(port_budget, 0) / per_amp)
    converter_cap = math.floor(min(converter_total, (3 if balanced else 1) * converter_phase) / per_amp)
    deye_cap, actuator_cap, bms_cap = (math.floor(v) for v in (deye, actuator, bms))
    hard_cap = min(deye_cap, actuator_cap, bms_cap, converter_cap)
    feedback_cap = math.floor(max(current - excess / per_amp, 0)) if excess > 0 else hard_cap
    cap = max(0, min(hard_cap, load_cap, port_cap, feedback_cap))
    reason = ("bms_blocked" if bms < 1 else
              "inverter_grid_headroom" if port_excess > grid_excess else
              "grid_headroom" if grid_excess > 0 else
              "deye_charge_cap" if deye_cap <= min(actuator_cap, bms_cap, converter_cap, load_cap, port_cap) else
              "actuator_cap" if actuator_cap <= min(bms_cap, converter_cap, load_cap, port_cap) else
              "converter_cap" if converter_cap < min(bms_cap, load_cap, port_cap) else
              "inverter_grid_load_headroom" if port_cap < min(bms_cap, load_cap) else
              "load_headroom" if load_cap < bms_cap else "bms_cap")
    return dict(cap_a=cap, planning_cap_a=max(0, min(deye_cap, actuator_cap, load_cap, port_cap)),
                deye_cap_a=deye_cap, actuator_cap_a=actuator_cap,
                bms_cap_a=bms_cap, feedback_cap_a=feedback_cap,
                converter_cap_a=max(0, converter_cap),
                inverter_port_planning_cap_a=port_cap,
                hard_current_cap_a=max(0, hard_cap),
                grid_excess_w=round(excess, 6), grid_within_limits=excess == 0,
                connection_grid_excess_w=round(grid_excess, 6),
                inverter_port_excess_w=round(port_excess, 6),
                inverter_port_within_limits=port_excess == 0,
                phase_model="balanced" if balanced else "conservative",
                telemetry_ok=True, reason=reason, power_per_a_w=round(per_amp, 6))


def calculate_grid_charge_increase_cap(g: dict) -> dict:
    """Bound an increase by measured GRID headroom, in addition to full caps.

    ``current_a`` is the baseline of the incremental request, not power that
    can be added back to GRID headroom. A caller enabling previously inactive
    grid charging must supply a zero baseline so the entire setting fits.
    Register acknowledgement alone does not prove physical charger power.
    """
    cap = calculate_grid_charge_cap(g)
    if not cap["telemetry_ok"]:
        return dict(increase_cap_a=0, grid_step_headroom_a=0,
                    telemetry_ok=False, reason="telemetry_invalid")
    total_available = (g.get("total_limit_w", 12000) - g.get("headroom_w", 500)
                       - max(g["grid_w"], sum(g["grid_phases_w"])))
    phase_available = (g.get("phase_limit_w", 5000) - g.get("phase_headroom_w", 250)
                       - max(g["grid_phases_w"]))
    port_available = (g["inverter_grid_import_limit_w"] - g.get("headroom_w", 500)
                      - max(g["grid_port_w"], sum(g["grid_port_phases_w"])))
    port_phase_available = (g["inverter_grid_phase_limit_w"] - g.get("phase_headroom_w", 250)
                            - max(g["grid_port_phases_w"]))
    multiplier = 3 if g.get("grid_charge_balanced") is True else 1
    available = max(0, min(total_available, phase_available * multiplier,
                           port_available, port_phase_available * multiplier))
    per_amp = g["battery_voltage_v"] / g.get("charge_efficiency", .9)
    delta = math.floor(available / per_amp)
    return dict(increase_cap_a=max(0, min(cap["cap_a"], math.floor(g["current_a"] + delta))),
                grid_step_headroom_a=delta, telemetry_ok=True,
                reason="grid_step_headroom")


def _ordinary_history(g, now):
    """Accept only an explicitly validated dispatch history from the caller."""
    keys = ("ordinary_last_possible_ts", "ordinary_last_not_sent_ts")
    if (g.get("ordinary_history_known") is not True or not _number(now) or now <= 0
            or not all(key in g for key in keys)):
        return None
    possible, not_sent = (g[key] for key in keys)
    if any(value is not None and not (_number(value) and 0 <= value <= now)
           for value in (possible, not_sent)):
        return None
    return possible, not_sent


def calculate_grid_charge(g: dict, *, ordinary_policy=None) -> dict:
    """Propose a bounded setting; persist its ledger before attempting a write.

    Required snapshot fields are described by the cap function and integration
    coordinator snapshot builder. ``cheap_window`` denotes a validated current tariff window,
    not a forecast for a future slot. ``emergency_allowed`` is the summer plan's
    permission. Below the configured minimum (default 40%) is itself a
    cheap-window reserve emergency. This minimum is a reserve floor, not a
    weather-dependent charging target.

    An unknown/future history or attempt ledger prevents ordinary changes.
    The dispatch clock includes every potentially sent current setting,
    including safety reductions. Ordinary writes require 600 seconds since
    that dispatch, 60 seconds since a certainly not-sent attempt, and at least
    5 A of actual setting change, except a safe nonzero start from zero. A
    step is at most 20 A. A readback different
    from the last attempt can only retry that proposal, never stack another
    increase. Only a validated virgin history may start immediately.
    The caller must supply fresh telemetry (<=30 s, proper units, not restored).
    """
    cap = calculate_grid_charge_cap(g)
    current = g.get("current_a")
    current_ok = _number(current) and 0 <= current <= 1000
    current = current if current_ok else 0
    pending = g.get("pending_current_a")
    pending_ok = pending is None or (_number(pending) and 0 <= pending <= 1000)
    # An inactive charger may add the entire register setting when enabled.
    # Reduce a pre-existing high setting to that absolute start budget first.
    if cap["telemetry_ok"] and g.get("grid_charge_active") is not True:
        start_cap = calculate_grid_charge_increase_cap({**g, "current_a": 0})["increase_cap_a"]
        if start_cap < cap["cap_a"]:
            cap = dict(cap, cap_a=start_cap, reason="grid_start_headroom")
    pending_unsafe = pending_ok and pending is not None and pending > cap["cap_a"]
    now = g.get("now_ts")
    attempted_at, attempted_a = g.get("last_attempt_ts"), g.get("last_attempt_a")
    ledger_ok = (all(_number(v) for v in (now, attempted_at, attempted_a))
                 and now > 0 and 0 <= attempted_at <= now and 0 <= attempted_a <= 1000)
    age = now - attempted_at if ledger_ok else -1
    if g.get("safety_only") is True:
        candidate = min(current, cap["cap_a"]) if current_ok and pending_ok else 0
        same_attempt = ledger_ok and abs(attempted_a - candidate) < .01
        change = not current_ok or not pending_ok or pending_unsafe or abs(current - candidate) >= .01
        return dict(cap, need_a=0, next_a=candidate,
                    write=change and (not same_attempt or age >= 10), safety=True,
                    reason="safety_" + cap["reason"] if change else "safety_hold",
                    unreachable=False, gap_kwh=0, projected_soc=None)
    soc, target, hours = g.get("soc"), g.get("target_soc"), g.get("remaining_h")
    capacity = g.get("capacity_kwh", 66)
    minimum = g.get("minimum_soc_percent", 40)
    lower_bound = g.get("minimum_soc_lower_bound", 40)
    soc_ok = (g.get("soc_valid") is True
              and all(_number(v) for v in (soc, target, hours, capacity, minimum, lower_bound))
              and 0 <= soc <= 100 and 5 <= lower_bound <= minimum <= 90
              and minimum <= target <= 95 and 0 < hours <= 24
              and 1 <= capacity <= 1000)
    allowed = (g.get("cheap_window") is True and soc_ok
               and (g.get("winter") is True or g.get("emergency_allowed") is True or soc < minimum))
    gap = max((target - soc) * capacity / 100, 0) if soc_ok else 0
    voltage = g.get("battery_voltage_v")
    storage_eta = g.get("charge_storage_efficiency", .95)
    power_valid = (_number(voltage) and 40 <= voltage <= 65
                   and _number(storage_eta) and .5 <= storage_eta <= 1)
    need = math.ceil(gap * 1000 / hours / voltage / storage_eta) if allowed and power_valid else 0
    if allowed and soc < minimum:
        need = max(need, cap["cap_a"])
    wanted = min(cap["cap_a"], need)
    projected = (min(100, soc + cap["cap_a"] * voltage / 1000 * hours * storage_eta / (capacity / 100))
                 if soc_ok and power_valid else None)
    result = dict(cap, need_a=need, next_a=current, write=False, safety=False,
                  unreachable=bool(allowed and need > cap["cap_a"]),
                  gap_kwh=round(gap, 6), projected_soc=round(projected, 3) if projected is not None else None)
    # No charge, a failed snapshot and lower load/BMS limits take precedence
    # over all time/ramp gates. Identical failed writes are retried, not flooded.
    force_zero = not allowed or need == 0 or not cap["telemetry_ok"] or not pending_ok
    safety = not current_ok or current > cap["cap_a"] or pending_unsafe or force_zero
    if safety:
        candidate = 0 if force_zero or not current_ok else min(current, cap["cap_a"])
        same_attempt = ledger_ok and abs(attempted_a - candidate) < .01
        change = (not current_ok or not pending_ok or pending_unsafe
                  or (force_zero and pending is not None and pending > 0)
                  or abs(current - candidate) >= .01)
        result.update(next_a=candidate, safety=True,
                      write=change and (not same_attempt or age >= 10),
                      reason=("pending_current_invalid" if not pending_ok else
                              "telemetry_invalid" if not cap["telemetry_ok"] else
                              "window_or_policy_blocked" if not allowed else
                              "target_reached" if need == 0 else cap["reason"]))
        return result
    history = _ordinary_history(g, now)
    if history is None:
        result["reason"] = "dispatch_history_unknown"
        return result
    possible, not_sent = history
    first_attempt = (attempted_at is None and attempted_a is None and possible is None)
    if not (ledger_ok or first_attempt):
        result["reason"] = "ledger_missing_or_future"
        return result
    if ordinary_policy is not None:
        return ordinary_policy(g, result)
    unconfirmed = ledger_ok and abs(current - attempted_a) >= .01
    if possible is not None and now - possible < ORDINARY_INTERVAL_SECONDS:
        result["reason"] = "awaiting_readback" if unconfirmed else "ramp_wait"
        return result
    if not_sent is not None and now - not_sent < ORDINARY_RETRY_BACKOFF_SECONDS:
        result["reason"] = "dispatch_retry_wait"
        return result
    if unconfirmed:
        wanted = min(attempted_a, wanted)
    difference = wanted - current
    starting = current == 0 and difference > 0
    if abs(difference) < ORDINARY_DEADBAND_A and not starting:
        result["reason"] = "deadband"
        return result
    candidate = (min(wanted, current + ORDINARY_MAX_STEP_A) if difference > 0
                 else max(wanted, current - ORDINARY_MAX_STEP_A))
    if difference > 0:
        increase = calculate_grid_charge_increase_cap(g)
        result.update(increase)
        candidate = min(candidate, increase["increase_cap_a"])
    candidate = math.floor(candidate) if difference > 0 else math.ceil(candidate)
    # Test the final setting difference as well: GRID clipping to 1--4 A must
    # not turn a large requested increase into another small ordinary write.
    if (abs(candidate - current) < ORDINARY_DEADBAND_A
            and not (starting and candidate > 0)):
        result["reason"] = "grid_step_headroom" if difference > 0 else "deadband"
        return result
    result.update(next_a=candidate, write=True,
                  reason="retry_unconfirmed" if unconfirmed else
                         "ramp_up" if difference > 0 else "ramp_down")
    return result


