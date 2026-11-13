"""Real coordinator + provider/cache, with synthetic SDK/HA boundaries only."""
import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import AsyncMock, patch

from test_runtime import Coordinator, Harness, runtime
from test_esphome_live import Backoff, FakeClient, SensorInfo, SensorPacket, live
from test_esphome_provider import Entry, ESPHomeProviderAdapter, registry_entry


class Bus:
    def __init__(self):
        self.listeners = []

    def async_listen(self, name, callback):
        row = (name, callback)
        self.listeners.append(row)
        return lambda: self.listeners.remove(row)


class NativeFixture:
    def __init__(self):
        self.h = Harness()
        self.entry = Entry()
        self.clients = []
        self.backoff = Backoff()
        self.registry = {}
        self.info = {}
        for key, validation in self.h.co._native_stream_checks().items():
            entity_id = self.h.co._sources[key]
            self.add_entity(entity_id, validation["unit"])
        self.h.hass.bus = Bus()
        self.h.hass.config_entries.async_get_entry = lambda entry_id: self.entry if entry_id == self.entry.entry_id else None
        self.h.hass.async_create_task = lambda coro, *args: asyncio.create_task(coro)
        self.cache = live.LiveReportCache(clock=lambda: self.h.now, client_factory=self.factory,
            binding_mapper=self.mapper, sensor_state_type=SensorPacket, sleep=self.backoff)
        self.adapter = ESPHomeProviderAdapter(self.h.hass, self.cache,
            registry=Obj(async_get=self.registry.get), provider_factory=live.ProviderConfig,
            binding_factory=live.BindingRequest, clock=lambda: self.h.now)
        self.h.co = Coordinator(self.h.hass, self.h.entry, store=self.h.store, clock=lambda: self.h.now,
                                statistics_provider=self.h.statistics, report_provider=self.adapter)
        self.h.co._plan_due = self.h.now.timestamp()+10000

    def add_entity(self, entity_id, unit):
        self.registry[entity_id] = registry_entry(entity_id, unique_id=f"exact-{entity_id}")
        self.info[entity_id] = SensorInfo(key=len(self.info)+1, object_id=entity_id, unit_of_measurement=unit)

    def factory(self, config):
        client = FakeClient(config, entities=list(self.info.values()))
        self.clients.append(client)
        return client

    def mapper(self, device, entities, requests):
        by_id = {info.object_id: info for info in entities}
        return [live.Binding(row.entity_id, row.provider_id, by_id[row.entity_id].device_id,
                             by_id[row.entity_id].key, by_id[row.entity_id].unit_of_measurement, row.validation)
                for row in requests if row.entity_id in by_id and row.unique_id == f"exact-{row.entity_id}"]

    async def start(self):
        self.h.co._ensure_report_configuration()
        if self.h.co._report_setup_task:
            await self.h.co._report_setup_task
        await self.drain()

    async def drain(self):
        for _ in range(15):
            await asyncio.sleep(0)

    def emit(self, source, value=None):
        entity_id = self.h.co._sources[source]
        info = self.info[entity_id]
        if value is None:
            value = float(self.h.states[entity_id].state)
        self.clients[-1].emit(SensorPacket(info.key, value, False, info.device_id))

    def emit_twice(self, source):
        self.emit(source)
        self.emit(source)


class NativeReportRuntime(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixtures = []

    async def asyncTearDown(self):
        for fixture in self.fixtures:
            await fixture.h.co.async_shutdown()

    async def fixture(self):
        fixture = NativeFixture()
        self.fixtures.append(fixture)
        await fixture.start()
        return fixture

    async def test_two_live_reports_supplement_stale_ha_voltage_without_state_writes(self):
        f = await self.fixture()
        h = f.h
        h.set("voltage", 54, "V", age=175)
        original = h.states[h.co._sources["voltage"]]
        original_stamp = original.last_reported
        self.assertFalse(h.co._read_inputs(h.now)["telemetry_valid"])
        f.emit("voltage")
        self.assertFalse(h.co._read_inputs(h.now)["telemetry_valid"])
        first = h.now
        h.now += timedelta(seconds=1)
        f.emit("voltage")
        inputs = h.co._read_inputs(h.now)
        self.assertTrue(inputs["telemetry_valid"])
        self.assertEqual(inputs["voltage"], 54)
        row = next(row for row in inputs["telemetry_details"] if row["source"] == "voltage")
        self.assertEqual((row["timestamp_source"], row["age_seconds"], row["ha_age_seconds"], row["stream_samples"]),
                         ("esphome_live", 1, 176, 2))
        self.assertEqual(h.co._state("voltage").last_reported, first)
        self.assertIs(h.states[h.co._sources["voltage"]], original)
        self.assertEqual(original.last_reported, original_stamp)
        self.assertEqual(h.calls, [])

    async def test_original_ha_availability_unit_range_or_future_stamp_is_never_masked(self):
        f = await self.fixture()
        h = f.h
        for kind in ("unavailable", "restored", "future", "missing_stamp", "missing_entity", "wrong_unit", "range"):
            with self.subTest(kind=kind):
                h.set("voltage", 54, "V", age=175)
                f.emit_twice("voltage")
                original = h.states[h.co._sources["voltage"]]
                if kind == "unavailable":
                    original.state = "unavailable"
                elif kind == "restored":
                    original.attributes["restored"] = True
                elif kind == "future":
                    original.last_reported = h.now+timedelta(seconds=1)
                elif kind == "missing_stamp":
                    original.last_reported = original.last_updated = None
                elif kind == "missing_entity":
                    h.states.pop(h.co._sources["voltage"])
                elif kind == "wrong_unit":
                    original.attributes["unit_of_measurement"] = "mV"
                else:
                    original.state = "80"
                inputs = h.co._read_inputs(h.now)
                self.assertFalse(inputs["telemetry_valid"])
                self.assertIsNone(inputs["voltage"])
                with self.assertRaises(ValueError):
                    h.co._preflight()
                self.assertEqual(h.calls, [])

    async def test_disabled_or_disconnected_original_provider_blocks_even_fresh_numeric_ha(self):
        for kind in ("disabled", "disconnect"):
            with self.subTest(kind=kind):
                f = await self.fixture()
                h = f.h
                self.assertTrue(h.co._read_inputs(h.now)["telemetry_valid"])
                raw = h.states[h.co._sources["voltage"]]
                if kind == "disabled":
                    f.entry.disabled_by = "user"
                else:
                    f.entry.runtime_data.client.disconnect_event()
                inputs = h.co._read_inputs(h.now)
                self.assertFalse(inputs["telemetry_valid"])
                self.assertIsNone(inputs["voltage"])
                self.assertEqual(raw.state, "54")
                self.assertEqual(raw.last_reported, h.now)
                self.assertEqual(h.calls, [])

    async def test_native_receipts_keep_existing_ten_second_power_coherence_guard(self):
        f = await self.fixture()
        h = f.h
        for key, validation in h.co._native_stream_checks().items():
            if validation["unit"] == "W":
                old = h.states[h.co._sources[key]]
                h.set(key, float(old.state), "W", age=100)
        f.emit_twice("battery_power")
        h.now += timedelta(seconds=15)
        for key, validation in h.co._native_stream_checks().items():
            if validation["unit"] == "W" and key != "battery_power":
                f.emit_twice(key)
        inputs = h.co._read_inputs(h.now)
        self.assertFalse(inputs["charge_power_valid"])
        self.assertFalse(inputs["telemetry_valid"])
        self.assertIn({"source": "charge_power", "reason": "time_skew"}, inputs["telemetry_issues"])
        row = next(row for row in inputs["telemetry_details"] if row["source"] == "charge_power")
        self.assertEqual((row["observed_time_skew_seconds"], row["max_time_skew_seconds"]), (15, 10))
        self.assertEqual(h.calls, [])

    async def test_number_setpoint_readback_never_uses_native_sensor_receipt(self):
        f = await self.fixture()
        h = f.h
        h.set("grid_current_number", 0, "A", age=20)
        original = h.states[h.co._sources["grid_current_number"]]
        for key in h.co._native_stream_checks():
            f.emit_twice(key)
        self.assertIs(h.co._state("grid_current_number"), original)
        at = h.now.timestamp()-10
        h.co._memory["grid_dispatch"] = dict(id="synthetic-attempt", outcome="accepted", possible_at=at,
            possible_a=0, not_sent_at=None, attempt_at=at, unconfirmed_upper_a=0)
        inputs = h.co._read_inputs(h.now)
        request = h.co._grid_input(inputs, h.now, 75, False)
        self.assertEqual(request["pending_current_a"], 0)
        self.assertEqual(original.last_reported, h.now-timedelta(seconds=20))
        # Even an invalid action mapping to a streamed sensor must not acquire a proxy.
        h.co._sources["grid_current_number"] = h.co._sources["voltage"]
        self.assertIs(h.co._state("grid_current_number"), h.states[h.co._sources["voltage"]])
        self.assertIs(h.co._entity_state(h.co._sources["grid_current_number"], h.now),
                      h.states[h.co._sources["voltage"]])

    async def test_mapping_or_range_change_quarantines_before_any_background_io(self):
        f = await self.fixture()
        h = f.h
        h.set("voltage", 54, "V", age=175)
        f.emit_twice("voltage")
        self.assertTrue(h.co._read_inputs(h.now)["telemetry_valid"])
        new_entity = "sensor.changed_voltage"
        h.set_entity(new_entity, 54, "V", age=175)
        f.add_entity(new_entity, "V")
        h.co._sources["voltage"] = new_entity
        self.assertFalse(h.co._read_inputs(h.now)["telemetry_valid"])
        await f.start()
        h.now += timedelta(seconds=1)
        for key in h.co._native_stream_checks():
            f.emit_twice(key)
        self.assertTrue(h.co._read_inputs(h.now)["telemetry_valid"])
        h.co._options["inverter_model"] = "SUN-12K-SG04LP3-EU"
        h.set("voltage", 62, "V", age=175)
        f.emit_twice("voltage")
        self.assertFalse(h.co._read_inputs(h.now)["telemetry_valid"])
        self.assertIsNone(h.co._read_inputs(h.now)["voltage"])

    async def test_no_provider_keeps_classic_driver_behavior_and_shutdown_closes_only_owned_client(self):
        plain = Harness()
        before = deepcopy(plain.co._options)
        inputs = plain.co._read_inputs(plain.now)
        self.assertTrue(inputs["telemetry_valid"])
        self.assertEqual(inputs["report_stream"]["status"], "not_applicable")
        self.assertTrue(all(row["timestamp_source"] == "home_assistant" for row in inputs["telemetry_details"]))
        self.assertEqual(plain.co._options, before)
        f = await self.fixture()
        original = f.entry.runtime_data.client
        owned = f.clients[0]
        await f.h.co.async_shutdown()
        self.assertEqual(owned.disconnects, 1)
        self.assertTrue(original.is_connected)
        self.assertEqual(original.callbacks, [])
        self.assertEqual(f.h.hass.bus.listeners, [])
        self.assertEqual(f.h.calls, [])

    async def test_provider_factory_failure_retries_in_background_and_shutdown_cancels_retry(self):
        h = Harness()
        h.hass.bus = Bus()
        h.hass.config_entries.async_get_entry = lambda entry_id: None
        backoff = Backoff()
        h.co._report_retry_sleep = backoff
        factory = AsyncMock(side_effect=RuntimeError("synthetic-private-provider-failure"))
        with patch.object(runtime, "async_create_adapter", factory):
            h.co._ensure_report_configuration()
            for expected in (5, 10, 20, 40, 60, 60):
                for _ in range(12):
                    await asyncio.sleep(0)
                self.assertEqual(backoff.calls[-1], expected)
                attempts = factory.await_count
                # Repeated synchronous control reads cannot create more attempts.
                for _ in range(3):
                    h.co._read_inputs(h.now)
                self.assertEqual(factory.await_count, attempts)
                if len(backoff.calls) < 6:
                    backoff.release()
            self.assertEqual(h.co._report_stream_status()["status"], "unavailable")
            await h.co.async_shutdown()
            self.assertTrue(h.co._report_setup_task.done())
            self.assertEqual(h.calls, [])

    async def test_retry_recovers_with_latest_configuration_without_persisted_changes(self):
        h = Harness()
        h.hass.bus = Bus()
        h.hass.config_entries.async_get_entry = lambda entry_id: None
        backoff = Backoff()
        h.co._report_retry_sleep = backoff
        adapter = Obj(async_configure=AsyncMock(), async_close=AsyncMock(),
                      invalidate_all=lambda reason: None, source_invalid=lambda entity: False,
                      effective_report=lambda *args: None, status={})
        factory = AsyncMock(side_effect=[RuntimeError("private"), adapter])
        before = deepcopy(h.entry.options)
        with patch.object(runtime, "async_create_adapter", factory):
            h.co._ensure_report_configuration()
            for _ in range(12):
                await asyncio.sleep(0)
            h.co._sources["voltage"] = "sensor.latest_voltage"
            h.co._ensure_report_configuration()
            backoff.release()
            for _ in range(12):
                await asyncio.sleep(0)
            self.assertEqual(factory.await_count, 2)
            self.assertEqual(adapter.async_configure.await_args.args[0]["voltage"], "sensor.latest_voltage")
            self.assertFalse(h.co._report_failed)
            self.assertIsNone(h.co._report_pending)
            self.assertEqual(h.entry.options, before)
            await h.co.async_shutdown()
            adapter.async_close.assert_awaited_once()
