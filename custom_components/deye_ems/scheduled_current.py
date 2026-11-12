"""Half-hour setting decisions; the existing instantaneous safety path stays first.

The coordinator owns durable policy state. No service calls or physical ACKs here.
The old pure controller remains a regression-tested safety/cap calculation; its
600-second ramp is bypassed by the explicit ordinary-policy callback.
"""
from __future__ import annotations

import math
from datetime import datetime

from .grid_control import calculate_grid_charge as _base, calculate_grid_charge_increase_cap

SLOT_SECONDS = 1800
DISPATCH_WINDOW_SECONDS = 60
RECOVERY_SECONDS = 120
DEADBAND_A = 10
QUANTUM_A = 5
SOC_HYSTERESIS = 2


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def dispatch_ready(now, possible, not_sent):
    """First minute of :00/:30; one possible dispatch per block, safety included.

    UTC half-hours also align to local half-hours in Europe/Warsaw, including DST.
    Missed slots are skipped. Failed/uncertain sends cannot create a burst.
    """
    if not _finite(now) or now <= 0:
        return False
    if any(at is not None and (not _finite(at) or not 0 <= at <= now)
           for at in (possible, not_sent)):
        return False
    slot = math.floor(now / SLOT_SECONDS) * SLOT_SECONDS
    return (now - slot < DISPATCH_WINDOW_SECONDS
            and (possible is None or possible < slot and now - possible >= RECOVERY_SECONDS)
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
    since, observed = policy.get("safe_since"), policy.get("observed_at")
    if (not _finite(since) or not 0 <= since <= now - RECOVERY_SECONDS
            or not _finite(observed) or not 0 <= now - observed <= 30):
        return False
    for key, delay in (("ordinary_last_possible_ts", RECOVERY_SECONDS),
                       ("ordinary_last_not_sent_ts", 60)):
        if key not in g:
            return False
        at = g[key]
        if at is not None and (not _finite(at) or not delay <= now - at):
            return False
    return True


def update_policy(g, previous):
    """Target latch belongs to one tariff deadline, with a fresh safety timer.

    Unknown/corrupt state is treated as stopped until target-2pp (or reserve
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
    if valid:
        if known and previous.get("deadline") != key:
            stopped = soc >= target
        if soc >= target:
            stopped = True
        elif soc <= target - SOC_HYSTERESIS or (_finite(g.get("minimum_soc_percent"))
                                               and soc < g["minimum_soc_percent"]):
            stopped = False
    # Safety-only uses exactly the existing LOAD/GRID/BMS/converter validation.
    safety = _base({**g, "safety_only": True})
    healthy = (valid and safety["telemetry_ok"] and safety["grid_within_limits"]
               and safety["cap_a"] > 0 and not safety["write"]
               and g.get("hardware_ok") is True)
    since = previous.get("safe_since")
    observed = previous.get("observed_at")
    if not healthy:
        since = None
    elif (not _finite(since) or not 0 <= since <= now or not _finite(observed)
          or not 0 <= now - observed <= 30):
        since = now
    initial = g.get("initial_window_started")
    if not isinstance(initial, bool):
        initial = (previous.get("initial_started", False) if previous.get("deadline") == key else False)
    return dict(version=1, deadline=key if isinstance(key, str) else "",
                stopped=bool(stopped), safe_since=since, observed_at=now,
                initial_started=initial if isinstance(initial, bool) else True)


def _ordinary(g, result):
    result.update(write=False, next_a=g["current_a"])
    now = g["now_ts"]
    scheduled = dispatch_ready(now, g.get("ordinary_last_possible_ts"), g.get("ordinary_last_not_sent_ts"))
    initial = initial_dispatch_ready(g)
    if not scheduled and not initial:
        result["reason"] = "scheduled_hold"
        return result
    policy = g.get("current_policy", {})
    since = policy.get("safe_since")
    observed = policy.get("observed_at")
    if (not _finite(since) or not 0 <= since <= now - RECOVERY_SECONDS
            or not _finite(observed) or not 0 <= now - observed <= 30):
        result["reason"] = "recovery_wait"
        return result
    wanted = min(result["need_a"], result["cap_a"])
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
    if abs(candidate - g["current_a"]) < DEADBAND_A and not (g["current_a"] == 0 and candidate > 0):
        result["reason"] = "scheduled_deadband"
        return result
    result.update(next_a=candidate, write=True,
                  reason="initial_charge_start" if initial and not scheduled else
                         "scheduled_retry" if unconfirmed else "scheduled_setpoint")
    return result


def calculate_grid_charge(g):
    if g.get("safety_only") is True:
        return _base(g)
    policy = g.get("current_policy", {})
    if policy.get("stopped", True):
        # Keep all validation/safety cancellation semantics in the base path.
        result = _base({**g, "soc": g.get("target_soc")}, ordinary_policy=_ordinary)
        if result.get("reason") == "target_reached":
            result["reason"] = "target_hysteresis"
        return result
    return _base(g, ordinary_policy=_ordinary)


def describe_current_wait(g):
    """Read-only explanation of the next ordinary opportunity, never a promise.

    No permissions, journal entries or controller inputs are changed here.
    A missing recovery observation cannot be turned into a countdown.
    """
    status = dict(current_hold_reason="policy_blocked", recovery_remaining_s=None,
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
    if g.get("telemetry_valid") is not True or g.get("soc_valid") is not True or not result.get("telemetry_ok"):
        status["current_hold_reason"] = "telemetry_invalid"
        return status
    if reason in ("target_reached", "target_hysteresis", "pv_covers_charge_need"):
        status["current_hold_reason"] = "pv_covers_charge_need" if reason == "pv_covers_charge_need" else "target_reached"
        return status
    if (g.get("hardware_ok") is not True or g.get("cheap_window") is not True
            or result.get("safety") or result.get("need_a", 0) <= 0):
        return status
    policy = g.get("current_policy", {})
    if not isinstance(policy, dict):
        return status
    pending = g.get("pending_current_a")
    if (g.get("ordinary_history_known") is not True
            or pending is not None and (not _finite(pending) or pending != 0)):
        status["current_hold_reason"] = "waiting_readback"
        return status
    since, observed = policy.get("safe_since"), policy.get("observed_at")
    status["current_hold_reason"] = "waiting_stable_measurements"
    if (not _finite(since) or not 0 <= since <= now or not _finite(observed)
            or not 0 <= now-observed <= 30):
        return status
    recovery = max(0, since+RECOVERY_SECONDS-now)
    status["recovery_remaining_s"] = math.ceil(recovery)
    eligible = max(now, since+RECOVERY_SECONDS)
    retry = now
    for key, delay in (("ordinary_last_possible_ts", RECOVERY_SECONDS),
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
        if deadline.tzinfo is None or not now < deadline.timestamp() <= now+86400:
            return status
    except (KeyError, TypeError, ValueError, OverflowError):
        return status
    initial = (g.get("current_a") == 0 and policy.get("initial_started", False) is False
               and policy.get("stopped", True) is False and policy.get("deadline") == g["policy_deadline"])
    candidate = eligible
    if not initial:
        slot = math.floor(now/SLOT_SECONDS)*SLOT_SECONDS
        possible = g.get("ordinary_last_possible_ts")
        for _ in range(50):
            candidate = max(slot, eligible)
            if candidate < slot+DISPATCH_WINDOW_SECONDS and (possible is None or possible < slot):
                break
            slot += SLOT_SECONDS
        status["current_hold_reason"] = "waiting_stable_measurements" if recovery > 0 else "scheduled_regular"
    else:
        status["current_hold_reason"] = ("waiting_stable_measurements" if recovery > 0 else
                                         "waiting_retry" if retry > now else "initial_start")
    if candidate >= deadline.timestamp():
        return status
    if not initial and candidate <= now:
        status["current_hold_reason"] = "ready"
    status["next_current_change_at"] = datetime.fromtimestamp(candidate, deadline.tzinfo).isoformat()
    return status
