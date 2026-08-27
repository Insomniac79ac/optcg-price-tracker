"""The gate every NEW source-mapping approval passes through.

WHY THIS EXISTS. A source listing is priced against a *printing*, not against
a card code. The legacy `cards` table holds 25 rows; the print catalogue holds
4,281. Approving a Yuyu-Tei or SNKRDUNK listing to a `card_id` therefore says
almost nothing about which physical item was priced, and the 2026-08-27 audit
found the two approval endpoints writing exactly that - `card_id` only, with
`card_print_id` left NULL on every row they create.

The rule this module enforces is narrow and absolute: an approval names an
exact `card_print_id`, and that print must be *corroborated by the source's
own evidence* before anything is written.

WHY A CARD-CODE MATCH IS NOT ENOUGH, stated as the code sees it. One card code
routinely spans many prints. OP02-013 on staging is five: the OP-02 base, an
OP-02 `p1` and `p2`, a `r1` reprint carried in PRB-01, and an `SPカード` `p3`
from OP-08. A listing whose only evidence is "OP02-013" is consistent with all
five and identifies none of them. Selecting one anyway - by first, by lowest
id, by most common, by newest - would be inventing a fact about which item was
priced. So when the available evidence leaves more than one print standing,
this module refuses and asks for review. It never breaks a tie.

The operator's explicit choice is required but is NOT self-justifying: the
chosen print still has to survive the evidence filter. A human clicking the
wrong row is precisely the failure this is here to catch.

WHAT IT DELIBERATELY DOES NOT DO. It does not fetch anything, does not create
price observations, does not touch the 74 existing mappings, and does not
invent a uniqueness rule - duplicate protection is already the database's
`uq_source_card_mappings_source_url` UNIQUE (source_id, source_url), and that
constraint is what stops one listing reaching two prints.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CanonicalCard, CardPrint

# Machine-readable refusal codes. They are part of the endpoint contract - the
# admin UI branches on them - so they are named here rather than spelled out
# at each raise site.
REFUSAL_PRINT_REQUIRED = "card_print_id_required"
REFUSAL_PRINT_NOT_FOUND = "print_not_found"
REFUSAL_PRINT_INACTIVE = "print_inactive"
REFUSAL_PRINT_UNVERIFIED = "print_unverified"
REFUSAL_NO_SOURCE_CARD_CODE = "source_card_code_missing"
REFUSAL_CARD_CODE_MISMATCH = "card_code_mismatch"
REFUSAL_EVIDENCE_CONTRADICTS = "evidence_contradicts_selection"
REFUSAL_AMBIGUOUS = "evidence_cannot_distinguish_print"
# A row that predates exact prints being written, asked to become approved.
# Distinct from REFUSAL_PRINT_REQUIRED, which is about a missing request
# field: here the request is well formed and it is the ROW that cannot
# support approval.
REFUSAL_LEGACY_MAPPING_HAS_NO_PRINT = "mapping_has_no_card_print"

# Refusals that mean "a human needs to look at this", as opposed to "the
# request was malformed". Callers map these onto review_status='needs_review'.
NEEDS_REVIEW_REFUSALS = frozenset(
    {
        REFUSAL_NO_SOURCE_CARD_CODE,
        REFUSAL_AMBIGUOUS,
        REFUSAL_EVIDENCE_CONTRADICTS,
        REFUSAL_LEGACY_MAPPING_HAS_NO_PRINT,
    }
)


def _norm(value: str | None) -> str | None:
    """Upper-cased, stripped, with the separators sources vary on removed.

    Sources write a set code as `OP-02`, `OP02` or `op 02` interchangeably;
    none of that is a difference in fact. Returns None for anything that is
    empty once stripped, so a blank string can never match a real value.
    """
    if value is None:
        return None
    cleaned = value.strip().upper().replace("-", "").replace("_", "").replace(" ", "")
    return cleaned or None


@dataclass(frozen=True)
class SourceEvidence:
    """What the source actually told us about the item it is selling.

    Every field is optional because sources genuinely omit them - that is the
    point. Absent evidence narrows nothing; it never counts as agreement.
    """

    source_name: str
    source_url: str | None = None
    card_code: str | None = None
    set_code: str | None = None
    variant: str | None = None
    rarity: str | None = None
    title: str | None = None

    @classmethod
    def from_snkrdunk_candidate(cls, candidate) -> "SourceEvidence":
        """The SNKRDUNK candidate row, read as evidence.

        These are the fields the discovery/parse step already persisted; this
        reads them, and fetches nothing.
        """
        return cls(
            source_name="snkrdunk",
            source_url=candidate.source_url,
            card_code=candidate.detected_card_code,
            set_code=candidate.detected_set_code,
            variant=candidate.detected_variant,
            rarity=candidate.detected_rarity,
            title=candidate.title,
        )


class ExactPrintApprovalError(Exception):
    """A refusal, carrying enough for the operator to act on it.

    `alternatives` lists the print ids that survived the evidence filter, so
    an ambiguous refusal tells the operator exactly which printings the source
    failed to distinguish rather than just declining.
    """

    def __init__(self, code: str, detail: str, alternatives: list[int] | None = None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.alternatives = alternatives or []

    @property
    def needs_review(self) -> bool:
        return self.code in NEEDS_REVIEW_REFUSALS


@dataclass
class ApprovalDecision:
    """An approval that passed. `evidence_used` is the audit trail: which
    facts actually did the narrowing, recorded so a later reader can tell a
    corroborated approval from a lucky one."""

    card_print: CardPrint
    canonical: CanonicalCard
    evidence_used: list[str] = field(default_factory=list)
    considered_print_ids: list[int] = field(default_factory=list)

    def as_review_note(self) -> str:
        return (
            f"Exact print {self.card_print.id} approved on "
            + ", ".join(self.evidence_used)
            + f" (distinguished from {len(self.considered_print_ids)} print(s) sharing the card code)."
        )


def sibling_prints_for_card_code(db: Session, card_code: str) -> list[tuple[CardPrint, CanonicalCard]]:
    """Every active, verified print that shares this card code.

    Joined through CanonicalCard because the code lives there, and matched on
    the code rather than on canonical_card_id: the JP and EN catalogues are
    scoped separately, so one code can legitimately reach more than one
    canonical card. Widening the sibling set can only ever make this module
    more cautious, never less.
    """
    rows = db.execute(
        select(CardPrint, CanonicalCard)
        .join(CanonicalCard, CanonicalCard.id == CardPrint.canonical_card_id)
        .where(
            CardPrint.is_active.is_(True),
            CardPrint.verification_status == "verified",
        )
    ).all()
    target = _norm(card_code)
    return [(p, c) for p, c in rows if _norm(c.card_code) == target]


def assert_print_is_priceable(db: Session, card_print_id: int) -> CardPrint:
    """The three facts a print must satisfy before any mapping may point at it.

    Shared by the candidate approval paths and by the status-transition guard
    on the admin mapping endpoints, so "approved" means the same thing however
    a row reaches it. A print that is missing, deactivated, or not yet verified
    has no settled product and official artwork to price against.
    """
    print_row = db.get(CardPrint, card_print_id)
    if print_row is None:
        raise ExactPrintApprovalError(
            REFUSAL_PRINT_NOT_FOUND, f"card_print {card_print_id} does not exist."
        )
    if not print_row.is_active:
        raise ExactPrintApprovalError(
            REFUSAL_PRINT_INACTIVE, f"card_print {card_print_id} is not active."
        )
    if print_row.verification_status != "verified":
        raise ExactPrintApprovalError(
            REFUSAL_PRINT_UNVERIFIED,
            f"card_print {card_print_id} is {print_row.verification_status!r}, not verified. "
            "Only a verified print has a settled product and official artwork to price against.",
        )
    return print_row


def resolve_exact_print(
    db: Session,
    *,
    card_print_id: int | None,
    evidence: SourceEvidence,
) -> ApprovalDecision:
    """Resolve and corroborate the exact print for a new mapping approval.

    Raises ExactPrintApprovalError on every path that cannot prove the print.
    Returns only when the source's own evidence narrows the catalogue to
    exactly the print the operator named.
    """
    if card_print_id is None:
        raise ExactPrintApprovalError(
            REFUSAL_PRINT_REQUIRED,
            "card_print_id is required: a mapping must name the exact printing it prices.",
        )

    print_row = assert_print_is_priceable(db, card_print_id)

    canonical = db.get(CanonicalCard, print_row.canonical_card_id)
    if canonical is None:  # pragma: no cover - FK makes this unreachable
        raise ExactPrintApprovalError(
            REFUSAL_PRINT_NOT_FOUND,
            f"card_print {card_print_id} has no canonical card.",
        )

    # Identity has to start somewhere, and the card code is the only thing
    # every source publishes. Without one there is nothing to anchor to, and
    # guessing from a free-text title is exactly the inference this forbids.
    if _norm(evidence.card_code) is None:
        raise ExactPrintApprovalError(
            REFUSAL_NO_SOURCE_CARD_CODE,
            "The source evidence carries no card code, so the listing cannot be tied to a "
            "printing. Resolve the card code on the candidate first.",
        )
    if _norm(evidence.card_code) != _norm(canonical.card_code):
        raise ExactPrintApprovalError(
            REFUSAL_CARD_CODE_MISMATCH,
            f"Source reports card code {evidence.card_code!r} but card_print "
            f"{card_print_id} is {canonical.card_code!r}.",
        )

    siblings = sibling_prints_for_card_code(db, canonical.card_code)
    considered = sorted(p.id for p, _ in siblings)
    evidence_used = [f"card code {canonical.card_code}"]

    # Narrow only on identity-bearing evidence. `release_product_code` is the
    # product this printing shipped in and `official_asset_variant` is which
    # official asset it carries - the two facts that actually separate
    # printings of one card. Rarity is descriptive and is deliberately not a
    # discriminator here.
    surviving = list(siblings)
    if _norm(evidence.set_code) is not None:
        surviving = [
            (p, c) for p, c in surviving if _norm(p.release_product_code) == _norm(evidence.set_code)
        ]
        evidence_used.append(f"product {evidence.set_code}")
    if _norm(evidence.variant) is not None:
        surviving = [
            (p, c)
            for p, c in surviving
            if _norm(p.official_asset_variant) == _norm(evidence.variant)
        ]
        evidence_used.append(f"asset variant {evidence.variant}")

    surviving_ids = sorted(p.id for p, _ in surviving)

    if not surviving_ids:
        raise ExactPrintApprovalError(
            REFUSAL_EVIDENCE_CONTRADICTS,
            "No active verified print matches the source's product/variant evidence "
            f"(card code {canonical.card_code}, product {evidence.set_code!r}, "
            f"variant {evidence.variant!r}).",
            alternatives=considered,
        )
    if card_print_id not in surviving_ids:
        raise ExactPrintApprovalError(
            REFUSAL_EVIDENCE_CONTRADICTS,
            f"The source evidence does not describe card_print {card_print_id}. "
            f"It is consistent with {surviving_ids} instead.",
            alternatives=surviving_ids,
        )
    if len(surviving_ids) > 1:
        # The whole point. The operator may well be right, but nothing in the
        # source proves it, and a mapping is a claim about which item was
        # priced.
        raise ExactPrintApprovalError(
            REFUSAL_AMBIGUOUS,
            f"Card code {canonical.card_code} matches {len(surviving_ids)} active verified "
            f"prints ({surviving_ids}) and the source evidence does not distinguish them. "
            "Approving would be a guess; resolve the product or artwork evidence first.",
            alternatives=surviving_ids,
        )

    return ApprovalDecision(
        card_print=print_row,
        canonical=canonical,
        evidence_used=evidence_used,
        considered_print_ids=considered,
    )


# --- operator-facing labels ---------------------------------------------------
# These mirror apps/web/src/lib/terminology.ts, and mirror it deliberately
# rather than inventing a second vocabulary: the operator approving a mapping
# should be reading the same words a collector reads on the tile, or the two
# surfaces disagree about what the card is. Kept narrow - only the labels the
# approval screen needs - so the frontend module stays the single place the
# full terminology system lives.

# Both published Japanese tokens name one collector-facing category; the
# English catalogue publishes both as SP CARD. TR stays separate: it is a
# distinct, language-specific token in both catalogues.
_SPECIAL_PRINT_LABELS = {
    "SPカード": "SP Card",
    "SP P": "SP Card",
    "SP CARD": "SP Card",
    "TR": "Treasure Rare",
}


def special_print_label(print_row: CardPrint, canonical: CanonicalCard) -> str | None:
    """The special-printing category, or None for an ordinary print.

    Reads the print's own official rarity first and falls back to the card's,
    because the special-print token is published in the rarity column - which
    is exactly why it has to be lifted out into its own dimension here.
    """
    for raw in (print_row.official_rarity, canonical.rarity):
        if raw and raw.strip() in _SPECIAL_PRINT_LABELS:
            return _SPECIAL_PRINT_LABELS[raw.strip()]
    return None


def printing_label(print_row: CardPrint) -> str | None:
    """Which printing this is, from the official asset address.

    `base` is the ordinary printing and gets no label - its absence is the
    signal. An unrecognised address returns None rather than a guess: the
    variant is an address, never a classification.
    """
    variant = (print_row.official_asset_variant or "").strip().lower()
    if not variant or variant == "base":
        return None
    if variant.startswith("p") and variant[1:].isdigit():
        return "Alt Art"
    if variant.startswith("r") and variant[1:].isdigit():
        return "Reprint"
    return None
