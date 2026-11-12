"""Automatic current ceiling replaces the old writable integration parameter."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_installable import load, C
from test_runtime import Harness


class Base:
    available = True
    def __init__(self, coordinator, entry, key, name):
        self.coordinator = coordinator
    @property
    def snapshot(self):
        return self.coordinator.data


class CurrentLimitInterface(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_option_cannot_override_automatic_hardware_limit(self):
        self.assertNotIn("grid_current_max_a", C["DEFAULT_OPTIONS"])
        self.assertNotIn("grid_current_max_a", C["OPTION_RANGES"])
        h = Harness(options={"grid_current_max_a": 108})
        with self.assertRaisesRegex(ValueError, "Unknown EMS setting"):
            await h.co.async_set_option("grid_current_max_a", 500)
        self.assertEqual(h.calls, [])

    async def test_legacy_number_is_retired_without_deleting_history_or_other_entities(self):
        for disabled, owner in ((None, "entry"), ("user", "entry"), (None, "other")):
            with self.subTest(disabled=disabled, owner=owner):
                registry = SimpleNamespace(async_get_entity_id=Mock(return_value="number.legacy"),
                    async_get=Mock(return_value=SimpleNamespace(config_entry_id=owner, disabled_by=disabled)),
                    async_update_entity=Mock())
                module = load("number.py", {**C, "NumberEntity": type("NumberEntity", (), {}),
                    "NumberMode": SimpleNamespace(BOX="box"), "DeyeEMSEntity": Base,
                    "EntityCategory": SimpleNamespace(CONFIG="config"),
                    "er": SimpleNamespace(async_get=lambda _:registry,
                        RegistryEntryDisabler=SimpleNamespace(INTEGRATION="integration"))})
                added = Mock()
                await module["async_setup_entry"](object(), SimpleNamespace(entry_id="entry", runtime_data=object()), added)
                if owner == "entry" and disabled is None:
                    registry.async_update_entity.assert_called_once_with("number.legacy", disabled_by="integration")
                else:
                    registry.async_update_entity.assert_not_called()
                self.assertNotIn("grid_current_max_a", [e.key for e in added.call_args.args[0]])

    def test_read_only_sensor_has_no_numeric_fallback_when_limit_invalid(self):
        module = load("sensor.py", {"DeyeEMSEntity": Base, "SensorEntity": type("SensorEntity", (), {}),
            "EntityCategory": SimpleNamespace(DIAGNOSTIC="diagnostic")})
        coordinator = SimpleNamespace(data={"inputs": {"grid_charge_limit_valid": True,
            "deye_max_charge_current_a": 200, "deye_grid_charge_limit_a": 190}}, options={"sources": {}})
        sensor = module["DeyeEMSSensor"](coordinator, object(), "deye_grid_charge_limit", "Limit", "A")
        self.assertTrue(sensor.available)
        self.assertEqual(sensor.native_value, 190)
        self.assertEqual(sensor.extra_state_attributes["deye_max_charge_current_a"], 200)
        coordinator.data["inputs"]["grid_charge_limit_valid"] = False
        self.assertFalse(sensor.available)
        self.assertIsNone(sensor.native_value)
