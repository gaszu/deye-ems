"""Native load flows preserve the same canonical meters as the inline editor."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

import test_installable as boundary
from test_runtime import Harness, PC_SOURCES


PUMP = PC_SOURCES["pc_energy_total"]


def flow(*, data=None, options=None, runtime=None):
    result = boundary.Installation().flow()["DeyeEMSOptionsFlow"]()
    result.config_entry = SimpleNamespace(
        data=deepcopy({"sources": dict(PC_SOURCES), **(data or {})}),
        options=deepcopy(options or {}), runtime_data=runtime)
    return result


def choices(result):
    selector = next(iter(result["data_schema"].values()))
    return selector["args"][0]["options"]


class NativeLoadFlows(unittest.IsolatedAsyncioTestCase):
    def test_default_pump_is_materialized_with_its_canonical_id(self):
        item = flow()._loads()
        self.assertEqual(item, [{"id": "configured_heatpump", "name": "Pompa ciepła",
            "energy_entity": PUMP, "power_entity": "", "included_in_load": True, "enabled": True}])

    def test_source_overrides_and_explicitly_disabled_pump_are_respected(self):
        item = flow(data={"sources": {"pc_energy_total": "sensor.old_pump"}},
            options={"sources": {"pc_energy_total": "sensor.current_pump"}})._loads()
        self.assertEqual(item[0]["energy_entity"], "sensor.current_pump")
        self.assertEqual(flow(options={"sources": {"pc_energy_total": ""}})._loads(), [])

    def test_runtime_effective_list_is_authoritative_and_not_mutated(self):
        channels = [{"id": "existing-uuid", "name": "Meter",
            "energy_entity": "sensor.runtime_energy", "power_entity": "sensor.runtime_power",
            "included_in_load": False}]
        runtime = SimpleNamespace(mode="shadow", effective_loads=channels)
        loaded = flow(options={"extra_loads": [{"energy_entity": "sensor.stale"}]},
            runtime=runtime)._loads()
        self.assertEqual(loaded, [{**channels[0], "included_in_load": True}])
        self.assertIs(channels[0]["included_in_load"], False)
        loaded[0]["name"] = "Local form edit"
        self.assertEqual(channels[0]["name"], "Meter")
        runtime.effective_loads = []
        self.assertEqual(flow(runtime=runtime)._loads(), [])

    def test_offline_fallback_matches_runtime_ids_and_legacy_pump_rules(self):
        cases = (
            ({}, {}),
            ({"sources": {"pc_energy_total": "sensor.custom_pump"}},
             {"extra_loads": [{"energy_entity": "sensor.cwu"}]}),
            ({}, {"extra_loads": [
                {"id": "raw-uuid", "name": "Pump", "energy_entity": PUMP},
                {"energy_entity": "sensor.cwu"}, {"energy_entity": "sensor.cwu"},
                {"name": "Missing meter"}, None]}),
            ({"extra_loads_managed": True}, {"extra_loads": []}),
            ({}, {"extra_loads": [{"energy_entity": PUMP, "enabled": False}]}),
            ({}, {"extra_loads_managed": True, "extra_loads": [
                {"id": "legacy-outside", "name": "EV", "energy_entity": "sensor.ev_energy",
                 "included_in_load": False, "power_entity": ""}]}),
        )
        for data, options in cases:
            with self.subTest(data=data, options=options):
                runtime = Harness(initial=data, options=options).co
                self.assertEqual(flow(data=data, options=options)._loads(), runtime.effective_loads)

    def test_legacy_missing_id_is_stable_and_existing_uuid_survives(self):
        options = {"extra_loads": [
            {"id": "saved-uuid", "energy_entity": PUMP},
            {"name": "CWU", "energy_entity": "sensor.cwu"}]}
        first, second = flow(options=options)._loads(), flow(options=options)._loads()
        self.assertEqual(first, second)
        self.assertEqual([item["id"] for item in first], ["saved-uuid", "sensor.cwu"])
        self.assertEqual(sum(item["energy_entity"] == PUMP for item in first), 1)

    async def test_add_persists_the_implicit_pump_and_existing_ids(self):
        native = flow(options={"min_soc_percent": 55, "extra_loads": [
            {"id": "saved-uuid", "name": "CWU", "energy_entity": "sensor.cwu"}]})
        before = deepcopy(native.config_entry.options)
        result = await native.async_step_add_load({"name": "EV", "energy_entity": "sensor.ev",
            "power_entity": "sensor.ev_power"})
        saved = result["data"]
        self.assertEqual(result["type"], "create_entry")
        self.assertTrue(saved["extra_loads_managed"])
        self.assertEqual(saved["min_soc_percent"], 55)
        self.assertEqual([item["energy_entity"] for item in saved["extra_loads"]],
            ["sensor.cwu", PUMP, "sensor.ev"])
        self.assertEqual([item["id"] for item in saved["extra_loads"][:2]],
            ["saved-uuid", "configured_heatpump"])
        self.assertTrue(saved["extra_loads"][2]["id"])
        self.assertEqual(flow(options=saved)._loads(), saved["extra_loads"])
        self.assertEqual(native.config_entry.options, before)

    async def test_form_has_no_load_membership_checkbox_and_power_is_optional(self):
        native = flow(options={"extra_loads_managed": True})
        shown = await native.async_step_add_load()
        fields = {marker.key for marker in shown["data_schema"]}
        self.assertEqual(fields, {"name", "energy_entity", "power_entity"})
        result = await native.async_step_add_load({"name": "EV", "energy_entity": "sensor.ev_energy"})
        self.assertEqual(result["type"], "create_entry")
        saved = result["data"]["extra_loads"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["power_entity"], "")
        self.assertIs(saved[0]["included_in_load"], True)

    async def test_add_normalizes_legacy_false_without_requiring_power(self):
        native = flow(options={"extra_loads_managed": True, "extra_loads": [
            {"id": "existing-off", "name": "CWU", "energy_entity": "sensor.cwu_energy",
             "included_in_load": False, "enabled": False}]})
        before = deepcopy(native.config_entry.options)
        result = await native.async_step_add_load({"name": "EV", "energy_entity": "sensor.ev_energy",
            "included_in_load": False})
        saved = result["data"]["extra_loads"]
        self.assertEqual([item["energy_entity"] for item in saved], ["sensor.cwu_energy", "sensor.ev_energy"])
        self.assertTrue(all(item["included_in_load"] is True for item in saved))
        self.assertTrue(all(item["power_entity"] == "" for item in saved))
        self.assertEqual(saved[0]["id"], "existing-off")
        self.assertIs(saved[0]["enabled"], False)
        self.assertEqual(native.config_entry.options, before)

    async def test_remove_normalizes_legacy_false_in_remaining_channels(self):
        native = flow(options={"extra_loads_managed": True, "extra_loads": [
            {"id": "remaining", "name": "CWU", "energy_entity": "sensor.cwu_energy",
             "included_in_load": False, "enabled": False},
            {"id": "removed", "name": "EV", "energy_entity": "sensor.ev_energy"}]})
        result = await native.async_step_remove_load({"load_id": "removed"})
        saved = result["data"]["extra_loads"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["id"], "remaining")
        self.assertIs(saved[0]["included_in_load"], True)
        self.assertIs(saved[0]["enabled"], False)

    async def test_add_rejects_a_duplicate_of_the_implicit_pump(self):
        native = flow()
        result = await native.async_step_add_load({"name": "Duplicate pump",
            "energy_entity": PUMP, "included_in_load": True})
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {"base": "duplicate_load"})
        self.assertEqual(native.config_entry.options, {})

    async def test_remove_default_pump_persists_empty_list_without_resurrection(self):
        native = flow(options={"min_soc_percent": 60})
        shown = await native.async_step_remove_load()
        self.assertEqual(choices(shown), [{"value": "configured_heatpump", "label": "Pompa ciepła"}])
        result = await native.async_step_remove_load({"load_id": "configured_heatpump"})
        self.assertEqual(result["data"], {"min_soc_percent": 60,
            "extra_loads": [], "extra_loads_managed": True})
        reloaded = flow(options=result["data"])
        self.assertEqual(reloaded._loads(), [])
        self.assertEqual(await reloaded.async_step_remove_load(),
            {"type": "abort", "reason": "no_extra_loads"})
        added = await reloaded.async_step_add_load({"name": "CWU", "energy_entity": "sensor.cwu",
            "included_in_load": True})
        self.assertEqual([item["energy_entity"] for item in added["data"]["extra_loads"]], ["sensor.cwu"])
        self.assertEqual(flow(options=added["data"])._loads(), added["data"]["extra_loads"])

    async def test_remove_uses_normalized_dropdown_id_and_keeps_other_channels(self):
        native = flow(data={"extra_loads": [
            {"id": "pump-uuid", "energy_entity": PUMP},
            {"name": "CWU", "energy_entity": "sensor.cwu"}]})
        shown = await native.async_step_remove_load()
        self.assertEqual(choices(shown), [
            {"value": "pump-uuid", "label": PUMP}, {"value": "sensor.cwu", "label": "CWU"}])
        result = await native.async_step_remove_load({"load_id": "sensor.cwu"})
        self.assertTrue(result["data"]["extra_loads_managed"])
        self.assertEqual([item["id"] for item in result["data"]["extra_loads"]], ["pump-uuid"])
        self.assertEqual(flow(data=native.config_entry.data, options=result["data"])._loads(),
            result["data"]["extra_loads"])

    async def test_explicit_empty_managed_data_does_not_recreate_pump(self):
        native = flow(data={"extra_loads": [], "extra_loads_managed": True})
        self.assertEqual(native._loads(), [])
        result = await native.async_step_add_load({"name": "EV", "energy_entity": "sensor.ev",
            "included_in_load": True})
        self.assertEqual([item["energy_entity"] for item in result["data"]["extra_loads"]], ["sensor.ev"])
        self.assertTrue(result["data"]["extra_loads_managed"])

    async def test_active_mode_blocks_both_forms_and_submissions_without_changing_mode(self):
        runtime = SimpleNamespace(mode="active", effective_loads=[])
        native = flow(options={"extra_loads_managed": True}, runtime=runtime)
        before = deepcopy(native.config_entry.options)
        for method, submitted in (
            (native.async_step_add_load, {"name": "EV", "energy_entity": "sensor.ev"}),
            (native.async_step_remove_load, {"load_id": "configured_heatpump"}),
        ):
            for values in (None, submitted):
                self.assertEqual(await method(values), {"type": "abort", "reason": "stop_before_mapping"})
        self.assertEqual(native.config_entry.options, before)
        self.assertEqual(runtime.mode, "active")

