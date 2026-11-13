"""Durable mode-write races keep manual STOP above post-save activation."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest

from test_runtime import Harness, runtime
from test_planner import fixture


class PostSaveCoordinator(unittest.IsolatedAsyncioTestCase):
    def manager(self, h, status="waiting"):
        alive = {"value": True, "cancels": 0}
        def cancel(entry_id, reason):
            alive.update(value=False, cancels=alive["cancels"]+1)
        h.hass.data = {"deye_ems_post_save": SimpleNamespace(cancel=cancel,
            get_status=lambda entry_id: {"status": status}, requires_reload=lambda entry_id, co: False)}
        return alive

    async def test_manual_stop_cancels_waiting_activation_before_lock(self):
        h = Harness()
        alive = self.manager(h)
        await h.co._lock.acquire()
        active = asyncio.create_task(h.co.async_set_mode("active", activation_guard=lambda: alive["value"]))
        await asyncio.sleep(0)
        stop = asyncio.create_task(h.co.async_set_mode("shadow"))
        await asyncio.sleep(0)
        self.assertFalse(alive["value"])
        h.co._lock.release()
        with self.assertRaisesRegex(ValueError, "activation_cancelled"):
            await active
        await stop
        self.assertEqual(h.co.mode, "shadow")
        self.assertEqual(h.store.saved["mode"], "shadow")
        self.assertEqual(h.calls, [])

    async def test_manual_stop_during_store_is_durable_before_any_refresh(self):
        h = Harness()
        alive = self.manager(h)
        entered, release = asyncio.Event(), asyncio.Event()
        async def save(value):
            h.store.saved = deepcopy(value)
            h.store.history.append(deepcopy(value))
            if value["mode"] == "active":
                entered.set()
                await release.wait()
        h.store.async_save = save
        active = asyncio.create_task(h.co.async_set_mode("active", activation_guard=lambda: alive["value"]))
        await entered.wait()
        stop = asyncio.create_task(h.co.async_set_mode("shadow"))
        await asyncio.sleep(0)
        self.assertFalse(alive["value"])
        release.set()
        with self.assertRaisesRegex(ValueError, "activation_cancelled"):
            await active
        await stop
        self.assertEqual([r["mode"] for r in h.store.history[:2]], ["active", "shadow"])
        self.assertEqual(h.co.mode, "shadow")
        self.assertEqual(h.calls, [])

    async def test_guarded_store_failure_leaves_ram_shadow(self):
        h = Harness()
        h.store.fail = True
        with self.assertRaises(OSError):
            await h.co.async_set_mode("active", activation_guard=lambda: True)
        self.assertEqual(h.co.mode, "shadow")
        self.assertEqual(h.calls, [])

    async def test_internal_configuration_pause_stops_and_confirms_without_cancelling_intent(self):
        h = Harness()
        alive = self.manager(h)
        h.active()
        h.set("grid_current_number", 20, "A")
        h.set("tou_gc_6", "on")
        await h.co.async_set_mode("shadow", activation_guard=lambda: alive["value"])
        self.assertTrue(alive["value"])
        self.assertEqual(alive["cancels"], 0)
        self.assertEqual(h.co.mode, "shadow")
        self.assertEqual(h.co._state("tou_gc_6").state, "off")
        self.assertEqual(h.co._state("grid_current_number").state, "0")
        self.assertTrue(any(action == "turn_off" for _,action,_ in h.calls))

    async def test_unconfirmed_configuration_pause_is_shadow_but_does_not_allow_reload(self):
        h = Harness()
        alive = self.manager(h)
        h.active()
        h.set("grid_current_number", 20, "A")
        h.set("tou_gc_6", "on")
        async def queued(domain, action, data, **kw):
            h.calls.append((domain,action,deepcopy(data)))
        h.hass.services.async_call = queued
        async def no_delay(_seconds): pass
        h.co._configuration_pause_sleep = no_delay
        with self.assertRaisesRegex(ValueError, "configuration_pause_unconfirmed"):
            await h.co.async_set_mode("shadow", activation_guard=lambda: alive["value"])
        self.assertEqual(h.co.mode, "shadow")
        self.assertEqual(h.store.saved["mode"], "shadow")
        self.assertTrue(alive["value"])

    async def test_configuration_pause_waits_for_reports_without_repeating_sends_or_store(self):
        h = Harness()
        alive = self.manager(h)
        h.active()
        h.set("grid_current_number", 20, "A")
        h.set("tou_gc_6", "on")
        async def queued(domain, action, data, **kw):
            h.calls.append((domain,action,deepcopy(data)))
        h.hass.services.async_call = queued
        snapshots = []
        async def delayed(_seconds):
            self.assertEqual(h.co.mode, "shadow")
            self.assertEqual(h.store.saved["mode"], "shadow")
            snapshots.append((len(h.calls), len(h.store.history)))
            if len(snapshots) == 2:
                h.set("grid_current_number", 0, "A")
                h.set("tou_gc_6", "off")
        h.co._configuration_pause_sleep = delayed
        await h.co.async_set_mode("shadow", activation_guard=lambda: alive["value"])
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[0], snapshots[1])
        self.assertTrue(alive["value"])

    async def test_manual_stop_during_report_wait_revokes_auto_intent(self):
        h = Harness()
        alive = self.manager(h)
        h.active()
        h.set("grid_current_number", 20, "A")
        async def queued(domain, action, data, **kw):
            h.calls.append((domain,action,deepcopy(data)))
        h.hass.services.async_call = queued
        stops = []
        async def stop_during_wait(_seconds):
            stops.append(asyncio.create_task(h.co.async_set_mode("shadow")))
            await asyncio.sleep(0)
        h.co._configuration_pause_sleep = stop_during_wait
        with self.assertRaisesRegex(ValueError, "activation_cancelled"):
            await h.co.async_set_mode("shadow", activation_guard=lambda: alive["value"])
        await stops[0]
        self.assertFalse(alive["value"])
        self.assertEqual(h.co.mode, "shadow")

    async def test_pending_reload_does_not_restore_active_before_preparation(self):
        h = Harness()
        self.manager(h)
        h.store.saved = {"mode": "active"}
        await h.co.async_initialize()
        self.assertEqual(h.co.mode, "shadow")
        self.assertEqual(h.store.saved["mode"], "shadow")
        self.assertEqual(h.calls, [])

    async def test_stale_measurements_do_not_start_planning_or_activate(self):
        h = Harness()
        h.set("voltage", "unavailable", "V")
        called = []
        async def forbidden(*args): called.append(True)
        h.co._make_plan = forbidden
        result = await h.co.async_prepare_activation()
        self.assertFalse(result["ready"])
        self.assertEqual(result["reason"], "waiting_for_measurements")
        self.assertFalse(result["recalculated"])
        self.assertEqual(called, [])
        self.assertEqual(h.co.mode, "shadow")

    async def test_missing_forecast_can_prepare_explicit_conservative_plan(self):
        h = Harness()
        result = await h.co.async_prepare_activation()
        self.assertTrue(result["ready"], result)
        self.assertTrue(result["recalculated"])
        self.assertEqual(result["plan_source"], "own_conservative_fallback")
        self.assertEqual(result["plan_reason"], "incomplete_48h_forecast")
        self.assertEqual(h.co.mode, "shadow")
        self.assertEqual(h.calls, [])

    async def test_configuration_fallback_is_not_accepted_as_forecast_gap(self):
        h = Harness()
        value = fixture(now=h.now.isoformat())
        value["config"]["battery_charge_max_a"] = None
        h.co._memory["plan"] = runtime.plan_energy(value)
        result = await h.co.async_prepare_activation(recalculate=False)
        self.assertFalse(result["ready"])
        self.assertEqual(result["reason"], "waiting_for_plan")
        self.assertEqual(h.co.mode, "shadow")

    async def test_operator_profile_conservative_plan_has_matching_dated_targets(self):
        h = Harness(options={"tariff_profile": "enea_g12w_2026", "tariff_clock_basis": "local",
                             "tariff_contract_confirmed": True})
        result = await h.co.async_prepare_activation()
        self.assertTrue(result["ready"], result)
        self.assertEqual(result["plan_source"], "own_conservative_fallback")
        self.assertTrue(all(k.startswith("tariff_") for k in h.co._memory["plan"]["targets"]))
        self.assertEqual(h.co.mode, "shadow")

    async def test_changed_configuration_during_planning_is_rejected(self):
        h = Harness()
        async def change(*args):
            h.co._options["capacity_kwh"] += 1
        h.co._make_plan = change
        result = await h.co.async_prepare_activation()
        self.assertFalse(result["ready"])
        self.assertEqual(result["reason"], "activation_conditions_failed")
        self.assertTrue(result["recalculated"])
        self.assertEqual(h.co.mode, "shadow")

    async def test_old_runtime_cannot_activate_after_cancelled_save_but_manual_stop_still_works(self):
        h = Harness()
        self.manager(h)
        old = h.co
        h.hass.data["deye_ems_post_save"].requires_reload = lambda entry_id, co: co is old
        h.entry.options = {**h.entry.options, "capacity_kwh": 77}
        with self.assertRaisesRegex(ValueError, "nie została jeszcze załadowana"):
            await old.async_set_mode("active")
        await old.async_set_mode("shadow")
        self.assertEqual(old.mode, "shadow")
        self.assertEqual(h.calls, [])
        new = runtime.DeyeEMSCoordinator(h.hass, h.entry, store=h.store, clock=lambda: h.now,
                                        statistics_provider=h.statistics)
        new._preflight(retake=True)
        self.assertEqual(new._options["capacity_kwh"], 77)

