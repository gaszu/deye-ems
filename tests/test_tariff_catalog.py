"""Official-calendar boundary and planning-window regressions, entirely offline."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import unittest


PATH = Path(__file__).parents[1] / "custom_components/deye_ems/tariff_calendar.py"
SPEC = importlib.util.spec_from_file_location("offline_tariff_catalog", PATH)
CAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAL)


def dt(value):
    return datetime.fromisoformat(value)


def preview(value, profile, basis="local"):
    return CAL.describe_calendar(dt(value), profile, basis)


def context(value, profile, **options):
    return CAL.calendar_context(dt(value), {"tariff_profile": profile,
        "tariff_clock_basis": "local", "tariff_contract_confirmed": True, **options})


class CatalogTests(unittest.TestCase):
    def test_exact_requested_operator_scope_and_profiles_have_primary_sources(self):
        expected = {"custom", "tauron_dystrybucja", "pge_dystrybucja", "enea_operator",
                    "energa_operator", "pge_energetyka_kolejowa"}
        self.assertEqual({p["operator_id"] for p in CAL.calendar_operators()}, expected)
        profiles = CAL.calendar_profiles()
        self.assertEqual(len({p["profile_id"] for p in profiles}), len(profiles))
        self.assertNotIn("stoen", json.dumps(profiles).lower())
        for operator in expected:
            selected = CAL.calendar_profiles(operator)
            self.assertTrue(selected)
            self.assertTrue(all(p["operator"] == p["operator_id"] == operator for p in selected))
        for profile in profiles:
            if profile["profile_id"] == "legacy_g13":
                continue
            with self.subTest(profile=profile["profile_id"]):
                self.assertTrue(profile["source_url"].startswith("https://"))
                self.assertTrue(profile["source_pages"])
                self.assertEqual(profile["valid_until"], "2026-12-31")
                self.assertTrue(profile["requires_contract_confirmation"])
                self.assertTrue(profile["clock_confirmation_required"])

    def test_catalog_lists_only_actual_g13_variants(self):
        for operator in ("pge_dystrybucja", "energa_operator", "pge_energetyka_kolejowa"):
            self.assertFalse(any(p["tariff"].startswith("G13") for p in CAL.calendar_profiles(operator)))
        self.assertIn("G13active", {p["tariff"] for p in CAL.calendar_profiles("enea_operator")})
        self.assertNotIn("G13", {p["tariff"] for p in CAL.calendar_profiles("enea_operator")})

    def test_contract_ack_is_strict_and_never_implicitly_migrates_legacy(self):
        now = dt("2026-11-13T02:00:00+01:00")
        for ack in (None, False, 1, "true", [], {}):
            with self.subTest(ack=ack):
                result = CAL.calendar_context(now, {"tariff_profile": "tauron_g12_2026",
                                                    "tariff_contract_confirmed": ack})
                self.assertFalse(result["valid"])
                self.assertEqual(result["issue"], "tariff_contract_confirmation_required")
                self.assertIsNone(result["current_interval"])
                self.assertEqual(result["protected_windows"], [])
                self.assertIsNone(result["charge_window"])
        legacy = CAL.calendar_context(now, {})
        self.assertTrue(legacy["valid"])
        self.assertEqual(legacy["profile_id"], "legacy_g13")
        self.assertEqual(legacy["current_interval"]["legacy_slot"], 1)
        self.assertTrue(context(now.isoformat(), "tauron_g12_2026")["valid"])

    def test_known_unsupported_groups_are_visible_but_never_get_fallback_windows(self):
        for profile, reason in (("pge_g12e_2026", "unverified_region_schedule"),
                                ("tauron_g14dynamic_2026", "dynamic_feed_required")):
            with self.subTest(profile=profile):
                result = context("2026-11-13T02:00:00+01:00", profile)
                self.assertFalse(result["valid"])
                self.assertEqual(result["issue"], reason)
                self.assertEqual(result["profile_id"], profile)
                self.assertEqual(result["protected_windows"], [])
                view = preview("2026-11-13T02:00:00+01:00", profile)
                self.assertEqual(view["today"], [])
                self.assertIsNone(view["current_zone"])
                self.assertFalse(view["runtime_allowed"])
                with self.assertRaisesRegex(ValueError, "unsupported_tariff_profile"):
                    CAL.intervals_between(dt("2026-11-13T00:00:00+01:00"),
                                          dt("2026-11-14T00:00:00+01:00"), profile)

    def test_invalid_saved_profile_and_clock_raise_instead_of_legacy_fallback(self):
        now = dt("2026-11-13T02:00:00+01:00")
        for values in ({"tariff_profile": "unknown"}, {"tariff_profile": []},
                       {"tariff_clock_basis": "automatic"}, {"tariff_clock_basis": None}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                CAL.calendar_context(now, values)

    def test_real_profile_with_ack_but_missing_clock_cannot_silently_assume_local(self):
        result = CAL.calendar_context(dt("2026-11-13T02:00:00+01:00"),
            {"tariff_profile": "tauron_g12_2026", "tariff_contract_confirmed": True})
        self.assertFalse(result["valid"])
        self.assertEqual(result["issue"], "tariff_clock_confirmation_required")
        self.assertIsNone(result["charge_window"])

    def test_g12as_uses_verified_hours_and_does_not_promise_volume_discount(self):
        for prefix in ("tauron", "pge", "enea", "energa", "pge_ek"):
            profile = prefix + "_g12as_2026"
            day = context("2026-11-13T13:30:00+01:00", profile)
            night = context("2026-11-13T23:30:00+01:00", profile)
            self.assertTrue(day["valid"])
            self.assertFalse(day["current_interval"]["grid_charge_allowed"])
            self.assertTrue(night["current_interval"]["grid_charge_allowed"])
            self.assertIn("przyrost", night["metadata"]["notice"])
            self.assertIn("nie potwierdza", night["metadata"]["notice"].lower())

    def test_expired_official_context_is_invalid_while_legacy_remains_its_own_policy(self):
        view = context("2027-01-01T00:00:00+01:00", "energa_g12_2026")
        self.assertFalse(view["valid"])
        self.assertFalse(view["within_validity"])
        self.assertEqual(view["issue"], "tariff_outside_validity")
        self.assertEqual(view["protected_windows"], [])
        self.assertTrue(context("2027-01-01T00:00:00+01:00", "legacy_g13")["valid"])
        rows = CAL.intervals_between(dt("2026-12-31T23:00:00+01:00"),
                                     dt("2027-01-01T01:00:00+01:00"), "energa_g12_2026")
        self.assertEqual([r["within_validity"] for r in rows], [True, False])

    def test_nested_catalog_and_runtime_result_mutations_cannot_change_future_calls(self):
        profile = next(p for p in CAL.calendar_profiles() if p["profile_id"] == "enea_g13active_2026")
        profile["monthly_windows"]["1"]["low"][0][0] = "12:00"
        profile["requirements"].append("mutated")
        first = context("2026-01-13T23:30:00+01:00", "enea_g13active_2026")
        saved = deepcopy(first)
        first["metadata"]["monthly_windows"]["1"]["low"][0][0] = "14:00"
        first["charge_window"]["end"] = "edited"
        self.assertEqual(context("2026-01-13T23:30:00+01:00", "enea_g13active_2026"), saved)


class ScheduleBoundaryTests(unittest.TestCase):
    def assert_allowed(self, profile, value, allowed, basis="local"):
        self.assertEqual(preview(value, profile, basis)["current_interval"]["grid_charge_allowed"], allowed)

    def test_regular_g12_exact_end_exclusive_hours_for_four_osds(self):
        for prefix in ("tauron", "enea", "energa", "pge_ek"):
            for at, allowed in (("05:59:59", True), ("06:00:00", False),
                                ("12:59:59", False), ("13:00:00", True),
                                ("14:59:59", True), ("15:00:00", False),
                                ("21:59:59", False), ("22:00:00", True)):
                with self.subTest(prefix=prefix, at=at):
                    self.assert_allowed(prefix + "_g12_2026", f"2026-11-13T{at}+01:00", allowed)

    def test_pge_midday_g12_really_changes_on_april_and_october_first(self):
        for value, allowed in (("2026-03-31T13:30:00+02:00", True),
                               ("2026-04-01T13:30:00+02:00", False),
                               ("2026-04-01T15:30:00+02:00", True),
                               ("2026-09-30T15:30:00+02:00", True),
                               ("2026-10-01T15:30:00+02:00", False),
                               ("2026-10-01T13:30:00+02:00", True)):
            with self.subTest(value=value):
                self.assert_allowed("pge_g12_2026", value, allowed)

    def test_enea_g12w_has_nine_hour_night_and_no_midday_cheap_period(self):
        for at, allowed in (("05:59:59", True), ("06:00:00", False),
                            ("13:30:00", False), ("20:59:59", False), ("21:00:00", True)):
            self.assert_allowed("enea_g12w_2026", f"2026-11-13T{at}+01:00", allowed)
        for prefix in ("tauron", "energa", "pge_ek"):
            self.assert_allowed(prefix + "_g12w_2026", "2026-11-13T13:30:00+01:00", True)
            self.assert_allowed(prefix + "_g12w_2026", "2026-11-13T21:30:00+01:00", False)

    def test_g12w_statutory_holidays_and_weekends_are_real_dates(self):
        for prefix in ("tauron", "pge", "enea", "energa", "pge_ek"):
            for day in ("2026-11-14", "2026-11-15", "2026-11-11", "2026-12-24", "2026-06-04"):
                with self.subTest(prefix=prefix, day=day):
                    self.assert_allowed(prefix + "_g12w_2026", day + "T10:00:00+01:00", True)
            # A compensatory Friday off at an employer is not a statutory day.
            self.assert_allowed(prefix + "_g12w_2026", "2026-05-22T10:00:00+02:00", False)

    def test_pge_g12n_does_not_mistake_ordinary_saturday_for_all_day_cheap(self):
        self.assert_allowed("pge_g12n_2026", "2026-11-14T10:00:00+01:00", False)
        self.assert_allowed("pge_g12n_2026", "2026-11-14T01:00:00+01:00", True)
        self.assert_allowed("pge_g12n_2026", "2026-11-14T05:00:00+01:00", False)
        self.assert_allowed("pge_g12n_2026", "2026-11-15T10:00:00+01:00", True)

    def test_energa_g12r_is_13_to16_and22_to7_without_weekend_exception(self):
        for at, allowed in (("06:59:59", True), ("07:00:00", False),
                            ("13:00:00", True), ("15:59:59", True),
                            ("16:00:00", False), ("22:00:00", True)):
            self.assert_allowed("energa_g12r_2026", f"2026-11-14T{at}+01:00", allowed)

    def test_tauron_g13s_seasonal_preference_does_not_erase_weekend_peaks(self):
        for value, zone, tier in (("2026-07-11T08:00:00+02:00", "day_peak", 2),
                                  ("2026-07-11T12:00:00+02:00", "day_offpeak", 0),
                                  ("2026-07-11T23:00:00+02:00", "night", 1),
                                  ("2026-11-14T12:00:00+01:00", "day_offpeak", 1),
                                  ("2026-11-14T17:00:00+01:00", "day_peak", 2),
                                  ("2026-11-14T23:00:00+01:00", "night", 0)):
            with self.subTest(value=value):
                row = preview(value, "tauron_g13s_2026")["current_interval"]
                self.assertEqual((row["zone"], row["tier"]), (zone, tier))
                self.assertEqual(row["grid_charge_allowed"], tier == 0)

    def test_enea_season_profile_keeps_weekend_and_month_separate(self):
        for value, allowed in (("2026-07-11T02:00:00+02:00", False),
                               ("2026-07-11T04:00:00+02:00", True),
                               ("2026-07-11T09:00:00+02:00", True),
                               ("2026-07-11T17:00:00+02:00", False),
                               ("2026-11-14T11:00:00+01:00", True),
                               ("2026-11-14T13:00:00+01:00", False),
                               ("2026-11-14T22:00:00+01:00", True)):
            self.assert_allowed("enea_g12sezon_2026", value, allowed)

    def test_enea_g13active_all_months_with_independent_boundary_fixtures(self):
        # Known published low/high samples; Sundays keep the monthly schedule.
        expected = [(1, "02:00", "08:00"), (2, "02:00", "08:00"),
                    (3, "12:00", "22:00"), (4, "12:00", "22:00"),
                    (5, "12:00", "08:00"), (6, "12:00", "08:00"),
                    (7, "12:00", "08:00"), (8, "12:00", "08:00"),
                    (9, "12:00", "22:00"), (10, "12:00", "22:00"),
                    (11, "02:00", "14:00"), (12, "02:00", "13:00")]
        for month, low, high in expected:
            with self.subTest(month=month):
                suffix = "+02:00" if 4 <= month <= 10 else "+01:00"
                row = preview(f"2026-{month:02}-15T{low}:00{suffix}", "enea_g13active_2026")["current_interval"]
                self.assertEqual(row["tier"], 0)
                row = preview(f"2026-{month:02}-15T{high}:00{suffix}", "enea_g13active_2026")["current_interval"]
                self.assertEqual(row["tier"], 2)
        self.assert_allowed("enea_g13active_2026", "2026-11-15T14:00:00+01:00", False)
        self.assert_allowed("enea_g13active_2026", "2026-11-11T14:00:00+01:00", False)
        self.assertEqual(len(preview("2026-01-13T12:00:00+01:00", "enea_g13active_2026")["today"]), 7)


class PlanningWindowsTests(unittest.TestCase):
    def test_night_window_spans_midnight_and_legacy_four_am_without_reset(self):
        for value in ("2026-11-13T22:00:00+01:00", "2026-11-14T02:00:00+01:00",
                      "2026-11-14T04:00:00+01:00"):
            result = context(value, "legacy_g13")["charge_window"]
            self.assertEqual(result["start"], "2026-11-13T20:00:00+00:00")
            self.assertEqual(result["end"], "2026-11-14T06:00:00+00:00")
            self.assertFalse(result["continuous"])

    def test_weekend_holiday_chain_has_one_stable_window_and_real_monday_deadline(self):
        results = [context(value, "tauron_g12w_2026") for value in (
            "2026-12-23T23:00:00+01:00", "2026-12-25T12:00:00+01:00",
            "2026-12-27T23:00:00+01:00")]
        windows = [r["charge_window"] for r in results]
        self.assertTrue(all(w["id"] == windows[0]["id"] for w in windows))
        self.assertEqual(windows[0]["start"], "2026-12-23T21:00:00+00:00")
        self.assertEqual(windows[0]["end"], "2026-12-28T05:00:00+00:00")
        self.assertTrue(all(r["next_deadline"] == windows[0]["end"] for r in results))

    def test_noncheap_normal_and_peak_segments_are_one_coverage_window(self):
        result = context("2026-11-13T08:00:00+01:00", "enea_g13active_2026")
        self.assertIsNone(result["charge_window"])
        first = result["protected_windows"][0]
        self.assertEqual(first["start"], "2026-11-13T05:00:00+00:00")
        self.assertEqual(first["end"], "2026-11-13T22:00:00+00:00")
        self.assertEqual(result["protected_until"], first["end"])
        self.assertEqual(result["next_charge_window"]["start"], first["end"])
        self.assertGreater(result["protected_windows"][-1]["end_ts"],
                           dt("2026-11-15T08:00:00+01:00").timestamp())

    def test_flat_calendar_has_no_fictitious_operator_deadline(self):
        for prefix in ("tauron", "pge", "enea", "energa", "pge_ek"):
            result = context("2026-11-13T02:00:00+01:00", prefix + "_g11_2026")
            self.assertTrue(result["valid"])
            self.assertTrue(result["charge_window"]["continuous"])
            self.assertIsNone(result["charge_window"]["start_ts"])
            self.assertIsNone(result["charge_window"]["end_ts"])
            self.assertIsNone(result["next_deadline"])
            self.assertIsNone(result["next_charge_window"])
            self.assertEqual(result["protected_windows"], [])

    def test_calendar_expiry_is_not_invented_as_an_operator_protected_zone(self):
        result = context("2026-12-31T23:00:00+01:00", "energa_g12_2026")
        self.assertEqual(result["charge_window"]["end"], "2026-12-31T23:00:00+00:00")
        self.assertFalse(any(w["start_ts"] >= dt("2027-01-01T00:00:00+01:00").timestamp()
                             for w in result["protected_windows"]))

    def test_arbitrary_range_is_clipped_exactly_and_serializes_utc(self):
        a, b = dt("2026-11-13T12:59:59.500+01:00"), dt("2026-11-13T15:00:00.250+01:00")
        rows = CAL.intervals_between(a, b, "energa_g12_2026")
        self.assertEqual(rows[0]["start_ts"], a.timestamp())
        self.assertEqual(rows[-1]["end_ts"], b.timestamp())
        self.assertTrue(all(r["start"].endswith("+00:00") for r in rows))
        self.assertEqual([r["grid_charge_allowed"] for r in rows], [False, True, False])
        self.assertEqual(sum(r["duration_seconds"] for r in rows), b.timestamp() - a.timestamp())
        self.assertTrue(all(x["end_ts"] == y["start_ts"] for x, y in zip(rows, rows[1:])))
        self.assertEqual(json.loads(json.dumps(rows)), rows)
        self.assertEqual(CAL.intervals_between(a, a), [])
        with self.assertRaisesRegex(ValueError, "invalid_tariff_range"):
            CAL.intervals_between(b, a)

    def test_every_verified_profile_covers_all_months_and_both_dst_days_without_gaps(self):
        samples = [f"2026-{month:02}-15T00:00:00" for month in range(1, 13)]
        samples += ["2026-03-29T00:00:00", "2026-10-25T00:00:00"]
        for profile in CAL.calendar_profiles():
            if not profile["supported"]:
                continue
            for value in samples:
                start = datetime.fromisoformat(value).replace(tzinfo=CAL.WARSAW)
                end = start + timedelta(days=1)
                for basis in ("local", "fixed_cet"):
                    with self.subTest(profile=profile["profile_id"], value=value, basis=basis):
                        rows = CAL.intervals_between(start, end, profile["profile_id"], basis)
                        self.assertEqual(rows[0]["start_ts"], start.timestamp())
                        self.assertEqual(rows[-1]["end_ts"], end.timestamp())
                        self.assertTrue(all(r["end_ts"] > r["start_ts"] for r in rows))
                        self.assertTrue(all(x["end_ts"] == y["start_ts"] for x, y in zip(rows, rows[1:])))
                        self.assertEqual(sum(r["end_ts"] - r["start_ts"] for r in rows),
                                         end.timestamp() - start.timestamp())

    def test_fixed_cet_holiday_rollover_resolves_in_meter_date_not_local_midnight(self):
        # May1 begins one local summer hour after midnight with a fixed-CET meter.
        before = preview("2026-05-01T00:30:00+02:00", "energa_g12w_2026", "fixed_cet")
        after = preview("2026-05-01T01:00:00+02:00", "energa_g12w_2026", "fixed_cet")
        self.assertEqual(before["current_interval"]["clock_date"], "2026-04-30")
        self.assertEqual(after["current_interval"]["clock_date"], "2026-05-01")
        self.assertEqual(after["current_interval"]["reason"], "holiday:labour_day")
        self.assertEqual(before["current_interval"]["end"], "2026-05-01T01:00:00+02:00")


if __name__ == "__main__":
    unittest.main()
