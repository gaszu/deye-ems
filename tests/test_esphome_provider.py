"""Offline tests for registry identity gates and adapter lifecycle only."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as Obj
import unittest

import importlib.util
from pathlib import Path
import sys

_path = Path(__file__).resolve().parents[1] / "custom_components/deye_ems/esphome_provider.py"
_spec = importlib.util.spec_from_file_location("esphome_provider", _path)
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)
ESPHomeProviderAdapter = _module.ESPHomeProviderAdapter
discover_provider_bindings = _module.discover_provider_bindings


@dataclass(frozen=True)
class Provider:
    provider_id: str
    host: str = field(repr=False)
    port: int = field(repr=False)
    password: str = field(repr=False)
    noise_psk: str | None = field(repr=False)
    expected_name: str | None = field(repr=False)
    expected_mac: str = field(repr=False)
    enabled: bool = True


@dataclass(frozen=True)
class Binding:
    entity_id: str
    provider_id: str
    unique_id: str
    validation: dict


class Entry:
    def __init__(self, entry_id="provider", **changes):
        self.entry_id = entry_id
        self.domain = "esphome"
        self.state = Obj(value="loaded")
        self.disabled_by = None
        self.unique_id = "01:23:45:67:89:ab"
        self.data = {"host": "existing-device.local", "port": 6053, "password": "private-password",
                     "noise_psk": "private-noise-key", "device_name": "existing-device"}
        self.runtime_data = Obj(client=OriginalClient())
        self.states = []
        self.updates = []
        self.__dict__.update(changes)

    def async_on_state_change(self, callback):
        self.states.append(callback)
        return lambda: self.states.remove(callback)

    def add_update_listener(self, callback):
        self.updates.append(callback)
        return lambda: self.updates.remove(callback)


class OriginalClient:
    def __init__(self):
        self.is_connected = True
        self.callbacks = []

    def add_connection_closed_callback(self, callback):
        self.callbacks.append(callback)
        return lambda: self.callbacks.remove(callback)

    def disconnect_event(self):
        self.is_connected = False
        for callback in tuple(self.callbacks):
            callback(Obj(expected_disconnect=False))


def registry_entry(entity_id="sensor.battery_voltage", **changes):
    data = dict(entity_id=entity_id, platform="esphome", config_entry_id="provider",
                unique_id="01:23:45:67:89:ab/0/sensor/Battery Voltage", disabled_by=None)
    data.update(changes)
    return Obj(**data)


CHECK = {"unit": "V", "age": 120, "low": 40, "high": 65}


class DiscoveryTests(unittest.TestCase):
    def discover(self, sources=None, checks=None, registry=None, entries=None):
        return discover_provider_bindings(
            sources or {"voltage": "sensor.battery_voltage"}, checks or {"voltage": CHECK},
            registry_get=(registry or {"sensor.battery_voltage": registry_entry()}).get,
            config_entry_get=(entries or {"provider": Entry()}).get,
            provider_factory=Provider, binding_factory=Binding,
        )

    def test_existing_esphome_entry_is_only_authority_for_connection(self):
        result = self.discover()
        self.assertEqual(len(result.providers), 1)
        provider = result.providers[0]
        self.assertEqual(provider.host, "existing-device.local")
        self.assertEqual(provider.expected_mac, "0123456789ab")
        self.assertEqual(provider.password, "private-password")
        self.assertEqual(result.bindings[0].validation, CHECK)
        self.assertNotIn("private-password", repr(result))
        self.assertNotIn("private-noise-key", repr(provider))

    def test_skip_generic_drivers_and_non_age_limited_measurements(self):
        for platform in ("template", "mqtt", "modbus"):
            with self.subTest(platform=platform):
                result = self.discover(registry={"sensor.battery_voltage": registry_entry(platform=platform)})
                self.assertEqual(result.providers, ())
                self.assertEqual(result.bindings, ())
        for check in ({"unit": "V", "age": None}, {"unit": "%", "age": 30},
                      {"unit": "A", "age": 30}, {"unit": "W", "age": float("nan")},
                      {"unit": "V", "age": 30, "low": 65, "high": 40}):
            with self.subTest(check=check):
                self.assertEqual(self.discover(checks={"voltage": check}).providers, ())
        self.assertEqual(self.discover(sources={"voltage": "number.battery_voltage"}).providers, ())

    def test_not_loaded_disabled_wrong_domain_or_identity_never_connects(self):
        entries = [Entry(state=Obj(value="setup_retry")), Entry(disabled_by="user"),
                   Entry(domain="mqtt"), Entry(unique_id="old-device-name"),
                   Entry(entry_id="wrong-entry")]
        for entry in entries:
            with self.subTest(entry=entry.__dict__):
                result = self.discover(entries={"provider": entry})
                self.assertEqual(result.providers, ())
                self.assertEqual(result.bindings, ())

    def test_provider_is_watched_while_not_loaded(self):
        entry = Entry(state=Obj(value="not_loaded"))
        result = self.discover(entries={"provider": entry})
        self.assertEqual(result.watched_entries, (entry,))
        self.assertEqual(result.providers, ())

    def test_original_ha_connection_offline_or_unobservable_never_opens_observer(self):
        entry = Entry()
        entry.runtime_data.client.is_connected = False
        self.assertEqual(self.discover(entries={"provider": entry}).providers, ())
        entry.runtime_data.client = Obj(is_connected=True)
        result = self.discover(entries={"provider": entry})
        self.assertEqual(result.providers, ())
        self.assertEqual(result.reasons["unsupported_original_lifecycle"], 1)

    def test_untrusted_registry_lookup_and_config_urls_are_rejected(self):
        result = self.discover(registry={"sensor.battery_voltage": registry_entry(entity_id="sensor.other")})
        self.assertEqual(result.providers, ())
        for host in ("https://host/", "name@host", "device.local ", "device.local:6053"):
            entry = Entry(data={"host": host, "port": 6053})
            with self.subTest(host=host):
                self.assertEqual(self.discover(entries={"provider": entry}).providers, ())

    def test_group_native_sensors_into_single_provider(self):
        registry = {"sensor.battery_voltage": registry_entry(),
                    "sensor.grid": registry_entry("sensor.grid", unique_id="native-grid")}
        result = self.discover(sources={"voltage": "sensor.battery_voltage", "grid_power": "sensor.grid"},
                               checks={"voltage": CHECK, "grid_power": {"unit": "W", "age": 30}},
                               registry=registry)
        self.assertEqual(len(result.providers), 1)
        self.assertEqual(len(result.bindings), 2)

    def test_conflicting_alias_does_not_choose_weaker_validation(self):
        result = self.discover(sources={"voltage": "sensor.battery_voltage", "other": "sensor.battery_voltage"},
                               checks={"voltage": CHECK, "other": {"unit": "V", "age": 999}})
        self.assertEqual(result.providers, ())
        self.assertEqual(result.bindings, ())
        self.assertEqual(result.reasons["conflicting_alias"], 1)


class Collector:
    def __init__(self):
        self.configurations = []
        self.invalidations = []
        self.report_reads = 0
        self.closed = False
        self.proof = None

    def invalidate_all(self, reason="binding_changed"):
        self.invalidations.append(reason)
        self.proof = None

    async def async_configure(self, providers, bindings):
        self.configurations.append((providers, bindings))

    def effective_report(self, *_):
        self.report_reads += 1
        return self.proof

    async def async_close(self):
        self.closed = True


class Bus:
    def __init__(self):
        self.callbacks = []

    def async_listen(self, event, callback):
        self.callbacks.append((event, callback))
        return lambda: self.callbacks.remove((event, callback))

    def fire_registry(self, **data):
        for _event, callback in tuple(self.callbacks):
            callback(Obj(data=data))


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = datetime(2026, 11, 13, 7, tzinfo=timezone.utc)
        self.entry = Entry()
        self.entries = {"provider": self.entry}
        self.entities = {"sensor.battery_voltage": registry_entry()}
        self.bus = Bus()
        self.hass = Obj(bus=self.bus, config_entries=Obj(async_get_entry=self.entries.get),
                        async_create_task=asyncio.create_task, states=Obj(get=lambda _: self.ha_state))
        self.ha_state = Obj(state="53", attributes={"unit_of_measurement": "V"},
                            last_reported=self.now - timedelta(seconds=5))
        self.collector = Collector()
        self.adapter = ESPHomeProviderAdapter(
            self.hass, self.collector, registry=Obj(async_get=self.entities.get),
            provider_factory=Provider, binding_factory=Binding,
            clock=lambda: self.now,
        )
        self.sources = {"voltage": "sensor.battery_voltage"}
        self.checks = {"voltage": CHECK}
        await self.adapter.async_configure(self.sources, self.checks)

    async def asyncTearDown(self):
        await self.adapter.async_close()

    async def drain(self):
        task = self.adapter._refresh_task
        if task:
            await task

    async def test_hotpath_does_not_discover_or_connect_and_status_is_sanitized(self):
        self.collector.proof = {"reported_at": 123}
        before = len(self.collector.configurations)
        self.assertEqual(self.adapter.effective_report("sensor.battery_voltage", None, None, CHECK), {"reported_at": 123})
        self.assertEqual(len(self.collector.configurations), before)
        self.assertEqual(self.collector.report_reads, 1)
        status = repr(self.adapter.status)
        for secret in ("private-password", "private-noise-key", "existing-device.local", "0123456789ab"):
            self.assertNotIn(secret, status)

    async def test_same_source_checks_do_not_reconnect(self):
        await self.adapter.async_configure(dict(self.sources), {"voltage": dict(CHECK)})
        self.assertEqual(len(self.collector.configurations), 1)

    async def test_registry_change_invalidates_before_background_refresh(self):
        self.collector.proof = {"reported_at": 123}
        self.bus.fire_registry(action="update", entity_id="sensor.battery_voltage", changes={"unique_id": "old"})
        self.assertIsNone(self.collector.proof)
        self.assertIsNone(self.adapter.effective_report("sensor.battery_voltage", None, None, CHECK))
        await self.drain()
        self.assertEqual(len(self.collector.configurations), 2)

    async def test_provider_unload_then_reload_rebuilds_and_watches(self):
        self.entry.state = Obj(value="unload_in_progress")
        for callback in tuple(self.entry.states):
            callback()
        self.assertTrue(self.adapter.status["refresh_pending"])
        await self.drain()
        self.assertEqual(self.collector.configurations[-1], ((), ()))
        self.assertEqual(len(self.entry.states), 1)
        self.entry.state = Obj(value="loaded")
        for callback in tuple(self.entry.states):
            callback()
        await self.drain()
        self.assertEqual(len(self.collector.configurations[-1][0]), 1)

    async def test_credential_change_uses_fresh_config_without_status_leak(self):
        self.entry.data = {**self.entry.data, "noise_psk": "new-private-key"}
        for callback in tuple(self.entry.updates):
            await callback(self.hass, self.entry)
        await self.drain()
        self.assertEqual(self.collector.configurations[-1][0][0].noise_psk, "new-private-key")
        self.assertNotIn("new-private-key", repr(self.adapter.status))

    async def test_source_range_change_invalidates_and_reconfigures(self):
        self.collector.proof = {"reported_at": 123}
        await self.adapter.async_configure(self.sources, {"voltage": {**CHECK, "low": 45}})
        self.assertIsNone(self.collector.proof)
        self.assertEqual(self.collector.configurations[-1][1][0].validation["low"], 45)

    async def test_initial_valid_ha_source_does_not_require_native_packets(self):
        self.assertFalse(self.adapter.source_invalid("sensor.battery_voltage"))

    async def test_disabled_provider_blocks_lingering_numeric_ha_state_immediately(self):
        self.entry.disabled_by = "user"
        self.assertTrue(self.adapter.source_invalid("sensor.battery_voltage"))
        self.entry.disabled_by = None
        self.entry.state = Obj(value="not_loaded")
        self.assertTrue(self.adapter.source_invalid("sensor.battery_voltage"))

    async def test_removed_known_provider_blocks_but_generic_driver_falls_back(self):
        self.entries.clear()
        self.assertTrue(self.adapter.source_invalid("sensor.battery_voltage"))
        self.entities["sensor.battery_voltage"].platform = "mqtt"
        self.assertFalse(self.adapter.source_invalid("sensor.battery_voltage"))

    async def test_registry_identity_change_blocks_even_before_event(self):
        self.entities["sensor.battery_voltage"].unique_id = "different-native-entity"
        self.assertTrue(self.adapter.source_invalid("sensor.battery_voltage"))

    async def test_original_disconnect_immediately_quarantines_with_entry_still_loaded(self):
        self.collector.proof = {"reported_at": self.now}
        original = self.entry.runtime_data.client
        original.disconnect_event()
        self.assertEqual(self.entry.state.value, "loaded")
        self.assertIsNone(self.collector.proof)
        self.assertTrue(self.adapter.source_invalid("sensor.battery_voltage"))
        await self.drain()
        self.assertEqual(self.collector.configurations[-1], ((), ()))
        original.is_connected = True
        self.adapter._check_original_health()
        await self.drain()
        self.assertEqual(len(self.collector.configurations[-1][0]), 1)
        self.assertTrue(self.adapter.source_invalid("sensor.battery_voltage"))
        self.now += timedelta(seconds=5)
        self.ha_state.last_reported = self.now
        self.assertFalse(self.adapter.source_invalid("sensor.battery_voltage"))

    async def test_original_listener_is_additive_removable_and_local_health_does_not_churn(self):
        original = self.entry.runtime_data.client
        other_callback = lambda _: None
        original.callbacks.append(other_callback)
        self.assertEqual(len(original.callbacks), 2)
        before = len(self.collector.configurations)
        for _ in range(3):
            self.adapter._check_original_health()
        await asyncio.sleep(0)
        self.assertEqual(len(self.collector.configurations), before)
        await self.adapter.async_close()
        self.assertEqual(original.callbacks, [other_callback])
        self.assertTrue(original.is_connected)

    async def test_lifetime_health_monitor_uses_background_tracking_and_cleans_up(self):
        await self.adapter.async_close()
        foreground, background = [], []

        def create_foreground(coroutine, name=None):
            task = asyncio.create_task(coroutine, name=name)
            foreground.append(task)
            return task

        def create_background(coroutine, name):
            task = asyncio.create_task(coroutine, name=name)
            background.append(task)
            return task

        self.hass.async_create_task = create_foreground
        self.hass.async_create_background_task = create_background
        self.collector = Collector()
        self.adapter = ESPHomeProviderAdapter(self.hass, self.collector,
            registry=Obj(async_get=self.entities.get), provider_factory=Provider,
            binding_factory=Binding, clock=lambda: self.now)
        await self.adapter.async_configure(self.sources, self.checks)
        self.assertEqual(foreground, [])
        self.assertEqual(len(background), 1)
        self.assertIs(self.adapter._health_task, background[0])
        self.assertFalse(background[0].done())
        await self.adapter.async_configure(self.sources, self.checks)
        self.assertEqual(len(background), 1)
        await self.adapter.async_close()
        self.assertTrue(background[0].done())
        self.assertTrue(background[0].cancelled())
        self.assertEqual(self.bus.callbacks, [])
        self.assertEqual(self.entry.runtime_data.client.callbacks, [])
        self.assertTrue(self.entry.runtime_data.client.is_connected)
        self.assertTrue(self.collector.closed)

    async def test_event_requires_new_valid_ha_report_or_post_event_native_proof(self):
        self.bus.fire_registry(action="update", entity_id="sensor.battery_voltage", changes={})
        await self.drain()
        self.assertTrue(self.adapter.source_invalid("sensor.battery_voltage"))
        self.now += timedelta(seconds=1)
        self.ha_state.last_reported = self.now
        self.ha_state.state = "unknown"
        self.assertTrue(self.adapter.source_invalid("sensor.battery_voltage"))
        self.ha_state.state = "53"
        self.assertFalse(self.adapter.source_invalid("sensor.battery_voltage"))

    async def test_native_evidence_can_release_event_gate_without_ha_stamp_write(self):
        self.bus.fire_registry(action="update", entity_id="sensor.battery_voltage", changes={})
        await self.drain()
        self.now += timedelta(seconds=5)
        old_ha_stamp = self.ha_state.last_reported
        self.collector.proof = {"reported_at": self.now - timedelta(seconds=1), "samples": 2}
        self.assertFalse(self.adapter.source_invalid("sensor.battery_voltage"))
        self.assertEqual(self.ha_state.last_reported, old_ha_stamp)

    async def test_unrelated_registry_change_has_no_effect(self):
        self.bus.fire_registry(action="update", entity_id="sensor.unrelated", changes={})
        await asyncio.sleep(0)
        self.assertEqual(len(self.collector.configurations), 1)

    async def test_close_removes_callbacks_and_prevents_reconfigure(self):
        await self.adapter.async_close()
        self.assertEqual(self.bus.callbacks, [])
        self.assertEqual(self.entry.states, [])
        self.assertEqual(self.entry.updates, [])
        self.assertTrue(self.collector.closed)
        await self.adapter.async_configure(self.sources, self.checks)
        self.assertEqual(len(self.collector.configurations), 1)
        self.assertIsNone(self.adapter.effective_report("sensor.battery_voltage", None, None, CHECK))

    async def test_actual_collector_contract_and_provider_disable_without_device_calls(self):
        from test_esphome_live import live
        NativeBinding, BindingRequest = live.Binding, live.BindingRequest
        LiveReportCache, ProviderConfig = live.LiveReportCache, live.ProviderConfig

        class Client:
            def __init__(inner):
                inner.callback = None
                inner.closed_callback = None
                inner.disconnected = False

            def add_connection_closed_callback(inner, callback):
                inner.closed_callback = callback
                return lambda: None

            async def connect(inner, *, login):
                self.assertTrue(login)

            async def device_info_and_list_entities(inner):
                return Obj(mac_address=self.entry.unique_id, name="existing-device"), [], []

            def subscribe_states(inner, callback):
                inner.callback = callback

            async def disconnect(inner):
                inner.disconnected = True

        clients = []

        def make_client(_config):
            client = Client()
            clients.append(client)
            return client

        collector = LiveReportCache(
            clock=lambda: self.now, client_factory=make_client, sensor_state_type=Obj,
            binding_mapper=lambda _di, _entities, requests: [
                NativeBinding(row.entity_id, row.provider_id, 0, 42, "V", row.validation) for row in requests],
        )
        adapter = ESPHomeProviderAdapter(
            self.hass, collector, registry=Obj(async_get=self.entities.get), clock=lambda: self.now,
            provider_factory=ProviderConfig, binding_factory=BindingRequest,
        )
        try:
            await adapter.async_configure(self.sources, self.checks)
            for _ in range(5):
                await asyncio.sleep(0)
                if clients and clients[0].callback is not None:
                    break
            client = clients[0]
            self.assertIsNotNone(client.callback)
            old_stamp = self.ha_state.last_reported
            packet = Obj(device_id=0, key=42, state=53.0, missing_state=False)
            client.callback(packet)
            self.assertIsNone(adapter.effective_report("sensor.battery_voltage", self.ha_state, self.now, CHECK))
            self.now += timedelta(seconds=5)
            client.callback(packet)
            proof = adapter.effective_report("sensor.battery_voltage", self.ha_state, self.now, CHECK)
            self.assertEqual(proof["samples"], 2)
            self.assertEqual(proof["reported_at"], self.now - timedelta(seconds=5))
            self.assertEqual(self.ha_state.last_reported, old_stamp)
            # HA may still mark the config entry LOADED while its native API
            # link has just failed. The owned observer must not mask that loss
            # from api.connected on the firmware.
            original = self.entry.runtime_data.client
            original.disconnect_event()
            self.assertTrue(adapter.source_invalid("sensor.battery_voltage"))
            self.assertIsNone(adapter.effective_report("sensor.battery_voltage", self.ha_state, self.now, CHECK))
            await adapter._refresh_task
            self.assertTrue(client.disconnected)
            self.assertEqual(len(clients), 1)
            self.assertEqual(self.entry.state.value, "loaded")
            original.is_connected = True
            adapter._check_original_health()
            await adapter._refresh_task
            for _ in range(5):
                await asyncio.sleep(0)
                if len(clients) == 2 and clients[1].callback is not None:
                    break
            self.assertEqual(len(clients), 2)
            self.now += timedelta(seconds=1)
            clients[1].callback(packet)
            self.assertIsNone(adapter.effective_report("sensor.battery_voltage", self.ha_state, self.now, CHECK))
            self.now += timedelta(seconds=5)
            clients[1].callback(packet)
            self.assertIsNotNone(adapter.effective_report("sensor.battery_voltage", self.ha_state, self.now, CHECK))
            self.entry.disabled_by = "user"
            self.assertTrue(adapter.source_invalid("sensor.battery_voltage"))
            self.assertIsNone(adapter.effective_report("sensor.battery_voltage", self.ha_state, self.now, CHECK))
        finally:
            await adapter.async_close()
        self.assertTrue(client.disconnected)
        self.assertTrue(clients[-1].disconnected)


if __name__ == "__main__":
    unittest.main()
