"""Load-priority grid-charge limiter and deadline current ramp.

No Home Assistant calls.  This standalone standard-library module is bundled with the HA integration.
Measurements and the attempt ledger must
come from a single validated snapshot.  A proposed value is not a device ACK.

The phase budget intentionally allows the *whole* incremental charger power on
any phase.  It does not assume balanced AC charging.  LOAD budgets ignore PV so
a sudden loss of PV cannot create additional charging headroom.
``load_w`` and ``load_phases_w`` are native LOAD measurements. Optional
``outside_load_w`` is additional demand outside LOAD: added once to the total
and conservatively once to each candidate phase budget, never to measured GRID.
"""
from __future__ import annotations

import math


def _number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def _vector(value):
    return (isinstance(value, (list, tuple)) and len(value) == 3
            and all(_number(v) for v in value))


def calculate_grid_charge_cap(g: dict) -> dict:
    """Return an instantaneous upper bound; never grant a time-based override."""
    result = dict(cap_a=0, telemetry_ok=False, reason="telemetry_invalid",
                  power_per_a_w=0.0)
    values = [g.get(k) for k in ("load_w", "grid_w", "battery_voltage_v", "current_a")]
    loads, grids = g.get("load_phases_w"), g.get("grid_phases_w")
    if not (g.get("telemetry_valid") is True and all(_number(v) for v in values)
            and _vector(loads) and _vector(grids)):
        return result
    load, grid, voltage, current = values
    if not (-200 <= load <= 60000 and -60000 <= grid <= 60000
            and all(-200 <= v <= 30000 for v in loads)
            and all(-30000 <= v <= 30000 for v in grids)
            and 40 <= voltage <= 65 and 0 <= current <= 1000):
        return result
    total = g.get("total_limit_w", 12000)
    phase = g.get("phase_limit_w", 5000)
    margin = g.get("headroom_w", 500)
    phase_margin = g.get("phase_headroom_w", 250)
    eta = g.get("charge_efficiency", .9)
    bms = g.get("bms_cap_a", 0)
    outside = g.get("outside_load_w", 0)
    if not (all(_number(v) for v in (total, phase, margin, phase_margin, eta, bms, outside))
            and 0 < total <= 30000 and 0 < phase <= 15000
            and 0 <= margin < total and 0 <= phase_margin < phase
            and .5 <= eta <= 1 and 0 <= bms <= 1000 and 0 <= outside <= 60000):
        return result
    per_amp = voltage / eta
    load_budget = min(total - margin - max(load, sum(max(v, 0) for v in loads), 0) - outside,
                      phase - phase_margin - max(max(loads), 0) - outside)
    excess = max(grid - (total - margin), sum(grids) - (total - margin),
                 max(grids) - (phase - phase_margin), 0)
    load_cap = math.floor(max(load_budget, 0) / per_amp)
    feedback_cap = math.floor(max(current - excess / per_amp, 0)) if excess > 0 else 108
    cap = max(0, min(108, math.floor(bms), load_cap, feedback_cap))
    reason = ("bms_blocked" if bms < 1 else "grid_headroom" if excess > 0
              else "load_headroom" if cap < min(108, math.floor(bms)) else "bms_cap")
    return dict(cap_a=cap, telemetry_ok=True, reason=reason,
                power_per_a_w=round(per_amp, 6))


def calculate_grid_charge(g: dict) -> dict:
    """Propose a bounded setting; persist its ledger before attempting a write.

    Required snapshot fields are described by the cap function and integration
    coordinator snapshot builder. ``cheap_window`` denotes a validated current tariff window,
    not a forecast for a future slot. ``emergency_allowed`` is the summer plan's
    permission. Below the configured minimum (default 40%) is itself a
    cheap-window reserve emergency. This minimum is a reserve floor, not a
    weather-dependent charging target.

    An unknown/future ledger prevents increases.  A readback different from the
    last attempt can only retry that proposal, never stack another increase.
    The caller must supply fresh telemetry (<=30 s, proper units, not restored).
    """
    cap = calculate_grid_charge_cap(g)
    current = g.get("current_a")
    current_ok = _number(current) and 0 <= current <= 1000
    current = current if current_ok else 0
    now = g.get("now_ts")
    attempted_at, attempted_a = g.get("last_attempt_ts"), g.get("last_attempt_a")
    ledger_ok = (all(_number(v) for v in (now, attempted_at, attempted_a))
                 and now > 0 and 0 <= attempted_at <= now and 0 <= attempted_a <= 1000)
    age = now - attempted_at if ledger_ok else -1
    if g.get("safety_only") is True:
        candidate = min(current, cap["cap_a"]) if current_ok else 0
        same_attempt = ledger_ok and abs(attempted_a - candidate) < .01
        change = not current_ok or abs(current - candidate) >= .01
        return dict(cap, need_a=0, next_a=candidate,
                    write=change and (not same_attempt or age >= 10), safety=True,
                    reason="safety_" + cap["reason"] if change else "safety_hold",
                    unreachable=False, gap_kwh=0, projected_soc=None)
    soc, target, hours = g.get("soc"), g.get("target_soc"), g.get("remaining_h")
    capacity = g.get("capacity_kwh", 66)
    minimum = g.get("minimum_soc_percent", 40)
    soc_ok = (g.get("soc_valid") is True
              and all(_number(v) for v in (soc, target, hours, capacity, minimum))
              and 0 <= soc <= 100 and 40 <= minimum <= 90
              and minimum <= target <= 95 and 0 < hours <= 24
              and 1 <= capacity <= 1000)
    allowed = (g.get("cheap_window") is True and soc_ok
               and (g.get("winter") is True or g.get("emergency_allowed") is True or soc < minimum))
    gap = max((target - soc) * capacity / 100, 0) if soc_ok else 0
    need = math.ceil(gap / hours * 108 / 5.3) if allowed else 0
    if allowed and soc < minimum:
        need = max(need, cap["cap_a"])
    wanted = min(cap["cap_a"], need)
    projected = min(100, soc + cap["cap_a"] * 5.3 / 108 * hours / (capacity / 100)) if soc_ok else None
    result = dict(cap, need_a=need, next_a=current, write=False, safety=False,
                  unreachable=bool(allowed and need > cap["cap_a"]),
                  gap_kwh=round(gap, 6), projected_soc=round(projected, 3) if projected is not None else None)
    # No charge, a failed snapshot and lower load/BMS limits take precedence
    # over all time/ramp gates. Identical failed writes are retried, not flooded.
    force_zero = not allowed or need == 0 or not cap["telemetry_ok"]
    safety = not current_ok or current > cap["cap_a"] or force_zero
    if safety:
        candidate = 0 if force_zero or not current_ok else cap["cap_a"]
        same_attempt = ledger_ok and abs(attempted_a - candidate) < .01
        change = not current_ok or abs(current - candidate) >= .01
        result.update(next_a=candidate, safety=True,
                      write=change and (not same_attempt or age >= 10),
                      reason=("telemetry_invalid" if not cap["telemetry_ok"] else
                              "window_or_policy_blocked" if not allowed else
                              "target_reached" if need == 0 else cap["reason"]))
        return result
    if not ledger_ok:
        result["reason"] = "ledger_missing_or_future"
        return result
    if abs(current - attempted_a) >= .01:
        candidate = min(attempted_a, wanted)
        # Cancelling an obsolete higher proposal may reduce normally, but it
        # must not invent an immediate multi-amp ordinary downward jump.
        if candidate < current:
            candidate = max(candidate, current - 5)
            ready = age >= 30
        else:
            # A manual setting change or stale readback can put the device far
            # below the previous proposal.  Retrying that old high value must
            # not bypass the ordinary upward ramp from the observed setting.
            candidate = min(candidate, current + 2)
            same_proposal = abs(candidate - attempted_a) < .01
            ready = age >= (10 if same_proposal else 30)
        result.update(next_a=candidate, write=ready and abs(candidate-current) >= .01,
                      reason="retry_unconfirmed" if ready else "awaiting_readback")
        return result
    if age < 30:
        result["reason"] = "ramp_wait"
        return result
    difference = wanted - current
    if abs(difference) < 2:
        result["reason"] = "deadband"
        return result
    candidate = min(wanted, current + 2) if difference > 0 else max(wanted, current - 5)
    result.update(next_a=int(candidate), write=True,
                  reason="ramp_up" if difference > 0 else "ramp_down")
    return result


