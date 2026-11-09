"""Configure a local EMS; setup never takes ownership of the inverter."""
from __future__ import annotations
from uuid import uuid4

import probatio as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import DEFAULT_OPTIONS, DEFAULT_SOURCES, DOMAIN, OPTION_RANGES


def _schema(values, keys):
    fields = {}
    for key in keys:
        low, high, step, unit = OPTION_RANGES[key]
        fields[vol.Required(key, default=values.get(key, DEFAULT_OPTIONS[key]))] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=low, max=high, step=step,
                mode=selector.NumberSelectorMode.BOX, unit_of_measurement=unit))
    return vol.Schema(fields)


def _errors(values):
    floor = values.get("min_soc_percent", 40)
    ceiling = values.get("grid_max_soc_percent", 95)
    margin = values.get("reserve_margin_soc_percent", 5)
    return {"base": "invalid_soc_limits"} if floor + margin > ceiling else {}


class DeyeEMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            errors = _errors(user_input)
            if not errors:
                await self.async_set_unique_id("deye_ems_local")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Deye EMS", data={
                    **DEFAULT_OPTIONS, **user_input, "sources": dict(DEFAULT_SOURCES)})
        return self.async_show_form(step_id="user", errors=errors, data_schema=_schema(
            user_input or DEFAULT_OPTIONS, ["min_soc_percent", "capacity_kwh",
                "grid_import_limit_kw", "grid_phase_limit_kw"]),
            description_placeholders={"mode": "shadow"})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return DeyeEMSOptionsFlow()


class DeyeEMSOptionsFlow(config_entries.OptionsFlow):
    def _mapping_locked(self):
        runtime = getattr(self.config_entry, "runtime_data", None)
        return runtime is not None and runtime.mode == "active"

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=["parameters", "sources", "add_load", "remove_load"])

    def _loads(self):
        return list(self.config_entry.options.get("extra_loads", self.config_entry.data.get("extra_loads", [])))

    async def async_step_add_load(self, user_input=None):
        if self._mapping_locked():
            return self.async_abort(reason="stop_before_mapping")
        errors = {}
        if user_input is not None:
            loads = self._loads()
            if any(x.get("energy_entity") == user_input["energy_entity"] for x in loads):
                errors["base"] = "duplicate_load"
            else:
                loads.append({"id": uuid4().hex[:12], **user_input})
                return self.async_create_entry(title="", data={**dict(self.config_entry.options), "extra_loads": loads})
        return self.async_show_form(step_id="add_load", errors=errors, data_schema=vol.Schema({
            vol.Required("name"): selector.TextSelector(),
            vol.Required("energy_entity"): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="energy")),
            vol.Optional("power_entity"): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="power")),
            vol.Required("included_in_load", default=True): selector.BooleanSelector(),
        }))

    async def async_step_remove_load(self, user_input=None):
        if self._mapping_locked():
            return self.async_abort(reason="stop_before_mapping")
        loads = self._loads()
        if not loads:
            return self.async_abort(reason="no_extra_loads")
        if user_input is not None:
            loads = [x for x in loads if x.get("id") != user_input["load_id"]]
            return self.async_create_entry(title="", data={**dict(self.config_entry.options), "extra_loads": loads})
        return self.async_show_form(step_id="remove_load", data_schema=vol.Schema({
            vol.Required("load_id"): selector.SelectSelector(selector.SelectSelectorConfig(
                options=[{"value": x["id"], "label": x.get("name", x["energy_entity"])} for x in loads]))
        }))

    async def async_step_parameters(self, user_input=None):
        values = {**DEFAULT_OPTIONS, **self.config_entry.data, **self.config_entry.options}
        errors = {}
        if user_input is not None:
            errors = _errors({**values, **user_input})
            if not errors:
                return self.async_create_entry(title="", data={**dict(self.config_entry.options), **user_input})
        return self.async_show_form(step_id="parameters", errors=errors,
            data_schema=_schema({**values, **(user_input or {})}, OPTION_RANGES))

    async def async_step_sources(self, user_input=None):
        if self._mapping_locked():
            return self.async_abort(reason="stop_before_mapping")
        values = {**DEFAULT_SOURCES, **self.config_entry.data.get("sources", {}),
                  **self.config_entry.options.get("sources", {})}
        if user_input is not None:
            # Empty selections intentionally disable a source; no credential is needed.
            values.update(user_input)
            return self.async_create_entry(title="", data={**dict(self.config_entry.options), "sources": values})
        fields = {}
        for key, entity in values.items():
            domain = "number" if key in ("grid_current_number", "max_charge_current_number") or key.startswith("tou_soc_") else "switch" if key.startswith("tou_gc_") or key in ("solar_sell", "tou_enabled") else "time" if key.startswith("tou_time_") else "select" if key in ("energy_priority", "work_mode") else "sensor"
            fields[vol.Optional(key, description={"suggested_value": entity})] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=domain))
        return self.async_show_form(step_id="sources", data_schema=vol.Schema(fields))
