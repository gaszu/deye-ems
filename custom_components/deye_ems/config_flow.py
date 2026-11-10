"""Configure a local EMS; setup never takes ownership of the inverter."""
from __future__ import annotations
from uuid import uuid4

import probatio as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers import entity_registry as er

from .const import DEFAULT_OPTIONS, DEFAULT_SOURCES, DOMAIN, OPTION_RANGES
from .solcast import validate_config
from .solcast_import import import_existing_options


def _schema(values, keys):
    fields = {}
    for key in keys:
        low, high, step, unit = OPTION_RANGES[key]
        value = values.get(key, DEFAULT_OPTIONS[key])
        marker = vol.Optional(key) if value is None else vol.Required(key, default=value)
        fields[marker] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=low, max=high, step=step,
                mode=selector.NumberSelectorMode.BOX, unit_of_measurement=unit))
    return vol.Schema(fields)


def _errors(values):
    floor = values.get("min_soc_percent", 40)
    ceiling = values.get("grid_max_soc_percent", 95)
    margin = values.get("reserve_margin_soc_percent", 5)
    if floor + margin > ceiling:
        return {"base": "invalid_soc_limits"}
    if values.get("pv_forecast_mode") == "specific_profile" and not values.get("pv_forecast_reference_kwp"):
        return {"base": "pv_reference_required"}
    return {}


def _solcast_input(user_input, previous):
    """Normalize private config without putting a saved key back in a form."""
    key = user_input.get("api_key", "").strip() or previous.get("api_key", "")
    ids = user_input.get("resource_ids", "")
    ids = ids.replace("\n", ",").replace(";", ",")
    hourly = user_input.get("hourly_factors", "").strip()
    factors = [float(v) for v in hourly.replace(";", " ").replace(",", " ").split()] if hourly else [1.] * 24
    result = {"api_key": key, "enabled": True,
        "resource_ids": [v.strip() for v in ids.split(",") if v.strip()],
        "poll_interval_minutes": user_input.get("poll_interval_minutes", 360),
        "max_requests_per_day": user_input.get("max_requests_per_day", 10),
        "initial_requests_used": user_input.get("initial_requests_used", 10),
        "dampening_factor": user_input.get("dampening_factor", 1.),
        "hourly_factors": factors, "config_generation": uuid4().hex}
    for name in ("half_hourly_factors", "site_factors", "exclude_sites", "import_report", "import_metadata"):
        if name in previous:
            result[name] = previous[name]
    validate_config(result)
    return result


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
            user_input or DEFAULT_OPTIONS, ["min_soc_percent", "capacity_kwh", "pv_peak_kwp",
                "inverter_max_power_kw", "inverter_phase_max_power_kw", "grid_import_limit_kw", "grid_phase_limit_kw"]),
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
        return self.async_show_menu(step_id="init", menu_options=["parameters", "solcast", "sources", "add_load", "remove_load"])

    def _solcast_values(self):
        return dict(getattr(self, "_solcast_draft", None) or self.config_entry.options.get(
            "solcast", self.config_entry.data.get("solcast", {})))

    async def async_step_solcast(self, user_input=None):
        if self._mapping_locked():
            return self.async_abort(reason="stop_before_mapping")
        return self.async_show_menu(step_id="solcast", menu_options=[
            "solcast_manual", "solcast_import", "solcast_disable"])

    async def async_step_solcast_manual(self, user_input=None):
        if self._mapping_locked():
            return self.async_abort(reason="stop_before_mapping")
        values, errors = self._solcast_values(), {}
        adaptive = getattr(self, "_import_adaptive", False)
        if user_input is not None:
            try:
                if adaptive and not user_input.get("accept_manual_calibration"):
                    raise ValueError("import_calibration_required")
                config = _solcast_input(user_input, values)
                return self.async_create_entry(title="", data={
                    **dict(self.config_entry.options), "solcast": config})
            except (ValueError, TypeError):
                errors["base"] = "import_calibration_required" if adaptive and not user_input.get(
                    "accept_manual_calibration") else "invalid_solcast"
        display = {**values, **(user_input or {})}
        fields = {
            vol.Optional(vol.Secret("api_key")): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
            vol.Optional("resource_ids", default=display.get("resource_ids", "") if isinstance(display.get("resource_ids"), str)
                else ", ".join(display.get("resource_ids", []))): selector.TextSelector(),
        }
        for key, default, low, high, step in (
            ("poll_interval_minutes", 360, 15, 1440, 1),
            ("max_requests_per_day", 10, 1, 1000, 1),
            ("initial_requests_used", 10, 0, 1000, 1),
            ("dampening_factor", 1., 0, 2, .01)):
            fields[vol.Required(key, default=display.get(key, default))] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=low,max=high,step=step,mode=selector.NumberSelectorMode.BOX))
        hourly = display.get("hourly_factors", "")
        fields[vol.Optional("hourly_factors", default=hourly if isinstance(hourly, str) else " ".join(map(str, hourly)))] = selector.TextSelector()
        if adaptive:
            fields[vol.Required("accept_manual_calibration", default=False)] = selector.BooleanSelector()
        report = getattr(self, "_import_report", {})
        note = "Zapisany klucz pozostaje ukryty. Puste pole zachowuje dotychczasowy klucz."
        if report.get("calibration_imported"):
            note = "Bieżące współczynniki korekty zostały odczytane i skopiowane. Będą stosowane tylko do surowej prognozy API, bez ponownej korekty prognoz HA."
        if adaptive:
            note += " Przeniesiono stan współczynników, nie cały mechanizm dalszego automatycznego uczenia ani jego historię. Sprawdź ustawienia i potwierdź ten zakres migracji."
        if "source_suppression_not_implemented" in report.get("warnings", []):
            note += " Warunek wstrzymywania kalibracji ze źródłowej integracji zachowano jako opis; EMS go nie wykonuje."
        return self.async_show_form(step_id="solcast_manual", errors=errors,
            data_schema=vol.Schema(fields), description_placeholders={"import_note": note})

    async def async_step_solcast_import(self, user_input=None):
        if self._mapping_locked():
            return self.async_abort(reason="stop_before_mapping")
        entries = self.hass.config_entries.async_entries("solcast_solar")
        if not entries:
            return self.async_abort(reason="no_solcast_to_import")
        if user_input is not None:
            entry = next((e for e in entries if e.entry_id == user_input.get("source_entry")), None)
            if entry is None:
                return self.async_abort(reason="no_solcast_to_import")
            source = {**entry.data, **entry.options}
            attributes = None
            registry = er.async_get(self.hass)
            for record in er.async_entries_for_config_entry(registry, entry.entry_id):
                if record.platform == "solcast_solar" and record.unique_id == "dampen":
                    state = self.hass.states.get(record.entity_id)
                    if state is not None and state.state not in ("unknown", "unavailable"):
                        attributes = dict(state.attributes)
                    break
            try:
                imported = import_existing_options(source, attributes)
            except (ValueError, TypeError):
                return self.async_abort(reason="solcast_import_incomplete")
            self._import_report = imported["report"]
            self._import_adaptive = self._import_report.get("needs_manual_review", False)
            self._solcast_draft = {**imported["config"], "import_report": self._import_report}
            return await self.async_step_solcast_manual()
        return self.async_show_form(step_id="solcast_import", data_schema=vol.Schema({
            vol.Required("source_entry"): selector.SelectSelector(selector.SelectSelectorConfig(
                options=[{"value": e.entry_id, "label": e.title} for e in entries]))}))

    async def async_step_solcast_disable(self, user_input=None):
        if self._mapping_locked():
            return self.async_abort(reason="stop_before_mapping")
        config = {**self._solcast_values(), "enabled": False, "config_generation": uuid4().hex}
        return self.async_create_entry(title="", data={**dict(self.config_entry.options), "solcast": config})

    def _loads(self):
        runtime = getattr(self.config_entry, "runtime_data", None)
        effective = getattr(runtime, "effective_loads", None)
        if effective is not None:
            return [{**dict(channel), "included_in_load": True} for channel in effective]
        values = {**self.config_entry.data, **self.config_entry.options}
        sources = {**DEFAULT_SOURCES, **self.config_entry.data.get("sources", {}),
                   **self.config_entry.options.get("sources", {})}
        loads, seen = [], set()
        for raw in values.get("extra_loads", []):
            if not isinstance(raw, dict):
                continue
            entity = raw.get("energy_entity")
            if not isinstance(entity, str) or not entity or entity in seen:
                continue
            seen.add(entity)
            loads.append({"id": raw.get("id") or entity,
                "name": str(raw.get("name") or entity), "energy_entity": entity,
                "power_entity": raw.get("power_entity", ""),
                "included_in_load": True,
                "enabled": raw.get("enabled", True) is True})
        pump = sources.get("pc_energy_total")
        if pump and pump not in seen and values.get("extra_loads_managed") is not True:
            loads.append({"id": "configured_heatpump", "name": "Pompa ciepła",
                "energy_entity": pump, "power_entity": "", "included_in_load": True, "enabled": True})
        return loads

    async def async_step_add_load(self, user_input=None):
        if self._mapping_locked():
            return self.async_abort(reason="stop_before_mapping")
        errors = {}
        if user_input is not None:
            loads = self._loads()
            if any(x.get("energy_entity") == user_input["energy_entity"] for x in loads):
                errors["base"] = "duplicate_load"
            else:
                loads.append({"power_entity": "", "enabled": True, **user_input,
                    "included_in_load": True, "id": uuid4().hex[:12]})
                return self.async_create_entry(title="", data={**dict(self.config_entry.options),
                    "extra_loads": loads, "extra_loads_managed": True})
        return self.async_show_form(step_id="add_load", errors=errors, data_schema=vol.Schema({
            vol.Required("name"): selector.TextSelector(),
            vol.Required("energy_entity"): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="energy")),
            vol.Optional("power_entity"): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="power")),
        }))

    async def async_step_remove_load(self, user_input=None):
        if self._mapping_locked():
            return self.async_abort(reason="stop_before_mapping")
        loads = self._loads()
        if not loads:
            return self.async_abort(reason="no_extra_loads")
        if user_input is not None:
            loads = [x for x in loads if x.get("id") != user_input["load_id"]]
            return self.async_create_entry(title="", data={**dict(self.config_entry.options),
                "extra_loads": loads, "extra_loads_managed": True})
        return self.async_show_form(step_id="remove_load", data_schema=vol.Schema({
            vol.Required("load_id"): selector.SelectSelector(selector.SelectSelectorConfig(
                options=[{"value": x["id"], "label": x.get("name") or x["energy_entity"]} for x in loads]))
        }))

    async def async_step_parameters(self, user_input=None):
        values = {**DEFAULT_OPTIONS, **self.config_entry.data, **self.config_entry.options}
        errors = {}
        if user_input is not None:
            errors = _errors({**values, **user_input})
            if not errors:
                return self.async_create_entry(title="", data={**dict(self.config_entry.options), **user_input})
        return self.async_show_form(step_id="parameters", errors=errors,
            data_schema=_schema({**values, **(user_input or {})}, OPTION_RANGES).extend({
                vol.Required("pv_forecast_mode", default=(user_input or {}).get("pv_forecast_mode", values["pv_forecast_mode"])):
                    selector.SelectSelector(selector.SelectSelectorConfig(options=[
                        {"value": "whole_system", "label": "Solcast / prognoza całej instalacji (bez skalowania)"},
                        {"value": "specific_profile", "label": "Profil referencyjny (skalowanie według mocy kWp)"}]))}))

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
            domain = "number" if key in ("grid_current_number", "max_charge_current_number") or key.startswith("tou_soc_") else "switch" if key.startswith("tou_gc_") or key in ("solar_sell", "tou_enabled", "asymmetric_phase_feeding") else "time" if key.startswith("tou_time_") else "select" if key in ("energy_priority", "work_mode") else "sensor"
            fields[vol.Optional(key, description={"suggested_value": entity})] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=domain))
        return self.async_show_form(step_id="sources", data_schema=vol.Schema(fields))
