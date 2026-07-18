"""python -m app.prune_data_retention - see app.prune_data_retention and
app.services.data_retention."""

from datetime import datetime, timedelta, timezone

import app.prune_data_retention as cli_module
from app.models import RawSnapshot, Source

NOW = datetime.now(timezone.utc)


def make_source(db_session, name: str = "yuyutei") -> Source:
    source = Source(name=name, base_url=f"https://{name}.example.com")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def _old_raw_snapshot(db_session) -> None:
    source = make_source(db_session)
    db_session.add(
        RawSnapshot(
            source_id=source.id,
            source_url="https://example.com/old",
            fetched_at=NOW - timedelta(days=100),
            http_status=200,
            content_hash="old",
            raw_content="<html></html>",
        )
    )
    db_session.commit()


def test_cli_dry_run_default_does_not_delete(db_session, monkeypatch, capsys):
    monkeypatch.setattr(cli_module, "SessionLocal", lambda: db_session)
    _old_raw_snapshot(db_session)

    exit_code = cli_module.main(["--tables", "raw_snapshots"])

    assert exit_code == 0
    assert db_session.query(RawSnapshot).count() == 1
    out = capsys.readouterr().out
    assert "dry_run=True" in out
    assert "rows_would_delete=1" in out
    assert "rows_deleted=0" in out


def test_cli_apply_without_confirm_fails(db_session, monkeypatch, capsys):
    monkeypatch.setattr(cli_module, "SessionLocal", lambda: db_session)
    _old_raw_snapshot(db_session)

    exit_code = cli_module.main(["--apply", "--tables", "raw_snapshots"])

    assert exit_code == 1
    assert db_session.query(RawSnapshot).count() == 1
    err = capsys.readouterr().err
    assert "confirm" in err.lower()


def test_cli_apply_with_wrong_confirm_fails(db_session, monkeypatch):
    monkeypatch.setattr(cli_module, "SessionLocal", lambda: db_session)
    _old_raw_snapshot(db_session)

    exit_code = cli_module.main(["--apply", "--confirm", "nope", "--tables", "raw_snapshots"])

    assert exit_code == 1
    assert db_session.query(RawSnapshot).count() == 1


def test_cli_apply_with_confirm_deletes(db_session, monkeypatch, capsys):
    monkeypatch.setattr(cli_module, "SessionLocal", lambda: db_session)
    _old_raw_snapshot(db_session)

    exit_code = cli_module.main(["--apply", "--confirm", "PRUNE", "--tables", "raw_snapshots"])

    assert exit_code == 0
    assert db_session.query(RawSnapshot).count() == 0
    out = capsys.readouterr().out
    assert "rows_deleted=1" in out


def test_cli_defaults_to_all_prunable_tables(db_session, monkeypatch, capsys):
    monkeypatch.setattr(cli_module, "SessionLocal", lambda: db_session)

    exit_code = cli_module.main([])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "raw_snapshots" in out
    assert "market_signal_events" in out
