"""4D-4: the Railway tunnel is cleaned up as a PROCESS GROUP, not one process.

THE BUG THIS CLOSES, observed live against Railway on 2026-08-25.

`railway connect --tunnel-only` is a node process that spawns `ssh -L ...` and
lets it do the actual forwarding. `proc.terminate()` signals only the node
leader. The `ssh` grandchild survives it, and - because it inherited the same
stdout - it keeps the PIPE WRITE END OPEN. Three things followed:

    1. the drain thread never saw EOF, so `join(timeout=...)` EXPIRED with the
       reader still blocked inside `stream.read()`;
    2. `proc.stdout.close()` then blocked FOREVER on the `BufferedReader` lock
       that the blocked reader still held - a hard deadlock, not a slow path;
    3. every invocation leaked a live SSH port-forward into staging.

The operator-visible damage was worse than a hang: `staging_db_read_check`
closes its tunnel in a `finally` that runs BEFORE the results are printed, and
the dedicated importer's `finally` runs AFTER the apply has COMMITTED and
before its report is printed. A correct, committed import looked like a wedged
process.

WHY THESE TESTS USE REAL SUBPROCESSES. None of this is reproducible with a
mocked `Popen`. The deadlock lives in an OS pipe held open by a process we did
not directly spawn, and the fix lives in POSIX process-group signalling. So the
fake Railway here is a genuine `python` subprocess that spawns a genuine
grandchild which genuinely inherits the pipe - the exact topology observed -
and liveness is read from `/proc`, not from a mock's call list.

`test_negative_control_*` is the reproduction, kept permanently: it performs
the OLD parent-only termination inline and asserts the descendant survives it.
It is what makes the passing tests below mean something.

No Railway access, no network, no canonical staging.
"""

import os
import signal
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

if not hasattr(os, "killpg"):  # pragma: no cover - POSIX-only guarantees
    pytestmark = pytest.mark.skip(reason="process-group cleanup is POSIX-only")

SECRET = "SUPERSECRET"
TUNNEL_URL = f"postgresql://railwayuser:{SECRET}@127.0.0.1:54321/railway"

# 8x a Linux pipe buffer (~64 KiB): a run that is not draining is guaranteed to
# wedge rather than merely be unlucky.
FLOOD_BYTES = 512 * 1024

# Bounded everywhere. A regression must fail the assertion, never hang the run.
SETTLE_S = 2.0
CLEANUP_BUDGET_S = 20.0


@pytest.fixture
def checker():
    return T.load_staging_checker()


# --- liveness, read from /proc rather than a mock ---------------------------


def _alive(pid: int) -> bool:
    """True only for a process that exists and is not a reaped zombie.

    A descendant we SIGKILL is reparented to init; on a devcontainer that is
    `docker-init`, which reaps. Treating 'Z' as dead keeps the assertion about
    "is anything still running" rather than about who happened to reap first.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - exists, not ours
        return True
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return False
    # state is the field after the (possibly parenthesised) comm
    state = stat.rsplit(")", 1)[1].split()[0]
    return state != "Z"


def _wait_gone(pid: int, timeout: float = CLEANUP_BUDGET_S) -> bool:
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


def _drain_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "railway-tunnel-drain"]


def _run_bounded(fn, budget: float = CLEANUP_BUDGET_S) -> bool:
    """Runs `fn` on a daemon thread. Returns whether it completed in budget.

    This is how a DEADLOCK is asserted on rather than suffered: before the fix
    `close_tunnel` never returns, and a plain call would hang the whole suite.
    """
    done = threading.Event()

    def _target():
        try:
            fn()
        finally:
            done.set()

    threading.Thread(target=_target, daemon=True, name="bounded-cleanup").start()
    return done.wait(timeout=budget)


# --- the fake Railway, with the real topology -------------------------------


def _fake_railway_with_descendant(
    tmp_path: Path,
    *,
    flood: int = 0,
    ignore_sigterm: bool = False,
    parent_exits_immediately: bool = False,
    spawn_descendant: bool = True,
    emit_url: bool = True,
) -> tuple[Path, Path, Path]:
    """Writes a fake `railway connect`. Returns (script, pidfile, marker).

    The shape that matters: the LEADER spawns a DESCENDANT which inherits
    stdout - i.e. the pipe write end - and outlives it. That is `railway
    connect` spawning `ssh -L`, reduced to its essentials.

    The descendant is spawned and its pid recorded BEFORE the URL line, for
    the same reason the real one is: the URL describes a forward that already
    exists. It also removes a race - `open_tunnel` returns the instant it sees
    the URL, and a caller that closed immediately could otherwise kill the
    leader before it had spawned anything.

    `ignore_sigterm` makes the leader itself refuse SIGTERM, forcing the
    SIGKILL escalation path. `emit_url=False` keeps the leader chattering
    without ever announcing a URL, which is the refusal path: it must keep
    writing, because `open_tunnel` observes its deadline between reads.
    """
    pidfile = tmp_path / "pids.txt"
    marker = tmp_path / "flood_complete.marker"
    url_line = f"URL: {TUNNEL_URL}\n" if emit_url else f"NOTURL: {TUNNEL_URL}\n"

    # The descendant holds stdout open and does NOT ignore signals: the point
    # is that nothing ever signals it under the old model, not that it is
    # unkillable.
    #
    # setpgid(0, 0) is not incidental - it is what the REAL `ssh -L` does.
    # Measured against the live CLI: the forward runs in its own process group
    # but stays in the tunnel's session, so a group-only kill sails past it:
    #     railway pid=273096 pgid=273096 sid=273096
    #     ssh     pid=273182 pgid=273182 sid=273096
    # A fake that stayed in the leader's group would let a group-only fix
    # look correct.
    kidready = tmp_path / "kid_ready.txt"
    descendant_src = (
        "import os, time\n"
        "os.setpgid(0, 0)\n"
        f"open({str(kidready)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(600)\n"
    )

    lines = ["import os, signal, subprocess, sys, time"]
    if ignore_sigterm:
        lines.append("signal.signal(signal.SIGTERM, signal.SIG_IGN)")
    if spawn_descendant:
        lines += [
            # No stdout= : the descendant INHERITS our pipe. This is the whole
            # reproduction.
            f"kid = subprocess.Popen([sys.executable, '-c', {descendant_src!r}])",
            # Publish the pids only once the kid has actually re-parented its
            # process group. Without this handshake a test can read the pidfile
            # while the kid is still in the leader's group, and assert the
            # wrong topology.
            "_deadline = time.time() + 15",
            f"while not os.path.exists({str(kidready)!r}) and time.time() < _deadline:",
            "    time.sleep(0.01)",
            f"open({str(pidfile)!r}, 'w').write(f'{{os.getpid()}},{{kid.pid}}')",
        ]
    else:
        lines.append(f"open({str(pidfile)!r}, 'w').write(f'{{os.getpid()}},0')")
    lines += [
        # the credential-bearing preamble a real CLI prints
        f"sys.stderr.write('  Password: {SECRET}\\n'); sys.stderr.flush()",
        "sys.stdout.write('Connecting to Postgres on environment staging...\\n')",
        f"sys.stdout.write('Connection string: {TUNNEL_URL}\\n')",
        f"sys.stdout.write({url_line!r})",
        "sys.stdout.flush()",
    ]

    if flood:
        lines += [
            f"line = 'tunnel chatter PGPASSWORD={SECRET} {TUNNEL_URL}\\n'",
            "written = 0",
            f"while written < {flood}:",
            "    sys.stdout.write(line)",
            "    written += len(line)",
            "sys.stdout.flush()",
            f"open({str(marker)!r}, 'w').write('done')",
        ]

    if parent_exits_immediately:
        lines.append("sys.exit(0)")
    elif not emit_url:
        # Keep talking, never announcing a URL. `open_tunnel` reads with a
        # blocking readline and only checks its deadline between lines, so a
        # leader that fell silent would stall the refusal path rather than
        # exercise it.
        lines += [
            "while True:",
            f"    sys.stdout.write('still connecting {TUNNEL_URL}\\n')",
            "    sys.stdout.flush()",
            "    time.sleep(0.1)",
        ]
    else:
        lines.append("time.sleep(600)")

    script = tmp_path / "fake_railway_tunnel.py"
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return script, pidfile, marker


def _patch_popen(monkeypatch, checker, script: Path) -> None:
    """Swap the argv only. Every kwarg - crucially start_new_session - is
    forwarded untouched, so what the test drives is the real call shape."""
    real_popen = subprocess.Popen
    monkeypatch.setattr(
        checker.subprocess,
        "Popen",
        lambda argv, *a, **k: real_popen([sys.executable, str(script)], *a, **k),
    )


def _open(checker, tmp_path, **kwargs):
    """Opens a fake tunnel and returns (proc, url, leader_pid, kid_pid, marker)."""
    script, pidfile, marker = _fake_railway_with_descendant(tmp_path, **kwargs)
    proc, url = checker.open_tunnel("Postgres", "staging")
    leader, kid = (int(x) for x in _wait_for(pidfile).split(","))
    return proc, url, leader, kid, marker


# --- 1. THE REPRODUCTION / permanent negative control -----------------------


def test_negative_control_parent_only_termination_leaves_the_descendant_alive(
    checker, monkeypatch, tmp_path
):
    """The OLD model, performed inline: terminate the leader and nothing else.

    This is the observed Railway failure reduced to an assertion. It must keep
    passing forever - it is the control that gives the process-group tests
    below their meaning.
    """
    script, pidfile, _ = _fake_railway_with_descendant(tmp_path)
    _patch_popen(monkeypatch, checker, script)
    proc, url = checker.open_tunnel("Postgres", "staging")
    leader, kid = (int(x) for x in _wait_for(pidfile).split(","))
    try:
        assert url == TUNNEL_URL
        assert _alive(leader) and _alive(kid)

        # --- exactly what the old close_tunnel did ---
        proc.terminate()
        proc.wait(timeout=10)

        assert not _alive(leader), "the leader should die from SIGTERM"
        time.sleep(SETTLE_S)
        assert _alive(kid), (
            "REPRODUCTION: parent-only termination leaves the descendant alive - "
            "this is the ssh -L that kept leaking into staging"
        )

        # And because the descendant still owns the pipe write end, the drain
        # never reaches EOF: the reader is still blocked in read().
        thread = getattr(proc, checker.DRAIN_ATTR, None)
        assert thread is not None
        thread.join(timeout=3.0)
        assert thread.is_alive(), (
            "REPRODUCTION: no EOF while a descendant holds the write end, so the "
            "drain join expires - and the old code then called stdout.close() "
            "on a BufferedReader whose lock this thread still holds, deadlocking"
        )
    finally:
        checker.close_tunnel(proc)
        _wait_gone(kid)


def test_negative_control_a_group_only_kill_still_misses_the_forward(
    checker, monkeypatch, tmp_path
):
    """The SECOND reproduction, and the reason cleanup sweeps the session.

    Signalling only the stored process group - the obvious fix - is still not
    enough, because the real `ssh -L` puts itself in its own group. Measured
    against the live CLI on 2026-08-25:

        railway  pid=273096  pgid=273096  sid=273096
        ssh      pid=273182  pgid=273182  sid=273096

    so `killpg(273096)` reaches the leader and sails straight past the forward.
    This test performs that group-only kill inline and asserts the descendant
    survives it.
    """
    script, pidfile, _ = _fake_railway_with_descendant(tmp_path)
    _patch_popen(monkeypatch, checker, script)
    proc, _url = checker.open_tunnel("Postgres", "staging")
    leader, kid = (int(x) for x in _wait_for(pidfile).split(","))
    try:
        assert os.getpgid(kid) == kid, "the fake ssh must lead its own group"
        assert os.getsid(kid) == proc.pid, "but stay in the tunnel's session"

        os.killpg(checker.tunnel_pgid(proc), signal.SIGTERM)
        proc.wait(timeout=10)
        time.sleep(SETTLE_S)

        assert not _alive(leader)
        assert _alive(kid), (
            "REPRODUCTION: a group-only kill leaves the forward alive - the "
            "session is the boundary that actually contains the tunnel"
        )
    finally:
        checker.close_tunnel(proc)
        assert _wait_gone(kid)


def test_reproduction_the_stored_id_still_resolves_after_the_leader_exits(
    checker, monkeypatch, tmp_path
):
    """Why the id must be STORED: os.getpgid(proc.pid) is unavailable later.

    Once the leader has exited and been reaped, its pid no longer resolves, so
    cleanup cannot go looking the tunnel up at the moment it needs it. The id
    captured at spawn is both the group id and the SESSION id, and the session
    outlives the leader for as long as any member is alive.
    """
    script, pidfile, _ = _fake_railway_with_descendant(
        tmp_path, parent_exits_immediately=True
    )
    _patch_popen(monkeypatch, checker, script)
    proc, _url = checker.open_tunnel("Postgres", "staging")
    leader, kid = (int(x) for x in _wait_for(pidfile).split(","))
    try:
        proc.wait(timeout=10)  # reap the leader
        assert _alive(kid)

        with pytest.raises(ProcessLookupError):
            os.getpgid(proc.pid)

        # The stored id still identifies the session the descendant is in.
        assert checker.tunnel_pgid(proc) == leader
        assert os.getsid(kid) == checker.tunnel_pgid(proc)
        assert kid in checker._session_members(checker.tunnel_pgid(proc))
    finally:
        checker.close_tunnel(proc)
        assert _wait_gone(kid)


# --- 2. process-group ownership --------------------------------------------


def test_the_tunnel_is_spawned_in_its_own_session(checker, monkeypatch, tmp_path):
    seen = {}
    real_popen = subprocess.Popen
    script, pidfile, _ = _fake_railway_with_descendant(tmp_path)

    def _spy(argv, *a, **k):
        seen.update(k)
        seen["argv"] = argv
        return real_popen([sys.executable, str(script)], *a, **k)

    monkeypatch.setattr(checker.subprocess, "Popen", _spy)
    proc, _url = checker.open_tunnel("Postgres", "staging")
    kid = int(_wait_for(pidfile).split(",")[1])
    try:
        assert seen["start_new_session"] is True
        assert seen.get("shell") in (None, False), "no shell=True"
        # Railway arguments are untouched.
        assert seen["argv"] == [
            "railway", "connect", "Postgres",
            "--environment", "staging", "--tunnel-only",
        ]
        # Containment is unchanged: one merged captured pipe.
        assert seen["stdout"] is subprocess.PIPE
        assert seen["stderr"] is subprocess.STDOUT
    finally:
        checker.close_tunnel(proc)
        _wait_gone(kid)


def test_the_pgid_is_the_leader_pid_and_is_stored(checker, monkeypatch, tmp_path):
    script, pidfile, _ = _fake_railway_with_descendant(tmp_path)
    _patch_popen(monkeypatch, checker, script)
    proc, _url = checker.open_tunnel("Postgres", "staging")
    kid = int(_wait_for(pidfile).split(",")[1])
    try:
        assert checker.tunnel_pgid(proc) == proc.pid
        assert os.getpgid(proc.pid) == proc.pid, "the leader leads its own group"
        assert os.getsid(proc.pid) == proc.pid, "and its own session"
        # The real topology: the forward leaves the group but not the session.
        assert os.getpgid(kid) == kid
        assert os.getsid(kid) == proc.pid
        # Neither is ours - so signalling the tunnel can never signal us.
        assert os.getsid(proc.pid) != os.getsid(os.getpid())
        assert os.getpgid(proc.pid) != os.getpgid(os.getpid())
    finally:
        checker.close_tunnel(proc)
        assert _wait_gone(kid)


@pytest.mark.parametrize("own", ["pgid", "sid"])
def test_our_own_group_or_session_is_never_signalled(
    checker, monkeypatch, tmp_path, own
):
    """The guard that matters most: a tunnel whose group or session is somehow
    ours must not be signalled, because that would SIGKILL this process."""
    script, pidfile, _ = _fake_railway_with_descendant(tmp_path)
    _patch_popen(monkeypatch, checker, script)
    proc, _url = checker.open_tunnel("Postgres", "staging")
    kid = int(_wait_for(pidfile).split(",")[1])
    try:
        killed_pids = []
        monkeypatch.setattr(checker.os, "kill", lambda pid, sig: killed_pids.append(pid))
        ours = os.getpgid(0) if own == "pgid" else os.getsid(0)
        killed = []
        monkeypatch.setattr(checker.os, "killpg", lambda pgid, sig: killed.append((pgid, sig)))
        setattr(proc, checker.PGID_ATTR, ours)
        assert _run_bounded(lambda: checker.close_tunnel(proc))
        assert killed == [], f"refused to signal our own {own}"
        # `Popen.terminate` legitimately calls os.kill on the leader - that is
        # the leader-only fallback. Nothing ELSE may be signalled: no sweep of
        # our own session, and above all not us.
        assert set(killed_pids) <= {proc.pid}, f"swept our own {own}"
        assert os.getpid() not in killed_pids
    finally:
        monkeypatch.undo()
        setattr(proc, checker.PGID_ATTR, proc.pid)
        checker.close_tunnel(proc)
        assert _wait_gone(kid)


def test_the_session_sweep_never_returns_our_own_processes(checker):
    """`_session_members` must be empty for our own session, whatever else is
    running in it - the sweep is the one place a stray pid would be fatal."""
    assert checker._session_members(os.getsid(0)) == []
    assert checker._session_members(None) == []


# --- 3./4. close_tunnel kills the whole tree -------------------------------


def test_close_tunnel_kills_a_descendant_that_survived_the_leader(
    checker, monkeypatch, tmp_path
):
    """THE FIX. The exact observed case: leader dies from SIGTERM, descendant
    would survive it - and close_tunnel kills it anyway, via the group."""
    script, pidfile, _ = _fake_railway_with_descendant(tmp_path)
    _patch_popen(monkeypatch, checker, script)
    proc, _url = checker.open_tunnel("Postgres", "staging")
    leader, kid = (int(x) for x in _wait_for(pidfile).split(","))
    assert _alive(leader) and _alive(kid)

    assert _run_bounded(lambda: checker.close_tunnel(proc)), (
        "close_tunnel deadlocked - stdout.close() blocked on the lock held by "
        "the drain thread that never reached EOF"
    )
    assert _wait_gone(leader), "leader survived"
    assert _wait_gone(kid), "descendant survived - the group was not signalled"
    assert not _drain_threads(), "a drain thread outlived the tunnel"
    assert proc.stdout is None or proc.stdout.closed


def test_close_tunnel_kills_the_descendant_when_the_leader_already_exited(
    checker, monkeypatch, tmp_path
):
    """Step 4's case: the leader is gone (and reaped) before cleanup starts.

    `os.getpgid(proc.pid)` raises here, which is precisely why the group id is
    captured at spawn and stored on the process object.
    """
    script, pidfile, _ = _fake_railway_with_descendant(
        tmp_path, parent_exits_immediately=True
    )
    _patch_popen(monkeypatch, checker, script)
    proc, _url = checker.open_tunnel("Postgres", "staging")
    leader, kid = (int(x) for x in _wait_for(pidfile).split(","))
    proc.wait(timeout=10)
    assert not _alive(leader) and _alive(kid)

    assert _run_bounded(lambda: checker.close_tunnel(proc))
    assert _wait_gone(kid), "descendant survived after the leader had exited"
    assert not _drain_threads()


def test_sigterm_alone_is_enough_for_a_well_behaved_tunnel(
    checker, monkeypatch, tmp_path
):
    """No escalation when the group answers SIGTERM: SIGKILL is not sent."""
    script, pidfile, _ = _fake_railway_with_descendant(tmp_path)
    _patch_popen(monkeypatch, checker, script)
    proc, _url = checker.open_tunnel("Postgres", "staging")
    leader, kid = (int(x) for x in _wait_for(pidfile).split(","))

    signals = []
    real_killpg = os.killpg
    monkeypatch.setattr(
        checker.os, "killpg",
        lambda pgid, sig: (signals.append(sig), real_killpg(pgid, sig))[1],
    )
    assert _run_bounded(lambda: checker.close_tunnel(proc))
    assert signal.SIGTERM in signals
    assert signal.SIGKILL not in signals, "escalated when SIGTERM had sufficed"
    assert _wait_gone(leader) and _wait_gone(kid)


def test_sigkill_escalation_when_the_group_ignores_sigterm(
    checker, monkeypatch, tmp_path
):
    """A leader that ignores SIGTERM must still be gone when close returns."""
    script, pidfile, _ = _fake_railway_with_descendant(tmp_path, ignore_sigterm=True)
    _patch_popen(monkeypatch, checker, script)
    proc, _url = checker.open_tunnel("Postgres", "staging")
    leader, kid = (int(x) for x in _wait_for(pidfile).split(","))

    signals = []
    real_killpg = os.killpg
    monkeypatch.setattr(
        checker.os, "killpg",
        lambda pgid, sig: (signals.append(sig), real_killpg(pgid, sig))[1],
    )
    assert _run_bounded(lambda: checker.close_tunnel(proc, timeout=1.0))
    assert signal.SIGTERM in signals and signal.SIGKILL in signals
    assert _wait_gone(leader), "SIGTERM-ignoring leader survived cleanup"
    assert _wait_gone(kid)
    assert not _drain_threads()


def test_close_tunnel_is_idempotent_with_a_real_tree(checker, monkeypatch, tmp_path):
    script, pidfile, _ = _fake_railway_with_descendant(tmp_path)
    _patch_popen(monkeypatch, checker, script)
    proc, _url = checker.open_tunnel("Postgres", "staging")
    leader, kid = (int(x) for x in _wait_for(pidfile).split(","))

    assert _run_bounded(lambda: checker.close_tunnel(proc))
    assert _wait_gone(leader) and _wait_gone(kid)
    # Second call: no raise, no hang, nothing left to do.
    assert _run_bounded(lambda: checker.close_tunnel(proc))
    assert not _drain_threads()


def test_a_missing_group_is_not_an_error(checker, monkeypatch, tmp_path):
    """ESRCH is the normal outcome of closing a tunnel that already died."""
    script, pidfile, _ = _fake_railway_with_descendant(
        tmp_path, spawn_descendant=False, parent_exits_immediately=True
    )
    _patch_popen(monkeypatch, checker, script)
    proc, _url = checker.open_tunnel("Postgres", "staging")
    _wait_for(pidfile)
    proc.wait(timeout=10)
    time.sleep(0.5)
    assert _run_bounded(lambda: checker.close_tunnel(proc))
    assert not _drain_threads()


def test_the_pipe_closes_only_after_the_reader_returned(
    checker, monkeypatch, tmp_path
):
    """Ordering is the deadlock's root cause, so it is asserted directly."""
    script, pidfile, _ = _fake_railway_with_descendant(tmp_path)
    _patch_popen(monkeypatch, checker, script)
    proc, _url = checker.open_tunnel("Postgres", "staging")
    kid = int(_wait_for(pidfile).split(",")[1])
    thread = getattr(proc, checker.DRAIN_ATTR, None)
    assert thread is not None and thread.is_alive()

    order = []
    stream = proc.stdout
    real_close = stream.close

    def _watched_close():
        order.append(("close", thread.is_alive()))
        return real_close()

    monkeypatch.setattr(stream, "close", _watched_close)
    assert _run_bounded(lambda: checker.close_tunnel(proc))
    assert _wait_gone(kid)
    assert order, "stdout was never closed"
    assert order[0] == ("close", False), (
        "stdout.close() ran while the drain reader was still inside read() - "
        "that is the deadlock"
    )
    assert stream.closed


def test_the_timeout_path_leaves_no_descendants(checker, monkeypatch, tmp_path):
    """open_tunnel's own refusal path cleans up the whole tree, not just the
    leader - a tunnel that never reported a URL still spawned an ssh."""
    script, pidfile, _ = _fake_railway_with_descendant(tmp_path, emit_url=False)
    _patch_popen(monkeypatch, checker, script)
    monkeypatch.setattr(checker, "TUNNEL_READY_TIMEOUT_S", 2)

    with pytest.raises(RuntimeError) as excinfo:
        checker.open_tunnel("Postgres", "staging")

    leader, kid = (int(x) for x in _wait_for(pidfile).split(","))
    assert _wait_gone(leader) and _wait_gone(kid), "refusal path leaked a tunnel"
    assert not _drain_threads()
    # Secret containment on the refusal path is unchanged.
    assert SECRET not in str(excinfo.value)
    assert TUNNEL_URL not in str(excinfo.value)


# --- 5. callers -------------------------------------------------------------


def test_verified_staging_target_close_kills_the_whole_tree(
    checker, monkeypatch, tmp_path
):
    script, pidfile, _ = _fake_railway_with_descendant(tmp_path)
    _patch_popen(monkeypatch, checker, script)
    proc, url = checker.open_tunnel("Postgres", "staging")
    leader, kid = (int(x) for x in _wait_for(pidfile).split(","))

    target = T.VerifiedStagingTarget(
        attestation=None,
        url=url,
        redacted=checker.redacted_target(url),
        _process=proc,
        _closer=checker.close_tunnel,
    )
    assert _run_bounded(target.close)
    assert _wait_gone(leader) and _wait_gone(kid)
    assert not _drain_threads()
    target.close()  # idempotent


def test_the_cli_finally_cleans_up_the_whole_tree(checker, monkeypatch, tmp_path):
    """`main`'s finally closes the tunnel BEFORE printing results, so a hang
    there costs the operator the entire report. Drive it end to end."""
    script, pidfile, _ = _fake_railway_with_descendant(tmp_path)
    _patch_popen(monkeypatch, checker, script)

    # `main` does `import psycopg` internally, so the module object is what
    # has to be patched - there is no checker.psycopg attribute to reach.
    import psycopg

    def _boom(url, **kwargs):
        raise RuntimeError("no database behind this fake tunnel")

    monkeypatch.setattr(psycopg, "connect", _boom)

    rc_box = {}
    assert _run_bounded(lambda: rc_box.update(rc=checker.main([]))), (
        "the CLI hung in its finally"
    )
    leader, kid = (int(x) for x in _wait_for(pidfile).split(","))
    assert rc_box["rc"] == 1
    assert _wait_gone(leader) and _wait_gone(kid)
    assert not _drain_threads()


# --- 6. realistic stress: flood + descendant + full-tree cleanup ------------


def test_stress_flood_with_a_descendant_holding_the_pipe(
    checker, monkeypatch, tmp_path, capfd
):
    """The whole failure mode at once, on a real process tree.

    >512 KiB emitted after the URL marker, by a leader whose descendant holds
    the same pipe. Proves: the URL still parses, the drain prevents
    backpressure (the leader reaches its post-flood line), cleanup terminates
    the COMPLETE tree, and nothing we print carries the secret.
    """
    script, pidfile, marker = _fake_railway_with_descendant(
        tmp_path, flood=FLOOD_BYTES
    )
    _patch_popen(monkeypatch, checker, script)
    proc, url = checker.open_tunnel("Postgres", "staging")
    leader, kid = (int(x) for x in _wait_for(pidfile).split(","))

    assert url == TUNNEL_URL, "URL parsing still works with a descendant present"
    assert _wait_for(marker) == "done", (
        "the leader never finished the flood - it blocked on a full pipe"
    )
    assert _alive(kid)

    assert _run_bounded(lambda: checker.close_tunnel(proc))
    assert _wait_gone(leader), "leader survived"
    assert _wait_gone(kid), "descendant survived the flood cleanup"
    assert not _drain_threads()

    out, err = capfd.readouterr()
    assert SECRET not in out and SECRET not in err
    assert TUNNEL_URL not in out and TUNNEL_URL not in err
    assert "PGPASSWORD" not in out and "PGPASSWORD" not in err


def test_no_tunnel_process_or_thread_survives_this_module(checker):
    """A leak in any test above shows up here rather than in someone else's."""
    assert not _drain_threads()
    leftovers = subprocess.run(
        ["pgrep", "-f", "fake_railway_tunnel.py"], capture_output=True, text=True
    )
    assert leftovers.returncode == 1, (
        f"fake tunnel processes survived: {leftovers.stdout!r}"
    )
