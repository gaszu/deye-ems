"""Pure import of an existing Solcast configuration and calibration snapshot.

The caller binds the source integration's ``dampen`` entity in the entity
registry and supplies only its current attributes. No files, HA services or
HTTP are used here. The live sensor's ``factors`` is a GLOBAL 48 point table:
``[{"interval": "00:00", "factor": 1.0}, ..., {"interval": "23:30", ...}]``.

Canonical scalar, 24/48 value lists, clock-keyed maps and per-site maps are
also accepted. An ALL/global table overrides site tables instead of being
multiplied by them. Missing factors are errors; a real zero remains zero.
The resulting corrections apply ONLY to raw Solcast API forecasts. Existing
HA detailedForecast values have already been calibrated and must not receive
these factors again. This imports coefficients, not the learning algorithm.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import math
import re

_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_KEY = re.compile(r"^[A-Za-z0-9_-]{8,256}$")
_CLOCK = re.compile(r"^(?:[01][0-9]|2[0-3]):(?:00|30)$")
_BOOL_OPTIONS = ("auto_dampen", "site_damp", "get_actuals")
_ADV_BOOL = (
    "automated_dampening_adaptive_model_configuration",
    "automated_dampening_elevation_adjustment", "automated_dampening_no_delta_adjustment",
    "automated_dampening_no_limiting_consistency", "automated_dampening_preserve_unmatched_factors",
    "granular_dampening_delta_adjustment",
)
_ADV_NUMBER = (
    "automated_dampening_adaptive_model_minimum_history_days",
    "automated_dampening_adaptive_model_switch_margin", "automated_dampening_delta_adjustment_model",
    "automated_dampening_generation_fetch_delay", "automated_dampening_generation_history_load_days",
    "automated_dampening_insignificant_factor", "automated_dampening_insignificant_factor_adjusted",
    "automated_dampening_minimum_matching_generation", "automated_dampening_minimum_matching_intervals",
    "automated_dampening_model", "automated_dampening_model_days", "automated_dampening_similar_peak",
)
_ADV_LIST = ("automated_dampening_adaptive_model_exclude", "automated_dampening_ignore_intervals")
_SUPPRESSION = "automated_dampening_suppression_entity"


def _number(value, code, low=0, high=2):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(code)
    if isinstance(value, str) and len(value) > 32:
        raise ValueError(code)
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(code) from None
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(code)
    return result


def _boolean(value):
    if isinstance(value, bool):
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    raise ValueError("invalid_source_boolean")


def _curve(raw):
    if isinstance(raw, (int, float, str)) and not isinstance(raw, bool):
        return [_number(raw, "invalid_calibration_factor")] * 48
    if isinstance(raw, dict):
        if len(raw) not in (24, 48) or not all(isinstance(k, str) and _CLOCK.fullmatch(k) for k in raw):
            raise ValueError("incomplete_calibration_intervals")
        raw = [{"interval": k, "factor": v} for k, v in raw.items()]
    if not isinstance(raw, (list, tuple)) or len(raw) not in (24, 48):
        raise ValueError("incomplete_calibration_factors")
    if any(isinstance(item, dict) for item in raw):
        points = {}
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("mixed_calibration_format")
            interval = item.get("interval")
            if not isinstance(interval, str) or not _CLOCK.fullmatch(interval) or interval in points:
                raise ValueError("invalid_or_duplicate_calibration_interval")
            points[interval] = _number(item.get("factor"), "invalid_calibration_factor")
        expected = [f"{hour:02}:{minute:02}" for hour in range(24)
                    for minute in ((0,) if len(raw) == 24 else (0, 30))]
        if set(points) != set(expected):
            raise ValueError("incomplete_calibration_intervals")
        values = [points[key] for key in expected]
    else:
        values = [_number(value, "invalid_calibration_factor") for value in raw]
    return [value for value in values for _ in range(2)] if len(values) == 24 else values


def _ids(raw, key):
    if not isinstance(raw, (list, tuple)) or len(raw) > 32:
        raise ValueError("invalid_site_selection")
    result = []
    for value in raw:
        if not isinstance(value, str) or not _ID.fullmatch(value) or key in value or value in result:
            raise ValueError("invalid_site_selection")
        result.append(value)
    return result


def _metadata(options, attrs, key):
    public, private, warnings = {}, {}, []
    for name in _BOOL_OPTIONS:
        if name in options:
            public[name] = _boolean(options[name])
    for name in ("auto_update", "use_actuals"):
        if name in options:
            value = _number(options[name], "invalid_source_option", 0, 2)
            if int(value) != value:
                raise ValueError("invalid_source_option")
            public[name] = int(value)
    if "key_estimate" in options:
        if options["key_estimate"] not in ("estimate", "estimate10", "estimate90"):
            raise ValueError("invalid_source_option")
        public["key_estimate"] = options["key_estimate"]
    if "integration_automated" in attrs:
        public["integration_automated"] = _boolean(attrs["integration_automated"])
    for name in _ADV_BOOL + _ADV_NUMBER:
        if name not in attrs:
            continue
        try:
            value = _boolean(attrs[name]) if name in _ADV_BOOL else _number(
                attrs[name], "invalid_advanced_metadata", -1000000, 1000000)
            private[name] = public[name] = value
        except ValueError:
            warnings.append("advanced_metadata_omitted")
    for name in _ADV_LIST:
        value = attrs.get(name)
        if value is None:
            continue
        if (not isinstance(value, list) or len(value) > 256 or any(
                not isinstance(item, (str, int, float, bool)) or
                isinstance(item, str) and (len(item) > 128 or key in item) or
                isinstance(item, float) and not math.isfinite(item) for item in value)):
            warnings.append("advanced_metadata_omitted")
            continue
        private[name] = deepcopy(value)
        public[name+"_count"] = len(value)
    suppression = attrs.get(_SUPPRESSION)
    if suppression:
        if (isinstance(suppression, str) and len(suppression) <= 255 and key not in suppression and
                re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z0-9_]+", suppression)):
            private[_SUPPRESSION] = suppression
        warnings.append("source_suppression_not_implemented")
        public["suppression_configured"] = True
    return public, private, sorted(set(warnings))


def import_existing_options(source_options, calibration_attributes=None):
    """Return ``{'config': private_draft, 'report': sanitized_report}``.

    ``ValueError`` messages are fixed codes and never echo input or secrets.
    A caller must assign a new config_generation only when the operator saves
    this draft. API usage is unknown, so its initial usage is set to the full
    imported daily limit. No installed PV power or location is inferred.
    """
    if not isinstance(source_options, dict) or len(source_options) > 256:
        raise ValueError("invalid_source_options")
    attrs = {} if calibration_attributes is None else calibration_attributes
    if not isinstance(attrs, dict) or len(attrs) > 128:
        raise ValueError("invalid_calibration_attributes")
    key = source_options.get("api_key")
    if not isinstance(key, str) or not _KEY.fullmatch(key.strip()):
        raise ValueError("api_key_missing_or_invalid")
    key = key.strip()
    public, private, warnings = _metadata(source_options, attrs, key)
    adaptive = any(public.get(name) is True for name in ("auto_dampen", "site_damp", "integration_automated"))
    globals_, site_raw = [], {}

    def site_bundle(mapping):
        if not isinstance(mapping, dict) or len(mapping) > 33:
            raise ValueError("invalid_site_calibration")
        for site, curve in mapping.items():
            if site == "ALL":
                globals_.append(_curve(curve))
            elif not isinstance(site, str) or not _ID.fullmatch(site) or key in site or site in site_raw:
                raise ValueError("invalid_site_calibration")
            else:
                site_raw[site] = curve

    if "factors" in attrs:
        raw = attrs["factors"]
        if isinstance(raw, dict) and not all(isinstance(k, str) and _CLOCK.fullmatch(k) for k in raw):
            site_bundle(raw)
        else:
            globals_.append(_curve(raw))
    for name in ("ALL", "global_factors", "half_hourly_factors", "hourly_factors", "dampening_factor"):
        if name in attrs:
            globals_.append(_curve(attrs[name]))
    if "site_factors" in attrs:
        site_bundle(attrs["site_factors"])
    from_sensor = bool(globals_ or site_raw)
    if not from_sensor:
        if adaptive:
            raise ValueError("adaptive_calibration_snapshot_missing")
        for name in ("half_hourly_factors", "hourly_factors", "dampening_factor"):
            if name in source_options:
                globals_.append(_curve(source_options[name]))
        fixed = [f"damp{hour:02}" for hour in range(24)]
        if any(name in source_options for name in fixed):
            if not all(name in source_options for name in fixed):
                raise ValueError("incomplete_fixed_calibration")
            globals_.append(_curve([source_options[name] for name in fixed]))
    if not globals_ and not site_raw:
        raise ValueError("calibration_snapshot_missing")
    if globals_ and any(curve != globals_[0] for curve in globals_[1:]):
        raise ValueError("conflicting_global_calibration")
    sites = {site: _curve(curve) for site, curve in site_raw.items()}
    ignored = len(sites) if globals_ else 0
    if globals_:
        sites = {}  # The source ALL table overrides, it is not a multiplier.
    global_curve = globals_[0] if globals_ else [1.] * 48
    limit_key = "api_limit" if "api_limit" in source_options else "api_quota" if "api_quota" in source_options else None
    limit = _number(source_options[limit_key], "invalid_api_limit", 1, 1000) if limit_key else 10
    if int(limit) != limit:
        raise ValueError("invalid_api_limit")
    excluded_raw = source_options.get("exclude_sites", source_options.get("excluded_sites", []))
    excluded = _ids(excluded_raw, key)
    selected = _ids(source_options.get("resource_ids", []), key)
    if adaptive:
        warnings.append("automatic_learning_not_migrated")
    report = {"calibration_imported": True,
        "needs_manual_review": adaptive or "source_suppression_not_implemented" in warnings,
        "calibration_kind": "global_snapshot" if from_sensor and globals_ else "per_site_snapshot" if from_sensor else "fixed_options",
        "snapshot_only": True, "global_override": bool(globals_ and ignored),
        "global_factor_count": 48 if globals_ else 0, "site_factor_count": len(sites),
        "ignored_site_factor_count": ignored, "api_limit_imported": limit_key is not None,
        "excluded_sites_count": len(excluded), "quota_usage_known": False,
        "source_options": public, "warnings": sorted(set(warnings)),
        "corrections_apply_to": "raw_solcast_api_only", "ha_forecast_already_calibrated": True}
    stamp = attrs.get("last_updated")
    if isinstance(stamp, str) and len(stamp) <= 64:
        try:
            value = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if value.tzinfo is not None and value.utcoffset() is not None:
                report["calibration_updated_at"] = value.isoformat()
        except ValueError:
            pass
    config = {"api_key": key, "enabled": True, "resource_ids": selected, "exclude_sites": excluded,
        "poll_interval_minutes": 360, "max_requests_per_day": int(limit), "initial_requests_used": int(limit),
        "dampening_factor": 1., "hourly_factors": [1.] * 24,
        "half_hourly_factors": global_curve, "site_factors": sites}
    if private:
        config["import_metadata"] = private
    return {"config": config, "report": report}
