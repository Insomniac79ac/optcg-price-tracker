"""Positive identification of a card from a DIFFERENT trading card game.

WHY THIS EXISTS. Discovery run 9 pulled in 117 Shadowverse Evolve listings and
made candidates of them. They got that far because the only test standing
between a page and a candidate row was `ListingEvidence.is_one_piece`, which
asks whether a bracketed card code was found at all - and Shadowverse writes
its codes in exactly the One Piece shape, `[BP08-117]`. Structure alone cannot
separate the two games, and nothing downstream ever recovers: the codes match
no canonical card, so all 117 sat permanently in `card_code_not_in_catalogue`.

THE STANDARD THIS MODULE HOLDS ITSELF TO, and the reason it is narrow.

A filter on the way into the candidate table is a filter on what a human will
ever be shown. Discarding a real One Piece listing is therefore the expensive
error - it is silent, and there is no queue it lands in to be noticed - while
keeping a foreign listing costs only a row someone has to look at. So this
module refuses ONLY what it can positively identify as another game, and every
uncertain answer is "keep":

    positively another game  ->  the game's name, and discovery drops it
    One Piece                ->  None, kept
    unrecognised             ->  None, kept
    no image / no filename   ->  None, kept

There is deliberately NO rule of the form "card code not in the catalogue, so
reject". That would fail exactly when Atlas is behind Bandai - a genuinely new
One Piece product, whose codes are absent precisely because it is new - and it
would delete the evidence that the catalogue needs updating. An unknown One
Piece-looking listing must remain a candidate for review.

WHAT COUNTS AS POSITIVE IDENTIFICATION: SNKRDUNK'S OWN ASSET NAMING. The
listing image is served from a CDN path whose filename names the game:

    SVE-TCG-bp08-117.webp          Shadowverse Evolve
    OPC-EN-TCG-OP01-001-of.webp    One Piece
    OPC-EN-TCG-OP01-001_p1-of.webp One Piece
    TCG-OPC-ST01-001.webp          One Piece
    20220903005802-0.webp          an upload timestamp; names nothing

That is the source stating the product's identity in its own words, which is
strictly better evidence than anything inferred from a code prefix or a
translated product title - the same "identity by explicit evidence, never by
inference" standard the product aliases are held to.

Note the second and fourth shapes: One Piece assets ALSO carry a `TCG`
segment, and the game token sits on either side of it. So the match is made on
whole hyphen-separated SEGMENTS rather than on a prefix or a substring. A
substring test for "SVE" would fire on any filename that happened to contain
those three letters; a segment test cannot.

Both conditions must hold before anything is refused: the filename must carry
the `TCG` segment that marks this naming convention at all, AND one of its
segments must be a game this module has been shown. A filename that satisfies
only one of them is not understood, and not understood means kept.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Game tokens OBSERVED in SNKRDUNK asset filenames that are not One Piece,
# mapped to the name reported to the operator.
#
# An allowlist of One Piece tokens would be the wrong shape here: it would
# reject every token it has not been shown, including whatever SNKRDUNK names
# a future One Piece product, which is the error this module must not make.
# So the table lists what is known to be FOREIGN, and its absence means keep.
_FOREIGN_GAME_TOKENS: dict[str, str] = {
    # 117 candidates from discovery run 9, all
    # 'Booster Pack Vol.8 "Chaotic Dimensions"', all BP08-*, every one of them
    # served from `SVE-TCG-bp08-<n>.webp`.
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
    image. Callers must treat None as "keep", never as "assume One Piece".
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
