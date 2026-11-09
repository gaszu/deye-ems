"""Recalculate without injecting a fake plan or bypassing ownership."""
from homeassistant.components.button import ButtonEntity
from .entity import DeyeEMSEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([DeyeEMSRecalculate(entry.runtime_data, entry, "recalculate", "Przelicz plan")])


class DeyeEMSRecalculate(DeyeEMSEntity, ButtonEntity):
    _attr_icon = "mdi:calculator"

    async def async_press(self):
        await self.coordinator.async_recalculate()

