"""Versioned Polish tariff-calendar foundation, with no HA or control calls.

``legacy_g13`` is the existing six-slot EMS policy, INCLUDING on holidays and
weekends. It is deliberately not described as a complete operator tariff.
``tauron_g13_2026`` is a read-only preview of the published operator calendar;
selecting it here never activates a hardware schedule or changes an EMS option.

Intervals are half-open and use UTC timestamps for comparison/duration. Public
ISO timestamps are converted to Europe/Warsaw so a fixed-CET meter can be
understood without confusing its clock with seasonal tariff rules. A local
calendar day always has full coverage, including the 23-/25-hour DST days.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


WARSAW = ZoneInfo("Europe/Warsaw")
FIXED_CET = timezone(timedelta(hours=1), "CET")
TAURON_SOURCE = ("https://www.tauron-dystrybucja.pl/-/media/offer-documents/"
                  "dystrybucja/aktualna-taryfa/taryfa-tauron-dystrybucja-2026_ocr.ashx")
HOLIDAYS_SOURCE = "https://eli.gov.pl/eli/DU/2025/296/ogl"

_PROFILES = {
    "legacy_g13": {
        "operator": "custom", "tariff": "legacy_g13",
        "label": "Dotychczasowy harmonogram EMS G13",
        "version": "legacy-1", "source_url": None,
        "preview_only": False, "runtime_allowed": True,
        "valid_from": None, "valid_until": None,
        "description": "Sześć dotychczasowych slotów, codziennie; bez automatycznych wyjątków OSD.",
    },
    "tauron_g13_2026": {
        "operator": "tauron_dystrybucja", "tariff": "G13",
        "label": "TAURON Dystrybucja — G13 (2026, podgląd)",
        "version": "2026", "source_url": TAURON_SOURCE,
        "preview_only": True, "runtime_allowed": False,
        "valid_from": "2026-01-01", "valid_until": "2026-12-31",
        "description": "Podgląd kalendarza operatora; nie steruje falownikiem.",
    },
}


def calendar_profiles():
    """Independent JSON metadata; callers cannot mutate the catalog."""
    return [{"profile_id": key, **value} for key, value in _PROFILES.items()]


def _easter(year):
    """Gregorian computus, valid for supported modern calendar years."""
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
    """Return a named statutory holiday, not an employee's replacement day off.

    Christmas Eve is included from 2025. Operator-specific grandfathered meter
    exceptions require a separate confirmed profile and are not inferred here.
    """
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


def _rows_for_clock_day(day, profile_id, clock_tz):
    winter = day.month in (10, 11, 12, 1, 2, 3)
    peak, late = (16, 21) if winter else (19, 22)
    reason = "winter" if winter else "summer"
    boundaries = ((0, 4, 7, 13, peak, late, 24) if profile_id == "legacy_g13"
                  else (0, 7, 13, peak, late, 24))
    holiday = polish_holiday(day)
    if profile_id != "legacy_g13" and (holiday or day.weekday() >= 5):
        boundaries = (0, 24)
        reason = "holiday:" + holiday if holiday else "weekend"
    midnight = datetime.combine(day, time.min, clock_tz)
    for index, (start_hour, end_hour) in enumerate(zip(boundaries, boundaries[1:]), 1):
        start = midnight + timedelta(hours=start_hour)
        end = midnight + timedelta(hours=end_hour)
        zone = ("morning_peak" if start_hour == 7 else
                "afternoon_peak" if start_hour == peak else "off_peak")
        row = {"start_ts": start.timestamp(), "end_ts": end.timestamp(),
               "zone": zone, "grid_charge_allowed": zone == "off_peak",
               "reason": reason, "season": "winter" if winter else "summer",
               "clock_date": day.isoformat()}
        if profile_id == "legacy_g13":
            row["legacy_slot"] = index
        yield row


def _day_rows(day, profile_id, clock_tz):
    """Clip meter-clock periods to one complete displayed Warsaw day."""
    start = datetime.combine(day, time.min, WARSAW).timestamp()
    end = datetime.combine(day + timedelta(days=1), time.min, WARSAW).timestamp()
    rows = []
    for offset in (-1, 0, 1):
        for item in _rows_for_clock_day(day + timedelta(days=offset), profile_id, clock_tz):
            a, b = max(start, item["start_ts"]), min(end, item["end_ts"])
            if a >= b:
                continue
            row = {key: value for key, value in item.items() if key not in ("start_ts", "end_ts")}
            row.update(start=datetime.fromtimestamp(a, WARSAW).isoformat(),
                       end=datetime.fromtimestamp(b, WARSAW).isoformat(),
                       duration_seconds=int(b - a))
            rows.append(row)
    rows.sort(key=lambda row: datetime.fromisoformat(row["start"]).timestamp())
    return rows


def describe_calendar(now, profile_id="legacy_g13", clock_basis="local"):
    """Return today's/tomorrow's preview, never modify a runtime schedule.

    ``next_change`` is the next interval boundary, including the retained 04:00
    legacy slot split. ``grid_charge_allowed`` is a calendar-policy eligibility,
    not a declaration that all other EMS/BMS/SoC guards permit charging.
    """
    if not isinstance(profile_id, str) or profile_id not in _PROFILES:
        raise ValueError("invalid_tariff_profile")
    if clock_basis not in ("local", "fixed_cet"):
        raise ValueError("invalid_tariff_clock_basis")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("invalid_tariff_timestamp")
    local = now.astimezone(WARSAW)
    clock_tz = WARSAW if clock_basis == "local" else FIXED_CET
    today = _day_rows(local.date(), profile_id, clock_tz)
    tomorrow = _day_rows(local.date() + timedelta(days=1), profile_id, clock_tz)
    current = next(row for row in today if datetime.fromisoformat(row["start"]).timestamp()
                   <= now.timestamp() < datetime.fromisoformat(row["end"]).timestamp())
    metadata = dict(_PROFILES[profile_id])
    day_text = local.date().isoformat()
    valid = (metadata["valid_from"] is None or
             metadata["valid_from"] <= day_text <= metadata["valid_until"])
    return {"profile_id": profile_id, **metadata, "clock_basis": clock_basis,
            "timezone": "Europe/Warsaw", "local_date": day_text,
            "within_validity": valid, "holiday_source_url": HOLIDAYS_SOURCE,
            "today": today, "tomorrow": tomorrow, "current_interval": dict(current),
            "current_zone": current["zone"], "next_change": current["end"]}
