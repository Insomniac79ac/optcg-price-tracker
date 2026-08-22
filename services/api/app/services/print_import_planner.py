"""Plans - never performs - the import of exact Japanese Bandai prints.

This module answers one question: *given what the official JP Card List
publishes, and what Atlas already holds, what would have to be created?* It
returns that answer as data. It contains no INSERT, UPDATE or DELETE, calls no
`Session.add`/`flush`/`commit`, and is expected to run inside a read-only
database session (see app.plan_canonical_print_import).

Why a planner exists at all
---------------------------
The exact-print identity went live on 2026-08-22:

    (canonical_card_id, language, release_product_id, official_asset_variant)

Every component of that key is a fact somebody has to establish *before* a row
can be written. Getting one wrong does not fail loudly - it silently creates a
duplicate print, or silently attaches prices to the wrong physical printing.
So the establishing step is separated from the writing step, and this is the
establishing step.

What is authoritative here
--------------------------
The Japanese official Card List, and nothing else. Yuyu-Tei, SNKRDUNK, price
similarity and Atlas's own `treatment` labels are all excluded from physical
print identity by construction: none of them is read by any code path below
that produces an identity component. Source mappings are inspected, but only
to *classify* them for a human (see classify_lineage_less_mappings); a mapping
can never move a planned print's identity.

The two refusals that matter
----------------------------
1. `treatment` is never inferred from `_pN`. Bandai's suffix numbers artworks;
   it does not name a finish. A genuinely new printing is planned with
   treatment NULL, and NULL is a legitimate state for a *verified* print under
   the live schema. The only treatment a plan ever carries is one Atlas
   already recorded on an exact match.
2. A product is never identified by its prose. Coded products are matched on
   `(source_catalogue, official_code)`; uncoded ones are matched only on an
   exact frozen-name match against evidence already accepted into
   `release_products`, and otherwise get a *proposed new* product whose real
   identity is the surrogate id a future write step would assign.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CanonicalCard, Card, CardPrint, ReleaseProduct, Source, SourceCardMapping
from app.services.official_asset_variant import parse_official_asset_variant
from app.services.official_cardlist import (
    OfficialCardEntry,
    OfficialSeries,
    product_code_from_display_name,
)

# The only language this catalogue can establish. The JP Card List is the JP
# printing; a print in another language is a different catalogue's evidence.
LANGUAGE = "jp"

# --- outcome vocabulary -----------------------------------------------------
#
# Deliberately four outcomes and a separate set of creations, rather than one
# flat list containing both "create_card_print" and "create_multiple". A flat
# list has to grow a new member for every combination, and "create_multiple"
# hides *which* things - so the caller ends up re-deriving the detail anyway.
# Here the outcome says what a human must do, and `creations` says exactly
# what a write step would have to make. `PlannedPrint.action` still renders
# the flat label for anyone who wants it.

OUTCOME_NO_CHANGE = "no_change"
OUTCOME_CREATE = "create"
OUTCOME_NEEDS_REVIEW = "needs_review"
OUTCOME_CONFLICT = "conflict"

CREATE_RELEASE_PRODUCT = "release_product"
CREATE_CANONICAL_CARD = "canonical_card"
CREATE_CARD_PRINT = "card_print"

# --- flags ------------------------------------------------------------------
# Facts about a plan that a human may need to act on, kept separate from the
# outcome so that several can be true at once.

FLAG_ASSET_CHANGED = "asset_changed"
FLAG_MALFORMED_ASSET = "malformed_asset"
FLAG_ENTRY_ASSET_MISMATCH = "entry_asset_mismatch"
FLAG_UNCODED_PRODUCT = "uncoded_product"
FLAG_NEW_PRODUCT_PROPOSED = "new_product_proposed"
FLAG_MULTIPLE_PRODUCTS = "multiple_products"
FLAG_CANONICAL_CARD_CONFLICT = "canonical_card_conflict"
FLAG_CANONICAL_CARD_PLANNED = "canonical_card_planned"
FLAG_DIGEST_NOT_ESTABLISHED = "artwork_digest_not_established"
FLAG_SIBLING_VARIANTS = "sibling_variants_present"
FLAG_MALFORMED_ENTRY = "malformed_entry"
# Bandai publishes rarity per *entry*, not per card: a card reprinted into a
# later set can carry 'SPカード' there while its own set lists it as 'SR'
# (observed 2026-08-22 on OP02-013_p3 in OP-08, OP04-024_p2 in OP-06 and
# OP04-044_p2 in OP-05). Atlas records rarity on the canonical card, so that
# difference is information about a printing - not evidence that the canonical
# card is wrong, and not an identity component. It is surfaced, not blocking.
FLAG_RARITY_DIFFERS_BY_PRINTING = "rarity_differs_by_printing"

# --- lineage-less source mapping classification ------------------------------

MAPPING_EXACT_CANDIDATE = "exact_candidate"
MAPPING_PROBABLE = "probable"
MAPPING_AMBIGUOUS = "ambiguous"
MAPPING_UNRELATED = "unrelated"

VERIFIED = "verified"
NEEDS_REVIEW = "needs_review"


def original_set_code(card_code: str) -> str | None:
    """Atlas's set code for a card, read out of the card code itself.

    `OP01-001` -> `OP-01`, matching every canonical_cards row present on
    staging (checked 2026-08-22). This is a re-spelling of evidence Bandai
    already supplies in the code, not a lookup and not an invention: the
    letters and digits both come from the code's own prefix.
    """
    code = (card_code or "").strip().upper()
    prefix, _, _ = code.partition("-")
    if not prefix:
        return None
    letters = "".join(c for c in prefix if c.isalpha())
    digits = "".join(c for c in prefix if c.isdigit())
    if not letters or not digits:
        return None
    return f"{letters}-{digits}"


def _card_type_from_category(category: str | None) -> str | None:
    """Bandai's shouting category as Atlas spells it: `LEADER` -> `Leader`.

    Capitalisation only. No mapping table, because inventing one would let a
    category Bandai adds tomorrow be silently renamed into an Atlas word.
    """
    value = (category or "").strip()
    return value.title() if value else None


@dataclass(frozen=True)
class ProposedCanonicalCard:
    """The canonical card a write step would create, from Bandai fields only."""

    card_code: str
    name_jp: str
    original_set_code: str | None
    rarity: str | None
    card_type: str | None


@dataclass(frozen=True)
class ProposedReleaseProduct:
    """The product a write step would create.

    There is no `id` and no natural key: identity is the surrogate id assigned
    at write time. `first_seen_name` is the verbatim evidence that would create
    the row and is frozen thereafter.
    """

    source_catalogue: str
    official_code: str | None
    display_name: str
    first_seen_name: str
    source_series_id: str | None
    source_url: str | None


@dataclass(frozen=True)
class PlannedPrint:
    """One official artwork, resolved against Atlas. Pure data."""

    # -- authority
    source_catalogue: str
    source_series_id: str | None
    source_url: str | None
    entry_id: str

    # -- product as Bandai names it for this entry
    official_product_code: str | None
    official_product_display_name: str | None

    # -- card as Bandai publishes it
    card_code: str
    official_card_name: str
    language: str
    official_image_url: str | None
    official_asset_variant: str | None
    official_artwork_sha256: str | None

    # -- Atlas descriptive metadata, never derived from the suffix
    treatment: str | None

    # -- what Atlas already holds
    existing_canonical_card_id: int | None
    existing_release_product_id: int | None
    existing_card_print_id: int | None

    # -- the plan
    outcome: str
    creations: tuple[str, ...]
    verification_status: str
    flags: tuple[str, ...]
    reasons: tuple[str, ...]

    proposed_canonical_card: ProposedCanonicalCard | None = None
    proposed_release_product: ProposedReleaseProduct | None = None

    @property
    def action(self) -> str:
        """The flat label, for callers that want the small vocabulary."""
        if self.outcome == OUTCOME_CONFLICT:
            return OUTCOME_CONFLICT
        if self.outcome == OUTCOME_NEEDS_REVIEW:
            return NEEDS_REVIEW
        if self.outcome == OUTCOME_NO_CHANGE:
            return OUTCOME_NO_CHANGE
        if len(self.creations) > 1:
            return "create_multiple"
        if self.creations:
            return f"create_{self.creations[0]}"
        return OUTCOME_NO_CHANGE

    def to_dict(self) -> dict:
        document = asdict(self)
        document["action"] = self.action
        return document


@dataclass(frozen=True)
class ClassifiedMapping:
    """A lineage-less source mapping, judged against a planned print.

    Judgement only. Nothing here attaches, edits or scores a mapping, and the
    classification never feeds back into the print's identity.
    """

    mapping_id: int
    source_name: str | None
    source_card_id: str | None
    source_url: str | None
    legacy_card_code: str | None
    review_status: str
    classification: str
    reason: str


@dataclass
class ImportPlan:
    """Everything one planning run established."""

    prints: list[PlannedPrint] = field(default_factory=list)
    mappings: list[ClassifiedMapping] = field(default_factory=list)

    def by_outcome(self, outcome: str) -> list[PlannedPrint]:
        return [p for p in self.prints if p.outcome == outcome]

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for planned in self.prints:
            counts[planned.outcome] = counts.get(planned.outcome, 0) + 1
        return counts


# A caller-supplied way to learn an official asset's SHA-256. Injected rather
# than imported so the planner itself never performs I/O: tests pass a dict's
# lookup, the CLI passes a network fetcher, and passing nothing is a supported
# mode that simply cannot establish `artwork_key` evidence.
DigestProvider = Callable[[str], str | None]


class PrintImportPlanner:
    """Resolves official Card List entries against Atlas. Read-only."""

    def __init__(
        self,
        session: Session,
        *,
        source_catalogue: str = "bandai_jp",
        digest_provider: DigestProvider | None = None,
    ) -> None:
        self._session = session
        self._catalogue = source_catalogue
        self._digest_provider = digest_provider

    # -- lookups (all SELECT) ---------------------------------------------
    def _canonical_card(self, card_code: str) -> CanonicalCard | None:
        return self._session.execute(
            select(CanonicalCard).where(CanonicalCard.card_code == card_code)
        ).scalar_one_or_none()

    def _product_by_code(self, official_code: str) -> ReleaseProduct | None:
        return self._session.execute(
            select(ReleaseProduct).where(
                ReleaseProduct.source_catalogue == self._catalogue,
                ReleaseProduct.official_code == official_code,
            )
        ).scalar_one_or_none()

    def _uncoded_product_by_exact_name(self, name: str) -> ReleaseProduct | None:
        """An uncoded product already established under this exact name.

        Exact, untransformed comparison against the frozen evidence fields. No
        casefolding, no whitespace-insensitive matching, no similarity: the
        repo's own normalize_release_text collapses 30 Bandai products into 13
        keys, so anything fuzzier than equality would merge real products.
        """
        candidates = (
            self._session.execute(
                select(ReleaseProduct).where(
                    ReleaseProduct.source_catalogue == self._catalogue,
                    ReleaseProduct.official_code.is_(None),
                )
            )
            .scalars()
            .all()
        )
        for candidate in candidates:
            if name in (candidate.first_seen_name, candidate.display_name):
                return candidate
        return None

    def _exact_print(
        self, canonical_card_id: int, release_product_id: int, variant: str
    ) -> CardPrint | None:
        """The one print holding this exact identity, if Atlas has it.

        Exactly the four identity columns - never treatment, never
        artwork_key, never release_product_code, never card code alone.
        """
        return self._session.execute(
            select(CardPrint).where(
                CardPrint.canonical_card_id == canonical_card_id,
                CardPrint.language == LANGUAGE,
                CardPrint.release_product_id == release_product_id,
                CardPrint.official_asset_variant == variant,
                CardPrint.is_active.is_(True),
            )
        ).scalar_one_or_none()

    # -- planning ----------------------------------------------------------
    def plan_entry(
        self,
        entry: OfficialCardEntry,
        *,
        series_index: Sequence[OfficialSeries] = (),
        sibling_count: int = 1,
    ) -> PlannedPrint:
        """Resolve one official Card List entry into a plan."""
        flags: list[str] = []
        reasons: list[str] = []
        creations: list[str] = []

        card_code = (entry.card_code or "").strip()
        variant = parse_official_asset_variant(entry.image_url, card_code)

        if not entry.is_wellformed:
            flags.append(FLAG_MALFORMED_ENTRY)
            reasons.append(
                "the catalogue entry is missing one of entry id, card code or card name, "
                "so it cannot establish identity"
            )

        # --- official artwork variant, from the asset address only ---------
        if variant is None:
            flags.append(FLAG_MALFORMED_ASSET)
            reasons.append(
                f"the official asset address {entry.image_url!r} does not resolve to an "
                f"artwork variant for card code {card_code!r}"
            )
        else:
            # The entry id is Bandai's own name for this artwork. If it and the
            # asset disagree, one of them is not this printing's evidence.
            expected_entry_suffix = "" if variant == "base" else f"_{variant}"
            expected_entry_id = f"{card_code}{expected_entry_suffix}"
            if entry.entry_id and entry.entry_id.upper() != expected_entry_id.upper():
                flags.append(FLAG_ENTRY_ASSET_MISMATCH)
                reasons.append(
                    f"catalogue entry id {entry.entry_id!r} does not agree with the artwork "
                    f"variant {variant!r} parsed from the asset address"
                )

        if sibling_count > 1:
            flags.append(FLAG_SIBLING_VARIANTS)
            reasons.append(
                f"Bandai publishes {sibling_count} official artworks for {card_code}; this "
                "plan describes exactly one of them"
            )

        # --- product -------------------------------------------------------
        product_name: str | None = None
        product_code: str | None = None
        existing_product: ReleaseProduct | None = None
        proposed_product: ProposedReleaseProduct | None = None

        if len(entry.product_names) > 1:
            flags.append(FLAG_MULTIPLE_PRODUCTS)
            reasons.append(
                "the entry names more than one product "
                f"({', '.join(entry.product_names)}), so one product identity cannot be "
                "established for a single print"
            )
        if entry.product_names:
            product_name = entry.product_names[0]
            product_code = product_code_from_display_name(product_name)

        series_for_code = None
        if product_code:
            series_for_code = next(
                (s for s in series_index if s.official_code == product_code), None
            )
            existing_product = self._product_by_code(product_code)
            if existing_product is None:
                creations.append(CREATE_RELEASE_PRODUCT)
                flags.append(FLAG_NEW_PRODUCT_PROPOSED)
                # Prefer the series picker's own full title: it is the
                # catalogue's authoritative name for the product, where the
                # entry's 入手情報 line is an abbreviated rendering of it.
                authoritative_name = (
                    series_for_code.display_name if series_for_code else product_name
                )
                proposed_product = ProposedReleaseProduct(
                    source_catalogue=self._catalogue,
                    official_code=product_code,
                    display_name=authoritative_name or product_name or "",
                    first_seen_name=authoritative_name or product_name or "",
                    source_series_id=series_for_code.series_id if series_for_code else None,
                    source_url=series_for_code.source_url if series_for_code else None,
                )
                reasons.append(
                    f"Atlas has no {self._catalogue} product with official code "
                    f"{product_code!r}; creation is proposed from catalogue evidence"
                )
        elif product_name:
            flags.append(FLAG_UNCODED_PRODUCT)
            existing_product = self._uncoded_product_by_exact_name(product_name)
            if existing_product is not None:
                reasons.append(
                    f"reusing the established uncoded product #{existing_product.id} matched "
                    "on its exact frozen catalogue name"
                )
            else:
                creations.append(CREATE_RELEASE_PRODUCT)
                flags.append(FLAG_NEW_PRODUCT_PROPOSED)
                proposed_product = ProposedReleaseProduct(
                    source_catalogue=self._catalogue,
                    official_code=None,
                    display_name=product_name,
                    first_seen_name=product_name,
                    source_series_id=None,
                    source_url=None,
                )
                reasons.append(
                    f"the product {product_name!r} carries no official code, and no existing "
                    "uncoded product matches it exactly; a new product with surrogate identity "
                    "is proposed rather than merging on a similar name"
                )
        else:
            reasons.append("the entry names no product, so product identity cannot be established")

        # --- canonical card --------------------------------------------------
        existing_card = self._canonical_card(card_code) if card_code else None
        proposed_card: ProposedCanonicalCard | None = None
        conflict = False

        if existing_card is not None:
            differences, notes = self._canonical_card_conflicts(
                existing_card, entry, product_code
            )
            for note in notes:
                flags.append(FLAG_RARITY_DIFFERS_BY_PRINTING)
                reasons.append(note)
            if differences:
                conflict = True
                flags.append(FLAG_CANONICAL_CARD_CONFLICT)
                reasons.append(
                    "existing canonical card #%d disagrees with the catalogue on %s"
                    % (existing_card.id, "; ".join(differences))
                )
        elif card_code:
            creations.append(CREATE_CANONICAL_CARD)
            flags.append(FLAG_CANONICAL_CARD_PLANNED)
            proposed_card = ProposedCanonicalCard(
                card_code=card_code,
                name_jp=entry.card_name,
                original_set_code=original_set_code(card_code),
                rarity=(entry.rarity or "").strip() or None,
                card_type=_card_type_from_category(entry.category),
            )
            reasons.append(
                f"Atlas has no canonical card for {card_code}; the catalogue proves it exists, "
                "so creation is proposed from Bandai fields only"
            )

        # --- the exact print --------------------------------------------------
        existing_print: CardPrint | None = None
        if existing_card is not None and existing_product is not None and variant is not None:
            existing_print = self._exact_print(existing_card.id, existing_product.id, variant)

        digest = self._digest(entry.image_url)

        treatment: str | None = None
        if existing_print is not None:
            # The only treatment a plan ever carries: one Atlas already holds.
            treatment = existing_print.treatment
            reasons.append(
                f"exact identity already held by card_print #{existing_print.id} "
                f"(canonical_card={existing_card.id}, language={LANGUAGE}, "
                f"release_product={existing_product.id}, variant={variant})"
            )
            if digest and existing_print.artwork_key and digest != existing_print.artwork_key:
                flags.append(FLAG_ASSET_CHANGED)
                reasons.append(
                    "the official asset digest no longer equals this print's artwork_key "
                    f"(catalogue {digest[:12]}..., Atlas {existing_print.artwork_key[:12]}...); "
                    "this is the same exact print, so no duplicate is proposed"
                )
        else:
            creations.append(CREATE_CARD_PRINT)
            reasons.append(
                "no active print holds this exact identity "
                "(canonical_card, language, release_product, official_asset_variant)"
            )
            if digest is None:
                flags.append(FLAG_DIGEST_NOT_ESTABLISHED)
                reasons.append(
                    "no SHA-256 was established for the official asset, so the artwork_key "
                    "evidence a verified print requires is missing"
                )

        # --- outcome ----------------------------------------------------------
        outcome, verification_status = self._decide(
            conflict=conflict,
            flags=flags,
            creations=creations,
            existing_print=existing_print,
            variant=variant,
            product_resolved=existing_product is not None or proposed_product is not None,
        )

        return PlannedPrint(
            source_catalogue=self._catalogue,
            # Series provenance is only known when the entry's product code
            # appears in the catalogue's own series picker. An uncoded product
            # has no series page, so None is the truthful answer.
            source_series_id=series_for_code.series_id if series_for_code else None,
            source_url=series_for_code.source_url if series_for_code else None,
            entry_id=entry.entry_id,
            official_product_code=product_code,
            official_product_display_name=(
                series_for_code.display_name if series_for_code else product_name
            ),
            card_code=card_code,
            official_card_name=entry.card_name,
            language=LANGUAGE,
            official_image_url=entry.image_url,
            official_asset_variant=variant,
            official_artwork_sha256=digest,
            treatment=treatment,
            existing_canonical_card_id=existing_card.id if existing_card else None,
            existing_release_product_id=existing_product.id if existing_product else None,
            existing_card_print_id=existing_print.id if existing_print else None,
            outcome=outcome,
            creations=tuple(dict.fromkeys(creations)),
            verification_status=verification_status,
            flags=tuple(dict.fromkeys(flags)),
            reasons=tuple(reasons),
            proposed_canonical_card=proposed_card,
            proposed_release_product=proposed_product,
        )

    @staticmethod
    def _canonical_card_conflicts(
        card: CanonicalCard, entry: OfficialCardEntry, product_code: str | None
    ) -> tuple[list[str], list[str]]:
        """Material identity disagreements, and print-scoped differences.

        Returns `(conflicts, notes)`. Only fields Bandai actually publishes are
        compared, and only when Atlas holds a value: a NULL in Atlas is missing
        information the catalogue can fill, not a contradiction of it.

        Rarity is the subtle one. Bandai lists it per entry, so a reprint into a
        later set legitimately shows a different rarity from the card's own set
        - comparing those two would report a conflict that does not exist and
        invite someone to "fix" a canonical card that is already right. Rarity
        is therefore only treated as canonical evidence when the entry *is* the
        card's own set; anywhere else the difference is reported as a note
        about that printing.
        """
        conflicts: list[str] = []
        notes: list[str] = []

        catalogue_name = (entry.card_name or "").strip()
        if card.name_jp and catalogue_name and card.name_jp.strip() != catalogue_name:
            conflicts.append(f"name_jp ({card.name_jp!r} vs {catalogue_name!r})")

        catalogue_rarity = (entry.rarity or "").strip()
        if card.rarity and catalogue_rarity and card.rarity.strip().upper() != catalogue_rarity.upper():
            own_set = bool(
                product_code
                and card.original_set_code
                and product_code.strip().upper() == card.original_set_code.strip().upper()
            )
            if own_set:
                conflicts.append(f"rarity ({card.rarity!r} vs {catalogue_rarity!r})")
            else:
                notes.append(
                    f"the catalogue lists this printing's rarity as {catalogue_rarity!r} while "
                    f"canonical card #{card.id} records {card.rarity!r} for the card's own set "
                    f"({card.original_set_code}); Bandai publishes rarity per printing, so this "
                    "is a property of the reprint and not a canonical-card disagreement"
                )

        catalogue_type = _card_type_from_category(entry.category)
        if card.card_type and catalogue_type and card.card_type.strip().lower() != catalogue_type.lower():
            conflicts.append(f"card_type ({card.card_type!r} vs {catalogue_type!r})")
        return conflicts, notes

    @staticmethod
    def _decide(
        *,
        conflict: bool,
        flags: Sequence[str],
        creations: Sequence[str],
        existing_print: CardPrint | None,
        variant: str | None,
        product_resolved: bool,
    ) -> tuple[str, str]:
        """The single place an outcome and a verification status are chosen.

        The standard is not relaxed to increase coverage: every ambiguity in
        an identity component lands in needs_review, including ones that would
        be tempting to wave through (an uncoded product, a changed asset, a
        catalogue entry naming two products).
        """
        if conflict:
            return OUTCOME_CONFLICT, NEEDS_REVIEW

        blocking = {
            FLAG_MALFORMED_ENTRY,
            FLAG_MALFORMED_ASSET,
            FLAG_ENTRY_ASSET_MISMATCH,
            FLAG_MULTIPLE_PRODUCTS,
            FLAG_DIGEST_NOT_ESTABLISHED,
            FLAG_ASSET_CHANGED,
            # An uncoded product that Atlas has not already established cannot
            # be told apart from a product it already holds under another
            # spelling, so a human decides before anything is created.
            FLAG_UNCODED_PRODUCT,
        }
        if set(flags) & blocking:
            return OUTCOME_NEEDS_REVIEW, NEEDS_REVIEW
        if variant is None or not product_resolved:
            return OUTCOME_NEEDS_REVIEW, NEEDS_REVIEW

        if existing_print is not None:
            # Identity already held and the evidence still agrees.
            return OUTCOME_NO_CHANGE, existing_print.verification_status
        if not creations:
            return OUTCOME_NO_CHANGE, VERIFIED
        return OUTCOME_CREATE, VERIFIED

    def _digest(self, url: str | None) -> str | None:
        if not url or self._digest_provider is None:
            return None
        return self._digest_provider(url)

    # -- source mappings, read-only ----------------------------------------
    def classify_lineage_less_mappings(
        self, planned: Iterable[PlannedPrint]
    ) -> list[ClassifiedMapping]:
        """Judge every lineage-less mapping against the planned prints.

        A lineage-less mapping is one with `card_print_id IS NULL`: it points
        at a legacy card but names no exact printing. These are the rows a
        future write step might one day attach, so a planner should say what
        it thinks of them - and nothing more. Nothing is attached, scored or
        edited here, and no classification feeds back into any print identity.
        """
        planned_list = list(planned)
        # How many official artworks each card code has in this run. A code
        # with siblings cannot be resolved from the code alone.
        variants_per_code: dict[str, set[str]] = {}
        for plan in planned_list:
            variants_per_code.setdefault(plan.card_code.upper(), set()).add(
                plan.official_asset_variant or "?"
            )
        planned_codes = set(variants_per_code)

        rows = self._session.execute(
            select(SourceCardMapping, Card, Source)
            .join(Card, Card.id == SourceCardMapping.card_id)
            .join(Source, Source.id == SourceCardMapping.source_id)
            .where(SourceCardMapping.card_print_id.is_(None))
        ).all()

        classified: list[ClassifiedMapping] = []
        for mapping, card, source in rows:
            legacy_code = (getattr(card, "card_code", None) or "").strip()
            upper = legacy_code.upper()
            if upper not in planned_codes:
                classification = MAPPING_UNRELATED
                reason = (
                    f"legacy card code {legacy_code or '<none>'} is not among the card codes "
                    "this run planned"
                )
            elif mapping.review_status == "rejected" or not mapping.is_active:
                classification = MAPPING_AMBIGUOUS
                reason = (
                    "the mapping names a planned card code but is "
                    f"{'rejected' if mapping.review_status == 'rejected' else 'inactive'}, "
                    "so it is not usable evidence without a human decision"
                )
            else:
                matched = self._matched_variant(mapping)
                if matched and matched in variants_per_code[upper]:
                    classification = MAPPING_EXACT_CANDIDATE
                    reason = (
                        "the mapping's own recorded Bandai artwork evidence names official "
                        f"artwork {matched}, which is one of this run's planned prints"
                    )
                elif len(variants_per_code[upper]) == 1:
                    classification = MAPPING_PROBABLE
                    reason = (
                        f"card code {legacy_code} has exactly one official artwork in this run, "
                        "so the mapping has only one print it could describe - but it carries "
                        "no artwork evidence of its own"
                    )
                else:
                    classification = MAPPING_AMBIGUOUS
                    reason = (
                        f"card code {legacy_code} has "
                        f"{len(variants_per_code[upper])} official artworks and the mapping "
                        "carries no evidence naming one of them"
                    )
            classified.append(
                ClassifiedMapping(
                    mapping_id=mapping.id,
                    source_name=getattr(source, "name", None),
                    source_card_id=mapping.source_card_id,
                    source_url=mapping.source_url,
                    legacy_card_code=legacy_code or None,
                    review_status=mapping.review_status,
                    classification=classification,
                    reason=reason,
                )
            )
        return classified

    @staticmethod
    def _matched_variant(mapping: SourceCardMapping) -> str | None:
        """The official artwork a mapping's *own* evidence already names.

        Read from the verification metadata the collectors already write
        (`matched_bandai_artwork`, e.g. 'OP01-001_p2'). Absent for most rows,
        which is the honest answer - it is why those become probable or
        ambiguous rather than exact candidates.
        """
        document = mapping.match_explanation_json or {}
        if not isinstance(document, dict):
            return None
        matched = document.get("matched_bandai_artwork")
        if not isinstance(matched, str) or not matched.strip():
            return None
        stem = matched.strip()
        code, sep, suffix = stem.partition("_p")
        if not sep:
            return "base"
        return f"p{suffix}" if suffix.isdigit() else None


def plan_entries(
    session: Session,
    entries: Sequence[OfficialCardEntry],
    *,
    series_index: Sequence[OfficialSeries] = (),
    source_catalogue: str = "bandai_jp",
    digest_provider: DigestProvider | None = None,
    classify_mappings: bool = True,
) -> ImportPlan:
    """Plan a set of official entries, with sibling counts resolved for free."""
    planner = PrintImportPlanner(
        session, source_catalogue=source_catalogue, digest_provider=digest_provider
    )
    per_code: dict[str, int] = {}
    for entry in entries:
        key = (entry.card_code or "").strip().upper()
        per_code[key] = per_code.get(key, 0) + 1

    plan = ImportPlan()
    for entry in entries:
        plan.prints.append(
            planner.plan_entry(
                entry,
                series_index=series_index,
                sibling_count=per_code.get((entry.card_code or "").strip().upper(), 1),
            )
        )
    if classify_mappings:
        plan.mappings = planner.classify_lineage_less_mappings(plan.prints)
    return plan
