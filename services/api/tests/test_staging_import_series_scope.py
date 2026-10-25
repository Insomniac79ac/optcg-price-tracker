"""The staging import runner's --series scope and the two seams the ops runbook uses.

Hermetic: a tiny snapshot written here, the target authority and the planner stubbed, so the
run stops before any database is reached.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import import_frozen_bandai_to_canonical_staging as runner
from app.services import canonical_import_apply as A
from app.services import canonical_staging_target as T


def _snapshot(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "manifest.json").write_text(
        json.dumps({"source_catalogue": "bandai_jp", "started_at": "s", "finished_at": "f"})
    )
    series = [
        {"source_series_id": "550101", "display_name": "ROMANCE DAWN【OP-01】", "official_code": "OP-01"},
        {"source_series_id": "550205", "display_name": "Heroines【EB-05】", "official_code": "EB-05"},
        {"source_series_id": "550901", "display_name": "プロモーションカード", "official_code": None},
    ]
    entries = [
        {"entry_id": "OP01-001", "card_code": "OP01-001", "source_series_id": "550101"},
        {"entry_id": "EB05-001", "card_code": "EB05-001", "source_series_id": "550205"},
        {"entry_id": "EB05-001_p1", "card_code": "EB05-001", "source_series_id": "550205"},
        {"entry_id": "OP01-001_p9", "card_code": "OP01-001", "source_series_id": "550901"},
    ]
    (root / "series.jsonl").write_text("\n".join(json.dumps(r) for r in series))
    (root / "entries.jsonl").write_text("\n".join(json.dumps(r) for r in entries))
    (root / "assets.jsonl").write_text("")
    return root


class _Stop(Exception):
    pass


def _stub_target(monkeypatch, seen):
    class _Target:
        attestation = A.StagingTargetAttestation(
            railway_environment="staging", railway_service="Postgres", database="railway",
            db_revision="rev", checks=(("fingerprint", True),),
        )
        url = "postgresql://u:p@localhost:1/db"
        redacted = "localhost:1/db"

        def close(self):
            seen["closed"] = True

    def _verified(**kwargs):
        seen["checker"] = kwargs.get("checker")
        return _Target()

    monkeypatch.setattr(runner.target_authority, "verified_staging_target", _verified)


def test_series_scope_plans_only_that_series_with_whole_snapshot_sibling_counts(tmp_path, monkeypatch):
    root = _snapshot(tmp_path / "bandai_jp" / "current")
    seen: dict = {}
    _stub_target(monkeypatch, seen)

    def _plan(_session, entries, **kwargs):
        seen["entries"] = [e.entry_id for e in entries]
        seen["siblings"] = kwargs["sibling_counts"]
        raise _Stop()

    monkeypatch.setattr(runner, "plan_entries", _plan)
    code = runner.main(
        ["--snapshot-root", str(root), "--series", "550205", "--json"],
        open_tunnel=lambda service, environment: f"postgresql://u:p@proxy:1/{service}-{environment}",
    )

    assert code == runner.EXIT_FAILED  # the stub stopped it, nothing ran past planning
    assert seen["entries"] == ["EB05-001", "EB05-001_p1"]
    assert seen["siblings"]["OP01-001"] == 2  # counted over the whole snapshot, not the scope
    assert seen["closed"]
    # Only how the connection is reached changes; the real checker decides acceptance.
    rerouted = seen["checker"]
    assert isinstance(rerouted, T.ReroutedChecker)
    assert rerouted.open_tunnel("Postgres", "staging") == (None, "postgresql://u:p@proxy:1/Postgres-staging")
    assert rerouted.evaluate.__code__.co_filename == str(T.STAGING_CHECKER)
    assert rerouted.collect_facts.__code__.co_filename == str(T.STAGING_CHECKER)
    assert rerouted.REFUSED_ENVIRONMENTS == T.load_staging_checker().REFUSED_ENVIRONMENTS


def test_without_open_tunnel_the_target_authority_gets_no_checker(tmp_path, monkeypatch):
    root = _snapshot(tmp_path / "bandai_jp" / "current")
    seen: dict = {}
    _stub_target(monkeypatch, seen)
    monkeypatch.setattr(runner, "plan_entries", lambda *_a, **_k: (_ for _ in ()).throw(_Stop()))
    runner.main(["--snapshot-root", str(root), "--series", "550205", "--json"])
    assert seen["checker"] is None


def test_a_repeated_entry_id_refuses_the_series_scope(tmp_path, monkeypatch, capsys):
    root = _snapshot(tmp_path / "bandai_jp" / "current")
    with (root / "entries.jsonl").open("a") as handle:
        handle.write("\n" + json.dumps({"entry_id": "EB05-001", "card_code": "EB05-001", "source_series_id": "550101"}))
    monkeypatch.setattr(
        runner.target_authority, "verified_staging_target",
        lambda **_k: (_ for _ in ()).throw(AssertionError("no target may be resolved")),
    )
    assert runner.main(["--snapshot-root", str(root), "--series", "550205"]) == runner.EXIT_USAGE
    assert "repeats an entry id" in capsys.readouterr().err


def test_on_plan_runs_before_the_applier_and_a_raise_writes_nothing(tmp_path, monkeypatch):
    root = _snapshot(tmp_path / "bandai_jp" / "current")
    seen: dict = {}
    _stub_target(monkeypatch, seen)
    monkeypatch.setattr(runner, "plan_entries", lambda *_a, **_k: "the-plan")

    def _no_applier(*_a, **_k):
        raise AssertionError("the applier must not be constructed")

    monkeypatch.setattr(runner, "CanonicalImportApplier", _no_applier)

    def _on_plan(plan):
        seen["plan"] = plan
        raise RuntimeError("plan differs from the reviewed dry run")

    code = runner.main(["--snapshot-root", str(root), "--series", "550205", "--json"], on_plan=_on_plan)

    assert code == runner.EXIT_FAILED
    assert seen["plan"] == "the-plan"


@pytest.mark.parametrize(
    "series, reason",
    [("559999", "not a series in the snapshot"), ("550901", "uncoded catch-all")],
)
def test_unknown_or_uncoded_series_refuse_before_any_connection(tmp_path, monkeypatch, capsys, series, reason):
    root = _snapshot(tmp_path / "bandai_jp" / "current")

    def _never(**_kwargs):
        raise AssertionError("no target may be resolved")

    monkeypatch.setattr(runner.target_authority, "verified_staging_target", _never)
    code = runner.main(["--snapshot-root", str(root), "--series", series])

    assert code == runner.EXIT_USAGE
    assert reason in capsys.readouterr().err
