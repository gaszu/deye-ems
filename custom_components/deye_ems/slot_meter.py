"""Pure, restart-safe measurements of Deye tariff slots; no HA dependencies.

sample = {at: aware datetime/ISO or Unix seconds, battery_w: number,
          grid_w: number, telemetry_valid: bool}. Battery positive means
discharge; Grid positive means import. The runtime supplies current telemetry,
not a proposed command. Timezone is Europe/Warsaw.

Energy uses linear interpolation between two valid samples at most30s apart,
splitting at tariff boundaries and power zero crossings. This is a sampling
approximation, not a revenue meter. Longer/missing intervals have explicitly
missing coverage and ZERO attributed energy. Earlier parts of a slot before
the first observation are missing too. A closed slot is complete only when its
entire actual UTC duration was covered. DST slots can have nonstandard lengths.

The returned dict is the complete durable memory. Keep previous and slots
across restarts; current_slot and completed_slots are keys into slots. The
function never mutates caller-owned sample/memory. At most42 slots/7days stay.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import math
from zoneinfo import ZoneInfo

if __package__:
    from .tariff_calendar import calendar_context, describe_calendar


TZ = ZoneInfo("Europe/Warsaw")
MAX_INTERVAL_SECONDS = 30.0
RETENTION_SECONDS = 7 * 86400
MAX_SLOTS = 42
_COUNTERS = ("seconds_valid", "seconds_missing", "grid_import_kwh",
             "battery_discharge_kwh", "battery_charge_kwh")


def _number(value):
    return (not isinstance(value, bool) and isinstance(value, (float, int))
            and math.isfinite(value))


def _stamp(value):
    if _number(value):
        if value <= 0:
            raise ValueError("invalid_timestamp")
        # Validate representability instead of allowing datetime overflow later.
        datetime.fromtimestamp(value, TZ)
        return float(value)
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("invalid_timestamp")
    return dt.timestamp()


def _slot(at, options=None):
    if options is not None and options.get("tariff_profile", "legacy_g13") != "legacy_g13":
        local = datetime.fromtimestamp(at, TZ)
        calendar = describe_calendar(local, options["tariff_profile"], options.get("tariff_clock_basis", "local"))
        if calendar.get("within_validity") is not True:
            raise ValueError("tariff_outside_validity")
        for index, row in enumerate(calendar["today"], 1):
            start, end = _stamp(row["start"]), _stamp(row["end"])
            if start <= at < end:
                return index, datetime.fromtimestamp(start, TZ), datetime.fromtimestamp(end, TZ)
        raise ValueError("timestamp_outside_slot")
    local = datetime.fromtimestamp(at, TZ)
    midnight = datetime.combine(local.date(), datetime.min.time(), tzinfo=TZ)
    winter = local.month in (10, 11, 12, 1, 2, 3)
    hours = (0, 4, 7, 13, 16 if winter else 19, 21 if winter else 22)
    boundaries = [midnight.replace(hour=h) for h in hours]
    boundaries.append(datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), tzinfo=TZ))
    for i in range(6):
        if boundaries[i].timestamp() <= at < boundaries[i + 1].timestamp():
            return i + 1, boundaries[i], boundaries[i + 1]
    raise ValueError("timestamp_outside_slot")


def _positive_integral(a, b, seconds):
    """W seconds for max(linearly interpolated power,0), including a crossing."""
    if a >= 0 and b >= 0:
        return (a + b) * .5 * seconds
    if a <= 0 and b <= 0:
        return 0.
    if a > 0:
        return a * .5 * seconds * a / (a - b)
    return b * .5 * seconds * b / (b - a)


def _record_key(start, options=None):
    return (f"{options['tariff_profile']}|{options.get('tariff_clock_basis', 'local')}|{start.isoformat()}"
            if options is not None and options.get("tariff_profile", "legacy_g13") != "legacy_g13" else start.isoformat())


def _record(slots, at, options=None):
    slot, start, end = _slot(at, options)
    key = _record_key(start, options)
    if key not in slots:
        # No record means no observed history before this instant in this slot.
        slots[key] = dict(slot=slot, start=start.isoformat(), end=end.isoformat(),
                          duration_seconds=end.timestamp() - start.timestamp(),
                          seconds_valid=0., seconds_missing=max(at - start.timestamp(), 0.),
                          grid_import_kwh=0., battery_discharge_kwh=0.,
                          battery_charge_kwh=0., complete=False, closed=False,
                          coverage=0., reason="partial_unobserved_start")
        if options is not None and options.get("tariff_profile", "legacy_g13") != "legacy_g13":
            calendar = describe_calendar(start, options["tariff_profile"], options.get("tariff_clock_basis", "local"))
            logical = calendar["today"][slot-1]
            slots[key].update(profile_id=options["tariff_profile"], tariff_version=calendar.get("version"),
                clock_basis=options.get("tariff_clock_basis", "local"), calendar_date=start.date().isoformat(),
                tariff_date=logical.get("clock_date", start.date().isoformat()), zone=logical["zone"],
                tier=logical.get("tier"), grid_charge_allowed=logical["grid_charge_allowed"])
    return slots[key], end.timestamp()


def _clean_slots(memory):
    result = {}
    for key, record in memory.get("slots", {}).items() if isinstance(memory.get("slots"), dict) else ():
        if not isinstance(record, dict):
            continue
        try:
            start, end = _stamp(record.get("start")), _stamp(record.get("end"))
            options = ({"tariff_profile": record["profile_id"], "tariff_clock_basis": record.get("clock_basis", "local")}
                       if record.get("profile_id") else None)
            expected_slot, expected_start, expected_end = _slot(start, options)
        except (ValueError, TypeError, OverflowError, OSError):
            continue
        if (end <= start or not all(_number(record.get(k)) and record[k] >= 0 for k in _COUNTERS)
                or not _number(record.get("duration_seconds"))
                or abs(record["duration_seconds"] - (end - start)) > .001
                or record.get("slot") != expected_slot
                or expected_start.timestamp() != start or expected_end.timestamp() != end
                or record["seconds_valid"] + record["seconds_missing"] > end - start + .001):
            continue
        result[_record_key(expected_start, options)] = deepcopy(record)
    return result


def _finish(result, now, options=None):
    slots = result["slots"]
    retained = [(key, record) for key, record in slots.items()
                if _stamp(record["end"]) > now - RETENTION_SECONDS
                and _stamp(record["start"]) <= now]
    retained.sort(key=lambda pair: _stamp(pair[1]["start"]))
    result["slots"] = dict(retained[-(168 if options is not None else MAX_SLOTS):])
    for record in result["slots"].values():
        duration = record["duration_seconds"]
        record["closed"] = now >= _stamp(record["end"])
        record["coverage"] = min(1., record["seconds_valid"] / duration) if duration > 0 else 0.
        record["complete"] = (record["closed"] and record["seconds_missing"] < .001
                              and record["seconds_valid"] >= duration - .001)
        if record["complete"]:
            record["reason"] = "complete_observed_slot"
        elif record["seconds_missing"] > 0:
            record["reason"] = "incomplete_coverage"
        else:
            record["reason"] = "measuring"
    key = _record_key(_slot(now, options)[1], options)
    result["current_slot"] = key if key in result["slots"] else None
    result["completed_slots"] = [key for key, row in result["slots"].items() if row["closed"]]
    return result


def update_slot_measurements(memory: dict, sample: dict, options=None) -> dict:
    """Integrate one actual interval, or attribute it to missing coverage."""
    memory = memory if isinstance(memory, dict) else {}
    sample = sample if isinstance(sample, dict) else {}
    result = {"previous": deepcopy(memory.get("previous")), "slots": _clean_slots(memory),
              "reason": "initial_sample"}
    try:
        now = _stamp(sample.get("at", sample.get("timestamp")))
    except (ValueError, TypeError, OverflowError, OSError):
        if isinstance(result["previous"], dict):
            result["previous"]["telemetry_valid"] = False
        result.update(reason="invalid_timestamp", current_slot=memory.get("current_slot"),
                      completed_slots=deepcopy(memory.get("completed_slots", [])))
        return result
    if options is not None and options.get("tariff_profile", "legacy_g13") != "legacy_g13":
        try:
            context = calendar_context(datetime.fromtimestamp(now, TZ), options)
            if context.get("valid") is not True:
                raise ValueError("invalid_tariff_configuration")
        except (ValueError, TypeError, KeyError):
            result.update(previous=None, reason="invalid_tariff_configuration", current_slot=None,
                          completed_slots=deepcopy(memory.get("completed_slots", [])))
            return result
    previous = result["previous"]
    before = None
    if isinstance(previous, dict):
        try:
            before = _stamp(previous.get("at"))
        except (ValueError, TypeError, OverflowError, OSError):
            pass
    valid = (sample.get("telemetry_valid") is True and _number(sample.get("battery_w"))
             and _number(sample.get("grid_w")))
    if before is not None and now <= before:
        result["reason"] = "non_monotonic_timestamp"
        return _finish(result, before, options)
    if before is not None:
        dt = now - before
        was_valid = (previous.get("telemetry_valid") is True
                     and _number(previous.get("battery_w")) and _number(previous.get("grid_w")))
        integrate = 0 < dt <= MAX_INTERVAL_SECONDS and valid and was_valid
        signature = ([options.get("tariff_profile"), options.get("tariff_clock_basis", "local")] if options is not None else None)
        if previous.get("calendar_signature") != signature:
            integrate = False
        result["reason"] = ("integrated" if integrate else "gap_above_30s" if dt > 30
                            else "invalid_telemetry")
        cursor = max(before, now - RETENTION_SECONDS)
        while cursor < now:
            record, end = _record(result["slots"], cursor, options)
            finish = min(now, end)
            seconds = finish - cursor
            if integrate:
                x0, x1 = (cursor - before) / dt, (finish - before) / dt
                def endpoints(key):
                    a, b = previous[key], sample[key]
                    return a + (b - a) * x0, a + (b - a) * x1
                ga, gb = endpoints("grid_w")
                ba, bb = endpoints("battery_w")
                record["seconds_valid"] += seconds
                record["grid_import_kwh"] += _positive_integral(ga, gb, seconds) / 3600000
                record["battery_discharge_kwh"] += _positive_integral(ba, bb, seconds) / 3600000
                record["battery_charge_kwh"] += _positive_integral(-ba, -bb, seconds) / 3600000
            else:
                record["seconds_missing"] += seconds
            cursor = finish
    _record(result["slots"], now, options)
    result["previous"] = dict(at=now, battery_w=sample.get("battery_w") if valid else None,
                              grid_w=sample.get("grid_w") if valid else None,
                              telemetry_valid=valid)
    if options is not None:
        result["previous"]["calendar_signature"] = [options.get("tariff_profile"), options.get("tariff_clock_basis", "local")]
    if before is None and not valid:
        result["reason"] = "invalid_telemetry"
    return _finish(result, now, options)
