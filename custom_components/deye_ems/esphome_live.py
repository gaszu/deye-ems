"""Read-only ESPHome report evidence. No device commands or HA state writes.

Native sensor messages do not contain acquisition timestamps. Two distinct
packets in one verified connection provide conservative *receipt* evidence,
using the earlier receipt of the last two, never a fabricated device timestamp.
Optional SDK imports occur only after real provider bindings are configured.
"""
from __future__ import annotations

import asyncio
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import re
from typing import Any, Callable, Mapping

_UTC = timezone.utc
_MAC = re.compile(r"^[0-9a-f]{12}$")


@dataclass(frozen=True, repr=False)
class ProviderConfig:
    provider_id: str
    host: str
    port: int = 6053
    password: str = ""
    noise_psk: str | None = None
    expected_name: str | None = None
    expected_mac: str = ""
    enabled: bool = True


@dataclass(frozen=True, repr=False)
class BindingRequest:
    entity_id: str
    provider_id: str
    unique_id: str
    validation: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, repr=False)
class Binding:
    entity_id: str
    provider_id: str
    device_id: int
    key: int
    unit: str
    validation: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _Sample:
    received_at: datetime
    value: float


def normalize_mac(value):
    if not isinstance(value, str):
        return None
    value = value.replace(":", "").replace("-", "").lower()
    return value if _MAC.fullmatch(value) else None


def _clock_utc(clock):
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("invalid_receipt_clock")
    return value.astimezone(_UTC)


def _number(value, *, packet=False):
    if isinstance(value, bool) or packet and not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _within(value, validation):
    if value is None:
        return False
    low, high = validation.get("low"), validation.get("high")
    if low is not None and (_number(low, packet=True) is None or value < low):
        return False
    if high is not None and (_number(high, packet=True) is None or value > high):
        return False
    return not (low is not None and high is not None and low > high)


def _unit(value):
    # Only absence is normalized. W, kW and malformed strings are not aliases.
    return "" if value is None else value if isinstance(value, str) else None


def _unsigned(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 0xFFFFFFFF


def default_client_factory(config, *, zeroconf_instance=None):
    from aioesphomeapi import APIClient
    return APIClient(config.host, config.port, config.password,
        client_info="Deye EMS telemetry", noise_psk=config.noise_psk,
        expected_name=config.expected_name, expected_mac=normalize_mac(config.expected_mac),
        zeroconf_instance=zeroconf_instance,
        provide_time=False, outgoing_connection_target=False)


def default_binding_mapper(device_info, entities, requests):
    """Use the same public v3 identity builder as the native HA integration."""
    from aioesphomeapi import SensorInfo, build_device_unique_id
    candidates = {}
    for info in entities:
        if isinstance(info, SensorInfo):
            unique_id = build_device_unique_id(device_info.mac_address, info)
            candidates.setdefault(unique_id, []).append(info)
    result = []
    for request in requests:
        found = candidates.get(request.unique_id, [])
        if len(found) != 1:
            continue
        info = found[0]
        result.append(Binding(request.entity_id, request.provider_id,
            info.device_id, info.key, _unit(info.unit_of_measurement), dict(request.validation)))
    return result


class LiveReportCache:
    """Own one read-only client per provider, outside the synchronous control path."""

    def __init__(self, *, clock=None, client_factory=None, binding_mapper=None,
                 sensor_state_type=None, sleep=None):
        self._clock = clock or (lambda: datetime.now(_UTC))
        self._client_factory = client_factory or default_client_factory
        self._binding_mapper = binding_mapper or default_binding_mapper
        self._sensor_state_type = sensor_state_type
        self._sleep = sleep or asyncio.sleep
        self._providers = {}
        self._requests = {}
        self._bindings = {}
        self._by_entity = {}
        self._samples = {}
        self._tasks = {}
        self._clients = {}
        self._nonces = {}
        self._connected = set()
        self._generation = 0
        self._quarantined = True
        self._closed = False
        self._reason = "not_configured"
        self._configure_lock = asyncio.Lock()

    @property
    def status(self):
        try:
            now = _clock_utc(self._clock)
        except ValueError:
            now = None
        ready = 0
        for entity_id, pair in self._samples.items():
            binding = self._by_entity.get(entity_id)
            age = _number(binding.validation.get("age"), packet=True) if binding is not None else None
            if (now is not None and binding is not None and binding.provider_id in self._connected
                    and len(pair) == 2 and age is not None and age > 0
                    and all(0 <= (now-sample.received_at).total_seconds() <= age for sample in pair)):
                ready += 1
        return {"status": "closed" if self._closed else "quarantined" if self._quarantined
                else "connected" if self._connected else "waiting" if self._providers else "not_configured",
            "provider_count": len(self._providers), "connected_count": len(self._connected),
            "bound_entity_count": len(self._by_entity),
            "ready_entity_count": ready,
            "reason": self._reason}

    def _clear_proofs(self, reason):
        self._samples.clear()
        self._reason = reason

    def invalidate_all(self, reason="binding_changed"):
        """Synchronous event-boundary quarantine; old callbacks cannot refill it."""
        self._generation += 1
        self._quarantined = True
        self._connected.clear()
        self._nonces.clear()
        self._clear_proofs(reason if reason in ("binding_changed", "provider_changed", "provider_disabled",
            "configuration_changed", "unloaded", "closed") else "binding_changed")
        for task in self._tasks.values():
            task.cancel()

    async def _stop_owned(self):
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._clients.clear()
        self._bindings.clear()
        self._by_entity.clear()

    async def async_configure(self, providers, bindings):
        self.invalidate_all("configuration_changed")
        generation = self._generation
        async with self._configure_lock:
            await self._stop_owned()
            if self._closed or generation != self._generation:
                return
            configured = {}
            for provider in providers:
                if not isinstance(provider, ProviderConfig) or not provider.enabled:
                    continue
                if (not provider.provider_id or provider.provider_id in configured
                        or not isinstance(provider.host, str) or not provider.host
                        or not isinstance(provider.port, int) or isinstance(provider.port, bool)
                        or not 0 < provider.port <= 65535 or not normalize_mac(provider.expected_mac)):
                    self._reason = "invalid_provider_configuration"
                    self._providers, self._requests = {}, {}
                    return
                configured[provider.provider_id] = provider
            requests = {key: [] for key in configured}
            entities = set()
            for request in bindings:
                if not isinstance(request, BindingRequest) or request.provider_id not in configured:
                    continue
                if (not isinstance(request.entity_id, str) or not request.entity_id
                        or request.entity_id in entities or not isinstance(request.unique_id, str) or not request.unique_id):
                    self._reason = "ambiguous_binding"
                    self._providers, self._requests = {}, {}
                    return
                entities.add(request.entity_id)
                requests[request.provider_id].append(BindingRequest(request.entity_id, request.provider_id,
                    request.unique_id, dict(request.validation)))
            self._providers = {key: value for key, value in configured.items() if requests[key]}
            self._requests = {key: requests[key] for key in self._providers}
            self._quarantined = False
            self._reason = "connecting" if self._providers else "not_configured"
            for key, provider in self._providers.items():
                self._tasks[key] = asyncio.create_task(self._run(provider, generation),
                    name="Deye EMS native report subscription")

    configure = async_configure

    def _current(self, provider_id, generation, nonce):
        return (not self._closed and not self._quarantined and self._generation == generation
                and self._nonces.get(provider_id) is nonce)

    def _install_bindings(self, config, device_info, entities):
        if normalize_mac(getattr(device_info, "mac_address", None)) != normalize_mac(config.expected_mac):
            raise ValueError("device_identity_mismatch")
        if config.expected_name is not None and getattr(device_info, "name", None) != config.expected_name:
            raise ValueError("device_identity_mismatch")
        requested = {request.entity_id: request for request in self._requests[config.provider_id]}
        rows = self._binding_mapper(device_info, entities, tuple(requested.values()))
        result, by_entity = {}, {}
        for binding in rows:
            if (not isinstance(binding, Binding) or binding.provider_id != config.provider_id
                    or binding.entity_id not in requested or not _unsigned(binding.device_id) or not _unsigned(binding.key)
                    or _unit(binding.unit) is None or binding.entity_id in by_entity):
                raise ValueError("ambiguous_binding")
            key = (binding.device_id, binding.key)
            if key in result:
                raise ValueError("ambiguous_binding")
            request = requested[binding.entity_id]
            if request.validation.get("unit") is not None and binding.unit != request.validation["unit"]:
                continue
            # Range authority comes from the coordinator's request, never a mapper override.
            binding = Binding(binding.entity_id, binding.provider_id, binding.device_id,
                binding.key, binding.unit, dict(request.validation))
            result[key], by_entity[binding.entity_id] = binding, binding
        self._bindings[config.provider_id] = result
        self._by_entity.update(by_entity)

    def _receive(self, provider_id, generation, nonce, state):
        if not self._current(provider_id, generation, nonce) or provider_id not in self._connected:
            return
        state_type = self._sensor_state_type
        if state_type is None:
            from aioesphomeapi import SensorState
            state_type = SensorState
        if not isinstance(state, state_type):
            return
        device_id, entity_key = getattr(state, "device_id", None), getattr(state, "key", None)
        if not _unsigned(device_id) or not _unsigned(entity_key):
            return
        key = (device_id, entity_key)
        binding = self._bindings.get(provider_id, {}).get(key)
        if binding is None:
            return
        value = _number(getattr(state, "state", None), packet=True)
        if getattr(state, "missing_state", True) is not False or not _within(value, binding.validation):
            self._samples.pop(binding.entity_id, None)
            return
        try:
            at = _clock_utc(self._clock)
        except ValueError:
            self._samples.pop(binding.entity_id, None)
            return
        pair = self._samples.setdefault(binding.entity_id, deque(maxlen=2))
        if pair and at < pair[-1].received_at:
            pair.clear()
        pair.append(_Sample(at, value))

    async def _run(self, config, generation):
        backoff = 5
        while not self._closed and not self._quarantined and self._generation == generation:
            client, remove_close = None, None
            connected_at = None
            nonce, closed_event = object(), asyncio.Event()
            self._nonces[config.provider_id] = nonce
            try:
                client = self._client_factory(config)
                self._clients[config.provider_id] = client

                def connection_closed(event, connection_nonce=nonce, connection_event=closed_event):
                    if self._current(config.provider_id, generation, connection_nonce):
                        self._connected.discard(config.provider_id)
                        self._clear_proofs("disconnected")
                        connection_event.set()

                remove_close = client.add_connection_closed_callback(connection_closed)
                await client.connect(login=True)
                if not self._current(config.provider_id, generation, nonce):
                    return
                device_info, entities, _services = await client.device_info_and_list_entities()
                if not self._current(config.provider_id, generation, nonce):
                    return
                self._install_bindings(config, device_info, entities)
                self._connected.add(config.provider_id)
                # Exactly once per connection, including its initial state snapshot.
                client.subscribe_states(lambda state, connection_nonce=nonce:
                    self._receive(config.provider_id, generation, connection_nonce, state))
                self._reason = "receiving"
                connected_at = _clock_utc(self._clock)
                await closed_event.wait()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if self._current(config.provider_id, generation, nonce):
                    self._clear_proofs("device_identity_mismatch" if isinstance(error, ValueError)
                        and str(error) == "device_identity_mismatch" else "connection_failed")
            finally:
                if connected_at is not None:
                    with suppress(ValueError):
                        if (_clock_utc(self._clock)-connected_at).total_seconds() >= 60:
                            backoff = 5
                self._connected.discard(config.provider_id)
                self._bindings.pop(config.provider_id, None)
                self._by_entity = {entity: binding for entity, binding in self._by_entity.items()
                                   if binding.provider_id != config.provider_id}
                self._clear_proofs("disconnected")
                if callable(remove_close):
                    with suppress(Exception):
                        remove_close()
                if client is not None:
                    with suppress(Exception):
                        await asyncio.wait_for(client.disconnect(), timeout=5)
                self._clients.pop(config.provider_id, None)
            if not self._closed and not self._quarantined and self._generation == generation:
                await self._sleep(backoff)
                backoff = min(backoff * 2, 60)

    def effective_report(self, entity_id, ha_state, now, validation):
        """Synchronous RAM-only evidence. Unavailable/restored HA stays blocked."""
        if self._closed or self._quarantined:
            return None
        if ha_state is None:
            self._samples.pop(entity_id, None)
            return None
        binding = self._by_entity.get(entity_id)
        pair = self._samples.get(entity_id)
        if binding is None or binding.provider_id not in self._connected or pair is None or len(pair) != 2:
            return None
        attributes = getattr(ha_state, "attributes", {})
        if attributes.get("restored", False):
            self._samples.pop(entity_id, None)
            return None
        value = _number(getattr(ha_state, "state", None))
        unit = _unit(attributes.get("unit_of_measurement"))
        expected = validation.get("unit")
        if (unit != binding.unit or expected is not None and unit != expected
                or not _within(value, validation) or not all(_within(sample.value, validation) for sample in pair)
                or not math.isclose(value, pair[-1].value, rel_tol=1e-9, abs_tol=1e-6)):
            self._samples.pop(entity_id, None)
            return None
        if not isinstance(now, datetime) or now.tzinfo is None:
            return None
        if any(sample.received_at > now for sample in pair):
            return None
        return {"reported_at": pair[0].received_at, "source": "esphome_live", "samples": 2}

    async def async_close(self):
        self.invalidate_all("closed")
        self._closed = True
        async with self._configure_lock:
            await self._stop_owned()
            self._providers.clear()
            self._requests.clear()

    close = async_close
