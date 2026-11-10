"""Authenticated admin API for the bundled panel; no generic service proxy."""
import probatio as vol
from homeassistant.components import websocket_api
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from .const import DOMAIN, DEFAULT_OPTIONS, DEFAULT_SOURCES


def _coordinator(hass):
    entries = hass.data.get(DOMAIN, {})
    return next(iter(entries.values())) if entries else None


def _payload(coordinator):
    return {"entry_id": coordinator.entry.entry_id, "mode": coordinator.mode, "data": coordinator.data or {},
        "effective_loads": coordinator.effective_loads, "loads_revision": coordinator.loads_revision,
        "options": {k: coordinator.options.get(k, v) for k, v in DEFAULT_OPTIONS.items()},
        "sources": {**DEFAULT_SOURCES, **coordinator.options.get("sources", {})}}


@websocket_api.websocket_command({vol.Required("type"): "deye_ems/status"})
@websocket_api.require_admin
@websocket_api.async_response
async def status(hass, connection, msg):
    coordinator = _coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Deye EMS is not loaded")
        return
    connection.send_result(msg["id"], _payload(coordinator))


@websocket_api.websocket_command({vol.Required("type"): "deye_ems/command",
    vol.Required("command"): vol.In(("recalculate", "mode", "option", "load_save", "load_delete", "load_toggle")),
    vol.Optional("mode"): vol.In(("shadow", "active")),
    vol.Optional("original_energy_entity"): str, vol.Optional("channel"): dict,
    vol.Optional("expected_loads_revision"): str,
    vol.Optional("enabled"): bool,
    vol.Optional("key"): str, vol.Optional("value"): vol.Any(float, int)})
@websocket_api.require_admin
@websocket_api.async_response
async def command(hass, connection, msg):
    coordinator = _coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Deye EMS is not loaded")
        return
    try:
        if msg["command"] == "recalculate":
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
    connection.send_result(msg["id"], _payload(coordinator))


@callback
def async_register(hass):
    websocket_api.async_register_command(hass, status)
    websocket_api.async_register_command(hass, command)

