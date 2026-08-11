"""Field-specific identity authority: where a print's *expected card code*
is allowed to come from.

SNKRDUNK may never supply both sides of its own card-code check. The expected
value is therefore always established from a source independent of the page
being validated, in a fixed order of preference:

  1. Bandai, when card-level evidence exists for the exact card.
  2. A verified Yuyu-Tei product for the SAME card_print, when Bandai has no
     card-level record. Bandai's public card list does not cover every
     collectible print (promos and special products in particular), so
     requiring a Bandai record for every print would block legitimate cards.
  3. Nothing - in which case the caller must fail closed. A missing authority
     is never a reason to fall back on the mapping's own SNKRDUNK-scoped
     fields.

Bandai card-level evidence, in practice
---------------------------------------
`card_prints.image_url` holds Bandai's own official card-list artwork URL, and
Bandai encodes the card code in the path itself:

    https://www.onepiece-cardgame.com/images/cardlist/card/OP04-083.png
    https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001_p2.png

That URL is already fetched and perceptual-hash compared during every
validation run, so the code parsed from it is evidence this collector has
independently exercised - not a value copied out of a spreadsheet. The
optional `_p<n>` suffix distinguishes a parallel treatment's artwork and is
not part of the card code.

Release/set identity does NOT use this hierarchy - Bandai remains its sole
authority. See release_reference.py.
"""

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from snkrdunk_collector.models import CardPrint, Source, SourceCardMapping

BANDAI_CARDLIST_IMAGE_RE = re.compile(
    r"^https://www\.onepiece-cardgame\.com/images/cardlist/card/"
    r"([A-Z]{1,4}\d{0,2}-\d{2,3})(?:_p\d+)?\.png",
    re.IGNORECASE,
)

YUYUTEI_SOURCE_NAME = "yuyutei"

AUTHORITY_BANDAI = "Bandai"
AUTHORITY_YUYUTEI = "Yuyu-Tei"


@dataclass(frozen=True)
class CardCodeAuthority:
    """An expected card code together with where it came from."""

    card_code: str
    authority: str
    evidence_url: str


def card_code_from_bandai_image_url(image_url: str | None) -> str | None:
    """The card code Bandai encodes in its own card-list artwork path, or
    None if this is not a Bandai card-list URL."""
    match = BANDAI_CARDLIST_IMAGE_RE.match((image_url or "").strip())
    return match.group(1).upper() if match else None


def _verified_yuyutei_mapping(session: Session, card_print_id: int) -> SourceCardMapping | None:
    """A Yuyu-Tei product good enough to establish a card code: same exact
    print, active, approved AND manually verified, with a card code actually
    extracted from the source and a product URL to cite.

    manual_verified is required in addition to review_status - review_status
    alone is exactly what the 2026-08-10 incident showed to be insufficient.
    """
    stmt = (
        select(SourceCardMapping)
        .join(Source, Source.id == SourceCardMapping.source_id)
        .where(
            Source.name == YUYUTEI_SOURCE_NAME,
            SourceCardMapping.card_print_id == card_print_id,
            SourceCardMapping.is_active.is_(True),
            SourceCardMapping.review_status == "approved",
            SourceCardMapping.manual_verified.is_(True),
            SourceCardMapping.source_card_id.is_not(None),
            SourceCardMapping.source_url.is_not(None),
        )
        .order_by(SourceCardMapping.id.asc())
    )
    return session.scalars(stmt).first()


def resolve_expected_card_code(
    session: Session, card_print: CardPrint | None
) -> CardCodeAuthority | None:
    """The trusted expected card code for a print, or None when no
    independent authority exists (caller fails closed).

    Never consults the SNKRDUNK mapping being validated.
    """
    if card_print is None:
        return None

    bandai_code = card_code_from_bandai_image_url(card_print.image_url)
    if bandai_code:
        return CardCodeAuthority(
            card_code=bandai_code,
            authority=AUTHORITY_BANDAI,
            evidence_url=card_print.image_url,
        )

    yuyutei = _verified_yuyutei_mapping(session, card_print.id)
    if yuyutei is not None and (yuyutei.source_card_id or "").strip():
        return CardCodeAuthority(
            card_code=yuyutei.source_card_id.strip().upper(),
            authority=AUTHORITY_YUYUTEI,
            evidence_url=yuyutei.source_url,
        )

    return None
