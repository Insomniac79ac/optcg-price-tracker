"""Applies the safe, verified subset of a planner run inside one transaction.

THE DIVISION OF LABOUR. `print_import_planner` decides identity; this module
decides nothing about identity at all. It consumes `PlannedPrint.outcome` and
refuses anything that is not already `create` with `verification_status ==
'verified'`. There is deliberately no second opinion here: a rule that could
promote a `needs_review` plan would be a second identity authority, and two
authorities that disagree is how a catalogue silently splits.

WHAT IT WILL WRITE

    release_products   missing CODED bandai_jp products, once each
    canonical_cards    missing cards, once each, rarity from a proven baseline
                       or NULL where the catalogue proves none
    card_prints        the planned exact prints, verified
    card_prints.official_*  the four metadata columns, on existing prints that
                       are currently NULL and whose identity and digest still
                       agree

WHAT IT WILL NEVER WRITE. source_card_mappings, price_observations,
market_index_snapshots, the legacy `cards` table, collection tables, or any
existing identity field. `treatment` is never written - not even NULL-to-value
- because Bandai publishes no treatment and the suffix is an address, not a
classification.

THE RARITY PROBLEM, AS RESOLVED (see resolve_canonical_baseline). Rarity is a
property of a *printing*: the same card code is published at different
rarities in different products. `canonical_cards.rarity` used to be NOT NULL,
which forced a choice between inventing a value and refusing the card - this
module refused, and 122 exact prints across 49 codes went unimported for a
reason that was about a summary column rather than about the prints.

Migration c7e91a4d2b60 made the column optional and this module now writes
what the catalogue actually supports:

    one rarity under the card's own set   -> that rarity
    the own set publishes several         -> NULL
    no own-set occurrence to read         -> NULL

Never the first occurrence, the most common, the highest, or anything derived
from a pN/rN suffix. Every print still records the rarity Bandai published for
its exact occurrence in `card_prints.official_rarity`, which is the
authoritative value; the canonical column is optional summary metadata.

PROMOS HAVE NO ORIGINAL SET (see _resolve_promo_consensus). `P-014` carries no
set number, so no occurrence can be shown to be its original printing and none
ever will be - the products a promo is distributed in are distribution
products, not its set. Since migration d1c48b7f36ae `original_set_code` is
optional, and a promo's canonical row is established by CONSENSUS over its
CODED occurrences: a field they all publish identically is written, a field
they disagree on materially is left NULL. Nothing is read from an uncoded
occurrence, and no occurrence is ever preferred over another.

WHAT STILL EXCLUDES A CARD is missing IDENTITY evidence, never rarity and
never a promo's absent set code: a malformed card code, no own-set occurrence
to read a name and type from, or card-level evidence that disagrees across
occurrences. See CanonicalBaseline.composable.

A CONFLICT STOPS EVERYTHING (see _check_no_planner_conflicts). The planner
raises `conflict` only when the catalogue disagrees with a canonical row Atlas
already holds about the card ITSELF - its baseline name, its baseline rarity,
its type. That is not a thinly-evidenced row to leave behind: it is two
records of the same card that no longer agree. One anywhere in the plan aborts
the whole run before a row is composed, so an unexplained disagreement is
never buried under 4260 successful writes. Conflicts are not demoted to
needs_review, not skipped and not mutated; `needs_review` itself stays
non-fatal and costs only its own rows.

MISSING INPUT IS NOT DRIFT (see _check_existing_asset_digests). A NEW planned
print whose official digest cannot be established is left unimported and the
run continues: Atlas holds nothing for it, so nothing has diverged. An
EXISTING exact print whose stored artwork_key disagrees with the frozen
official evidence aborts the WHOLE run before a row is composed, because two
records that were once the same have diverged and no other row should be
written on top of that until someone says which is right. Neither value is
overwritten and no row is quarantined.

ATOMICITY. One run is one transaction. Every refusal - a stale count, a
changed snapshot, a planner conflict, a metadata conflict, an unresolvable
baseline, a drifted digest - raises before or during that transaction and
rolls the whole run back. There is no partial catalogue import and no per-product commit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CanonicalCard, CardPrint, ReleaseProduct, ReleaseProductAlias
from app.services import print_import_planner as planner
from app.services.official_snapshot import normalize_for_comparison
from app.services.print_import_planner import (
    METADATA_FIELDS,
    OUTCOME_CONFLICT,
    OUTCOME_CREATE,
    OUTCOME_NEEDS_REVIEW,
    OUTCOME_NO_CHANGE,
    ImportPlan,
    PlannedPrint,
    is_promo_card_code,
    original_set_code,
)

LANGUAGE = planner.LANGUAGE
VERIFIED = planner.VERIFIED
SOURCE_CATALOGUE = "bandai_jp"

# Environments an apply run may write to *by name alone*. Canonical staging is
# deliberately absent: naming it buys nothing, because a staging write needs a
# grant object (below) that no flag and no environment variable can produce.
# Production is additionally hard-refused by name so a typo cannot fall
# through to a permissive default.
ALLOWED_APPLY_ENVIRONMENTS = ("test", "development", "staging_copy")

# What the GENERIC CLI refuses outright, before it constructs an applier.
# `staging` stays in this list: `--environment staging` is, and remains, a
# refusal on that path. Unchanged from before the dedicated runner existed.
REFUSED_APPLY_ENVIRONMENTS = ("production", "prod", "staging")

# What NOTHING can make writable. No grant, no attestation, no confirmation
# string reaches these - the check runs first and returns before any
# authorisation is consulted.
PERMANENTLY_REFUSED_APPLY_ENVIRONMENTS = ("production", "prod")

# The one environment a grant can unlock, and only for the dedicated runner.
CANONICAL_STAGING_ENVIRONMENT = "staging"

# The exact phrase an operator must type to authorise a canonical staging
# write. Compared for equality - not parsed, not lowercased, not prefix
# matched - so a typo is a refusal rather than a near miss. There is no
# --force and no --yes anywhere on that path.
STAGING_APPLY_CONFIRMATION = "IMPORT_FROZEN_BANDAI_TO_CANONICAL_STAGING"

# Arbitrary but fixed: the key two concurrent apply runs would contend on.
# Transaction-scoped, so it needs no cleanup path.
IMPORT_LOCK_KEY = 0x0A71A5_10  # "atlas" + import


# --- refusal reasons, one vocabulary -------------------------------------
SKIP_NOT_CREATE = "outcome_not_create"
SKIP_NOT_VERIFIED = "verification_status_not_verified"
SKIP_WRONG_CATALOGUE = "source_catalogue_not_bandai_jp"
SKIP_NO_VARIANT = "no_official_asset_variant"
SKIP_NO_IMAGE = "no_official_image_url"
SKIP_NO_DIGEST = "no_artwork_sha256"
SKIP_INCOMPLETE_METADATA = "incomplete_official_metadata"
SKIP_UNCODED_PRODUCT = "uncoded_product_not_established"
# The only alias_kind this module ever writes. A storefront's spelling is
# never a Bandai name; see ReleaseProductAlias.ALIAS_KINDS.
SOURCE_RENDERING_KIND = "source_rendering"
SKIP_NO_CARD_CODE = "no_card_code"

# Why a NEW canonical card cannot be composed. None of these is about rarity:
# since migration c7e91a4d2b60 `canonical_cards.rarity` is optional, so an
# unestablished rarity costs the card nothing and the old
# `canonical_rarity_baseline_not_established` reason is gone. What remains is
# identity evidence that is NOT NULL in the schema and cannot be guessed.
SKIP_NO_ORIGINAL_SET_CODE = "canonical_original_set_code_not_established"
SKIP_NO_BASELINE_OCCURRENCE = "canonical_baseline_occurrence_not_established"
SKIP_CARD_EVIDENCE_DISAGREES = "canonical_card_evidence_disagrees"

# §3. An EXISTING exact print whose stored artwork_key disagrees with the
# frozen official evidence. Not a per-row skip: Atlas already holds this print,
# so the disagreement is drift between two records that were once the same, and
# importing 4138 other rows on top of an unexplained one would bury it.
ABORT_EXISTING_ASSET_DIGEST = "existing_asset_digest_mismatch"

# 4C-4B. A planner outcome of `conflict` is the catalogue disagreeing with a
# record Atlas already holds about the SAME card - not a row with thin
# evidence. Skipping it and importing the other 4260 rows would leave the
# disagreement buried under an import that looks successful, so any conflict
# anywhere in the plan stops the whole run before a row is composed. Not
# converted to needs_review and not mutated: the planner's decision is read,
# never edited.
ABORT_PLANNER_CONFLICT = "planner_conflict"

# How many conflicting plans the abort context names individually. The count
# is always exact; the sample is bounded so a corpus-wide disagreement reports
# a readable refusal rather than thousands of rows.
CONFLICT_CONTEXT_LIMIT = 25

BASELINE_UNIQUE = "unique"
BASELINE_NONE = "none"
BASELINE_MULTIPLE = "multiple"


class ApplyAborted(RuntimeError):
    """Any condition that must roll the whole run back.

    Carries the machine-readable reason so a report can name it without
    parsing prose, and an optional `context` for the reasons whose detail is
    a set of named values rather than a sentence - so an operator reads the
    stored digest and the expected digest as fields, not by parsing them back
    out of an error message.
    """

    def __init__(
        self, reason: str, detail: str, context: dict[str, Any] | None = None
    ) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail
        self.context = context or {}


# --- §3 canonical baseline -----------------------------------------------
@dataclass(frozen=True)
class CanonicalBaseline:
    """How a card code's canonical row would be established, and whether it can be.

    `status` is one of unique/none/multiple. Only `unique` is ever written;
    the other two exclude the card and all of its prints, and are reported.
    """

    card_code: str
    status: str
    expected_set_code: str | None
    candidates: tuple[str, ...]
    # True when the code names a PROMO, whose expected_set_code is absent
    # BECAUSE the card has no original set - not because one could not be
    # read. The two look identical on the field and mean opposite things, so
    # the distinction is carried rather than re-derived.
    is_promo: bool = False
    rarity: str | None = None
    card_type: str | None = None
    name_jp: str | None = None
    entry_id: str | None = None
    disagreements: tuple[str, ...] = ()
    # Language-independent numerics, read off the baseline occurrence's own
    # published blocks. See NUMERIC_FIELDS for why only these three.
    cost: int | None = None
    power: int | None = None
    counter: int | None = None

    @property
    def rarity_established(self) -> bool:
        """Whether the catalogue settles ONE card-level rarity for this code.

        False is not a refusal any more (see composable): it means the card is
        written with `rarity = NULL`, which is what the catalogue actually
        says. Kept as a named property because "was a rarity established?" is
        a real question a report should be able to answer.
        """
        return self.status == BASELINE_UNIQUE and self.rarity is not None

    @property
    def composable(self) -> bool:
        """Whether a canonical row can be composed at all.

        This is about IDENTITY, not rarity. Three things are needed and none
        of them may be guessed:

            expected_set_code   `original_set_code` is NOT NULL, and a promo
                                code like P-014 carries no set code to read.
                                Writing the product it was distributed in
                                would be inventing an original printing.
            name_jp             read off the card's own-set occurrence. There
                                is no baseline to read it from when no such
                                occurrence exists, and copying the name from
                                an arbitrary reprint is exactly the
                                order-dependence this whole module refuses.
            card_type           same, and it must additionally not vary across
                                occurrences (see disagreements).

        `rarity` is deliberately absent from this list - as of migration
        c7e91a4d2b60 the column is optional, so an unestablished rarity costs
        the card nothing. Since d1c48b7f36ae `original_set_code` is optional
        too, but only for a PROMO: absent-because-there-is-none is composable,
        absent-because-it-could-not-be-read is not.
        """
        if not (self.name_jp and self.card_type) or self.disagreements:
            return False
        return bool(self.expected_set_code) or self.is_promo


# The one field the corpus says describes the CARD rather than the printing,
# so it must agree across every occurrence of a code before that code may be
# written as a single canonical row. `rarity` is deliberately absent - varying
# by printing is the whole reason a baseline is needed. `card_name` is absent
# too: Bandai republishes typo fixes, and a name difference is not evidence of
# a different card.
INVARIANT_FIELDS = ("card_type",)

# The only canonical columns beyond the four required ones this importer will
# fill from JP evidence. All three are numbers Bandai prints as digits, so
# they carry no language: `cost` 2 is 2 in every catalogue.
#
# WHAT IS DELIBERATELY NOT HERE, and why. `colors` and `attribute` are the
# tempting ones - the JP entry publishes both - but the columns as they stand
# hold ENGLISH: staging's own rows carry ["Red"], ["Yellow"] and 'Slash',
# 'Strike', 'Special' (checked 2026-08-23 against all 15 canonical rows).
# Bandai JP publishes 赤 / 黄 and 斬 / 打 / 特. Writing those would leave one
# column holding two vocabularies with nothing recording which row is in
# which, so they stay NULL until a translation authority exists. Same reason
# `effect_text` and `trigger_text` stay NULL - the exact published JP text is
# already carried, correctly attributed, in card_prints.official_effect_text.
NUMERIC_FIELDS = ("cost", "power", "counter")

# Bandai's own spelling for "this card has no such value". It is a published
# value meaning absence, not a missing block, and it maps to NULL.
ABSENT_NUMERIC = "-"


def _numeric(value: str | None) -> int | None:
    """A published numeric block as an int, or None when Bandai says '-'.

    Anything that is neither a plain integer nor '-' returns None rather than
    being coerced: a value this does not understand is not evidence it may
    reshape into one.
    """
    text = (value or "").strip()
    if not text or text == ABSENT_NUMERIC:
        return None
    try:
        return int(text)
    except ValueError:
        return None


# The only occurrences a promo's canonical row is established from. An uncoded
# product is one the planner could not resolve at all, so it is not evidence
# Atlas is willing to act on: those occurrences stay needs_review and are read
# by nothing here. See §4 of the tranche contract.
def _coded(occurrences: Sequence[PlannedPrint]) -> list[PlannedPrint]:
    return [
        p
        for p in occurrences
        if p.official_product_code and p.proposed_canonical_card is not None
    ]


def _consensus(values: Iterable[str | None]) -> tuple[str | None, str]:
    """The one published value, or None with the reason there isn't one.

    Fail-closed by construction. Returns `(value, status)` where status is one
    of `exact` / `formatting_tie` / `material_disagreement` / `absent`. A
    formatting-only difference still yields None: the two renderings are the
    same name, but picking one of them would be picking an occurrence, and
    writing the NFKC-folded form would store a rendering Bandai never
    published. Neither is evidence, so the field is left unset and the exact
    spellings stay on each print.
    """
    present = [v.strip() for v in values if v is not None and v.strip()]
    if not present:
        return None, "absent"
    raw = set(present)
    if len(raw) == 1:
        return present[0], "exact"
    if len({normalize_for_comparison(v) for v in present}) == 1:
        return None, "formatting_tie"
    return None, "material_disagreement"


def _resolve_promo_consensus(
    card_code: str,
    occurrences: Sequence[PlannedPrint],
    *,
    entries: dict[str, Any] | None = None,
) -> CanonicalBaseline:
    """A promo's canonical row, established from consensus over its coded
    occurrences rather than from a baseline printing.

    WHY CONSENSUS AND NOT A BASELINE. `P-014` has no set number, so no
    occurrence can be shown to be "the original printing" - and the corpus
    offers nothing that would settle it either: ReleaseProduct carries no
    release date, the snapshot records only `fetched_at`, and `source_series_id`
    is an opaque namespaced vendor id (audited 2026-08-24, no authoritative
    chronology exists anywhere in the repo). Anything that named one product
    "first" would be inferring from row order, fetch order or lexicographic
    code, all of which are forbidden and none of which is evidence.

    What IS available is agreement. Across the 31 excluded promo codes every
    coded occurrence agrees exactly on card_name, card_type, colour, cost,
    power, counter, feature and block icon; only rarity disagrees, on two
    codes. So the rule is: a field the coded occurrences all publish
    identically is established from that agreement, and a field they disagree
    on materially is left NULL. Order is never consulted, and no occurrence is
    ever preferred over another.

    Rarity reuses the existing vocabulary: `unique` when the coded occurrences
    settle one, `multiple` when they disagree, `none` when none publishes one.
    """
    coded = _coded(occurrences)
    if not coded:
        # Every occurrence is under a product the planner could not resolve.
        # Nothing is established from those, so the card is not composable and
        # its prints stay needs_review.
        return CanonicalBaseline(
            card_code,
            BASELINE_NONE,
            None,
            tuple(sorted({p.official_product_code or "<uncoded>" for p in occurrences})),
            is_promo=True,
        )

    proposals = [p.proposed_canonical_card for p in coded]
    name_jp, name_status = _consensus(p.name_jp for p in proposals)
    card_type, type_status = _consensus(p.card_type for p in proposals)
    rarity, rarity_status = _consensus(p.rarity for p in proposals)

    disagreements: list[str] = []
    if name_status not in ("exact",):
        disagreements.append(
            f"name_jp has no consensus across the coded occurrences ({name_status}): "
            f"{sorted({(p.name_jp or '') for p in proposals})}"
        )
    if type_status not in ("exact",):
        disagreements.append(
            f"card_type has no consensus across the coded occurrences ({type_status}): "
            f"{sorted({(p.card_type or '') for p in proposals})}"
        )

    # Rarity is NOT a disagreement that blocks - since c7e91a4d2b60 it is
    # optional, so a promo whose printings carry different rarities is written
    # with NULL and each print keeps its own official_rarity.
    if rarity_status == "exact":
        status = BASELINE_UNIQUE
    elif rarity_status == "absent":
        status = BASELINE_NONE
    else:
        status = BASELINE_MULTIPLE

    # Numerics come from one coded occurrence's published blocks only when
    # every coded occurrence agrees on the identity fields - the same
    # "consensus, not a chosen row" standard. The entry read is the one whose
    # entry_id sorts first, which is a deterministic tie-break over values that
    # have already been proven identical, not a choice between differing ones.
    numerics: dict[str, int | None] = {name: None for name in NUMERIC_FIELDS}
    entry_id = None
    if not disagreements:
        entry_id = sorted(p.entry_id for p in coded)[0]
        entry = (entries or {}).get(entry_id)
        if entry is not None:
            for field_name in NUMERIC_FIELDS:
                block = entry.field(field_name)
                numerics[field_name] = _numeric(
                    getattr(block, "value", None) if block else None
                )

    return CanonicalBaseline(
        card_code=card_code,
        status=status,
        # THE POINT OF THIS WHOLE PATH. A promo has no original set, and the
        # products it is distributed in are not one.
        expected_set_code=None,
        is_promo=True,
        candidates=tuple(sorted({(p.rarity or "").strip() for p in proposals} - {""})),
        rarity=rarity,
        card_type=card_type,
        name_jp=name_jp,
        entry_id=entry_id,
        disagreements=tuple(disagreements),
        **numerics,
    )


def resolve_canonical_baseline(
    card_code: str,
    occurrences: Sequence[PlannedPrint],
    *,
    entries: dict[str, Any] | None = None,
) -> CanonicalBaseline:
    """The one occurrence a new canonical row may be built from, if it exists.

    THE RULE. A card code carries its own set code: `OP01-001` -> `OP-01`.
    The baseline is the occurrence published under the product whose official
    code is exactly that - the card's original printing. It supplies the
    canonical row's `name_jp`, `card_type` and numerics, and, when the
    catalogue settles one, its `rarity`.

    `status` answers ONLY the rarity question, in three ways:

        unique    the own-set occurrences publish one rarity -> that rarity
        none      no own-set occurrence is present to read one from
        multiple  the own-set occurrences disagree - the catalogue itself does
                  not settle a card-level value

    Since migration c7e91a4d2b60 `none` and `multiple` no longer exclude the
    card: `canonical_cards.rarity` is optional, so the row is written with
    NULL and every one of its prints still records the rarity Bandai published
    for that exact occurrence in `card_prints.official_rarity`. What CAN still
    exclude a card is missing IDENTITY evidence - see `composable`.

    Nothing is ever picked to break a tie. Not the first occurrence, not the
    most common rarity, not the highest, and never anything derived from a
    `pN`/`rN` suffix, which is an address rather than a classification.
    Iteration order is never consulted; when several matching occurrences
    agree on every field that would be written, they are the same evidence
    twice and the answer is still `unique`.
    """
    expected = original_set_code(card_code)
    if not expected:
        if is_promo_card_code(card_code):
            # A PROMO. No set code exists to read, and none ever will - the
            # products a promo is distributed in are not its original set. So
            # there is no baseline occurrence to scope anything to, and the
            # canonical row is established by CONSENSUS instead.
            return _resolve_promo_consensus(card_code, occurrences, entries=entries)
        # Not a promo and not readable: a malformed code. Nothing is resolved
        # from it, and it is not quietly promoted into the promo path.
        return CanonicalBaseline(card_code, BASELINE_NONE, None, ())

    matching = [p for p in occurrences if (p.official_product_code or "") == expected]
    if not matching:
        return CanonicalBaseline(
            card_code,
            BASELINE_NONE,
            expected,
            tuple(sorted({p.official_product_code or "<none>" for p in occurrences})),
        )

    proposals = [p.proposed_canonical_card for p in matching if p.proposed_canonical_card]
    if not proposals:
        return CanonicalBaseline(card_code, BASELINE_NONE, expected, ())

    # The fields the corpus says describe the CARD must not vary across ANY
    # occurrence of the code - not only the matching ones. A card whose type
    # changes between products is not one canonical card and must not be
    # written as one. This is still blocking, and rarity is still not in it.
    disagreements: list[str] = []
    for name in INVARIANT_FIELDS:
        values = {
            (getattr(p.proposed_canonical_card, name, None) or "").strip()
            for p in occurrences
            if p.proposed_canonical_card is not None
        }
        values.discard("")
        if len(values) > 1:
            disagreements.append(f"{name} differs across occurrences: {sorted(values)}")

    rarities = {(p.rarity or "").strip() for p in proposals}
    rarities.discard("")
    if len(rarities) == 1:
        status, rarity = BASELINE_UNIQUE, proposals[0].rarity
    elif len(rarities) > 1:
        # Several own-set occurrences, disagreeing. EB03-003 is published both
        # as 'SR' and as 'SPカード' inside EB-03 itself (2026-08-22 corpus).
        status, rarity = BASELINE_MULTIPLE, None
    else:
        status, rarity = BASELINE_NONE, None

    # Identity evidence comes from the own-set occurrences either way, and
    # they must agree with each other about it - the whole point of a baseline
    # is that it does not depend on which occurrence you happen to read.
    names = {(p.name_jp or "").strip() for p in proposals}
    names.discard("")
    types = {(p.card_type or "").strip() for p in proposals}
    types.discard("")
    if len(names) > 1:
        disagreements.append(
            f"name_jp differs between own-set occurrences: {sorted(names)}"
        )
    if len(types) > 1:
        disagreements.append(
            f"card_type differs between own-set occurrences: {sorted(types)}"
        )

    baseline = proposals[0]
    baseline_entry_id = matching[0].entry_id
    numerics: dict[str, int | None] = {name: None for name in NUMERIC_FIELDS}
    entry = (entries or {}).get(baseline_entry_id)
    if entry is not None:
        for name in NUMERIC_FIELDS:
            block = entry.field(name)
            numerics[name] = _numeric(getattr(block, "value", None) if block else None)

    return CanonicalBaseline(
        card_code=card_code,
        status=status,
        expected_set_code=expected,
        candidates=tuple(sorted(rarities)),
        rarity=rarity,
        card_type=baseline.card_type,
        name_jp=baseline.name_jp,
        entry_id=baseline_entry_id,
        disagreements=tuple(disagreements),
        **numerics,
    )


@dataclass
class BaselineAudit:
    """Every canonical card the safe set would create, and whether it can be."""

    baselines: dict[str, CanonicalBaseline] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        counts = {BASELINE_UNIQUE: 0, BASELINE_NONE: 0, BASELINE_MULTIPLE: 0}
        for baseline in self.baselines.values():
            counts[baseline.status] = counts.get(baseline.status, 0) + 1
        return counts

    @property
    def composable_codes(self) -> set[str]:
        """Codes a canonical row can be composed for. Rarity is not a term."""
        return {c for c, b in self.baselines.items() if b.composable}

    @property
    def excluded_codes(self) -> set[str]:
        return {c for c, b in self.baselines.items() if not b.composable}

    @property
    def rarity_null_codes(self) -> set[str]:
        """Composable, but the catalogue settles no card-level rarity.

        These are written with `rarity = NULL`. Reported rather than merely
        allowed: "49 cards have no canonical rarity" is a fact about the
        catalogue that should stay visible after the import, not a silence.
        """
        return {
            c for c, b in self.baselines.items() if b.composable and not b.rarity_established
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "counts": self.counts(),
            "rarity_null": sorted(self.rarity_null_codes),
            "excluded": {
                code: {
                    "status": b.status,
                    "expected_set_code": b.expected_set_code,
                    "candidates": list(b.candidates),
                    "disagreements": list(b.disagreements),
                    "reason": (
                        SKIP_NO_ORIGINAL_SET_CODE
                        if not (b.expected_set_code or b.is_promo)
                        else SKIP_NO_BASELINE_OCCURRENCE
                        if not (b.name_jp and b.card_type)
                        else SKIP_CARD_EVIDENCE_DISAGREES
                    ),
                }
                for code, b in sorted(self.baselines.items())
                if not b.composable
            },
        }


def audit_canonical_baselines(
    plans: Iterable[PlannedPrint],
    *,
    entries: dict[str, Any] | None = None,
) -> BaselineAudit:
    """Baselines for every card code the plan proposes to create a card for.

    Occurrences are grouped over the WHOLE plan, not only its create rows: a
    card's original printing may itself be a needs_review occurrence, and it
    is still the evidence that settles the card's rarity.
    """
    plans = list(plans)
    by_code: dict[str, list[PlannedPrint]] = {}
    for planned in plans:
        code = (planned.card_code or "").strip().upper()
        if code:
            by_code.setdefault(code, []).append(planned)

    wanted = {
        (p.card_code or "").strip().upper()
        for p in plans
        if p.outcome == OUTCOME_CREATE and p.proposed_canonical_card is not None
    }
    wanted.discard("")

    audit = BaselineAudit()
    for code in sorted(wanted):
        audit.baselines[code] = resolve_canonical_baseline(
            code, by_code.get(code, []), entries=entries
        )
    return audit


# --- §2 eligibility -------------------------------------------------------
@dataclass(frozen=True)
class Eligibility:
    planned: PlannedPrint
    eligible: bool
    reasons: tuple[str, ...]


def _metadata_complete(planned: PlannedPrint) -> bool:
    """All four published values present.

    The planner's contract is that these come verbatim from the occurrence.
    A print whose catalogue entry omits one is evidence Atlas does not have,
    so it is not applied rather than written with a NULL that would later be
    indistinguishable from "not yet imported".
    """
    return all(getattr(planned, name) is not None for name in METADATA_FIELDS)


def evaluate_eligibility(
    planned: PlannedPrint,
    *,
    composable_card_codes: set[str] | None = None,
    baselines: dict[str, CanonicalBaseline] | None = None,
    authorised_uncoded_names: frozenset[str] | None = None,
) -> Eligibility:
    """Whether one plan may be applied. Consumes the planner; re-decides nothing."""
    reasons: list[str] = []

    if planned.outcome != OUTCOME_CREATE:
        reasons.append(SKIP_NOT_CREATE)
    if planned.verification_status != VERIFIED:
        reasons.append(SKIP_NOT_VERIFIED)
    if planned.source_catalogue != SOURCE_CATALOGUE:
        reasons.append(SKIP_WRONG_CATALOGUE)
    if not (planned.card_code or "").strip():
        reasons.append(SKIP_NO_CARD_CODE)
    if not planned.official_asset_variant:
        reasons.append(SKIP_NO_VARIANT)
    if not planned.official_image_url:
        reasons.append(SKIP_NO_IMAGE)
    if not planned.official_artwork_sha256:
        reasons.append(SKIP_NO_DIGEST)
    if not _metadata_complete(planned):
        reasons.append(SKIP_INCOMPLETE_METADATA)
    # A coded product, one Atlas already holds, or one this run was
    # explicitly authorised to establish.
    #
    # `authorised_uncoded_names` is the set of product names an operator named
    # on the command line AND that app.services.uncoded_product_evidence
    # proved against the frozen JP catalogue. It is not a relaxation of this
    # rule: an unnamed or unproven uncoded product still lands here, so the
    # default (None) behaves exactly as before. What it buys is that
    # establishing a product and importing its prints can happen in ONE
    # transaction - the audit of 2026-08-30 established that creating uncoded
    # products WITHOUT their prints turns ~34 unresolved candidates into
    # conflicts, so the two must not be separable.
    if planned.official_product_code is None and planned.existing_release_product_id is None:
        name = planned.official_product_display_name
        if not (authorised_uncoded_names and name and name in authorised_uncoded_names):
            reasons.append(SKIP_UNCODED_PRODUCT)

    # A print whose canonical card must be CREATED needs that card to be
    # composable. Rarity is not part of that any more; the NOT NULL identity
    # columns are, and none of them may be guessed.
    code = (planned.card_code or "").strip().upper()
    if (
        composable_card_codes is not None
        and planned.existing_canonical_card_id is None
        and code
        and code not in composable_card_codes
    ):
        baseline = (baselines or {}).get(code)
        if baseline is None or not (baseline.expected_set_code or baseline.is_promo):
            reasons.append(SKIP_NO_ORIGINAL_SET_CODE)
        elif not (baseline.name_jp and baseline.card_type):
            reasons.append(SKIP_NO_BASELINE_OCCURRENCE)
        else:
            reasons.append(SKIP_CARD_EVIDENCE_DISAGREES)

    return Eligibility(planned, not reasons, tuple(reasons))


# --- §7 metadata backfill -------------------------------------------------
@dataclass(frozen=True)
class MetadataBackfill:
    card_print_id: int
    values: dict[str, str]


def plan_metadata_backfill(
    planned: PlannedPrint,
    stored: CardPrint,
) -> MetadataBackfill | None:
    """The currently-NULL official metadata this no_change plan may fill in.

    Refuses - by raising - when a stored value disagrees with the catalogue:
    overwriting published evidence Atlas already recorded would destroy the
    only record that the two ever differed.
    """
    if planned.outcome != OUTCOME_NO_CHANGE:
        return None
    if planned.existing_card_print_id != stored.id:
        return None
    # Second line of defence. `_check_existing_asset_digests` already aborts
    # the whole run for this before a row is composed, so in a full run this
    # never fires; it stays because plan_metadata_backfill is callable on its
    # own and must not be a way to write to a print whose digest has drifted.
    if planner.FLAG_ASSET_CHANGED in planned.flags:
        raise ApplyAborted(
            ABORT_EXISTING_ASSET_DIGEST,
            f"card_print #{stored.id} artwork_key no longer equals the catalogue digest",
            {
                "card_print_id": stored.id,
                "stored_artwork_sha256": stored.artwork_key,
                "expected_artwork_sha256": planned.official_artwork_sha256,
            },
        )
    if planned.official_artwork_sha256 and stored.artwork_key != planned.official_artwork_sha256:
        raise ApplyAborted(
            ABORT_EXISTING_ASSET_DIGEST,
            f"card_print #{stored.id} artwork_key {stored.artwork_key!r} != catalogue "
            f"{planned.official_artwork_sha256!r}",
            {
                "card_print_id": stored.id,
                "stored_artwork_sha256": stored.artwork_key,
                "expected_artwork_sha256": planned.official_artwork_sha256,
            },
        )

    values: dict[str, str] = {}
    for name in METADATA_FIELDS:
        published = getattr(planned, name)
        current = getattr(stored, name)
        if current is None:
            if published is not None:
                values[name] = published
        elif published is not None and current != published:
            raise ApplyAborted(
                "existing_metadata_conflict",
                f"card_print #{stored.id} {name} is {current!r} but the catalogue "
                f"publishes {published!r}; nothing is overwritten",
            )
    return MetadataBackfill(stored.id, values) if values else None


# --- the run --------------------------------------------------------------
@dataclass
class ApplyReport:
    """§12's structured summary. Printed as JSON; no table is added for it."""

    snapshot_identity: str | None = None
    source_catalogue: str = SOURCE_CATALOGUE
    db_revision: str | None = None
    environment: str | None = None
    applied: bool = False
    started_at: str | None = None
    finished_at: str | None = None

    products_created: int = 0
    product_aliases_created: int = 0
    canonical_cards_created: int = 0
    card_prints_created: int = 0
    existing_print_metadata_updated: int = 0

    plans_total: int = 0
    eligible_plans: int = 0
    skipped_needs_review: int = 0
    # Not "skipped": since 4C-4B a conflict aborts the run, so this is only
    # ever 0 on a run that finished and the exact count on one that refused.
    planner_conflicts: int = 0
    skipped_no_change: int = 0
    skipped_ineligible: dict[str, int] = field(default_factory=dict)

    baseline_counts: dict[str, int] = field(default_factory=dict)
    baseline_excluded: dict[str, Any] = field(default_factory=dict)
    # Codes written with rarity = NULL because the catalogue settles none.
    # Named in the report so the absence stays visible after the import.
    rarity_null_codes: list[str] = field(default_factory=list)

    distinct_image_digests: int = 0
    pre_counts: dict[str, int] = field(default_factory=dict)
    post_counts: dict[str, int] = field(default_factory=dict)

    rollback_reason: str | None = None
    rollback_detail: str | None = None
    # Named values for the refusals whose evidence is a set of fields rather
    # than a sentence - the existing-print digest mismatch, which an operator
    # needs to read card_print_id and both digests out of, and the planner
    # conflict, which is read as the disagreeing canonical and official values
    # per card.
    rollback_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_identity": self.snapshot_identity,
            "source_catalogue": self.source_catalogue,
            "db_revision": self.db_revision,
            "environment": self.environment,
            "applied": self.applied,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "products_created": self.products_created,
            "product_aliases_created": self.product_aliases_created,
            "canonical_cards_created": self.canonical_cards_created,
            "card_prints_created": self.card_prints_created,
            "existing_print_metadata_updated": self.existing_print_metadata_updated,
            "plans_total": self.plans_total,
            "eligible_plans": self.eligible_plans,
            "skipped_needs_review": self.skipped_needs_review,
            "planner_conflicts": self.planner_conflicts,
            "skipped_no_change": self.skipped_no_change,
            "skipped_ineligible": dict(sorted(self.skipped_ineligible.items())),
            "canonical_baseline": {
                "counts": self.baseline_counts,
                "excluded": self.baseline_excluded,
                "rarity_null_codes": self.rarity_null_codes,
                "rarity_null_count": len(self.rarity_null_codes),
            },
            "distinct_image_digests": self.distinct_image_digests,
            "pre_counts": self.pre_counts,
            "post_counts": self.post_counts,
            "rollback_reason": self.rollback_reason,
            "rollback_detail": self.rollback_detail,
            "rollback_context": self.rollback_context,
        }


COUNTED_TABLES = (
    "release_products",
    "canonical_cards",
    "card_prints",
    "source_card_mappings",
    "price_observations",
    "market_index_snapshots",
)

# The three tables this engine must never touch. Counted before and after and
# compared, so "we did not write prices" is proven rather than asserted.
UNTOUCHED_TABLES = (
    "source_card_mappings",
    "price_observations",
    "market_index_snapshots",
)


def current_counts(session: Session) -> dict[str, int]:
    from sqlalchemy import text as _text

    return {
        table: session.execute(_text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in COUNTED_TABLES
    }


def db_revision(session: Session) -> str | None:
    from sqlalchemy import text as _text

    row = session.execute(_text("SELECT version_num FROM alembic_version")).first()
    return row[0] if row else None


@dataclass(frozen=True)
class ApplyPinning:
    """§10. What the run was planned against, re-proved before it commits.

    `snapshot_identity` is the identity of the snapshot this run actually
    loaded. `expected_snapshot_identity` is the one the plan was reviewed
    against, supplied by the operator: when the two differ the corpus has been
    recollected since the plan was read, and the run refuses rather than
    writing from input nobody looked at. Recording the identity is not the
    same as pinning to it, so both fields exist.
    """

    snapshot_identity: str
    source_catalogue: str = SOURCE_CATALOGUE
    expected_db_revision: str | None = None
    expected_pre_counts: dict[str, int] | None = None
    expected_snapshot_identity: str | None = None


# --- 4D-1 the canonical staging write grant -------------------------------
#
# WHY A PYTHON OBJECT AND NOT A FLAG. The generic CLI refuses `--environment
# staging` and always will. If staging write permission were a string, a
# boolean, an environment variable or a config key, then "refuses staging"
# would only mean "refuses staging until someone types the other thing" - and
# the whole point of the refusal is that there is no other thing to type.
#
# So permission is an OBJECT that cannot be spelled on a command line. It is
# minted by `grant_canonical_staging_write()`, which requires an attestation
# that the connection in front of it really is canonical Atlas staging, plus
# the exact confirmation phrase. The constructor is sealed behind a
# module-private key, so a caller cannot fabricate one by importing the class.
#
# And the seal is not the only thing holding: the engine RE-PROVES the grant
# against the live session before it writes (see `_check_staging_grant`). A
# forged grant that somehow got past the key still has to agree with the
# alembic revision of the database actually connected, which an attacker
# writing a fake object has no way to make true for the wrong database.


@dataclass(frozen=True)
class StagingTargetAttestation:
    """Evidence that a specific connection is the canonical Atlas staging DB.

    Built by `app.services.canonical_staging_target` from the fingerprints in
    `scripts/staging_db_read_check.py` - reused wholesale, never restated
    here. This engine deliberately holds no opinion about what staging looks
    like; it only checks that every fingerprint the established checker ran
    came back PASS, and that the revision recorded here is the revision of the
    session about to be written.

    Carries no URL, no host, no credential - nothing that would make an
    attestation unsafe to print or to put in a report.
    """

    railway_environment: str
    railway_service: str
    database: str
    db_revision: str
    checks: tuple[tuple[str, bool], ...] = ()

    @property
    def all_checks_passed(self) -> bool:
        return bool(self.checks) and all(ok for _, ok in self.checks)

    @property
    def failed_checks(self) -> tuple[str, ...]:
        return tuple(name for name, ok in self.checks if not ok)

    def describe(self) -> dict[str, Any]:
        return {
            "railway_environment": self.railway_environment,
            "railway_service": self.railway_service,
            "database": self.database,
            "db_revision": self.db_revision,
            "checks_passed": sum(1 for _, ok in self.checks if ok),
            "checks_total": len(self.checks),
        }


class _GrantKey:
    """Module-private. Its only purpose is to be unobtainable from outside."""

    __slots__ = ()


_GRANT_KEY = _GrantKey()


class CanonicalStagingWriteGrant:
    """Permission for ONE applier to write to canonical staging.

    Not constructible by callers: `__init__` refuses without the module's own
    key object, so `CanonicalStagingWriteGrant(...)` from anywhere else raises
    rather than producing permission. Mint via
    `grant_canonical_staging_write()`.
    """

    __slots__ = ("attestation",)

    def __init__(self, key: Any, attestation: StagingTargetAttestation) -> None:
        if key is not _GRANT_KEY:
            raise PermissionError(
                "CanonicalStagingWriteGrant cannot be constructed directly; "
                "mint one with grant_canonical_staging_write()"
            )
        self.attestation = attestation


def grant_canonical_staging_write(
    *, confirmation: str, attestation: StagingTargetAttestation
) -> CanonicalStagingWriteGrant:
    """Mints a staging write grant, or refuses.

    `confirmation` must equal STAGING_APPLY_CONFIRMATION exactly. The typed
    value is never echoed - a refusal says that it did not match, not what was
    typed - so a shell history or a CI log cannot be mined for near misses.
    """
    if confirmation != STAGING_APPLY_CONFIRMATION:
        raise ApplyAborted(
            "staging_confirmation_mismatch",
            "the canonical staging confirmation phrase was missing or did not "
            "match exactly; nothing was written",
        )
    if attestation.railway_environment != CANONICAL_STAGING_ENVIRONMENT:
        raise ApplyAborted(
            "staging_target_not_attested",
            f"attestation names environment "
            f"{attestation.railway_environment!r}, not "
            f"{CANONICAL_STAGING_ENVIRONMENT!r}",
        )
    if not attestation.all_checks_passed:
        raise ApplyAborted(
            "staging_target_not_attested",
            "the staging fingerprint did not pass: "
            + (", ".join(attestation.failed_checks) or "no checks were run"),
        )
    if not attestation.db_revision:
        raise ApplyAborted(
            "staging_target_not_attested",
            "the attestation carries no alembic revision to bind the grant to",
        )
    return CanonicalStagingWriteGrant(_GRANT_KEY, attestation)


class CanonicalImportApplier:
    """One apply run. Writes only inside `run(apply=True)`, and only once."""

    def __init__(
        self,
        session: Session,
        plan: ImportPlan,
        *,
        pinning: ApplyPinning,
        environment: str,
        entries: dict[str, Any] | None = None,
        staging_grant: CanonicalStagingWriteGrant | None = None,
        authorised_uncoded_products: dict[str, Any] | None = None,
        source_renderings: dict[str, tuple[tuple[str, str], ...]] | None = None,
    ) -> None:
        self._session = session
        self._plan = plan
        self._pinning = pinning
        self._environment = (environment or "").strip().lower()
        # 4D-1. None for every caller except the dedicated staging runner.
        # Keyword-only and typed as an object, so no CLI flag, environment
        # variable or config value can supply it.
        self._staging_grant = staging_grant
        # Entry-id -> OfficialCardEntry, from the same frozen snapshot the
        # plan was built from. Only the baseline occurrence's numeric blocks
        # are read from it; identity never is.
        self._entries = entries or {}
        # Exact frozen product name -> UncodedProductEvidence, one entry per
        # product an operator named and the JP-only standard proved. Empty for
        # every caller that does not pass one, which is every caller today
        # except the uncoded-product runner.
        self._authorised_uncoded = dict(authorised_uncoded_products or {})
        # Frozen product name -> ((alias_name, source_name), ...). How a
        # storefront writes a product this run establishes, recorded as
        # `source_rendering` evidence so the exact-print gate can resolve a
        # source label to a product that has no code to resolve to. Passed in
        # rather than known here: which marketplace writes what is not a fact
        # about importing a catalogue, and this class must not learn it.
        self._source_renderings = dict(source_renderings or {})

    # -- guards ------------------------------------------------------------
    def _check_environment(self) -> None:
        # Production first and unconditionally: the return below is the only
        # way out of this branch, so no grant, attestation or confirmation is
        # ever consulted for it.
        if self._environment in PERMANENTLY_REFUSED_APPLY_ENVIRONMENTS:
            raise ApplyAborted(
                "refused_environment",
                f"apply is hard-refused for environment {self._environment!r}",
            )
        if self._environment == CANONICAL_STAGING_ENVIRONMENT:
            # 4D-1. Reachable only with a grant object, which only
            # `grant_canonical_staging_write()` can mint and only after the
            # target attested as canonical staging. Without one the message is
            # the same refusal callers saw before the runner existed.
            if self._staging_grant is None:
                raise ApplyAborted(
                    "refused_environment",
                    f"apply is hard-refused for environment {self._environment!r}",
                )
            return
        if self._staging_grant is not None:
            raise ApplyAborted(
                "refused_environment",
                "a canonical staging write grant was supplied for environment "
                f"{self._environment!r}; a grant authorises "
                f"{CANONICAL_STAGING_ENVIRONMENT!r} and nothing else",
            )
        if self._environment in REFUSED_APPLY_ENVIRONMENTS:
            raise ApplyAborted(
                "refused_environment",
                f"apply is hard-refused for environment {self._environment!r}",
            )
        if self._environment not in ALLOWED_APPLY_ENVIRONMENTS:
            raise ApplyAborted(
                "refused_environment",
                f"environment {self._environment!r} is not in the apply allowlist "
                f"{ALLOWED_APPLY_ENVIRONMENTS}",
            )

    def _check_staging_grant(self) -> None:
        """Re-proves the grant against the session that is about to write.

        The sealed constructor stops a grant being fabricated; this stops a
        genuine grant being pointed at a different database. The attested
        revision must be the revision of THIS connection, so a grant minted
        against staging cannot be carried over to anything else - including a
        restored copy that has since been migrated past staging's head.
        """
        grant = self._staging_grant
        if grant is None:  # pragma: no cover - _check_environment ran first
            raise ApplyAborted(
                "refused_environment",
                "canonical staging writes require a grant",
            )
        if not isinstance(grant, CanonicalStagingWriteGrant):
            raise ApplyAborted(
                "staging_target_not_attested",
                "the supplied staging authorisation is not a "
                "CanonicalStagingWriteGrant",
            )
        attestation = grant.attestation
        if not attestation.all_checks_passed:
            raise ApplyAborted(
                "staging_target_not_attested",
                "the staging fingerprint did not pass: "
                + (", ".join(attestation.failed_checks) or "no checks were run"),
            )
        live = db_revision(self._session)
        if live != attestation.db_revision:
            raise ApplyAborted(
                "staging_target_revision_mismatch",
                f"the attested staging database is at "
                f"{attestation.db_revision!r} but this connection is at "
                f"{live!r}; the grant does not authorise it",
            )

    def _take_import_lock(self) -> None:
        """One apply run at a time, released when the transaction ends.

        A transaction-scoped advisory lock rather than a row or a table: it
        needs no schema, and it cannot outlive the run that took it even if
        the process dies. Non-blocking, so a second concurrent run is told
        what is happening instead of waiting behind it. Silently skipped on
        engines without advisory locks (sqlite in the unit tests), where
        concurrency is not a real condition.
        """
        from sqlalchemy import text as _text

        if self._session.bind is None or self._session.bind.dialect.name != "postgresql":
            return
        acquired = self._session.execute(
            _text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": IMPORT_LOCK_KEY}
        ).scalar_one()
        if not acquired:
            raise ApplyAborted(
                "import_run_in_progress",
                "another canonical import apply run holds the advisory lock",
            )

    def _check_pinning(self, pre: dict[str, int]) -> None:
        if self._staging_grant is not None:
            self._check_staging_grant()
        revision = db_revision(self._session)
        expected = self._pinning.expected_db_revision
        if expected is not None and revision != expected:
            raise ApplyAborted(
                "db_revision_mismatch",
                f"database is at {revision!r}, plan was built against {expected!r}",
            )
        expected_snapshot = self._pinning.expected_snapshot_identity
        if (
            expected_snapshot is not None
            and expected_snapshot != self._pinning.snapshot_identity
        ):
            raise ApplyAborted(
                "snapshot_identity_mismatch",
                f"the snapshot on disk is {self._pinning.snapshot_identity!r}, the plan "
                f"was built from {expected_snapshot!r}",
            )
        if self._pinning.source_catalogue != SOURCE_CATALOGUE:
            raise ApplyAborted(
                "source_catalogue_mismatch",
                f"apply supports {SOURCE_CATALOGUE!r} only, got "
                f"{self._pinning.source_catalogue!r}",
            )
        expected_counts = self._pinning.expected_pre_counts
        if expected_counts is not None:
            drifted = {
                table: (expected_counts.get(table), pre.get(table))
                for table in expected_counts
                if expected_counts.get(table) != pre.get(table)
            }
            if drifted:
                raise ApplyAborted(
                    "stale_pre_apply_counts",
                    f"the database changed under the plan: {drifted}",
                )

    # -- the run -----------------------------------------------------------
    def run(self, *, apply: bool = False) -> ApplyReport:
        report = ApplyReport(
            snapshot_identity=self._pinning.snapshot_identity,
            source_catalogue=self._pinning.source_catalogue,
            environment=self._environment,
            started_at=datetime.now(timezone.utc).isoformat(),
            plans_total=len(self._plan.prints),
        )
        try:
            self._execute(report, apply=apply)
        except ApplyAborted as exc:
            self._session.rollback()
            report.applied = False
            report.rollback_reason = exc.reason
            report.rollback_detail = exc.detail
            report.rollback_context = dict(exc.context)
            report.finished_at = datetime.now(timezone.utc).isoformat()
            report.post_counts = current_counts(self._session)
            raise ApplyRunFailed(report) from exc
        report.finished_at = datetime.now(timezone.utc).isoformat()
        return report

    def _execute(self, report: ApplyReport, *, apply: bool) -> None:
        if apply:
            self._check_environment()

        # 1. planner input, re-read from the session that will do the writing
        if apply:
            self._take_import_lock()
        pre = current_counts(self._session)
        report.pre_counts = pre
        report.db_revision = db_revision(self._session)
        self._check_pinning(pre)

        # 2. no planner conflict anywhere in the plan. First of the plan-level
        #    preflights and before the baseline audit reads a single entry, so
        #    a conflicting run does no work at all beyond proving it must not
        #    run.
        self._check_no_planner_conflicts(report)

        # 3. baselines, before a single row is composed
        audit = audit_canonical_baselines(self._plan.prints, entries=self._entries)
        report.baseline_counts = audit.counts()
        report.baseline_excluded = audit.to_dict()["excluded"]
        composable = audit.composable_codes
        report.rarity_null_codes = sorted(audit.rarity_null_codes)

        # 4. eligibility. No OUTCOME_CONFLICT can reach this loop - step 2
        #    aborted the run - and if one ever did, `evaluate_eligibility`
        #    refuses it for SKIP_NOT_CREATE rather than writing it.
        eligible: list[PlannedPrint] = []
        for planned in self._plan.prints:
            if planned.outcome == OUTCOME_NEEDS_REVIEW:
                report.skipped_needs_review += 1
                continue
            if planned.outcome == OUTCOME_NO_CHANGE:
                report.skipped_no_change += 1
                continue
            decision = evaluate_eligibility(
                planned,
                composable_card_codes=composable,
                baselines=audit.baselines,
                authorised_uncoded_names=frozenset(self._authorised_uncoded),
            )
            if decision.eligible:
                eligible.append(planned)
            else:
                for reason in decision.reasons:
                    report.skipped_ineligible[reason] = (
                        report.skipped_ineligible.get(reason, 0) + 1
                    )
        report.eligible_plans = len(eligible)
        report.distinct_image_digests = len(
            {p.official_artwork_sha256 for p in eligible if p.official_artwork_sha256}
        )

        # 5. preflight, over the COMPLETE plan and not only the eligible
        #    subset. A digest that disagrees on a print Atlas already holds is
        #    checked here - before anything is composed - so the answer to
        #    "did this run write anything?" is no.
        self._check_existing_asset_digests()
        self._check_proposed_identity_unique(eligible)
        self._check_established_products(eligible)

        if not apply:
            report.applied = False
            report.post_counts = pre
            return

        # 6. the writes, all inside the caller's transaction.
        #
        # Uncoded products are created in the SAME transaction as the prints
        # that reference them, and never in one of their own: the 2026-08-30
        # residual audit established that a product with no prints narrows the
        # exact-print gate's survivor set to empty, which turns an unresolved
        # candidate into a conflict. Products and prints are one unit or they
        # are a regression.
        products = self._create_products(eligible, report)
        self._session.flush()
        uncoded = self._create_uncoded_release_products(eligible, report)
        cards = self._create_canonical_cards(eligible, audit, report)
        self._session.flush()
        self._create_card_prints(eligible, products, cards, report, uncoded_products=uncoded)
        self._session.flush()
        self._backfill_existing_metadata(report)
        self._session.flush()

        # 7. post-write invariants, before commit
        post = current_counts(self._session)
        self._check_untouched(pre, post)
        self._check_no_duplicate_identity()

        self._session.commit()
        report.applied = True
        report.post_counts = current_counts(self._session)

    # -- invariants --------------------------------------------------------
    def _check_no_planner_conflicts(self, report: ApplyReport) -> None:
        """4C-4B. One `conflict` anywhere in the plan and nothing is written.

        WHAT A CONFLICT IS, AND WHY IT IS FATAL. The planner raises
        OUTCOME_CONFLICT only when the catalogue disagrees with a canonical
        row Atlas already holds about the card ITSELF - its baseline name, its
        baseline rarity, its type - as opposed to a difference between two
        printings, which is a note. So a conflict is never "this row has thin
        evidence, import the rest": it is two records of the same card that no
        longer agree. Importing 4260 other rows on top of that would bury the
        disagreement under a run that reports success, which is exactly how a
        catalogue splits quietly. The same reasoning as
        ABORT_EXISTING_ASSET_DIGEST, applied to identity instead of artwork.

        WHAT IT DOES NOT DO. It does not re-decide anything: the planner's
        outcome is read and never edited, no conflict is demoted to
        needs_review, and neither the canonical nor the official value is
        touched. needs_review is deliberately NOT fatal here - an ambiguity
        the planner refused to resolve costs its own rows and nothing else.

        Read over the COMPLETE plan, not the eligible subset: a conflict is
        never eligible, so a check that looked at eligible rows would never
        see one.
        """
        conflicts = [p for p in self._plan.prints if p.outcome == OUTCOME_CONFLICT]
        report.planner_conflicts = len(conflicts)
        if not conflicts:
            return

        context = {
            "planner_conflicts": len(conflicts),
            "reported": min(len(conflicts), CONFLICT_CONTEXT_LIMIT),
            "conflicts": [
                self._conflict_context(planned)
                for planned in conflicts[:CONFLICT_CONTEXT_LIMIT]
            ],
        }
        first = context["conflicts"][0]
        raise ApplyAborted(
            ABORT_PLANNER_CONFLICT,
            f"{len(conflicts)} planned print(s) carry outcome={OUTCOME_CONFLICT!r}; "
            f"the first is {first['card_code']} (entry {first['entry_id']}) in "
            f"{first['official_product_code'] or first['official_product_display_name']} "
            f"against canonical card #{first['existing_canonical_card_id']}: "
            + "; ".join(first["reasons"])
            + " - nothing is written and no canonical value is overwritten",
            context,
        )

    def _conflict_context(self, planned: PlannedPrint) -> dict[str, Any]:
        """The named values an operator diagnoses one conflict from.

        Both sides of the disagreement, the identity that carries it and the
        planner's own reasons. The canonical side is re-read from the session
        that would have done the writing rather than trusted from the plan, so
        what is reported is what the database holds now. Nothing outside the
        conflicting card is read.
        """
        canonical = (
            self._session.get(CanonicalCard, planned.existing_canonical_card_id)
            if planned.existing_canonical_card_id is not None
            else None
        )
        return {
            "entry_id": planned.entry_id,
            "card_code": (planned.card_code or "").strip().upper() or None,
            "existing_canonical_card_id": planned.existing_canonical_card_id,
            "existing_card_print_id": planned.existing_card_print_id,
            "official_product_code": planned.official_product_code,
            "official_product_display_name": planned.official_product_display_name,
            "flags": list(planned.flags),
            "reasons": list(planned.reasons),
            "canonical": (
                {
                    "name_jp": canonical.name_jp,
                    "rarity": canonical.rarity,
                    "card_type": canonical.card_type,
                    "original_set_code": canonical.original_set_code,
                }
                if canonical is not None
                else None
            ),
            "official": {
                "card_name": planned.official_card_name,
                "rarity": planned.official_rarity,
                "name": planned.official_name,
                "source_url": planned.source_url,
            },
        }

    def _check_existing_asset_digests(self) -> None:
        """§3. Any existing exact print whose stored digest disagrees stops the run.

        WHY THIS IS FATAL AND A MISSING DIGEST IS NOT. The two look alike and
        are opposites. A NEW planned print with no established digest is
        missing input: Atlas holds nothing, nobody's record is wrong, and the
        right answer is to leave that one row unimported (needs_review /
        ineligible) and import the rest. An EXISTING exact print whose stored
        artwork_key disagrees with the frozen official evidence is integrity
        drift: two records that were once the same have diverged, and until
        someone says which is right, every other row in the run is being
        written on top of an unexplained divergence in the same table. So this
        one aborts the whole run, and neither value is touched.

        Checked over the whole plan, not the eligible subset: the planner
        sends an `asset_changed` plan to needs_review, so it is never eligible
        and a check that only looked at eligible rows would never see it. The
        stored row is re-read and compared here rather than the flag being
        trusted on its own, so a plan built against a different session cannot
        wave a drifted print through.

        Runs before any row is composed, so an abort leaves the transaction
        with nothing in it.
        """
        for planned in self._plan.prints:
            if planned.existing_card_print_id is None:
                continue
            stored = self._session.get(CardPrint, planned.existing_card_print_id)
            if stored is None:
                continue
            expected = planned.official_artwork_sha256
            flagged = planner.FLAG_ASSET_CHANGED in planned.flags
            mismatched = bool(
                expected and stored.artwork_key and stored.artwork_key != expected
            )
            if not (flagged or mismatched):
                continue
            product = self._session.get(ReleaseProduct, stored.release_product_id)
            context = {
                "card_print_id": stored.id,
                "card_code": (planned.card_code or "").strip().upper() or None,
                "entry_id": planned.entry_id,
                "release_product_id": stored.release_product_id,
                "release_product_code": (
                    product.official_code if product is not None else None
                ),
                "release_product_name": (
                    product.display_name if product is not None else None
                ),
                "official_asset_variant": stored.official_asset_variant,
                "stored_artwork_sha256": stored.artwork_key,
                "expected_artwork_sha256": expected,
                "official_image_url": planned.official_image_url,
                "flagged_by_planner": flagged,
            }
            raise ApplyAborted(
                ABORT_EXISTING_ASSET_DIGEST,
                f"card_print #{stored.id} ({context['card_code']} in "
                f"{context['release_product_code']}, variant "
                f"{stored.official_asset_variant}) stores artwork_key "
                f"{stored.artwork_key!r} but the frozen catalogue evidence is "
                f"{expected!r}; nothing is written and neither value is overwritten",
                context,
            )

    @staticmethod
    def _check_proposed_identity_unique(eligible: Sequence[PlannedPrint]) -> None:
        """Two eligible plans must never propose the same final identity.

        Checked on the plan rather than left to the unique index, so the run
        aborts with the colliding entry ids named instead of a bare
        IntegrityError.
        """
        seen: dict[tuple, str] = {}
        for planned in eligible:
            key = (
                (planned.card_code or "").strip().upper(),
                planned.language,
                planned.official_product_code,
                planned.existing_release_product_id,
                planned.official_asset_variant,
            )
            if key in seen:
                raise ApplyAborted(
                    "duplicate_proposed_identity",
                    f"entries {seen[key]!r} and {planned.entry_id!r} propose the same "
                    f"final identity {key}",
                )
            seen[key] = planned.entry_id

    def _check_established_products(self, eligible: Sequence[PlannedPrint]) -> None:
        """§5. A product Atlas already holds is never silently reused when the
        catalogue's own authority evidence disagrees with it.

        The planner resolves a coded product by `(source_catalogue,
        official_code)` and does not compare the series behind it. If the
        stored row was created from a different series page than the one this
        occurrence was captured under, attaching prints to it would file them
        against a product record nobody has reconciled - so the whole run
        stops and a human decides which record is right. Nothing is
        overwritten either way.
        """
        checked: set[int] = set()
        for planned in eligible:
            product_id = planned.existing_release_product_id
            if product_id is None or product_id in checked:
                continue
            checked.add(product_id)
            product = self._session.get(ReleaseProduct, product_id)
            if product is None:
                raise ApplyAborted(
                    "product_evidence_conflict",
                    f"release_product #{product_id} named by entry {planned.entry_id!r} "
                    "no longer exists",
                )
            if (
                planned.source_series_id
                and product.source_series_id
                and product.source_series_id != planned.source_series_id
            ):
                raise ApplyAborted(
                    "product_evidence_conflict",
                    f"release_product #{product.id} ({product.official_code}) was "
                    f"established from series {product.source_series_id!r} but the "
                    f"catalogue publishes this occurrence under "
                    f"{planned.source_series_id!r}",
                )
            if (
                planned.official_product_code
                and product.official_code
                and product.official_code != planned.official_product_code
            ):
                raise ApplyAborted(
                    "product_evidence_conflict",
                    f"release_product #{product.id} carries official_code "
                    f"{product.official_code!r}, not {planned.official_product_code!r}",
                )

    def _check_untouched(self, pre: dict[str, int], post: dict[str, int]) -> None:
        for table in UNTOUCHED_TABLES:
            if pre.get(table) != post.get(table):
                raise ApplyAborted(
                    "untouched_table_changed",
                    f"{table} changed from {pre.get(table)} to {post.get(table)}",
                )

    def _check_no_duplicate_identity(self) -> None:
        rows = self._session.execute(
            select(
                CardPrint.canonical_card_id,
                CardPrint.language,
                CardPrint.release_product_id,
                CardPrint.official_asset_variant,
                func.count(),
            )
            .where(CardPrint.is_active.is_(True), CardPrint.verification_status == VERIFIED)
            .group_by(
                CardPrint.canonical_card_id,
                CardPrint.language,
                CardPrint.release_product_id,
                CardPrint.official_asset_variant,
            )
            .having(func.count() > 1)
        ).all()
        if rows:
            raise ApplyAborted(
                "duplicate_final_identity",
                f"{len(rows)} duplicate identity group(s) after write: {rows[:5]}",
            )

    # -- writes ------------------------------------------------------------
    def _create_products(
        self, eligible: Sequence[PlannedPrint], report: ApplyReport
    ) -> dict[str, ReleaseProduct]:
        """Missing CODED bandai_jp products, created exactly once each.

        Reuse is resolved by reading the row first, using the same
        `(source_catalogue, official_code)` contract the planner used - never
        by attempting an insert and catching the integrity error.
        """
        wanted: dict[str, PlannedPrint] = {}
        for planned in eligible:
            code = planned.official_product_code
            if code and planned.existing_release_product_id is None:
                wanted.setdefault(code, planned)

        resolved: dict[str, ReleaseProduct] = {}
        for code, planned in sorted(wanted.items()):
            existing = self._session.execute(
                select(ReleaseProduct).where(
                    ReleaseProduct.source_catalogue == SOURCE_CATALOGUE,
                    ReleaseProduct.official_code == code,
                )
            ).scalar_one_or_none()
            if existing is not None:
                self._check_product_agreement(existing, planned)
                resolved[code] = existing
                continue

            proposed = planned.proposed_release_product
            if proposed is None or not proposed.source_series_id or not proposed.source_url:
                raise ApplyAborted(
                    "product_evidence_incomplete",
                    f"product {code!r} has no series authority evidence to create it from",
                )
            product = ReleaseProduct(
                source_catalogue=SOURCE_CATALOGUE,
                official_code=code,
                display_name=proposed.display_name,
                first_seen_name=proposed.first_seen_name,
                source_series_id=proposed.source_series_id,
                source_url=proposed.source_url,
                verification_status=VERIFIED,
            )
            self._session.add(product)
            resolved[code] = product
            report.products_created += 1
        return resolved

    @staticmethod
    def _check_product_agreement(existing: ReleaseProduct, planned: PlannedPrint) -> None:
        """An established product is never overwritten, and never silently reused
        when the catalogue's authority evidence disagrees with it."""
        proposed = planned.proposed_release_product
        if proposed is None:
            return
        if proposed.source_series_id and existing.source_series_id != proposed.source_series_id:
            raise ApplyAborted(
                "product_evidence_conflict",
                f"release_product #{existing.id} ({existing.official_code}) has series "
                f"{existing.source_series_id!r} but the catalogue says "
                f"{proposed.source_series_id!r}",
            )

    def _create_uncoded_release_products(
        self,
        eligible: Sequence[PlannedPrint],
        report: ApplyReport,
    ) -> dict[str, ReleaseProduct]:
        """Missing AUTHORISED uncoded bandai_jp products, created exactly once.

        Deliberately parallel to `_create_release_products` and deliberately
        separate from it. A coded product is reused on
        `(source_catalogue, official_code)`; an uncoded one has no code, so it
        is reused on its EXACT frozen catalogue name - the same untransformed
        equality `PrintImportPlanner._uncoded_product_by_exact_name` uses, and
        for the same reason: the repo's own normalize_release_text collapses
        30 Bandai products into 13 keys, so anything fuzzier would merge real
        products.

        Two things this may not do, both of which the evidence object exists
        to prevent. It never invents an `official_code` - the column stays
        NULL, which the schema explicitly allows because "Bandai ships uncoded
        limited/promotional products, and those prints are legitimate". And it
        never creates a product this run was not authorised for: the name must
        be in `self._authorised_uncoded`, which only proven evidence populates.
        """
        wanted: dict[str, PlannedPrint] = {}
        for planned in eligible:
            name = planned.official_product_display_name
            if (
                planned.official_product_code is None
                and planned.existing_release_product_id is None
                and name
                and name in self._authorised_uncoded
            ):
                wanted.setdefault(name, planned)

        resolved: dict[str, ReleaseProduct] = {}
        for name, _planned in sorted(wanted.items()):
            evidence = self._authorised_uncoded[name]
            existing = self._session.execute(
                select(ReleaseProduct).where(
                    ReleaseProduct.source_catalogue == SOURCE_CATALOGUE,
                    ReleaseProduct.official_code.is_(None),
                    ReleaseProduct.first_seen_name == name,
                )
            ).scalars().first()
            if existing is not None:
                if existing.source_series_id != evidence.source_series_id:
                    raise ApplyAborted(
                        "product_evidence_conflict",
                        f"release_product #{existing.id} ({name!r}) has series "
                        f"{existing.source_series_id!r} but the catalogue says "
                        f"{evidence.source_series_id!r}",
                    )
                resolved[name] = existing
                continue

            product = ReleaseProduct(
                source_catalogue=SOURCE_CATALOGUE,
                official_code=None,
                display_name=name,
                first_seen_name=name,
                source_series_id=evidence.source_series_id,
                source_url=evidence.source_url,
                verification_status=VERIFIED,
            )
            self._session.add(product)
            resolved[name] = product
            report.products_created += 1
        if resolved:
            # Ids are needed by _create_card_prints in this same transaction,
            # and by the alias rows below.
            self._session.flush()
            self._record_source_renderings(resolved, report)
        return resolved

    def _record_source_renderings(
        self, products: dict[str, ReleaseProduct], report: ApplyReport
    ) -> None:
        """Storefront spellings for the products this run established.

        Written as `source_rendering` and never anything else, so a
        marketplace's wording can never be read back as a name Bandai
        publishes - the distinction `ReleaseProductAlias.alias_kind` exists to
        keep, and the one the 2026-08-10 fabricated-evidence incident came
        from. `source_url` is deliberately left NULL: the provenance of a
        source rendering is the declared rendering table, and minting a
        plausible storefront URL to fill the column would be fabricating
        exactly the evidence the column is for.

        Idempotent by the table's own (product_id, alias_kind, alias_name)
        identity, so a second run adds nothing.
        """
        for name, product in sorted(products.items()):
            for alias_name, _source_name in self._source_renderings.get(name, ()):
                exists = self._session.execute(
                    select(ReleaseProductAlias).where(
                        ReleaseProductAlias.product_id == product.id,
                        ReleaseProductAlias.alias_kind == SOURCE_RENDERING_KIND,
                        ReleaseProductAlias.alias_name == alias_name,
                    )
                ).scalars().first()
                if exists is not None:
                    continue
                self._session.add(
                    ReleaseProductAlias(
                        product_id=product.id,
                        alias_name=alias_name,
                        alias_kind=SOURCE_RENDERING_KIND,
                        source_url=None,
                    )
                )
                report.product_aliases_created += 1
        self._session.flush()

    def _create_canonical_cards(
        self,
        eligible: Sequence[PlannedPrint],
        audit: BaselineAudit,
        report: ApplyReport,
    ) -> dict[str, CanonicalCard]:
        wanted = {
            (p.card_code or "").strip().upper()
            for p in eligible
            if p.existing_canonical_card_id is None
        }
        wanted.discard("")

        resolved: dict[str, CanonicalCard] = {}
        for code in sorted(wanted):
            existing = self._session.execute(
                select(CanonicalCard).where(CanonicalCard.card_code == code)
            ).scalar_one_or_none()
            if existing is not None:
                resolved[code] = existing
                continue

            baseline = audit.baselines.get(code)
            if baseline is None or not baseline.composable:
                raise ApplyAborted(
                    "canonical_card_not_composable",
                    f"canonical card {code!r} has no baseline identity evidence "
                    f"(set code, name and card type) to be created from",
                )
            card = CanonicalCard(
                card_code=code,
                name_jp=baseline.name_jp,
                original_set_code=baseline.expected_set_code,
                # NULL when the catalogue settles no card-level rarity - the
                # 18 codes whose own set publishes two. Never a tie broken by
                # first/most-common/highest, and never derived from a pN/rN
                # suffix. Each print still carries its own official_rarity.
                rarity=baseline.rarity,
                card_type=baseline.card_type,
                # Language-independent numbers only. colors, attribute,
                # effect_text and trigger_text stay NULL - see NUMERIC_FIELDS
                # for the measured reason (those columns hold English today).
                cost=baseline.cost,
                power=baseline.power,
                counter=baseline.counter,
            )
            self._session.add(card)
            resolved[code] = card
            report.canonical_cards_created += 1
        return resolved

    def _create_card_prints(
        self,
        eligible: Sequence[PlannedPrint],
        products: dict[str, ReleaseProduct],
        cards: dict[str, CanonicalCard],
        report: ApplyReport,
        uncoded_products: dict[str, ReleaseProduct] | None = None,
    ) -> None:
        for planned in eligible:
            code = (planned.card_code or "").strip().upper()
            card = cards.get(code)
            card_id = planned.existing_canonical_card_id or (card.id if card else None)
            if card_id is None:
                raise ApplyAborted(
                    "canonical_card_unresolved",
                    f"no canonical card id for {code!r} at print creation",
                )

            product_id = planned.existing_release_product_id
            if product_id is None and planned.official_product_code:
                product = products.get(planned.official_product_code)
                product_id = product.id if product else None
            if product_id is None and not planned.official_product_code:
                # An authorised uncoded product created earlier in this same
                # transaction. Keyed on the exact frozen name, never on a code.
                product = (uncoded_products or {}).get(
                    planned.official_product_display_name or ""
                )
                product_id = product.id if product else None
            if product_id is None:
                raise ApplyAborted(
                    "release_product_unresolved",
                    f"no release product id for entry {planned.entry_id!r}",
                )

            # Resolve before insert, using the planner's own identity contract
            # - this is what makes a second run write nothing.
            existing = self._session.execute(
                select(CardPrint).where(
                    CardPrint.canonical_card_id == card_id,
                    CardPrint.language == LANGUAGE,
                    CardPrint.release_product_id == product_id,
                    CardPrint.official_asset_variant == planned.official_asset_variant,
                    CardPrint.is_active.is_(True),
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue

            self._session.add(
                CardPrint(
                    canonical_card_id=card_id,
                    language=LANGUAGE,
                    treatment=None,
                    release_product_id=product_id,
                    release_product_code=planned.official_product_code,
                    artwork_key=planned.official_artwork_sha256,
                    official_asset_variant=planned.official_asset_variant,
                    official_rarity=planned.official_rarity,
                    official_block_icon=planned.official_block_icon,
                    official_name=planned.official_name,
                    official_effect_text=planned.official_effect_text,
                    image_url=planned.official_image_url,
                    verification_status=VERIFIED,
                    is_active=True,
                )
            )
            report.card_prints_created += 1

    def _backfill_existing_metadata(self, report: ApplyReport) -> None:
        for planned in self._plan.prints:
            if planned.outcome != OUTCOME_NO_CHANGE or planned.existing_card_print_id is None:
                continue
            stored = self._session.get(CardPrint, planned.existing_card_print_id)
            if stored is None:
                continue
            backfill = plan_metadata_backfill(planned, stored)
            if backfill is None:
                continue
            for name, value in backfill.values.items():
                setattr(stored, name, value)
            report.existing_print_metadata_updated += 1


class ApplyRunFailed(RuntimeError):
    """Raised after a rollback, carrying the report that describes it."""

    def __init__(self, report: ApplyReport) -> None:
        super().__init__(f"{report.rollback_reason}: {report.rollback_detail}")
        self.report = report
