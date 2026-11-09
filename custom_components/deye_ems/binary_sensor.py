"""Expose planning and ownership constraints without hiding their cause."""
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import EntityCategory
from .entity import DeyeEMSEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([DeyeEMSBinary(entry.runtime_data, entry, key, name)
        for key, name in (("unreachable", "Cel może być nieosiągalny"),
            ("telemetry", "Dane regulacji poprawne"))])


class DeyeEMSBinary(DeyeEMSEntity, BinarySensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, key, name):
        super().__init__(coordinator, entry, key, name)
        self.key = key

    @property
    def is_on(self):
        control = self.snapshot.get("control", {})
        if self.key == "telemetry":
            return control.get("telemetry_ok", False)
        return bool(self.snapshot.get("plan", {}).get("unreachable") or control.get("unreachable"))

