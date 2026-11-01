"""The committed discovery seeds file (owner 2026-11-01): valid, distinct, public product URLs."""

import json

import pytest

from snkrdunk_collector import discovery_seeds


def test_the_committed_seeds_are_valid_and_distinct():
    identities = discovery_seeds.seed_identities()
    assert identities and len(identities) == len(set(identities))
    data = json.loads(discovery_seeds.SEEDS_FILE.read_text(encoding="utf-8"))
    assert all(seed["url"].startswith("https://snkrdunk.com/apparels/") for seed in data["seeds"])


@pytest.mark.parametrize("seeds", [
    [{"release": "OP-05", "url": "https://snkrdunk.com/apparels/1", "title": "t"}],  # unconfirmed
    [{"release": "OP-05", "url": "https://example.com/apparels/1", "title": "t", "confirmed_by": "o"}],
    [{"release": "OP-05", "url": "https://snkrdunk.com/apparels/1", "title": "t", "confirmed_by": "o"}] * 2,
])
def test_a_bad_seeds_file_fails_closed(tmp_path, seeds):
    path = tmp_path / "seeds.json"
    path.write_text(json.dumps({"schema_version": 1, "seeds": seeds}), encoding="utf-8")
    with pytest.raises(ValueError):
        discovery_seeds.seed_identities(path)
