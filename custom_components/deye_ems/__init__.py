"""Independent local EMS integration. Installing it does not transfer ownership."""
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform

from .const import DOMAIN, PLATFORMS, VERSION
from .coordinator import DeyeEMSCoordinator
from .websocket import async_register

PANEL_PATH = "deye-ems"


async def async_setup_entry(hass, entry):
    coordinator = DeyeEMSCoordinator(hass, entry)
    await coordinator.async_initialize()
    entry.runtime_data = coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, [Platform(p) for p in PLATFORMS])
    entry.async_on_unload(entry.add_update_listener(_async_options_changed))
    if not hass.data.get(DOMAIN + "_static"):
        await hass.http.async_register_static_paths([StaticPathConfig(
            "/deye_ems_static", str(Path(__file__).parent / "frontend"), False)])
        async_register(hass)
        hass.data[DOMAIN + "_static"] = True
    if not hass.data.get(DOMAIN + "_panel"):
        await panel_custom.async_register_panel(hass,
            frontend_url_path=PANEL_PATH, webcomponent_name="deye-ems-panel",
            sidebar_title="Deye EMS", sidebar_icon="mdi:solar-power",
            module_url=f"/deye_ems_static/deye-ems-panel.js?v={VERSION}",
            require_admin=True, config_panel_domain=DOMAIN)
        hass.data[DOMAIN + "_panel"] = True


async def _async_options_changed(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    await hass.config_entries.async_unload_platforms_or_raise(entry, [Platform(p) for p in PLATFORMS])
    await entry.runtime_data.async_shutdown()
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if not hass.data.get(DOMAIN):
        frontend.async_remove_panel(hass, PANEL_PATH)
        # Static paths and websocket handlers are registered once per HA process.
        hass.data.pop(DOMAIN + "_panel", None)

