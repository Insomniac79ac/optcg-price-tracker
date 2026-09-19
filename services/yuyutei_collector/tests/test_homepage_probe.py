import ast
import builtins
import io
import json
import os
import socket
import subprocess
import sys
import urllib.error
from email.message import Message
from pathlib import Path

from yuyutei_collector import homepage_probe
from yuyutei_collector.browser import HOMEPAGE_URL, warm_up_homepage


NORMAL_HTML = (
    "<html><head><title>遊々亭</title></head><body>遊々亭"
    + (" normal catalogue content" * 80)
    + "</body></html>"
).encode()


class FakeHeaders(dict):
    def get(self, key, default=None):
        key_lower = key.lower()
        for existing, value in self.items():
            if existing.lower() == key_lower:
                return value
        return default

    def get_content_charset(self):
        return "utf-8"


class FakeHttpResponse:
    def __init__(self, status, body, headers=None, url=HOMEPAGE_URL):
        self.status = status
        self.body = body
        self.headers = FakeHeaders(headers or {})
        self.url = url
        self.read_sizes = []
        self.closed = False

    def getcode(self):
        return self.status

    def geturl(self):
        return self.url

    def read(self, size):
        self.read_sizes.append(size)
        return self.body[:size]

    def close(self):
        self.closed = True


class FakeOpener:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request.full_url, request.get_method(), timeout))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class FakeNavigationResponse:
    def __init__(self, status):
        self.status = status
        self.ok = 200 <= status < 400


class FakePage:
    def __init__(self, status, html, title):
        self.status = status
        self.html = html
        self._title = title
        self.url = HOMEPAGE_URL
        self.goto_calls = []
        self.closed = False

    def goto(self, url, *, wait_until, timeout):
        self.goto_calls.append((url, wait_until, timeout))
        self.url = url
        return FakeNavigationResponse(self.status)

    def wait_for_timeout(self, milliseconds):
        assert milliseconds == 1500

    def title(self):
        return self._title

    def content(self):
        return self.html

    def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, page):
        self.page = page
        self.new_page_calls = 0
        self.closed = False

    def new_page(self):
        self.new_page_calls += 1
        return self.page

    def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, context):
        self.context = context
        self.context_kwargs = None
        self.closed = False

    def new_context(self, **kwargs):
        self.context_kwargs = kwargs
        return self.context

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, browser):
        self.browser = browser
        self.launch_calls = []

    def launch(self, **kwargs):
        self.launch_calls.append(kwargs)
        return self.browser


class FakePlaywrightManager:
    def __init__(self, chromium):
        self.playwright = type("FakePlaywright", (), {"chromium": chromium})()

    def __enter__(self):
        return self.playwright

    def __exit__(self, exc_type, exc, tb):
        return False


def playwright_fixture(status=200, html=NORMAL_HTML.decode(), title="遊々亭"):
    page = FakePage(status, html, title)
    context = FakeContext(page)
    browser = FakeBrowser(context)
    chromium = FakeChromium(browser)
    manager = FakePlaywrightManager(chromium)
    return page, context, browser, chromium, lambda: manager


def test_simple_http_200_is_classified_without_emitting_body():
    sentinel = "BODY_MUST_NOT_BE_EMITTED"
    response = FakeHttpResponse(200, NORMAL_HTML + sentinel.encode())
    opener = FakeOpener(response)

    result = homepage_probe.run_simple_http(opener=opener)

    assert result["status"] == 200
    assert result["classification"] == "normal_product"
    assert result["error"] is None
    assert len(opener.calls) == 1
    assert opener.calls[0] == (HOMEPAGE_URL, "GET", homepage_probe.HTTP_TIMEOUT_S)
    assert response.read_sizes == [homepage_probe.MAX_CLASSIFICATION_BYTES]
    assert sentinel not in json.dumps(result)
    assert "html" not in result


def test_simple_http_403_uses_the_http_error_response_once():
    headers = Message()
    headers["Content-Type"] = "text/html; charset=utf-8"
    error = urllib.error.HTTPError(
        HOMEPAGE_URL,
        403,
        "Forbidden",
        headers,
        io.BytesIO(b"<html><title>403 Forbidden</title></html>"),
    )
    opener = FakeOpener(error)

    result = homepage_probe.run_simple_http(opener=opener)

    assert len(opener.calls) == 1
    assert result["status"] == 403
    assert result["classification"] == "static_403"
    assert result["classification_evidence"] == ["http_403"]


def test_simple_http_timeout_is_bounded_and_structured():
    opener = FakeOpener(urllib.error.URLError(socket.timeout("timed out")))

    result = homepage_probe.run_simple_http(opener=opener)

    assert len(opener.calls) == 1
    assert result["status"] is None
    assert result["classification"] == "navigation_error"
    assert result["error"] == "URLError: TimeoutError"


def test_simple_http_emits_only_allowlisted_headers():
    response = FakeHttpResponse(
        200,
        NORMAL_HTML,
        {
            "Server": "edge",
            "CF-Ray": "safe-ray-id",
            "Location": "https://yuyu-tei.jp/",
            "Set-Cookie": "secret-cookie",
            "Authorization": "secret-token",
            "X-Secret": "secret-value",
        },
    )

    result = homepage_probe.run_simple_http(opener=FakeOpener(response))

    assert result["headers"] == {
        "server": "edge",
        "location": "https://yuyu-tei.jp/",
        "cf-ray": "safe-ray-id",
    }
    serialized = json.dumps(result)
    assert "secret-cookie" not in serialized
    assert "secret-token" not in serialized
    assert "secret-value" not in serialized


def test_playwright_200_uses_collector_setup_and_navigates_once():
    page, context, browser, chromium, factory = playwright_fixture()

    result = homepage_probe.run_playwright(
        playwright_factory=factory,
        homepage_runner=warm_up_homepage,
    )

    assert result["status"] == 200
    assert result["classification"] == "normal_product"
    assert result["title"] == "遊々亭"
    assert page.goto_calls == [(HOMEPAGE_URL, "domcontentloaded", 30000)]
    assert chromium.launch_calls == [
        {
            "headless": True,
            "timeout": homepage_probe.settings.BROWSER_LAUNCH_TIMEOUT_S * 1000,
        }
    ]
    assert context.new_page_calls == 1
    assert browser.context_kwargs == {}
    assert page.closed and context.closed and browser.closed


def test_playwright_static_403_navigates_once():
    page, _context, _browser, _chromium, factory = playwright_fixture(
        status=403,
        html="<html><title>403 Forbidden</title></html>",
        title="403 Forbidden",
    )

    result = homepage_probe.run_playwright(
        playwright_factory=factory,
        homepage_runner=warm_up_homepage,
    )

    assert len(page.goto_calls) == 1
    assert result["status"] == 403
    assert result["classification"] == "static_403"
    assert result["classification_evidence"] == ["http_403"]
    assert "html" not in result


def test_playwright_error_is_structured_and_not_retried():
    page, _context, _browser, _chromium, factory = playwright_fixture()
    calls = []

    def failing_runner(_page):
        calls.append(True)
        raise TimeoutError("browser deadline")

    result = homepage_probe.run_playwright(
        playwright_factory=factory,
        homepage_runner=failing_runner,
    )

    assert calls == [True]
    assert page.goto_calls == []
    assert result["status"] is None
    assert result["classification"] == "navigation_error"
    assert result["error"] == "TimeoutError"


def test_build_result_performs_no_filesystem_writes(monkeypatch):
    def forbidden_open(*args, **kwargs):
        raise AssertionError("filesystem access is forbidden")

    response = FakeHttpResponse(200, NORMAL_HTML)
    _page, _context, _browser, _chromium, factory = playwright_fixture()
    monkeypatch.setattr(builtins, "open", forbidden_open)
    result = homepage_probe.build_result(
        simple_probe=lambda: homepage_probe.run_simple_http(opener=FakeOpener(response)),
        playwright_probe=lambda: homepage_probe.run_playwright(
            playwright_factory=factory,
            homepage_runner=warm_up_homepage,
        ),
    )

    assert result["writes_possible"] is False


def test_import_boundary_excludes_write_capable_modules():
    service_root = Path(__file__).resolve().parents[1]
    script = """
import json, sys
import yuyutei_collector.homepage_probe
print(json.dumps(sorted(sys.modules)))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(service_root)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=service_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    imported = set(json.loads(completed.stdout))
    forbidden = {
        "yuyutei_collector.db",
        "yuyutei_collector.models",
        "yuyutei_collector.writer",
        "yuyutei_collector.telemetry",
        "yuyutei_collector.batch",
        "yuyutei_collector.collect",
        "yuyutei_collector.discovery",
        "yuyutei_collector.discovery_probe",
        "sqlalchemy",
        "psycopg",
        "worker",
    }
    assert forbidden.isdisjoint(imported)
    assert not any(name.startswith("yuyutei_collector.discovery") for name in imported)
    assert not any(name.startswith("worker.") for name in imported)
    assert not any(name.startswith("sqlalchemy.") for name in imported)
    assert not any(name.startswith("psycopg.") for name in imported)


def test_source_has_no_db_or_artifact_write_capability():
    source_path = Path(homepage_probe.__file__)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    forbidden_import_fragments = {
        "db",
        "models",
        "writer",
        "telemetry",
        "batch",
        "collect",
        "discovery",
        "worker",
        "sqlalchemy",
        "psycopg",
    }
    assert not any(
        fragment in module.split(".")
        for module in imported_modules
        for fragment in forbidden_import_fragments
    )
    for forbidden_call in (
        "SessionLocal",
        "create_engine",
        "RawSnapshot",
        "SourceCollectionAttempt",
        "PriceObservation",
        "write_text",
        "write_bytes",
        "screenshot",
        "tracing",
        "record_har",
        "launch_persistent_context",
    ):
        assert forbidden_call not in source


def test_main_emits_exactly_one_json_result(monkeypatch, capsys):
    simple = {
        "status": 200,
        "final_url": HOMEPAGE_URL,
        "redirect_count": 0,
        "headers": {},
        "classification": "normal_product",
        "classification_evidence": ["expected_content_present=True"],
        "error": None,
    }
    browser = {
        "status": 403,
        "final_url": HOMEPAGE_URL,
        "title": "403 Forbidden",
        "classification": "static_403",
        "classification_evidence": ["http_403"],
        "error": None,
    }
    monkeypatch.setattr(homepage_probe, "run_simple_http", lambda: simple)
    monkeypatch.setattr(homepage_probe, "run_playwright", lambda: browser)

    homepage_probe.main()

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "probe_version": 1,
        "target": "yuyutei_homepage",
        "simple_http": simple,
        "playwright": browser,
        "writes_possible": False,
    }
