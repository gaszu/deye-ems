"""Persistent, UI-editable engine parameters, including a fixed safety SoC."""
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from .const import DEFAULT_OPTIONS, OPTION_LABELS, OPTION_RANGES
from .entity import DeyeEMSEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([DeyeEMSNumber(entry.runtime_data, entry, key) for key in OPTION_RANGES])


class DeyeEMSNumber(DeyeEMSEntity, NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, entry, key):
        super().__init__(coordinator, entry, key, OPTION_LABELS[key])
        self.key = key
        low, high, step, unit = OPTION_RANGES[key]
        self._attr_native_min_value, self._attr_native_max_value = low, high
        self._attr_native_step, self._attr_native_unit_of_measurement = step, unit

    @property
    def native_value(self):
        return self.coordinator.options.get(self.key, DEFAULT_OPTIONS[self.key])

    async def async_set_native_value(self, value):
        await self.coordinator.async_set_option(self.key, value)

