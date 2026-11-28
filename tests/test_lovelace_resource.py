"""Test the existing Lovelace resource migration without a live dashboard."""

import re
import unittest

from test_installable import C, load

PANEL_MODULE_URL = C["PANEL_MODULE_URL"]
async_refresh_panel_resource = load("lovelace_resource.py", {**C, "re": re})["async_refresh_panel_resource"]


class ResourceCollection:
    def __init__(self, rows):
        self.rows = rows
        self.loaded = False
        self.updates = []

    async def async_get_info(self):
        self.loaded = True

    def async_items(self):
        assert self.loaded
        return self.rows

    async def async_update_item(self, item_id, changes):
        row = next(row for row in self.rows if row["id"] == item_id)
        row.update(changes)
        self.updates.append(item_id)


class LovelaceResourceTest(unittest.IsolatedAsyncioTestCase):
    async def test_updates_only_existing_local_ems_modules_in_place(self):
        path = PANEL_MODULE_URL.split("?")[0]
        rows = [{"id": str(i), "type": kind, "url": url} for i, (kind, url) in enumerate((
            ("module", path + "?v=2.7.2"), ("module", path),
            ("module", PANEL_MODULE_URL), ("module", "https://example.com" + path),
            ("module", path + "?other=1"), ("css", path),
        ))]
        resources = ResourceCollection(rows)
        await async_refresh_panel_resource(resources)
        await async_refresh_panel_resource(resources)
        self.assertEqual(resources.updates, ["0", "1"])
        self.assertEqual([row["url"] for row in rows[:3]], [PANEL_MODULE_URL] * 3)

    async def test_no_resource_is_created(self):
        resources = ResourceCollection([])
        await async_refresh_panel_resource(resources)
        self.assertEqual(resources.rows, [])
