"""Accepted reductions with delayed register reports, never physical ACKs."""
from copy import deepcopy
from datetime import datetime
import unittest

from test_runtime import Coordinator, Harness, OWNERS, SOURCES, TZ, runtime


def scenario(when=None):
    h = Harness(when=when or datetime(2026, 11, 10, 5, 28, tzinfo=TZ),
                options={"winter_weather_soc_percent": 85})
    h.set("asymmetric_phase_feeding", "on", age=3600)
    h.set("soc", 65, "%")
    h.set("grid_current_number", 42, "A")
    h.set("load_power", 9280, "W")
    h.set("grid_power", 11200, "W")
    for index, value in enumerate((3000, 3500, 2780), 1):
        h.set(f"load_l{index}_power", value, "W")
    for index, value in enumerate((3700, 3800, 3700), 1):
        h.set(f"grid_l{index}_power", value, "W")
    h.set("battery_power", -1800, "W")
    for slot in (1, 2, 6):
        h.set(f"tou_soc_{slot}", 85, "%")
    h.set("tou_gc_2", "on")
    h.co._memory["ledger"][SOURCES["grid_current_number"]] = {
        "at": h.now.timestamp() - 60, "a": 42, "action": "set_value"}
    h.active()
    h.fail_grid_write = False
    original_call = h.call

    async def delayed_register(domain, action, data, **kwargs):
        if data["entity_id"] == SOURCES["grid_current_number"]:
            attempt = h.store.saved["ledger"][data["entity_id"]]
            assert attempt["a"] == data["value"] and attempt["action"] == action
            h.calls.append((domain, action, deepcopy(data)))
            if h.fail_grid_write:
                raise OSError("Synthetic unaccepted current command")
            # HA accepts the command, but the old setting remains until the
            # test publishes a later register read. Battery power is unchanged.
            return
        return await original_call(domain, action, data, **kwargs)

    h.hass.services.async_call = delayed_register
    return h


async def drive(h):
    inputs = h.co._read_inputs(h.now)
    control = h.co._controller(h.co._grid_input(inputs, h.now, 85, False))
    await h.co._run_driver(inputs, control, 85, False, h.now)
    return control


class BalancedGridRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_balanced_signal_requires_available_on_zero_load_and_live_measurements(self):
        h = scenario()
        self.assertIs(h.co._read_inputs(h.now)["grid_charge_balanced"], True)
        for state, expected in (("off", False), ("unavailable", None), ("unknown", None)):
            h.set("asymmetric_phase_feeding", state)
            self.assertIs(h.co._read_inputs(h.now)["grid_charge_balanced"], expected)
        h.set("asymmetric_phase_feeding", "on", attributes={"restored": True})
        self.assertIsNone(h.co._read_inputs(h.now)["grid_charge_balanced"])
        h.set("asymmetric_phase_feeding", "on", age=-1)
        self.assertIsNone(h.co._read_inputs(h.now)["grid_charge_balanced"])
        h.set("asymmetric_phase_feeding", "on")
        h.set("work_mode", "Zero Export To CT")
        self.assertIs(h.co._read_inputs(h.now)["grid_charge_balanced"], False)
        h.set("work_mode", "Zero Export To Load")
        h.set("grid_l1_power", 3700, "W", age=31)
        self.assertIsNone(h.co._read_inputs(h.now)["grid_charge_balanced"])

    async def test_accepted_reduction_42_to_37_keeps_active_gc_with_old_readback(self):
        h = scenario()
        control = await drive(h)
        self.assertEqual(h.current_calls(), [37])
        self.assertEqual(control["read_setting_a"], 42)
        self.assertTrue(control["reduction_pending"])
        self.assertFalse(control["setting_settled"])
        self.assertEqual(h.states[SOURCES["tou_gc_2"]].state, "on")
        self.assertFalse(any(action == "turn_off" for _, action, _ in h.calls))
        self.assertEqual(float(h.states[SOURCES["battery_power"]].state), -1800)
        h.advance(10)
        h.set("grid_current_number", 37, "A")
        settled = await drive(h)
        self.assertTrue(settled["setting_settled"])
        self.assertEqual(h.states[SOURCES["tou_gc_2"]].state, "on")

    async def test_lower_planning_cap_during_store_allows_safe_monotonic_reduction(self):
        h = scenario()
        def lower_planning_cap():
            h.set("load_power", 9460, "W")
            h.set("load_l1_power", 3180, "W")
        h.store.on_save = lower_planning_cap
        control = await drive(h)
        latest = runtime.calculate_grid_charge_cap(h.co._grid_input(h.co._read_inputs(h.now), h.now, 85, False))
        self.assertEqual(latest["planning_cap_a"], 34)
        self.assertEqual(h.current_calls(), [37])
        self.assertTrue(control["reduction_pending"])
        self.assertEqual(h.states[SOURCES["tou_gc_2"]].state, "on")

    async def test_an_increase_never_bypasses_the_current_planning_cap(self):
        h = scenario()
        self.assertFalse(await h.co._grid_attempt(43, h.now.timestamp(), force=True))
        self.assertEqual(h.current_calls(), [])
        self.assertIsNone(h.co._pending_grid_reduction)

    async def test_initial_gc_off_still_waits_for_exact_settled_readback(self):
        h = scenario()
        h.set("tou_gc_2", "off")
        # With charging OFF, GRID contains only LOAD. Enabling the charger
        # must have room for the full setting, not just a register delta.
        h.set("grid_power", 9280, "W")
        for index, value in enumerate((3000, 3500, 2780), 1):
            h.set(f"grid_l{index}_power", value, "W")
        await drive(h)
        self.assertEqual(h.states[SOURCES["tou_gc_2"]].state, "off")
        self.assertFalse(any(action == "turn_on" for _, action, _ in h.calls))
        h.advance(10)
        h.set("grid_current_number", 37, "A")
        def observe_policy():
            inputs = h.co._read_inputs(h.now)
            h.co._memory["current_policy"] = runtime.update_policy(
                h.co._grid_input(inputs, h.now, 85, False), h.co._memory["current_policy"])
        observe_policy()
        settled = await drive(h)
        self.assertTrue(settled["setting_settled"])
        self.assertEqual(h.states[SOURCES["tou_gc_2"]].state, "off")
        for _ in range(11):
            h.advance(10)
            observe_policy()
            await drive(h)
            self.assertEqual(h.states[SOURCES["tou_gc_2"]].state, "off")
        h.advance(10)
        observe_policy()
        await drive(h)
        self.assertEqual(h.states[SOURCES["tou_gc_2"]].state, "on")

    async def test_journal_only_and_failed_transport_do_not_authorize_gc_keep(self):
        for failure in ("journal_only", "transport"):
            with self.subTest(failure=failure):
                h = scenario()
                if failure == "journal_only":
                    h.co._memory["ledger"][SOURCES["grid_current_number"]] = {
                        "at": h.now.timestamp() - 1, "a": 37, "action": "set_value"}
                else:
                    h.fail_grid_write = True
                control = await drive(h)
                self.assertFalse(control["reduction_pending"])
                self.assertEqual(h.states[SOURCES["tou_gc_2"]].state, "off")
                self.assertIsNone(h.co._pending_grid_reduction)

    async def test_accepted_retry_does_not_extend_thirty_second_pending_bound(self):
        h = scenario()
        await drive(h)
        started = h.co._pending_grid_reduction["started_at"]
        h.advance(30)
        at_bound = await drive(h)
        self.assertTrue(at_bound["reduction_pending"])
        self.assertEqual(h.co._pending_grid_reduction["started_at"], started)
        h.advance(1)
        expired = await drive(h)
        self.assertFalse(expired["reduction_pending"])
        self.assertEqual(h.states[SOURCES["tou_gc_2"]].state, "off")

    async def test_failed_gc_off_after_timeout_does_not_renew_reduction_grace(self):
        h = scenario()
        await drive(h)
        started = h.co._pending_grid_reduction["started_at"]
        accepted_calls = h.hass.services.async_call
        rejected_off = []
        async def fail_only_gc_off(domain, action, data, **kwargs):
            if data["entity_id"] == SOURCES["tou_gc_2"] and action == "turn_off":
                rejected_off.append(h.now.timestamp())
                raise OSError("Synthetic GC OFF transport failure")
            return await accepted_calls(domain, action, data, **kwargs)
        h.hass.services.async_call = fail_only_gc_off
        h.advance(31)
        expired = await drive(h)
        self.assertFalse(expired["reduction_pending"])
        # The physical switch cannot be claimed OFF after a transport failure.
        self.assertEqual(h.states[SOURCES["tou_gc_2"]].state, "on")
        for _ in range(3):
            h.advance(10)
            retry = await drive(h)
            self.assertFalse(retry["reduction_pending"])
            self.assertEqual(h.co._grid_reduction_chain["started_at"], started)
        self.assertGreaterEqual(len(rejected_off), 3)
        self.assertEqual(h.co._last_error, "command_failed:OSError")

    async def test_failed_current_attempt_before_or_after_expiry_never_renews_chain_clock(self):
        for failure_age in (15, 41):
            for failure_kind in ("transport", "store"):
                with self.subTest(failure_age=failure_age, failure_kind=failure_kind):
                    h = scenario()
                    await drive(h)
                    started = h.co._grid_reduction_chain["started_at"]
                    accepted_calls = h.hass.services.async_call
                    async def fail_gc_off(domain, action, data, **kwargs):
                        if data["entity_id"] == SOURCES["tou_gc_2"] and action == "turn_off":
                            raise OSError("Synthetic GC OFF failure")
                        return await accepted_calls(domain, action, data, **kwargs)
                    h.hass.services.async_call = fail_gc_off
                    if failure_age > 30:
                        h.advance(31)
                        self.assertFalse((await drive(h))["reduction_pending"])
                        h.advance(failure_age - 31)
                    else:
                        h.advance(failure_age)
                    h.fail_grid_write = failure_kind == "transport"
                    h.store.fail = failure_kind == "store"
                    failed = await drive(h)
                    self.assertFalse(failed["reduction_pending"])
                    self.assertEqual(h.co._grid_reduction_chain["started_at"], started)
                    self.assertEqual(h.states[SOURCES["tou_gc_2"]].state, "on")
                    h.fail_grid_write = h.store.fail = False
                    h.advance(10)
                    retried = await drive(h)
                    self.assertEqual(retried["reduction_pending"], failure_age + 10 <= 30)
                    self.assertEqual(h.co._grid_reduction_chain["started_at"], started)
                    if failure_age + 10 <= 30:
                        h.advance(31 - (failure_age + 10))
                    else:
                        h.advance(10)
                    self.assertFalse((await drive(h))["reduction_pending"])
                    self.assertEqual(h.co._grid_reduction_chain["started_at"], started)

    async def test_pending_does_not_override_hard_grid_bms_stale_or_flag_guards(self):
        for failure in ("grid_total", "grid_phase", "bms_block", "bms_cap", "stale", "flag_off",
                        "flag_missing", "hardware_mode", "unexpected_increase", "zero_request"):
            with self.subTest(failure=failure):
                h = scenario()
                await drive(h)
                h.advance(10)
                if failure == "grid_total":
                    h.set("grid_power", 12400, "W")
                elif failure == "grid_phase":
                    h.set("grid_l2_power", 5100, "W")
                elif failure == "bms_block":
                    h.set("bms_blocking_charge", 1)
                elif failure == "bms_cap":
                    h.set("bms_charge_current", 30, "A")
                elif failure == "stale":
                    h.set("grid_l1_power", 3700, "W", age=31)
                elif failure == "flag_off":
                    h.set("asymmetric_phase_feeding", "off")
                elif failure == "flag_missing":
                    del h.states[SOURCES["asymmetric_phase_feeding"]]
                elif failure == "hardware_mode":
                    h.set("energy_priority", "Battery First")
                elif failure == "unexpected_increase":
                    h.set("grid_current_number", 45, "A")
                else:
                    h.set("soc", 85, "%")
                control = await drive(h)
                self.assertEqual(h.states[SOURCES["tou_gc_2"]].state, "off")
                self.assertFalse(control["reduction_pending"])

    async def test_owner_change_invalidates_pending_without_touching_another_owner(self):
        h = scenario()
        await drive(h)
        h.set_entity(OWNERS[0], "on")
        before = len(h.calls)
        await h.tick()
        self.assertEqual(h.co.mode, "shadow")
        self.assertEqual(len(h.calls), before)
        inputs = h.co._read_inputs(h.now)
        cap = runtime.calculate_grid_charge_cap(h.co._grid_input(inputs, h.now, 85, False))
        self.assertFalse(h.co._pending_reduction_ok(inputs, h.now, 37, cap))

    async def test_protected_boundary_during_store_never_keeps_gc_on(self):
        h = scenario(datetime(2026, 11, 10, 6, 59, 59, tzinfo=TZ))
        h.store.on_save = lambda: h.advance(2)
        await drive(h)
        self.assertEqual(h.states[SOURCES["tou_gc_2"]].state, "off")
        self.assertFalse(any(action == "turn_on" for _, action, _ in h.calls))

    async def test_protected_gc_slots_remain_off_during_pending_reduction(self):
        h = scenario()
        h.set("tou_gc_3", "on")
        h.set("tou_gc_5", "on")
        control = await drive(h)
        self.assertTrue(control["reduction_pending"])
        self.assertEqual(h.states[SOURCES["tou_gc_2"]].state, "on")
        for slot in (3, 5):
            self.assertEqual(h.states[SOURCES[f"tou_gc_{slot}"]].state, "off")

    async def test_restart_has_no_accepted_evidence_even_with_restored_journal(self):
        h = scenario()
        await drive(h)
        restored = Coordinator(h.hass, h.entry, store=h.store, clock=lambda: h.now)
        self.assertIsNone(restored._pending_grid_reduction)
        self.assertIsNone(restored._grid_reduction_chain)
