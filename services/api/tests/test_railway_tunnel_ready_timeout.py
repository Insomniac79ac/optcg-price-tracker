"""4D-4B: TUNNEL_READY_TIMEOUT_S is a real deadline, not an aspiration.

THE GAP THIS CLOSES. `open_tunnel` used to read the pipe itself:

    while time.time() < deadline:
        line = proc.stdout.readline()      # <- blocks until a NEWLINE
        ...

The deadline was only ever consulted BETWEEN lines, so a child that stayed
alive and said nothing - or wrote a partial line and fell silent - parked the
caller in `readline` forever. `TUNNEL_READY_TIMEOUT_S` bounded nothing. It was
found while fixing the process-group deadlock: a fake tunnel with a 600s sleep
and a 2s timeout hung for the full 600s.

THE FIX, in one sentence: the caller stopped reading. A single thread owns
stdout for the tunnel's whole life - it scans for the URL with `os.read`
(which returns on ANY bytes, not on punctuation), publishes through a
`_TunnelHandshake`, and then drains - while `open_tunnel` does nothing but
`Event.wait(timeout)`. One blocking call, woken by the OS: no polling, no
second reader on the fd, and no way to overrun.

Real subprocesses throughout. A mock cannot exhibit a blocking read, which is
the entire subject. No Railway access, no network, no canonical staging.
"""

import os
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

# Short enough to keep the suite quick, long enough that scheduling jitter
# cannot make a correct implementation look late.
TIMEOUT_S = 2.0
# A timeout must land in [TIMEOUT_S, TIMEOUT_S + TOLERANCE_S]. The upper bound
# is the assertion that matters: before the fix these cases ran until the
# child's own sleep expired, i.e. minutes.
TOLERANCE_S = 6.0

FLOOD_BYTES = 512 * 1024


@pytest.fixture
def checker():
    return T.load_staging_checker()


def _drain_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "railway-tunnel-drain"]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover
        return True
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


def _wait_gone(pid: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


def _wait_for(path: Path, timeout: float = 15.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            text = path.read_text().strip()
            if text:
                return text
        time.sleep(0.05)
    raise AssertionError(f"{path} never appeared")


def _write_fake(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "fake_railway_tunnel.py"
    script.write_text(
        "import os, subprocess, sys, time\n" + body, encoding="utf-8"
    )
    return script


def _patch_popen(monkeypatch, checker, script: Path) -> None:
    """Argv only - every kwarg, including start_new_session, is forwarded."""
    real_popen = subprocess.Popen
    monkeypatch.setattr(
        checker.subprocess,
        "Popen",
        lambda argv, *a, **k: real_popen([sys.executable, str(script)], *a, **k),
    )


def _timed_open(checker, expect_raise=True):
    """Runs open_tunnel and returns (elapsed, result_or_exception)."""
    started = time.time()
    if expect_raise:
        with pytest.raises(RuntimeError) as excinfo:
            checker.open_tunnel("Postgres", "staging")
        return time.time() - started, excinfo.value
    result = checker.open_tunnel("Postgres", "staging")
    return time.time() - started, result


def _assert_bounded(elapsed: float) -> None:
    assert elapsed >= TIMEOUT_S - 0.5, f"returned before the deadline ({elapsed:.2f}s)"
    assert elapsed < TIMEOUT_S + TOLERANCE_S, (
        f"open_tunnel overran its {TIMEOUT_S}s deadline by {elapsed - TIMEOUT_S:.2f}s "
        "- the caller is blocked on a read again"
    )


# --- A. alive and completely silent ----------------------------------------


def test_a_a_silent_child_times_out_within_tolerance(checker, monkeypatch, tmp_path):
    """The headline case. Alive, holding the pipe, never writing a byte.

    Under the old readline loop this blocked for the child's full 600s sleep.
    """
    pidfile = tmp_path / "pids.txt"
    script = _write_fake(
        tmp_path,
        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(600)\n",
    )
    _patch_popen(monkeypatch, checker, script)
    monkeypatch.setattr(checker, "TUNNEL_READY_TIMEOUT_S", TIMEOUT_S)

    elapsed, error = _timed_open(checker)
    leader = int(_wait_for(pidfile))

    _assert_bounded(elapsed)
    assert "did not report a tunnel URL" in str(error)
    assert _wait_gone(leader), "the silent child survived the refusal"
    assert not _drain_threads()


# --- B. partial text, no newline, then silence -----------------------------


def test_b_a_partial_line_without_a_newline_still_times_out(
    checker, monkeypatch, tmp_path
):
    """`readline` waits for punctuation that never comes; `os.read` does not.

    The child writes a credential-shaped fragment with NO trailing newline and
    then sleeps. Bytes are available, so the reader wakes - and still finds no
    URL, so the deadline is what ends the wait.
    """
    pidfile = tmp_path / "pids.txt"
    script = _write_fake(
        tmp_path,
        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
        f"sys.stdout.write('  Password: {SECRET}')\n"  # no newline, ever
        "sys.stdout.flush()\n"
        "time.sleep(600)\n",
    )
    _patch_popen(monkeypatch, checker, script)
    monkeypatch.setattr(checker, "TUNNEL_READY_TIMEOUT_S", TIMEOUT_S)

    elapsed, error = _timed_open(checker)
    leader = int(_wait_for(pidfile))

    _assert_bounded(elapsed)
    assert SECRET not in str(error), "the partial line reached the error"
    assert _wait_gone(leader)
    assert not _drain_threads()


def test_b_a_newline_free_flood_does_not_grow_the_scan_buffer(
    checker, monkeypatch, tmp_path
):
    """PRE_URL_SCAN_LIMIT: bytes without a newline are dropped, not hoarded.

    1 MiB with no newline, 16x the cap. The run must still refuse on time
    rather than accumulate - the old `readline` would have buffered the lot.
    """
    pidfile = tmp_path / "pids.txt"
    assert checker.PRE_URL_SCAN_LIMIT == 64 * 1024
    script = _write_fake(
        tmp_path,
        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
        "sys.stdout.write('x' * (1024 * 1024))\n"  # not one newline
        "sys.stdout.flush()\n"
        "time.sleep(600)\n",
    )
    _patch_popen(monkeypatch, checker, script)
    monkeypatch.setattr(checker, "TUNNEL_READY_TIMEOUT_S", TIMEOUT_S)

    elapsed, error = _timed_open(checker)
    leader = int(_wait_for(pidfile))

    _assert_bounded(elapsed)
    assert "did not report a tunnel URL" in str(error)
    assert _wait_gone(leader)
    assert not _drain_threads()


# --- C. noise then URL -----------------------------------------------------


def test_c_noisy_credential_lines_then_a_url_resolves_and_retains_nothing(
    checker, monkeypatch, tmp_path, capfd
):
    """200 credential-bearing lines, then the URL. Only the URL survives."""
    noise = (
        "for i in range(200):\n"
        f"    sys.stdout.write(f'  Password: {SECRET} attempt {{i}}\\n')\n"
        f"    sys.stdout.write('Connection string: {TUNNEL_URL}\\n')\n"
        f"sys.stdout.write('URL: {TUNNEL_URL}\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(600)\n"
    )
    script = _write_fake(tmp_path, noise)
    _patch_popen(monkeypatch, checker, script)
    monkeypatch.setattr(checker, "TUNNEL_READY_TIMEOUT_S", TIMEOUT_S)

    elapsed, (proc, url) = _timed_open(checker, expect_raise=False)
    try:
        assert url == TUNNEL_URL, "the URL after the noise was not parsed"
        assert elapsed < TIMEOUT_S, "resolved late despite the URL arriving early"
        out, err = capfd.readouterr()
        # Nothing scanned is printed, and nothing is retained anywhere we can
        # reach: the only value that escaped the reader is the URL itself.
        assert SECRET not in out and SECRET not in err
        assert "Password:" not in out and "Password:" not in err
        assert "Connection string:" not in out and "Connection string:" not in err
    finally:
        checker.close_tunnel(proc)
    assert not _drain_threads()


# --- D. URL just before the deadline ---------------------------------------


def test_d_a_url_arriving_just_before_the_deadline_succeeds(
    checker, monkeypatch, tmp_path
):
    """A slow tunnel is not a failed one - the wait must not fire early."""
    late = TIMEOUT_S * 0.6
    script = _write_fake(
        tmp_path,
        f"time.sleep({late})\n"
        f"sys.stdout.write('URL: {TUNNEL_URL}\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(600)\n",
    )
    _patch_popen(monkeypatch, checker, script)
    monkeypatch.setattr(checker, "TUNNEL_READY_TIMEOUT_S", TIMEOUT_S)

    elapsed, (proc, url) = _timed_open(checker, expect_raise=False)
    try:
        assert url == TUNNEL_URL
        assert elapsed >= late, "returned before the child had even written"
        assert elapsed < TIMEOUT_S + TOLERANCE_S
    finally:
        checker.close_tunnel(proc)
    assert not _drain_threads()


def test_d_a_child_that_dies_without_a_url_refuses_without_waiting(
    checker, monkeypatch, tmp_path
):
    """EOF settles the handshake, so a dead child is not waited out."""
    script = _write_fake(
        tmp_path,
        f"sys.stdout.write('  Password: {SECRET}\\n')\n"
        "sys.stdout.flush()\n"
        "sys.exit(1)\n",
    )
    _patch_popen(monkeypatch, checker, script)
    monkeypatch.setattr(checker, "TUNNEL_READY_TIMEOUT_S", 30.0)

    started = time.time()
    with pytest.raises(RuntimeError) as excinfo:
        checker.open_tunnel("Postgres", "staging")
    elapsed = time.time() - started

    assert elapsed < 10.0, (
        f"waited {elapsed:.1f}s for a child that had already exited - EOF must "
        "settle the handshake rather than burn the whole budget"
    )
    assert SECRET not in str(excinfo.value)
    assert not _drain_threads()


# --- E. no URL while a descendant retains the pipe -------------------------


def test_e_timeout_with_a_descendant_holding_the_pipe_cleans_the_session(
    checker, monkeypatch, tmp_path
):
    """The two failure modes at once.

    No URL ever arrives AND a descendant holds the write end - so there is no
    EOF to end the wait, and the leader alone is not the whole tunnel. The
    deadline must fire, and the refusal must go through the process/session
    authority, leaving nothing behind.
    """
    pidfile = tmp_path / "pids.txt"
    kidready = tmp_path / "kid_ready.txt"
    kid_src = (
        "import os, time\n"
        "os.setpgid(0, 0)\n"  # exactly what Railway's ssh -L does
        f"open({str(kidready)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(600)\n"
    )
    script = _write_fake(
        tmp_path,
        f"kid = subprocess.Popen([sys.executable, '-c', {kid_src!r}])\n"
        "_deadline = time.time() + 15\n"
        f"while not os.path.exists({str(kidready)!r}) and time.time() < _deadline:\n"
        "    time.sleep(0.01)\n"
        f"open({str(pidfile)!r}, 'w').write(f'{{os.getpid()}},{{kid.pid}}')\n"
        f"sys.stdout.write('Connection string: {TUNNEL_URL}\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(600)\n",
    )
    _patch_popen(monkeypatch, checker, script)
    monkeypatch.setattr(checker, "TUNNEL_READY_TIMEOUT_S", TIMEOUT_S)

    elapsed, error = _timed_open(checker)
    leader, kid = (int(x) for x in _wait_for(pidfile).split(","))

    _assert_bounded(elapsed)
    assert "did not report a tunnel URL" in str(error)
    assert TUNNEL_URL not in str(error)
    assert _wait_gone(leader), "leader survived the timeout"
    assert _wait_gone(kid), "the forward survived the timeout"
    assert not _drain_threads()


# --- F. flood after the URL ------------------------------------------------


def test_f_a_flood_after_the_url_still_drains_without_blocking(
    checker, monkeypatch, tmp_path, capfd
):
    """Phase 2 is unchanged: >512 KiB after the URL and the child still
    finishes, proving the single reader keeps draining once it has handed the
    URL over."""
    marker = tmp_path / "flood_complete.marker"
    script = _write_fake(
        tmp_path,
        f"sys.stdout.write('URL: {TUNNEL_URL}\\n')\n"
        "sys.stdout.flush()\n"
        f"line = 'chatter PGPASSWORD={SECRET} {TUNNEL_URL}\\n'\n"
        "written = 0\n"
        f"while written < {FLOOD_BYTES}:\n"
        "    sys.stdout.write(line)\n"
        "    written += len(line)\n"
        "sys.stdout.flush()\n"
        f"open({str(marker)!r}, 'w').write('done')\n"
        "time.sleep(600)\n",
    )
    _patch_popen(monkeypatch, checker, script)
    monkeypatch.setattr(checker, "TUNNEL_READY_TIMEOUT_S", TIMEOUT_S)

    _elapsed, (proc, url) = _timed_open(checker, expect_raise=False)
    try:
        assert url == TUNNEL_URL
        assert _wait_for(marker) == "done", (
            "the child blocked on a full pipe - the reader stopped draining "
            "after publishing the URL"
        )
        out, err = capfd.readouterr()
        assert SECRET not in out and SECRET not in err
        assert "PGPASSWORD" not in out and "PGPASSWORD" not in err
    finally:
        checker.close_tunnel(proc)
    assert not _drain_threads()


# --- structure: the caller no longer reads ---------------------------------


def _code_of(function: str) -> str:
    """The executable body of `function`, with docstring and comments removed.

    These assertions are about what the code DOES. Scanning raw source would
    match the prose explaining why `readline` is wrong, which is the opposite
    of the intended check - so the body is round-tripped through `ast` and the
    docstring dropped, leaving only statements.
    """
    import ast

    source = (REPO_ROOT / "scripts" / "staging_db_read_check.py").read_text(
        encoding="utf-8"
    )
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == function:
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = body[1:]
            return "\n".join(ast.unparse(statement) for statement in body)
    raise AssertionError(f"{function} not found in the checker")


def test_the_caller_never_reads_the_pipe_itself():
    """One reader owner. `open_tunnel` must contain no read of its own."""
    code = _code_of("open_tunnel")

    for forbidden in ("readline", "stdout.read", "os.read", "time.sleep", "poll()"):
        assert forbidden not in code, f"open_tunnel still does its own {forbidden}"
    assert "handshake.wait(TUNNEL_READY_TIMEOUT_S)" in code
    # Containment and the command are untouched by this tranche.
    assert "stdout=subprocess.PIPE" in code
    assert "stderr=subprocess.STDOUT" in code
    assert "start_new_session=True" in code
    assert "shell=True" not in code
    assert "'railway', 'connect', service" in code


def test_the_scan_retains_only_one_bounded_partial_line():
    """The pre-URL scanner must not accumulate, and must not report."""
    code = _code_of("_scan_for_url")

    for forbidden in ("append", "print(", "logger", "logging", "readline"):
        assert forbidden not in code, forbidden
    assert "os.read(fd, DRAIN_CHUNK)" in code
    assert "PRE_URL_SCAN_LIMIT" in code
    # The only thing that escapes is the captured group of the URL match.
    assert "handshake.publish(match.group(1))" in code


def test_no_tunnel_process_or_thread_survives_this_module(checker):
    assert not _drain_threads()
    leftovers = subprocess.run(
        ["pgrep", "-f", "fake_railway_tunnel.py"], capture_output=True, text=True
    )
    assert leftovers.returncode == 1, (
        f"fake tunnel processes survived: {leftovers.stdout!r}"
    )
