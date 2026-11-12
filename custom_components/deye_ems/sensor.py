"""Small diagnostic states. Full 48-hour rows are served over authenticated WS."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from .entity import DeyeEMSEntity
from .telemetry import build_entities

DESCRIPTIONS = (
    ("status", "Stan silnika", None),
    ("plan", "Jakość planu", None),
    ("night_soc", "Modelowy cel SoC noc", "%"),
    ("peak_soc", "Modelowy cel SoC popołudnie", "%"),
    ("selected_soc", "Wybrany cel SoC", "%"),
    ("charge_cap", "Dostępny prąd ładowania", "A"),
    ("deye_grid_charge_limit", "Automatyczny limit ładowania z sieci", "A"),
    ("charge_request", "Żądany prąd ładowania", "A"),
    ("decision_reason", "Przyczyna regulacji", None),
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([DeyeEMSSensor(entry.runtime_data, entry, *d) for d in DESCRIPTIONS]
        + build_entities(entry.runtime_data, entry))


class DeyeEMSSensor(DeyeEMSEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, key, name, unit):
        super().__init__(coordinator, entry, key, name)
        self.key = key
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = "mdi:solar-power"

    @property
    def available(self):
        return super().available and (self.key != "deye_grid_charge_limit" or
                                      self.snapshot.get("inputs", {}).get("grid_charge_limit_valid") is True)

    @property
    def native_value(self):
        plan, control = self.snapshot.get("plan", {}), self.snapshot.get("control", {})
        if self.key == "status":
            return self.snapshot.get("status", "starting")
        if self.key == "plan":
            return plan.get("status", "waiting")
        if self.key in ("night_soc", "peak_soc"):
            return plan.get("targets", {}).get("night" if self.key == "night_soc" else "peak", {}).get("soc_percent")
        if self.key == "charge_cap":
            return control.get("cap_a")
        if self.key == "deye_grid_charge_limit":
            inputs = self.snapshot.get("inputs", {})
            return inputs.get("deye_grid_charge_limit_a") if inputs.get("grid_charge_limit_valid") else None
        if self.key == "selected_soc":
            return control.get("target_soc")
        if self.key == "charge_request":
            return control.get("next_a")
        return control.get("reason", self.snapshot.get("reason", "waiting"))

    @property
    def extra_state_attributes(self):
        if self.key == "deye_grid_charge_limit":
            inputs = self.snapshot.get("inputs", {})
            return {"deye_max_charge_current_a": inputs.get("deye_max_charge_current_a"),
                    "fraction": 0.95, "source_entity": self.coordinator.options.get("sources", {}).get("max_charge_current_number")}
        if self.key == "plan":
            p = self.snapshot.get("plan", {})
            return {key: p[key] for key in ("generated_at", "quality", "reason", "source", "season", "targets") if key in p}
        if self.key == "status":
            return {"mode": self.coordinator.mode, "execution_confirmed": False}
        return None

