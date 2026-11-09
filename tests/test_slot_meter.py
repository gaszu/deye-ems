"""Offline slot accounting, including real UTC time across Warsaw DST."""
from copy import deepcopy
from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).parents[1] / "custom_components/deye_ems/slot_meter.py"
SPEC = importlib.util.spec_from_file_location("deye_ems_slot_meter_test", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
update = MODULE.update_slot_measurements


def sample(at, battery=3600, grid=7200, valid=True):
    return dict(at=at, battery_w=battery, grid_w=grid, telemetry_valid=valid)


def pair(a, b, battery=3600, grid=7200):
    return update(update({}, sample(a, battery, grid)), sample(b, battery, grid))


class SlotMeterTests(unittest.TestCase):
    def test_energy_signs_and_units(self):
        m = pair("2026-11-10T05:00:00+01:00", "2026-11-10T05:00:10+01:00")
        r = m["slots"][m["current_slot"]]
        self.assertAlmostEqual(r["battery_discharge_kwh"], .01)
        self.assertAlmostEqual(r["grid_import_kwh"], .02)
        self.assertEqual(r["battery_charge_kwh"], 0)

    def test_charging_and_export_are_not_discharge_or_import(self):
        m = pair("2026-11-10T05:00:00+01:00", "2026-11-10T05:00:10+01:00", -3600, -7200)
        r = m["slots"][m["current_slot"]]
        self.assertAlmostEqual(r["battery_charge_kwh"], .01)
        self.assertEqual(r["battery_discharge_kwh"], 0)
        self.assertEqual(r["grid_import_kwh"], 0)

    def test_linear_zero_crossing_keeps_each_direction(self):
        m = update({}, sample("2026-11-10T05:00:00+01:00", 3600, 3600))
        m = update(m, sample("2026-11-10T05:00:10+01:00", -3600, -3600))
        r = m["slots"][m["current_slot"]]
        self.assertAlmostEqual(r["battery_discharge_kwh"], .0025)
        self.assertAlmostEqual(r["battery_charge_kwh"], .0025)
        self.assertAlmostEqual(r["grid_import_kwh"], .0025)

    def test_all_winter_and_summer_boundaries_split_energy(self):
        for date, hours, offset in (("2026-11-10", (7, 13, 16, 21), "+01:00"),
                                    ("2026-07-10", (7, 13, 19, 22), "+02:00")):
            for hour in hours:
                with self.subTest(date=date, hour=hour):
                    boundary = datetime.fromisoformat(f"{date}T{hour:02}:00:00{offset}")
                    m = pair((boundary - timedelta(seconds=5)).isoformat(),
                             (boundary + timedelta(seconds=5)).isoformat())
                    rows = list(m["slots"].values())
                    self.assertEqual(len(rows), 2)
                    self.assertTrue(all(r["seconds_valid"] == 5 for r in rows))
                    self.assertTrue(all(abs(r["grid_import_kwh"] - .01) < 1e-9 for r in rows))

    def test_midnight_and_season_boundary(self):
        m = pair("2026-03-31T23:59:55+02:00", "2026-04-01T00:00:05+02:00")
        rows = list(m["slots"].values())
        self.assertEqual([r["slot"] for r in rows], [6, 1])
        self.assertTrue(all(r["seconds_valid"] == 5 for r in rows))
        self.assertEqual(rows[1]["start"], "2026-04-01T00:00:00+02:00")

    def test_dst_fall_repeated_hour_is_ten_actual_seconds(self):
        m = pair("2026-10-25T02:59:55+02:00", "2026-10-25T02:00:05+01:00")
        r = m["slots"][m["current_slot"]]
        self.assertEqual(r["slot"], 1)
        self.assertEqual(r["duration_seconds"], 5 * 3600)
        self.assertEqual(r["seconds_valid"], 10)
        self.assertAlmostEqual(r["grid_import_kwh"], .02)

    def test_dst_spring_missing_wall_hour_is_ten_actual_seconds(self):
        m = pair("2026-03-29T01:59:55+01:00", "2026-03-29T03:00:05+02:00")
        r = m["slots"][m["current_slot"]]
        self.assertEqual(r["duration_seconds"], 3 * 3600)
        self.assertEqual(r["seconds_valid"], 10)

    def test_gap_adds_missing_coverage_without_energy(self):
        m = pair("2026-11-10T06:59:40+01:00", "2026-11-10T07:00:20+01:00")
        self.assertEqual(m["reason"], "gap_above_30s")
        self.assertEqual(sum(r["seconds_valid"] for r in m["slots"].values()), 0)
        self.assertEqual(sum(r["grid_import_kwh"] for r in m["slots"].values()), 0)
        self.assertEqual(m["slots"][m["current_slot"]]["seconds_missing"], 20)

    def test_invalid_sample_prevents_bridge_to_next_valid_sample(self):
        m = update({}, sample("2026-11-10T07:00:00+01:00"))
        m = update(m, sample("2026-11-10T07:00:10+01:00", valid=False))
        m = update(m, sample("2026-11-10T07:00:20+01:00"))
        r = m["slots"][m["current_slot"]]
        self.assertEqual(r["seconds_missing"], 20)
        self.assertEqual(r["seconds_valid"], 0)
        self.assertEqual(r["grid_import_kwh"], 0)

    def test_unknown_power_and_invalid_clock_never_become_zero_measurements(self):
        m = update({}, sample("2026-11-10T07:00:00+01:00"))
        m = update(m, sample("bad", "unknown", 1))
        self.assertEqual(m["reason"], "invalid_timestamp")
        m = update(m, sample("2026-11-10T07:00:20+01:00"))
        self.assertEqual(m["slots"][m["current_slot"]]["seconds_missing"], 20)

    def test_restart_with_durable_memory_continues_once(self):
        m = update({}, sample("2026-11-10T07:00:00+01:00"))
        m = update(deepcopy(m), sample("2026-11-10T07:00:10+01:00"))
        r = m["slots"][m["current_slot"]]
        self.assertEqual(r["seconds_valid"], 10)
        duplicate = update(m, sample("2026-11-10T07:00:10+01:00"))
        self.assertEqual(duplicate["slots"], m["slots"])
        self.assertEqual(duplicate["reason"], "non_monotonic_timestamp")

    def test_closed_complete_requires_whole_slot_coverage(self):
        start = datetime.fromisoformat("2026-11-10T04:00:00+01:00")
        m = update({}, sample(start))
        for seconds in range(30, 3 * 3600 + 1, 30):
            m = update(m, sample(start + timedelta(seconds=seconds)))
        r = m["slots"][start.isoformat()]
        self.assertTrue(r["closed"])
        self.assertTrue(r["complete"])
        self.assertEqual(r["seconds_missing"], 0)
        self.assertEqual(r["coverage"], 1)
        self.assertAlmostEqual(r["grid_import_kwh"], 21.6)

    def test_first_observation_mid_slot_is_incomplete(self):
        m = pair("2026-11-10T06:59:50+01:00", "2026-11-10T07:00:00+01:00")
        r = next(r for r in m["slots"].values() if r["slot"] == 2)
        self.assertTrue(r["closed"])
        self.assertFalse(r["complete"])
        self.assertEqual(r["seconds_missing"], 3 * 3600 - 10)

    def test_long_restart_gap_retention_never_exceeds42slots(self):
        m = update({}, sample("2026-11-01T00:00:00+01:00"))
        m = update(m, sample("2026-11-20T12:00:00+01:00"))
        self.assertLessEqual(len(m["slots"]), 42)
        self.assertEqual(sum(r["grid_import_kwh"] for r in m["slots"].values()), 0)

    def test_inputs_are_not_mutated_and_epoch_is_supported(self):
        at = datetime.fromisoformat("2026-11-10T07:00:00+01:00").timestamp()
        first = sample(at)
        memory = update({}, first)
        saved = deepcopy(memory)
        second = sample(at + 10)
        update(memory, second)
        self.assertEqual(memory, saved)
        self.assertEqual(first, sample(at))

    def test_corrupt_persisted_duration_cannot_claim_complete_coverage(self):
        m = pair("2026-11-10T06:59:50+01:00", "2026-11-10T07:00:00+01:00")
        old = next(r for r in m["slots"].values() if r["slot"] == 2)
        old["duration_seconds"] = 10
        old["seconds_missing"] = 0
        m = update(m, sample("2026-11-10T07:00:10+01:00"))
        self.assertTrue(all(r["slot"] != 2 for r in m["slots"].values()))


if __name__ == "__main__":
    unittest.main()
