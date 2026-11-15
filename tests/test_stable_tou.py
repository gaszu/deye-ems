"""Stable TAURON clocks preserve actual calendars and existing plan deadlines."""
from copy import deepcopy
from datetime import date, datetime, time, timedelta
import unittest
from unittest.mock import patch

from test_installable import CALENDAR as CAL, TARIFF_SETTINGS
from test_tariff_config_flow import options_flow, preview
from test_tariff_runtime import GLOBALS, PLAN, options, request
from test_runtime import Harness


def instant(value):
    return datetime.fromisoformat(value)


class StableTauronClocks(unittest.TestCase):
    def program(self, day, profile="tauron_g13_2026", basis="local"):
        now = datetime.combine(date.fromisoformat(day), time(12), CAL.WARSAW)
        return GLOBALS["physical_tariff_tou"](now, options(profile, basis))

    def test_winter_approved_g11_and_g13_anchors_are_identical_on_every_day_type(self):
        expected = ["00:00:00", "04:00:00", "07:00:00", "13:00:00", "16:00:00", "21:00:00"]
        for profile in ("tauron_g11_2026", "tauron_g13_2026"):
            for day in ("2026-11-10", "2026-11-11", "2026-11-14", "2026-11-15"):
                with self.subTest(profile=profile, day=day):
                    program = self.program(day, profile)
                    self.assertTrue(program["valid"], program)
                    self.assertEqual([r["time"] for r in program["rows"]], expected)
        self.assertTrue(all(row["zone"] == "flat" and row["tier"] == 0
                            for row in self.program("2026-11-10", "tauron_g11_2026")["rows"]))
        self.assertTrue(all(row["grid_charge_allowed"] for row in self.program("2026-11-15")["rows"]))
        self.assertFalse(self.program("2026-11-10")["rows"][2]["grid_charge_allowed"])

    def test_summer_approved_g11_g13_use_selected_season_not_next_working_day(self):
        for profile in ("tauron_g11_2026", "tauron_g13_2026"):
            for day in ("2026-09-30", "2026-04-01", "2026-07-11", "2026-07-12"):
                self.assertEqual([r["time"] for r in self.program(day, profile)["rows"]],
                    ["00:00:00", "04:00:00", "07:00:00", "13:00:00", "19:00:00", "22:00:00"])
        self.assertEqual(self.program("2026-03-31")["template_season"], "winter")

    def test_g12_and_g12w_keep_all_normal_boundaries_year_round(self):
        for profile in ("tauron_g12_2026", "tauron_g12w_2026"):
            for month in range(1, 13):
                for day in (10, 11, 14, 15):
                    program = self.program(f"2026-{month:02}-{day:02}", profile)
                    self.assertEqual([r["time"] for r in program["rows"]],
                        ["00:00:00", "04:00:00", "06:00:00", "13:00:00", "15:00:00", "22:00:00"])
        self.assertFalse(self.program("2026-11-15", "tauron_g12_2026")["rows"][2]["grid_charge_allowed"])
        self.assertTrue(self.program("2026-11-15", "tauron_g12w_2026")["rows"][2]["grid_charge_allowed"])

    def test_fixed_cet_summer_converts_anchors_without_changing_meter_schedule(self):
        program = self.program("2026-07-12", basis="fixed_cet")
        self.assertEqual([r["time"] for r in program["rows"]],
                         ["01:00:00", "05:00:00", "08:00:00", "14:00:00", "20:00:00", "23:00:00"])
        now = instant("2026-07-12T00:30:00+02:00")
        program = GLOBALS["physical_tariff_tou"](now, options("tauron_g13_2026", "fixed_cet"))
        self.assertEqual(program["active_slot"], 6)

    def test_calendar_splits_cover_dst_season_and_free_day_transitions_exactly(self):
        for profile in CAL.STABLE_TAURON_PROFILES:
            for basis in ("local", "fixed_cet"):
                for day in (date(2026, 3, 29), date(2026, 4, 1), date(2026, 7, 12),
                            date(2026, 10, 1), date(2026, 10, 25), date(2026, 11, 11)):
                    with self.subTest(profile=profile, basis=basis, day=day):
                        start = datetime.combine(day, time.min, CAL.WARSAW)
                        end = datetime.combine(day + timedelta(days=1), time.min, CAL.WARSAW)
                        actual = CAL.intervals_between(start, end, profile, basis)
                        rows = CAL.stable_tou_intervals(start, end, profile, basis)
                        self.assertEqual(rows[0]["start_ts"], start.timestamp())
                        self.assertEqual(rows[-1]["end_ts"], end.timestamp())
                        self.assertEqual(sum(r["duration_seconds"] for r in rows), end.timestamp() - start.timestamp())
                        self.assertTrue(all(a["end_ts"] == b["start_ts"] for a, b in zip(rows, rows[1:])))
                        for row in rows:
                            logical = next(a for a in actual if a["start_ts"] <= row["start_ts"] < a["end_ts"])
                            self.assertLessEqual(row["end_ts"], logical["end_ts"])
                            self.assertEqual((row["zone"], row["tier"], row["grid_charge_allowed"]),
                                (logical["zone"], logical["tier"], logical["grid_charge_allowed"]))

    def test_physical_six_slots_match_every_actual_minute_for_all_four_profiles(self):
        for profile in CAL.STABLE_TAURON_PROFILES:
            for basis in ("local", "fixed_cet"):
                for text in ("2026-03-29", "2026-04-01", "2026-07-12", "2026-10-25", "2026-11-10", "2026-11-11"):
                    day = date.fromisoformat(text)
                    now = datetime.combine(day, time(12), CAL.WARSAW)
                    actual = CAL.describe_calendar(now, profile, basis)["today"]
                    program = GLOBALS["physical_tariff_tou"](now, options(profile, basis))
                    self.assertTrue(program["valid"], program)
                    for minute in range(1440):
                        at = now.replace(hour=minute // 60, minute=minute % 60, second=0).timestamp()
                        logical = next(r for r in actual if r["start_ts"] <= at < r["end_ts"])
                        physical = next((r for r in reversed(program["rows"]) if r["minute"] <= minute), program["rows"][-1])
                        self.assertEqual((physical["zone"], physical["grid_charge_allowed"]),
                            (logical["zone"], logical["grid_charge_allowed"]), (profile, basis, text, minute))

    def test_new_unrepresentable_catalog_boundary_fails_closed(self):
        original = CAL._PROFILES["tauron_g12_2026"]
        changed = {**original, "low_windows": [["22:00", "06:00"], ["13:30", "15:00"]]}
        with patch.dict(CAL._PROFILES, {"tauron_g12_2026": changed}):
            with self.assertRaisesRegex(ValueError, "tariff_exceeds_six_tou_slots"):
                CAL.stable_tou_template(instant("2026-11-10T12:00:00+01:00"), "tauron_g12_2026", "local")

    def test_foreign_and_legacy_are_not_silently_compiled_as_tauron(self):
        for profile in ("legacy_g13", "tauron_g13s_2026", "enea_g13active_2026", "pge_g12n_2026"):
            with self.assertRaisesRegex(ValueError, "stable_tariff_template_unavailable"):
                CAL.stable_tou_template(instant("2026-11-10T12:00:00+01:00"), profile, "local")
        self.assertGreater(len(CAL.calendar_profiles()), 4)
        self.assertEqual(set(TARIFF_SETTINGS.SELECTABLE_TARIFF_PROFILES), CAL.STABLE_TAURON_PROFILES)


class SharedSlotTargets(unittest.TestCase):
    def test_fixed_cet_local_midnight_clips_one_cycle_without_a_seventh_register(self):
        start, end = instant("2026-07-12T00:00:00+02:00"), instant("2026-07-13T00:00:00+02:00")
        rows = CAL.stable_tou_intervals(start, end, "tauron_g13_2026", "fixed_cet")
        self.assertEqual([row["slot"] for row in rows], [6, 1, 2, 3, 4, 5, 6])
        self.assertEqual(rows[0]["end"], "2026-07-12T01:00:00+02:00")
        self.assertEqual(rows[0]["slot_time"], "23:00:00")
        self.assertEqual({row["slot"] for row in rows}, {1, 2, 3, 4, 5, 6})

    def test_flat_and_weekend_show_six_rows_without_synthetic_deadlines(self):
        for profile in ("tauron_g11_2026", "tauron_g13_2026", "tauron_g12w_2026"):
            result = PLAN(request(now="2026-11-14T01:00:00+01:00", profile=profile))
            self.assertEqual(result["quality"], "valid")
            today = [r for r in result["tariff_slot_targets"] if r["start"].startswith("2026-11-14")]
            self.assertEqual([r["slot"] for r in today], [1, 2, 3, 4, 5, 6])
            targets = {r["deadline"]: r["soc_percent"] for r in result["targets"].values()}
            self.assertEqual(len(targets), 1)
            for row in result["tariff_slot_targets"]:
                if row["deadline"] is not None:
                    self.assertIn(row["deadline"], targets)
                    if row["charge_target_soc_percent"] is not None:
                        self.assertEqual(row["charge_target_soc_percent"], targets[row["deadline"]])

    def test_split_preserves_targets_and_nullable_projection_semantics(self):
        value = request(now="2026-11-10T14:05:00+01:00", profile="tauron_g13_2026")
        plan = PLAN(value)
        original = deepcopy(plan["targets"])
        now = instant(value["now"])
        rows = GLOBALS["tariff_slot_targets"](now, value["config"], plan, None, 40)
        self.assertEqual(plan["targets"], original)
        current = next(r for r in rows if instant(r["start"]).timestamp() <= now.timestamp() < instant(r["end"]).timestamp())
        self.assertIsNone(current["projected_soc_start_percent"])
        self.assertIsNone(current["projected_soc_end_percent"])
        self.assertIsNone(current["projection_from"])
        self.assertTrue(all(r["charge_target_soc_percent"] is None for r in rows if not r["grid_charge_allowed"]))
        self.assertTrue(all(r["deadline"] is None for r in rows if r["quality"] == "past"))


class SelectionCompatibility(unittest.IsolatedAsyncioTestCase):
    async def test_opening_foreign_saved_selection_does_not_choose_a_replacement(self):
        flow = options_flow(options={"tariff_profile": "enea_g12_2026", "tariff_clock_basis": "fixed_cet",
                                     "tariff_contract_confirmed": True, "min_soc_percent": 43})
        before = deepcopy(flow.config_entry.options)
        form = await flow.async_step_tariff()
        self.assertEqual(form["step_id"], "tariff_plan")
        profile_marker = next(marker for marker in form["data_schema"] if marker.key == "profile_id")
        self.assertNotIn("default", profile_marker.kw)
        self.assertEqual(flow.config_entry.options, before)

    async def test_foreign_unchanged_tariff_does_not_block_unrelated_active_save(self):
        flow = options_flow(mode="active", options={"tariff_profile": "enea_g12_2026", "tariff_clock_basis": "fixed_cet",
                                                   "tariff_contract_confirmed": True, "min_soc_percent": 43})
        result = flow.async_create_entry(title="", data={**flow.config_entry.options, "grid_import_limit_kw": 13})
        self.assertEqual(result["data"]["tariff_profile"], "enea_g12_2026")
        self.assertEqual(flow.config_entry.runtime_data.mode, "active")

    async def test_rogue_new_foreign_or_archived_selection_and_clock_change_are_rejected(self):
        for original, changed in (("tauron_g13_2026", "enea_g12_2026"),
                                  ("legacy_g13", "tauron_g13s_2026")):
            flow = options_flow(options={"tariff_profile": original, "tariff_clock_basis": "local"})
            with self.assertRaisesRegex(ValueError, "tariff_selection_restricted"):
                flow.async_create_entry(title="", data={"tariff_profile": changed})
        flow = options_flow(options={"tariff_profile": "enea_g12_2026", "tariff_clock_basis": "local"})
        with self.assertRaisesRegex(ValueError, "tariff_selection_restricted"):
            flow.async_create_entry(title="", data={"tariff_clock_basis": "fixed_cet"})

    async def test_foreign_config_can_explicitly_select_a_tauron_profile(self):
        flow = options_flow(options={"tariff_profile": "enea_g12_2026", "tariff_clock_basis": "fixed_cet"})
        form = await preview(flow, profile="tauron_g12w_2026")
        self.assertEqual(form["step_id"], "tariff_confirm")
        saved = await flow.async_step_tariff_confirm({"confirm_tariff": True})
        self.assertEqual(saved["data"]["tariff_profile"], "tauron_g12w_2026")


class StableClockRuntime(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def old_program(h):
        for slot, hour in enumerate((0, 3, 6, 9, 12, 18), 1):
            h.set(f"tou_time_{slot}", f"{hour:02}:00:00")

    async def test_accepted_zero_without_fresh_zero_ha_readback_never_changes_clocks(self):
        for variant in ("held_positive", "stale_zero", "zero_before_attempt", "restored_zero", "wrong_unit", "future_zero"):
            with self.subTest(variant=variant):
                h = Harness(when=datetime(2026, 11, 15, 5, tzinfo=CAL.WARSAW), options=options("tauron_g13_2026"))
                self.old_program(h)
                h.active()
                value = 30 if variant == "held_positive" else 0
                h.set("grid_current_number", value, "A", age=31 if variant == "stale_zero" else 1 if variant == "zero_before_attempt" else 0)
                original = h.call
                async def accepted_without_echo(domain, action, data, **kwargs):
                    if data["entity_id"] == h.co._sources["grid_current_number"]:
                        h.calls.append((domain, action, deepcopy(data)))
                        return  # Service returned, but HA did not acknowledge zero.
                    await original(domain, action, data, **kwargs)
                h.hass.services.async_call = accepted_without_echo
                if variant == "restored_zero":
                    h.set("grid_current_number", 0, "A", attributes={"restored": True})
                elif variant == "wrong_unit":
                    h.set("grid_current_number", 0, "W")
                elif variant == "future_zero":
                    h.set("grid_current_number", 0, "A", age=-1)
                await h.tick()
                clocks = {h.co._sources[f"tou_time_{i}"] for i in range(1, 7)}
                self.assertFalse(any(data["entity_id"] in clocks for _, _, data in h.calls))
                self.assertEqual(h.co.data["control"].get("runtime_reason"), "waiting_tou_zero_current_readback")
                self.assertTrue(all(h.co._state(f"tou_gc_{i}").state == "off" for i in range(1, 7)))

    async def test_store_race_invalidates_zero_readback_before_any_time_service(self):
        for variant in ("positive", "stale", "restored", "future", "pending_positive", "ledger_positive", "unknown_intent"):
            with self.subTest(variant=variant):
                h = Harness(when=datetime(2026, 11, 15, 5, tzinfo=CAL.WARSAW), options=options("tauron_g13_2026"))
                self.old_program(h)
                h.active()
                clocks = {h.co._sources[f"tou_time_{i}"] for i in range(1, 7)}
                changed = []
                def corrupt_on_clock_prepare():
                    if not changed and any(entity in h.store.saved["ledger"] for entity in clocks):
                        changed.append(True)
                        h.set("grid_current_number", 30 if variant == "positive" else 0, "A",
                            age=31 if variant == "stale" else -1 if variant == "future" else 0,
                            attributes={"restored": True} if variant == "restored" else {})
                        if variant in ("pending_positive", "ledger_positive"):
                            if variant == "pending_positive":
                                h.co._memory["grid_dispatch"] = {}
                            h.co._memory["ledger"][h.co._sources["grid_current_number"]] = {
                                "at": h.now.timestamp(), "a": 30, "action": "set_value"}
                        elif variant == "unknown_intent":
                            h.co._memory["grid_dispatch"] = {"outcome": "corrupt"}
                h.store.on_save = corrupt_on_clock_prepare
                await h.tick()
                self.assertTrue(changed)
                self.assertFalse(any(data["entity_id"] in clocks for _, _, data in h.calls))
                self.assertEqual(h.co._last_error, "last_moment_tariff_program_guard")
                self.assertEqual(h.co.data["status"], "waiting_tou_clock_readback")
                # A certainly-not-sent clock still retains its durable cooldown.
                prepared = {key: deepcopy(record) for key, record in h.co._memory["ledger"].items() if key in clocks}
                h.store.on_save = None
                h.set("grid_current_number", 0, "A")
                h.advance(1)
                await h.tick()
                self.assertEqual({key: record for key, record in h.co._memory["ledger"].items() if key in clocks}, prepared)
                self.assertFalse(any(data["entity_id"] in clocks for _, _, data in h.calls))

    async def test_latched_confirmed_zero_hours_old_allows_migration_without_zero_rewrites(self):
        for restarted, not_sent_retry in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(restarted=restarted, not_sent_retry=not_sent_retry):
                h = Harness(when=datetime(2026, 11, 15, 4, tzinfo=CAL.WARSAW), options=options("tauron_g13_2026"))
                h.active()
                await h.co._grid_attempt(0, h.now.timestamp(), force=True)
                memory = deepcopy(h.co._memory)
                h.advance(4000)
                if restarted:
                    h = Harness(when=h.now, options=options("tauron_g13_2026"))
                    h.co._memory = deepcopy(memory)
                    h.active()
                if not_sent_retry:
                    # Offline replay of a zero prepared durably but rejected
                    # before service; the previous confirmed zero stays valid.
                    original_hold, original_service = h.co._grid_duplicate_hold, h.co._service
                    h.co._grid_duplicate_hold = lambda *args: None
                    async def not_sent(*args):
                        return False
                    h.co._service = not_sent
                    await h.co._grid_attempt(0, h.now.timestamp(), force=True)
                    h.co._grid_duplicate_hold, h.co._service = original_hold, original_service
                    self.assertEqual(h.co._memory["grid_dispatch"]["outcome"], "not_sent")
                self.old_program(h)
                h.set("soc", 90, "%")
                h.set("grid_current_number", 0, "A", age=4000)
                zero_report = h.co._state("grid_current_number").last_reported
                h.calls.clear()
                for tick in range(4):
                    await h.tick()
                    self.assertTrue(h.co._clocks_ok(h.now))
                    self.assertEqual(h.current_calls(), [])
                    if tick == 0:
                        self.assertEqual(h.co.data["status"], "tariff_program_updated")
                    h.advance(10)
                    h.co._state("grid_current_number").last_reported = zero_report
                    h.co._state("grid_current_number").last_updated = zero_report
                clocks = {h.co._sources[f"tou_time_{i}"] for i in range(1, 7)}
                self.assertEqual(len([data for _, _, data in h.calls if data["entity_id"] in clocks]), 5)

    async def test_old_weekend_program_converts_in_active_only_after_zero_and_gc_off(self):
        for profile in ("tauron_g11_2026", "tauron_g13_2026"):
            h = Harness(when=datetime(2026, 11, 15, 5, tzinfo=CAL.WARSAW), options=options(profile))
            for slot, hour in enumerate((0, 3, 6, 9, 12, 18), 1):
                h.set(f"tou_time_{slot}", f"{hour:02}:00:00")
            original, seen = h.call, []
            async def call(domain, action, data, **kwargs):
                if data["entity_id"] in [h.co._sources[f"tou_time_{i}"] for i in range(1, 7)]:
                    self.assertEqual(h.co._state("grid_current_number").state, "0")
                    self.assertTrue(all(h.co._state(f"tou_gc_{i}").state == "off" for i in range(1, 7)))
                    seen.append(data)
                await original(domain, action, data, **kwargs)
                clocks = [h.co._state(f"tou_time_{i}").state for i in range(1, 7)]
                self.assertEqual(clocks, sorted(set(clocks)))
            h.hass.services.async_call = call
            h.active()
            await h.tick()
            self.assertTrue(seen)
            self.assertEqual(h.co.mode, "active")
            self.assertTrue(h.co._clocks_ok(h.now))
            self.assertFalse(any(action == "turn_on" for _, action, _ in h.calls))
            self.assertFalse(any(value > 0 for value in h.current_calls()))

    async def test_already_stable_weekend_program_never_rewrites_clock_registers(self):
        h = Harness(when=datetime(2026, 11, 15, 12, tzinfo=CAL.WARSAW), options=options("tauron_g13_2026"))
        h.active()
        await h.tick()
        clocks = {h.co._sources[f"tou_time_{i}"] for i in range(1, 7)}
        self.assertFalse(any(data["entity_id"] in clocks for _, _, data in h.calls))


if __name__ == "__main__":
    unittest.main()
