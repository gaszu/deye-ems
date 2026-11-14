"""Discover native telemetry providers through Home Assistant registries.

This adapter never writes HA states or changes an ESPHome config entry.  Only
selected numeric sensors that already belong to a loaded ESPHome integration
can supply a provider.  Network work belongs to the separate LiveReportCache;
effective_report is deliberately synchronous and performs no discovery or I/O.

HA and aioesphomeapi imports are deferred so discovery can be tested offline.
Credentials are passed only to the private transport configuration and are
never included in discovery/status results intended for presentation.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import ipaddress
import math
import re
from typing import Any

_ENTITY_ID = re.compile(r"sensor\.[a-z0-9_]+\Z")
_HOST_NAME = re.compile(r"[a-zA-Z0-9_.-]+\Z")
_MAC = re.compile(r"[0-9a-f]{12}\Z")
_EVENT_ENTITY_REGISTRY_UPDATED = "entity_registry_updated"


def _mac(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.lower().replace(":", "").replace("-", "")
    return normalized if _MAC.fullmatch(normalized) else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _validation(value: Any) -> dict[str, Any] | None:
    """Accept the existing age-limited power/voltage validator, without edits."""
    if not isinstance(value, Mapping) or value.get("unit") not in ("W", "V"):
        return None
    age = _number(value.get("age"))
    if age is None or age <= 0:
        return None
    result = {"unit": value["unit"], "age": value["age"]}
    for key in ("low", "high"):
        bound = value.get(key)
        if bound is not None and _number(bound) is None:
            return None
        if key in value:
            result[key] = bound
    if result.get("low") is not None and result.get("high") is not None:
        if result["low"] > result["high"]:
            return None
    return result


def _loaded(entry: Any) -> bool:
    state = getattr(entry, "state", None)
    return getattr(state, "value", state) == "loaded" and getattr(entry, "disabled_by", None) is None


def _original_client(entry: Any) -> Any:
    # RuntimeEntryData.client is the APIClient owned by HA's ESPHome integration.
    # Only its public connection lifecycle is observed; never change its state
    # callback subscriptions, reconnect logic, credentials, or connection.
    return getattr(getattr(entry, "runtime_data", None), "client", None)


def _original_connected(entry: Any) -> bool:
    return getattr(_original_client(entry), "is_connected", False) is True


def _host(value: Any) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        return value if _HOST_NAME.fullmatch(value) else None


@dataclass(frozen=True)
class Discovery:
    """Private transport inputs; only counts/reasons are safe for diagnostics."""

    providers: tuple[Any, ...] = field(repr=False)
    bindings: tuple[Any, ...] = field(repr=False)
    watched_entries: tuple[Any, ...] = field(repr=False)
    known_entities: frozenset[str] = field(repr=False)
    reasons: dict[str, int]


async def async_create_adapter(hass: Any, *, clock: Callable[[], datetime] | None = None) -> "ESPHomeProviderAdapter":
    """Construct on HA's setup path, sharing its existing Zeroconf instance.

    There is no aioesphomeapi import or device connection until discovery
    produces a genuine loaded ESPHome provider. No separate UDP probe is used.
    """
    from homeassistant.components import zeroconf
    from .esphome_live import LiveReportCache, default_client_factory

    shared_zeroconf = await zeroconf.async_get_instance(hass)
    collector = LiveReportCache(
        clock=clock,
        client_factory=lambda config: default_client_factory(config, zeroconf_instance=shared_zeroconf),
    )
    return ESPHomeProviderAdapter(hass, collector, clock=clock)


def discover_provider_bindings(
    sources: Mapping[str, str],
    checks: Mapping[str, Mapping[str, Any]],
    *,
    registry_get: Callable[[str], Any],
    config_entry_get: Callable[[str], Any],
    provider_factory: Callable[..., Any],
    binding_factory: Callable[..., Any],
) -> Discovery:
    """Build private transport requests solely from registry-linked providers.

    The collector must additionally compare the connected DeviceInfo MAC and
    exact SensorInfo-derived unique IDs before accepting a packet.  This
    discovery step is not sufficient evidence that a device is the provider.
    """
    providers: dict[str, Any] = {}
    bindings: dict[str, Any] = {}
    watched: dict[str, Any] = {}
    known_entities: set[str] = set()
    reasons: Counter[str] = Counter()
    seen_validation: dict[str, dict[str, Any]] = {}
    rejected_aliases: set[str] = set()
    for source_key, check in checks.items():
        validation = _validation(check)
        if validation is None:
            reasons["ineligible_validation"] += 1
            continue
        entity_id = sources.get(source_key)
        if not isinstance(entity_id, str) or not _ENTITY_ID.fullmatch(entity_id):
            reasons["ineligible_entity"] += 1
            continue
        if entity_id in rejected_aliases:
            continue
        if entity_id in seen_validation:
            if seen_validation[entity_id] != validation:
                # Do not select a weaker validator when aliases disagree.
                reasons["conflicting_alias"] += 1
                rejected_aliases.add(entity_id)
                bindings.pop(entity_id, None)
            continue
        seen_validation[entity_id] = validation
        registry_entry = registry_get(entity_id)
        if registry_entry is None or getattr(registry_entry, "entity_id", None) != entity_id:
            reasons["missing_registry"] += 1
            continue
        if getattr(registry_entry, "platform", None) != "esphome":
            reasons["other_platform"] += 1
            continue
        known_entities.add(entity_id)
        if getattr(registry_entry, "disabled_by", None) is not None:
            reasons["entity_disabled"] += 1
            continue
        provider_id = getattr(registry_entry, "config_entry_id", None)
        unique_id = getattr(registry_entry, "unique_id", None)
        if not isinstance(provider_id, str) or not provider_id or not isinstance(unique_id, str) or not unique_id:
            reasons["missing_identity"] += 1
            continue
        entry = config_entry_get(provider_id)
        if entry is None or getattr(entry, "entry_id", None) != provider_id or getattr(entry, "domain", None) != "esphome":
            reasons["missing_provider"] += 1
            continue
        watched[provider_id] = entry
        if not _loaded(entry):
            reasons["provider_not_loaded"] += 1
            continue
        if not _original_connected(entry):
            reasons["original_connection_offline"] += 1
            continue
        if not callable(getattr(_original_client(entry), "add_connection_closed_callback", None)):
            # A permanent observer must never mask loss of HA's original client
            # from firmware's api.connected failsafe.
            reasons["unsupported_original_lifecycle"] += 1
            continue
        data = getattr(entry, "data", None)
        expected_mac = _mac(getattr(entry, "unique_id", None))
        if not isinstance(data, Mapping) or expected_mac is None:
            reasons["invalid_provider_identity"] += 1
            continue
        host = _host(data.get("host"))
        port = data.get("port", 6053)
        password = data.get("password", "")
        noise_psk = data.get("noise_psk")
        expected_name = data.get("device_name")
        if (host is None or isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535
                or password is not None and not isinstance(password, str)
                or noise_psk is not None and not isinstance(noise_psk, str)
                or expected_name is not None and not isinstance(expected_name, str)):
            reasons["invalid_provider_configuration"] += 1
            continue
        if provider_id not in providers:
            providers[provider_id] = provider_factory(
                provider_id=provider_id, host=host, port=port, password=password or "",
                noise_psk=noise_psk, expected_name=expected_name, expected_mac=expected_mac, enabled=True,
            )
        bindings[entity_id] = binding_factory(
            entity_id=entity_id, provider_id=provider_id, unique_id=unique_id, validation=dict(validation),
        )
    used_providers = {binding.provider_id for binding in bindings.values()}
    return Discovery(
        tuple(provider for provider_id, provider in providers.items() if provider_id in used_providers),
        tuple(bindings.values()), tuple(watched.values()), frozenset(known_entities), dict(reasons),
    )


class ESPHomeProviderAdapter:
    """HA discovery/lifecycle adapter for an owned, read-only native collector."""

    def __init__(
        self, hass: Any, collector: Any, *, registry: Any = None,
        provider_factory: Callable[..., Any] | None = None,
        binding_factory: Callable[..., Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[..., Any] | None = None,
    ) -> None:
        self._hass = hass
        self._collector = collector
        self._registry = registry
        self._provider_factory = provider_factory
        self._binding_factory = binding_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep or asyncio.sleep
        self._sources: dict[str, str] = {}
        self._checks: dict[str, Any] = {}
        self._selected_ids: set[str] = set()
        self._known_entities: set[str] = set()
        self._gated_after: dict[str, datetime] = {}
        self._pending_epoch: datetime | None = None
        self._identities: dict[str, tuple[str, str, str]] = {}
        self._entry_unsubs: dict[str, tuple[Any, list[Callable[[], None]]]] = {}
        self._original_unsubs: dict[str, tuple[Any, Callable[[], None]]] = {}
        self._registry_unsub: Callable[[], None] | None = None
        self._refresh_task: asyncio.Task | None = None
        self._health_task: asyncio.Task | None = None
        self._health_snapshot: tuple[Any, ...] = ()
        self._refresh_lock = asyncio.Lock()
        self._revision = 0
        self._applied_revision = -1
        self._closed = False
        self._provider_count = 0
        self._binding_count = 0
        self._reasons: dict[str, int] = {}

    def _eligible_entities(self) -> dict[str, dict[str, Any]]:
        return {self._sources[key]: validation for key, check in self._checks.items()
                if (validation := _validation(check)) is not None
                and isinstance(self._sources.get(key), str)
                and _ENTITY_ID.fullmatch(self._sources[key])}

    def _gate_known_entities(self) -> None:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("invalid_receipt_clock")
        self._pending_epoch = now
        for entity_id in self._known_entities.intersection(self._eligible_entities()):
            self._gated_after[entity_id] = now

    def _invalidate(self, reason: str) -> None:
        self._collector.invalidate_all(reason)

    def invalidate_all(self, reason: str = "binding_changed") -> None:
        """Quarantine synchronously before a queued coordinator reconfigure."""
        if not self._closed:
            self._gate_known_entities()
            self._revision += 1
            self._invalidate(reason)

    def _ensure_dependencies(self) -> None:
        if self._registry is None:
            from homeassistant.helpers import entity_registry
            self._registry = entity_registry.async_get(self._hass)
        if self._provider_factory is None or self._binding_factory is None:
            from .esphome_live import BindingRequest, ProviderConfig
            self._provider_factory = self._provider_factory or ProviderConfig
            self._binding_factory = self._binding_factory or BindingRequest

    async def async_configure(self, sources: Mapping[str, str], checks: Mapping[str, Mapping[str, Any]]) -> None:
        """Apply the coordinator's actual source mapping and unchanged validators."""
        if self._closed:
            return
        copied_sources = dict(sources)
        copied_checks = {key: dict(value) if isinstance(value, Mapping) else value for key, value in checks.items()}
        if (self._applied_revision >= 0 and self._applied_revision == self._revision
                and copied_sources == self._sources and copied_checks == self._checks):
            return
        previous_configuration = self._applied_revision >= 0
        self._sources = copied_sources
        self._checks = copied_checks
        self._selected_ids = {value for value in sources.values() if isinstance(value, str)}
        if previous_configuration:
            self._gate_known_entities()
        self._revision += 1
        self._invalidate("binding_changed")
        self._ensure_dependencies()
        if self._registry_unsub is None:
            self._registry_unsub = self._hass.bus.async_listen(
                _EVENT_ENTITY_REGISTRY_UPDATED, self._on_registry_changed,
            )
        await self._async_refresh()

    def _on_registry_changed(self, event: Any) -> None:
        data = getattr(event, "data", {})
        changes = data.get("changes", {})
        previous_id = changes.get("entity_id") if isinstance(changes, Mapping) else None
        if data.get("entity_id") in self._selected_ids or previous_id in self._selected_ids:
            self._queue_refresh()

    def _queue_refresh(self) -> None:
        if self._closed:
            return
        self._revision += 1
        self._gate_known_entities()
        # This must quarantine the old collector generation synchronously.
        self._invalidate("provider_changed")
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = self._hass.async_create_task(self._async_refresh())

    async def _on_entry_updated(self, _hass: Any, _entry: Any) -> None:
        self._queue_refresh()

    @staticmethod
    def _unsubscribe(callbacks: list[Callable[[], None]]) -> None:
        for unsubscribe in callbacks:
            try:
                unsubscribe()
            except ValueError:
                # A provider unload may already have removed its listener.
                pass

    def _watch_entries(self, entries: tuple[Any, ...]) -> None:
        wanted = {entry.entry_id: entry for entry in entries}
        for entry_id, (entry, callbacks) in tuple(self._entry_unsubs.items()):
            if wanted.get(entry_id) is not entry:
                self._unsubscribe(callbacks)
                del self._entry_unsubs[entry_id]
        for entry_id, entry in wanted.items():
            if entry_id not in self._entry_unsubs:
                callbacks = [entry.async_on_state_change(self._queue_refresh),
                             entry.add_update_listener(self._on_entry_updated)]
                self._entry_unsubs[entry_id] = (entry, callbacks)
        original_clients = {entry_id: _original_client(entry) for entry_id, entry in wanted.items()}
        for entry_id, (client, unsubscribe) in tuple(self._original_unsubs.items()):
            if original_clients.get(entry_id) is not client:
                unsubscribe()
                del self._original_unsubs[entry_id]
        for entry_id, client in original_clients.items():
            if entry_id not in self._original_unsubs:
                subscribe = getattr(client, "add_connection_closed_callback", None)
                if callable(subscribe):
                    unsubscribe = subscribe(lambda _event: self._queue_refresh())
                    self._original_unsubs[entry_id] = (client, unsubscribe)
        self._health_snapshot = self._health_fingerprint()
        if wanted and (self._health_task is None or self._health_task.done()):
            # This lifetime monitor must not enter HA's foreground task set:
            # startup/async_block_till_done must never await its infinite loop.
            create_background = getattr(self._hass, "async_create_background_task", None)
            coroutine = self._async_monitor_original()
            self._health_task = (create_background(coroutine, "Deye EMS ESPHome connection monitor")
                if callable(create_background) else asyncio.create_task(
                    coroutine, name="Deye EMS ESPHome connection monitor"))

    def _health_fingerprint(self) -> tuple[Any, ...]:
        return tuple((entry_id, id(entry), id(_original_client(entry)), _loaded(entry),
                      _original_connected(entry), _mac(getattr(entry, "unique_id", None)))
                     for entry_id, (entry, _callbacks) in sorted(self._entry_unsubs.items()))

    def _check_original_health(self) -> None:
        """RAM-only lifecycle check; never polls the device or sends a ping."""
        current = self._health_fingerprint()
        if current != self._health_snapshot:
            self._health_snapshot = current
            self._queue_refresh()

    async def _async_monitor_original(self) -> None:
        while not self._closed:
            await self._sleep(5)
            if not self._closed:
                self._check_original_health()

    async def _async_refresh(self) -> None:
        async with self._refresh_lock:
            while not self._closed and self._applied_revision != self._revision:
                revision = self._revision
                discovery = discover_provider_bindings(
                    self._sources, self._checks,
                    registry_get=self._registry.async_get,
                    config_entry_get=self._hass.config_entries.async_get_entry,
                    provider_factory=self._provider_factory, binding_factory=self._binding_factory,
                )
                self._watch_entries(discovery.watched_entries)
                # Collector reconfiguration must replace/quarantine the previous
                # generation even when the lifecycle event coalesced to LOADED.
                await self._collector.async_configure(discovery.providers, discovery.bindings)
                self._provider_count = len(discovery.providers)
                self._binding_count = len(discovery.bindings)
                self._reasons = discovery.reasons
                eligible = set(self._eligible_entities())
                self._known_entities.intersection_update(eligible)
                self._known_entities.update(discovery.known_entities)
                self._gated_after = {key: value for key, value in self._gated_after.items() if key in eligible}
                if self._pending_epoch is not None:
                    for entity_id in discovery.known_entities:
                        self._gated_after[entity_id] = self._pending_epoch
                self._identities = {}
                for binding in discovery.bindings:
                    provider = self._hass.config_entries.async_get_entry(binding.provider_id)
                    self._identities[binding.entity_id] = (
                        binding.provider_id, binding.unique_id, _mac(getattr(provider, "unique_id", None)),
                    )
                self._applied_revision = revision

    def source_invalid(self, entity_id: str) -> bool:
        """Fail closed for known ESPHome provider loss, without affecting others.

        The registry/config entry checks are local dictionary reads. An event
        also quarantines previous HA reports until HA or the native collector
        supplies new evidence after that event; numeric lingering HA states are
        not evidence that a disabled provider is communicating.
        """
        validation = self._eligible_entities().get(entity_id)
        if validation is None:
            return False
        if self._closed:
            return entity_id in self._known_entities
        entry = self._registry.async_get(entity_id) if self._registry is not None else None
        if entry is None or getattr(entry, "entity_id", None) != entity_id:
            return entity_id in self._known_entities
        if getattr(entry, "platform", None) != "esphome":
            return False
        if getattr(entry, "disabled_by", None) is not None:
            return True
        provider_id = getattr(entry, "config_entry_id", None)
        unique_id = getattr(entry, "unique_id", None)
        provider = self._hass.config_entries.async_get_entry(provider_id) if provider_id else None
        if (not isinstance(unique_id, str) or not unique_id or provider is None
                or getattr(provider, "domain", None) != "esphome"
                or getattr(provider, "entry_id", None) != provider_id
                or _mac(getattr(provider, "unique_id", None)) is None or not _loaded(provider)
                or not _original_connected(provider)):
            return True
        expected_identity = self._identities.get(entity_id)
        if expected_identity is not None and expected_identity != (provider_id, unique_id, _mac(provider.unique_id)):
            return True
        if self._applied_revision != self._revision:
            return True
        after = self._gated_after.get(entity_id)
        if after is None:
            return False
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            return True
        states = getattr(self._hass, "states", None)
        state = states.get(entity_id) if states is not None else None
        reported = getattr(state, "last_reported", None) or getattr(state, "last_updated", None)
        if isinstance(reported, datetime) and reported.tzinfo is not None and after < reported <= now:
            attributes = getattr(state, "attributes", {})
            try:
                raw_value = state.state
                value = float(raw_value) if not isinstance(raw_value, bool) else math.nan
            except (TypeError, ValueError, OverflowError):
                value = math.nan
            if (math.isfinite(value) and not attributes.get("restored", False)
                    and attributes.get("unit_of_measurement") == validation["unit"]
                    and (validation.get("low") is None or value >= validation["low"])
                    and (validation.get("high") is None or value <= validation["high"])
                    and (now - reported).total_seconds() <= validation["age"]):
                self._gated_after.pop(entity_id, None)
                return False
        proof = self._collector.effective_report(entity_id, state, now, validation)
        reported = proof.get("reported_at") if isinstance(proof, Mapping) else None
        confirmed = proof.get("confirmed_at") if isinstance(proof, Mapping) else None
        if (isinstance(reported, datetime) and reported.tzinfo is not None
                and isinstance(confirmed, datetime) and confirmed.tzinfo is not None
                and after < confirmed <= reported <= now
                and (now - confirmed).total_seconds() <= validation["age"]):
            self._gated_after.pop(entity_id, None)
            return False
        return True

    def effective_report(self, entity_id: str, ha_state: Any, now: Any, validation: Mapping[str, Any]) -> Any:
        """Read only already collected evidence; never connect from the hot path."""
        if self._closed or self._applied_revision != self._revision or self.source_invalid(entity_id):
            return None
        return self._collector.effective_report(entity_id, ha_state, now, validation)

    @property
    def status(self) -> dict[str, Any]:
        stream = getattr(self._collector, "status", {})
        if not isinstance(stream, Mapping):
            stream = {}
        def count(key: str) -> int:
            value = stream.get(key, 0)
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
        pending = not self._closed and self._applied_revision != self._revision
        status = stream.get("status")
        if status not in {"closed", "quarantined", "connected", "waiting", "not_configured"}:
            status = "not_configured"
        return {"status": "closed" if self._closed else "quarantined" if pending else status,
                "providers": self._provider_count, "connected_providers": count("connected_count"),
                "bindings": count("bound_entity_count"), "verified_sources": count("ready_entity_count"),
                "provider_count": self._provider_count, "binding_count": self._binding_count,
                "refresh_pending": pending, "closed": self._closed, "reasons": dict(self._reasons)}

    async def async_close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._invalidate("adapter_closed")
        if self._registry_unsub:
            self._registry_unsub()
            self._registry_unsub = None
        for _entry, callbacks in self._entry_unsubs.values():
            self._unsubscribe(callbacks)
        self._entry_unsubs.clear()
        for _client, unsubscribe in self._original_unsubs.values():
            unsubscribe()
        self._original_unsubs.clear()
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
        # An explicit async_configure call may be running in its caller's task,
        # independently of the queued lifecycle refresh task cancelled above.
        async with self._refresh_lock:
            await self._collector.async_close()
