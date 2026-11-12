"""Offline manual-release checks: bounded HTTP and no controller authority."""
import ast
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1] / "custom_components/deye_ems"


def load_updates(version="1.0.17"):
    tree = ast.parse((ROOT / "updates.py").read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body
                 if not isinstance(node, ast.ImportFrom) or node.level == 0]
    values = {"VERSION": version, "__name__": "offline_updates"}
    exec(compile(tree, "updates.py", "exec"), values)
    return values


class Body:
    def __init__(self, data, *, chunk_size=100000):
        self.data = data
        self.position = 0
        self.chunk_size = chunk_size
        self.requests = []

    async def read(self, count):
        self.requests.append(count)
        count = min(count, self.chunk_size)
        value = self.data[self.position:self.position+count]
        self.position += len(value)
        return value


class Response:
    def __init__(self, data=None, *, status=200, headers=None, raw=None, chunk_size=100000, event=None):
        self.status = status
        self.headers = headers or {}
        self.content = Body(raw if raw is not None else json.dumps(data).encode(), chunk_size=chunk_size)
        self.event = event
        self.closed = False

    async def __aenter__(self):
        if self.event is not None:
            await self.event.wait()
        return self

    async def __aexit__(self, *args):
        self.closed = True


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def release(tag="v1.0.18", **changes):
    return {"tag_name": tag, "draft": False, "prerelease": False, **changes}


class Updates(unittest.IsolatedAsyncioTestCase):
    def fixture(self, *responses, version="1.0.17"):
        module = load_updates(version)
        self.now = datetime(2026, 11, 12, 20, tzinfo=timezone.utc)
        session = Session(*responses)
        # Any accidental access to configuration or services is outside this
        # deliberately empty HA object; no credentials are supplied to checker.
        manager = module["UpdateManager"](object(), session=session, clock=lambda: self.now)
        return module, manager, session

    async def test_setup_and_polling_have_no_http_and_status_is_defensive(self):
        _, manager, session = self.fixture()
        self.assertEqual(manager.running_version, "1.0.17")
        for _ in range(5):
            status = manager.status
            status["latest_version"] = "999.0.0"
            status["marketplace_url"] = "https://untrusted.invalid"
        self.assertEqual(manager.status["status"], "not_checked")
        self.assertIsNone(manager.status["latest_version"])
        self.assertEqual(manager.status["marketplace_url"], "/marketplace")
        self.assertEqual(session.calls, [])

    async def test_manual_check_validates_version_order_and_builds_fixed_links(self):
        for tag, expected in (("v1.0.18", "available"), ("1.0.17", "current"),
                              ("v1.0.9", "ahead"), ("v1.0.100", "available"),
                              ("v2.0.0", "available")):
            with self.subTest(tag=tag):
                _, manager, session = self.fixture(Response(release(tag,
                    html_url="https://untrusted.invalid", body="private-provider-body")))
                status = await manager.async_check()
                self.assertEqual(status["status"], expected)
                self.assertEqual(status["latest_version"], tag.removeprefix("v"))
                self.assertEqual(status["release_url"],
                    "https://github.com/gaszu/ha-deye-ems/releases/tag/"+tag)
                self.assertFalse(status["stale"])
                self.assertEqual(len(session.calls), 1)
                self.assertNotIn("private-provider-body", json.dumps(status))

    async def test_http_has_fixed_https_target_no_redirect_or_auth_and_bounded_timeout(self):
        module, manager, session = self.fixture(Response(release()))
        await manager.async_check()
        url, options = session.calls[0]
        self.assertEqual(url, module["API_URL"])
        self.assertEqual(url, "https://api.github.com/repos/gaszu/ha-deye-ems/releases/latest")
        self.assertTrue(options["ssl"])
        self.assertFalse(options["allow_redirects"])
        self.assertLessEqual(options["timeout"], 10)
        self.assertEqual(set(options["headers"]), {"Accept", "X-GitHub-Api-Version", "User-Agent"})
        self.assertFalse(any(key in options for key in ("auth", "params", "cookies")))

    async def test_many_chunks_are_read_but_oversized_response_is_bounded_and_closed(self):
        small = Response(release(), chunk_size=3)
        module, manager, _ = self.fixture(small)
        self.assertEqual((await manager.async_check())["status"], "available")
        self.assertTrue(small.closed)
        self.assertGreater(len(small.content.requests), 3)
        large = Response(raw=b"x" * 100000, chunk_size=999999)
        _, manager, _ = self.fixture(large)
        status = await manager.async_check()
        self.assertEqual(status["reason"], "invalid_response")
        self.assertLessEqual(large.content.position, module["MAX_RESPONSE_BYTES"]+1)
        self.assertTrue(large.closed)

    async def test_malformed_unstable_or_injectable_versions_never_become_current(self):
        malformed = [[], {}, release(None), release("v1.0.17-rc1"), release("v01.0.18"),
                     release("v99999999.0.0"), release("v1.0.18\n"), release("<img src=x>"),
                     release("v1.0.18", draft=True), release("v1.0.18", prerelease=True),
                     release("v1.0.18", draft="false"), release("v1.0.18", prerelease=None)]
        for data in malformed:
            with self.subTest(data=data):
                _, manager, _ = self.fixture(Response(data))
                status = await manager.async_check()
                self.assertEqual(status["status"], "error")
                self.assertEqual(status["reason"], "invalid_response")
                self.assertIsNone(status["latest_version"])
                self.assertIsNone(status["release_url"])
        for raw in (b"not-json-private-token", b"\xff\xff", b"null"):
            _, manager, _ = self.fixture(Response(raw=raw))
            self.assertEqual((await manager.async_check())["reason"], "invalid_response")

    async def test_cooldown_and_clock_rollback_cannot_reissue_http(self):
        _, manager, session = self.fixture(Response(release()), Response(release("v1.0.19")))
        first = await manager.async_check()
        self.now += timedelta(seconds=59)
        self.assertEqual(await manager.async_check(), first)
        self.now -= timedelta(days=1)
        await manager.async_check()
        self.assertEqual(len(session.calls), 1)
        self.now += timedelta(days=1, seconds=1)
        second = await manager.async_check()
        self.assertEqual(second["latest_version"], "1.0.19")
        self.assertEqual(len(session.calls), 2)

    async def test_concurrent_checks_share_one_http_and_cancelled_caller_does_not_cancel_it(self):
        event = asyncio.Event()
        _, manager, session = self.fixture(Response(release(), event=event))
        first = asyncio.create_task(manager.async_check())
        await asyncio.sleep(0)
        second = asyncio.create_task(manager.async_check())
        await asyncio.sleep(0)
        self.assertEqual(manager.status["status"], "checking")
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        event.set()
        status = await second
        self.assertEqual(status["status"], "available")
        self.assertEqual(len(session.calls), 1)
        status["latest_version"] = "999.0.0"
        self.assertEqual(manager.status["latest_version"], "1.0.18")

    async def test_ha_lifecycle_tracks_only_the_explicit_manual_request(self):
        module = load_updates()
        tracked = []
        class Hass:
            def async_create_background_task(self, coroutine, name):
                tracked.append(name)
                return asyncio.create_task(coroutine)
        session = Session(Response(release()))
        manager = module["UpdateManager"](Hass(), session=session)
        self.assertEqual(tracked, [])
        self.assertEqual(session.calls, [])
        await manager.async_check()
        self.assertEqual(tracked, ["Deye EMS release check"])
        self.assertEqual(len(session.calls), 1)

    async def test_hanging_request_has_a_total_timeout_and_safe_error(self):
        module, manager, session = self.fixture(Response(release(), event=asyncio.Event()))
        module["REQUEST_TIMEOUT_SECONDS"] = .01
        result = await manager.async_check()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "network")
        self.assertEqual(len(session.calls), 1)
        self.assertTrue(manager._task.done())

    async def test_rate_limit_backoff_is_bounded_and_no_provider_content_is_exposed(self):
        for code, headers, delay in ((403, {"Retry-After": "120"}, 120),
                (429, {"Retry-After": "999999999"}, 3600),
                (429, {"Retry-After": "private-header"}, 60),
                (403, {"X-RateLimit-Reset": str(datetime(2026, 11, 12, 20, 5, tzinfo=timezone.utc).timestamp())}, 300),
                (429, {"Retry-After": "Thu, 12 Nov 2026 20:10:00 GMT"}, 600)):
            with self.subTest(code=code, headers=headers):
                response = Response(raw=b"private-body-token", status=code, headers=headers)
                _, manager, session = self.fixture(response)
                status = await manager.async_check()
                self.assertEqual(status["status"], "error")
                self.assertEqual(status["reason"], "rate_limited")
                self.assertEqual((datetime.fromisoformat(status["retry_at"])-self.now).total_seconds(), delay)
                self.assertNotIn("private", json.dumps(status))
                self.assertEqual(response.content.position, 0)
                await manager.async_check()
                self.assertEqual(len(session.calls), 1)

    async def test_failure_retains_last_success_as_stale_without_claiming_current(self):
        for failure in (OSError("secret-error-token"), TimeoutError("private-timeout"),
                        Response(status=500), Response(status=404), Response(status=302)):
            with self.subTest(failure=type(failure).__name__):
                _, manager, _ = self.fixture(Response(release("v1.0.17")), failure)
                self.assertEqual((await manager.async_check())["status"], "current")
                self.now += timedelta(seconds=60)
                status = await manager.async_check()
                self.assertEqual(status["status"], "error")
                self.assertEqual(status["latest_version"], "1.0.17")
                self.assertTrue(status["stale"])
                self.assertIn(status["reason"], ("network", "invalid_response"))
                self.assertNotIn("secret", json.dumps(status))
                self.assertNotIn("private", json.dumps(status))


if __name__ == "__main__":
    unittest.main()
