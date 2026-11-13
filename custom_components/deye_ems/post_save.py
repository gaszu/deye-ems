"""Bounded activation after a committed user save; no control-guard bypass.

Jobs survive coordinator reloads but not HA shutdown. Cancellation invalidates
the ticket synchronously; it never cancels an in-progress durable mode write.
Only the coordinator's public preparation and guarded activation APIs can grant
control. Status contains controlled codes, never settings, keys or exceptions.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import time


DATA_POST_SAVE = "deye_ems_post_save"
_STATUSES = frozenset(("idle", "waiting", "checking", "active", "blocked", "cancelled"))
_REASONS = frozenset(("waiting_for_reload", "waiting_for_measurements", "waiting_for_plan",
    "activation_conditions_failed", "activation_cancelled", "configuration_changed",
    "configuration_reload_failed", "configuration_pause_failed", "activation_failed", "activation_completed"))
_SOURCES = frozenset(("soc", "voltage", "battery_power", "bms_charge_current",
    "bms_blocking_charge", "battery_alarm", "battery_fault", "battery_low_soc",
    "max_charge_current_number", "grid_current_number", "charge_power", "hardware",
    "topology", "grid_power", "load_power", "ct_grid_power", "grid_setting", "tariff",
    *(f"{kind}_l{i}_power" for kind in ("grid", "load", "ct_grid") for i in (1, 2, 3))))
_ISSUE_REASONS = frozenset(("missing", "restored", "invalid", "future", "wrong_unit",
    "alias", "stale", "time_skew", "invalid_or_unsupported", "provider_unavailable"))
_PLAN_SOURCES = frozenset(("own_deterministic_planner", "own_conservative_fallback"))
_PLAN_REASONS = frozenset(("planned", "unreachable", "forecast_energy_or_power_deficit",
    "incomplete_48h_forecast", "invalid_forecast_row", "stale_or_discontinuous_forecast_axis",
    "invalid_aware_timestamp", "invalid_pv_p10_kw", "invalid_pv_p50_kw", "invalid_load_kw",
    "pv_p10_exceeds_p50", "forecast_capacity_mismatch", "forecast_missing_protected_window",
    "missing_next_night_or_peak_deadline"))
_UNSET = object()


def _issues(values):
    result = []
    if isinstance(values, list):
        for value in values[:64]:
            if (isinstance(value, dict) and isinstance(value.get("source"), str)
                    and value["source"] in _SOURCES and isinstance(value.get("reason"), str)
                    and value["reason"] in _ISSUE_REASONS):
                result.append({"source": value["source"], "reason": value["reason"]})
    return result


def _fingerprint(entry):
    try:
        encoded = json.dumps({"data": dict(getattr(entry, "data", {})),
                              "options": dict(getattr(entry, "options", {}))},
                             sort_keys=True, ensure_ascii=True, allow_nan=False,
                             separators=(",", ":")).encode()
        return hashlib.sha256(encoded).digest()
    except (ValueError, TypeError, OverflowError):
        return None


class _Ticket:
    def __init__(self, entry, previous_runtime):
        self.entry_id = entry.entry_id
        self.fingerprint = _fingerprint(entry)
        self.previous_runtime = previous_runtime
        self.cancelled = False
        self.task = None
        self.status = {"status": "waiting", "reason": "waiting_for_reload", "issues": [], "updated_at": None}


class PostSaveActivationManager:
    """One current activation intent per entry; no settings or secrets in status."""
    def __init__(self, hass, *, monotonic=None, utcnow=None, sleep=None,
                 timeout_seconds=180, interval_seconds=5):
        self.hass = hass
        self._monotonic = monotonic or time.monotonic
        self._utcnow = utcnow or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep or asyncio.sleep
        self._timeout = timeout_seconds
        self._interval = interval_seconds
        self._tickets = {}
        self._tasks = set()
        self._closed = False
        self._stop_unsubscribe = None

    def begin(self, entry, *, previous_runtime=_UNSET):
        """Create intent before reload; newer saves immediately revoke old ones."""
        self.cancel(entry.entry_id, "configuration_changed")
        previous = getattr(entry, "runtime_data", None) if previous_runtime is _UNSET else previous_runtime
        ticket = _Ticket(entry, previous)
        self._tickets[entry.entry_id] = ticket
        if self._closed:
            ticket.cancelled = True
            self._status(ticket, "cancelled", "activation_cancelled")
        else:
            self._status(ticket, "waiting", "waiting_for_reload")
        return ticket

    def after_reload(self, ticket, success):
        """Schedule only after setup completed; never keep the browser waiting."""
        if not self._current(ticket):
            return
        if success is not True:
            self._status(ticket, "blocked", "configuration_reload_failed")
            return
        if ticket.task is not None:
            return
        coroutine = self._run(ticket)
        factory = getattr(self.hass, "async_create_background_task", None)
        task = (factory(coroutine, "Deye EMS activation after save") if factory
                else asyncio.create_task(coroutine, name="Deye EMS activation after save"))
        ticket.task = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def get_status(self, entry_id):
        ticket = self._tickets.get(entry_id)
        return deepcopy(ticket.status) if ticket else {
            "status": "idle", "reason": None, "issues": [], "updated_at": None,
            "plan_source": None, "plan_reason": None}

    def cancel(self, entry_id, reason="manual_stop"):
        ticket = self._tickets.get(entry_id)
        if ticket is None:
            return
        ticket.cancelled = True
        self._status(ticket, "cancelled", "configuration_changed" if reason == "configuration_changed"
                     else "activation_cancelled")

    def cancel_all(self, reason="manual_stop"):
        """Revoke intents even while the coordinator mapping is empty on reload."""
        for entry_id in tuple(self._tickets):
            self.cancel(entry_id, reason)

    def is_current(self, ticket):
        """Settings fence usable before reload, while the old runtime still owns hardware."""
        if not self._current(ticket):
            return False
        entry = self._entry(ticket)
        return (entry is not None and not getattr(entry, "disabled_by", None)
                and ticket.fingerprint is not None and _fingerprint(entry) == ticket.fingerprint)

    def pause_failed(self, ticket):
        """Do not unload an owner whose GC OFF / 0 A readback is unconfirmed."""
        if self._current(ticket):
            ticket.cancelled = True
            self._status(ticket, "blocked", "configuration_pause_failed")

    def requires_reload(self, entry_id, coordinator):
        """An old runtime cannot resume using settings superseded by a save.

        This fence deliberately survives cancellation and a failed pause. Only
        a genuinely new runtime clears it; an initial-install ticket explicitly
        has no previous runtime and therefore does not fence its new coordinator.
        """
        ticket = self._tickets.get(entry_id)
        return bool(ticket is not None and coordinator is not None
                    and ticket.previous_runtime is coordinator)

    def _status(self, ticket, status, reason=None, issues=None, *, plan_source=None, plan_reason=None):
        if self._tickets.get(ticket.entry_id) is not ticket:
            return
        ticket.status = {"status": status if status in _STATUSES else "blocked",
                         "reason": reason if reason in _REASONS else None,
                         "issues": _issues(issues), "updated_at": self._utcnow().isoformat(),
                         "plan_source": plan_source if isinstance(plan_source, str) and plan_source in _PLAN_SOURCES else None,
                         "plan_reason": plan_reason if isinstance(plan_source, str) and plan_source in _PLAN_SOURCES
                         and isinstance(plan_reason, str) and plan_reason in _PLAN_REASONS else None}

    def _entry(self, ticket):
        return self.hass.config_entries.async_get_entry(ticket.entry_id)

    def _current(self, ticket):
        return (not self._closed and not ticket.cancelled
                and self._tickets.get(ticket.entry_id) is ticket)

    def _guard(self, ticket, coordinator):
        if not self._current(ticket):
            return False
        entry = self._entry(ticket)
        return (entry is not None and not getattr(entry, "disabled_by", None)
                and getattr(getattr(entry, "state", None), "value", getattr(entry, "state", None)) == "loaded"
                and ticket.fingerprint is not None and _fingerprint(entry) == ticket.fingerprint
                and coordinator is not None
                and getattr(entry, "runtime_data", None) is coordinator
                and coordinator is not ticket.previous_runtime)

    async def _run(self, ticket):
        deadline, recalculated = self._monotonic() + self._timeout, False
        last_reason, last_issues = "waiting_for_reload", []
        try:
            while self._current(ticket) and self._monotonic() < deadline:
                entry = self._entry(ticket)
                if (entry is None or getattr(entry, "disabled_by", None)
                        or ticket.fingerprint is None or _fingerprint(entry) != ticket.fingerprint):
                    self.cancel(ticket.entry_id, "configuration_changed")
                    return
                coordinator = getattr(entry, "runtime_data", None)
                if not self._guard(ticket, coordinator):
                    last_reason = "waiting_for_reload"
                    self._status(ticket, "waiting", last_reason)
                    await self._sleep(self._interval)
                    continue
                self._status(ticket, "checking", last_reason, last_issues)
                try:
                    verdict = await coordinator.async_prepare_activation(recalculate=not recalculated)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    if self._current(ticket):
                        self._status(ticket, "blocked", "activation_conditions_failed")
                    return
                if not self._guard(ticket, coordinator):
                    if self._current(ticket):
                        self.cancel(ticket.entry_id, "configuration_changed")
                    return
                if self._monotonic() >= deadline:
                    break
                if not isinstance(verdict, dict):
                    self._status(ticket, "blocked", "activation_conditions_failed")
                    return
                recalculated = recalculated or verdict.get("recalculated") is True
                last_issues = _issues(verdict.get("issues"))
                if verdict.get("ready") is True:
                    try:
                        await coordinator.async_set_mode("active", activation_guard=lambda: self._guard(ticket, coordinator))
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        if self._current(ticket):
                            self._status(ticket, "blocked", "activation_failed", last_issues)
                        return
                    if self._guard(ticket, coordinator):
                        if getattr(coordinator, "mode", None) == "active":
                            self._status(ticket, "active", "activation_completed",
                                         plan_source=verdict.get("plan_source"), plan_reason=verdict.get("plan_reason"))
                        else:
                            self._status(ticket, "blocked", "activation_failed")
                    elif self._current(ticket):
                        self.cancel(ticket.entry_id, "configuration_changed")
                    return
                last_reason = verdict.get("reason")
                if last_reason not in ("waiting_for_measurements", "waiting_for_plan"):
                    self._status(ticket, "blocked", "activation_conditions_failed", last_issues)
                    return
                self._status(ticket, "waiting", last_reason, last_issues)
                await self._sleep(self._interval)
            if self._current(ticket):
                self._status(ticket, "blocked", last_reason, last_issues)
        except asyncio.CancelledError:
            # Host task cancellation is not an instruction to resume later.
            if self._tickets.get(ticket.entry_id) is ticket:
                self.cancel(ticket.entry_id)
            raise
        except Exception:
            if self._current(ticket):
                self._status(ticket, "blocked", "activation_failed")

    async def async_close(self):
        self._closed = True
        self.cancel_all()
        # Do not cancel a task that may be inside the coordinator's durable save.
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        if self._stop_unsubscribe:
            self._stop_unsubscribe()
            self._stop_unsubscribe = None


def get_post_save_manager(hass):
    manager = hass.data.get(DATA_POST_SAVE)
    if manager is None:
        manager = PostSaveActivationManager(hass)
        hass.data[DATA_POST_SAVE] = manager
        bus = getattr(hass, "bus", None)
        if bus is not None:
            async def stop(_event):
                await manager.async_close()
            manager._stop_unsubscribe = bus.async_listen_once("homeassistant_stop", stop)
    return manager


def get_post_save_status(hass, entry_id):
    manager = hass.data.get(DATA_POST_SAVE)
    return manager.get_status(entry_id) if manager else {
        "status": "idle", "reason": None, "issues": [], "updated_at": None,
        "plan_source": None, "plan_reason": None}


post_save_status = get_post_save_status


def cancel_post_save(hass, entry_id, reason="manual_stop"):
    """Synchronous ticket invalidation, also used by manual HA mode controls."""
    if manager := hass.data.get(DATA_POST_SAVE):
        manager.cancel(entry_id, reason)


def cancel_all_post_save(hass, reason="manual_stop"):
    """Manual STOP remains effective during an entry's unload/setup interval."""
    if manager := hass.data.get(DATA_POST_SAVE):
        manager.cancel_all(reason)


def configuration_requires_reload(hass, entry_id, coordinator):
    """Read-only stale-runtime fence for the ordinary activation preflight."""
    manager = getattr(hass, "data", {}).get(DATA_POST_SAVE)
    return manager.requires_reload(entry_id, coordinator) if manager else False
