"""Saved calculations survive interval boundaries without inventing history."""
from copy import deepcopy
from datetime import datetime
import json
import unittest
from test_planner import MODULE


class SlotHistoryTests(unittest.TestCase):
    def test_last_calculation_is_frozen_and_survives_storage(self):
        now = datetime.fromisoformat("2026-11-16T12:00:00+01:00")
        row = dict(start="2026-11-16T07:00:00+01:00", end="2026-11-16T13:00:00+01:00",
                   quality="forecast", grid_charge_allowed=True, charge_target_soc_percent=78,
                   reserve_soc_percent=40, projected_soc_start_percent=70,
                   projected_soc_end_percent=62, projection_from=now.isoformat(),
                   deadline="2026-11-16T16:00:00+01:00")
        history = {}
        MODULE.remember_tariff_slot_targets(now, {}, [row], history)
        row["charge_target_soc_percent"] = 80
        MODULE.remember_tariff_slot_targets(now, {}, [row], history)
        history = json.loads(json.dumps(history))
        past = {**row, "quality": "past", "charge_target_soc_percent": None,
                "projected_soc_start_percent": None, "projected_soc_end_percent": None,
                "projection_from": None, "deadline": None}
        result = MODULE.remember_tariff_slot_targets(now, {}, [past], history)[0]
        self.assertEqual(result["quality"], "historical")
        self.assertEqual(result["charge_target_soc_percent"], 80)
        self.assertEqual(result["projected_soc_end_percent"], 62)
        frozen = deepcopy(history)
        MODULE.remember_tariff_slot_targets(now, {}, [past], history)
        self.assertEqual(frozen, history)
        self.assertEqual(MODULE.remember_tariff_slot_targets(now, {}, [past], {})[0], past)
        self.assertEqual(MODULE.remember_tariff_slot_targets(now, {"tariff_clock_basis": "fixed_cet"}, [past], history)[0], past)

    def test_unavailable_does_not_erase_calculation_and_old_dates_are_pruned(self):
        now = datetime.fromisoformat("2026-11-16T12:00:00+01:00")
        row = dict(start="2026-11-16T07:00:00+01:00", end="2026-11-16T13:00:00+01:00",
                   quality="fallback", grid_charge_allowed=True, charge_target_soc_percent=85)
        history = {}
        MODULE.remember_tariff_slot_targets(now, {}, [row], history)
        frozen = deepcopy(history)
        MODULE.remember_tariff_slot_targets(now, {}, [{**row, "quality": "unavailable"}], history)
        self.assertEqual(history, frozen)
        result = MODULE.remember_tariff_slot_targets(now, {}, [{**row, "quality": "past"}], history)
        self.assertIsNone(result[0]["projected_soc_end_percent"])
        MODULE.remember_tariff_slot_targets(now, {}, [], history)
        self.assertEqual(history["slots"], {})
