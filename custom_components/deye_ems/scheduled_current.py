"""Rolling setting decisions; the existing instantaneous safety path stays first.

The coordinator owns durable policy state. No service calls or physical ACKs here.
The old pure controller remains a regression-tested safety/cap calculation; its
stepped ramp is bypassed by the explicit ordinary-policy callback. The
durable interval is 600 seconds normally and 120 seconds at night.
"""
from __future__ import annotations

import math
from datetime import datetime

from .grid_control import calculate_grid_charge as _base, calculate_grid_charge_increase_cap

ORDINARY_INTERVAL_SECONDS = 600
COMMAND_SETTLE_SECONDS = 120
DEADBAND_A = 10
MAX_STEP_A = 10
QUANTUM_A = 5
SOC_HYSTERESIS = 5


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def policy_ready(policy, now):
    """Use the latest validated snapshot; no continuous-observation timer."""
    observed = policy.get("observed_at") if isinstance(policy, dict) else None
    return (_finite(now) and now > 0 and _finite(observed)
            and 0 <= now - observed <= 30)


def tapering(g):
    """Only continue an already running charge below the hard SoC ceiling."""
    policy = g.get("current_policy", {})
    current, soc, ceiling = g.get("current_a"), g.get("soc"), g.get("grid_max_soc_percent", 95)
    return (isinstance(policy, dict) and policy.get("stopped") is True
            and g.get("grid_charge_active") is True and _finite(current) and current > 0
            and _finite(soc) and _finite(ceiling) and soc < ceiling)


def dispatch_ready(now, possible, not_sent, positive, *, fast=False):
    """Every ordinary start/correction shares the same durable rolling clocks."""
    if not _finite(now) or now <= 0:
        return False
    if any(at is not None and (not _finite(at) or not 0 <= at <= now)
           for at in (possible, not_sent, positive)):
        return False
    interval = COMMAND_SETTLE_SECONDS if fast else ORDINARY_INTERVAL_SECONDS
    return ((positive is None or now - positive >= interval)
            and (possible is None or now - possible >= COMMAND_SETTLE_SECONDS)
            and (not_sent is None or now - not_sent >= 60))


def initial_dispatch_ready(g):
    """One observed zero-to-positive start per whole cheap-window deadline.

    The coordinator spends the permission in a durable prepared-attempt
    journal. It is never refunded by a zero setting, clouds or a restart.
    """
    policy = g.get("current_policy", {})
    now = g.get("now_ts")
    if (not isinstance(policy, dict) or not _finite(now) or now <= 0
            or g.get("cheap_window") is not True or g.get("hardware_ok") is not True
            or g.get("telemetry_valid") is not True or g.get("soc_valid") is not True
            or g.get("current_a") != 0 or g.get("ordinary_history_known") is not True
            or policy.get("initial_started", False) is not False
            or policy.get("stopped", True) is not False
            or policy.get("deadline") != g.get("policy_deadline")
            or not isinstance(g.get("policy_deadline"), str) or not g["policy_deadline"]):
        return False
    pending = g.get("pending_current_a")
    if pending is not None and (not _finite(pending) or pending != 0):
        return False
    if ("ordinary_last_positive_possible_ts" not in g or not dispatch_ready(
            now, g.get("ordinary_last_possible_ts"), g.get("ordinary_last_not_sent_ts"),
            g["ordinary_last_positive_possible_ts"], fast=g.get("fast_night_charge") is True)):
        return False
    if not policy_ready(policy, now):
        return False
    for key, delay in (("ordinary_last_possible_ts", COMMAND_SETTLE_SECONDS),
                       ("ordinary_last_not_sent_ts", 60)):
        if key not in g:
            return False
        at = g[key]
        if at is not None and (not _finite(at) or not delay <= now - at):
            return False
    return True


def update_policy(g, previous):
    """Target latch belongs to one tariff deadline; readiness uses current data.

    Unknown/corrupt state is treated as stopped until target-5pp (or reserve
    emergency). A changed target alone does not erase a reached-target latch.
    """
    now, soc, target = g.get("now_ts"), g.get("soc"), g.get("target_soc")
    key = g.get("policy_deadline")
    valid = (_finite(now) and now > 0 and _finite(soc) and 0 <= soc <= 100
             and g.get("soc_valid") is True and _finite(target) and 5 <= target <= 95
             and isinstance(key, str) and bool(key))
    previous = previous if isinstance(previous, dict) else {"invalid": True}
    known = previous == {} or (previous.get("version") == 1
            and isinstance(previous.get("stopped"), bool)
            and isinstance(previous.get("deadline"), str))
    stopped = previous.get("stopped", False) if known else True
    final_seen = previous.get("final_window_seen") is True if previous.get("deadline") == key else False
    if valid:
        if known and previous.get("deadline") != key:
            stopped = soc >= target
        if soc >= target:
            stopped = True
        elif soc <= target - SOC_HYSTERESIS or (_finite(g.get("minimum_soc_percent"))
                                               and soc < g["minimum_soc_percent"]):
            stopped = False
        hours = g.get("remaining_h")
        if g.get("fast_night_charge") is not True and _finite(hours) and 0 < hours <= 1 and not final_seen:
            if soc < target:
                stopped = False
            final_seen = True
    # Safety-only uses exactly the existing LOAD/GRID/BMS/converter validation.
    safety = _base({**g, "safety_only": True})
    healthy = (valid and safety["telemetry_ok"] and safety["grid_within_limits"]
               and safety["cap_a"] > 0 and not safety["write"]
               and g.get("hardware_ok") is True)
    initial = g.get("initial_window_started")
    if not isinstance(initial, bool):
        initial = (previous.get("initial_started", False) if previous.get("deadline") == key else False)
    return dict(version=1, deadline=key if isinstance(key, str) else "",
                stopped=bool(stopped), observed_at=now if healthy else None, final_window_seen=final_seen,
                initial_started=initial if isinstance(initial, bool) else True)


def _ordinary(g, result):
    result.update(write=False, next_a=g["current_a"])
    now = g["now_ts"]
    scheduled = ("ordinary_last_positive_possible_ts" in g and dispatch_ready(
        now, g.get("ordinary_last_possible_ts"), g.get("ordinary_last_not_sent_ts"),
        g["ordinary_last_positive_possible_ts"], fast=g.get("fast_night_charge") is True))
    initial = initial_dispatch_ready(g)
    if not scheduled:
        result["reason"] = "scheduled_hold"
        return result
    policy = g.get("current_policy", {})
    if not policy_ready(policy, now):
        result["reason"] = "fresh_data_wait"
        return result
    wanted = 0 if g.get("taper_to_zero") is True else min(result["need_a"], result["cap_a"])
    attempted = g.get("last_attempt_a")
    unconfirmed = _finite(attempted) and abs(g["current_a"] - attempted) >= .01
    if unconfirmed:
        wanted = min(wanted, attempted)
    if wanted > g["current_a"]:
        increase = calculate_grid_charge_increase_cap(g)
        result.update(increase)
        wanted = min(wanted, increase["increase_cap_a"])
    # Round demand upwards, but never round through a validated upper bound.
    upper = min(result["cap_a"], result.get("increase_cap_a", result["cap_a"]))
    if unconfirmed:
        upper = min(upper, attempted)
    candidate = min(math.ceil(wanted / QUANTUM_A) * QUANTUM_A,
                    math.floor(upper / QUANTUM_A) * QUANTUM_A)
    # A sub-5A hardware cap must still permit a safe initial start.
    if candidate == 0 and wanted > 0 and g["current_a"] == 0:
        candidate = math.floor(min(wanted, upper))
    # Night increases use the measured headroom above; ordinary reductions
    # remain stepped. Protective reductions bypass this path.
    current = g["current_a"]
    material_change = abs(candidate - current) >= DEADBAND_A
    if candidate > current and g.get("fast_night_charge") is not True:
        candidate = min(candidate, math.floor((current + MAX_STEP_A) / QUANTUM_A) * QUANTUM_A)
    elif candidate < current:
        candidate = max(candidate, math.ceil(max(current - MAX_STEP_A, 0) / QUANTUM_A) * QUANTUM_A)
    starting = current == 0 and candidate > 0
    tapering_down = g.get("taper_to_zero") is True and candidate < current
    if candidate == current or not (material_change or starting or tapering_down):
        result["reason"] = "scheduled_deadband"
        return result
    result.update(next_a=candidate, write=True,
                  reason="target_taper" if g.get("taper_to_zero") else "initial_charge_start" if initial else
                         "scheduled_retry" if unconfirmed else "scheduled_setpoint")
    return result


def batch_window(g, cap):
    """Defer small optional charging, retaining time and reserve headroom.

    Reserve recovery is never delayed. A low instantaneous cap opens the
    window earlier, rather than assuming maximum inverter power at dawn.
    No forecast, service, state mutation or permission is introduced here.
    """
    values = [g.get(k) for k in ("remaining_h", "soc", "target_soc", "capacity_kwh",
                               "minimum_soc_percent", "battery_voltage_v")]
    if not all(_finite(v) for v in values) or not _finite(cap) or cap <= 0:
        return False, g.get("remaining_h")
    hours, soc, target, capacity, reserve, voltage = values
    eta = g.get("charge_storage_efficiency", .95)
    if not _finite(eta) or not .5 <= eta <= 1 or not 0 < hours <= 24 or voltage <= 0:
        return False, hours
    if soc <= reserve + 5:
        return False, hours
    gap = max(target-soc, 0) * capacity / 100
    rate = cap * voltage * eta / 1000
    battery = g.get("battery_power_w")
    discharge = max(battery, 0) / 1000 if _finite(battery) else rate
    # Include observed battery depletion during a possible wait. Demand at
    # LOAD is not added again: it is already constrained by the cap model.
    lead = max(1., (gap + discharge * hours) * 1.5 / rate + .25)
    reserve_energy = max(soc-reserve-5, 0) * capacity / 100
    reserve_urgent = discharge > 0 and reserve_energy <= discharge * max(hours-lead, 0)
    return hours > lead and not reserve_urgent, min(hours, max(1., lead))


def calculate_grid_charge(g):
    if g.get("safety_only") is True:
        return _base(g)
    policy = g.get("current_policy", {})
    if _finite(g.get("soc")) and g["soc"] >= g.get("grid_max_soc_percent", 95):
        result = _base({**g, "soc": g.get("target_soc")}, ordinary_policy=_ordinary)
        result["reason"] = "maximum_soc_reached"
        return result
    if policy.get("stopped", True):
        if g.get("fast_night_charge") is not True and tapering(g):
            return _base({**g, "soc": g.get("target_soc"), "taper_to_zero": True}, ordinary_policy=_ordinary)
        result = _base({**g, "soc": g.get("target_soc")}, ordinary_policy=_ordinary)
        if result.get("reason") == "target_reached":
            result["reason"] = "target_hysteresis"
        return result
    result = _base(g, ordinary_policy=_ordinary)
    if (g.get("fast_night_charge") is True or result.get("safety")
            or not result.get("telemetry_ok") or g.get("cheap_window") is not True):
        return result
    if result.get("need_a", 0) > 10:
        return result
    defer, pace_hours = batch_window(g, result.get("cap_a"))
    if defer and g.get("current_a") == 0:
        # A deliberate wait is distinct from a telemetry failure. The usual
        # stop path journals a zero only when the setting actually changes.
        stop = _base({**g, "soc": g.get("target_soc")}, ordinary_policy=_ordinary)
        stop["reason"] = "batch_wait"
        return stop
    return _base({**g, "remaining_h": pace_hours}, ordinary_policy=_ordinary)


def describe_current_wait(g):
    """Read-only explanation of the next ordinary opportunity, never a promise.

    No permissions, journal entries or controller inputs are changed here.
    A missing current valid snapshot cannot be turned into a countdown.
    """
    status = dict(current_hold_reason="policy_blocked",
                  next_current_change_at=None,
                  initial_window_started=g.get("initial_window_started")
                  if isinstance(g.get("initial_window_started"), bool) else None,
                  grid_charge_enabled=g.get("grid_charge_enabled")
                  if isinstance(g.get("grid_charge_enabled"), bool) else None)
    now = g.get("now_ts")
    if not _finite(now) or now <= 0:
        return status
    result = calculate_grid_charge(g)
    reason = result.get("reason")
    if reason == "batch_wait" and g.get("telemetry_valid") is True and g.get("soc_valid") is True:
        _, pace = batch_window(g, result.get("cap_a"))
        if _finite(pace) and _finite(g.get("remaining_h")):
            at = now + max(g["remaining_h"]-pace, 0) * 3600
            status["current_hold_reason"] = "batch_wait"
            try:
                deadline = datetime.fromisoformat(g["policy_deadline"])
                if deadline.tzinfo is not None and now <= at < deadline.timestamp() <= now+15*86400:
                    status["next_current_change_at"] = datetime.fromtimestamp(at, deadline.tzinfo).isoformat()
            except (KeyError, TypeError, ValueError, OverflowError):
                pass
        return status
    if g.get("telemetry_valid") is not True or g.get("soc_valid") is not True or not result.get("telemetry_ok"):
        status["current_hold_reason"] = "telemetry_invalid"
        return status
    if reason in ("target_reached", "target_hysteresis", "pv_covers_charge_need"):
        status["current_hold_reason"] = "pv_covers_charge_need" if reason == "pv_covers_charge_need" else "target_reached"
        return status
    # A switch can stay on while the battery receives negligible power.
    # Report the measured connection limit before the generic policy wait,
    # keeping port GRID limits and the dispatch decision separate.
    if (g.get("hardware_ok") is True and g.get("cheap_window") is True
            and result.get("need_a", 0) > 0
            and reason != "window_or_policy_blocked"
            and g["battery_power_w"] >= -g["battery_voltage_v"]):
        headroom = calculate_grid_charge_increase_cap(g)
        if result["connection_grid_excess_w"] > 0 or headroom["connection_step_headroom_a"] == 0:
            status["current_hold_reason"] = "connection_headroom_blocked"
            return status
        if result["inverter_port_excess_w"] > 0 or headroom["port_step_headroom_a"] == 0:
            status["current_hold_reason"] = "inverter_grid_headroom_blocked"
            return status
    if (g.get("hardware_ok") is not True or g.get("cheap_window") is not True
            or result.get("safety") or result.get("need_a", 0) <= 0 and not tapering(g)):
        return status
    policy = g.get("current_policy", {})
    if not isinstance(policy, dict):
        return status
    pending = g.get("pending_current_a")
    if (g.get("ordinary_history_known") is not True
            or pending is not None and (not _finite(pending) or pending != 0)):
        status["current_hold_reason"] = "waiting_readback"
        return status
    status["current_hold_reason"] = "waiting_valid_measurements"
    if not policy_ready(policy, now):
        return status
    eligible = now
    retry = now
    interval = COMMAND_SETTLE_SECONDS if g.get("fast_night_charge") is True else ORDINARY_INTERVAL_SECONDS
    for key, delay in (("ordinary_last_positive_possible_ts", interval),
                       ("ordinary_last_possible_ts", COMMAND_SETTLE_SECONDS),
                       ("ordinary_last_not_sent_ts", 60)):
        if key not in g:
            status["current_hold_reason"] = "waiting_readback"
            return status
        at = g[key]
        if at is not None:
            if not _finite(at) or not 0 <= at <= now:
                status["current_hold_reason"] = "waiting_readback"
                return status
            retry = max(retry, at+delay)
    eligible = max(eligible, retry)
    try:
        deadline = datetime.fromisoformat(g["policy_deadline"])
        max_window = 15*86400 if g.get("tariff_window_valid") is True else 86400
        if deadline.tzinfo is None or not now < deadline.timestamp() <= now+max_window:
            return status
    except (KeyError, TypeError, ValueError, OverflowError):
        return status
    initial = (g.get("current_a") == 0 and policy.get("initial_started", False) is False
               and policy.get("stopped", True) is False and policy.get("deadline") == g["policy_deadline"])
    candidate = eligible
    status["current_hold_reason"] = ("waiting_retry" if retry > now else "initial_start" if initial else "ready")
    if candidate >= deadline.timestamp():
        return status
    status["next_current_change_at"] = datetime.fromtimestamp(candidate, deadline.tzinfo).isoformat()
    return status
