"""Calendar-only checks: no HA, no live actuators and no external services."""
from datetime import date, datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import unittest


PATH = Path(__file__).parents[1] / "custom_components/deye_ems/tariff_calendar.py"
SPEC = importlib.util.spec_from_file_location("offline_tariff_calendar", PATH)
CALENDAR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CALENDAR)


def describe(value, profile="legacy_g13", basis="local"):
    return CALENDAR.describe_calendar(datetime.fromisoformat(value), profile, basis)


def stamp(value):
    return datetime.fromisoformat(value).timestamp()


class TariffCalendarTests(unittest.TestCase):
    def assert_day_coverage(self, rows, hours):
        self.assertEqual(sum(row["duration_seconds"] for row in rows), hours * 3600)
        self.assertTrue(all(stamp(row["end"]) > stamp(row["start"]) for row in rows))
        self.assertTrue(all(stamp(a["end"]) == stamp(b["start"])
                            for a, b in zip(rows, rows[1:])))

    def test_legacy_keeps_six_slots_and_existing_winter_permissions(self):
        result = describe("2026-11-13T06:59:59+01:00")
        self.assertEqual([row["legacy_slot"] for row in result["today"]], list(range(1, 7)))
        self.assertEqual([row["start"][11:16] for row in result["today"]],
                         ["00:00", "04:00", "07:00", "13:00", "16:00", "21:00"])
        self.assertEqual([row["grid_charge_allowed"] for row in result["today"]],
                         [True, True, False, True, False, True])
        self.assertEqual(result["current_interval"]["legacy_slot"], 2)
        self.assertEqual(result["next_change"], "2026-11-13T07:00:00+01:00")
        self.assert_day_coverage(result["today"], 24)

    def test_legacy_does_not_silently_adopt_weekend_or_holiday_exceptions(self):
        for value in ("2026-11-14T08:00:00+01:00", "2026-11-11T08:00:00+01:00"):
            with self.subTest(value=value):
                result = describe(value)
                self.assertEqual(len(result["today"]), 6)
                self.assertFalse(result["current_interval"]["grid_charge_allowed"])
                self.assertTrue(result["runtime_allowed"])

    def test_boundaries_are_exact_and_end_exclusive(self):
        for at, slot, allowed in (("06:59:59", 2, True), ("07:00:00", 3, False),
                                  ("12:59:59", 3, False), ("13:00:00", 4, True),
                                  ("16:00:00", 5, False), ("21:00:00", 6, True)):
            with self.subTest(at=at):
                result = describe(f"2026-11-13T{at}+01:00")
                self.assertEqual(result["current_interval"]["legacy_slot"], slot)
                self.assertEqual(result["current_interval"]["grid_charge_allowed"], allowed)

    def test_season_changes_on_calendar_date_not_dst_date(self):
        march = describe("2026-03-31T17:00:00+02:00")
        april = describe("2026-04-01T17:00:00+02:00")
        september = describe("2026-09-30T17:00:00+02:00")
        october = describe("2026-10-01T17:00:00+02:00")
        self.assertEqual([x["current_zone"] for x in (march, april, september, october)],
                         ["afternoon_peak", "off_peak", "off_peak", "afternoon_peak"])
        self.assertEqual(march["tomorrow"][4]["start"], "2026-04-01T19:00:00+02:00")

    def test_summer_has_required_19_to_22_evening(self):
        result = describe("2026-07-10T20:00:00+02:00")
        self.assertEqual(result["current_interval"]["start"], "2026-07-10T19:00:00+02:00")
        self.assertEqual(result["current_interval"]["end"], "2026-07-10T22:00:00+02:00")

    def test_verified_official_profile_treats_weekend_as_off_peak(self):
        result = describe("2026-11-14T08:00:00+01:00", "tauron_g13_2026")
        self.assertFalse(result["preview_only"])
        self.assertTrue(result["runtime_allowed"])
        self.assertEqual(len(result["today"]), 1)
        self.assertEqual(result["current_zone"], "off_peak")
        self.assertEqual(result["current_interval"]["reason"], "weekend")
        self.assertNotIn("legacy_slot", result["current_interval"])
        self.assertIn("2026", result["source_url"])

    def test_official_weekday_has_no_artificial_four_am_slot(self):
        result = describe("2026-11-13T03:00:00+01:00", "tauron_g13_2026")
        self.assertEqual(len(result["today"]), 5)
        self.assertEqual(result["next_change"], "2026-11-13T07:00:00+01:00")
        self.assertNotIn("04:00", [row["start"][11:16] for row in result["today"]])

    def test_movable_holidays_and_christmas_eve(self):
        expected = {date(2026, 4, 5): "easter", date(2026, 4, 6): "easter_monday",
                    date(2026, 5, 24): "pentecost", date(2026, 6, 4): "corpus_christi",
                    date(2026, 12, 24): "christmas_eve", date(2026, 11, 11): "independence_day"}
        for day, reason in expected.items():
            with self.subTest(day=day):
                self.assertEqual(CALENDAR.polish_holiday(day), reason)
                now = datetime.combine(day, datetime.min.time(), CALENDAR.WARSAW)
                result = CALENDAR.describe_calendar(now, "tauron_g13_2026")
                self.assertEqual(result["current_interval"]["reason"], "holiday:" + reason)
                self.assertEqual(len(result["today"]), 1)
        self.assertIsNone(CALENDAR.polish_holiday(date(2024, 12, 24)))
        self.assertEqual(CALENDAR.polish_holiday(date(2025, 12, 24)), "christmas_eve")

    def test_dst_days_cover_real_23_and_25_hours(self):
        for value, hours in (("2026-03-29T12:00:00+02:00", 23),
                              ("2026-10-25T12:00:00+01:00", 25)):
            with self.subTest(value=value):
                for basis in ("local", "fixed_cet"):
                    result = describe(value, basis=basis)
                    self.assert_day_coverage(result["today"], hours)
                    self.assert_day_coverage(result["tomorrow"], 24)

    def test_repeated_hour_selects_by_timestamp_not_wall_time(self):
        first = describe("2026-10-25T02:30:00+02:00")
        second = describe("2026-10-25T02:30:00+01:00")
        self.assertEqual(first["current_interval"], second["current_interval"])
        self.assertEqual(first["next_change"], "2026-10-25T04:00:00+01:00")

    def test_fixed_cet_clock_moves_summer_slots_in_displayed_local_time(self):
        local = describe("2026-07-10T07:30:00+02:00", "tauron_g13_2026", "local")
        fixed = describe("2026-07-10T07:30:00+02:00", "tauron_g13_2026", "fixed_cet")
        self.assertEqual(local["current_zone"], "morning_peak")
        self.assertEqual(fixed["current_zone"], "off_peak")
        self.assertEqual(fixed["next_change"], "2026-07-10T08:00:00+02:00")
        evening = describe("2026-07-10T20:00:00+02:00", "tauron_g13_2026", "fixed_cet")
        self.assertEqual(evening["current_interval"]["start"], "2026-07-10T20:00:00+02:00")
        self.assertEqual(evening["current_interval"]["end"], "2026-07-10T23:00:00+02:00")
        self.assert_day_coverage(fixed["today"], 24)

    def test_fixed_cet_retains_previous_clock_day_before_local_one_am(self):
        result = describe("2026-04-01T00:30:00+02:00", "tauron_g13_2026", "fixed_cet")
        self.assertEqual(result["current_interval"]["clock_date"], "2026-03-31")
        self.assertEqual(result["current_interval"]["season"], "winter")
        self.assertEqual(result["current_interval"]["end"], "2026-04-01T01:00:00+02:00")

    def test_timestamp_input_can_be_in_utc_and_payload_is_json_only(self):
        now = datetime(2026, 11, 13, 6, 15, tzinfo=timezone.utc)
        result = CALENDAR.describe_calendar(now)
        self.assertEqual(result["current_zone"], "morning_peak")
        self.assertEqual(json.loads(json.dumps(result)), result)

    def test_validity_explicitly_expires_instead_of_claiming_future_tariff(self):
        result = describe("2027-01-04T08:00:00+01:00", "tauron_g13_2026")
        self.assertFalse(result["within_validity"])
        self.assertTrue(result["preview_only"])
        self.assertFalse(result["runtime_allowed"])

    def test_catalog_and_result_mutations_never_modify_future_calls(self):
        profiles = CALENDAR.calendar_profiles()
        profiles[0]["runtime_allowed"] = False
        one = describe("2026-11-13T07:30:00+01:00")
        one["today"][0]["grid_charge_allowed"] = False
        one["current_interval"]["zone"] = "edited"
        two = describe("2026-11-13T07:30:00+01:00")
        self.assertTrue(two["runtime_allowed"])
        self.assertTrue(two["today"][0]["grid_charge_allowed"])
        self.assertEqual(two["current_zone"], "morning_peak")

    def test_invalid_profile_clock_and_naive_timestamp_are_rejected(self):
        valid = datetime.fromisoformat("2026-11-13T07:00:00+01:00")
        for profile in (None, [], "unknown"):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                CALENDAR.describe_calendar(valid, profile_id=profile)
        for basis in (None, "automatic", "unconfirmed"):
            with self.subTest(basis=basis), self.assertRaises(ValueError):
                CALENDAR.describe_calendar(valid, clock_basis=basis)
        for now in (None, "2026-11-13T07:00:00+01:00", datetime(2026, 11, 13)):
            with self.subTest(now=now), self.assertRaises(ValueError):
                CALENDAR.describe_calendar(now)


if __name__ == "__main__":
    unittest.main()
