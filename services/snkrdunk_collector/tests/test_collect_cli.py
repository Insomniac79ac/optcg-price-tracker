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
