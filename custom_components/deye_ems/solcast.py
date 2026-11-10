"""Direct Solcast rooftop forecasts with durable, conservative request budgets.

Primary API contract: https://docs.solcast.com.au/docs/authentication and
https://docs.solcast.com.au/docs/section/rooftop-sites-hobbyist . Forecasts use
the documented HTTPS /rooftop_sites/{resource_id}/forecasts?format=json route.
The current hobbyist reference does not specify an hours query parameter, so
we retain the first72h locally instead of guessing one. Legacy site discovery
uses GET /rooftop_sites; explicitly supplied resource IDs need no discovery.

The provider's default10-call limit is per UTC day. The Warsaw calendar-day
counter is informational. We persist counters before EVERY HTTP attempt and
refuse a clock rollback. This tracks only this client, not other clients
sharing the same Solcast account. All selected sites must cover the full48h;
a missing site/period is never substituted with zero.

DI: fetch_json(url, *, headers, params) -> await {status, data, headers}.
The HA adapter must use verified TLS and disable redirects. persist(state)
must durably save the supplied JSON dict. One client instance owns one store.
Neither saved state nor returned results contain the API key/HTTP headers.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import math
import re
from zoneinfo import ZoneInfo

API_ORIGIN = "https://api.solcast.com.au"
_UTC, _WARSAW = timezone.utc, ZoneInfo("Europe/Warsaw")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_KEY = re.compile(r"^[A-Za-z0-9_-]{8,256}$")


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _time(value):
    try:
        at = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError
        return at.astimezone(_UTC)
    except (TypeError, ValueError, AttributeError):
        raise ValueError("invalid_timestamp") from None


def _config(config):
    if not isinstance(config, dict):
        raise ValueError("invalid_config")
    key = config.get("api_key", "")
    if not isinstance(key, str) or not _KEY.fullmatch(key.strip()):
        raise ValueError("api_key_missing_or_invalid")
    key = key.strip()
    ids = config.get("resource_ids", [])
    if not isinstance(ids, (list, tuple)) or len(ids) > 32 or any(
            not isinstance(i, str) or not _ID.fullmatch(i) or key in i for i in ids):
        raise ValueError("invalid_resource_ids")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate_resource_ids")
    poll, limit = config.get("poll_interval_minutes", 360), config.get("max_requests_per_day", 10)
    factor = config.get("dampening_factor", 1.0)
    if not (_number(poll) and 15 <= poll <= 1440 and _number(limit)
            and int(limit) == limit and 1 <= limit <= 1000 and _number(factor) and 0 <= factor <= 2):
        raise ValueError("invalid_poll_quota_or_dampening")
    hourly = config.get("hourly_factors")
    if hourly is None:
        hourly = [1.] * 24
    elif isinstance(hourly, dict):
        if any(str(k) not in {str(i) for i in range(24)} for k in hourly):
            raise ValueError("invalid_hourly_factors")
        hourly = [hourly.get(str(i), hourly.get(i, 1.)) for i in range(24)]
    if not isinstance(hourly, (list, tuple)) or len(hourly) != 24 or any(
            not _number(v) or not 0 <= v <= 2 for v in hourly):
        raise ValueError("invalid_hourly_factors")
    initial = config.get("initial_requests_used")
    if initial is not None and (not _number(initial) or int(initial) != initial or not 0 <= initial <= 1000):
        raise ValueError("invalid_initial_requests_used")
    return dict(api_key=key, ids=list(ids), poll=poll*60, limit=int(limit), factor=factor,
                hourly=list(hourly), initial=initial)


def validate_config(config):
    """Validate flow input without echoing a key, making requests or changing state."""
    _config(config)


def _periods(rows, *, endpoint=False):
    if not isinstance(rows, list) or not rows or len(rows) > 1000:
        raise ValueError("invalid_forecast_rows")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or endpoint and row.get("period") != "PT30M":
            raise ValueError("invalid_forecast_period")
        at = _time(row.get("period_end" if endpoint else "period_start"))
        if endpoint:
            at -= timedelta(minutes=30)
        epoch = at.timestamp()
        p10, p50 = row.get("pv_estimate10"), row.get("pv_estimate")
        if (abs(epoch/1800-round(epoch/1800)) > 1e-8 or not _number(p10)
                or not _number(p50) or not 0 <= p10 <= p50 <= 10000):
            raise ValueError("invalid_forecast_value_or_axis")
        value = dict(period_start=at.isoformat(), pv_estimate=p50, pv_estimate10=p10)
        if epoch in result and result[epoch] != value:
            raise ValueError("conflicting_forecast_period")
        result[epoch] = value
    return result


def _clean_state(raw):
    raw = raw if isinstance(raw, dict) else {}
    state = {"quota": {}, "per_site": {}, "sites": [], "sites_at": 0,
             "last_request_ts": 0, "retry_after": 0}
    for label in ("utc", "warsaw"):
        item = raw.get("quota", {}).get(label, {}) if isinstance(raw.get("quota"), dict) else {}
        if item:
            day, used = item.get("day"), item.get("used")
            valid = isinstance(day, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)) and isinstance(used, int) and not isinstance(used, bool) and 0 <= used <= 1000000
            state["quota"][label] = {"day": day, "used": used} if valid else {"day": "9999-12-31", "used": 1000000}
    for key in ("sites_at", "last_request_ts", "retry_after"):
        value = raw.get(key, 0)
        state[key] = value if _number(value) and value >= 0 else 253402300799
    for rid, item in raw.get("per_site", {}).items() if isinstance(raw.get("per_site"), dict) else ():
        try:
            if not isinstance(rid, str) or not _ID.fullmatch(rid) or not isinstance(item, dict):
                continue
            at = item.get("fetched_at")
            if not _number(at) or at < 0:
                continue
            rows = _periods(item.get("periods"))
            state["per_site"][rid] = {"fetched_at": at, "periods": list(rows.values())}
        except (ValueError, TypeError):
            continue
    for site in raw.get("sites", []) if isinstance(raw.get("sites"), list) else []:
        if isinstance(site, dict) and isinstance(site.get("resource_id"), str) and _ID.fullmatch(site["resource_id"]):
            state["sites"].append({k: deepcopy(v) for k, v in site.items()
                                   if k in ("resource_id", "name", "capacity", "capacity_dc", "tilt", "azimuth", "loss_factor")
                                   and (isinstance(v, str) or _number(v))})
    return state


class SolcastClient:
    def __init__(self, fetch_json, persist, state=None):
        self._fetch, self._persist = fetch_json, persist
        self._state = _clean_state(state)
        self._lock = asyncio.Lock()

    @property
    def state(self):
        return deepcopy(self._state)

    async def _commit(self, state):
        await self._persist(deepcopy(state))
        self._state = deepcopy(state)

    async def _initialize_quota(self, cfg, now):
        if all(label in self._state["quota"] for label in ("utc", "warsaw")):
            return True
        proposed = deepcopy(self._state)
        # Shared/migrated keys may have already spent today's allowance in
        # another integration. Unknown usage never silently starts at zero.
        used = cfg["limit"] if cfg["initial"] is None else int(cfg["initial"])
        for label, zone in (("utc", _UTC), ("warsaw", _WARSAW)):
            if label not in proposed["quota"]:
                proposed["quota"][label] = {"day": now.astimezone(zone).date().isoformat(), "used": used}
        try:
            await self._commit(proposed)
            return True
        except Exception:
            return False

    async def _cooldown(self, now, seconds=300):
        proposed = deepcopy(self._state)
        proposed["retry_after"] = max(proposed["retry_after"], now.timestamp()+seconds)
        try:
            await self._commit(proposed)
        except Exception:
            pass

    def _quota(self, cfg, now):
        result = {"limit": cfg["limit"]}
        for label, zone in (("utc", _UTC), ("warsaw", _WARSAW)):
            day = now.astimezone(zone).date().isoformat()
            item = self._state["quota"].get(label, {})
            result[label] = {"day": day, "used": item.get("used", 0) if item.get("day") == day else 0}
        return result

    async def _request(self, path, cfg, now):
        epoch = now.timestamp()
        if epoch < self._state["last_request_ts"]:
            return None, "clock_moved_backwards"
        if epoch < self._state["retry_after"]:
            return None, "retry_cooldown"
        proposed = deepcopy(self._state)
        for label, zone in (("utc", _UTC), ("warsaw", _WARSAW)):
            day = now.astimezone(zone).date().isoformat()
            old = proposed["quota"].get(label, {})
            if old and (not isinstance(old.get("day"), str) or old["day"] > day
                        or not isinstance(old.get("used"), int) or isinstance(old.get("used"), bool)
                        or old["used"] < 0):
                if label == "utc":
                    return None, "invalid_quota_state"
                old = {}  # A malformed informational counter cannot stop UTC quota.
            used = old.get("used", 0) if old.get("day") == day else 0
            if label == "utc" and used >= cfg["limit"]:
                return None, "daily_quota_exhausted"
            proposed["quota"][label] = {"day": day, "used": used+1}
        proposed["last_request_ts"] = epoch
        proposed["retry_after"] = epoch+60  # Crash/restart guard for an in-flight request.
        try:
            await self._commit(proposed)
        except Exception:
            return None, "quota_store_failed"
        status, body, headers = 0, None, {}
        try:
            response = await asyncio.wait_for(self._fetch(API_ORIGIN+path,
                headers={"Authorization": "Bearer "+cfg["api_key"], "Accept": "application/json"},
                params={"format": "json"}), timeout=30)
            status = response.get("status", 0)
            body, headers = response.get("data"), response.get("headers", {})
        except Exception:
            pass  # Never echo an exception, URL/header or response body with a credential.
        reason = "ok" if status == 200 and isinstance(body, dict) else "rate_limited" if status == 429 else "authentication_failed" if status in (401, 403) else "api_request_failed"
        retry = 0 if reason == "ok" else epoch+(3600 if status in (429, 401, 403) else 300)
        if status == 429 and isinstance(headers, dict):
            header = next((v for k, v in headers.items() if str(k).lower() == "retry-after"), None)
            try:
                wait = float(header)
                if math.isfinite(wait) and 0 <= wait <= 86400:
                    retry = max(retry, epoch+wait)
            except (ValueError, TypeError):
                try:
                    retry = max(retry, min(parsedate_to_datetime(header).timestamp(), epoch+86400))
                except (ValueError, TypeError, AttributeError):
                    pass
        updated = deepcopy(self._state)
        updated["retry_after"] = retry
        try:
            await self._commit(updated)
        except Exception:
            return None, "response_store_failed"
        return (body if reason == "ok" else None), reason

    async def async_sites(self, config, now, force=False):
        async with self._lock:
            try:
                cfg, now = _config(config), _time(now)
                if not await self._initialize_quota(cfg, now):
                    return {"status": "unavailable", "reason": "quota_store_failed", "sites": []}
                return await self._sites(cfg, now, force)
            except ValueError as error:
                return {"status": "unavailable", "reason": str(error), "sites": []}

    async def _sites(self, cfg, now, force):
        age = now.timestamp()-self._state["sites_at"]
        if self._state["sites"] and 0 <= age < 86400 and not force:
            return {"status": "cached", "reason": "sites_cache", "sites": deepcopy(self._state["sites"])}
        body, reason = await self._request("/rooftop_sites", cfg, now)
        if body is not None:
            sites, seen = [], set()
            if body.get("page_count", 1) != 1 or not isinstance(body.get("sites"), list):
                reason = "invalid_or_paginated_sites"
            else:
                for item in body["sites"]:
                    rid = item.get("resource_id") if isinstance(item, dict) else None
                    if not isinstance(rid, str) or not _ID.fullmatch(rid) or rid in seen or cfg["api_key"] in rid:
                        reason = "invalid_sites"
                        break
                    seen.add(rid)
                    site = {"resource_id": rid}
                    for key in ("name", "capacity", "capacity_dc", "tilt", "azimuth", "loss_factor"):
                        value = item.get(key)
                        if key == "name" and isinstance(value, str):
                            site[key] = value.replace(cfg["api_key"], "[redacted]")[:128]
                        elif _number(value):
                            site[key] = value
                    sites.append(site)
                else:
                    if sites:
                        candidate = deepcopy(self._state)
                        candidate.update(sites=sites, sites_at=now.timestamp())
                        try:
                            await self._commit(candidate)
                            return {"status": "ok", "reason": "sites_downloaded", "sites": deepcopy(sites)}
                        except Exception:
                            reason = "sites_store_failed"
                    else:
                        reason = "sites_missing"
        if body is not None:
            await self._cooldown(now)
        cached_sites = self._state["sites"] if 0 <= age <= 7*86400 else []
        return {"status": "cached" if cached_sites else "unavailable", "reason": reason,
                "sites": deepcopy(cached_sites)}

    def _aggregate(self, cfg, now, ids, reason, downloaded):
        start = int(now.timestamp()//1800)*1800
        per_site = []
        for rid in ids:
            cache = self._state["per_site"].get(rid, {})
            try:
                if not _number(cache.get("fetched_at")) or cache["fetched_at"] > now.timestamp():
                    raise ValueError
                per_site.append(_periods(cache.get("periods")))
            except (TypeError, ValueError):
                return {"status": "unavailable", "reason": reason if reason not in ("ok", "poll_interval") else "site_cache_missing",
                        "coverage_reason": "site_cache_missing", "periods": [], "sites": [], "quota": self._quota(cfg, now)}
        required = {start+i*1800 for i in range(96)}
        common = set.intersection(*(set(rows) for rows in per_site)) if per_site else set()
        if not required <= common:
            return {"status": "unavailable", "reason": reason if reason not in ("ok", "poll_interval") else "forecast_coverage_incomplete",
                    "coverage_reason": "forecast_coverage_incomplete", "periods": [], "sites": [], "quota": self._quota(cfg, now)}
        periods = []
        for at in sorted(t for t in common if start <= t < start+72*3600):
            factor = cfg["factor"] * cfg["hourly"][datetime.fromtimestamp(at, _WARSAW).hour]
            periods.append(dict(period_start=datetime.fromtimestamp(at, _UTC).isoformat(),
                pv_estimate=sum(rows[at]["pv_estimate"] for rows in per_site)*factor,
                pv_estimate10=sum(rows[at]["pv_estimate10"] for rows in per_site)*factor))
        known = {site["resource_id"]: site for site in self._state["sites"]}
        return {"status": "ok" if downloaded else "cached", "reason": reason,
                "source": "solcast_api" if downloaded else "solcast_dated_cache", "periods": periods,
                "sites": [deepcopy(known.get(rid, {"resource_id": rid})) for rid in ids],
                "quota": self._quota(cfg, now), "dampening_factor": cfg["factor"]}

    async def async_forecast(self, config, now, force=False):
        async with self._lock:
            try:
                cfg, now = _config(config), _time(now)
            except ValueError as error:
                return {"status": "unavailable", "reason": str(error), "periods": [], "sites": []}
            if not await self._initialize_quota(cfg, now):
                return {"status": "unavailable", "reason": "quota_store_failed", "periods": [], "sites": []}
            ids, discovery_reason = cfg["ids"], "resource_ids_missing"
            if not ids:
                discovery = await self._sites(cfg, now, False)
                ids = [site["resource_id"] for site in discovery["sites"]]
                discovery_reason = discovery["reason"]
            if not ids:
                return {"status": "unavailable", "reason": discovery_reason, "periods": [], "sites": [], "quota": self._quota(cfg, now)}
            downloaded, reason = False, "poll_interval"
            start = int(now.timestamp()//1800)*1800
            for rid in ids:
                cached = self._state["per_site"].get(rid, {})
                age = now.timestamp()-cached.get("fetched_at", 0)
                if cached and 0 <= age < cfg["poll"] and not force:
                    continue
                body, reason = await self._request("/rooftop_sites/"+rid+"/forecasts", cfg, now)
                if body is None:
                    break
                try:
                    rows = _periods(body.get("forecasts"), endpoint=True)
                    old = _periods(cached["periods"]) if cached else {}
                    rows = {**old, **rows}
                    rows = [row for at, row in sorted(rows.items()) if start <= at < start+72*3600]
                    if not rows:
                        raise ValueError
                    candidate = deepcopy(self._state)
                    candidate["per_site"][rid] = {"fetched_at": now.timestamp(), "periods": rows}
                    await self._commit(candidate)
                    downloaded = True
                except (ValueError, TypeError):
                    reason = "invalid_forecast_response"
                    await self._cooldown(now)
                    break
                except Exception:
                    reason = "forecast_store_failed"
                    break
            return self._aggregate(cfg, now, ids, reason, downloaded)
