"""Versioned EU inverter ratings, independent of user installation settings.

Ratings are ceilings, not permission to increase a saved setting. Only LV
families matching the existing six-period entity control contract are listed.
The actual mapped Deye/BMS limits and fresh telemetry remain mandatory.
"""
from __future__ import annotations

import math

CATALOG_VERSION = "2026-11-13"
SG04LP1_SOURCE = "https://www.deyeinverter.com/deyeinverter/2026/04/24/BDatasheetSUN-3-6K-SG04LP120260424en-xMzy.pdf"
SG05LP1_SOURCE = "https://www.deyeinverter.com/product/single-phase-low-voltage-hybrid-inverter/hybrid-inverter-sun-3-610-ksg05lp1eusm2p-2740.html"
SG04LP3_SOURCE = "https://deye.com/product/sun-5-6-8-10-12k-sg04lp3-eu/"
SG05LP3_SOURCE = "https://www.deyeinverter.com/deyeinverter/2026/09/14/BDatasheetSUN-3-12K-SG05LP3-EU-SM220260911en.pdf"
SG05LP3_LARGE_SOURCE = "https://www.deyeinverter.com/deyeinverter/2026/09/14/BDatasheetSUN-14-20K-SG05LP3-EU-SM220260911en.pdf"


def _family(suffix, phases, powers, currents, source, passthrough=None, *, battery_inputs=None):
    return {
        f"SUN-{power:g}K-{suffix}": {
            "model_id": f"SUN-{power:g}K-{suffix}",
            "label": f"SUN-{power:g}K-{suffix}", "phases": phases,
            "battery_type": "LV", "battery_min_v": 40., "battery_max_v": 60.,
            "rated_power_kw": float(power),
            "phase_max_power_kw": float(power if phases == 1 else power / 2),
            "grid_passthrough_a": passthrough,
            "max_charge_current_a": float(current),
            "max_discharge_current_a": float(current), "tou_periods": 6,
            "control_supported": True, "source_url": source,
            "catalog_version": CATALOG_VERSION,
            "compatibility": "LV entity contract; verify mapped entities and firmware before control",
            **({"battery_inputs": battery_inputs} if battery_inputs is not None else {}),
        }
        for power, current in zip(powers, currents, strict=True)
    }


INVERTER_MODELS = {
    **_family("SG04LP1-EU", 1, (3, 3.6, 5, 6), (70, 90, 120, 135), SG04LP1_SOURCE),
    **_family("SG05LP1-EU-SM2-P", 1, (3.6, 5, 6, 7, 7.6, 8, 10),
              (90, 120, 135, 175, 190, 190, 210), SG05LP1_SOURCE),
    **_family("SG04LP3-EU", 3, (5, 6, 8, 10, 12), (120, 150, 190, 210, 240),
              SG04LP3_SOURCE, 45.),
    **_family("SG05LP3-EU-SM2", 3, (3, 4, 5, 6, 8, 10, 12),
              (70, 95, 120, 135, 190, 210, 240), SG05LP3_SOURCE, 45., battery_inputs=1),
    **_family("SG05LP3-EU-SM2", 3, (14, 15, 16, 18, 20),
              (260, 280, 300, 330, 350), SG05LP3_LARGE_SOURCE, 70., battery_inputs=2),
}
HARDWARE_KEYS = ("inverter_model", "inverter_phases", "connection_phases", "inverter_phase")


def _phases(value):
    if isinstance(value, bool) or value not in (1, 3):
        raise ValueError("invalid_inverter_phases")
    return int(value)


def model_choices():
    """Fresh dicts for HA SelectSelector; no network or discovery side effects."""
    return [{"value": "custom", "label": "Własny / dotychczasowe parametry — LV 40–65 V"}, *(
        {"value": key, "label": f"{model['label']} — {model['phases']} faz., LV"}
        for key, model in INVERTER_MODELS.items())]


def hardware_profile(options):
    """Validate every saved hardware setting; unknown models never mean 3-phase."""
    model_id = options.get("inverter_model", "custom")
    if not isinstance(model_id, str) or (model_id != "custom" and model_id not in INVERTER_MODELS):
        raise ValueError("invalid_inverter_model")
    phases = _phases(options.get("inverter_phases", 3))
    connection = _phases(options.get("connection_phases", 3))
    phase = options.get("inverter_phase", "L1")
    if phase not in ("L1", "L2", "L3") or (connection == 1 and phase != "L1"):
        raise ValueError("invalid_inverter_phase")
    if phases > connection:
        raise ValueError("invalid_connection_phases")
    if model_id == "custom":
        profile = {
            "model_id": "custom", "label": "Własny / dotychczasowe parametry",
            "phases": phases, "battery_type": "LV", "battery_min_v": 40.,
            "battery_max_v": 65., "rated_power_kw": None, "phase_max_power_kw": None,
            "grid_passthrough_a": None, "max_charge_current_a": None,
            "max_discharge_current_a": None, "tou_periods": 6, "control_supported": True,
            "source_url": None, "catalog_version": CATALOG_VERSION,
            "compatibility": "Manual LV settings; verify inverter ratings and entity mappings",
        }
    else:
        profile = dict(INVERTER_MODELS[model_id])
        if phases != profile["phases"]:
            raise ValueError("inverter_model_phase_mismatch")
    return {**profile, "connection_phases": connection, "inverter_phase": phase}


def model_selection(values):
    """Normalize an explicit model choice; callers show a preview before saving."""
    result = {key: values.get(key, default) for key, default in zip(
        HARDWARE_KEYS, ("custom", 3, 3, "L1"), strict=True)}
    for key in ("inverter_phases", "connection_phases"):
        if result[key] in ("1", "3"):
            result[key] = int(result[key])
    model = result["inverter_model"]
    if not isinstance(model, str):
        raise ValueError("invalid_inverter_model")
    if model != "custom":
        if model not in INVERTER_MODELS:
            raise ValueError("invalid_inverter_model")
        result["inverter_phases"] = INVERTER_MODELS[model]["phases"]
    hardware_profile(result)
    return result


def applied_limits(options):
    """Effective power ceilings only, retaining lower user limits and all options."""
    profile = hardware_profile(options)
    result = {}
    ceilings = {
        "inverter_max_power_kw": profile["rated_power_kw"],
        "inverter_phase_max_power_kw": profile["phase_max_power_kw"],
        "combined_output_limit_kw": profile["rated_power_kw"],
        "discharge_max_kw": profile["rated_power_kw"],
    }
    for key, ceiling in ceilings.items():
        value = options.get(key)
        if value is None:
            if ceiling is not None:
                result[key] = ceiling
            continue
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            raise ValueError("invalid_inverter_limits")
        result[key] = min(value, ceiling) if ceiling is not None else value
    # A one-phase unit cannot have a phase ceiling greater than its total.
    if profile["phases"] == 1 and "inverter_max_power_kw" in result and "inverter_phase_max_power_kw" in result:
        result["inverter_phase_max_power_kw"] = min(
            result["inverter_phase_max_power_kw"], result["inverter_max_power_kw"])
    return result
