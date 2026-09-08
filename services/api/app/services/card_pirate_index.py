"""The Card Pirate Index v1 estimator, chain-linker and replay engine.

`docs/card_pirate_index.md` is the methodology of record and this module is its
implementation. Where the two could disagree, the document wins and this module
is the bug. Every constant, rule and vocabulary item below cites the section it
comes from.

WHAT THIS MODULE IS
--------------------
Three layers, in dependency order:

  1. `compute_step`          - pure. Two days of constituent values in, one
                               StepResult out. No database, no clock, no I/O.
  2. `build_points`          - pure. A whole scope's snapshot history in, the
                               full ordered list of PointDraft rows out,
                               including segment carries and gaps.
  3. `replay_scope` / `verify_scope`  (app.services.card_pirate_index_replay)
                             - the database edges. One reads snapshots and
                               writes points; the other reads both and reports
                               differences without writing anything.

There is deliberately no job, no scheduler and no route here. Those are steps
7 and 8 of the rollout; this is steps 4 and 5.

WHAT THIS MODULE MUST NEVER DO
-------------------------------
The methodology names these explicitly as rejected, and a reviewer should be
able to grep for them and find nothing but this paragraph:

  * No median. It publishes a permanently flat line in this market - on all
    three real v3 steps the median daily log return is exactly zero.
  * No percentile winsorization. With 230 zeros and one mover the empirical
    p99 is ITSELF zero, so it clips away the only signal and degenerates into
    the median it was supposed to improve on.
  * No trimming, no value weighting, no market-cap weighting.
  * No forward-fill, no zero-fill, no interpolation. A print absent on a day
    is absent from that step, never carried forward.
  * No source substitution. This module reads `index_value_jpy` and the
    version pair. It consults no source name and no reference type.

DETERMINISM
------------
Two independent rebuilds over identical source rows must produce identical
natural-key rows and identical numbers. Three things secure that:

  * Every arithmetic value is `Decimal`, quantized at exactly the column's
    precision. Logs and exponentials go through `Decimal.ln()`/`Decimal.exp()`
    so no binary float ever reaches a stored value.
  * The chain multiplies the PUBLISHED (already-quantized) prior level, not an
    unrounded running total. This is the literal reading of the frozen formula
    `level_D = level_P * exp(step_log_return)`, and it is also what makes a
    carried base's level EXACTLY equal to its source's - which the composite
    foreign key requires.
  * Nothing depends on database row order. Every input list is re-sorted here,
    and every set comparison is over sorted keys.

ROUNDING MODE. The methodology froze the precisions (Numeric(12,4) for the
level, Numeric(18,12) for the step) but not the rounding mode. ROUND_HALF_EVEN
is used, because the document's own stated reason for choosing log returns is
that "rounding cannot accumulate directionally across 730 steps" - and
half-even is the mode that keeps that true. Half-up would introduce exactly the
upward bias that sentence rules out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from app.services.market_index_change import (
    ContributorKey,
    eligible_contributor_set,
)
from app.services.print_series import (
    BREAK_INDEX_VERSION_CHANGE,
    BREAK_SOURCE_SEMANTICS_VERSION_CHANGE,
)

# --- frozen constants (methodology section 1) -------------------------------

METHODOLOGY_VERSION = 1
MIN_CONSTITUENTS = 30

# Quantized to the level column's scale at definition. An unquantized
# Decimal("1000") compares equal to Decimal("1000.0000") but does not render
# or serialize identically, and the carry rule turns on the level being
# EXACTLY the source point's - so the base value carries the column's shape
# from the moment it exists rather than acquiring it on the way to the
# database.
BASE_VALUE = Decimal("1000").quantize(Decimal("0.0001"))

# The unconditional per-constituent daily cap, applied at EVERY n. Held as a
# ratio so no float ever enters the arithmetic; ln(1.25) = 0.2231435513...
#
# The cap is symmetric in LOG space, which is asymmetric in percentage terms
# by design: the per-print daily price ratio is clamped to [0.8, 1.25], at
# most +25% up and -20% down. A halving and a doubling are moves of equal
# magnitude and only a log-symmetric bound treats them that way; a
# percent-symmetric +/-25% bound would permit -25% (ratio 0.75) while refusing
# its exact inverse (+33%), putting a directional bias into the estimator.
CAP_RATIO = Decimal("1.25")

# Column precisions, from the frozen schema (section 8.4).
LEVEL_PLACES = Decimal("0.0001")  # Numeric(12,4)
STEP_PLACES = Decimal("0.000000000001")  # Numeric(18,12)

# BASE_VALUE is quantized above, before LEVEL_PLACES exists; this keeps the
# two from drifting apart if the column's scale is ever revisited.
assert BASE_VALUE == BASE_VALUE.quantize(LEVEL_PLACES)
assert BASE_VALUE.as_tuple().exponent == LEVEL_PLACES.as_tuple().exponent

# Internal working precision. Generous enough that quantizing to the column
# precisions above is the only rounding that ever happens.
_WORKING_PRECISION = 40

# --- vocabulary -------------------------------------------------------------

SCOPE_OVERALL = "overall"
SCOPE_SET = "set"
SCOPE_RARITY = "rarity"
SCOPE_KINDS = (SCOPE_OVERALL, SCOPE_SET, SCOPE_RARITY)

UNPUBLISHABLE_INSUFFICIENT_CONSTITUENTS = "insufficient_constituents"
UNPUBLISHABLE_MIXED_VERSION_DAY = "mixed_version_day"

# Break reasons. The first two are print_series' own spellings, imported
# rather than restated so one client primitive renders both series and the two
# vocabularies cannot drift apart.
BREAK_METHODOLOGY_VERSION_CHANGE = "methodology_version_change"
BREAK_SNAPSHOT_GAP = "snapshot_gap"

CHANGE_UNAVAILABLE_NO_POINT = "no_published_point_in_window"
CHANGE_UNAVAILABLE_NO_CONTINUITY = "no_carried_continuity"


# --- the frozen v1 seed (methodology sections 6 and 14) ---------------------
#
# CONFIGURATION, NOT ARITHMETIC. Nothing in compute_step, chain or build_points
# may reference this: the estimator is a pure function of the days it is
# handed, and a date baked into it would make the mechanics unusable for any
# other scope or era. This constant only tells a CALLER which archive to hand
# over.
#
# `history_start` is 2026-09-03 because that is the first day of the
# (methodology 1, index 3, semantics 2) era and the first day with a
# defensible constituent count. The v1/v2 archive before it (2026-08-21 ->
# 2026-09-02) is retained and queryable but is NOT published in this headline
# index: it carries 20 constituents, far below MIN_CONSTITUENTS. Feeding it to
# the builder would make 2026-09-03 a CARRIED base off the v2 era and emit
# boundary breaks the methodology says do not exist there - the series opens
# on 2026-09-03, it does not resume there.


@dataclass(frozen=True)
class SeedSpec:
    """Which scope a replay is for, and where its history begins."""

    scope_kind: str
    scope_key: str
    methodology_version: int
    history_start: date


V1_OVERALL_SEED = SeedSpec(
    scope_kind=SCOPE_OVERALL,
    scope_key="",
    methodology_version=METHODOLOGY_VERSION,
    history_start=date(2026, 9, 3),
)


def _cap() -> Decimal:
    """ln(1.25), at working precision."""
    with localcontext() as ctx:
        ctx.prec = _WORKING_PRECISION
        return +CAP_RATIO.ln()


# --- inputs -----------------------------------------------------------------


@dataclass(frozen=True)
class ConstituentObservation:
    """One print's archived Market Index value on one snapshot day.

    This is deliberately a projection of `market_index_snapshots`, not the ORM
    row: the estimator must be testable without a database, and it must be
    impossible for it to reach a column the methodology does not authorise it
    to read. There is no source name here, no reference type, no rarity and no
    price floor - by construction, not by discipline.
    """

    card_print_id: int
    index_value_jpy: int
    index_version: int
    source_semantics_version: int
    # The (source, reference_type) pairs that actually counted, or None when
    # the archived payload cannot prove the role. None is "cannot compare",
    # never "nothing contributed" - see eligible_contributor_set.
    contributors: frozenset[ContributorKey] | None

    @classmethod
    def from_snapshot_row(
        cls,
        *,
        card_print_id: int,
        index_value_jpy: int,
        index_version: int,
        source_semantics_version: int,
        provenance: dict | None,
    ) -> "ConstituentObservation":
        """Builds an observation from an archived snapshot row.

        The contributor set comes from `market_index_change.
        eligible_contributor_set`, REUSED VERBATIM rather than reimplemented
        (methodology section 3, rule 4). It fails closed: a payload missing
        `contributes_to_index` yields None, and None on either endpoint
        excludes the print from the step rather than being read as "did not
        contribute".
        """
        source_values = None
        if isinstance(provenance, dict):
            source_values = provenance.get("source_values")
        contributors = eligible_contributor_set(source_values)
        return cls(
            card_print_id=card_print_id,
            index_value_jpy=index_value_jpy,
            index_version=index_version,
            source_semantics_version=source_semantics_version,
            contributors=None if contributors is None else frozenset(contributors),
        )


@dataclass(frozen=True)
class SnapshotDay:
    """Every eligible observation for one scope on one snapshot day.

    `observations` holds only prints with a non-NULL index_value_jpy: a NULL
    value is `coverage_status='none'`, which is an absence, and absences are
    never carried forward.
    """

    point_date: date
    observations: tuple[ConstituentObservation, ...]

    @property
    def eligible_print_count(self) -> int:
        return len(self.observations)

    @property
    def version_pairs(self) -> frozenset[tuple[int, int]]:
        return frozenset(
            (o.index_version, o.source_semantics_version) for o in self.observations
        )

    @property
    def is_mixed_version(self) -> bool:
        """A day whose rows do not share one version pair. Unpublishable
        (section 5.4) - refusing costs one point, while adjudicating a
        majority would put a fudge factor into the methodology."""
        return len(self.version_pairs) > 1

    def by_print(self) -> dict[int, ConstituentObservation]:
        return {o.card_print_id: o for o in self.observations}


# --- step result ------------------------------------------------------------


@dataclass(frozen=True)
class StepResult:
    """The outcome of comparing one snapshot day against its prior."""

    step_log_return: Decimal | None
    constituent_count: int
    movers_up: int
    movers_down: int
    movers_flat: int
    capped_count: int
    # Prints excluded and why - never published, but invaluable when a panel
    # moves and nobody can say which guard fired.
    excluded_version_mismatch: int = 0
    excluded_contributor_churn: int = 0

    @property
    def is_publishable(self) -> bool:
        """Whether a point built from this step may carry a level.

        THE ESTIMATOR AND THE PUBLISH GATE ARE SEPARATE, on purpose. The
        frozen pseudocode writes `if n < MIN_CONSTITUENTS: point is
        unpublishable` as an early exit inside the algorithm block, but the
        gate is a statement about publishability, not about arithmetic: the
        mean of 5 returns is perfectly well defined, it just must not become a
        headline. Splitting them changes no published output - build_points
        consults this property and nothing else does - and it keeps
        MIN_CONSTITUENTS enforced in exactly one place while leaving
        `step_log_return` available to the section 18 worked example, which is
        a five-card illustration of the estimator.
        """
        return (
            self.step_log_return is not None
            and self.constituent_count >= MIN_CONSTITUENTS
        )


# Why a print was NOT a constituent for a step. These are the ONLY three
# reasons, and they are the section 3 rules in the order compute_step applies
# them.
EXCLUDED_ENTRANT = "entrant"
EXCLUDED_VERSION_MISMATCH = "version_mismatch"
EXCLUDED_CONTRIBUTOR_CHURN = "contributor_churn"


def constituent_exclusion(
    before: ConstituentObservation | None,
    observation: ConstituentObservation,
) -> str | None:
    """Why this print contributes no return this step, or None if it does.

    THE SINGLE DEFINITION OF CONSTITUENCY. Extracted from `compute_step`'s
    loop so that anything else needing the constituent SET - the composition
    read path, for one - asks this function rather than restating section 3's
    rules in its own words. A second predicate that agreed today would be free
    to disagree after the next methodology change, and the disagreement would
    surface as a rarity chart that quietly contradicted the constituent count
    printed beside it.

    Pure, and deliberately says nothing about arithmetic: it decides
    membership only. `compute_step` still owns the returns, the cap and the
    mean, and its behaviour is unchanged by this extraction - the three
    branches below are the three `continue`s it used to spell out inline.
    """
    if before is None:
        # An entrant: no value on the prior day, so no return exists.
        return EXCLUDED_ENTRANT

    # Section 3 rule 3 - pairwise per print, never against a segment
    # constant. A (3,2) value and a (1,1) value are different measurements
    # and no arithmetic relating them is publishable.
    if (observation.index_version, observation.source_semantics_version) != (
        before.index_version,
        before.source_semantics_version,
    ):
        return EXCLUDED_VERSION_MISMATCH

    # Section 3 rule 4 - contributor-set-identical. A print that lost a
    # Yuyu-Tei retail price and gained a SNKRDUNK listing floor keeps
    # source_count = 1 while the number underneath switches instrument;
    # reporting that as movement is a category error. None on either side
    # means "cannot prove comparability", which excludes rather than assumes.
    if (
        observation.contributors is None
        or before.contributors is None
        or observation.contributors != before.contributors
    ):
        return EXCLUDED_CONTRIBUTOR_CHURN

    return None


def constituent_print_ids(
    prior: SnapshotDay, current: SnapshotDay
) -> tuple[int, ...]:
    """The print ids that produced a return for this step, ascending.

    The set behind `StepResult.constituent_count`, exposed for read paths that
    need to describe the constituents rather than count them. Same predicate,
    same order (`sorted` by print id) as `compute_step`, so
    `len(constituent_print_ids(p, c)) == compute_step(p, c).constituent_count`
    holds by construction rather than by coincidence.
    """
    prior_by_print = prior.by_print()
    return tuple(
        o.card_print_id
        for o in sorted(current.observations, key=lambda o: o.card_print_id)
        if constituent_exclusion(prior_by_print.get(o.card_print_id), o) is None
    )


def compute_step(prior: SnapshotDay, current: SnapshotDay) -> StepResult:
    """The frozen estimator, and nothing else (methodology section 2.1).

        r_i        = ln(V_i,D / V_i,P)
        r_i_capped = clamp(r_i, -ln(1.25), +ln(1.25))     UNCONDITIONAL
        step       = sum(r_i_capped) / n                  plain arithmetic mean

    A print contributes only when it is valued on BOTH days, its version pair
    is identical across them, and its eligible contributor set is identical
    across them (section 3). Entrants and leavers therefore produce no return
    and cannot move the level - that is the whole chain-link property, and it
    is what stops a coverage cohort manufacturing a fake market move.

    Returns a StepResult whose `step_log_return` is None only when NO print
    qualified - "there was no mean to take", which is distinct from "the mean
    was zero". The MIN_CONSTITUENTS publish gate lives on
    `StepResult.is_publishable`, not here; see that property for why.
    """
    cap = _cap()
    prior_by_print = prior.by_print()

    returns: list[Decimal] = []
    movers_up = movers_down = movers_flat = 0
    capped_count = 0
    excluded_version = 0
    excluded_churn = 0

    with localcontext() as ctx:
        ctx.prec = _WORKING_PRECISION

        # Sorted, so the summation order is fixed by print id rather than by
        # whatever order the database happened to return rows in. Decimal
        # addition is not associative at finite precision, so this is a
        # determinism requirement, not a stylistic one.
        for observation in sorted(current.observations, key=lambda o: o.card_print_id):
            before = prior_by_print.get(observation.card_print_id)
            # Section 3's membership rules, in one place - see
            # `constituent_exclusion`. The three outcomes below are the three
            # inline `continue`s this loop used to carry.
            exclusion = constituent_exclusion(before, observation)
            if exclusion is EXCLUDED_ENTRANT:
                continue
            if exclusion is EXCLUDED_VERSION_MISMATCH:
                excluded_version += 1
                continue
            if exclusion is EXCLUDED_CONTRIBUTOR_CHURN:
                excluded_churn += 1
                continue
            assert before is not None  # exclusion is None => before exists

            current_value = Decimal(observation.index_value_jpy)
            prior_value = Decimal(before.index_value_jpy)
            raw = (current_value / prior_value).ln()

            if raw > cap:
                capped = cap
                capped_count += 1
            elif raw < -cap:
                capped = -cap
                capped_count += 1
            else:
                capped = raw
            returns.append(capped)

            # Classified from the VALUES, not from the capped return. Capping
            # never changes a sign so the two agree, but comparing integers is
            # exact where comparing a rounded log is merely almost always
            # right.
            if observation.index_value_jpy > before.index_value_jpy:
                movers_up += 1
            elif observation.index_value_jpy < before.index_value_jpy:
                movers_down += 1
            else:
                movers_flat += 1

        n = len(returns)
        if n == 0:
            # No constituent produced a return, so there is no mean to take.
            # Distinct from "the mean was zero", which is a real measurement.
            step_log_return = None
        else:
            # Plain arithmetic mean. Every constituent gets exactly 1/n of the
            # day's move regardless of its price - the JPY 66,000 SP and the
            # JPY 30 common weigh the same, which is what a return-based index
            # buys and what a median was mistakenly reached for.
            total = sum(returns, Decimal(0))
            step_log_return = (total / Decimal(n)).quantize(
                STEP_PLACES, rounding=ROUND_HALF_EVEN
            )

    return StepResult(
        step_log_return=step_log_return,
        constituent_count=n,
        movers_up=movers_up,
        movers_down=movers_down,
        movers_flat=movers_flat,
        capped_count=capped_count,
        excluded_version_mismatch=excluded_version,
        excluded_contributor_churn=excluded_churn,
    )


def chain(prior_level: Decimal, step_log_return: Decimal) -> Decimal:
    """`level_D = level_P * exp(step_log_return)`, quantized to the column.

    `prior_level` is the PUBLISHED prior level - the already-quantized value
    that is stored and charted - not an unrounded running total. That is the
    literal reading of the frozen formula, and it is what makes a carried
    base's level exactly equal to its source point's, which the composite
    foreign key demands.
    """
    with localcontext() as ctx:
        ctx.prec = _WORKING_PRECISION
        level = prior_level * step_log_return.exp()
        return level.quantize(LEVEL_PLACES, rounding=ROUND_HALF_EVEN)


# --- point drafts -----------------------------------------------------------


@dataclass(frozen=True)
class PointDraft:
    """One computed row, before it has an id.

    Deliberately id-free. A draft is compared to a persisted row by NATURAL
    KEY (scope_kind, scope_key, methodology_version, point_date) and by value;
    surrogate ids are not reproducible across a rebuild and never take part in
    a comparison. `carried_from_key` is the carry target's point_date - part
    of its natural key - and `carried_from_point_id` deliberately is not here.
    """

    scope_kind: str
    scope_key: str
    methodology_version: int
    index_version: int
    source_semantics_version: int
    point_date: date
    index_value: Decimal | None
    is_base: bool
    carried_from_key: date | None
    prior_point_date: date | None
    step_days: int | None
    chain_link_log_return: Decimal | None
    constituent_count: int
    eligible_print_count: int
    movers_up: int | None
    movers_down: int | None
    movers_flat: int | None
    capped_count: int | None
    unpublishable_reason: str | None

    @property
    def natural_key(self) -> tuple[str, str, int, date]:
        return (
            self.scope_kind,
            self.scope_key,
            self.methodology_version,
            self.point_date,
        )

    @property
    def is_published(self) -> bool:
        return self.index_value is not None


@dataclass(frozen=True)
class Break:
    """A boundary a client must render. Version breaks keep the line solid
    with a marker; a snapshot_gap dashes the join (section 13.4)."""

    at: date
    reason: str
    from_index_version: int | None = None
    to_index_version: int | None = None
    from_source_semantics_version: int | None = None
    to_source_semantics_version: int | None = None
    carried: bool | None = None
    carried_level: Decimal | None = None
    carried_from_point_date: date | None = None
    step_days: int | None = None


@dataclass(frozen=True)
class ScopeSeries:
    points: tuple[PointDraft, ...]
    breaks: tuple[Break, ...] = field(default=())


def _version_pair(day: SnapshotDay) -> tuple[int, int]:
    """The single version pair of a non-mixed day."""
    return next(iter(day.version_pairs))


def _base_draft(
    *,
    scope_kind: str,
    scope_key: str,
    day: SnapshotDay,
    level: Decimal,
    carried_from: date | None,
) -> PointDraft:
    """A segment's opening row. Section 5.1 rule 5: no prior point, no
    step_days, no return, zero constituents, and therefore NULL breadth."""
    index_version, source_semantics_version = _version_pair(day)
    return PointDraft(
        scope_kind=scope_kind,
        scope_key=scope_key,
        methodology_version=METHODOLOGY_VERSION,
        index_version=index_version,
        source_semantics_version=source_semantics_version,
        point_date=day.point_date,
        index_value=level,
        is_base=True,
        carried_from_key=carried_from,
        prior_point_date=None,
        step_days=None,
        chain_link_log_return=None,
        constituent_count=0,
        eligible_print_count=day.eligible_print_count,
        movers_up=None,
        movers_down=None,
        movers_flat=None,
        capped_count=None,
        unpublishable_reason=None,
    )


def _unpublishable_draft(
    *,
    scope_kind: str,
    scope_key: str,
    day: SnapshotDay,
    index_version: int,
    source_semantics_version: int,
    reason: str,
    prior_point_date: date | None,
    step_days: int | None,
    step: StepResult | None,
) -> PointDraft:
    """A day that was computed and could not be published.

    Breadth is reported when a constituent set existed (an
    insufficient_constituents day still knows its n - that is a real
    measurement) and NULL when none did, exactly matching
    ck_cpi_points_breadth_presence.
    """
    has_breadth = step is not None and step.constituent_count > 0
    return PointDraft(
        scope_kind=scope_kind,
        scope_key=scope_key,
        methodology_version=METHODOLOGY_VERSION,
        index_version=index_version,
        source_semantics_version=source_semantics_version,
        point_date=day.point_date,
        index_value=None,
        is_base=False,
        carried_from_key=None,
        prior_point_date=prior_point_date,
        step_days=step_days,
        chain_link_log_return=None,
        constituent_count=step.constituent_count if has_breadth else 0,
        eligible_print_count=day.eligible_print_count,
        movers_up=step.movers_up if has_breadth else None,
        movers_down=step.movers_down if has_breadth else None,
        movers_flat=step.movers_flat if has_breadth else None,
        capped_count=step.capped_count if has_breadth else None,
        unpublishable_reason=reason,
    )


def build_points(
    days: list[SnapshotDay],
    *,
    scope_kind: str = SCOPE_OVERALL,
    scope_key: str = "",
) -> ScopeSeries:
    """The whole chain for one scope, from ordered snapshot days.

    Pure: no database, no clock. `days` is re-sorted defensively, because
    relying on the caller's ordering would make the result depend on query
    order - which determinism forbids.

    The walk, per day:

      * A MIXED-VERSION day is unpublishable and does not become a chain
        anchor. The following day therefore steps from the last non-mixed day,
        which is the honest reading of "prior available snapshot day".
      * The FIRST publishable day of the scope opens an initial segment at
        BASE_VALUE with no carry.
      * A day whose version pair differs from the anchor's opens a NEW SEGMENT.
        Its base level is the last published level (a carry), or BASE_VALUE if
        the scope has never published (an initial base). No return is
        calculated across the boundary, under either version.
      * Otherwise the day is an ordinary step: compute, and publish if at
        least MIN_CONSTITUENTS constituents qualified.
    """
    ordered = sorted(days, key=lambda d: d.point_date)

    points: list[PointDraft] = []
    breaks: list[Break] = []

    # The last day that can act as the prior endpoint of a step: published or
    # not, it must be a real, single-version day whose values are comparable.
    anchor_day: SnapshotDay | None = None
    anchor_versions: tuple[int, int] | None = None
    # The last PUBLISHED point - the level a boundary carries, and the level
    # an ordinary step chains from.
    last_published: PointDraft | None = None

    for day in ordered:
        if not day.observations:
            # A day with nothing valued is not a day of this series at all.
            # No row, no forward-fill, no zero.
            continue

        if day.is_mixed_version:
            # Section 5.4. Deliberately does NOT become the anchor: a mixed
            # day has no single version pair to compare the next day against.
            points.append(
                _unpublishable_draft(
                    scope_kind=scope_kind,
                    scope_key=scope_key,
                    day=day,
                    index_version=min(v[0] for v in day.version_pairs),
                    source_semantics_version=min(v[1] for v in day.version_pairs),
                    reason=UNPUBLISHABLE_MIXED_VERSION_DAY,
                    prior_point_date=anchor_day.point_date if anchor_day else None,
                    step_days=(
                        (day.point_date - anchor_day.point_date).days
                        if anchor_day
                        else None
                    ),
                    step=None,
                )
            )
            continue

        versions = _version_pair(day)

        # --- first day of the scope: an initial base at 1000 ---
        if anchor_day is None:
            draft = _base_draft(
                scope_kind=scope_kind,
                scope_key=scope_key,
                day=day,
                level=BASE_VALUE,
                carried_from=None,
            )
            points.append(draft)
            last_published = draft
            anchor_day, anchor_versions = day, versions
            continue

        # --- a version boundary: close the segment, open a new one ---
        if versions != anchor_versions:
            carried_from = last_published.point_date if last_published else None
            level = last_published.index_value if last_published else BASE_VALUE
            draft = _base_draft(
                scope_kind=scope_kind,
                scope_key=scope_key,
                day=day,
                level=level,
                carried_from=carried_from,
            )
            points.append(draft)

            # Two versions moving at one boundary emit TWO entries at the same
            # date, matching how print_series already appends them separately.
            # A combined reason would be a new vocabulary for no gain.
            reasons = []
            if versions[0] != anchor_versions[0]:
                reasons.append(BREAK_INDEX_VERSION_CHANGE)
            if versions[1] != anchor_versions[1]:
                reasons.append(BREAK_SOURCE_SEMANTICS_VERSION_CHANGE)
            for reason in reasons:
                breaks.append(
                    Break(
                        at=day.point_date,
                        reason=reason,
                        from_index_version=anchor_versions[0],
                        to_index_version=versions[0],
                        from_source_semantics_version=anchor_versions[1],
                        to_source_semantics_version=versions[1],
                        carried=carried_from is not None,
                        carried_level=level if carried_from is not None else None,
                        carried_from_point_date=carried_from,
                    )
                )

            last_published = draft
            anchor_day, anchor_versions = day, versions
            continue

        # --- an ordinary step ---
        step = compute_step(anchor_day, day)
        step_days = (day.point_date - anchor_day.point_date).days

        if step_days > 1:
            # Section 7: a real multi-day return, honestly labelled. Not
            # forward-fill; no value is invented.
            breaks.append(
                Break(
                    at=day.point_date,
                    reason=BREAK_SNAPSHOT_GAP,
                    step_days=step_days,
                )
            )

        if not step.is_publishable or last_published is None:
            points.append(
                _unpublishable_draft(
                    scope_kind=scope_kind,
                    scope_key=scope_key,
                    day=day,
                    index_version=versions[0],
                    source_semantics_version=versions[1],
                    reason=UNPUBLISHABLE_INSUFFICIENT_CONSTITUENTS,
                    prior_point_date=anchor_day.point_date,
                    step_days=step_days,
                    step=step,
                )
            )
            # An unpublishable step is still a real, single-version day, so it
            # DOES become the anchor: the next day compares against the values
            # actually observed here, not against a stale earlier day.
            anchor_day = day
            continue

        level = chain(last_published.index_value, step.step_log_return)
        draft = PointDraft(
            scope_kind=scope_kind,
            scope_key=scope_key,
            methodology_version=METHODOLOGY_VERSION,
            index_version=versions[0],
            source_semantics_version=versions[1],
            point_date=day.point_date,
            index_value=level,
            is_base=False,
            carried_from_key=None,
            prior_point_date=anchor_day.point_date,
            step_days=step_days,
            chain_link_log_return=step.step_log_return,
            constituent_count=step.constituent_count,
            eligible_print_count=day.eligible_print_count,
            movers_up=step.movers_up,
            movers_down=step.movers_down,
            movers_flat=step.movers_flat,
            capped_count=step.capped_count,
            unpublishable_reason=None,
        )
        points.append(draft)
        last_published = draft
        anchor_day = day

    return ScopeSeries(points=tuple(points), breaks=tuple(breaks))


# --- change across a break (section 5.6) ------------------------------------


@dataclass(frozen=True)
class ChangeResult:
    absolute: Decimal | None
    pct: Decimal | None
    from_date: date | None
    to_date: date | None
    spans_break: bool
    unavailable_reason: str | None


def compute_change(
    points: list[PointDraft],
    *,
    window_start: date | None = None,
) -> ChangeResult:
    """Percentage and absolute change over a window, per section 5.6.

    Change MAY be computed across one or more CARRIED segments, using the
    published chain-linked levels: that is a linked-index return, and it is
    what every chain-linked public index reports. It is NOT a claim that the
    underlying per-print measurements were directly comparable across the
    boundary, which is exactly what `spans_break` declares.

    It may NOT be computed across a RESET - an initial base that is not the
    chain's first point. There is no carried continuity there, so the answer
    is None rather than a spliced number. Do not fall back to a shorter window
    to manufacture one.
    """
    ordered = sorted(points, key=lambda p: p.point_date)
    published = [p for p in ordered if p.is_published]
    if window_start is not None:
        published = [p for p in published if p.point_date >= window_start]

    if not published:
        return ChangeResult(
            absolute=None, pct=None, from_date=None, to_date=None,
            spans_break=False, unavailable_reason=CHANGE_UNAVAILABLE_NO_POINT,
        )

    start, end = published[0], published[-1]

    # Walk every base row strictly inside the span. A carried base keeps the
    # scale; an initial base that is not the chain's own first point is a
    # reset and breaks it.
    spans_break = False
    for point in ordered:
        if not (start.point_date < point.point_date <= end.point_date):
            continue
        if not point.is_base:
            continue
        if point.carried_from_key is None:
            return ChangeResult(
                absolute=None, pct=None,
                from_date=start.point_date, to_date=end.point_date,
                spans_break=True,
                unavailable_reason=CHANGE_UNAVAILABLE_NO_CONTINUITY,
            )
        spans_break = True

    with localcontext() as ctx:
        ctx.prec = _WORKING_PRECISION
        absolute = (end.index_value - start.index_value).quantize(
            LEVEL_PLACES, rounding=ROUND_HALF_EVEN
        )
        pct = (
            (end.index_value / start.index_value - Decimal(1)) * Decimal(100)
        ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)

    return ChangeResult(
        absolute=absolute,
        pct=pct,
        from_date=start.point_date,
        to_date=end.point_date,
        spans_break=spans_break,
        unavailable_reason=None,
    )


__all__ = [
    "BASE_VALUE",
    "BREAK_METHODOLOGY_VERSION_CHANGE",
    "BREAK_SNAPSHOT_GAP",
    "Break",
    "CAP_RATIO",
    "CHANGE_UNAVAILABLE_NO_CONTINUITY",
    "CHANGE_UNAVAILABLE_NO_POINT",
    "ChangeResult",
    "ConstituentObservation",
    "LEVEL_PLACES",
    "METHODOLOGY_VERSION",
    "EXCLUDED_CONTRIBUTOR_CHURN",
    "EXCLUDED_ENTRANT",
    "EXCLUDED_VERSION_MISMATCH",
    "MIN_CONSTITUENTS",
    "PointDraft",
    "SCOPE_KINDS",
    "SCOPE_OVERALL",
    "SCOPE_RARITY",
    "SCOPE_SET",
    "STEP_PLACES",
    "ScopeSeries",
    "SeedSpec",
    "SnapshotDay",
    "StepResult",
    "UNPUBLISHABLE_INSUFFICIENT_CONSTITUENTS",
    "UNPUBLISHABLE_MIXED_VERSION_DAY",
    "V1_OVERALL_SEED",
    "build_points",
    "chain",
    "compute_change",
    "compute_step",
    "constituent_exclusion",
    "constituent_print_ids",
]
