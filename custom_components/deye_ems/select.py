"""Explicit operating mode; creation and installation start in observation mode."""
from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from .entity import DeyeEMSEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([DeyeEMSMode(entry.runtime_data, entry, "mode", "Tryb pracy")])


class DeyeEMSMode(DeyeEMSEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = ["Obserwacja", "Sterowanie"]

    @property
    def current_option(self):
        return "Sterowanie" if self.coordinator.mode == "active" else "Obserwacja"

    async def async_select_option(self, option):
        await self.coordinator.async_set_mode({"Obserwacja": "shadow", "Sterowanie": "active"}[option])

