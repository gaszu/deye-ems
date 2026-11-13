"""Real tariff wizard boundaries: explicit choices, safe save and stale drafts."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

import test_installable as fixture

CALENDAR, TARIFF_SETTINGS = fixture.CALENDAR, fixture.TARIFF_SETTINGS

NOW = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)


def options_flow(*, mode="shadow", options=None):
    flow = fixture.Installation().flow()["DeyeEMSOptionsFlow"]()
    flow.config_entry = SimpleNamespace(data={"capacity_kwh": 34, "min_soc_percent": 40},
        options=deepcopy(options or {"sources": {"soc": "sensor.fixture_soc"},
            "extra_loads": [{"name": "fixture", "enabled": False}],
            "solcast": {"api_key": "synthetic-private-key"}}),
        runtime_data=SimpleNamespace(mode=mode))
    flow._tariff_time = lambda: NOW
    return flow


async def preview(flow, operator="tauron_dystrybucja", profile="tauron_g13_2026", clock="local"):
    result = await flow.async_step_tariff()
    if result.get("type") == "abort":
        return result
    result = await flow.async_step_tariff_operator({"operator_id": operator})
    if result.get("step_id") != "tariff_plan":
        return result
    return await flow.async_step_tariff_plan({"profile_id": profile, "clock_basis": clock})


class TariffWizard(unittest.IsolatedAsyncioTestCase):
    async def test_options_save_is_explicit_and_preserves_other_settings(self):
        flow = options_flow()
        before = deepcopy(flow.config_entry.options)
        form = await preview(flow)
        self.assertEqual(form["step_id"], "tariff_confirm")
        self.assertIn("TAURON", form["description_placeholders"]["tariff_preview"])
        self.assertEqual(flow.config_entry.options, before)
        denied = await flow.async_step_tariff_confirm({"confirm_tariff": False})
        self.assertEqual(denied["errors"]["base"], "confirm_tariff")
        self.assertEqual(flow.config_entry.options, before)
        saved = await flow.async_step_tariff_confirm({"confirm_tariff": True})
        self.assertEqual(saved["type"], "create_entry")
        self.assertEqual(saved["data"], {**before, "tariff_profile": "tauron_g13_2026",
            "tariff_clock_basis": "local", "tariff_contract_confirmed": True,
            "_configuration_save_id": saved["data"]["_configuration_save_id"]})
        self.assertEqual(flow.config_entry.options, before)  # HA commits only after return.

    async def test_active_mode_cannot_change_tariff_or_confirm_old_preview(self):
        flow = options_flow(mode="active")
        self.assertEqual(await flow.async_step_tariff(), {"type": "abort", "reason": "stop_before_mapping"})
        flow.config_entry.runtime_data.mode = "shadow"
        await preview(flow)
        flow.config_entry.runtime_data.mode = "active"
        result = await flow.async_step_tariff_confirm({"confirm_tariff": True})
        self.assertEqual(result, {"type": "abort", "reason": "stop_before_mapping"})

    async def test_operator_profile_mismatch_is_rejected(self):
        flow = options_flow()
        result = await preview(flow, operator="enea_operator")
        self.assertEqual(result["errors"]["base"], "tariff_operator_mismatch")

    async def test_missing_clock_is_not_assumed_local(self):
        flow = options_flow()
        await flow.async_step_tariff()
        await flow.async_step_tariff_operator({"operator_id": "tauron_dystrybucja"})
        result = await flow.async_step_tariff_plan({"profile_id": "tauron_g13_2026"})
        self.assertEqual(result["errors"]["base"], "invalid_tariff_clock_basis")

    async def test_blocked_official_profile_is_not_saved(self):
        flow = options_flow()
        result = await preview(flow, operator="pge_dystrybucja", profile="pge_g12e_2026")
        self.assertEqual(result["errors"]["base"], "tariff_profile_unavailable")
        self.assertNotIn("tariff_profile", flow.config_entry.options)

    async def test_only_requested_five_operators_are_offered_for_new_install(self):
        flow = fixture.Installation().flow()["DeyeEMSConfigFlow"]()
        form = await flow.async_step_user({"min_soc_percent": 40})
        self.assertEqual(form["step_id"], "tariff_operator")
        schema = next(iter(form["data_schema"].values()))
        rows = schema["args"][0]["options"]
        self.assertEqual({row["value"] for row in rows}, {"pge_dystrybucja", "tauron_dystrybucja",
            "enea_operator", "energa_operator", "pge_energetyka_kolejowa"})

    async def test_changed_sources_invalidates_confirmation(self):
        flow = options_flow()
        await preview(flow)
        flow.config_entry.options["sources"]["soc"] = "sensor.changed_soc"
        result = await flow.async_step_tariff_confirm({"confirm_tariff": True})
        self.assertEqual(result, {"type": "abort", "reason": "tariff_configuration_changed"})

    async def test_date_expiry_is_rechecked_at_save(self):
        flow = options_flow()
        flow._tariff_time = lambda: datetime(2026, 12, 31, 12, tzinfo=timezone.utc)
        await preview(flow)
        flow._tariff_time = lambda: datetime(2027, 1, 1, 12, tzinfo=timezone.utc)
        result = await flow.async_step_tariff_confirm({"confirm_tariff": True})
        self.assertEqual(result, {"type": "abort", "reason": "tariff_outside_validity"})

    async def test_unknown_persisted_profile_can_be_repaired(self):
        flow = options_flow(options={"tariff_profile": "deleted_profile"})
        form = await preview(flow)
        self.assertEqual(form["step_id"], "tariff_confirm")
        saved = await flow.async_step_tariff_confirm({"confirm_tariff": True})
        self.assertEqual(saved["data"]["tariff_profile"], "tauron_g13_2026")

    async def test_cancelled_draft_does_not_mutate_entry_or_start_production(self):
        flow = options_flow()
        before = deepcopy(flow.config_entry.options)
        await preview(flow, clock="fixed_cet")
        self.assertEqual(flow.config_entry.options, before)
        self.assertEqual(flow.config_entry.runtime_data.mode, "shadow")

    async def test_confirming_identical_settings_still_notifies_ha_with_new_save_intent(self):
        flow = options_flow()
        await preview(flow)
        first = await flow.async_step_tariff_confirm({"confirm_tariff": True})
        # Model HA committing the first result; a second identical selection
        # must differ so HA's options listener can actually run again.
        flow.config_entry.options = deepcopy(first["data"])
        await preview(flow)
        second = await flow.async_step_tariff_confirm({"confirm_tariff": True})
        first_id, second_id = first["data"]["_configuration_save_id"], second["data"]["_configuration_save_id"]
        self.assertEqual(len(first_id), 32)
        self.assertEqual(len(second_id), 32)
        self.assertNotEqual(first_id, second_id)
        self.assertEqual({key: value for key, value in first["data"].items() if key != "_configuration_save_id"},
                         {key: value for key, value in second["data"].items() if key != "_configuration_save_id"})


class TariffPreview(unittest.TestCase):
    def test_conditional_benefit_and_requirements_are_readable(self):
        calendar = CALENDAR.describe_calendar(NOW, "tauron_g12as_2026", "local")
        text = TARIFF_SETTINGS.tariff_preview(calendar)
        self.assertIn("przyrostu zużycia", text)
        smart = TARIFF_SETTINGS.tariff_preview(CALENDAR.describe_calendar(NOW, "tauron_g13s_2026", "local"))
        self.assertIn("licznika zdalnego", smart)
        self.assertNotIn("remote_meter", smart)

    def test_local_and_fixed_cet_preview_are_distinct_in_summer(self):
        summer = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
        profiles = CALENDAR.calendar_profiles()
        _, local = TARIFF_SETTINGS.validate_tariff_draft(profiles, "tauron_dystrybucja",
            "tauron_g13_2026", "local", now=summer, describe=CALENDAR.describe_calendar)
        _, fixed = TARIFF_SETTINGS.validate_tariff_draft(profiles, "tauron_dystrybucja",
            "tauron_g13_2026", "fixed_cet", now=summer, describe=CALENDAR.describe_calendar)
        self.assertNotEqual(local["today"], fixed["today"])
        self.assertIn("stały czas zimowy", TARIFF_SETTINGS.tariff_preview(fixed))


if __name__ == "__main__":
    unittest.main()
