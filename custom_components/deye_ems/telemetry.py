"""Native integration telemetry: no helper or external EMS entity is required."""
from datetime import datetime, timezone

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory

from .entity import DeyeEMSEntity

METRICS = [
    ("soc", "Stan akumulatora", "%", "battery"),
    ("voltage", "Napięcie akumulatora", "V", "voltage"),
    ("grid_power", "Moc sieci", "W", "power"),
    ("load_power", "Moc domu", "W", "power"),
    ("battery_power", "Moc akumulatora", "W", "power"),
]
for phase in range(1, 4):
    METRICS.extend([
        (f"grid_l{phase}_power", f"Moc sieci L{phase}", "W", "power"),
        (f"load_l{phase}_power", f"Moc domu L{phase}", "W", "power"),
    ])


def build_entities(coordinator, entry):
    result = [TelemetrySensor(coordinator, entry, *m) for m in METRICS]
    result += [SlotEnergySensor(coordinator, entry, key, name)
        for key, name in (
            ("grid_import_kwh", "Import w bieżącym slocie"),
            ("battery_charge_kwh", "Ładowanie w bieżącym slocie"),
            ("battery_discharge_kwh", "Rozładowanie w bieżącym slocie"))]
    # The coordinator owns legacy migration and explicit-list semantics. Its
    # effective list includes the old pump only until the user manages loads;
    # an intentionally empty list must never recreate that channel here.
    for channel in coordinator.effective_loads:
        if channel.get("enabled", True) is not True:
            continue
        result.append(ExtraLoadSensor(coordinator, entry, channel, False))
        if channel.get("power_entity"):
            result.append(ExtraLoadSensor(coordinator, entry, channel, True))
    return result


class TelemetrySensor(DeyeEMSEntity, SensorEntity):
    def __init__(self, coordinator, entry, key, name, unit, device_class):
        super().__init__(coordinator, entry, "measurement_" + key, name)
        self.key = key
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = "measurement"

    @property
    def native_value(self):
        try:
            at = datetime.fromisoformat(self.snapshot.get("updated_at", ""))
            age = datetime.now(timezone.utc).timestamp() - at.timestamp()
            if not 0 <= age <= 30:
                return None
        except ValueError:
            return None
        inputs = self.snapshot.get("inputs", {})
        if self.key == "soc" and not inputs.get("soc_valid"):
            return None
        return inputs.get(self.key)


class SlotEnergySensor(DeyeEMSEntity, SensorEntity):
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = "energy"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, key, name):
        super().__init__(coordinator, entry, "slot_" + key, name)
        self.key = key

    @property
    def slot(self):
        meter = self.snapshot.get("slot_measurements", {})
        return meter.get("slots", {}).get(meter.get("current_slot"), {})

    @property
    def native_value(self):
        return self.slot.get(self.key)

    @property
    def extra_state_attributes(self):
        row = self.slot
        return {key: row[key] for key in ("slot", "start", "end", "seconds_valid",
            "seconds_missing", "complete") if key in row}


class ExtraLoadSensor(DeyeEMSEntity, SensorEntity):
    def __init__(self, coordinator, entry, channel, power):
        key = channel.get("id", channel["energy_entity"])
        super().__init__(coordinator, entry, f"load_{key}_{power}",
            channel.get("name", channel["energy_entity"]) + (" moc" if power else " energia"))
        self.channel = channel
        self.power = power
        self._attr_device_class = "power" if power else "energy"
        self._attr_native_unit_of_measurement = "W" if power else "kWh"
        if power:
            self._attr_state_class = "measurement"

    @property
    def native_value(self):
        # Keep measurement validation centralized in the runtime.
        key = "power_entity" if self.power else "energy_entity"
        entity = self.channel.get(key)
        state = self.hass.states.get(entity) if entity else None
        if state is None or state.attributes.get("restored"):
            return None
        from math import isfinite
        try:
            value = float(state.state)
            if not isfinite(value) or value < 0:
                return None
            stamp = getattr(state, "last_reported", None) or state.last_updated
            age = datetime.now(timezone.utc).timestamp() - stamp.timestamp()
            if age < 0 or (self.power and age > 30):
                return None
            unit = state.attributes.get("unit_of_measurement")
            if self.power:
                return value * (1000 if unit == "kW" else 1) if unit in ("W", "kW") else None
            return value / (1000 if unit == "Wh" else 1) if unit in ("Wh", "kWh") else None
        except (ValueError, TypeError, AttributeError):
            return None

