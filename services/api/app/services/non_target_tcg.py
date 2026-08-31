"""Positive identification of a card from a DIFFERENT trading card game.

DELIBERATELY MIRRORED, NOT SHARED, from
`worker.matching.non_target_tcg` - the api and worker are separate
deployables with no common package, the same reason `app.services.
snkrdunk_urls` and `worker.snkrdunk_urls` are mirrored. The worker half runs
this at DISCOVERY time, to stop a foreign listing becoming a candidate at all.
This half runs it at APPROVAL time, to stop a foreign listing that predates
the filter - or that arrives through some future path - being written into a
mapping and priced. The two must not disagree, so
`tests/test_non_target_tcg_mirror.py` asserts they answer identically over the
documented filename shapes and the shared token table.

The standard is the worker module's and is repeated here because it governs
what this file may ever grow into: it refuses ONLY what it can positively
identify as another game, and every uncertain answer is "keep".

    positively another game  ->  the game's name
    One Piece                ->  None
    unrecognised             ->  None
    no image / no filename   ->  None

There is deliberately NO rule of the form "card code not in the catalogue, so
reject". That fires exactly when Atlas is behind Bandai - a genuinely new One
Piece product, whose codes are absent precisely because it is new.

WHAT COUNTS AS POSITIVE IDENTIFICATION: SNKRDUNK'S OWN ASSET NAMING. The
listing image is served from a CDN path whose filename names the game:

    SVE-TCG-bp08-117.webp          Shadowverse Evolve
    OPC-EN-TCG-OP01-001-of.webp    One Piece
    TCG-OPC-ST01-001.webp          One Piece
    20220903005802-0.webp          an upload timestamp; names nothing

One Piece assets ALSO carry a `TCG` segment and the game token sits on either
side of it, so the match is made on whole hyphen-separated SEGMENTS rather
than on a prefix or a substring. Both conditions must hold before anything is
refused: the filename must carry the `TCG` segment that marks this naming
convention at all, AND one of its segments must be a game this module has been
shown.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Game tokens OBSERVED in SNKRDUNK asset filenames that are not One Piece.
# An allowlist of One Piece tokens would be the wrong shape: it would reject
# every token it has not been shown, including whatever SNKRDUNK names a
# future One Piece product.
_FOREIGN_GAME_TOKENS: dict[str, str] = {
    # 117 candidates from discovery run 9, all BP08-*, every one of them
    # served from `SVE-TCG-bp08-<n>.webp`. Purged from staging 2026-08-30.
    "SVE": "Shadowverse Evolve",
}

# The segment that marks a filename as using SNKRDUNK's game-token convention
# at all. Required, so that an arbitrary filename which merely happens to
# contain a game token is not read as an identity claim.
_CONVENTION_SEGMENT = "TCG"


def _basename(image_url: str | None) -> str | None:
    """The filename with its query string and extension removed."""
    if not image_url:
        return None
    path = urlparse(image_url).path
    name = path.rsplit("/", 1)[-1]
    if not name:
        return None
    return name.rsplit(".", 1)[0] if "." in name else name


def identify_non_target_tcg(image_url: str | None) -> str | None:
    """The name of the OTHER game this listing's asset belongs to, or None.

    None is "not positively another game" and covers every uncertain case -
    One Piece, an unrecognised naming scheme, a timestamp upload, a missing
    image. Callers must treat None as "not disqualified here", never as
    "proven to be One Piece": the proof that a listing is One Piece comes from
    the exact-print gate resolving its card code and product against the Atlas
    catalogue, which holds no other game.
    """
    basename = _basename(image_url)
    if not basename:
        return None
    segments = {segment.upper() for segment in basename.split("-")}
    if _CONVENTION_SEGMENT not in segments:
        return None
    for token, game in _FOREIGN_GAME_TOKENS.items():
        if token in segments:
            return game
    return None


def known_foreign_game_tokens() -> dict[str, str]:
    """The whole table, for tests and audit output."""
    return dict(_FOREIGN_GAME_TOKENS)
