"""Pure validation and readable previews for an explicit tariff selection."""
from copy import deepcopy
from hashlib import sha256
import json


def selected_tariff(profiles, profile_id):
    found = [row for row in profiles if row.get("profile_id") == profile_id]
    if len(found) != 1:
        raise ValueError("invalid_tariff_profile")
    return deepcopy(found[0])


def tariff_revision(values):
    # Only settings that affect this preview; credentials never enter a token.
    keys = ("tariff_profile", "tariff_clock_basis", "tariff_contract_confirmed",
            "inverter_model", "inverter_phases", "connection_phases", "inverter_phase",
            "topology", "sources", "min_soc_percent", "capacity_kwh", "pv_peak_kwp",
            "grid_import_limit_kw", "grid_phase_limit_kw")
    return sha256(json.dumps({key: values.get(key) for key in keys},
                             sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_tariff_draft(profiles, operator_id, profile_id, clock_basis, *, now, describe):
    profile = selected_tariff(profiles, profile_id)
    if profile.get("operator_id", profile.get("operator")) != operator_id:
        raise ValueError("tariff_operator_mismatch")
    if profile.get("runtime_allowed") is not True or profile.get("supported") is not True:
        raise ValueError("tariff_profile_unavailable")
    if clock_basis not in ("local", "fixed_cet"):
        raise ValueError("invalid_tariff_clock_basis")
    if profile_id == "legacy_g13" and clock_basis != "local":
        raise ValueError("legacy_tariff_clock_unchanged")
    calendar = describe(now, profile_id, clock_basis)
    if calendar.get("within_validity") is not True:
        raise ValueError("tariff_outside_validity")
    return {"tariff_profile": profile_id, "tariff_clock_basis": clock_basis,
            "tariff_contract_confirmed": True}, calendar


def tariff_preview(calendar):
    basis = ("czas lokalny Polski, automatyczna zmiana lato/zima"
             if calendar["clock_basis"] == "local" else "stały czas zimowy CET")
    lines = [calendar["label"], "Zegar licznika: " + basis + "."]
    if calendar.get("valid_until"):
        lines.append("Reguły potwierdzone do " + calendar["valid_until"] + ".")
    if isinstance(calendar.get("notice"), str):
        lines.append(calendar["notice"])
    requirement_labels = {
        "remote_meter": "Taryfa wymaga licznika zdalnego odczytu.",
        "monthly_settlement": "Taryfa wymaga miesięcznego rozliczania.",
        "contract_group_confirmation": "Potwierdź grupę taryfową na swojej umowie.",
    }
    for notice in calendar.get("requirements") or []:
        if isinstance(notice, str):
            lines.append(requirement_labels.get(notice, "Sprawdź dodatkowe warunki taryfy w dokumencie operatora."))
    for key, label in (("today", "Dzisiaj"), ("tomorrow", "Jutro")):
        lines.append(label + ":")
        for row in calendar[key]:
            begin = row["start"][11:16]
            end = row["end"][11:16]
            end = "24:00" if end == "00:00" else end
            zone = row.get("zone_label") or row["zone"]
            policy = "możliwe ładowanie z sieci" if row["grid_charge_allowed"] else "bez ładowania z sieci"
            lines.append(f"{begin}–{end}: {zone}; {policy}.")
    if calendar.get("source_url"):
        lines.append("Źródło: " + calendar["source_url"])
    lines.append("Zapis dotyczy taryfy i potwierdzonego zegara licznika. Rezerwa SoC, źródła i limity instalacji pozostają zachowane. Po zapisie system sprawdzi warunki przed automatycznym włączeniem sterowania.")
    return "\n".join(lines)
