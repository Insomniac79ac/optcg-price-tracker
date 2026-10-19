"""One polite HTTP client per run: allowed hosts only, robots-gated, spaced, budgeted, stop rule."""

from __future__ import annotations

import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from source_collector_kit.etiquette import (
    MAX_JITTER_SECONDS,
    MIN_SPACING_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    stop_reason,
)
from source_collector_kit.robots import RobotsGate, RobotsRefused


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""


Transport = Callable[[str, Mapping[str, str], float], Response]


class SourceDenied(RuntimeError):
    """The stop rule fired. The source is paused until the owner decides; no retry."""

    def __init__(self, reason: str, response: Response):
        super().__init__(f"{reason} at {response.url}")
        self.reason = reason
        self.response = response


class RequestLimitReached(RuntimeError):
    """The run asked for more requests than it reserved."""


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).hostname != urlsplit(req.full_url).hostname:
            raise urllib.error.HTTPError(newurl, code, "cross-host redirect refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> Response:
    """Plain HTTP(S) GET. No cookie jar, same-host redirects only, proxies from the environment."""
    opener = urllib.request.build_opener(_SameHostRedirects())
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with opener.open(request, timeout=timeout) as reply:
            return Response(reply.geturl(), reply.status, dict(reply.headers.items()), reply.read())
    except urllib.error.HTTPError as error:
        return Response(url, error.code, dict(error.headers.items()) if error.headers else {}, error.read() or b"")


class PoliteFetcher:
    def __init__(
        self,
        *,
        user_agent: str,
        allowed_hosts: Collection[str],
        max_requests: int,
        transport: Transport = urllib_transport,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ):
        self._headers = {"User-Agent": user_agent, "Accept-Language": "ja"}
        self._hosts = frozenset(h.lower() for h in allowed_hosts)
        self._max = max_requests
        self._transport = transport
        self._clock = clock
        self._sleep = sleep
        self._jitter = jitter
        self._last: float | None = None
        self.requests_made = 0
        self.bytes_fetched = 0
        self.robots: RobotsGate | None = None

    def _wait(self) -> None:
        if self._last is None:
            return
        due = self._last + MIN_SPACING_SECONDS + self._jitter() * MAX_JITTER_SECONDS
        delay = due - self._clock()
        if delay > 0:
            self._sleep(delay)

    def _request(self, url: str) -> Response:
        host = (urlsplit(url).hostname or "").lower()
        if host not in self._hosts:
            raise ValueError(f"{host} is not an allowed host for this run")
        if self.requests_made >= self._max:
            raise RequestLimitReached(f"run reserved {self._max} requests")
        self._wait()
        self.requests_made += 1
        try:
            response = self._transport(url, self._headers, REQUEST_TIMEOUT_SECONDS)
        finally:
            self._last = self._clock()
        self.bytes_fetched += len(response.body)
        reason = stop_reason(response.status, response.body)
        if reason is not None:
            raise SourceDenied(reason, response)
        return response

    def load_robots(self, robots_url: str) -> RobotsGate:
        """Read robots.txt; must be the run's first request. Fails closed."""
        if self.requests_made:
            raise RuntimeError("robots.txt is read before any other request")
        response = self._request(robots_url)
        self.robots = RobotsGate.from_response(response.status, response.body)
        return self.robots

    def get(self, url: str) -> Response:
        if self.robots is None:
            raise RobotsRefused("robots.txt has not been read in this run")
        if not self.robots.allows(url):
            raise RobotsRefused(f"robots.txt disallows {url}")
        return self._request(url)
