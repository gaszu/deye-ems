"""Diagnostics contain configuration and decisions, never external credentials."""
from homeassistant.components.diagnostics import async_redact_data


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return async_redact_data({
        "version": 1, "mode": coordinator.mode,
        "options": dict(coordinator.options), "data": coordinator.data,
    }, {"token", "password", "api_key", "authorization", "access_token"})

