"""The api's foreign-game filter must answer exactly like the worker's.

`app.services.non_target_tcg` is a deliberate mirror of
`worker.matching.non_target_tcg` - the two services are separate deployables
with no shared package. A mirror that drifts is worse than no mirror: the
worker would keep a listing out of the candidate table while the api quietly
approved an equivalent one, or the other way round, and neither service would
report a disagreement.

So this compares them directly where the worker source is on disk (the repo
checkout, and CI), and falls back to pinning the api half against the
documented filename shapes where it is not (a deployed api image ships without
the worker).
"""

import importlib.util
from pathlib import Path

import pytest

from app.services.non_target_tcg import identify_non_target_tcg, known_foreign_game_tokens

_WORKER_MODULE = (
    Path(__file__).resolve().parents[3]
    / "services"
    / "worker"
    / "worker"
    / "matching"
    / "non_target_tcg.py"
)

# Every shape the two modules' docstrings name, plus the ways a naive
# substring or prefix test would go wrong: `SVE` inside a longer segment, a
# game token with no `TCG` segment to mark the convention, and a filename that
# names nothing at all.
_CASES = [
    None,
    "",
    "https://static.snkrdunk.com/SVE-TCG-bp08-117.webp",
    "https://static.snkrdunk.com/sve-tcg-bp08-117.webp",
    "https://static.snkrdunk.com/OPC-EN-TCG-OP01-001-of.webp",
    "https://static.snkrdunk.com/OPC-EN-TCG-OP01-001_p1-of.webp",
    "https://static.snkrdunk.com/TCG-OPC-ST01-001.webp",
    "https://static.snkrdunk.com/20220903005802-0.webp",
    "https://static.snkrdunk.com/SVETCG-bp08-117.webp",
    "https://static.snkrdunk.com/SVE-bp08-117.webp",
    "https://static.snkrdunk.com/SVENSKA-TCG-bp08-117.webp",
    "https://static.snkrdunk.com/TCG.webp",
    "https://static.snkrdunk.com/",
    "https://static.snkrdunk.com/SVE-TCG-bp08-117.webp?w=400",
    "not a url at all",
]


def _worker_half():
    if not _WORKER_MODULE.exists():
        pytest.skip("worker source is not present in this image")
    spec = importlib.util.spec_from_file_location("_worker_non_target_tcg", _WORKER_MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_two_halves_answer_identically():
    worker = _worker_half()
    disagreements = [
        (url, identify_non_target_tcg(url), worker.identify_non_target_tcg(url))
        for url in _CASES
        if identify_non_target_tcg(url) != worker.identify_non_target_tcg(url)
    ]
    assert disagreements == []


def test_the_token_tables_are_the_same():
    """A token added on one side and not the other is the drift that matters
    most: it is silent, and it changes what gets approved."""
    worker = _worker_half()
    assert known_foreign_game_tokens() == worker.known_foreign_game_tokens()


def test_the_api_half_stands_alone():
    """Pinned independently of the worker, so a deployed api without the
    worker source still has these asserted."""
    assert identify_non_target_tcg("https://static.snkrdunk.com/SVE-TCG-bp08-117.webp") == (
        "Shadowverse Evolve"
    )
    # One Piece, an unmarked filename, a token that is only a substring of a
    # segment, and a missing image all mean "not positively another game".
    for url in (
        "https://static.snkrdunk.com/OPC-EN-TCG-OP01-001-of.webp",
        "https://static.snkrdunk.com/TCG-OPC-ST01-001.webp",
        "https://static.snkrdunk.com/20220903005802-0.webp",
        "https://static.snkrdunk.com/SVENSKA-TCG-bp08-117.webp",
        "https://static.snkrdunk.com/SVE-bp08-117.webp",
        None,
    ):
        assert identify_non_target_tcg(url) is None, url
