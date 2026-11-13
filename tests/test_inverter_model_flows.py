"""Explicit model preview/save and migration-preserving native flows."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

import test_installable as boundary


def options_flow(*, mode="shadow", options=None, data=None):
    flow = boundary.Installation().flow()["DeyeEMSOptionsFlow"]()
    flow.config_entry = SimpleNamespace(options=deepcopy(options or {}),
        data=deepcopy(data or {}), runtime_data=SimpleNamespace(mode=mode))
    return flow


class InverterModelFlows(unittest.IsolatedAsyncioTestCase):
    async def test_installer_contains_model_and_phase_fields_with_sidebar_notice(self):
        flow = boundary.Installation().flow()["DeyeEMSConfigFlow"]()
        form = await flow.async_step_user()
        fields = {marker.key for marker in form["data_schema"]}
        self.assertTrue({"inverter_model", "inverter_phases", "connection_phases", "inverter_phase"} <= fields)

    async def test_existing_empty_submission_remains_compatible_and_in_observation(self):
        flow = boundary.Installation().flow()["DeyeEMSConfigFlow"]()
        result = await flow.async_step_user({})
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["inverter_model"], "custom")
        self.assertEqual(result["data"]["inverter_phases"], 3)
        self.assertNotIn("mode", result["data"])

    async def test_single_phase_new_install_requires_preview_confirmation(self):
        flow = boundary.Installation().flow()["DeyeEMSConfigFlow"]()
        supplied = dict(inverter_model="SUN-5K-SG04LP1-EU", inverter_phases="3",
                        connection_phases="3", inverter_phase="L2", min_soc_percent=60,
                        capacity_kwh=30, pv_peak_kwp=7, entity_prefix="deye_example_")
        form = await flow.async_step_user(supplied)
        self.assertEqual((form["type"], form["step_id"]), ("form", "user_inverter_confirm"))
        self.assertIn("SUN-5K-SG04LP1-EU", form["description_placeholders"]["model_preview"])
        self.assertEqual((await flow.async_step_user_inverter_confirm({"confirm_model": False}))["type"], "form")
        result = await flow.async_step_user_inverter_confirm({"confirm_model": True})
        data = result["data"]
        self.assertEqual(data["inverter_phases"], 1)
        self.assertEqual(data["inverter_max_power_kw"], 5)
        self.assertEqual((data["min_soc_percent"], data["capacity_kwh"], data["pv_peak_kwp"]), (60, 30, 7))
        self.assertEqual(data["sources"]["grid_power"], "sensor.deye_example_grid_power")
        self.assertFalse(any(data["sources"][f"{kind}_l{i}_power"]
                             for kind in ("grid", "load") for i in (1, 2, 3)))
        self.assertNotIn("confirm_model", data)

    async def test_options_preview_and_cancel_do_not_save_or_mutate_lower_limits(self):
        saved = dict(inverter_max_power_kw=4, inverter_phase_max_power_kw=3,
                     discharge_max_kw=3, combined_output_limit_kw=4, min_soc_percent=65,
                     capacity_kwh=42, topology="load_only", sources={"soc": "sensor.example_soc"},
                     solcast={"api_key": "synthetic-key-never-in-preview"})
        flow = options_flow(options=saved)
        before = deepcopy(flow.config_entry.options)
        preview = await flow.async_step_inverter({"inverter_model": "SUN-6K-SG04LP1-EU",
            "inverter_phases": "3", "connection_phases": "3", "inverter_phase": "L3"})
        self.assertEqual(preview["step_id"], "inverter_confirm")
        self.assertEqual(flow.config_entry.options, before)
        self.assertNotIn("synthetic-key", repr(preview))
        refused = await flow.async_step_inverter_confirm({"confirm_model": False})
        self.assertEqual(refused["errors"], {"base": "confirm_inverter_model"})
        result = await flow.async_step_inverter_confirm({"confirm_model": True})
        for key, value in saved.items():
            self.assertEqual(result["data"][key], value)
        self.assertEqual(result["data"]["inverter_phases"], 1)
        self.assertEqual(result["data"]["inverter_phase"], "L3")
        self.assertEqual(flow.config_entry.options, before)

    async def test_model_change_is_locked_in_active_mode_at_both_steps(self):
        flow = options_flow(mode="active")
        for method in (flow.async_step_inverter, flow.async_step_inverter_confirm):
            self.assertEqual(await method({"confirm_model": True}),
                             {"type": "abort", "reason": "stop_before_mapping"})

    async def test_model_save_rejects_stale_limits_or_activation_after_preview(self):
        for change in ("limits", "mode"):
            with self.subTest(change=change):
                flow = options_flow(options={"inverter_max_power_kw": 8})
                await flow.async_step_inverter({"inverter_model": "SUN-6K-SG04LP1-EU"})
                if change == "limits":
                    flow.config_entry.options["inverter_max_power_kw"] = 2
                    expected = "inverter_settings_changed"
                else:
                    flow.config_entry.runtime_data.mode = "active"
                    expected = "stop_before_mapping"
                result = await flow.async_step_inverter_confirm({"confirm_model": True})
                self.assertEqual(result, {"type": "abort", "reason": expected})

    async def test_invalid_model_and_connection_return_readable_flow_errors(self):
        flow = options_flow()
        for values, error in (({"inverter_model": "missing"}, "invalid_inverter_model"),
                ({"inverter_model": "SUN-12K-SG04LP3-EU", "connection_phases": "1"},
                 "invalid_connection_phases")):
            with self.subTest(values=values):
                result = await flow.async_step_inverter(values)
                self.assertEqual(result["errors"]["base"], error)
                self.assertEqual(flow.config_entry.options, {})

