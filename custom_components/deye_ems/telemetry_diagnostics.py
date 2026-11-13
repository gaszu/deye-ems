"""Read-only explanations of existing telemetry validation outcomes.

This module grants no freshness and does not poll, publish or change a state.
The coordinator's original validators supply all validity decisions. Diagnostic
values use a strict numeric/unit allowlist; arbitrary provider states and
attributes never enter the output or the activation error.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re

_UTC = timezone.utc
_ENTITY = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_]+$")
_PLATFORM = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_UNITS = frozenset(("V", "mV", "A", "mA", "W", "kW", "VA", "kVA", "%", "Wh", "kWh"))
_LABELS = {
    "soc": "SoC baterii", "voltage": "Napięcie baterii",
    "bms_charge_current": "Limit prądu ładowania BMS",
    "bms_blocking_charge": "Blokada ładowania BMS",
    "charge_power": "Zgodność czasowa mocy GRID i baterii",
}
_REASONS = {"missing": "brak encji lub odczytu", "restored": "stan odtworzony po restarcie",
    "invalid": "niepoprawny odczyt", "future": "czas odczytu w przyszłości",
    "wrong_unit": "nieprawidłowa jednostka", "alias": "powtórzone przypisanie encji",
    "time_skew": "niespójne czasy odczytów", "invalid_or_unsupported": "niepoprawny profil sprzętu"}


def _finite(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _reported(state):
    """Match accepted timestamp shapes without exposing raw timestamp text."""
    value = getattr(state, "last_reported", None) or getattr(state, "last_updated", None)
    try:
        if isinstance(value, datetime):
            return value.astimezone(_UTC) if value.tzinfo is not None else None
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(_UTC) if parsed.tzinfo is not None else None
        stamp = _finite(value)
        if stamp is not None:
            stamp = stamp / 1000 if stamp > 10**11 else stamp
            return datetime.fromtimestamp(stamp, _UTC) if 0 <= stamp < 253402214400 else None
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    return None


def entity_platform(hass, entity_id):
    """Optional local registry lookup; framework stubs and missing entries are OK."""
    if not entity_id:
        return None
    try:
        from homeassistant.helpers import entity_registry as er
        registry = er.async_get(hass)
        record = registry.async_get(entity_id)
        value = getattr(record, "platform", None)
        return value if isinstance(value, str) and _PLATFORM.fullmatch(value) else None
    except Exception:
        # Provider identification is optional diagnostic enrichment. A registry
        # problem must not interrupt measurement validation or safety control.
        return None


def describe_telemetry(hass, sources, checks, issues, now, *, groups=None, platform_lookup=None, state_lookup=None):
    """Describe the authority's decisions, including aggregate coherence failures."""
    groups = groups or {}
    lookup = platform_lookup or entity_platform
    lookup_state = state_lookup or hass.states.get
    reasons = {}
    for issue in issues:
        reasons.setdefault(issue["source"], issue["reason"])
    details, platforms = [], {}
    for source, validation in checks.items():
        configured = sources.get(source)
        entity_id = configured if isinstance(configured, str) and len(configured) <= 255 and _ENTITY.fullmatch(configured) else None
        state = lookup_state(configured) if isinstance(configured, str) and configured else None
        attributes = getattr(state, "attributes", {})
        unit = attributes.get("unit_of_measurement")
        unit = unit if isinstance(unit, str) and unit in _UNITS else None
        expected = validation.get("unit")
        value = _finite(getattr(state, "state", None))
        if value is not None and (validation.get("low") is not None and value < validation["low"]
                                  or validation.get("high") is not None and value > validation["high"]):
            value = None
        reported = _reported(state)
        age = (now.timestamp() - reported.timestamp()) if reported is not None else None
        original = getattr(state, "original", state)
        ha_reported = _reported(original)
        ha_age = now.timestamp() - ha_reported.timestamp() if ha_reported is not None else None
        timestamp_source = "esphome_live" if getattr(state, "timestamp_source", None) == "esphome_live" else "home_assistant"
        if entity_id not in platforms:
            try:
                platform = lookup(hass, entity_id) if entity_id else None
                platforms[entity_id] = platform if isinstance(platform, str) and _PLATFORM.fullmatch(platform) else None
            except Exception:
                platforms[entity_id] = None
        reason = reasons.get(source)
        details.append({"source": source, "entity_id": entity_id, "value": value,
            "unit": unit, "expected_unit": expected if expected in _UNITS else None,
            "last_reported": reported.isoformat() if reported is not None else None,
            "age_seconds": round(age, 1) if age is not None else None,
            "max_age_seconds": validation.get("age"), "valid": reason is None,
            "reason": reason, "platform": platforms[entity_id],
            "timestamp_source": timestamp_source,
            "ha_last_reported": ha_reported.isoformat() if ha_reported is not None else None,
            "ha_age_seconds": round(ha_age, 1) if ha_age is not None else None,
            "stream_samples": 2 if timestamp_source == "esphome_live" else 0})
    for source, reason in reasons.items():
        if source in checks:
            continue
        row = {"source": source, "entity_id": None, "value": None, "unit": None,
            "expected_unit": None, "last_reported": None, "age_seconds": None,
            "max_age_seconds": None, "valid": False, "reason": reason, "platform": None,
            "timestamp_source": "home_assistant", "ha_last_reported": None,
            "ha_age_seconds": None, "stream_samples": 0}
        if reason == "time_skew" and source in groups:
            reports = [_reported(lookup_state(sources.get(key))) for key in groups[source] if sources.get(key)]
            if reports and all(report is not None for report in reports):
                row["observed_time_skew_seconds"] = round(
                    max(report.timestamp() for report in reports) - min(report.timestamp() for report in reports), 1)
            row["max_time_skew_seconds"] = 10
        details.append(row)
    hints = []
    for reason in ("stale", "time_skew"):
        affected = {row["source"] for row in details if row["reason"] == reason and row["source"] in checks}
        for source, members in groups.items():
            if reasons.get(source) == reason:
                affected.update(key for key in members if key in checks)
        if not affected:
            continue
        for provider in ("esphome", "generic"):
            subset = [row["source"] for row in details if row["source"] in affected
                      and (row["platform"] == "esphome") == (provider == "esphome")]
            if not subset:
                continue
            message = ("Deye EMS odczytuje również natywne raporty ESPHome, bez zmiany firmware. Potwierdzenie wymaga dwóch poprawnych pakietów zgodnych z wartością i jednostką HA. Sprawdź połączenie źródłowe i stan odbiornika w diagnostyce. Czas odbioru pakietu nie jest czasem wykonania pomiaru Modbus."
                if provider == "esphome" else
                "Sprawdź działanie integracji źródłowej i odstęp rzeczywistego odczytu urządzenia. EMS wymaga aktualnych pomiarów; samo odświeżenie znacznika czasu nie zastępuje odczytu.")
            hints.append({"provider": provider, "reason": reason, "sources": subset, "message": message})
    return details, hints


def activation_diagnostics(details):
    """Controlled, concise reasons; never format a raw source state or attribute."""
    descriptions = []
    for row in details:
        if row["valid"]:
            continue
        source, reason = row["source"], row["reason"]
        label = f"{_LABELS[source]} ({source})" if source in _LABELS else source
        if reason == "stale" and row["age_seconds"] is not None and row["max_age_seconds"] is not None:
            text = f"odczyt sprzed {row['age_seconds']:g} s, dopuszczalne {row['max_age_seconds']:g} s"
        elif reason == "time_skew" and row.get("observed_time_skew_seconds") is not None:
            text = f"różnica czasu odczytów {row['observed_time_skew_seconds']:g} s, dopuszczalne {row['max_time_skew_seconds']:g} s"
        elif reason == "wrong_unit" and row.get("expected_unit"):
            text = f"nieprawidłowa jednostka; wymagane {row['expected_unit']}"
        else:
            text = _REASONS.get(reason, "wymaga sprawdzenia")
        descriptions.append(f"{label}: {text}")
    return "; ".join(descriptions)
