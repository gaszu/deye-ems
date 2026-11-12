"""Live limits replace retired writable current and charging-power parameters."""
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
        h = Harness(options={"grid_current_max_a": 108, "charge_max_kw": 5.3})
        for key in ("grid_current_max_a", "charge_max_kw"):
            with self.subTest(key=key):
                self.assertNotIn(key, C["DEFAULT_OPTIONS"])
                self.assertNotIn(key, C["OPTION_RANGES"])
                self.assertNotIn(key, C["OPTION_LABELS"])
                with self.assertRaisesRegex(ValueError, "Unknown EMS setting"):
                    await h.co.async_set_option(key, 500)
        self.assertEqual(h.calls, [])

    async def test_legacy_number_is_retired_without_deleting_history_or_other_entities(self):
        keys = ("grid_current_max_a", "charge_max_kw")
        for key in keys:
          for disabled, owner in ((None, "entry"), ("user", "entry"),
                                  ("integration", "entry"), (None, "other")):
            with self.subTest(key=key, disabled=disabled, owner=owner):
                target = f"number.entry_{key}"
                records = {f"number.entry_{k}": SimpleNamespace(config_entry_id="entry", disabled_by="user")
                           for k in keys}
                records[target] = SimpleNamespace(config_entry_id=owner, disabled_by=disabled)
                registry = SimpleNamespace(async_get_entity_id=Mock(side_effect=lambda domain, platform, uid:f"number.{uid}"),
                    async_get=Mock(side_effect=records.get),
                    async_update_entity=Mock())
                module = load("number.py", {**C, "NumberEntity": type("NumberEntity", (), {}),
                    "NumberMode": SimpleNamespace(BOX="box"), "DeyeEMSEntity": Base,
                    "EntityCategory": SimpleNamespace(CONFIG="config"),
                    "er": SimpleNamespace(async_get=lambda _:registry,
                        RegistryEntryDisabler=SimpleNamespace(INTEGRATION="integration"))})
                added = Mock()
                await module["async_setup_entry"](object(), SimpleNamespace(entry_id="entry", runtime_data=object()), added)
                if owner == "entry" and disabled is None:
                    registry.async_update_entity.assert_called_once_with(target, disabled_by="integration")
                else:
                    registry.async_update_entity.assert_not_called()
                for old_key in keys:
                    registry.async_get_entity_id.assert_any_call("number", C["DOMAIN"], f"entry_{old_key}")
                    self.assertNotIn(old_key, [e.key for e in added.call_args.args[0]])
                self.assertIn("discharge_max_kw", [e.key for e in added.call_args.args[0]])

    async def test_missing_retired_numbers_do_not_create_or_modify_registry_entries(self):
        registry = SimpleNamespace(async_get_entity_id=Mock(return_value=None),
            async_get=Mock(), async_update_entity=Mock())
        module = load("number.py", {**C, "NumberEntity": type("NumberEntity", (), {}),
            "NumberMode": SimpleNamespace(BOX="box"), "DeyeEMSEntity": Base,
            "EntityCategory": SimpleNamespace(CONFIG="config"),
            "er": SimpleNamespace(async_get=lambda _:registry,
                RegistryEntryDisabler=SimpleNamespace(INTEGRATION="integration"))})
        added = Mock()
        await module["async_setup_entry"](object(), SimpleNamespace(entry_id="entry", runtime_data=object()), added)
        registry.async_get.assert_not_called()
        registry.async_update_entity.assert_not_called()
        self.assertTrue(added.called)

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
