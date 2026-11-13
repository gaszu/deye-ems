"""Real operator calendars drive planning, TOU and safety without live I/O."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

from test_runtime import Harness, runtime, TZ
from test_planner import fixture

PLAN = runtime.plan_energy
GLOBALS = PLAN.__globals__
calendar_profiles = runtime.describe_calendar.__globals__["calendar_profiles"]


def options(profile="enea_g12w_2026", basis="local"):
    return {"tariff_profile": profile, "tariff_clock_basis": basis,
            "tariff_contract_confirmed": True}


def request(now="2026-11-10T01:00:00+01:00", profile="enea_g12w_2026", **kwargs):
    value = fixture(now=now, **kwargs)
    value["config"].update(options(profile))
    return value


class OperatorPlanner(unittest.TestCase):
    def test_enea_weekday_midday_is_protected_and_never_grid_charges(self):
        result = PLAN(request(soc=45, load=1))
        self.assertEqual(result["quality"], "valid")
        midday = [r for r in result["rows"] if datetime.fromisoformat(r["timestamp"]).date().isoformat() == "2026-11-10"
                  and datetime.fromisoformat(r["timestamp"]).hour == 13]
        self.assertTrue(midday)
        self.assertTrue(all(r["protected"] and r["grid_charge_kw"] == 0 for r in midday))
        self.assertTrue(all(k.startswith("tariff_") for k in result["targets"]))
        self.assertEqual(next(iter(result["targets"].values()))["deadline"], "2026-11-10T06:00:00+01:00")

    def test_g11_has_weather_checkpoint_without_inventing_operator_boundary(self):
        result = PLAN(request(profile="pge_g11_2026"))
        self.assertEqual(result["quality"], "valid")
        target = next(iter(result["targets"].values()))
        self.assertTrue(target["virtual_checkpoint"])
        self.assertEqual(datetime.fromisoformat(target["deadline"]).hour, 7)
        self.assertTrue(all(not r["protected"] for r in result["rows"]))
        self.assertTrue(all(r["zone"] == "flat" for r in result["tariff_slot_targets"]))

    def test_weekend_is_contiguous_not_a_fake_midnight_deadline(self):
        now = datetime(2026, 11, 14, 12, tzinfo=TZ)
        context = GLOBALS["tariff_context"](now, options())
        self.assertEqual(datetime.fromisoformat(context["charge_window"]["end"]).astimezone(TZ).isoformat(),
                         "2026-11-16T06:00:00+01:00")
        result = PLAN(request(now=now.isoformat()))
        self.assertEqual(result["quality"], "valid")
        self.assertTrue(next(iter(result["targets"].values()))["virtual_checkpoint"])

    def test_fractional_first_row_has_real_remaining_duration_and_start_soc(self):
        result = PLAN(request(now="2026-11-10T01:29:00+01:00"))
        self.assertEqual(result["quality"], "valid")
        self.assertAlmostEqual(result["rows"][0]["duration_h"], 1/60)
        self.assertEqual(result["rows"][0]["soc_start_percent"], 75)
        current = next(r for r in result["tariff_slot_targets"] if r["projection_from"] == "2026-11-10T01:29:00+01:00")
        self.assertEqual(current["projected_soc_start_percent"], 75)
        self.assertIsNotNone(current["projected_soc_end_percent"])

    def test_past_protected_and_fallback_slot_semantics_are_not_fake_zeroes(self):
        value = request(now="2026-11-10T14:05:00+01:00")
        result = PLAN(value)
        past = [r for r in result["tariff_slot_targets"] if r["quality"] == "past"]
        self.assertTrue(past)
        self.assertTrue(all(r["projected_soc_start_percent"] is None and r["projected_soc_end_percent"] is None for r in past))
        protected = [r for r in result["tariff_slot_targets"] if not r["grid_charge_allowed"]]
        self.assertTrue(all(r["charge_target_soc_percent"] is None and r["reserve_soc_percent"] == 40 for r in protected))
        value["forecast"] = []
        fallback = PLAN(value)
        self.assertEqual(fallback["quality"], "invalid")
        self.assertTrue(any(r["quality"] == "fallback" for r in fallback["tariff_slot_targets"]))
        self.assertTrue(all(r["projected_soc_start_percent"] is None and r["projected_soc_end_percent"] is None
                            for r in fallback["tariff_slot_targets"]))

    def test_unconfirmed_expired_blocked_and_unknown_never_become_legacy(self):
        for profile, when, ack in (("enea_g12w_2026", "2026-11-10T01:00:00+01:00", False),
                                  ("enea_g12w_2026", "2027-01-10T01:00:00+01:00", True),
                                  ("pge_g12e_2026", "2026-11-10T01:00:00+01:00", True),
                                  ("not_a_profile", "2026-11-10T01:00:00+01:00", True)):
            with self.subTest(profile=profile, when=when):
                value = request(now=when, profile=profile)
                value["config"]["tariff_contract_confirmed"] = ack
                result = PLAN(value)
                self.assertEqual(result["quality"], "invalid")
                self.assertEqual(result["targets"], {})
                self.assertEqual(result["rows"], [])

    def test_every_supported_profile_has_exact_six_slot_eligibility(self):
        now = datetime(2026, 11, 10, 12, tzinfo=TZ)
        for metadata in calendar_profiles():
            if metadata["profile_id"] == "legacy_g13" or not metadata["supported"]:
                continue
            profile = metadata["profile_id"]
            with self.subTest(profile=profile):
                program = GLOBALS["physical_tariff_tou"](now, options(profile))
                self.assertTrue(program["valid"], program)
                self.assertEqual(len(program["rows"]), 6)
                clocks = [r["minute"] for r in program["rows"]]
                self.assertEqual(clocks, sorted(set(clocks)))
                day = runtime.describe_calendar(now, profile)["today"]
                for minute in range(1440):
                    instant = now.replace(hour=minute//60, minute=minute%60, second=0).timestamp()
                    logical = next(r for r in day if datetime.fromisoformat(r["start"]).timestamp() <= instant < datetime.fromisoformat(r["end"]).timestamp())
                    physical = next((r for r in reversed(program["rows"]) if r["minute"] <= minute), program["rows"][-1])
                    self.assertEqual(physical["grid_charge_allowed"], logical["grid_charge_allowed"])
                    self.assertEqual(physical["zone"], logical["zone"])

    def test_six_cyclic_changes_are_not_seven_hardware_slots(self):
        now = datetime(2026, 1, 12, 12, tzinfo=TZ)
        program = GLOBALS["physical_tariff_tou"](now, options("enea_g13active_2026"))
        self.assertTrue(program["valid"])
        self.assertEqual(len(runtime.describe_calendar(now, "enea_g13active_2026")["today"]), 7)
        self.assertEqual([r["time"] for r in program["rows"]],
                         ["06:00:00", "07:00:00", "10:00:00", "15:00:00", "20:00:00", "23:00:00"])

    def test_more_than_six_cyclic_changes_are_rejected_not_truncated(self):
        now = datetime(2026, 11, 10, 12, tzinfo=TZ)
        rows = [dict(start=now.replace(hour=i*3, minute=0).isoformat(),
                     zone=str(i%2), tier=i%2, grid_charge_allowed=i%2 == 0) for i in range(8)]
        with patch.dict(GLOBALS, describe_calendar=lambda *a: {"today": rows}):
            result = GLOBALS["physical_tariff_tou"](now, options())
        self.assertFalse(result["valid"])
        self.assertEqual(result["issue"], "tariff_exceeds_six_tou_slots")
        self.assertEqual(result["rows"], [])

    def test_fixed_cet_program_displays_shifted_summer_clocks(self):
        now = datetime(2026, 7, 10, 12, tzinfo=TZ)
        program = GLOBALS["physical_tariff_tou"](now, options("pge_g12_2026", "fixed_cet"))
        self.assertTrue(program["valid"])
        clocks = {r["time"] for r in program["rows"]}
        self.assertTrue({"07:00:00", "16:00:00", "18:00:00", "23:00:00"} <= clocks)

    def test_summer_grid_stays_emergency_only_for_an_operator_profile(self):
        result = PLAN(request(now="2026-07-10T01:00:00+02:00", profile="pge_g11_2026", soc=95, load=.2, pv=3))
        self.assertEqual(result["quality"], "valid")
        self.assertTrue(all(not t["emergency"] and t["soc_percent"] == 40 for t in result["targets"].values()))
        self.assertEqual(result["p10"]["grid_charge_kwh"], 0)
        self.assertGreater(result["p10"]["export_kwh"], 0)

    def test_optional_soc_age_anchor_is_not_lost_on_real_tariff_path(self):
        value = request()
        value["soc_updated_at"] = "2026-11-09T20:00:00+01:00"
        self.assertEqual(PLAN(value)["reason"], "stale_soc_without_bms_communication")
        value["voltage_updated_at"] = value["now"]
        self.assertEqual(PLAN(value)["quality"], "valid")

    def test_missing_current_soc_is_not_replaced_by_an_old_projection(self):
        value = request()
        plan = PLAN(value)
        now = datetime.fromisoformat(value["now"]) + timedelta(minutes=5)
        rows = GLOBALS["tariff_slot_targets"](now, value["config"], plan, None, 40)
        current = next(r for r in rows if datetime.fromisoformat(r["start"]).timestamp() <= now.timestamp()
                       < datetime.fromisoformat(r["end"]).timestamp())
        self.assertIsNone(current["projected_soc_start_percent"])
        self.assertIsNone(current["projected_soc_end_percent"])
        self.assertIsNone(current["projection_from"])


class OperatorRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_real_window_does_not_use_old_midday_or_old_night_boundaries(self):
        for hour, expected in ((13, False), (20, False), (21, True), (5, True), (6, False)):
            h = Harness(when=datetime(2026, 11, 10, hour, tzinfo=TZ), options=options())
            self.assertEqual(h.co._window(h.now)[1], expected)
            g = h.co._grid_input(h.co._read_inputs(h.now), h.now, 75, False)
            self.assertEqual(g["cheap_window"], expected)

    async def test_invalid_profile_blocks_preflight_and_any_positive_service(self):
        h = Harness(options={**options(), "tariff_contract_confirmed": False})
        with self.assertRaisesRegex(ValueError, "taryf"):
            await h.co.async_set_mode("active")
        h.co._memory["mode"] = "active"
        accepted = await h.co._service(h.co._sources["grid_current_number"], "set_value", 20)
        self.assertFalse(accepted)
        self.assertEqual(h.calls, [])
        self.assertEqual(h.co._target(h.now), (40, False, "invalid_tariff_configuration"))

    async def test_all_cheap_contiguous_window_keeps_one_initial_permission(self):
        h = Harness(when=datetime(2026, 11, 14, 23, 59, tzinfo=TZ), options=options())
        deadline = h.co._window(h.now)[3]
        h.now += timedelta(minutes=2)
        self.assertEqual(h.co._window(h.now)[3], deadline)
        self.assertEqual(deadline, datetime(2026, 11, 16, 6, tzinfo=TZ))
        g = h.co._grid_input(h.co._read_inputs(h.now), h.now, 75, False)
        self.assertLessEqual(g["remaining_h"], 24)
        self.assertEqual(g["policy_deadline"], deadline.isoformat())

    async def test_merged_defaults_do_not_count_as_explicit_clock_confirmation(self):
        raw = options()
        del raw["tariff_clock_basis"]
        h = Harness(options=raw)
        self.assertEqual(h.co._options["tariff_clock_basis"], "local")
        self.assertFalse(h.co._tariff_context(h.now)["valid"])
        with self.assertRaisesRegex(ValueError, "tariff_clock_confirmation_required"):
            h.co._preflight()

    async def test_clock_conversion_preserves_strict_order_and_never_charges_during_conversion(self):
        h = Harness(when=datetime(2026, 1, 12, 5, tzinfo=TZ), options=options("enea_g13active_2026"))
        original = h.call
        seen = []
        async def call(domain, action, data, **kw):
            await original(domain, action, data, **kw)
            if data["entity_id"] in [h.co._sources[f"tou_time_{i}"] for i in range(1,7)]:
                clocks = [h.co._state(f"tou_time_{i}").state for i in range(1,7)]
                seen.append(clocks)
                self.assertEqual(clocks, sorted(set(clocks)))
        h.hass.services.async_call = call
        h.active()
        await h.tick()
        self.assertTrue(seen)
        self.assertTrue(h.co._clocks_ok(h.now))
        self.assertFalse(any(action == "turn_on" for _,action,_ in h.calls))
        self.assertFalse(any(v > 0 for v in h.current_calls()))

    async def test_unconfirmed_clock_write_stops_before_the_next_clock(self):
        h = Harness(when=datetime(2026, 1, 12, 5, tzinfo=TZ), options=options("enea_g13active_2026"))
        async def queued(domain, action, data, **kw):
            h.calls.append((domain,action,deepcopy(data)))
        h.hass.services.async_call = queued
        h.active()
        await h.tick()
        writes = [data for _,_,data in h.calls if data["entity_id"] in
                  [h.co._sources[f"tou_time_{i}"] for i in range(1,7)]]
        self.assertEqual(len(writes), 1)
        self.assertEqual(h.co.data["status"], "waiting_tou_clock_readback")
        self.assertFalse(any(action == "turn_on" for _,action,_ in h.calls))

    async def test_profile_change_invalidates_plan_without_reserve_or_source_change(self):
        h = Harness()
        await h.tick()
        floor, sources = h.co._options["min_soc_percent"], deepcopy(h.co._sources)
        h.co._memory.update(mode="active", target_cache={"night": {}}, plan={"old": True})
        h.co._options.update(options())
        await h.tick()
        self.assertEqual(h.co.mode, "shadow")
        self.assertEqual(h.co._memory["target_cache"], {})
        self.assertEqual(h.co._sources, sources)
        self.assertEqual(h.co._options["min_soc_percent"], floor)

    async def test_tariff_settings_cannot_bypass_confirmed_observation_wizard(self):
        h = Harness()
        for key, value in options().items():
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "kreator"):
                await h.co.async_set_option(key, value)


class OperatorSlotMeter(unittest.TestCase):
    def test_enea_boundary_splits_actual_energy_and_persists_identity(self):
        update = runtime.update_slot_measurements
        def sample(at):
            return dict(at=at, battery_w=3600, grid_w=7200, telemetry_valid=True)
        m = update({}, sample("2026-11-10T20:59:55+01:00"), options())
        m = update(m, sample("2026-11-10T21:00:05+01:00"), options())
        rows = list(m["slots"].values())
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["seconds_valid"] == 5 for r in rows))
        self.assertTrue(all(r["profile_id"] == "enea_g12w_2026" and r["tariff_version"] for r in rows))
        self.assertAlmostEqual(sum(r["grid_import_kwh"] for r in rows), .02)

    def test_gap_and_unconfirmed_profile_never_manufacture_observed_energy(self):
        update = runtime.update_slot_measurements
        a = dict(at="2026-11-10T20:59:40+01:00", battery_w=3600, grid_w=7200, telemetry_valid=True)
        b = {**a, "at": "2026-11-10T21:00:20+01:00"}
        m = update(update({}, a, options()), b, options())
        self.assertEqual(sum(r["grid_import_kwh"] for r in m["slots"].values()), 0)
        self.assertEqual(m["reason"], "gap_above_30s")
        m = update(m, {**b, "at": "2026-11-10T21:00:30+01:00"}, {**options(), "tariff_contract_confirmed": False})
        self.assertIsNone(m["previous"])
        self.assertEqual(m["reason"], "invalid_tariff_configuration")

    def test_json_restart_keeps_identity_and_does_not_lose_a_valid_interval(self):
        update = runtime.update_slot_measurements
        a = dict(at="2026-11-10T20:00:00+01:00", battery_w=3600, grid_w=7200, telemetry_valid=True)
        m = json.loads(json.dumps(update({}, a, options())))
        m = update(m, {**a,"at":"2026-11-10T20:00:10+01:00"}, options())
        self.assertAlmostEqual(sum(r["grid_import_kwh"] for r in m["slots"].values()), .02)
