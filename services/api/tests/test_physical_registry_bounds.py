"""Bounded registry transport does not change individual identity validation."""

import json

import pytest

from app.services import physical_artwork_proof as module


def write_registry(tmp_path, monkeypatch, data):
    path = tmp_path / "proofs.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(module, "REGISTRY", path)
    return path


@pytest.mark.parametrize("count", [0, 300, 301, 1000])
def test_bounded_registry_capacity(tmp_path, monkeypatch, count):
    proofs = [{"source_candidate_id": i + 1} for i in range(count)]
    write_registry(
        tmp_path,
        monkeypatch,
        {
            "schema_version": 1,
            "target": "staging",
            "proofs": proofs,
        },
    )
    assert module.registry() == proofs


def test_count_over_bound_refused(tmp_path, monkeypatch):
    write_registry(
        tmp_path,
        monkeypatch,
        {
            "schema_version": 1,
            "target": "staging",
            "proofs": [{}] * 1001,
        },
    )
    with pytest.raises(ValueError, match="bounded"):
        module.registry()


@pytest.mark.parametrize(
    "data",
    [
        [],
        {},
        {"schema_version": 1, "target": "staging", "proofs": {}},
        {"schema_version": 1, "target": "production", "proofs": []},
        {"schema_version": 2, "target": "staging", "proofs": []},
    ],
)
def test_wrong_registry_shape_or_scope_refused(tmp_path, monkeypatch, data):
    write_registry(tmp_path, monkeypatch, data)
    with pytest.raises(ValueError, match="bounded"):
        module.registry()


def test_byte_bound_refuses_even_small_record_count(tmp_path, monkeypatch):
    path = write_registry(
        tmp_path,
        monkeypatch,
        {
            "schema_version": 1,
            "target": "staging",
            "proofs": [],
        },
    )
    monkeypatch.setattr(module, "MAX_REGISTRY_BYTES", path.stat().st_size - 1)
    with pytest.raises(ValueError, match="byte bound"):
        module.registry()


def test_byte_bound_accepts_exact_boundary(tmp_path, monkeypatch):
    path = write_registry(
        tmp_path,
        monkeypatch,
        {
            "schema_version": 1,
            "target": "staging",
            "proofs": [],
        },
    )
    monkeypatch.setattr(module, "MAX_REGISTRY_BYTES", path.stat().st_size)
    assert module.registry() == []
