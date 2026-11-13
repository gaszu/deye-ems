"""Synthetic native-API packets only: no Home Assistant or device connection."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / "custom_components/deye_ems/esphome_live.py"
_spec = importlib.util.spec_from_file_location("esphome_live", _path)
live = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = live
_spec.loader.exec_module(live)


@dataclass
class SensorPacket:
    key: int = 10
    state: float = 54.
    missing_state: bool = False
    device_id: int = 0


@dataclass
class SensorInfo:
    key: int = 10
    device_id: int = 0
    unit_of_measurement: str = "V"
    object_id: str = "voltage"


class Backoff:
    def __init__(self):
        self.calls, self.waiters = [], []

    async def __call__(self, seconds):
        self.calls.append(seconds)
        future = asyncio.get_running_loop().create_future()
        self.waiters.append(future)
        await future

    def release(self):
        future = self.waiters.pop(0)
        if not future.done():
            future.set_result(None)


class FakeClient:
    def __init__(self, config, *, refuse=False, mac=None, entities=None):
        self.config, self.refuse = config, refuse
        self.info = SimpleNamespace(mac_address=mac or config.expected_mac,
                                    name=config.expected_name or "fixture")
        self.entities = entities or [SensorInfo()]
        self.disconnects, self.subscribes = 0, 0
        self.closed_callbacks, self.historical_callbacks = [], []
        self.state_callback = None
        self.is_connected = False

    def add_connection_closed_callback(self, callback):
        self.closed_callbacks.append(callback)
        self.historical_callbacks.append(callback)
        return lambda: self.closed_callbacks.remove(callback)

    async def connect(self, *, login):
        assert login is True
        if self.refuse:
            raise ConnectionError("synthetic-auth-secret-never-public")
        self.is_connected = True

    async def device_info_and_list_entities(self):
        return self.info, self.entities, []

    def subscribe_states(self, callback):
        self.subscribes += 1
        self.state_callback = callback

    async def disconnect(self):
        self.disconnects += 1
        self.is_connected = False

    def emit(self, packet=None):
        if self.state_callback:
            self.state_callback(packet or SensorPacket())

    def drop(self):
        self.is_connected = False
        for callback in tuple(self.closed_callbacks):
            callback(SimpleNamespace(expected_disconnect=False, reason="synthetic", error=None))


class Fixture:
    def __init__(self, *, refuse=False, metadata_mac=None, alias=False):
        self.now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        self.clients, self.backoff = [], Backoff()
        self.refuse, self.metadata_mac, self.alias = refuse, metadata_mac, alias
        self.cache = live.LiveReportCache(clock=lambda: self.now, client_factory=self.factory,
            binding_mapper=self.mapper, sensor_state_type=SensorPacket, sleep=self.backoff)
        self.validation = {"unit": "V", "age": 120, "low": 40, "high": 60}
        self.provider = live.ProviderConfig("entry-a", "fixture.local", password="synthetic-password",
            noise_psk="synthetic-psk", expected_name="fixture", expected_mac="aa:bb:cc:dd:ee:ff")
        self.request = live.BindingRequest("sensor.fixture_voltage", "entry-a", "exact-registry-id", self.validation)

    def factory(self, config):
        client = FakeClient(config, refuse=self.refuse, mac=self.metadata_mac)
        self.clients.append(client)
        return client

    def mapper(self, info, entities, requests):
        return [live.Binding(request.entity_id, request.provider_id, 0, 10 if self.alias else 10+i,
                             "V", request.validation) for i, request in enumerate(requests)]

    async def configure(self, *, requests=None):
        await self.cache.async_configure([self.provider], requests or [self.request])
        await self.drain()

    async def drain(self):
        for _ in range(12):
            await asyncio.sleep(0)

    def ha_state(self, value="54.0", unit="V", restored=False):
        return SimpleNamespace(state=value, attributes={"unit_of_measurement": unit, "restored": restored},
                               last_reported=self.now-timedelta(minutes=5))

    def report(self, state=None, validation=None):
        return self.cache.effective_report(self.request.entity_id, state or self.ha_state(),
                                           self.now, validation or self.validation)

    def emit(self, value=54, *, packet=None):
        self.clients[-1].emit(packet or SensorPacket(state=value))


class LiveReports(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixtures = []

    async def asyncTearDown(self):
        for fixture in self.fixtures:
            await fixture.cache.async_close()

    def fixture(self, **kwargs):
        fixture = Fixture(**kwargs)
        self.fixtures.append(fixture)
        return fixture

    async def test_initial_snapshot_never_grants_freshness_two_reports_use_older_receipt(self):
        f = self.fixture()
        await f.configure()
        first_at = f.now
        f.emit()
        self.assertIsNone(f.report())
        f.now += timedelta(seconds=5)
        f.emit()
        self.assertEqual(f.report(), {"reported_at": first_at, "source": "esphome_live", "samples": 2})
        self.assertEqual(f.clients[0].subscribes, 1)

    async def test_unchanged_real_reports_advance_conservative_receipt_without_state_write(self):
        f = self.fixture()
        await f.configure()
        state = f.ha_state()
        old_stamp = state.last_reported
        f.emit()
        f.now += timedelta(seconds=5)
        second_at = f.now
        f.emit()
        f.now += timedelta(seconds=5)
        f.emit()
        report = f.report(state)
        self.assertEqual(report["reported_at"], second_at)
        self.assertEqual(state.last_reported, old_stamp)
        self.assertEqual(state.state, "54.0")

    async def test_invalid_missing_nan_and_out_of_range_reset_pair(self):
        f = self.fixture()
        await f.configure()
        packets = [SensorPacket(missing_state=True), SensorPacket(state=float("nan")),
                   SensorPacket(state=float("inf")), SensorPacket(state=61), SensorPacket(state=True),
                   SensorPacket(state="54")]
        for packet in packets:
            with self.subTest(packet=packet):
                f.emit(); f.emit()
                self.assertIsNotNone(f.report())
                f.emit(packet=packet)
                self.assertIsNone(f.report())
                f.emit()
                self.assertIsNone(f.report())
                f.emit()
                self.assertIsNotNone(f.report())

    async def test_latest_value_must_match_ha_without_accuracy_decimal_relaxation(self):
        f = self.fixture()
        await f.configure()
        f.emit(54.0123); f.emit(54.0123)
        self.assertIsNone(f.report(f.ha_state("54.01")))
        f.emit(54.0123)
        self.assertIsNone(f.report(f.ha_state("54.0123")))
        f.emit(54.0123)
        self.assertIsNotNone(f.report(f.ha_state("54.0123")))

    async def test_unavailable_restored_missing_and_wrong_unit_ha_never_become_available(self):
        f = self.fixture()
        await f.configure()
        states = [f.ha_state("unavailable"), f.ha_state("unknown"), f.ha_state(unit="mV"),
                  f.ha_state(restored=True), None]
        for state in states:
            with self.subTest(state=state):
                f.emit(); f.emit()
                self.assertIsNotNone(f.report())
                self.assertIsNone(f.cache.effective_report(f.request.entity_id, state, f.now, f.validation))
                f.emit()
                self.assertIsNone(f.report())

    async def test_wrong_key_device_or_boolean_key_cannot_contribute_samples(self):
        f = self.fixture()
        await f.configure()
        for packet in [SensorPacket(key=11), SensorPacket(device_id=1), SensorPacket(key=True)]:
            f.emit(packet=packet); f.emit(packet=packet)
        self.assertIsNone(f.report())
        f.emit()
        self.assertIsNone(f.report())
        f.emit()
        self.assertIsNotNone(f.report())

    async def test_mac_mismatch_or_alias_binding_cannot_grant_proof(self):
        mismatch = self.fixture(metadata_mac="11:22:33:44:55:66")
        await mismatch.configure()
        self.assertEqual(mismatch.cache.status["connected_count"], 0)
        self.assertIsNone(mismatch.report())
        alias = self.fixture(alias=True)
        second = live.BindingRequest("sensor.other_voltage", "entry-a", "second-registry-id", alias.validation)
        await alias.configure(requests=[alias.request, second])
        self.assertEqual(alias.cache.status["bound_entity_count"], 0)
        alias.emit(); alias.emit()
        self.assertIsNone(alias.report())

    async def test_disconnect_clears_proof_and_reconnect_needs_two_new_packets(self):
        f = self.fixture()
        await f.configure()
        old = f.clients[0]
        f.emit(); f.emit()
        self.assertIsNotNone(f.report())
        old.drop()
        self.assertIsNone(f.report())
        await f.drain()
        self.assertEqual(f.backoff.calls, [5])
        f.backoff.release()
        await f.drain()
        self.assertEqual(len(f.clients), 2)
        self.assertEqual(f.clients[1].subscribes, 1)
        # Even if an old transport delivers queued callbacks after reconnect,
        # the connection nonce rejects both states and delayed close events.
        old.emit(); old.emit()
        for callback in old.historical_callbacks:
            callback(SimpleNamespace())
        self.assertIsNone(f.report())
        f.emit()
        self.assertIsNone(f.report())
        f.emit()
        self.assertIsNotNone(f.report())
        self.assertEqual(f.clients[0].subscribes, 1)

    async def test_synchronous_quarantine_blocks_inflight_packets_before_configure(self):
        f = self.fixture()
        await f.configure()
        old = f.clients[0]
        f.emit(); f.emit()
        self.assertIsNotNone(f.report())
        f.cache.invalidate_all("provider_changed")
        old.emit(); old.emit()
        self.assertIsNone(f.report())
        await f.configure()
        self.assertEqual(old.disconnects, 1)
        old.emit(); old.emit()
        f.emit()
        self.assertIsNone(f.report())
        f.emit()
        self.assertIsNotNone(f.report())

    async def test_range_change_revalidates_both_receipts_and_close_stays_closed(self):
        f = self.fixture()
        await f.configure()
        f.emit(54); f.emit(55)
        self.assertIsNone(f.report(f.ha_state("55"), {**f.validation, "high": 54.5}))
        f.emit(); f.emit()
        self.assertIsNotNone(f.report())
        f.now -= timedelta(seconds=1)
        self.assertIsNone(f.report())
        await f.cache.async_close()
        self.assertIsNone(f.report())
        self.assertEqual(f.cache.status["status"], "closed")

    async def test_refusal_backoff_is_bounded_and_status_contains_no_credentials(self):
        f = self.fixture(refuse=True)
        await f.configure()
        for _ in range(5):
            f.backoff.release()
            await f.drain()
        self.assertEqual(f.backoff.calls, [5, 10, 20, 40, 60, 60])
        public = json.dumps(f.cache.status)
        for private in (f.provider.host, f.provider.password, f.provider.noise_psk,
                        f.provider.expected_mac, "synthetic-auth-secret-never-public"):
            self.assertNotIn(private, public)
        self.assertTrue(all(client.subscribes == 0 for client in f.clients))

    async def test_repeated_short_connected_drops_back_off_until_connection_is_stable(self):
        f = self.fixture()
        await f.configure()
        for index in range(5):
            # Even two cached/snapshot-like packets do not reset connection backoff.
            f.emit(); f.emit()
            f.clients[-1].drop()
            await f.drain()
            self.assertEqual(f.backoff.calls[-1], [5, 10, 20, 40, 60][index])
            f.backoff.release()
            await f.drain()
        f.now += timedelta(seconds=60)
        f.clients[-1].drop()
        await f.drain()
        self.assertEqual(f.backoff.calls, [5, 10, 20, 40, 60, 5])

    async def test_ready_counter_expires_at_existing_older_receipt_age(self):
        f = self.fixture()
        await f.configure()
        f.emit()
        f.now += timedelta(seconds=5)
        f.emit()
        self.assertEqual(f.cache.status["ready_entity_count"], 1)
        f.now += timedelta(seconds=115)
        self.assertEqual(f.cache.status["ready_entity_count"], 1)
        f.now += timedelta(microseconds=1)
        self.assertEqual(f.cache.status["ready_entity_count"], 0)

    async def test_empty_or_disabled_configuration_creates_no_client_or_sdk_import(self):
        f = self.fixture()
        with patch.dict(sys.modules, {"aioesphomeapi": None}):
            await f.cache.async_configure([], [])
            await f.drain()
            self.assertEqual(f.clients, [])
            disabled = live.ProviderConfig("entry-a", "fixture.local", expected_mac="aabbccddeeff", enabled=False)
            await f.cache.async_configure([disabled], [f.request])
            await f.drain()
            self.assertEqual(f.clients, [])


class PublicSDKContract(unittest.TestCase):
    def test_default_factory_disables_time_and_outgoing_target(self):
        module = ModuleType("aioesphomeapi")
        calls = []
        module.APIClient = lambda *args, **kwargs: calls.append((args, kwargs))
        config = live.ProviderConfig("entry", "fixture.local", password="private", noise_psk="key",
            expected_name="fixture", expected_mac="AA:BB:CC:DD:EE:FF")
        shared_zeroconf = object()
        with patch.dict(sys.modules, {"aioesphomeapi": module}):
            live.default_client_factory(config, zeroconf_instance=shared_zeroconf)
        args, kwargs = calls[0]
        self.assertEqual(args, ("fixture.local", 6053, "private"))
        self.assertIs(kwargs["provide_time"], False)
        self.assertIs(kwargs["outgoing_connection_target"], False)
        self.assertEqual(kwargs["expected_mac"], "aabbccddeeff")
        self.assertIs(kwargs["zeroconf_instance"], shared_zeroconf)

    def test_metadata_mapper_uses_exact_public_identity_builder(self):
        module = ModuleType("aioesphomeapi")
        module.SensorInfo = SensorInfo
        calls = []
        def identity(mac, info):
            calls.append((mac, info))
            return f"exact-{info.device_id}-{info.key}"
        module.build_device_unique_id = identity
        first, other = SensorInfo(), SensorInfo(device_id=1)
        device = SimpleNamespace(mac_address="AA:BB:CC:DD:EE:FF")
        requests = [live.BindingRequest("sensor.voltage", "entry", "exact-0-10", {"unit": "V"}),
                    live.BindingRequest("sensor.wrong", "entry", "wrong", {"unit": "V"})]
        with patch.dict(sys.modules, {"aioesphomeapi": module}):
            mapped = live.default_binding_mapper(device, [first, other, object()], requests)
        self.assertEqual(calls, [(device.mac_address, first), (device.mac_address, other)])
        self.assertEqual(len(mapped), 1)
        self.assertEqual((mapped[0].device_id, mapped[0].key, mapped[0].entity_id), (0, 10, "sensor.voltage"))


if __name__ == "__main__":
    unittest.main()
