"""User-editable defaults for the independent Deye EMS engine."""
DOMAIN = "deye_ems"
VERSION = "1.0.12"
PLATFORMS = ["sensor", "binary_sensor", "number", "select", "button"]

DEFAULT_OPTIONS = {
    "topology": "load_only",
    "combined_output_limit_kw": 10.0,
    "capacity_kwh": 66.0,
    "pv_peak_kwp": None,
    "pv_forecast_reference_kwp": None,
    "pv_forecast_mode": "whole_system",
    "min_soc_percent": 40.0,
    "reserve_margin_soc_percent": 5.0,
    "winter_weather_soc_percent": 75.0,
    "grid_import_limit_kw": 12.0,
    "grid_phase_limit_kw": 5.0,
    "inverter_max_power_kw": 12.0,
    "inverter_phase_max_power_kw": 5.0,
    "grid_current_max_a": 108.0,
    "charge_max_kw": 5.3,
    "discharge_max_kw": 10.0,
    "grid_max_soc_percent": 95.0,
    "update_seconds": 10,
    "extra_loads": [],
}

OPTION_RANGES = {
    "combined_output_limit_kw": (.1, 1000, .1, "kW"),
    "min_soc_percent": (5, 90, 1, "%"),
    "capacity_kwh": (1, 1000, .1, "kWh"),
    "pv_peak_kwp": (.1, 1000, .1, "kWp"),
    "pv_forecast_reference_kwp": (.1, 1000, .1, "kWp"),
    "grid_import_limit_kw": (1, 30, .1, "kW"),
    "grid_phase_limit_kw": (.5, 15, .1, "kW"),
    "inverter_max_power_kw": (.1, 1000, .1, "kW"),
    "inverter_phase_max_power_kw": (.1, 500, .1, "kW"),
    "reserve_margin_soc_percent": (0, 10, 1, "%"),
    "winter_weather_soc_percent": (45, 95, 1, "%"),
    "grid_current_max_a": (0, 108, 1, "A"),
    "charge_max_kw": (.1, 12, .1, "kW"),
    "discharge_max_kw": (.1, 12, .1, "kW"),
    "grid_max_soc_percent": (45, 95, 1, "%"),
}
OPTION_LABELS = {
    "combined_output_limit_kw": "Wspólny limit modelowy LOAD i odbiorów przed GRID",
    "min_soc_percent": "Minimalny bezpieczny SoC",
    "capacity_kwh": "Pojemność magazynu",
    "pv_peak_kwp": "Zainstalowana moc PV",
    "pv_forecast_reference_kwp": "Moc instalacji referencyjnej prognozy",
    "grid_import_limit_kw": "Limit importu przyłącza — łącznie",
    "grid_phase_limit_kw": "Limit importu przyłącza — na fazę",
    "inverter_max_power_kw": "Moc falownika — łącznie",
    "inverter_phase_max_power_kw": "Dopuszczalna moc falownika na fazę",
    "reserve_margin_soc_percent": "Dodatkowy bufor prognozy",
    "winter_weather_soc_percent": "Zimowy cel przy słabej prognozie PV",
    "grid_current_max_a": "Maksymalny prąd ładowania z sieci",
    "charge_max_kw": "Modelowy limit ładowania baterii",
    "discharge_max_kw": "Modelowy limit rozładowania baterii",
    "grid_max_soc_percent": "Maksymalny cel doładowania z sieci",
}
DEFAULT_SOURCES = {
    "battery_low_soc": "number.deye_inverter_battery_low_soc",
    "ct_grid_power": "sensor.deye_inverter_external_ct_power",
    "ct_grid_l1_power": "sensor.deye_inverter_external_ct_l1_power",
    "ct_grid_l2_power": "sensor.deye_inverter_external_ct_l2_power",
    "ct_grid_l3_power": "sensor.deye_inverter_external_ct_l3_power",
    "soc": "sensor.yambms_1_battery_soc",
    "voltage": "sensor.yambms_1_total_voltage",
    "bms_charge_current": "sensor.yambms_1_max_charge_current",
    "bms_blocking_charge": "sensor.yambms_1_bms_blocking_charge",
    "battery_power": "sensor.deye_inverter_battery_power",
    "grid_power": "sensor.deye_inverter_grid_power",
    "load_power": "sensor.deye_inverter_load_power",
    "grid_current_number": "number.deye_inverter_maximum_battery_grid_charge_current",
    "max_charge_current_number": "number.deye_inverter_maximum_battery_charge_current",
    "pv_today": "sensor.solcast_pv_forecast_prognoza_na_dzisiaj",
    "pv_tomorrow": "sensor.solcast_pv_forecast_prognoza_na_jutro",
    "pv_day3": "sensor.solcast_pv_forecast_prognoza_na_dzien_3",
    "pc_energy_total": "sensor.pc_faza2_energy_total",
    "pc_energy_today": "sensor.pc_faza2_energy_today",
    "pc_energy_yesterday": "sensor.pc_faza2_energy_yesterday",
    "solar_sell": "switch.deye_inverter_solar_sell",
    "tou_enabled": "switch.deye_inverter_time_of_use",
    "energy_priority": "select.deye_inverter_energy_management_priority",
    "work_mode": "select.deye_inverter_system_work_mode",
    "asymmetric_phase_feeding": "switch.deye_inverter_asymmetric_phase_feeding",
}
for _phase in range(1, 4):
    for _kind in ("grid", "load"):
        DEFAULT_SOURCES[f"{_kind}_l{_phase}_power"] = f"sensor.deye_inverter_{_kind}_l{_phase}_power"
for _slot in range(1, 7):
    DEFAULT_SOURCES[f"tou_soc_{_slot}"] = f"number.deye_inverter_time_of_use_{_slot}_soc"
    DEFAULT_SOURCES[f"tou_gc_{_slot}"] = f"switch.deye_inverter_time_of_use_{_slot}_grid_charge"
    DEFAULT_SOURCES[f"tou_time_{_slot}"] = f"time.deye_inverter_time_of_use_{_slot}_start"

OWNER_ENTITIES = (
    "automation.ems_sterowanie_popoludniowe_magazynu_66kwh_g13_zima",
    "automation.ems_sterowanie_ladowaniem_nocnym_magazynu_66kwh_g13_zima",
    "automation.ems_sterowanie_tou_deye_66kwh_g13_lato",
    "automation.ems_sterowanie_tou_deye_66kwh_g13_zima",
    "automation.ems_sterowanie_ladowaniem_magazynu_66kwh_g13",
    "automation.ems_sterowanie_popoludniowe_magazynu_66kwh_g13",
    "automation.ems_sterowanie_popoludniowe_magazynu_66kwh_g13_zima_old",
    "automation.ems_emhass_sterowanie_produkcyjne",
    "automation.ems_emhass_ochrona_wlasciciela",
    "automation.ems_emhass_plan_shadow_co_5_minut",
)
LEGACY_OWNERS = OWNER_ENTITIES
