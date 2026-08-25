"""4D-1C: the Railway tunnel's stdout pipe is drained, so it cannot block.

THE BUG THIS CLOSES. `open_tunnel` returns the moment it has parsed the `URL:`
line, but the tunnel process keeps running and keeps writing. Nothing read the
far end of that pipe. Linux gives a pipe about 64 KiB of buffer; once a chatty
`railway connect` filled it, its next write would BLOCK - and a blocked tunnel
stops forwarding. An import that had already passed every fingerprint would
stall mid-run instead of failing cleanly.

WHY THESE TESTS USE A REAL CHILD PROCESS. A mocked `Popen` cannot exhibit this
at all: the bug lives in the OS pipe, not in Python. So the fake Railway here
is a genuine `python` subprocess writing genuine bytes through a genuine pipe,
and the proof that it is not blocked is that it reaches a line of its own code
AFTER the high-volume write and records that fact in a file the test reads.
If the drain stopped working, that file would never appear.

No Railway access, no network, no canonical staging.
"""

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from app.services import canonical_staging_target as T
from tests._repo_root import find_repo_root

REPO_ROOT = find_repo_root()
pytestmark = pytest.mark.skipif(
    REPO_ROOT is None, reason="repo root not visible from this environment"
)

SECRET = "SUPERSECRET"
TUNNEL_URL = f"postgresql://railwayuser:{SECRET}@127.0.0.1:54321/railway"

# Comfortably beyond a Linux pipe buffer (~64 KiB), so a run that is not
# draining is guaranteed to wedge rather than merely be lucky.
FLOOD_BYTES = 512 * 1024
PIPE_BUFFER_HINT = 64 * 1024


@pytest.fixture
def checker():
    return T.load_staging_checker()


def _fake_railway(
    tmp_path: Path,
    *,
    flood: int = 0,
    emit_url: bool = True,
    exit_immediately: bool = False,
) -> tuple[Path, Path]:
    """Writes a fake `railway connect` and returns (script, marker).

    The marker file is the whole point: the child touches it only AFTER it has
    finished writing `flood` bytes to stdout. A child blocked on a full pipe
    never gets there.
    """
    marker = tmp_path / "flood_complete.marker"
    url_line = f"URL: {TUNNEL_URL}\n" if emit_url else f"NOTURL: {TUNNEL_URL}\n"
    script = tmp_path / "fake_railway_tunnel.py"
    script.write_text(
        "import sys, time\n"
        # the credential-bearing preamble a real CLI prints
        "sys.stderr.write('  Password: " + SECRET + "\\n')\n"
        "sys.stderr.flush()\n"
        "sys.stdout.write('Connecting to Postgres on environment staging...\\n')\n"
        "sys.stdout.write('Connection string: " + TUNNEL_URL + "\\n')\n"
        f"sys.stdout.write({url_line!r})\n"
        "sys.stdout.flush()\n"
        + ("sys.exit(0)\n" if exit_immediately else "")
        + (
            # the flood, in credential-bearing lines so a leak would be visible
            f"line = 'tunnel chatter PGPASSWORD={SECRET} " + TUNNEL_URL + "\\n'\n"
            f"written = 0\n"
            f"while written < {flood}:\n"
            "    sys.stdout.write(line)\n"
            "    written += len(line)\n"
            "sys.stdout.flush()\n"
            f"open({str(marker)!r}, 'w').write('done')\n"
            if flood
            else ""
        )
        + "time.sleep(60)\n",
        encoding="utf-8",
    )
    return script, marker


def _patch_popen(monkeypatch, checker, script: Path) -> None:
    real_popen = subprocess.Popen
    monkeypatch.setattr(
        checker.subprocess,
        "Popen",
        lambda argv, *a, **k: real_popen([sys.executable, str(script)], *a, **k),
    )


def _drain_threads() -> list[threading.Thread]:
    return [
        t for t in threading.enumerate() if t.name == checker_drain_name()
    ]


def checker_drain_name() -> str:
    return "railway-tunnel-drain"


# --- 1. the high-volume pipe test ------------------------------------------


def test_the_child_is_not_blocked_by_a_flood_after_the_url(
    checker, monkeypatch, tmp_path, capfd
):
    """512 KiB after the URL line - 8x the pipe buffer - and the child finishes."""
    script, marker = _fake_railway(tmp_path, flood=FLOOD_BYTES)
    _patch_popen(monkeypatch, checker, script)

    proc, url = checker.open_tunnel("Postgres", "staging")
    try:
        assert url == TUNNEL_URL, "the parsed URL must be unchanged by draining"

        # The child reaches its post-flood line only if the pipe kept moving.
        deadline = time.time() + 30
        while time.time() < deadline and not marker.exists():
            time.sleep(0.05)
        assert marker.exists(), (
            f"the child never finished writing {FLOOD_BYTES} bytes - it blocked "
            "on a full stdout pipe (the drain is not running)"
        )
        assert marker.read_text() == "done"

        # and it is still alive, serving as a tunnel
        assert proc.poll() is None, "the tunnel process exited instead of serving"
    finally:
        checker.close_tunnel(proc)

    captured = capfd.readouterr()
    assert SECRET not in captured.out and SECRET not in captured.err
    assert TUNNEL_URL not in captured.out and TUNNEL_URL not in captured.err
    assert "PGPASSWORD" not in captured.out and "PGPASSWORD" not in captured.err


def test_the_flood_is_larger_than_a_pipe_buffer():
    """Guards the test itself: a smaller flood would prove nothing."""
    assert FLOOD_BYTES > PIPE_BUFFER_HINT * 4


def test_the_drain_thread_is_running_and_is_a_daemon(
    checker, monkeypatch, tmp_path
):
    script, _marker = _fake_railway(tmp_path, flood=FLOOD_BYTES)
    _patch_popen(monkeypatch, checker, script)

    proc, _url = checker.open_tunnel("Postgres", "staging")
    try:
        thread = getattr(proc, checker.DRAIN_ATTR)
        assert thread.is_alive()
        assert thread.daemon, "a non-daemon drain would hold up interpreter exit"
        assert thread.name == checker.DRAIN_THREAD_NAME
    finally:
        checker.close_tunnel(proc)


def test_the_drain_accumulates_nothing(checker, monkeypatch, tmp_path):
    """Read the source: the loop body is `pass`, there is no container."""
    source = (REPO_ROOT / "scripts" / "staging_db_read_check.py").read_text(
        encoding="utf-8"
    )
    body = source.split("def _drain")[1].split("\ndef ")[0]

    for forbidden in ("append", "print(", "logger", "logging", "return chunk"):
        assert forbidden not in body, forbidden
    assert "stream.read(DRAIN_CHUNK)" in body


def test_open_tunnel_no_longer_retains_the_lines_before_the_url(checker):
    """The old `captured` list held every credential line and had no reader."""
    source = (REPO_ROOT / "scripts" / "staging_db_read_check.py").read_text(
        encoding="utf-8"
    )
    body = source.split("def open_tunnel")[1].split("\ndef ")[0]

    assert "captured" not in body


# --- 2. cleanup ------------------------------------------------------------


def test_close_tunnel_leaves_no_process_and_no_thread(
    checker, monkeypatch, tmp_path
):
    before = _drain_threads()
    script, _marker = _fake_railway(tmp_path, flood=FLOOD_BYTES)
    _patch_popen(monkeypatch, checker, script)

    proc, _url = checker.open_tunnel("Postgres", "staging")
    thread = getattr(proc, checker.DRAIN_ATTR)
    checker.close_tunnel(proc)

    assert proc.poll() is not None, "the tunnel process survived close_tunnel"
    assert not thread.is_alive(), "the drain thread outlived close_tunnel"
    assert getattr(proc, checker.DRAIN_ATTR) is None
    assert len(_drain_threads()) == len(before)


def test_close_tunnel_is_idempotent(checker, monkeypatch, tmp_path):
    script, _marker = _fake_railway(tmp_path, flood=FLOOD_BYTES)
    _patch_popen(monkeypatch, checker, script)

    proc, _url = checker.open_tunnel("Postgres", "staging")
    checker.close_tunnel(proc)
    checker.close_tunnel(proc)  # must not raise
    checker.close_tunnel(proc)

    assert proc.poll() is not None


def test_the_pipe_is_closed_after_cleanup(checker, monkeypatch, tmp_path):
    script, _marker = _fake_railway(tmp_path, flood=FLOOD_BYTES)
    _patch_popen(monkeypatch, checker, script)

    proc, _url = checker.open_tunnel("Postgres", "staging")
    checker.close_tunnel(proc)

    assert proc.stdout is None or proc.stdout.closed


def test_the_verified_target_closes_through_the_checkers_helper(
    checker, monkeypatch, tmp_path
):
    """The gate's own close() joins the drain rather than only terminating."""
    script, _marker = _fake_railway(tmp_path, flood=FLOOD_BYTES)
    _patch_popen(monkeypatch, checker, script)

    proc, _url = checker.open_tunnel("Postgres", "staging")
    thread = getattr(proc, checker.DRAIN_ATTR)
    target = T.VerifiedStagingTarget(
        attestation=None, url=TUNNEL_URL, redacted="127.0.0.1:54321/railway",
        _process=proc, _closer=checker.close_tunnel,
    )

    target.close()

    assert proc.poll() is not None
    assert not thread.is_alive()
    target.close()  # idempotent


def test_a_target_close_after_an_exception_still_cleans_up(
    checker, monkeypatch, tmp_path
):
    """The runner closes in a `finally`; that path must join the drain too."""
    script, _marker = _fake_railway(tmp_path, flood=FLOOD_BYTES)
    _patch_popen(monkeypatch, checker, script)

    proc, _url = checker.open_tunnel("Postgres", "staging")
    thread = getattr(proc, checker.DRAIN_ATTR)
    target = T.VerifiedStagingTarget(
        attestation=None, url=TUNNEL_URL, redacted="127.0.0.1:54321/railway",
        _process=proc, _closer=checker.close_tunnel,
    )

    try:
        raise RuntimeError("the run blew up")
    except RuntimeError:
        pass
    finally:
        target.close()

    assert proc.poll() is not None
    assert not thread.is_alive()


# --- 3. failure paths ------------------------------------------------------


def test_a_child_that_exits_before_the_url_is_a_clean_refusal(
    checker, monkeypatch, tmp_path, capfd
):
    script, _marker = _fake_railway(tmp_path, emit_url=False, exit_immediately=True)
    _patch_popen(monkeypatch, checker, script)
    monkeypatch.setattr(checker, "TUNNEL_READY_TIMEOUT_S", 3)

    with pytest.raises(RuntimeError) as excinfo:
        checker.open_tunnel("Postgres", "staging")

    captured = capfd.readouterr()
    assert SECRET not in str(excinfo.value)
    assert TUNNEL_URL not in str(excinfo.value)
    assert SECRET not in captured.out and SECRET not in captured.err


def test_a_url_that_never_arrives_times_out_without_leaking(
    checker, monkeypatch, tmp_path, capfd
):
    script, _marker = _fake_railway(tmp_path, emit_url=False)
    _patch_popen(monkeypatch, checker, script)
    monkeypatch.setattr(checker, "TUNNEL_READY_TIMEOUT_S", 2)

    with pytest.raises(RuntimeError) as excinfo:
        checker.open_tunnel("Postgres", "staging")

    captured = capfd.readouterr()
    assert "did not report a tunnel URL" in str(excinfo.value)
    assert SECRET not in str(excinfo.value)
    assert TUNNEL_URL not in str(excinfo.value)
    assert SECRET not in captured.out and SECRET not in captured.err


def test_a_timed_out_tunnel_leaves_no_process_behind(
    checker, monkeypatch, tmp_path
):
    """The refusal path now closes through the same helper."""
    script, _marker = _fake_railway(tmp_path, emit_url=False)
    _patch_popen(monkeypatch, checker, script)
    monkeypatch.setattr(checker, "TUNNEL_READY_TIMEOUT_S", 2)
    started: list = []
    real_popen = subprocess.Popen

    def _record(argv, *a, **k):
        proc = real_popen([sys.executable, str(script)], *a, **k)
        started.append(proc)
        return proc

    monkeypatch.setattr(checker.subprocess, "Popen", _record)

    with pytest.raises(RuntimeError):
        checker.open_tunnel("Postgres", "staging")

    assert started and started[0].poll() is not None


def test_no_drain_thread_survives_this_module(checker):
    """Belt and braces: nothing above leaked a reader into the interpreter."""
    time.sleep(0.2)

    assert _drain_threads() == []
