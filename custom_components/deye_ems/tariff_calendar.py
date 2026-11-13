"""Versioned OSD calendars and planning windows; no HA, prices or device I/O.

The legacy six-slot policy is deliberately unchanged. Operator profiles require
an explicit contract/clock confirmation at runtime. All comparisons and duration
calculations use UTC instants, independently of the confirmed meter clock.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo


WARSAW = ZoneInfo("Europe/Warsaw")
FIXED_CET = timezone(timedelta(hours=1), "CET")
UTC = timezone.utc
TAURON_SOURCE = ("https://www.tauron-dystrybucja.pl/-/media/offer-documents/"
                  "dystrybucja/aktualna-taryfa/taryfa-tauron-dystrybucja-2026_ocr.ashx")
HOLIDAYS_SOURCE = "https://eli.gov.pl/eli/DU/2025/296/ogl"
_CATALOG = json.loads(Path(__file__).with_name("tariff_profiles.json").read_text(encoding="utf-8"))
_LEGACY = {
    "operator": "custom", "tariff": "legacy_g13",
    "label": "Dotychczasowy harmonogram EMS G13", "version": "legacy-1",
    "source_url": None, "source_pages": [], "preview_only": False,
    "runtime_allowed": True, "supported": True, "valid_from": None,
    "valid_until": None, "clock_confirmation_required": False,
    "requires_contract_confirmation": False,
    "description": "Sześć dotychczasowych slotów, codziennie; bez automatycznych wyjątków OSD.",
}
_PROFILES = {"legacy_g13": _LEGACY, **{
    item["profile_id"]: {key: value for key, value in item.items() if key != "profile_id"}
    for item in _CATALOG["profiles"]}}
_OPERATOR_LABELS = {"custom": "Dotychczasowy harmonogram EMS",
                    **{row["operator_id"]: row["label"] for row in _CATALOG["operators"]}}
for _item in _PROFILES.values():
    _item["operator_id"] = _item["operator"]
    _item["operator_label"] = _OPERATOR_LABELS[_item["operator"]]
    _item.setdefault("blocked_reason", None)
    _item.setdefault("requirements", [])
    if _item["operator"] != "custom":
        _item["requires_contract_confirmation"] = True


def calendar_operators():
    """Return the five requested OSDs plus the preserved custom legacy policy."""
    return [{"operator_id": "custom", "label": "Dotychczasowy harmonogram EMS"},
            *deepcopy(_CATALOG["operators"])]


def calendar_profiles(operator_id=None):
    """Independent JSON metadata; mutation never changes the embedded catalog."""
    if operator_id is not None and (not isinstance(operator_id, str)
            or operator_id not in {row["operator_id"] for row in calendar_operators()}):
        raise ValueError("invalid_tariff_operator")
    return [{"profile_id": key, **deepcopy(value)} for key, value in _PROFILES.items()
            if operator_id is None or value["operator"] == operator_id]


def _profile(profile_id):
    if not isinstance(profile_id, str) or profile_id not in _PROFILES:
        raise ValueError("invalid_tariff_profile")
    return _PROFILES[profile_id]


def _clock(clock_basis):
    if clock_basis not in ("local", "fixed_cet"):
        raise ValueError("invalid_tariff_clock_basis")
    return WARSAW if clock_basis == "local" else FIXED_CET


def _timestamp(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("invalid_tariff_timestamp")
    return value.timestamp()


def _easter(year):
    """Gregorian computus for the modern calendar."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day0 = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day0 + 1)


def polish_holiday(day):
    """Named statutory holiday, never an employer's compensatory day off."""
    if not isinstance(day, date) or isinstance(day, datetime):
        raise ValueError("invalid_calendar_date")
    fixed = {(1, 1): "new_year", (1, 6): "epiphany", (5, 1): "labour_day",
             (5, 3): "constitution_day", (8, 15): "assumption",
             (11, 1): "all_saints", (11, 11): "independence_day",
             (12, 25): "christmas", (12, 26): "boxing_day"}
    if day.year >= 2025:
        fixed[(12, 24)] = "christmas_eve"
    found = fixed.get((day.month, day.day))
    if found:
        return found
    easter = _easter(day.year)
    return {easter: "easter", easter + timedelta(days=1): "easter_monday",
            easter + timedelta(days=49): "pentecost",
            easter + timedelta(days=60): "corpus_christi"}.get(day)


def _within_validity(day, profile):
    text = day.isoformat()
    return ((profile["valid_from"] is None or text >= profile["valid_from"])
            and (profile["valid_until"] is None or text <= profile["valid_until"]))


def _minute(value):
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def _contains(minute, window):
    start, end = map(_minute, window)
    return start <= minute < end if start < end else minute >= start or minute < end


def _segments(day, profile_id, profile):
    """Return wall-clock minute segments, before timezone conversion."""
    winter = day.month in (10, 11, 12, 1, 2, 3)
    season = "winter" if winter else "summer"
    holiday = polish_holiday(day)
    reason = season
    if profile_id == "legacy_g13":
        peak, late = (16 * 60, 21 * 60) if winter else (19 * 60, 22 * 60)
        bounds = (0, 240, 420, 780, peak, late, 1440)
        return [{"a": a, "b": b, "zone": "morning_peak" if a == 420 else
                 "afternoon_peak" if a == peak else "off_peak",
                 "tier": 1 if a == 420 else 2 if a == peak else 0,
                 "reason": reason, "legacy_slot": index}
                for index, (a, b) in enumerate(zip(bounds, bounds[1:]), 1)]

    all_day = profile.get("all_day_low_on", [])
    free = ((holiday and "statutory_holiday" in all_day)
            or (day.weekday() == 5 and "saturday" in all_day)
            or (day.weekday() == 6 and "sunday" in all_day))
    if free:
        return [{"a": 0, "b": 1440,
                 "zone": "off_peak" if profile["tariff"] == "G13" else "low",
                 "tier": 0, "reason": "holiday:" + holiday if holiday else "weekend"}]
    if profile.get("default_zone") == "flat":
        return [{"a": 0, "b": 1440, "zone": "flat", "tier": 0, "reason": "flat_tariff"}]

    windows = []
    default_zone, default_tier = profile.get("default_zone", "high"), 2
    if profile["tariff"] == "G13":
        default_zone, default_tier = "off_peak", 0
        for index, window in enumerate(profile["seasonal_high_windows"][season], 1):
            windows.append(("morning_peak" if index == 1 else "afternoon_peak", index, window))
    elif "seasonal_zones" in profile:
        order = profile["ascending_preference"][season]
        for zone, values in profile["seasonal_zones"][season].items():
            windows.extend((zone, order.index(zone), window) for window in values)
        default_tier = order.index(default_zone)
    else:
        monthly = profile.get("monthly_windows", {}).get(str(day.month), {})
        low = monthly.get("low", profile.get("seasonal_low_windows", {}).get(season,
                                                                              profile.get("low_windows", [])))
        high = monthly.get("high", profile.get("high_windows", []))
        windows.extend(("low", 0, window) for window in low)
        windows.extend(("high", 2, window) for window in high)
        if default_zone == "normal":
            default_tier = 1
    bounds = sorted({0, 1440, *(_minute(value) for _, _, window in windows for value in window)})
    segments = []
    for a, b in zip(bounds, bounds[1:]):
        matches = [(zone, tier) for zone, tier, window in windows if _contains(a, window)]
        if len(matches) > 1:
            raise ValueError("overlapping_tariff_zones")
        zone, tier = matches[0] if matches else (default_zone, default_tier)
        if segments and segments[-1]["zone"] == zone and segments[-1]["tier"] == tier:
            segments[-1]["b"] = b
        else:
            segments.append({"a": a, "b": b, "zone": zone, "tier": tier, "reason": reason})
    return segments


def _rows_for_clock_day(day, profile_id, clock_tz):
    profile = _profile(profile_id)
    midnight = datetime.combine(day, time.min, clock_tz)
    season = "winter" if day.month in (10, 11, 12, 1, 2, 3) else "summer"
    for segment in _segments(day, profile_id, profile):
        start = (midnight + timedelta(minutes=segment["a"])).timestamp()
        end = (midnight + timedelta(minutes=segment["b"])).timestamp()
        if end <= start:
            continue
        yield {"start_ts": start, "end_ts": end,
               **{key: value for key, value in segment.items() if key not in ("a", "b")},
               "grid_charge_allowed": segment["tier"] == 0, "protected": segment["tier"] > 0,
               "season": season, "clock_date": day.isoformat(),
               "within_validity": _within_validity(day, profile),
               "profile_id": profile_id, "version": profile["version"]}


def _serialize_row(row, tz=UTC):
    result = dict(row)
    duration = row["end_ts"] - row["start_ts"]
    result.update(start=datetime.fromtimestamp(row["start_ts"], tz).isoformat(),
                  end=datetime.fromtimestamp(row["end_ts"], tz).isoformat(),
                  duration_seconds=int(duration) if duration.is_integer() else duration)
    return result


def intervals_between(start, end, profile_id="legacy_g13", clock_basis="local"):
    """Full, gap-free UTC coverage of [start,end), including DST and month changes.

    Tier is an ordinal calendar preference (0 lowest), not a monetary price.
    Grid-charge permission only permits considering charging; battery, forecast,
    summer emergency policy, power limits and contract validity still apply.
    """
    profile, clock_tz = _profile(profile_id), _clock(clock_basis)
    a, b = _timestamp(start), _timestamp(end)
    if b < a:
        raise ValueError("invalid_tariff_range")
    if not profile["supported"]:
        raise ValueError("unsupported_tariff_profile")
    if a == b:
        return []
    first = datetime.fromtimestamp(a, clock_tz).date()
    last = datetime.fromtimestamp(b, clock_tz).date()
    rows = []
    day = first
    while day <= last:
        for item in _rows_for_clock_day(day, profile_id, clock_tz):
            left, right = max(a, item["start_ts"]), min(b, item["end_ts"])
            if left < right:
                rows.append(_serialize_row({**item, "start_ts": left, "end_ts": right}))
        day += timedelta(days=1)
    return rows


def _day_rows(day, profile_id, clock_tz):
    start = datetime.combine(day, time.min, WARSAW)
    end = datetime.combine(day + timedelta(days=1), time.min, WARSAW)
    basis = "local" if clock_tz is WARSAW else "fixed_cet"
    return [_serialize_row(row, WARSAW) for row in intervals_between(start, end, profile_id, basis)]


def describe_calendar(now, profile_id="legacy_g13", clock_basis="local"):
    """JSON preview in Warsaw wall time; viewing never activates a profile."""
    profile, clock_tz = _profile(profile_id), _clock(clock_basis)
    _timestamp(now)
    local = now.astimezone(WARSAW)
    supported = profile["supported"]
    today = _day_rows(local.date(), profile_id, clock_tz) if supported else []
    tomorrow = _day_rows(local.date() + timedelta(days=1), profile_id, clock_tz) if supported else []
    current = next((row for row in today if row["start_ts"] <= now.timestamp() < row["end_ts"]), None)
    valid = _within_validity(now.astimezone(clock_tz).date(), profile)
    return {"profile_id": profile_id, **deepcopy(profile), "clock_basis": clock_basis,
            "preview_only": bool(profile["preview_only"] or not valid),
            "runtime_allowed": bool(profile["runtime_allowed"] and valid),
            "timezone": "Europe/Warsaw", "local_date": local.date().isoformat(),
            "within_validity": valid, "holiday_source_url": HOLIDAYS_SOURCE,
            "today": today, "tomorrow": tomorrow, "current_interval": current,
            "current_zone": current["zone"] if current else None,
            "next_change": current["end"] if current else None}


def _merge_windows(rows):
    """Merge eligibility, not individual zone names, over day/month boundaries."""
    windows = []
    for row in rows:
        allowed = row["grid_charge_allowed"] and row["within_validity"]
        if (windows and windows[-1]["grid_charge_allowed"] == allowed
                and windows[-1]["within_validity"] == row["within_validity"]
                and windows[-1]["end_ts"] == row["start_ts"]):
            windows[-1]["end_ts"] = row["end_ts"]
            windows[-1]["end"] = row["end"]
        else:
            windows.append({key: row[key] for key in ("start", "end", "start_ts", "end_ts")}
                           | {"grid_charge_allowed": allowed, "protected": not allowed,
                              "within_validity": row["within_validity"]})
    return windows


def calendar_context(now, options):
    """Runtime context with contiguous cheap/protected windows and strict ACK.

    Recognized blocked/expired/unconfirmed profiles return valid=False with no
    planning windows. Unknown identifiers raise instead of becoming legacy G13.
    A flat tariff has no real deadline: its continuous window has null endpoints.
    """
    _timestamp(now)
    profile_id = options.get("tariff_profile", "legacy_g13")
    basis = options.get("tariff_clock_basis", "local")
    profile, clock_tz = _profile(profile_id), _clock(basis)
    day = now.astimezone(clock_tz).date()
    within = _within_validity(day, profile)
    issue = (profile.get("blocked_reason", "unsupported_tariff_profile") if not profile["supported"]
             else "tariff_outside_validity" if not within
             else "tariff_contract_confirmation_required" if profile_id != "legacy_g13"
             and options.get("tariff_contract_confirmed") is not True
             else "tariff_clock_confirmation_required" if profile_id != "legacy_g13"
             and "tariff_clock_basis" not in options else None)
    context = {"valid": issue is None, "issue": issue, "profile_id": profile_id,
               "operator_id": profile["operator_id"], "operator": profile["operator"],
               "operator_label": profile["operator_label"], "tariff": profile["tariff"],
               "clock_basis": basis, "metadata": {"profile_id": profile_id, **deepcopy(profile)},
               "within_validity": within, "current_interval": None, "charge_window": None,
               "next_charge_window": None, "protected_windows": [], "deadlines": [],
               "next_deadline": None, "protected_until": None}
    if issue:
        return context
    stamp = now.timestamp()
    # Full neighboring days avoid fictitious midnight deadlines and cover chains
    # of statutory holidays and weekends on either side of the current instant.
    scan_start = datetime.combine(day - timedelta(days=14), time.min, clock_tz)
    scan_end = datetime.combine(day + timedelta(days=15), time.min, clock_tz)
    rows = intervals_between(scan_start, scan_end, profile_id, basis)
    current = next(row for row in rows if row["start_ts"] <= stamp < row["end_ts"])
    context["current_interval"] = current
    context["season"] = current["season"]
    windows = _merge_windows(rows)
    for window in windows:
        window["id"] = f"{profile_id}:{basis}:{int(window['start_ts'])}"
        window["continuous"] = False
    if profile.get("default_zone") == "flat":
        context["charge_window"] = {"id": f"{profile_id}:{basis}:continuous", "start": None,
            "end": None, "start_ts": None, "end_ts": None, "continuous": True,
            "grid_charge_allowed": True, "protected": False}
        return context
    active = next(row for row in windows if row["start_ts"] <= stamp < row["end_ts"])
    if active["grid_charge_allowed"]:
        context["charge_window"] = active
    else:
        context["protected_until"] = active["end"]
    context["next_charge_window"] = next((row for row in windows
        if row["grid_charge_allowed"] and row["start_ts"] > stamp), None)
    # Keep full endpoints, including current noncheap coverage and all future
    # normal/peak segments merged together; this covers well over 48 real hours.
    protected = [row for row in windows if row["protected"] and row["within_validity"] and row["end_ts"] > stamp]
    context["protected_windows"] = protected
    context["deadlines"] = [row["start"] for row in protected if row["start_ts"] > stamp]
    context["next_deadline"] = next(iter(context["deadlines"]), None)
    return context
