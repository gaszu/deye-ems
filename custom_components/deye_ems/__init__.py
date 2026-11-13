"""Independent local EMS integration. Installing it does not transfer ownership."""
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP, Platform

from .appearance import AppearanceManager, DATA_APPEARANCE
from .const import DOMAIN, PLATFORMS, VERSION
from .coordinator import DeyeEMSCoordinator
from .post_save import cancel_post_save, get_post_save_manager
from .updates import UpdateManager, DATA_UPDATES
from .websocket import async_register

PANEL_PATH = "deye-ems"


async def async_setup_entry(hass, entry):
    activate_after_install = getattr(entry, "data", {}).get("activate_after_install") is True
    if activate_after_install:
        # One-shot user intent: consume before registering listeners or creating
        # the coordinator. A failed/interrupted installation stays in shadow.
        data = dict(entry.data)
        data.pop("activate_after_install")
        hass.config_entries.async_update_entry(entry, data=data)
    if DATA_UPDATES not in hass.data:
        # Release checks are app-wide and never run in the EMS refresh path.
        hass.data[DATA_UPDATES] = UpdateManager(hass)
    if DATA_APPEARANCE not in hass.data:
        appearance = AppearanceManager(hass)
        await appearance.async_load()
        hass.data[DATA_APPEARANCE] = appearance
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
        await async_update_panel(hass)
    await _async_enable_update_checks(hass)
    if activate_after_install:
        manager = get_post_save_manager(hass)
        ticket = manager.begin(entry, previous_runtime=None)
        manager.after_reload(ticket, True)


async def _async_enable_update_checks(hass):
    """Tie the independent checker to HA lifecycle, not the control driver."""
    manager = hass.data[DATA_UPDATES]
    if DOMAIN + "_updates_stop" not in hass.data:
        async def stop_updates(_event):
            await _async_disable_update_checks(hass)

        hass.data[DOMAIN + "_updates_stop"] = hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, stop_updates)
    if hass.is_running:
        manager.async_start()
    elif DOMAIN + "_updates_start" not in hass.data:
        async def start_updates(_event):
            hass.data.pop(DOMAIN + "_updates_start", None)
            manager.async_start()

        hass.data[DOMAIN + "_updates_start"] = hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, start_updates)


async def _async_disable_update_checks(hass):
    for suffix in ("_updates_start", "_updates_stop"):
        cancel = hass.data.pop(DOMAIN + suffix, None)
        if cancel is not None:
            cancel()
    if manager := hass.data.get(DATA_UPDATES):
        await manager.async_stop()


async def async_update_panel(hass):
    """Refresh navigation only; leave the coordinator and all actuators alone."""
    manager = hass.data[DATA_APPEARANCE]
    if hass.data.get(DOMAIN + "_panel"):
        frontend.async_remove_panel(hass, PANEL_PATH)
        hass.data.pop(DOMAIN + "_panel", None)
    await panel_custom.async_register_panel(hass,
        frontend_url_path=PANEL_PATH, webcomponent_name="deye-ems-panel-" + VERSION.replace(".", "-"),
        sidebar_title="Deye EMS" if getattr(manager, "sidebar_visible", True) else None,
        sidebar_icon="mdi:solar-power",
        module_url=f"/deye_ems_static/deye-ems-panel.js?v={VERSION}",
        require_admin=True, config_panel_domain=DOMAIN)
    hass.data[DOMAIN + "_panel"] = True


async def _async_options_changed(hass, entry):
    manager = get_post_save_manager(hass)
    ticket = manager.begin(entry)
    previous = getattr(entry, "runtime_data", None)
    if previous is not None and getattr(previous, "mode", None) == "active":
        try:
            # Internal guarded pause keeps the saved activation intent, but uses
            # normal GC OFF / 0 A commands and requires register readbacks before
            # relinquishing this coordinator. Service acceptance is insufficient.
            await previous.async_set_mode("shadow", activation_guard=lambda: manager.is_current(ticket))
        except Exception:
            manager.pause_failed(ticket)
            return
    if not manager.is_current(ticket):
        return
    # Keep the existing route present while this options reload exchanges
    # coordinators. Removing it even briefly makes HA navigate to its default
    # dashboard before the replacement coordinator can register the panel.
    # Count per entry: concurrent or nested saves must not release another
    # reload's navigation lease.
    panel_reloads = None
    if hass.data.get("deye_ems_panel"):
        panel_reloads = hass.data.setdefault(DOMAIN + "_panel_reloads", {})
        panel_reloads[entry.entry_id] = panel_reloads.get(entry.entry_id, 0) + 1
    success = False
    try:
        success = await hass.config_entries.async_reload(entry.entry_id)
    except BaseException:
        manager.after_reload(ticket, False)
        raise
    finally:
        if panel_reloads is not None:
            depth = panel_reloads.get(entry.entry_id, 1) - 1
            if depth > 0:
                panel_reloads[entry.entry_id] = depth
            else:
                panel_reloads.pop(entry.entry_id, None)
            if not panel_reloads:
                hass.data.pop(DOMAIN + "_panel_reloads", None)
            if success is not True:
                _async_remove_unused_panel(hass, check_loaded_entries=True)
    manager.after_reload(ticket, success)


def _async_remove_unused_panel(hass, *, check_loaded_entries=False, ignore_reload_entry=None):
    """Clean navigation only when no runtime or reload still needs its route."""
    pending = hass.data.get(DOMAIN + "_panel_reloads", {})
    if any(depth > 0 for entry_id, depth in pending.items()
           if entry_id != ignore_reload_entry):
        return
    coordinators = hass.data.get(DOMAIN, {})
    if check_loaded_entries:
        # A failed setup may already have inserted a partial runtime into
        # DOMAIN. It must not retain a panel as though setup had succeeded.
        for entry_id in coordinators:
            registered = hass.config_entries.async_get_entry(entry_id)
            state = getattr(registered, "state", None)
            if (registered is not None and not getattr(registered, "disabled_by", None)
                    and getattr(state, "value", state) == "loaded"):
                return
    elif coordinators:
        return
    if hass.data.pop(DOMAIN + "_panel", None):
        frontend.async_remove_panel(hass, PANEL_PATH)


async def async_remove_entry(hass, entry):
    cancel_post_save(hass, entry.entry_id, "configuration_changed")
    _async_remove_unused_panel(hass, ignore_reload_entry=entry.entry_id)


async def async_unload_entry(hass, entry):
    await hass.config_entries.async_unload_platforms_or_raise(entry, [Platform(p) for p in PLATFORMS])
    await entry.runtime_data.async_shutdown()
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if not hass.data.get(DOMAIN):
        await _async_disable_update_checks(hass)
        # Static paths and websocket handlers are registered once per HA process.
        _async_remove_unused_panel(hass, ignore_reload_entry=(
            entry.entry_id if getattr(entry, "disabled_by", None) else None))

