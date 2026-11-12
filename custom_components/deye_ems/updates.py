"""Manual public release checks, isolated from planning and hardware control."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import re

from .const import VERSION

DATA_UPDATES = "deye_ems_updates"
API_URL = "https://api.github.com/repos/gaszu/ha-deye-ems/releases/latest"
RELEASE_ORIGIN = "https://github.com/gaszu/ha-deye-ems/releases/tag/"
MARKETPLACE_URL = "/marketplace"
COOLDOWN_SECONDS = 60
MAX_BACKOFF_SECONDS = 3600
MAX_RESPONSE_BYTES = 65536
REQUEST_TIMEOUT_SECONDS = 10
_UTC = timezone.utc
_VERSION = re.compile(r"^v?(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})$")


def _version(value):
    match = _VERSION.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError("invalid_version")
    return tuple(int(part) for part in match.groups())


def _stamp(at):
    return at.astimezone(_UTC).isoformat()


class UpdateManager:
    """One manually invoked checker per HA process; reading status performs no IO."""

    def __init__(self, hass, *, session=None, clock=None):
        self._hass = hass
        self._session = session
        self._clock = clock or (lambda: datetime.now(_UTC))
        self._task = None
        self._next_check_at = None
        self._state = {"status": "not_checked", "latest_version": None,
                       "checked_at": None, "retry_at": None, "reason": None,
                       "release_url": None, "marketplace_url": MARKETPLACE_URL,
                       "stale": False}

    @property
    def running_version(self):
        """Version imported by HA, independent of files awaiting a restart."""
        return VERSION

    @property
    def status(self):
        return deepcopy(self._state)

    def _now(self):
        at = self._clock()
        if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("invalid_clock")
        return at.astimezone(_UTC)

    async def async_check(self):
        """Join an in-flight check or reuse cooldown; never install or restart."""
        if self._task is not None and not self._task.done():
            return deepcopy(await asyncio.shield(self._task))
        now = self._now()
        if self._next_check_at is not None and now.timestamp() < self._next_check_at:
            return self.status
        self._state.update(status="checking", reason=None)
        background_task = getattr(self._hass, "async_create_background_task", None)
        self._task = (background_task(self._check(), "Deye EMS release check")
                      if callable(background_task) else asyncio.create_task(self._check()))
        return deepcopy(await asyncio.shield(self._task))

    def _finish(self, *, error=None, tag=None, backoff=COOLDOWN_SECONDS):
        at = self._now()
        delay = min(MAX_BACKOFF_SECONDS, max(COOLDOWN_SECONDS, backoff))
        self._next_check_at = at.timestamp() + delay
        self._state.update(checked_at=_stamp(at),
            retry_at=_stamp(datetime.fromtimestamp(self._next_check_at, _UTC)))
        if error is not None:
            self._state.update(status="error", reason=error,
                               stale=self._state["latest_version"] is not None)
            return self.status
        latest, running = _version(tag), _version(VERSION)
        state = "available" if latest > running else "ahead" if latest < running else "current"
        self._state.update(status=state, latest_version=".".join(map(str, latest)),
                           reason=None, release_url=RELEASE_ORIGIN + tag, stale=False)
        return self.status

    def _rate_backoff(self, headers):
        """Only bounded numeric/date values affect timing; headers are not exposed."""
        now = self._now().timestamp()
        delays = [COOLDOWN_SECONDS]
        retry = headers.get("Retry-After", "")
        try:
            delay = float(retry)
        except (ValueError, TypeError):
            try:
                date = parsedate_to_datetime(retry)
                delay = date.timestamp() - now if date.tzinfo is not None else 0
            except (ValueError, TypeError, OverflowError, AttributeError):
                delay = 0
        if math.isfinite(delay):
            delays.append(delay)
        try:
            reset = float(headers.get("X-RateLimit-Reset", "")) - now
            if math.isfinite(reset):
                delays.append(reset)
        except (ValueError, TypeError, OverflowError):
            pass
        return min(MAX_BACKOFF_SECONDS, max(delays))

    async def _check(self):
        try:
            if self._session is None:
                from homeassistant.helpers.aiohttp_client import async_get_clientsession
                session = async_get_clientsession(self._hass)
            else:
                session = self._session
            headers = {"Accept": "application/vnd.github+json",
                       "X-GitHub-Api-Version": "2026-03-10",
                       "User-Agent": f"Deye-EMS/{VERSION}"}
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                async with session.get(API_URL, headers=headers, ssl=True,
                        allow_redirects=False, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                    if response.status in (403, 429):
                        return self._finish(error="rate_limited", backoff=self._rate_backoff(response.headers))
                    if response.status != 200:
                        return self._finish(error="network" if response.status >= 500 else "invalid_response")
                    content = bytearray()
                    while True:
                        chunk = await response.content.read(min(8192, MAX_RESPONSE_BYTES + 1 - len(content)))
                        if not chunk:
                            break
                        content.extend(chunk)
                        if len(content) > MAX_RESPONSE_BYTES:
                            return self._finish(error="invalid_response")
                    try:
                        data = json.loads(content)
                        tag = data.get("tag_name") if isinstance(data, dict) else None
                        _version(tag)
                        if data.get("draft") is not False or data.get("prerelease") is not False:
                            raise ValueError("not_stable_release")
                    except (ValueError, TypeError, UnicodeError):
                        return self._finish(error="invalid_response")
                    return self._finish(tag=tag)
        except asyncio.CancelledError:
            self._state.update(status="error", reason="network",
                               stale=self._state["latest_version"] is not None)
            raise
        except Exception:
            # Provider bodies, URLs, headers and exception text never enter UI
            # state, logging, Solcast configuration or hardware diagnostics.
            return self._finish(error="network")
