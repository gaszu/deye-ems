"""Shared entities; no device setting is written from a property getter."""
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, VERSION


class DeyeEMSEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key, name):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name="Deye EMS",
            manufacturer="Deye EMS community", model="Local energy management",
            sw_version=VERSION)

    @property
    def snapshot(self):
        return self.coordinator.data or {}

