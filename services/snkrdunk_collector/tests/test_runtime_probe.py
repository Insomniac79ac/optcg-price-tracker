"""Proves runtime_probe does no network, DB, or source work - local only,
network access is actively blocked (not just unused) while it runs."""

import socket

import pytest

from snkrdunk_collector import runtime_probe


def _blocked_socket(*args, **kwargs):
    raise AssertionError("runtime_probe attempted to open a socket")


def test_no_network_or_collector_imports_in_module():
    forbidden = ("browser", "collect", "db", "writer", "extractor", "playwright", "socket", "requests", "httpx", "urllib")
    with open(runtime_probe.__file__) as f:
        import_lines = [
            line.strip()
            for line in f
            if line.strip().startswith("import ") or line.strip().startswith("from ")
        ]
    for line in import_lines:
        module = line.split()[1].split(".")[0]
        assert module not in forbidden, f"forbidden import: {line}"


def test_main_prints_expected_sequence_with_no_network_access(monkeypatch, capsys):
    monkeypatch.setattr(socket, "socket", _blocked_socket)
    monkeypatch.setattr(runtime_probe.time, "sleep", lambda seconds: None)

    exit_code = runtime_probe.main()

    assert exit_code == 0
    captured = capsys.readouterr()
    stdout_lines = captured.out.splitlines()
    assert stdout_lines[0] == "RUNTIME_PROBE_START"
    assert stdout_lines[1].startswith("pid=")
    assert stdout_lines[-1] == "RUNTIME_PROBE_END"
    assert captured.err.strip() == "RUNTIME_PROBE_STDERR"


def test_main_does_not_touch_environment_or_credentials(monkeypatch, capsys):
    monkeypatch.setattr(runtime_probe.time, "sleep", lambda seconds: None)
    monkeypatch.setenv("DATABASE_URL", "postgres://should-not-be-read")

    runtime_probe.main()

    captured = capsys.readouterr()
    assert "postgres://" not in captured.out
    assert "DATABASE_URL" not in captured.out
