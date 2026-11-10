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
    return {"mode": coordinator.mode, "data": coordinator.data or {},
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
    vol.Required("command"): vol.In(("recalculate", "mode", "option")),
    vol.Optional("mode"): vol.In(("shadow", "active")),
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

