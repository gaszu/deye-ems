"""Configure a local EMS; setup never takes ownership of the inverter."""
from __future__ import annotations
from uuid import uuid4

import probatio as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.helpers import entity_registry as er

from .const import (BATTERY_SOURCE_KEYS, BATTERY_SOURCE_PROFILES, DEFAULT_OPTIONS,
                    DEFAULT_SOURCES, DOMAIN, OPTION_RANGES, YAMBMS_SOURCES,
                    battery_source_profile)
from .solcast import validate_config
from .solcast_import import import_existing_options
from .appearance import DATA_APPEARANCE
from . import async_update_panel
from .soc_policy import reserve_bound_from_state
from .inverter_models import (HARDWARE_KEYS, applied_limits, hardware_profile,
                              model_choices, model_selection)


def _hardware_fields(values):
    fields = {vol.Required("inverter_model", default=values.get("inverter_model", "custom")):
        selector.SelectSelector(selector.SelectSelectorConfig(options=model_choices()))}
    for key in ("inverter_phases", "connection_phases"):
        fields[vol.Required(key, default=str(values.get(key, 3)))] = selector.SelectSelector(
            selector.SelectSelectorConfig(options=[{"value": "1", "label": "1 — jednofazowy"},
                                                    {"value": "3", "label": "3 — trójfazowy"}]))
    fields[vol.Required("inverter_phase", default=values.get("inverter_phase", "L1"))] = selector.SelectSelector(
        selector.SelectSelectorConfig(options=["L1", "L2", "L3"]))
    return fields


def _hardware_draft(values):
    selected = model_selection(values)
    candidate = {**values, **selected}
    return {**candidate, **applied_limits(candidate)}


def _hardware_revision(values):
    return {key: values.get(key) for key in (*HARDWARE_KEYS,
        "inverter_max_power_kw", "inverter_phase_max_power_kw", "combined_output_limit_kw", "discharge_max_kw")}


def _hardware_preview(values):
    profile = hardware_profile(values)
    rating = (f"{profile['rated_power_kw']:g} kW" if profile["rated_power_kw"] is not None
              else "parametry ręczne")
    return (f"{profile['label']} • {profile['phases']} faz. • bateria {profile['battery_type']} "
            f"{profile['battery_min_v']:g}–{profile['battery_max_v']:g} V\n\n"
            f"Moc producenta: {rating}. Przyłącze: {profile['connection_phases']} faz. "
            f"Faza falownika jednofazowego: {profile['inverter_phase']}.\n\n"
            f"Limity po zapisie: falownik {values.get('inverter_max_power_kw', 12):g} kW; "
            f"na fazę {values.get('inverter_phase_max_power_kw', 5):g} kW. "
            "Niższe limity instalacji, rezerwa SoC i przypisania encji są zachowane. "
            "Bieżące ograniczenia Deye oraz BMS nadal obowiązują. "
            "Wybór modelu nie potwierdza zgodności mapowań i firmware; sprawdź je w obserwacji.")


def _flow_reserve_bound(flow, sources):
    hass = getattr(flow, "hass", None)
    state = hass.states.get(sources.get("battery_low_soc")) if hass is not None else None
    return reserve_bound_from_state(state)


def _deye_prefix_sources(prefix):
    """Build explicit Deye mappings only; never rewrite YamBMS, PV or pump IDs."""
    if not isinstance(prefix, str):
        raise ValueError("invalid_entity_prefix")
    prefix = prefix.strip().lower().rstrip("_")
    if (not prefix or len(prefix) > 100
            or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in prefix)):
        raise ValueError("invalid_entity_prefix")
    prefix += "_"
    mapping = {}
    for key, entity in DEFAULT_SOURCES.items():
        if not entity:
            continue
        domain, name = entity.split(".", 1)
        if name.startswith("deye_inverter_"):
            mapping[key] = f"{domain}.{prefix}{name[len('deye_inverter_'):]}"
    return prefix, mapping


def _battery_profile_sources(profile, prefix):
    if profile not in BATTERY_SOURCE_PROFILES:
        raise ValueError("invalid_battery_source_profile")
    if profile == "yambms":
        return dict(YAMBMS_SOURCES)
    if profile == "manual":
        return dict.fromkeys(BATTERY_SOURCE_KEYS, "")
    _, mapping = _deye_prefix_sources(prefix)
    return {key: mapping.get(key, "") for key in BATTERY_SOURCE_KEYS}


def _single_phase_source_suggestions(values, prefix, phases, profile, get_state):
    """Suggest only existing 1P aliases for missing generated Deye defaults.

    This is a form proposal, never a migration or a runtime fallback. Keep
    manual IDs, explicit empty fields and separate battery profiles untouched.
    """
    if phases != 1 or profile != "deye":
        return {}
    try:
        prefix, generated = _deye_prefix_sources(prefix)
    except ValueError:
        return {}
    candidates = {"soc": f"sensor.{prefix}battery",
                  "battery_alarm": f"sensor.{prefix}device_alarm",
                  "battery_fault": f"sensor.{prefix}device_fault"}
    candidates.update({f"tou_gc_{slot}": f"switch.{prefix}time_of_use_{slot}_charge_enable"
                       for slot in range(1, 7)})
    return {key: entity for key, entity in candidates.items()
            if values.get(key) == generated.get(key)
            and get_state(values[key]) is None and get_state(entity) is not None}


def _battery_profile_selector():
    return selector.SelectSelector(selector.SelectSelectorConfig(options=[
        {"value": "deye", "label": "Deye — dane baterii z falownika"},
        {"value": "yambms", "label": "YamBMS — opcjonalne osobne źródło"},
        {"value": "manual", "label": "Ręczne przypisanie źródeł baterii"}]))


def _schema(values, keys):
    fields = {}
    for key in keys:
        low, high, step, unit = OPTION_RANGES[key]
        if key == "min_soc_percent":
            low = values.get("min_soc_lower_bound") or 40
        value = values.get(key, DEFAULT_OPTIONS[key])
        if key == "min_soc_percent":
            value = max(value, low)
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
        bound = _flow_reserve_bound(self, DEFAULT_SOURCES)
        if user_input is not None:
            errors = _errors(user_input)
            try:
                draft = _hardware_draft({**DEFAULT_OPTIONS, **user_input})
                prefix, mapping = _deye_prefix_sources(user_input.get("entity_prefix", "deye_inverter_"))
                profile = user_input.get("battery_source_profile", "deye")
                mapping.update(_battery_profile_sources(profile, prefix))
                hass = getattr(self, "hass", None)
                if hass is not None:
                    mapping.update(_single_phase_source_suggestions(
                        mapping, prefix, draft["inverter_phases"], profile, hass.states.get))
                bound = _flow_reserve_bound(self, {**DEFAULT_SOURCES, **mapping})
                if user_input.get("min_soc_percent", 40) < (bound if bound is not None else 40):
                    errors["min_soc_percent"] = "reserve_below_low_soc"
            except ValueError as error:
                errors["base" if str(error).startswith(("invalid_inverter", "invalid_connection", "inverter_model")) else
                       "battery_source_profile" if str(error) == "invalid_battery_source_profile"
                       else "entity_prefix"] = str(error)
            if not errors:
                if draft["inverter_phases"] == 1:
                    for phase in (1, 2, 3):
                        for kind in ("grid", "load"):
                            mapping[f"{kind}_l{phase}_power"] = ""
                    mapping["asymmetric_phase_feeding"] = ""
                self._initial_draft = {**draft, "entity_prefix": prefix,
                    "battery_source_profile": profile, "sources": {**DEFAULT_SOURCES, **mapping}}
                if draft["inverter_model"] != "custom" or draft["inverter_phases"] == 1:
                    return await self.async_step_user_inverter_confirm()
                await self.async_set_unique_id("deye_ems_local")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Deye EMS", data={
                    **self._initial_draft})
        return self.async_show_form(step_id="user", errors=errors, data_schema=_schema(
            {**(user_input or DEFAULT_OPTIONS), "min_soc_lower_bound": bound}, ["min_soc_percent", "capacity_kwh", "pv_peak_kwp",
                "inverter_max_power_kw", "inverter_phase_max_power_kw", "grid_import_limit_kw", "grid_phase_limit_kw"]).extend({
                    vol.Optional("entity_prefix", default=(user_input or {}).get("entity_prefix", "deye_inverter_")):
                        selector.TextSelector(),
                    vol.Required("battery_source_profile", default=(user_input or {}).get(
                        "battery_source_profile", "deye")): _battery_profile_selector()}).extend(
                    _hardware_fields(user_input or DEFAULT_OPTIONS)),
            description_placeholders={"mode": "shadow"})

    async def async_step_user_inverter_confirm(self, user_input=None):
        draft = getattr(self, "_initial_draft", None)
        if draft is None:
            return await self.async_step_user()
        if user_input is not None and user_input.get("confirm_model") is True:
            await self.async_set_unique_id("deye_ems_local")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Deye EMS", data=dict(draft))
        return self.async_show_form(step_id="user_inverter_confirm", data_schema=vol.Schema({
            vol.Required("confirm_model", default=False): selector.BooleanSelector()}),
            errors={"base": "confirm_inverter_model"} if user_input is not None else {},
            description_placeholders={"model_preview": _hardware_preview(draft)})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return DeyeEMSOptionsFlow()


class DeyeEMSOptionsFlow(config_entries.OptionsFlow):
    def _mapping_locked(self):
        runtime = getattr(self.config_entry, "runtime_data", None)
        return runtime is not None and runtime.mode == "active"

    def _entity_prefix(self):
        return self.config_entry.options.get("entity_prefix",
            self.config_entry.data.get("entity_prefix", "deye_inverter_"))

    def _battery_profile(self):
        return battery_source_profile(self.config_entry.data, self.config_entry.options)

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=["sidebar", "inverter", "topology", "parameters", "solcast", "entity_prefix", "sources", "add_load", "remove_load"])

    async def async_step_inverter(self, user_input=None):
        if self._mapping_locked():
            return self.async_abort(reason="stop_before_mapping")
        values = {**DEFAULT_OPTIONS, **self.config_entry.data, **self.config_entry.options}
        errors = {}
        if user_input is not None:
            try:
                self._hardware_draft = _hardware_draft({**values, **user_input})
                self._hardware_revision = _hardware_revision(values)
                return await self.async_step_inverter_confirm()
            except ValueError as error:
                errors["base"] = str(error)
        return self.async_show_form(step_id="inverter", errors=errors,
            data_schema=vol.Schema(_hardware_fields({**values, **(user_input or {})})))

    async def async_step_inverter_confirm(self, user_input=None):
        if self._mapping_locked():
            return self.async_abort(reason="stop_before_mapping")
        draft = getattr(self, "_hardware_draft", None)
        if draft is None:
            return await self.async_step_inverter()
        if user_input is not None and user_input.get("confirm_model") is True:
            # Only structural model fields and bounded power ceilings are saved.
            # No source, SoC, topology or forecast setting follows the model.
            selected = {key: draft[key] for key in HARDWARE_KEYS}
            values = {**DEFAULT_OPTIONS, **self.config_entry.data, **self.config_entry.options}
            if _hardware_revision(values) != self._hardware_revision:
                return self.async_abort(reason="inverter_settings_changed")
            return self.async_create_entry(title="", data={**dict(self.config_entry.options),
                **selected, **applied_limits(draft)})
        return self.async_show_form(step_id="inverter_confirm", data_schema=vol.Schema({
            vol.Required("confirm_model", default=False): selector.BooleanSelector()}),
            errors={"base": "confirm_inverter_model"} if user_input is not None else {},
            description_placeholders={"model_preview": _hardware_preview(draft)})

    async def async_step_topology(self, user_input=None):
        if self._mapping_locked():
            return self.async_abort(reason="stop_before_mapping")
        if user_input is not None:
            if user_input.get("topology") not in ("load_only", "load_with_external_ct"):
                return self.async_abort(reason="invalid_topology")
            return self.async_create_entry(title="", data={**dict(self.config_entry.options), **user_input})
        values = {**DEFAULT_OPTIONS, **self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="topology", data_schema=_schema(values,
            ["inverter_max_power_kw", "combined_output_limit_kw"]).extend({
            vol.Required("topology", default=values["topology"]): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[
                    {"value": "load_only", "label": "Cały dom pod LOAD — Zero Export To Load"},
                    {"value": "load_with_external_ct", "label": "Dom pod LOAD i odbiory między GRID a CT — Zero Export To CT"}]))}))

    async def async_step_entity_prefix(self, user_input=None):
        if self._mapping_locked():
            return self.async_abort(reason="stop_before_mapping")
        errors = {}
        if user_input is not None:
            try:
                prefix, mapping = _deye_prefix_sources(user_input.get("entity_prefix"))
                profile = user_input.get("battery_source_profile", self._battery_profile())
                battery = _battery_profile_sources(profile, prefix)
                try:
                    _, previous = _deye_prefix_sources(self._entity_prefix())
                except ValueError:
                    _, previous = _deye_prefix_sources("deye_inverter_")
                saved = {**self.config_entry.data.get("sources", {}),
                         **self.config_entry.options.get("sources", {})}
                # Keep manual mappings and intentionally disabled sources.
                # Only default/previous-prefix suggestions follow a new prefix.
                mapping = {key: entity for key, entity in mapping.items()
                    if key not in saved or saved[key] in (DEFAULT_SOURCES[key], previous[key])}
                for key in BATTERY_SOURCE_KEYS:
                    mapping.pop(key, None)
                if profile != "manual":
                    previous_battery = _battery_profile_sources(self._battery_profile(), self._entity_prefix())
                    mapping.update({key: entity for key, entity in battery.items()
                        if profile != self._battery_profile() or key not in saved
                        or saved[key] == previous_battery[key]})
                self._source_prefix_draft = prefix
                self._battery_profile_draft = profile
                self._source_mapping_draft = mapping
                return await self.async_step_sources()
            except ValueError as error:
                errors["base"] = str(error)
        value = (user_input or {}).get("entity_prefix", self._entity_prefix())
        return self.async_show_form(step_id="entity_prefix", errors=errors,
            data_schema=vol.Schema({vol.Required("entity_prefix", default=value): selector.TextSelector(),
                vol.Required("battery_source_profile", default=(user_input or {}).get(
                    "battery_source_profile", self._battery_profile())): _battery_profile_selector()}))

    async def async_step_sidebar(self, user_input=None):
        manager = self.hass.data.get(DATA_APPEARANCE)
        if manager is None:
            return self.async_abort(reason="panel_not_ready")
        errors = {}
        if user_input is not None:
            try:
                await manager.async_set_sidebar_visible(user_input.get("sidebar_visible"))
                await async_update_panel(self.hass)
                # No config-entry options update: this must not restart control.
                return self.async_abort(reason="sidebar_saved")
            except (HomeAssistantError, ValueError):
                errors["base"] = "sidebar_save_failed"
        return self.async_show_form(step_id="sidebar", errors=errors,
            data_schema=vol.Schema({vol.Required("sidebar_visible", default=manager.sidebar_visible):
                                   selector.BooleanSelector()}))

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
        sources = {**self.config_entry.data.get("sources", {}),
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
        sources = {**DEFAULT_SOURCES, **self.config_entry.data.get("sources", {}),
                   **self.config_entry.options.get("sources", {})}
        bound = _flow_reserve_bound(self, sources)
        values["min_soc_lower_bound"] = bound
        errors = {}
        if user_input is not None:
            if (self._mapping_locked() and "combined_output_limit_kw" in user_input
                    and user_input["combined_output_limit_kw"] != values["combined_output_limit_kw"]):
                return self.async_abort(reason="stop_before_mapping")
            errors = _errors({**values, **user_input})
            proposed = user_input.get("min_soc_percent", values["min_soc_percent"])
            if proposed < (bound if bound is not None else 40):
                errors["min_soc_percent"] = "reserve_below_low_soc"
            if bound is None and proposed != values["min_soc_percent"]:
                errors["min_soc_percent"] = "battery_low_soc_unavailable"
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
                  **self.config_entry.options.get("sources", {}),
                  **getattr(self, "_source_mapping_draft", {})}
        if user_input is not None:
            # EntitySelector omits an empty optional field instead of accepting
            # an empty entity ID. A source form submits the whole mapping.
            values = {key: user_input.get(key, "") for key in values}
            options = {**dict(self.config_entry.options), "sources": values}
            if hasattr(self, "_source_prefix_draft"):
                options["entity_prefix"] = self._source_prefix_draft
                options["battery_source_profile"] = self._battery_profile_draft
            return self.async_create_entry(title="", data=options)
        selected = {**DEFAULT_OPTIONS, **self.config_entry.data, **self.config_entry.options}
        profile = getattr(self, "_battery_profile_draft", self._battery_profile())
        prefix = getattr(self, "_source_prefix_draft", self._entity_prefix())
        suggestions = _single_phase_source_suggestions(
            values, prefix, selected["inverter_phases"], profile, self.hass.states.get)
        values.update(suggestions)
        fields = {}
        for key, entity in values.items():
            domain = "binary_sensor" if key in ("battery_alarm", "battery_fault") else "number" if key in ("grid_current_number", "max_charge_current_number", "battery_low_soc") or key.startswith("tou_soc_") else "switch" if key.startswith("tou_gc_") or key in ("solar_sell", "tou_enabled", "asymmetric_phase_feeding") else "time" if key.startswith("tou_time_") else "select" if key in ("energy_priority", "work_mode") else "sensor"
            if key in ("battery_alarm", "battery_fault") and selected["inverter_phases"] == 1 and profile == "deye":
                domain = ["binary_sensor", "sensor"]
            marker = (vol.Optional(key, description={"suggested_value": entity})
                      if entity else vol.Optional(key))
            fields[marker] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=domain))
        draft = getattr(self, "_source_mapping_draft", {})
        proposed = [values[key] for key in draft if values.get(key)]
        missing = [entity for entity in proposed if self.hass.states.get(entity) is None]
        profile_label = {"deye": "Deye", "yambms": "YamBMS", "manual": "ręczny"}[profile]
        profile_note = ("Wybrany profil proponuje nowe przypisania baterii. "
                        if profile != self._battery_profile() and profile != "manual"
                        else "Ręczne i wyłączone przypisania zachowano. ")
        preview = (f"Prefiks: {self._source_prefix_draft}. Znaleziono {len(proposed)-len(missing)}/{len(proposed)} encji. "
                   + ("Brak: " + ", ".join(missing) if missing else "Wszystkie proponowane encje istnieją.")
                   + f" Profil baterii: {profile_label}. " + profile_note
                   + "Sprawdź i popraw przypisania przed zapisaniem. Istnienie encji nie potwierdza zgodności trybu ani pomiarów."
                   if hasattr(self, "_source_prefix_draft") else "Ręczny wybór encji. Prefiks Deye ustawisz w osobnej pozycji menu konfiguracji.")
        if suggestions:
            preview += " Propozycje istniejących encji dla falownika jednofazowego: " + ", ".join(suggestions.values()) + ". Zapisz dopiero po sprawdzeniu przypisań."
        if selected["inverter_phases"] == 1 and profile == "deye":
            missing_ccl = not values.get("bms_charge_current") or self.hass.states.get(values["bms_charge_current"]) is None
            if missing_ccl:
                preview += (" Brak encji bieżącego limitu BMS (bms_charge_current): profil Deye korzysta wtedy z 95% "
                    "maksymalnego prądu ładowania odczytanego z ustawień Deye. Dotyczy to również świadomie wyłączonego przypisania CCL.")
            else:
                preview += " Przypisany bieżący limit BMS dodatkowo ogranicza limit Deye −5%, gdy jest od niego niższy."
            preview += (" Istniejąca encja CCL z błędnym lub niedostępnym odczytem nie pozwala przejść na sam limit Deye; "
                "CCL równy 0 A blokuje ładowanie.")
            if any(values.get(key, "").startswith("sensor.") for key in ("battery_alarm", "battery_fault")):
                preview += (" W profilu jednofazowym sensorowe źródła alarmu i błędu opisują cały falownik. "
                    "Tylko stan OK jest poprawnym potwierdzeniem braku problemu; błąd, alarm, N/A lub brak odczytu blokuje sterowanie.")
            missing_flags = [key for key in ("battery_alarm", "battery_fault")
                             if not values.get(key) or self.hass.states.get(values[key]) is None]
            if missing_flags:
                preview += (" Brak źródeł alarmu lub błędu baterii: " + ", ".join(missing_flags) + ". "
                    "Sterownik jednofazowy może ich nie publikować. Te zabezpieczenia nadal obowiązują; "
                    "brak poprawnych odczytów alarmu i błędu blokuje sterowanie.")
        return self.async_show_form(step_id="sources", data_schema=vol.Schema(fields),
                                    description_placeholders={"prefix_preview": preview})
