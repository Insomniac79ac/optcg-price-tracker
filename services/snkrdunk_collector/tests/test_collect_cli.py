"""CLI-arg-level tests for collect.main()'s --allow-unapproved gate: the
combination restriction lives here (batch.run_batch enforces the
validate_only pairing again independently - see test_batch.py), since
argparse rejects a bad combination before any database session opens."""

import pytest

from snkrdunk_collector import collect


def _run_main(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["collect.py"] + argv)
    with pytest.raises(SystemExit) as exc_info:
        collect.main()
    return exc_info.value.code


def test_allow_unapproved_without_validate_only_rejected(monkeypatch, capsys):
    code = _run_main(
        monkeypatch,
        ["--approved-mappings", "--allow-unapproved", "--mapping-ids", "36,37"],
    )
    assert code == 2
    assert "--allow-unapproved requires" in capsys.readouterr().err


def test_allow_unapproved_without_mapping_ids_rejected(monkeypatch, capsys):
    code = _run_main(
        monkeypatch,
        ["--approved-mappings", "--allow-unapproved", "--validate-only"],
    )
    assert code == 2
    assert "--allow-unapproved requires" in capsys.readouterr().err


def test_allow_unapproved_with_mapping_id_mode_rejected(monkeypatch, capsys):
    code = _run_main(
        monkeypatch,
        ["--mapping-id", "36", "--allow-unapproved", "--validate-only"],
    )
    assert code == 2
    assert "--allow-unapproved requires" in capsys.readouterr().err


def test_single_mapping_real_run_is_refused_while_the_lock_is_held(monkeypatch, capsys):
    """`--mapping-id N` without --validate-only writes exactly like a batch,
    so it takes the same single-run lock and no-ops when another run owns it."""
    from snkrdunk_collector import collect as _collect
    from snkrdunk_collector.run_lock import SKIPPED_LOCKED, LockState

    ran = []
    monkeypatch.setattr(_collect, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(
        "snkrdunk_collector.run_lock.collection_lock",
        _fake_lock(acquired=False),
    )
    monkeypatch.setattr(
        _collect, "run_one_mapping_detailed",
        lambda *a, **k: ran.append(1),
    )
    code = _run_main(monkeypatch, ["--mapping-id", "7"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert ran == [], "a refused run must not collect the mapping"
    assert "skipped_locked" in out


def test_single_mapping_validate_only_is_not_locked(monkeypatch, capsys):
    from snkrdunk_collector import collect as _collect

    ran = []
    monkeypatch.setattr(_collect, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(
        "snkrdunk_collector.run_lock.collection_lock",
        _fake_lock(acquired=False),
    )

    def _runner(session, mapping_id, validate_only, **k):
        ran.append(mapping_id)
        from snkrdunk_collector.collect import MappingOutcome

        return MappingOutcome(mapping_id=mapping_id, stage="validated_only", written=False)

    monkeypatch.setattr(_collect, "run_one_mapping_detailed", _runner)
    _run_main(monkeypatch, ["--mapping-id", "7", "--validate-only"])
    assert ran == [7], "validate-only writes nothing and must stay unlocked"


class _FakeSession:
    info: dict = {}

    def get_bind(self):
        return None

    def close(self):
        pass


def _fake_lock(*, acquired: bool):
    from contextlib import contextmanager

    from snkrdunk_collector.run_lock import SKIPPED_LOCKED, LockState

    @contextmanager
    def _lock(engine, *, enabled=True):
        if not enabled:
            yield LockState(acquired=True)
        else:
            yield LockState(acquired=acquired, reason=None if acquired else SKIPPED_LOCKED)

    return _lock


def test_single_mapping_real_run_aborts_when_the_lock_is_lost(monkeypatch, capsys):
    """`--mapping-id N` gets the same fail-closed treatment as a batch: a
    LockLost raised at a mutation boundary stops the run with a clear
    lock_lost status and a non-zero exit, and is never swallowed."""
    from snkrdunk_collector import collect as _collect
    from snkrdunk_collector.run_lock import LockLost

    monkeypatch.setattr(_collect, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(
        "snkrdunk_collector.run_lock.collection_lock", _fake_lock(acquired=True)
    )

    def _boom(*a, **k):
        raise LockLost("collection_lock_lost: backend changed under this run")

    monkeypatch.setattr(_collect, "run_one_mapping_detailed", _boom)
    code = _run_main(monkeypatch, ["--mapping-id", "7"])
    out = capsys.readouterr().out
    assert code == 1, out
    assert "lock_lost" in out
    assert '"written": false' in out.lower()


def test_single_mapping_validate_only_is_unaffected_by_lock_loss_handling(monkeypatch, capsys):
    """Validate-only keeps its exact previous lifecycle: unlocked, unpinned,
    and its session carries no ownership marker to fail on."""
    from snkrdunk_collector import collect as _collect
    from snkrdunk_collector.run_lock import LOCK_PID_INFO_KEY

    seen = {}

    def _runner(session, mapping_id, validate_only, **k):
        seen["marked"] = LOCK_PID_INFO_KEY in getattr(session, "info", {})
        from snkrdunk_collector.collect import MappingOutcome

        return MappingOutcome(mapping_id=mapping_id, stage="validated_only", written=False)

    monkeypatch.setattr(_collect, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(
        "snkrdunk_collector.run_lock.collection_lock", _fake_lock(acquired=True)
    )
    monkeypatch.setattr(_collect, "run_one_mapping_detailed", _runner)
    _run_main(monkeypatch, ["--mapping-id", "7", "--validate-only"])
    assert seen["marked"] is False
