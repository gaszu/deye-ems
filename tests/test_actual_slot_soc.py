"""Historical HA states remain separate from frozen model projections."""
import importlib.util
from pathlib import Path
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from test_runtime import Harness

spec = importlib.util.spec_from_file_location("slot_history_test",
    Path(__file__).parents[1] / "custom_components/deye_ems/slot_history.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ActualSlotSocTests(unittest.TestCase):
    def test_boundaries_use_held_state_and_unknown_is_not_interpolated(self):
        rows = [dict(start="2026-11-16T07:00:00+01:00", end="2026-11-16T13:00:00+01:00",
                     projected_soc_end_percent=62, charge_target_soc_percent=80)]
        history = dict(through="2026-11-16T14:00:00+01:00", samples=[
            ("2026-11-16T00:00:00+01:00", 70),
            ("2026-11-16T07:00:00+01:00", 72),
            ("2026-11-16T12:50:00+01:00", None),
            ("2026-11-16T13:01:00+01:00", 65)])
        actual = module.add_actual_soc(rows, history)[0]
        self.assertEqual(actual["actual_soc_start_percent"], 72)
        self.assertIsNone(actual["actual_soc_end_percent"])
        self.assertEqual(actual["projected_soc_end_percent"], 62)
        self.assertEqual(actual["charge_target_soc_percent"], 80)
        self.assertNotIn("actual_soc_source", rows[0])

    def test_missing_future_and_dst_boundaries(self):
        rows = [dict(start="2026-10-25T02:00:00+02:00", end="2026-10-25T02:00:00+01:00")]
        history = dict(through="2026-10-25T03:00:00+01:00", samples=[
            ("2026-10-25T01:50:00+02:00", 80),
            ("2026-10-25T02:50:00+02:00", 75)])
        actual = module.add_actual_soc(rows, history)[0]
        self.assertEqual((actual["actual_soc_start_percent"], actual["actual_soc_end_percent"]), (80, 75))
        for cache in ({}, {**history, "through": "2026-10-25T01:00:00+02:00"}):
            actual = module.add_actual_soc(rows, cache)[0]
            self.assertIsNone(actual["actual_soc_start_percent"])
            self.assertIsNone(actual["actual_soc_end_percent"])


class RecorderBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_recorder_snapshot_keeps_invalid_states_and_has_no_services(self):
        h = Harness()
        source = h.co._sources["soc"]
        records = [SimpleNamespace(state=value, last_updated=h.now,
                   attributes={"unit_of_measurement": unit})
                   for value, unit in [("72", "%"), ("unavailable", "%"), ("85", "W")]]
        recorder = ModuleType("homeassistant.components.recorder")
        history = ModuleType("homeassistant.components.recorder.history")
        async def execute(job):
            return job()
        recorder.get_instance = lambda hass: SimpleNamespace(async_add_executor_job=execute)
        history.get_significant_states = lambda *args, **kwargs: {source: records}
        with patch.dict("sys.modules", {recorder.__name__: recorder, history.__name__: history}):
            await h.co._refresh_soc_history(h.now)
        self.assertEqual([value for at, value in h.co._soc_history["samples"]], [72, None, None])
        self.assertEqual(h.calls, [])

    async def test_absent_recorder_does_not_change_control_or_error(self):
        h = Harness()
        before = dict(h.co._memory)
        await h.co._refresh_soc_history(h.now)
        self.assertEqual(before, h.co._memory)
        self.assertIsNone(h.co._last_error)
        self.assertEqual(h.calls, [])
