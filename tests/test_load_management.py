"""Real coordinator load CRUD, with only HA/storage/Recorder boundaries stubbed."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, Mock

from test_runtime import Coordinator, Harness


def load(name="CWU", energy="sensor.cwu_energy", power="", included=True):
    return {"name": name, "energy_entity": energy, "power_entity": power,
            "included_in_load": included}


def harness(**kwargs):
    h = Harness(**kwargs)
    # CRUD must not need forecasting or touch the inverter to persist a mapping.
    h.co.async_request_refresh = AsyncMock()
    h.set_entity("sensor.cwu_energy", 100, "kWh")
    h.set_entity("sensor.cwu_power", 0, "W")
    return h


class LoadManagement(unittest.IsolatedAsyncioTestCase):
    async def test_default_pump_is_effective_and_first_add_materializes_it_once(self):
        h = harness()
        pump = h.co.effective_loads[0]
        self.assertEqual(pump["id"], "configured_heatpump")
        self.assertEqual(pump["energy_entity"], h.co._sources["pc_energy_total"])
        original_revision = h.co.loads_revision
        await h.co.async_save_load("", load(), expected_revision=original_revision)
        saved = h.entry.options
        self.assertTrue(saved["extra_loads_managed"])
        self.assertEqual(saved["extra_loads"][0], pump)
        self.assertEqual(len(saved["extra_loads"]), 2)
        self.assertNotEqual(original_revision, h.co.loads_revision)
        self.assertEqual(h.calls, [])
        reloaded = Coordinator(h.hass, h.entry, store=h.store, clock=lambda: h.now)
        self.assertEqual(reloaded.effective_loads, h.co.effective_loads)
        self.assertEqual(reloaded.loads_revision, h.co.loads_revision)

    async def test_delete_default_pump_is_explicit_empty_and_survives_reload(self):
        h = harness()
        energy = h.co.effective_loads[0]["energy_entity"]
        del h.states[energy]  # A removed source must remain deletable.
        await h.co.async_delete_load(energy, expected_revision=h.co.loads_revision)
        self.assertEqual(h.co.effective_loads, [])
        self.assertEqual(h.entry.options["extra_loads"], [])
        self.assertTrue(h.entry.options["extra_loads_managed"])
        reloaded = Coordinator(h.hass, h.entry, store=h.store, clock=lambda: h.now)
        self.assertEqual(reloaded.effective_loads, [])
        self.assertEqual(reloaded._sources["pc_energy_total"], energy)
        self.assertNotIn(energy, h.states)

    async def test_edit_keeps_stable_pump_id_even_when_energy_sensor_changes(self):
        h = harness()
        original = h.co.effective_loads[0]
        await h.co.async_save_load(original["energy_entity"],
            load("Cała pompa", power="sensor.cwu_power"), expected_revision=h.co.loads_revision)
        row = h.co.effective_loads[0]
        self.assertEqual(row["id"], original["id"])
        self.assertEqual(row["energy_entity"], "sensor.cwu_energy")
        self.assertEqual(len(h.co.effective_loads), 1)
        self.assertEqual(h.entry.options["extra_loads"][0]["id"], "configured_heatpump")

    async def test_add_then_rename_preserves_new_channel_id_and_sources(self):
        h = harness(options={"extra_loads_managed": True})
        await h.co.async_save_load("", load(), expected_revision=h.co.loads_revision)
        identifier = h.co.effective_loads[0]["id"]
        source = h.states["sensor.cwu_energy"]
        await h.co.async_save_load("sensor.cwu_energy", load("Zasobnik CWU"),
                                  expected_revision=h.co.loads_revision)
        self.assertEqual(h.co.effective_loads[0]["id"], identifier)
        self.assertEqual(h.co.effective_loads[0]["name"], "Zasobnik CWU")
        self.assertIs(h.states["sensor.cwu_energy"], source)
        self.assertEqual(h.calls, [])

    async def test_invalid_and_duplicate_channels_are_rejected_without_mutation(self):
        for value in (
            load(energy="sensor.pc_faza2_energy_total"),
            load(energy="light.not_a_meter"), load(energy="sensor.bad..name"),
            load(energy="sensor.missing"), load(energy="sensor.cwu_power"),
            load(name=""), load(name="bad\nname"), load(included="yes"),
            load(power="sensor.missing"),
            load(power="sensor.cwu_energy"), {**load(), "api_key": "synthetic-private"},
        ):
            with self.subTest(value=value):
                h = harness()
                before = deepcopy(h.co.effective_loads)
                revision = h.co.loads_revision
                with self.assertRaises(ValueError):
                    await h.co.async_save_load("", value, expected_revision=revision)
                self.assertEqual(h.co.effective_loads, before)
                self.assertEqual(h.co.loads_revision, revision)
                self.assertEqual(h.entry.options, {})
                self.assertEqual(h.store.history, [])
                h.co.async_request_refresh.assert_not_awaited()

    async def test_unavailable_numeric_sources_can_be_saved_using_units_metadata(self):
        h = harness(options={"extra_loads_managed": True})
        h.set_entity("sensor.cwu_energy", "unavailable", "Wh")
        h.set_entity("sensor.cwu_power", "unavailable", "kW")
        await h.co.async_save_load("", load(power="sensor.cwu_power", included=False),
                                  expected_revision=h.co.loads_revision)
        self.assertTrue(h.co.effective_loads[0]["included_in_load"])
        self.assertEqual(h.co.effective_loads[0]["power_entity"], "sensor.cwu_power")

    async def test_duplicate_power_sensor_is_not_counted_twice(self):
        h = harness(options={"extra_loads_managed": True})
        h.set_entity("sensor.second_energy", 2, "kWh")
        await h.co.async_save_load("", load(power="sensor.cwu_power", included=False),
                                  expected_revision=h.co.loads_revision)
        with self.assertRaisesRegex(ValueError, "sensor mocy"):
            await h.co.async_save_load("", load("Drugie", "sensor.second_energy", "sensor.cwu_power", False),
                                      expected_revision=h.co.loads_revision)
        self.assertEqual(len(h.co.effective_loads), 1)

    async def test_active_mode_rejects_all_management_without_switching_mode(self):
        h = harness()
        h.co._memory["mode"] = "active"
        energy = h.co.effective_loads[0]["energy_entity"]
        revision = h.co.loads_revision
        for operation in (
            lambda: h.co.async_save_load("", load(), expected_revision=revision),
            lambda: h.co.async_delete_load(energy, expected_revision=revision),
            lambda: h.co.async_toggle_load(energy, False, expected_revision=revision),
            lambda: h.co.async_set_option("extra_loads", []),
        ):
            with self.assertRaisesRegex(ValueError, "obserwacji"):
                await operation()
        self.assertEqual(h.co.mode, "active")
        self.assertEqual(h.entry.options, {})
        self.assertEqual(h.calls, [])
        self.assertEqual(h.store.history, [])

    async def test_stale_revision_cannot_overwrite_another_tabs_change(self):
        h = harness()
        revision = h.co.loads_revision
        await h.co.async_save_load("", load(), expected_revision=revision)
        before = deepcopy(h.co.effective_loads)
        for expected in (revision, None, ""):
            with self.assertRaisesRegex(ValueError, "Odśwież"):
                await h.co.async_delete_load("sensor.cwu_energy", expected_revision=expected)
        self.assertEqual(h.co.effective_loads, before)

    async def test_concurrent_saves_with_same_revision_accept_only_one(self):
        h = harness(options={"extra_loads_managed": True})
        h.set_entity("sensor.second_energy", 2, "kWh")
        revision = h.co.loads_revision
        outcomes = await asyncio.gather(
            h.co.async_save_load("", load(), expected_revision=revision),
            h.co.async_save_load("", load("Drugie", "sensor.second_energy"), expected_revision=revision),
            return_exceptions=True)
        self.assertEqual(sum(value is None for value in outcomes), 1)
        self.assertEqual(sum(isinstance(value, ValueError) for value in outcomes), 1)
        self.assertEqual(len(h.co.effective_loads), 1)

    async def test_missing_rows_do_not_trap_deletion_or_repair_of_other_rows(self):
        initial = [{"id": "broken-one", **load("Pierwsze", "sensor.missing_one")},
                   {"id": "broken-two", **load("Drugie", "sensor.missing_two")}]
        h = harness(options={"extra_loads_managed": True, "extra_loads": initial})
        await h.co.async_save_load("sensor.missing_one", load(), expected_revision=h.co.loads_revision)
        self.assertEqual(h.co.effective_loads[0]["id"], "broken-one")
        await h.co.async_delete_load("sensor.cwu_energy", expected_revision=h.co.loads_revision)
        self.assertEqual(h.co.effective_loads[0]["energy_entity"], "sensor.missing_two")
        await h.co.async_delete_load("sensor.missing_two", expected_revision=h.co.loads_revision)
        self.assertEqual(h.co.effective_loads, [])
        h = harness(options={"extra_loads_managed": True, "extra_loads": initial})
        await h.co.async_delete_load("sensor.missing_one", expected_revision=h.co.loads_revision)
        self.assertEqual(len(h.co.effective_loads), 1)
        await h.co.async_delete_load("sensor.missing_two", expected_revision=h.co.loads_revision)
        self.assertEqual(h.co.effective_loads, [])

    async def test_shared_option_commit_persists_invalidations_before_reload_callback(self):
        h = harness()
        for key in ("plan", "target_cache", "safety_raise", "load_profiles"):
            h.co._memory[key] = {"previous": True}
        callbacks = []
        def update(entry, *, options):
            for key in ("plan", "target_cache", "safety_raise", "load_profiles"):
                self.assertEqual(h.store.saved[key], {})
            callbacks.append(deepcopy(options))
            h.update_entry(entry, options=options)
        h.hass.config_entries.async_update_entry = update
        await h.co.async_set_option("extra_loads", [])
        self.assertEqual(h.co.effective_loads, [])
        self.assertEqual(len(callbacks), 1)
        self.assertTrue(callbacks[0]["extra_loads_managed"])
        self.assertEqual(h.co._plan_due, 0)

    async def test_failed_runtime_save_keeps_mapping_and_entry_unchanged(self):
        h = harness()
        before, revision = deepcopy(h.co.effective_loads), h.co.loads_revision
        h.co._memory["target_cache"] = {"old": True}
        h.store.fail = True
        callback = Mock()
        h.hass.config_entries.async_update_entry = callback
        with self.assertRaises(OSError):
            await h.co.async_save_load("", load(), expected_revision=revision)
        self.assertEqual(h.co.effective_loads, before)
        self.assertEqual(h.co.loads_revision, revision)
        self.assertEqual(h.co._memory["target_cache"], {"old": True})
        self.assertEqual(h.entry.options, {})
        callback.assert_not_called()
        h.co.async_request_refresh.assert_not_awaited()

    async def test_disabled_default_pump_keeps_configuration_but_is_not_observed(self):
        h = harness()
        pump = deepcopy(h.co.effective_loads[0])
        await h.co.async_toggle_load(pump["energy_entity"], False, expected_revision=h.co.loads_revision)
        disabled = h.co.effective_loads[0]
        self.assertEqual(disabled, {**pump, "enabled": False})
        self.assertEqual(h.co._channels(), [])
        self.assertEqual(h.entry.options["extra_loads"], [disabled])
        get_state = h.hass.states.get
        observed = []
        def observe(entity):
            observed.append(entity)
            return get_state(entity)
        h.hass.states.get = observe
        inputs = h.co._read_inputs(h.now)
        self.assertNotIn(pump["energy_entity"], observed)
        self.assertEqual(inputs["outside_load_w"], 0)
        reloaded = Coordinator(h.hass, h.entry, store=h.store, clock=lambda: h.now)
        self.assertEqual(reloaded.effective_loads, [disabled])
        self.assertEqual(reloaded._channels(), [])
        self.assertEqual(h.calls, [])

    async def test_toggle_on_preserves_identity_without_revalidating_missing_source(self):
        h = harness()
        pump = deepcopy(h.co.effective_loads[0])
        await h.co.async_toggle_load(pump["energy_entity"], False, expected_revision=h.co.loads_revision)
        del h.states[pump["energy_entity"]]
        await h.co.async_toggle_load(pump["energy_entity"], True, expected_revision=h.co.loads_revision)
        self.assertEqual(h.co.effective_loads, [pump])
        self.assertEqual(h.co._channels(), [pump])
        self.assertEqual(h.calls, [])

    async def test_edit_without_enabled_keeps_disabled_and_new_rows_default_enabled(self):
        h = harness()
        energy = h.co.effective_loads[0]["energy_entity"]
        await h.co.async_toggle_load(energy, False, expected_revision=h.co.loads_revision)
        await h.co.async_save_load(energy, load("Pompa OFF", energy), expected_revision=h.co.loads_revision)
        self.assertFalse(h.co.effective_loads[0]["enabled"])
        await h.co.async_save_load("", load(), expected_revision=h.co.loads_revision)
        self.assertTrue(h.co.effective_loads[1]["enabled"])
        self.assertEqual([row["energy_entity"] for row in h.co._channels()], ["sensor.cwu_energy"])

    async def test_disabled_outside_meter_does_not_add_demand_or_block_telemetry(self):
        h = harness(options={"extra_loads_managed": True, "extra_loads": [
            {"id": "outside", **load("Brakujące", "sensor.absent_energy", "sensor.absent_power", False),
             "enabled": False}]})
        data = h.co._read_inputs(h.now)
        self.assertTrue(data["telemetry_valid"])
        self.assertEqual(data["outside_load_w"], 0)
        self.assertEqual(h.co._channels(), [])

    async def test_toggle_rejects_nonboolean_and_stale_snapshot_without_mutation(self):
        h = harness()
        energy = h.co.effective_loads[0]["energy_entity"]
        before = deepcopy(h.co.effective_loads)
        for enabled in (None, "false", 0, 1):
            with self.assertRaises(ValueError):
                await h.co.async_toggle_load(energy, enabled, expected_revision=h.co.loads_revision)
        with self.assertRaises(ValueError):
            await h.co.async_toggle_load(energy, False, expected_revision="stale")
        self.assertEqual(h.co.effective_loads, before)
        self.assertEqual(h.entry.options, {})
        self.assertEqual(h.store.history, [])

    async def test_legacy_false_save_without_power_is_normalized_to_whole_load(self):
        h = harness(options={"extra_loads_managed": True})
        await h.co.async_save_load("", load(included=False), expected_revision=h.co.loads_revision)
        self.assertTrue(h.co.effective_loads[0]["included_in_load"])
        self.assertEqual(h.co.effective_loads[0]["power_entity"], "")
        self.assertTrue(h.co._read_inputs(h.now)["telemetry_valid"])
        self.assertEqual(h.co._read_inputs(h.now)["outside_load_w"], 0)
        value = load("Drugi", "sensor.second_energy")
        value.pop("included_in_load")
        h.set_entity("sensor.second_energy", 2, "kWh")
        await h.co.async_save_load("", value, expected_revision=h.co.loads_revision)
        self.assertTrue(h.co.effective_loads[1]["included_in_load"])

    async def test_channel_power_is_never_read_or_added_to_live_load_budget(self):
        h = harness(options={"extra_loads_managed": True})
        baseline = h.co._read_inputs(h.now)
        base_cap = h.co._controller(h.co._grid_input(baseline, h.now, 85, False))["cap_a"]
        await h.co.async_save_load("", load(power="sensor.cwu_power", included=False),
                                  expected_revision=h.co.loads_revision)
        h.set_entity("sensor.cwu_power", 50000, "W", age=600)
        get_state, observed = h.hass.states.get, []
        def observe(entity):
            observed.append(entity)
            return get_state(entity)
        h.hass.states.get = observe
        inputs = h.co._read_inputs(h.now)
        self.assertNotIn("sensor.cwu_power", observed)
        self.assertTrue(inputs["telemetry_valid"])
        self.assertTrue(inputs["outside_power_valid"])
        self.assertEqual(inputs["outside_load_w"], 0)
        self.assertEqual(inputs["total_load_with_outside_w"], baseline["load_power"])
        self.assertEqual(h.co._controller(h.co._grid_input(inputs, h.now, 85, False))["cap_a"], base_cap)

    async def test_stored_legacy_false_missing_power_does_not_block_live_telemetry(self):
        h = harness(options={"extra_loads_managed": True, "extra_loads": [
            {"id": "old-channel", **load("Stary", "sensor.absent_energy", "sensor.absent_power", False)}]})
        self.assertTrue(h.co.effective_loads[0]["included_in_load"])
        inputs = h.co._read_inputs(h.now)
        self.assertTrue(inputs["telemetry_valid"])
        self.assertEqual(inputs["total_load_with_outside_w"], inputs["raw_load_power"])
