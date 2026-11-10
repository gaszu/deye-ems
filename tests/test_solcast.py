"""Direct Solcast adapter tests using synthetic HTTP and durable-storage fakes."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "custom_components/deye_ems/solcast.py"
spec = importlib.util.spec_from_file_location("solcast_offline", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Client, validate_config = module.SolcastClient, module.validate_config
UTC = timezone.utc
SECRET = "synthetic-api-key-not-a-real-credential"
NOW = datetime.fromisoformat("2026-11-10T12:00:00+01:00")


def config(**changes):
    return {"api_key": SECRET, "resource_ids": ["roof-a"], "initial_requests_used": 0, **changes}


def forecast(now=NOW, p10=1.2, p50=2., count=150):
    start = int(now.timestamp()//1800)*1800
    return {"forecasts": [dict(period_end=datetime.fromtimestamp(start+(i+1)*1800, UTC).isoformat(),
                                 period="PT30M", pv_estimate10=p10, pv_estimate=p50,
                                 pv_estimate90=3., ignored_api_key=SECRET)
                           for i in range(count)]}


class Harness:
    def __init__(self, state=None):
        self.history, self.requests, self.responses = [], [], []
        self.fail_store, self.fail_fetch = False, False
        self.client = Client(self.fetch, self.persist, state)

    async def persist(self, state):
        if self.fail_store:
            raise OSError("synthetic persistence error")
        json.dumps(state, allow_nan=False)
        self.history.append(deepcopy(state))

    async def fetch(self, url, *, headers, params):
        # Check the budget was durable BEFORE the transport was invoked.
        assert self.history and self.history[-1]["last_request_ts"] > 0
        assert self.history[-1]["quota"]["utc"]["used"] >= 1
        self.requests.append((url, deepcopy(headers), deepcopy(params)))
        if self.fail_fetch:
            raise RuntimeError("transport exception accidentally echoing "+SECRET)
        if self.responses:
            return deepcopy(self.responses.pop(0))
        if url.endswith("/rooftop_sites"):
            return dict(status=200, headers={}, data={"sites": [
                {"resource_id": "roof-a", "name": "Synthetic roof A", "capacity": 5,
                 "capacity_dc": 6, "api_key": SECRET},
                {"resource_id": "roof-b", "name": "Synthetic roof B", "capacity": 3,
                 "capacity_dc": 4, "api_key": SECRET}], "page_count": 1})
        return dict(status=200, headers={}, data=forecast())


class SolcastTests(unittest.IsolatedAsyncioTestCase):
    async def test_documented_forecast_route_header_and_local_72h_window(self):
        h = Harness()
        result = await h.client.async_forecast(config(), NOW)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["periods"]), 144)
        url, headers, params = h.requests[0]
        self.assertEqual(url, "https://api.solcast.com.au/rooftop_sites/roof-a/forecasts")
        self.assertEqual(headers["Authorization"], "Bearer "+SECRET)
        self.assertEqual(params, {"format": "json"})
        self.assertNotIn(SECRET, url)
        self.assertEqual(result["periods"][0]["pv_estimate"], 2.)
        self.assertEqual(result["periods"][0]["pv_estimate10"], 1.2)

    async def test_explicit_resource_ids_do_not_spend_discovery_request(self):
        h = Harness()
        await h.client.async_forecast(config(), NOW)
        self.assertEqual(len(h.requests), 1)

    async def test_auto_discovery_and_all_sites_aggregate_without_capacity_scaling(self):
        h = Harness()
        cfg = config(); cfg["resource_ids"] = []
        result = await h.client.async_forecast(cfg, NOW)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(h.requests), 3)
        self.assertEqual(result["periods"][0]["pv_estimate"], 4.)
        self.assertEqual(result["periods"][0]["pv_estimate10"], 2.4)
        self.assertEqual(sum(s["capacity_dc"] for s in result["sites"]), 10)
        later = await h.client.async_forecast(cfg, NOW+timedelta(hours=1))
        self.assertEqual(later["status"], "cached")
        self.assertEqual(len(h.requests), 3)

    async def test_excluded_site_is_neither_requested_nor_summed_for_explicit_or_discovered_ids(self):
        for selected in (["roof-a", "roof-b"], []):
            with self.subTest(selected=selected):
                h = Harness()
                result = await h.client.async_forecast(config(resource_ids=selected,
                                                exclude_sites=["roof-b"]), NOW)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["periods"][0]["pv_estimate"], 2.)
                self.assertEqual([site["resource_id"] for site in result["sites"]], ["roof-a"])
                self.assertFalse(any("/roof-b/forecasts" in request[0] for request in h.requests))
                self.assertEqual(len(h.requests), 1 if selected else 2)

    async def test_all_explicit_sites_excluded_returns_unavailable_without_http(self):
        h = Harness()
        result = await h.client.async_forecast(config(exclude_sites=["roof-a"]), NOW)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "all_sites_excluded")
        self.assertEqual(result["periods"], [])
        self.assertEqual(h.requests, [])

    async def test_missing_selected_site_or_period_never_becomes_zero(self):
        h = Harness()
        h.responses = [dict(status=200, headers={}, data=forecast()),
                       dict(status=429, headers={}, data={"error": SECRET})]
        cfg = config(); cfg["resource_ids"] = ["roof-a", "roof-b"]
        result = await h.client.async_forecast(cfg, NOW)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["periods"], [])
        h = Harness()
        broken = forecast(); del broken["forecasts"][20]
        h.responses = [dict(status=200, data=broken, headers={})]
        result = await h.client.async_forecast(config(), NOW)
        self.assertEqual(result["reason"], "forecast_coverage_incomplete")
        self.assertEqual(result["periods"], [])

    async def test_missing_p10_rejects_response_and_applies_cooldown(self):
        h = Harness()
        broken = forecast(); del broken["forecasts"][0]["pv_estimate10"]
        h.responses = [dict(status=200, data=broken, headers={})]
        first = await h.client.async_forecast(config(), NOW)
        self.assertEqual(first["status"], "unavailable")
        await h.client.async_forecast(config(), NOW+timedelta(seconds=10), force=True)
        self.assertEqual(len(h.requests), 1)

    async def test_cache_is_dated_and_restart_does_not_duplicate_calls(self):
        h = Harness()
        await h.client.async_forecast(config(), NOW)
        restarted = Harness(h.client.state)
        result = await restarted.client.async_forecast(config(), NOW+timedelta(hours=1))
        self.assertEqual(result["status"], "cached")
        self.assertEqual(len(restarted.requests), 0)
        self.assertEqual(result["quota"]["utc"]["used"], 1)

    async def test_default_dampening_preserves_optimized_site_one_to_one(self):
        h = Harness()
        original = await h.client.async_forecast(config(), NOW)
        identity = await h.client.async_forecast(config(dampening_factor=1.), NOW)
        self.assertEqual(identity["periods"], original["periods"])
        adjusted = await h.client.async_forecast(config(dampening_factor=.8), NOW)
        again = await h.client.async_forecast(config(dampening_factor=.8), NOW)
        self.assertEqual(adjusted["periods"], again["periods"])
        self.assertAlmostEqual(adjusted["periods"][0]["pv_estimate"], 1.6)
        self.assertEqual(len(h.requests), 1)

    async def test_hourly_dampening_uses_warsaw_period_start(self):
        h = Harness()
        factors = [1.] * 24; factors[12] = .5
        result = await h.client.async_forecast(config(hourly_factors=factors), NOW)
        self.assertEqual(result["periods"][0]["pv_estimate"], 1.)
        self.assertEqual(result["periods"][2]["pv_estimate"], 2.)

    async def test_half_hourly_dampening_distinguishes_both_halves_of_one_hour(self):
        h = Harness()
        factors = [1.] * 48
        factors[24], factors[25] = .2, .8  # 12:00 and 12:30 Europe/Warsaw.
        result = await h.client.async_forecast(config(half_hourly_factors=factors), NOW)
        self.assertAlmostEqual(result["periods"][0]["pv_estimate"], .4)
        self.assertAlmostEqual(result["periods"][1]["pv_estimate"], 1.6)
        self.assertAlmostEqual(result["periods"][2]["pv_estimate"], 2.)
        self.assertAlmostEqual(result["periods"][0]["pv_estimate10"], .24)

    async def test_per_site_correction_precedes_aggregation_and_global_corrections(self):
        h = Harness()
        h.responses = [dict(status=200, headers={}, data=forecast(p50=2., p10=1.2)),
                       dict(status=200, headers={}, data=forecast(p50=4., p10=2.4))]
        a, b, half, hourly = [1.]*48, [1.]*48, [1.]*48, [1.]*24
        a[24], b[24], a[25], b[25] = .5, 1.5, 1., .5
        half[24], hourly[12] = .25, .5
        cfg = config(resource_ids=["roof-a", "roof-b"], dampening_factor=.8,
                     hourly_factors=hourly, half_hourly_factors=half,
                     site_factors={"roof-a": a, "roof-b": b})
        result = await h.client.async_forecast(cfg, NOW)
        # First half: (2*.5 + 4*1.5) * .8 * .5 * .25 = .7 kW.
        self.assertAlmostEqual(result["periods"][0]["pv_estimate"], .7)
        self.assertAlmostEqual(result["periods"][0]["pv_estimate10"], .42)
        # Second half: (2*1 + 4*.5) * .8 * .5 * 1 = 1.6 kW.
        self.assertAlmostEqual(result["periods"][1]["pv_estimate"], 1.6)
        self.assertAlmostEqual(result["periods"][1]["pv_estimate10"], .96)

    async def test_cached_raw_forecast_is_not_dampened_twice(self):
        h = Harness()
        original = await h.client.async_forecast(config(), NOW)
        raw = h.client.state["per_site"]
        half, site = [.5]*48, [.8]*48
        cfg = config(half_hourly_factors=half, site_factors={"roof-a": site})
        adjusted = await h.client.async_forecast(cfg, NOW)
        repeated = await h.client.async_forecast(cfg, NOW)
        self.assertEqual(adjusted["periods"], repeated["periods"])
        self.assertAlmostEqual(adjusted["periods"][0]["pv_estimate"], .8)
        self.assertEqual(h.client.state["per_site"], raw)
        self.assertEqual(len(h.requests), 1)
        identity = await h.client.async_forecast(config(half_hourly_factors=[1.]*48,
                                      site_factors={"roof-a": [1.]*48}), NOW)
        self.assertEqual(identity["periods"], original["periods"])

    async def test_repeated_dst_hour_uses_the_same_local_half_hour_factors(self):
        at = datetime.fromisoformat("2026-10-25T02:00:00+02:00")
        h = Harness()
        h.responses = [dict(status=200, headers={}, data=forecast(at))]
        half = [1.]*48
        half[4], half[5] = .4, .6
        result = await h.client.async_forecast(config(half_hourly_factors=half), at)
        self.assertEqual([round(row["pv_estimate"], 5) for row in result["periods"][:4]],
                         [.8, 1.2, .8, 1.2])

    async def test_unselected_site_factors_are_unused_but_invalid_ids_are_rejected(self):
        h = Harness()
        result = await h.client.async_forecast(config(site_factors={"other-roof": [0.]*48}), NOW)
        self.assertEqual(result["periods"][0]["pv_estimate"], 2.)
        for rid in ("../roof", "https://example.invalid/roof", SECRET):
            h = Harness()
            result = await h.client.async_forecast(config(site_factors={rid: [1.]*48}), NOW)
            self.assertEqual(result["reason"], "invalid_site_factor_resource_id")
            self.assertEqual(h.requests, [])

    def test_invalid_half_hourly_and_site_factors_are_refused_offline(self):
        for factors in ([1.]*47, [1.]*49, [True]*48, [float("nan")]*48, [-.1]*48, [2.1]*48):
            with self.subTest(factors=factors[:1], length=len(factors)):
                with self.assertRaisesRegex(ValueError, "invalid_half_hourly_factors"):
                    validate_config(config(half_hourly_factors=factors))
                with self.assertRaisesRegex(ValueError, "invalid_site_half_hourly_factors"):
                    validate_config(config(site_factors={"roof-a": factors}))
        with self.assertRaisesRegex(ValueError, "invalid_site_factors"):
            validate_config(config(site_factors=[]))

    async def test_failures_and_429_spend_budget_before_transport_and_never_retry_early(self):
        h = Harness()
        h.responses = [dict(status=429, data={"message": SECRET}, headers={"Retry-After": "7200"})]
        first = await h.client.async_forecast(config(), NOW)
        self.assertEqual(first["quota"]["utc"]["used"], 1)
        await h.client.async_forecast(config(), NOW+timedelta(minutes=30), force=True)
        self.assertEqual(len(h.requests), 1)
        self.assertGreaterEqual(h.client.state["retry_after"], NOW.timestamp()+7200)
        self.assertNotIn(SECRET, json.dumps(first))

    async def test_valid_cache_survives_provider_error_without_new_zero_forecast(self):
        h = Harness()
        initial = await h.client.async_forecast(config(), NOW)
        h.responses = [dict(status=500, data={"message": SECRET}, headers={})]
        result = await h.client.async_forecast(config(), NOW, force=True)
        self.assertEqual(result["status"], "cached")
        self.assertEqual(result["periods"], initial["periods"])
        self.assertEqual(result["quota"]["utc"]["used"], 2)

    async def test_storage_failure_prevents_any_http_attempt(self):
        h = Harness(); h.fail_store = True
        result = await h.client.async_forecast(config(), NOW)
        self.assertEqual(result["reason"], "quota_store_failed")
        self.assertEqual(h.requests, [])

    async def test_default_unknown_initial_usage_blocks_first_day_safely(self):
        h = Harness()
        cfg = config(); del cfg["initial_requests_used"]
        result = await h.client.async_forecast(cfg, NOW)
        self.assertEqual(h.requests, [])
        self.assertEqual(result["quota"]["utc"]["used"], 10)
        self.assertEqual(result["quota"]["warsaw"]["used"], 10)
        self.assertEqual(result["reason"], "daily_quota_exhausted")
        next_day = NOW+timedelta(days=1)
        h.responses = [dict(status=200, data=forecast(next_day), headers={})]
        self.assertEqual((await h.client.async_forecast(cfg, next_day))["status"], "ok")

    async def test_initial_discovery_reports_authentication_or_quota_cause(self):
        h = Harness()
        cfg = config(); cfg["resource_ids"] = []
        h.responses = [dict(status=401, data={"message": SECRET}, headers={})]
        denied = await h.client.async_forecast(cfg, NOW)
        self.assertEqual(denied["reason"], "authentication_failed")
        self.assertNotIn(SECRET, json.dumps(denied))
        h = Harness(); cfg.pop("initial_requests_used")
        blocked = await h.client.async_forecast(cfg, NOW)
        self.assertEqual(blocked["reason"], "daily_quota_exhausted")
        self.assertEqual(h.requests, [])

    async def test_force_and_config_changes_cannot_reset_existing_daily_budget(self):
        h = Harness()
        cfg = config(max_requests_per_day=1)
        await h.client.async_forecast(cfg, NOW)
        cfg["initial_requests_used"] = 0
        cfg["config_generation"] = "new-user-config-generation"
        result = await h.client.async_forecast(cfg, NOW, force=True)
        self.assertEqual(result["status"], "cached")
        self.assertEqual(len(h.requests), 1)
        self.assertEqual(result["quota"]["utc"]["used"], 1)

    async def test_warsaw_midnight_does_not_reset_provider_utc_allowance(self):
        at = datetime.fromisoformat("2026-11-10T23:50:00+01:00")
        h = Harness()
        h.responses = [dict(status=500, data={}, headers={})]
        cfg = config(max_requests_per_day=1)
        await h.client.async_forecast(cfg, at)
        await h.client.async_forecast(cfg, at+timedelta(minutes=30), force=True)
        self.assertEqual(len(h.requests), 1)
        await h.client.async_forecast(cfg, at+timedelta(hours=2), force=True)
        self.assertEqual(len(h.requests), 2)

    async def test_unknown_initial_usage_waits_for_utc_midnight_not_next_warsaw_day(self):
        at = datetime.fromisoformat("2026-11-10T00:30:00+01:00")
        h = Harness()
        cfg = config(); cfg.pop("initial_requests_used")
        blocked = await h.client.async_forecast(cfg, at)
        self.assertEqual(blocked["reason"], "daily_quota_exhausted")
        self.assertEqual(h.requests, [])
        later = at+timedelta(minutes=31)
        h.responses = [dict(status=200, data=forecast(later), headers={})]
        resumed = await h.client.async_forecast(cfg, later)
        self.assertEqual(resumed["status"], "ok")
        self.assertEqual(resumed["quota"]["utc"]["used"], 1)
        self.assertEqual(resumed["quota"]["warsaw"]["used"], 11)
        self.assertEqual(len(h.requests), 1)

    async def test_clock_rollback_never_resets_or_reuses_budget(self):
        h = Harness()
        await h.client.async_forecast(config(), NOW)
        await h.client.async_forecast(config(), NOW-timedelta(days=1), force=True)
        self.assertEqual(len(h.requests), 1)

    async def test_api_key_and_echoed_credentials_are_absent_from_results_and_state(self):
        h = Harness()
        cfg = config(); cfg["resource_ids"] = []
        result = await h.client.async_forecast(cfg, NOW)
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn(SECRET, json.dumps(h.client.state))
        h = Harness(); h.fail_fetch = True
        result = await h.client.async_forecast(config(), NOW)
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn(SECRET, json.dumps(h.client.state))

    async def test_invalid_identifiers_never_change_host_or_put_a_key_in_path(self):
        for ids in (["https://attacker.invalid/x"], ["../secret"], ["roof?api_key=x"], [SECRET]):
            h = Harness(); cfg = config(); cfg["resource_ids"] = ids
            result = await h.client.async_forecast(cfg, NOW)
            self.assertEqual(result["reason"], "invalid_resource_ids")
            self.assertEqual(h.requests, [])

    async def test_sites_cache_and_json_snapshots_are_detached_from_caller_mutation(self):
        h = Harness()
        result = await h.client.async_sites(config(), NOW)
        result["sites"][0]["name"] = "changed"
        snapshot = h.client.state; snapshot["sites"][0]["name"] = "changed again"
        second = await h.client.async_sites(config(), NOW)
        self.assertEqual(second["sites"][0]["name"], "Synthetic roof A")
        self.assertEqual(len(h.requests), 1)

    async def test_concurrent_updates_share_one_budget_and_cache(self):
        h = Harness()
        results = await asyncio.gather(*(h.client.async_forecast(config(), NOW) for _ in range(6)))
        self.assertTrue(all(r["status"] in ("ok", "cached") for r in results))
        self.assertEqual(len(h.requests), 1)

    def test_flow_validation_is_offline_and_does_not_echo_a_secret(self):
        self.assertIsNone(validate_config(config()))
        with self.assertRaisesRegex(ValueError, "invalid_hourly_factors"):
            validate_config(config(hourly_factors=[1, 2]))
        with self.assertRaisesRegex(ValueError, "invalid_exclude_sites"):
            validate_config(config(exclude_sites=["../roof"]))
        with self.assertRaises(ValueError) as error:
            validate_config(config(api_key="bad\nheader"))
        self.assertNotIn(SECRET, str(error.exception))


if __name__ == "__main__":
    unittest.main()
