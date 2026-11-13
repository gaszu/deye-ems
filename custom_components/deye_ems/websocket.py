"""Authenticated admin API for the bundled panel; no generic service proxy."""
import probatio as vol
from homeassistant.components import websocket_api
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from .appearance import DATA_APPEARANCE
from .const import DOMAIN, DEFAULT_OPTIONS, DEFAULT_SOURCES, VERSION
from .updates import DATA_UPDATES
from .tariff_calendar import calendar_operators, calendar_profiles
from .post_save import post_save_status, cancel_all_post_save


def _coordinator(hass):
    entries = hass.data.get(DOMAIN, {})
    return next(iter(entries.values())) if entries else None


def _payload(coordinator, appearance=None, updates=None):
    options = coordinator.options
    hass = getattr(coordinator, "hass", None)
    completion = post_save_status(hass, coordinator.entry.entry_id) if hass is not None else {
        "status": "idle", "reason": None, "issues": [], "updated_at": None,
        "plan_source": None, "plan_reason": None}
    return {"entry_id": coordinator.entry.entry_id, "mode": coordinator.mode, "data": coordinator.data or {},
        "backend_version": VERSION,
        "post_save_activation": completion,
        "updates": updates.status if updates is not None else {
            "status": "not_checked", "latest_version": None, "checked_at": None,
            "retry_at": None, "reason": None, "release_url": None, "marketplace_url": "/marketplace", "stale": False},
        "appearance": appearance.appearance if appearance is not None else {"theme": ""},
        "effective_loads": coordinator.effective_loads, "loads_revision": coordinator.loads_revision,
        "options": {**{k: options.get(k, v) for k, v in DEFAULT_OPTIONS.items()},
                    **{k: options.get(k) for k in (
                        "min_soc_lower_bound", "min_soc_bound_valid", "effective_min_soc_percent",
                        "hardware_profile", "effective_hardware_limits", "tariff_calendar", "physical_tou")}},
        "sources": {**DEFAULT_SOURCES, **options.get("sources", {})}}


@websocket_api.websocket_command({vol.Required("type"): "deye_ems/status"})
@websocket_api.require_admin
@websocket_api.async_response
async def status(hass, connection, msg):
    coordinator = _coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Deye EMS is not loaded")
        return
    connection.send_result(msg["id"], _payload(coordinator, hass.data.get(DATA_APPEARANCE), hass.data.get(DATA_UPDATES)))


@websocket_api.websocket_command({vol.Required("type"): "deye_ems/tariff_catalog"})
@websocket_api.require_admin
@websocket_api.async_response
async def tariff_catalog(hass, connection, msg):
    """Embedded public rules only; no source, device, history or network calls."""
    connection.send_result(msg["id"], {"backend_version": VERSION,
        "operators": calendar_operators(), "profiles": calendar_profiles()})


@websocket_api.websocket_command({vol.Required("type"): "deye_ems/command",
    vol.Required("command"): vol.In(("recalculate", "mode", "option", "load_save", "load_delete", "load_toggle", "appearance", "check_updates")),
    vol.Optional("theme"): str,
    vol.Optional("mode"): vol.In(("shadow", "active")),
    vol.Optional("original_energy_entity"): str, vol.Optional("channel"): dict,
    vol.Optional("expected_loads_revision"): str,
    vol.Optional("enabled"): bool,
    vol.Optional("key"): str, vol.Optional("value"): vol.Any(float, int, str)})
@websocket_api.require_admin
@websocket_api.async_response
async def command(hass, connection, msg):
    if msg["command"] == "mode" and msg.get("mode") == "shadow":
        # Revoke waiting activation even while the config entry is reloading.
        cancel_all_post_save(hass)
    coordinator = _coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Deye EMS is not loaded")
        return
    try:
        if msg["command"] == "check_updates":
            updates = hass.data.get(DATA_UPDATES)
            if updates is None:
                raise ValueError("Sprawdzanie aktualizacji nie jest jeszcze dostępne. Odśwież panel.")
            try:
                await updates.async_check()
            except Exception:
                # Unexpected failures must not echo HTTP bodies or credentials.
                connection.send_error(msg["id"], "update_check_failed", "Nie udało się sprawdzić aktualizacji.")
                return
        elif msg["command"] == "appearance":
            appearance = hass.data.get(DATA_APPEARANCE)
            if appearance is None:
                raise ValueError("Wygląd panelu nie jest jeszcze dostępny. Odśwież panel.")
            await appearance.async_set_theme(msg.get("theme"))
        elif msg["command"] == "recalculate":
            await coordinator.async_recalculate()
        elif msg["command"] == "mode":
            await coordinator.async_set_mode(msg["mode"])
        elif msg["command"] == "load_save":
            await coordinator.async_save_load(msg.get("original_energy_entity", ""), msg.get("channel"),
                expected_revision=msg.get("expected_loads_revision"))
        elif msg["command"] == "load_delete":
            await coordinator.async_delete_load(msg.get("original_energy_entity", ""),
                expected_revision=msg.get("expected_loads_revision"))
        elif msg["command"] == "load_toggle":
            await coordinator.async_toggle_load(msg.get("original_energy_entity", ""), msg.get("enabled"),
                expected_revision=msg.get("expected_loads_revision"))
        else:
            await coordinator.async_set_option(msg["key"], msg["value"])
    except (ValueError, KeyError, HomeAssistantError) as err:
        connection.send_error(msg["id"], "invalid_request", str(err))
        return
    connection.send_result(msg["id"], _payload(coordinator, hass.data.get(DATA_APPEARANCE), hass.data.get(DATA_UPDATES)))


@callback
def async_register(hass):
    websocket_api.async_register_command(hass, status)
    websocket_api.async_register_command(hass, command)
    websocket_api.async_register_command(hass, tariff_catalog)

