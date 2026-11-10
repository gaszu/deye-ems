"""Channel telemetry follows the runtime's canonical, user-managed list.

Only HA entity classes are stubbed. Migration and channel selection use the real
coordinator; no event loop, recorder access or hardware command is required.
"""
import ast
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

from test_runtime import Harness, SOURCES


ROOT = Path(__file__).resolve().parents[1] / "custom_components/deye_ems"


class Entity:
    def __init__(self, coordinator, entry, key, name):
        self.coordinator = coordinator
        self.hass = coordinator.hass
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name

    @property
    def snapshot(self):
        return self.coordinator.data or {}


def load_telemetry():
    values = {"datetime": datetime, "timezone": timezone,
              "DeyeEMSEntity": Entity, "SensorEntity": type("SensorEntity", (), {}),
              "EntityCategory": SimpleNamespace(DIAGNOSTIC="diagnostic")}
    tree = ast.parse((ROOT / "telemetry.py").read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body
                 if not isinstance(node, (ast.Import, ast.ImportFrom))]
    exec(compile(tree, "telemetry.py", "exec"), values)
    return values


TELEMETRY = load_telemetry()


def channel_entities(harness):
    entities = TELEMETRY["build_entities"](harness.co, harness.entry)
    return [item for item in entities if isinstance(item, TELEMETRY["ExtraLoadSensor"])]


class TelemetryLoads(unittest.TestCase):
    def test_legacy_implicit_heatpump_remains_once_with_existing_unique_id(self):
        h = Harness(options={"extra_loads": []})
        entities = channel_entities(h)
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].channel["energy_entity"], SOURCES["pc_energy_total"])
        self.assertEqual(entities[0]._attr_unique_id,
                         "offline_load_configured_heatpump_False")
        self.assertFalse(entities[0].power)

    def test_managed_empty_list_does_not_resurrect_mapped_heatpump(self):
        h = Harness(options={"extra_loads_managed": True, "extra_loads": []})
        self.assertTrue(h.co.options["sources"]["pc_energy_total"])
        self.assertEqual(channel_entities(h), [])
        entities = TELEMETRY["build_entities"](h.co, h.entry)
        self.assertEqual(len(entities), len(TELEMETRY["METRICS"]) + 3)

    def test_explicit_legacy_heatpump_is_not_duplicated_and_keeps_its_id(self):
        pump = {"id": "existing_pump_id", "name": "Cała pompa", "included_in_load": True,
                "energy_entity": SOURCES["pc_energy_total"], "power_entity": "sensor.pump_power"}
        h = Harness(options={"extra_loads": [pump]})
        entities = channel_entities(h)
        self.assertEqual(len(entities), 2)
        self.assertEqual({item._attr_unique_id for item in entities},
                         {"offline_load_existing_pump_id_False",
                          "offline_load_existing_pump_id_True"})
        self.assertEqual({item.channel["energy_entity"] for item in entities},
                         {SOURCES["pc_energy_total"]})

    def test_managed_channels_create_energy_and_only_configured_power_sensors(self):
        loads = [
            {"id": "old_uuid", "name": "CWU", "energy_entity": "sensor.cwu_energy",
             "power_entity": "", "included_in_load": True},
            {"name": "Garaż", "energy_entity": "sensor.garage_energy",
             "power_entity": "sensor.garage_power", "included_in_load": False},
        ]
        h = Harness(options={"extra_loads_managed": True, "extra_loads": loads})
        entities = channel_entities(h)
        self.assertEqual(len(entities), 3)
        self.assertEqual({item.channel["energy_entity"] for item in entities},
                         {"sensor.cwu_energy", "sensor.garage_energy"})
        self.assertEqual({item._attr_unique_id for item in entities},
                         {"offline_load_old_uuid_False", "offline_load_sensor.garage_energy_False",
                          "offline_load_sensor.garage_energy_True"})
        self.assertEqual([item.channel["power_entity"] for item in entities if item.power],
                         ["sensor.garage_power"])

    def test_telemetry_uses_canonical_list_even_if_raw_options_still_contain_old_loads(self):
        coordinator = SimpleNamespace(
            options={"extra_loads": [{"energy_entity": "sensor.old_energy"}],
                     "sources": {"pc_energy_total": "sensor.legacy_energy"}},
            effective_loads=[], hass=SimpleNamespace(), data={})
        entities = TELEMETRY["build_entities"](coordinator, SimpleNamespace(entry_id="offline"))
        self.assertFalse(any(isinstance(item, TELEMETRY["ExtraLoadSensor"]) for item in entities))

    def test_name_and_power_edits_keep_energy_sensor_identity(self):
        h = Harness(options={"extra_loads_managed": True, "extra_loads": [
            {"id": "durable_id", "name": "Stara nazwa", "energy_entity": "sensor.device_energy",
             "power_entity": "", "included_in_load": True}]})
        original = channel_entities(h)[0]
        h.co._options["extra_loads"][0].update(
            name="Nowa nazwa", power_entity="sensor.device_power", included_in_load=False)
        updated = channel_entities(h)
        energy = next(item for item in updated if not item.power)
        self.assertEqual(energy._attr_unique_id, original._attr_unique_id)
        self.assertEqual(energy._attr_name, "Nowa nazwa energia")
        self.assertEqual(len(updated), 2)

    def test_disabled_heatpump_is_retained_in_config_without_implicit_resurrection(self):
        pump = {"id": "configured_heatpump", "name": "Pompa ciepła",
                "energy_entity": SOURCES["pc_energy_total"], "power_entity": "",
                "included_in_load": True, "enabled": False}
        h = Harness(options={"extra_loads_managed": True, "extra_loads": [pump]})
        self.assertEqual(len(h.co.effective_loads), 1)
        self.assertIs(h.co.effective_loads[0]["enabled"], False)
        self.assertEqual(channel_entities(h), [])
        self.assertEqual(h.co._channels(), [])
        self.assertEqual(h.entry.options["extra_loads"], [pump])

    def test_disabled_channel_does_not_hide_other_enabled_channel_or_add_default_pump(self):
        h = Harness(options={"extra_loads_managed": True, "extra_loads": [
            {"id": "configured_heatpump", "name": "PC", "energy_entity": SOURCES["pc_energy_total"],
             "power_entity": "sensor.pump_power", "included_in_load": True, "enabled": False},
            {"id": "cwu", "name": "CWU", "energy_entity": "sensor.cwu_energy",
             "power_entity": "sensor.cwu_power", "included_in_load": False, "enabled": True}]})
        entities = channel_entities(h)
        self.assertEqual(len(h.co.effective_loads), 2)
        self.assertEqual({item._attr_unique_id for item in entities},
                         {"offline_load_cwu_False", "offline_load_cwu_True"})
        self.assertEqual({item["energy_entity"] for item in h.co._channels()}, {"sensor.cwu_energy"})

    def test_off_then_on_reuses_existing_sensor_identity_and_configuration(self):
        h = Harness(options={"extra_loads_managed": True, "extra_loads": [
            {"id": "durable_id", "name": "Ogrzewanie", "energy_entity": "sensor.pump_energy",
             "power_entity": "sensor.pump_power", "included_in_load": True, "enabled": True}]})
        before = {item._attr_unique_id for item in channel_entities(h)}
        configuration = deepcopy(h.co._options["extra_loads"][0])
        h.co._options["extra_loads"][0]["enabled"] = False
        self.assertEqual(channel_entities(h), [])
        h.co._options["extra_loads"][0]["enabled"] = True
        self.assertEqual({item._attr_unique_id for item in channel_entities(h)}, before)
        self.assertEqual(h.co._options["extra_loads"][0], configuration)

    def test_building_or_removing_channel_telemetry_does_not_write_or_delete_sources(self):
        h = Harness(options={"extra_loads": []})
        before = deepcopy(h.states)
        channel_entities(h)
        h.co._options.update(extra_loads_managed=True, extra_loads=[])
        self.assertEqual(channel_entities(h), [])
        self.assertEqual(h.states, before)
        self.assertEqual(h.calls, [])
        self.assertEqual(h.store.history, [])


if __name__ == "__main__":
    unittest.main()
