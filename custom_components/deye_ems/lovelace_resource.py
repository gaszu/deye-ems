"""Keep the optional dashboard card on the installed EMS release."""

import re

from .const import PANEL_MODULE_PATH, PANEL_MODULE_URL

_EMS_RESOURCE = re.compile(rf"{re.escape(PANEL_MODULE_PATH)}(?:\?v=\d+\.\d+\.\d+)?")


async def async_refresh_panel_resource(resources):
    """Update matching storage entries in place, preserving IDs and dashboards."""
    # HA loads the storage collection lazily. Use its public collection methods
    # so the resource list and persisted data see the same change.
    await resources.async_get_info()
    for resource in resources.async_items():
        url = resource["url"]
        if (resource["type"] == "module" and url != PANEL_MODULE_URL
                and _EMS_RESOURCE.fullmatch(url)):
            await resources.async_update_item(resource["id"], {"url": PANEL_MODULE_URL})
