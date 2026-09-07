# Card Pirate Index — methodology of record

**Status: FROZEN v1 contract. Not yet implemented.**
Supersedes the recommendations in
`docs/card_pirate_index_foundation_audit_2026-09-07.pdf` wherever the two
disagree; the audit remains the evidence record, this document is the
specification.

Frozen 2026-09-07 against `staging @ f736e92`, alembic `b8e3f1a70d95`.
Schema constraints proved against PostgreSQL 18.6 (§8.5); staging runs PG18.4.

The Card Pirate Index is a single number describing how the One Piece
single-card market Atlas can price has moved over time. It is **not** the
per-print Market Index (`app/services/market_index.py`), and nothing in this
document changes that calculation, its versions, or its semantics. The Card
Pirate Index is a strictly downstream aggregate of values the Market Index has
already computed and already archived.

---

## 1. Frozen constants

| Constant | Value | Owner |
| --- | --- | --- |
| `METHODOLOGY_VERSION` | `1` | this index (new constant, `app/services/card_pirate_index.py`) |
| `BASE_VALUE` | `1000` | this index |
| `MIN_CONSTITUENTS` | `30` | this index |
| `DAILY_RETURN_CAP` | `ln(1.25)` = `0.223143551314` | this index |
| `INDEX_VERSION` | `3` | `app/services/market_index.py` — **not** ours |
| `SOURCE_SEMANTICS_VERSION` | `2` | `app/services/source_semantics.py` — **not** ours |

Changing any of the first four is a `METHODOLOGY_VERSION` bump and opens a new
segment (§6). The last two are read, recorded, and obeyed; they are never set
by this index.

---

## 2. The estimator

### 2.1 The algorithm, in full

For a step from prior available snapshot day `P` to day `D`, over the
constituent set defined in §3:

```
r_i        = ln(V_i,D / V_i,P)                 # natural log return, per print
cap        = ln(1.25)                          # 0.223143551314
r_i_capped = clamp(r_i, -cap, +cap)            # UNCONDITIONAL, at every n

n                = len(constituents)
if n < 30:  the point is unpublishable         # §5
step_log_return  = sum(r_i_capped) / n         # plain arithmetic mean
level_D          = level_P * exp(step_log_return)
```

This is an **equal-weighted geometric-return index**. Every constituent gets
exactly `1/n` of the day's move regardless of its price.

There is **no percentile winsorization, no trimming, and no value weighting**.
Those words must not appear in the implementation, in a column name, or in the
API payload.

### 2.2 Why the cap is applied at every `n`

The audit proposed `winsorize(returns, 0.01, 0.99) if n >= 100 else clip(±cap)`.
That is rejected.

With returns this sparse, the empirical p99 **is itself zero**, so percentile
winsorization clips the only mover to zero and reproduces exactly the
degeneracy that disqualified the median. This is not a hypothetical — it is
measured on the real staging archive (§17.3): under p1/p99 winsorization the
index reads `1000.0000` on all four days, identical to the median.

A fixed cap is a statement about what a plausible one-day move for a single
print is. That statement does not become more or less true at `n = 99` versus
`n = 100`, so it must not be conditioned on `n`. A conditional rule would also
mean the estimator silently changes character as coverage grows — the series
would acquire a methodology discontinuity that nothing in the record marks.

### 2.3 Why the median is rejected

A median of daily returns is non-zero only when more than half the
constituents move in the same direction on the same day. In this market that
does not happen: Yuyu-Tei sell prices change on 0.34 % of consecutive
day-pairs, SNKRDUNK floors on 3.38 %. On all three real v3 steps the median
daily log return is exactly `0.0000 %`. A median publishes a permanently flat
line and calls it a measurement.

The requirement the median was chosen to satisfy — that a ¥66,000 SP must not
dominate a ¥30 common — is **not** what a median solves. It is solved
structurally by using *returns instead of levels*: a return is scale-free, so
both cards carry identical weight under a plain mean. The median only adds
outlier resistance, and buys it by discarding all signal. The cap in §2.1 buys
the same outlier resistance without discarding the mover.

### 2.4 Cap semantics — log-symmetric, not percent-symmetric

`clamp(r, -ln(1.25), +ln(1.25))` bounds the per-print daily *price ratio* to
`[0.8, 1.25]`: at most **+25 % up**, at most **−20 % down**. That asymmetry in
percentage terms is deliberate and correct. A halving and a doubling are moves
of equal magnitude, and only a log-symmetric bound treats them that way; a
percent-symmetric ±25 % bound would permit a −25 % move (ratio 0.75) while
refusing its exact inverse (+33 %), putting a directional bias into the
estimator.

Capping never changes the sign of a return, so the breadth counters in §8 are
unambiguous: `movers_up`/`movers_down` can be classified from either the raw
or the capped return and agree.

### 2.5 When the cap is expected to bind

Essentially never, within a segment. On the real v3 archive the cap binds on
**zero** constituents across all three steps. The largest genuine same-version
daily move is `+21.43 %` (`r = 0.194156`), which sits at 87 % of the cap — thin
headroom, and worth watching: see §17.4.

Every archived move that *would* have breached the cap sits exactly on a
version boundary (up to `+991 %` at the v2→v3 change) and is already excluded
by §3 rule 3 before the cap is ever consulted. The cap is therefore a
second lock on a door the version guard already holds: it exists for data
errors, not for market moves.

---

## 3. Constituent eligibility

A `card_print` contributes a return to the step ending on day `D` when **all**
of the following hold:

1. It has a `market_index_snapshots` row on `D` with `index_value_jpy IS NOT
   NULL`. (The existing `ck_market_index_snapshots_value_presence` constraint
   makes this identical to `coverage_status <> 'none'`.)
2. It has such a row on the prior *available snapshot day* `P` — not the prior
   calendar day (§7).
3. `(index_version, source_semantics_version)` on `D` equals the pair on `P`,
   compared **pairwise per print**, never against a segment constant.
4. Its eligible contributor set is identical on `D` and `P`, compared by
   `(source, reference_type)` pairs read from `provenance.source_values` where
   `contributes_to_index is True`.

Rule 4 is `app/services/market_index_change.py::eligible_contributor_set`,
**reused verbatim, not reimplemented**. A print that lost its Yuyu-Tei retail
price and gained a SNKRDUNK listing floor keeps `source_count = 1` while the
number underneath switches instrument; reporting that as market movement is a
category error. The function fails closed — it returns `None`, not an empty
set, when the archived payload cannot prove the role — and `None` on either
side means the print is excluded from that step.

**Deliberately not in the rules:** no source name, no rarity, no price floor,
no set, no minimum value, no notion of card importance. The methodology
consults `index_value_jpy` and the version pair and nothing else. That is what
makes §14 a `GROUP BY` rather than a rewrite, and it is what lets a new source
be added without touching this index.

### 3.1 Entrants and leavers

Both are structurally free, because a return needs values at *both* endpoints.

- An **entrant** has no value on `P`, produces no return, and cannot move
  `level_D`. It begins contributing on its second valued day.
- A **leaver** has no value on `D`, produces no return, and cannot move
  `level_D`.

Panel size changes `constituent_count` and `eligible_print_count`. It never
changes `index_value`. On staging, entrant cohorts of 50 prints (09-04) and 15
prints (09-05) moved the index by exactly zero; under any level-based or
sum-based index the 09-04 cohort alone would have manufactured an enormous
fake move.

---

## 4. Minimum constituents

`MIN_CONSTITUENTS = 30`. Below it, the day is written with `index_value =
NULL` and `unpublishable_reason = "insufficient_constituents"`.

### 4.1 Rationale — a concentration guard, not a breadth expectation

**Thirty is a bound on how much of the published number one card can be.** It
is *not* a claim that more than one constituent is expected to move on a given
day, and the methodology must never be defended on that ground. With measured
mover rates of 0.34–3.4 %, the expected mover count at `n = 30` is between
0.1 and 1.0 — so a "more than one card will move" justification would be false
at the low end and marginal at the high end. The real question is not how many
cards move; it is how much of the headline a *single* card can be responsible
for.

Under an equal-weighted mean each constituent owns `1/n` of the step, so one
constituent moving all the way to the cap moves the index by
`exp(cap/n) - 1`:

| `n` | one capped constituent, log | one capped constituent, index effect | capped constituents needed to move the index +1.00 % |
| ---: | ---: | ---: | ---: |
| 10 | 0.022314355131 | **+2.256518 %** | 0.45 |
| 20 | 0.011157177566 | **+1.121965 %** | 0.89 |
| 30 | 0.007438118377 | **+0.746585 %** | 1.34 |
| 50 | 0.004462871026 | **+0.447284 %** | 2.23 |
| 100 | 0.002231435513 | **+0.223393 %** | 4.46 |
| 231 *(real, 09-04)* | 0.000965989400 | +0.096646 % | 10.30 |
| 296 *(real, 09-06)* | 0.000753863349 | +0.075415 % | 13.20 |

At `n = 10` a single card can move the headline by more than 2 %, and *less
than one* capped card is needed to produce a "+1 % market day" — one card is
the market. At `n = 30` the worst-case single-card contribution is under
0.75 %, and it takes more than one capped constituent to reach +1 %. Thirty is
the smallest round panel at which the sentence "the One Piece market moved 1 %
today" cannot be true because of one card alone.

That is the whole claim, and it holds regardless of how often cards move.

### 4.2 No breadth gate

Do **not** additionally gate on a minimum number of movers. A genuinely quiet
market day is real information and suppressing it would be its own dishonesty.
Report `movers_up` / `movers_down` / `movers_flat` on every point and let the
surface say "flat" out loud (§13).

---

## 5. Version boundaries and the continuous level

Three versions can invalidate a step. Each has a different owner:

| Version | Owner | Current |
| --- | --- | --- |
| `methodology_version` | this index | 1 |
| `index_version` | `market_index.INDEX_VERSION` | 3 |
| `source_semantics_version` | `source_semantics.SOURCE_SEMANTICS_VERSION` | 2 |

### 5.1 The policy

**The visible Card Pirate Index level does NOT reset to 1000 at a version
change.**

1. The initial series begins at `BASE_VALUE = 1000`.
2. **Never calculate a constituent return across an incompatible
   `methodology_version` / `index_version` / `source_semantics_version`
   boundary.** A `(3,2)` value and a `(1,1)` value are different measurements
   and no arithmetic relating them is publishable.
3. At a boundary, **close the old segment**.
4. **Open a new segment whose base level equals the previous segment's final
   published index level.** "Final published" means the most recent point of
   the same scope, under any prior segment, whose `index_value` is not NULL.
   The new base row records that point by id in `carried_from_point_id` (§8.3)
   and its `index_value` must equal that point's `index_value` exactly. If no
   such point exists, the new segment is an *initial* segment at 1000 with
   `carried_from_point_id = NULL`.
5. **The boundary itself has no calculated return.** The new segment's base
   row has `prior_point_date = NULL`, `step_days = NULL`,
   `chain_link_log_return = NULL`, `constituent_count = 0`. The boundary
   contributes exactly zero to every cumulative change.
6. **Persist and expose the boundary explicitly** (§8, §12).
7. **Never imply that the underlying per-print values were comparable across
   it.** The level is continuous; the *measurement* is not. Continuity is
   carried at the aggregate level only.
8. Percentage and absolute change **may** be calculated across one or more
   carried segments, using the published chain-linked levels. Whenever it is,
   `spans_break: true`. Where there is no valid carried continuity, change is
   `null` rather than invented. See §5.6.

### 5.2 What the continuity is, and what it is not

**The Card Pirate Index is a chain-linked public series.** The continuity at a
boundary is a **level carry**: the new segment starts from the number the old
segment finished on, in the same way every chain-linked public index carries
its level through a constituent- or methodology-rule change.

It is **not** continuity invented through underlying card prices. No
constituent return is computed across the boundary under either version. No
per-print value from one side is compared to a per-print value from the other.
Whatever the market did across the boundary day itself is unmeasured, and the
index records no step there because it has nothing to say — not because
nothing happened.

A change computed over a span that crosses a boundary is therefore a
**linked-index return**: a legitimate statement about the published series,
and *not* a claim that the underlying per-print measurements were directly
comparable across the boundary. That is exactly what `spans_break: true`
declares, and it is why the flag is mandatory rather than advisory.

### 5.3 What this policy buys, and what it costs

Buys: windows longer than the current segment stay renderable. Under the
reset-to-1000 policy in the audit, `INDEX_VERSION` moving twice and
`SOURCE_SEMANTICS_VERSION` once inside 17 days would have truncated every
window to the newest segment and reset the y-axis three times. Under the carry
policy a 1Y window spanning four segments is a continuous line with three
marked discontinuities. Audit risk R4 is closed by this decision.

Costs: the level is no longer a pure function of one methodology. It is a
chain of segments. That is why §8.3 records each carry as an explicit,
foreign-keyed reference rather than leaving it to be re-derived, and why every
span that crosses a break is flagged.

### 5.4 Mixed-version days

A day's rows normally share one version pair —
`_snapshot_market_index_locked` uses one
`print_market_index.get_market_index_for_prints` call per run — but a retry
after a deploy can add rows under a new version while `ON CONFLICT DO NOTHING`
preserves the old ones, so a day *can* be mixed.

A mixed-version day is **unpublishable**, `unpublishable_reason =
"mixed_version_day"`. Refusing costs one point; adjudicating a majority would
put a fudge factor into the methodology. It has never occurred in 17 days.

Note this is a property of the *day*, distinct from rule 3 in §3, which
excludes an individual print whose own pair changed.

### 5.5 Break vocabulary

Reuse `app/services/print_series.py`'s spellings so one client primitive
renders both a print's history and this index:

- `index_version_change` (`print_series.BREAK_INDEX_VERSION_CHANGE`)
- `source_semantics_version_change`
  (`print_series.BREAK_SOURCE_SEMANTICS_VERSION_CHANGE`)
- `methodology_version_change` — new, owned by this index
- `snapshot_gap` — new, emitted when `step_days > 1` (§7)

When two versions change at the same boundary — as at v2→v3, where both
`index_version` and `source_semantics_version` moved — emit **two break
entries at the same date**, matching how `print_series` already appends them
separately. Do not invent a combined reason.

### 5.6 Change across a break — FROZEN

Percentage and absolute change **may** be calculated across one or more
carried segments, using the published chain-linked index levels. The
resolution rule, in order:

1. **Resolve the endpoints.** `to_point` is the latest published point at or
   before the window's end. `from_point` is the earliest published point at or
   after `window_start` (for `all`, the earliest published point of the
   scope). "Published" means `index_value IS NOT NULL`; an unpublishable day
   is never an endpoint, and the payload reports the `from_date` / `to_date`
   actually used rather than the requested ones.
2. **If either endpoint does not exist**, `change` is `null` with
   `change_unavailable_reason: "no_published_point_in_window"`. Never
   substitute the base value, and never fabricate an endpoint.
3. **Walk the segment chain** from `from_point` to `to_point`. Every boundary
   crossed must be a *carried* boundary — the segment's base row has
   `carried_from_point_id IS NOT NULL`, which the schema already proves means
   its level equals its source point's level exactly (§8.5, proof 6).
4. **If every crossed boundary is carried**, the two levels sit on one linked
   scale. Compute `absolute = to − from` and `pct = (to / from − 1) × 100`,
   and set `spans_break: true` if at least one boundary was crossed.
5. **If any crossed boundary is a reset** — an *initial* base
   (`carried_from_point_id IS NULL`) that is not the chain's first point —
   there is no valid carried continuity. `change` is `null` with
   `change_unavailable_reason: "no_carried_continuity"`. **Do not splice
   across a reset, and do not fall back to a shorter window to manufacture a
   number.** The chart still renders both stretches; only the change figure is
   withheld.

Rule 5 should never fire under this methodology, because §5.1 requires a carry
wherever a prior published point exists. It is written down because "should
never fire" is not "cannot fire", and the honest behaviour when it does must be
decided now rather than improvised at the call site.

`spans_break` is a property of the **span**, not of the window name. A 1M
window that happens to contain no boundary carries `spans_break: false` even
while the 1Y window over the same series carries `true`.


---

## 6. History — what is published

- **Clean Card Pirate Index start: `2026-09-03`.** This is the first day of
  the `(methodology 1, index 3, semantics 2)` era, and the first day with a
  defensible constituent count (231 valued prints).
- The initial segment's base row is `is_base = true`,
  `carried_from_point_id = NULL`, `index_value = 1000.0000`.
- **The v1 archive (2026-08-21 → 2026-09-01) is not published in this headline
  index.** It carries 20 constituents — below `MIN_CONSTITUENTS` on every day
  — and three rebased stubs make a worse headline than one honest line. It is
  retained, queryable, and simply not charted here.
- The single v2 day (2026-09-02) has no prior same-version day and therefore
  no return. It is likewise not published.
- **Old Market Index snapshots are retained unchanged.** Nothing in this
  document deletes, rewrites, prunes, or reinterprets a
  `market_index_snapshots` row.

Because nothing before `2026-09-03` is published, there is **no break at
`2026-09-03`**. The series opens there; it does not resume there. (The audit's
§9 example payload showed a `methodology_boundary` break at that date; that is
superseded.)

---

## 7. Gaps and cadence

- Chain between **consecutive available snapshot days**, never consecutive
  calendar days.
- Record `prior_point_date` and `step_days` on every non-base point.
- A missed cron run produces a real multi-day return, honestly labelled with
  `step_days > 1`. That is not forward-fill; no value is invented.
- Emit a `snapshot_gap` break whenever `step_days > 1` so a client can render a
  dashed join.
- **No forward-fill anywhere.** A print with no snapshot on `D` is absent from
  that step's set — never carried forward, never zeroed, never interpolated.
  Same rule `print_series` already enforces for its points.
- **No trading calendar.** Yuyu-Tei is a shop and SNKRDUNK a marketplace; both
  quote every calendar day and both collectors run every day (Yuyu-Tei
  18:20 UTC, SNKRDUNK 03:20/11:20/19:20 UTC, snapshot 20:00 UTC). Every UTC day
  is a step.

Today: zero non-contiguous prints under v3, zero leavers, zero multi-day steps.

---

## 8. Persistence, schema and the replay contract

### 8.1 Persist, do not derive at read time

Two independent arguments, either sufficient.

**(a) Immutability — the primary one.** This repo already made this argument
once, in `models/market_index_snapshot.py`: *"a later change to INDEX_VERSION,
to a SOURCE_SEMANTICS rule, or to a freshness threshold silently rewrites every
value Atlas has ever displayed."* A read-time Card Pirate Index has the same
defect one layer up — a later tweak to the cap or to `MIN_CONSTITUENTS` would
rewrite every level ever charted, including the one in a screenshot a collector
took last month.

**(b) Runtime — the secondary one.** Measured 1.97 ms today over 1,688 rows;
projected 1.5–4 s and ~870 MB of heap reads at one year, 3–10 s at two. Not
acceptable on page load. A persisted read is one indexed row per day.

### 8.2 The replay guarantee — and why it does not contradict the sibling table

`market_index_snapshots` cannot be backfilled, because a past Market Index is
not computable: `_compute_index_fields` applies freshness windows relative to
the `now` it is handed.

**The Card Pirate Index has no such dependency.** Its inputs are the immutable,
already-archived `index_value_jpy` values themselves. It is a pure,
deterministic, idempotent function of rows that can never change. Therefore,
uniquely, the job carries:

- `--dry-run` — compute and print, write nothing.
- `--verify` — replay the whole archive and diff against stored points without
  writing. A mismatch is a bug alarm. The snapshot job structurally cannot
  offer this.
- `--replay-from` — a deterministic seed of `2026-09-03` onward.

This must be stated in both the job docstring and the migration docstring,
explicitly distinguished from `market_index_snapshots`' prohibited backfill —
otherwise a future reader will correctly flag it as violating the sibling
contract.

### 8.3 The segment carry — one reference, nothing derived twice

The carry is represented by **exactly one column**:

```
carried_from_point_id: int | None
```

It identifies the exact prior `CardPirateIndexPoint` whose published
`index_value` was carried into the new segment.

| Row kind | `is_base` | `carried_from_point_id` |
| --- | --- | --- |
| Initial base (series or scope opens) | `true` | `NULL` |
| Carried base (methodology / version boundary) | `true` | *id of the previous published point* |
| Ordinary non-base row | `false` | `NULL` |

The carried base row's `index_value` **must equal the referenced point's
`index_value` exactly**, and the referenced point must belong to the **same
scope**. Both are enforced declaratively by the composite foreign key in
§8.4 — not by application code, and not by a trigger.

**No `segment_base_kind` column.** The initial/carried distinction is a pure
function of this one field and must not be stored a second time:

```
kind = 'carried' if carried_from_point_id is not None else 'initial'   # is_base rows
```

A separate `segment_base_kind` could disagree with `carried_from_point_id`,
and a column that can contradict its own source of truth is the defect §8.3
previously argued against for `segment_base_value`. One reference, one
derivation.

**No `carried_from_point_date` column either.** The date is one join away
(`JOIN … ON id = carried_from_point_id`) and would be a second copy of the
target's `point_date`. The API still *exposes* a date rather than an id
(§12.1) — resolved by that join at read time, for the reason in §8.6.

**And still no `segment_base_value` / `boundary_from_level`.** `index_value` on
the base row **is** the carried level; the FK proves it equals the source's.
A second column holding the same number is a second source of truth that can
disagree with the first — precisely the failure the sibling table's
both-directions `CHECK` style exists to prevent.

Everything else about a segment remains derived, as before:

| Fact | How it is derived |
| --- | --- |
| Which segment a point belongs to | A contiguous run of equal `(methodology_version, index_version, source_semantics_version)` for a scope, ordered by `point_date`. One pass, exactly what `print_series` already does. |
| The break's from/to versions | The version columns of the two adjacent points. |
| Whether a base is initial or carried | `carried_from_point_id IS NULL`. |
| The carry's source date and level | A join through `carried_from_point_id`. |
| That the boundary carries no return | `prior_point_date IS NULL AND step_days IS NULL AND chain_link_log_return IS NULL AND constituent_count = 0`, constrained. |

### 8.4 Final proposed schema

One additive table. Nothing existing is touched.

```python
class CardPirateIndexPoint(Base):
    __tablename__ = "card_pirate_index_points"

    id: int                                    # PK, surrogate — see §8.6

    # --- scope: the extension point for §14. 'overall' + '' today ---
    scope_kind: str                            # String(16)  'overall'|'set'|'rarity'
    scope_key:  str                            # String(64)  '' for overall

    # --- methodology identity: three versions, three owners (§5) ---
    methodology_version: int                   # ours, copied at calculation time
    index_version: int                         # copied from the constituents
    source_semantics_version: int              # copied from the constituents

    point_date: date
    index_value: Decimal | None                # Numeric(12,4); NULL = unpublishable

    # --- segment identity and the continuous-level carry (§5, §8.3) ---
    is_base: bool
    carried_from_point_id: int | None           # self-FK; NULL = initial base

    # --- the step that produced it ---
    prior_point_date: date | None
    step_days: int | None
    chain_link_log_return: Decimal | None       # Numeric(18,12)

    # --- breadth, so a flat day is legible rather than suspicious ---
    constituent_count: int                      # prints with a return this step
    eligible_print_count: int                   # prints valued on point_date
    movers_up: int | None
    movers_down: int | None
    movers_flat: int | None
    capped_count: int | None                    # NOT "winsorized_count" — see §2

    unpublishable_reason: str | None            # String(32)
    calculated_at: datetime                     # tz-aware
    created_at: datetime                        # server_default now()
```

Every constraint, in the both-directions-equality style the sibling table
already uses — never a one-way implication:

```sql
-- identity -------------------------------------------------------------
PRIMARY KEY (id)

CONSTRAINT uq_cpi_points_point
    UNIQUE (scope_kind, scope_key, methodology_version, point_date)
    -- the ON CONFLICT DO NOTHING identity, and the read path's index.
    -- index_version is deliberately NOT a key column: two rows for one day
    -- under two index_versions is an error, not a legal pair of rows.

CONSTRAINT uq_cpi_points_carry_target
    UNIQUE (id, scope_kind, scope_key, index_value)
    -- EXISTS SOLELY AS THE FK TARGET BELOW. Redundant for reads (id alone is
    -- already unique); it is the price of enforcing the carry equality in the
    -- database instead of in application code. admin_db_index_audit will flag
    -- it as unused — that is expected, and this comment is the answer.

-- the carry (§8.3) -----------------------------------------------------
CONSTRAINT fk_cpi_points_carried_from
    FOREIGN KEY (carried_from_point_id, scope_kind, scope_key, index_value)
    REFERENCES card_pirate_index_points (id, scope_kind, scope_key, index_value)
    MATCH SIMPLE ON DELETE RESTRICT ON UPDATE RESTRICT
    -- Composite on purpose. One constraint proves three things at once:
    --   the target exists, it is in the SAME scope, and its index_value is
    --   IDENTICAL to this row's. MATCH SIMPLE means the whole check is
    --   skipped when ANY referencing column is NULL — which is exactly the
    --   behaviour wanted for carried_from_point_id IS NULL, and is safe
    --   because ck_cpi_points_base_has_value + ck_cpi_points_carry_requires_base
    --   together make index_value NOT NULL whenever the carry is set.
    --   MATCH FULL would be WRONG here: it rejects any partially-NULL tuple,
    --   and every ordinary row has NOT NULL scope columns with a NULL carry.
    -- ON UPDATE RESTRICT makes a carried-from point's published level
    --   IMMUTABLE at the database level, not merely by convention.
    -- ON DELETE RESTRICT means the chain cannot be silently truncated,
    --   matching MarketIndexSnapshot's RESTRICT on card_print_id.

CONSTRAINT ck_cpi_points_carry_requires_base
    CHECK (carried_from_point_id IS NULL OR is_base)
CONSTRAINT ck_cpi_points_carry_not_self
    CHECK (carried_from_point_id IS NULL OR carried_from_point_id <> id)
CONSTRAINT ck_cpi_points_initial_base_is_base_value
    CHECK (NOT is_base OR carried_from_point_id IS NOT NULL OR index_value = 1000)

-- scope ----------------------------------------------------------------
CONSTRAINT ck_cpi_points_scope_kind
    CHECK (scope_kind IN ('overall','set','rarity'))
CONSTRAINT ck_cpi_points_scope_key_pairing
    CHECK ((scope_kind = 'overall') = (scope_key = ''))

-- publishability -------------------------------------------------------
CONSTRAINT ck_cpi_points_value_presence
    CHECK ((index_value IS NULL) = (unpublishable_reason IS NOT NULL))
CONSTRAINT ck_cpi_points_base_has_value
    CHECK (NOT is_base OR index_value IS NOT NULL)
CONSTRAINT ck_cpi_points_base_has_no_step
    CHECK (NOT is_base OR (chain_link_log_return IS NULL
                           AND prior_point_date IS NULL
                           AND step_days IS NULL
                           AND constituent_count = 0))
CONSTRAINT ck_cpi_points_step_requires_prior
    CHECK (is_base OR index_value IS NULL OR prior_point_date IS NOT NULL)
CONSTRAINT ck_cpi_points_step_days_positive
    CHECK (step_days IS NULL OR step_days >= 1)

-- breadth --------------------------------------------------------------
CONSTRAINT ck_cpi_points_constituents_le_eligible
    CHECK (constituent_count <= eligible_print_count)
CONSTRAINT ck_cpi_points_breadth_presence
    CHECK ((movers_up IS NULL) = (constituent_count = 0))
    -- breadth is present exactly when a constituent set existed. Base rows,
    -- mixed-version days and empty steps all have constituent_count = 0 and
    -- NULL breadth; an insufficient_constituents day still reports its n.
CONSTRAINT ck_cpi_points_movers_pairing
    CHECK ((movers_down IS NULL) = (movers_up IS NULL)
           AND (movers_flat IS NULL) = (movers_up IS NULL)
           AND (capped_count IS NULL) = (movers_up IS NULL))
    -- without this, movers_up=1 with movers_down NULL makes the sum below
    -- evaluate to NULL, and a CHECK passes on NULL. The hole is real.
CONSTRAINT ck_cpi_points_movers_sum
    CHECK (movers_up IS NULL
           OR movers_up + movers_down + movers_flat = constituent_count)
CONSTRAINT ck_cpi_points_capped_le_constituents
    CHECK (capped_count IS NULL OR capped_count <= constituent_count)
CONSTRAINT ck_cpi_points_counts_non_negative
    CHECK (constituent_count >= 0 AND eligible_print_count >= 0
           AND (movers_up IS NULL OR (movers_up >= 0 AND movers_down >= 0
                                      AND movers_flat >= 0 AND capped_count >= 0)))
```

The foreign key is **not** `DEFERRABLE`. Points are inserted in ascending
`point_date` order per scope (§8.6), so the target always pre-exists and an
immediate check fails at the offending row rather than at commit.

| Decision | Rationale |
| --- | --- |
| Three indexes, not two | `pkey`, `uq_cpi_points_point` (the read path), and `uq_cpi_points_carry_target` (FK target only). The third is a deliberate, annotated exception to "no index beyond the unique constraint". |
| No provenance JSON column | Per-constituent evidence already lives in `market_index_snapshots.provenance`, is immutable, and is replayable. Duplicating it costs ~660 B/point for nothing. |
| No FK to `card_prints` | A point is an aggregate over a set, not a fact about a print. Constituent identity is recoverable by replay. |
| Not added to `PRUNABLE_TABLES` | Conscious omission, matching how `market_index_snapshots` is already absent. See §9. `ON DELETE RESTRICT` now backs that up for any carried-from point. |

Optionally in the same revision, additive and only helpful: a covering index
`(snapshot_date, card_print_id) INCLUDE (index_value_jpy, index_version,
source_semantics_version)` on `market_index_snapshots`, which makes the daily
aggregate and the `--verify` replay index-only and skips the 661-byte JSONB
entirely. This is a mitigation *with* persistence, never instead of it.

### 8.5 Constraint proof

The DDL above was created on **PostgreSQL 18.6** (staging runs PG18.4) in a
throwaway container and every case below was executed against it. Each attempt
ran inside a savepoint; the container was destroyed afterwards. No staging
database was involved.

| # | Attempt | Outcome | Enforced by |
| ---: | --- | --- | --- |
| 1 | Initial base: `is_base=true`, `carried_from_point_id=NULL`, `index_value=1000.0000` | **ACCEPTED** | — |
| 2 | Ordinary non-base step row with full breadth | **ACCEPTED** | — |
| 3 | Carried base: `is_base=true`, `carried_from_point_id=<step row>`, same scope, `index_value` identical | **ACCEPTED** | — |
| 4 | Carried base referencing **itself** | REJECTED | `ck_cpi_points_carry_not_self` |
| 5 | **Non-base row** with `carried_from_point_id` set | REJECTED | `ck_cpi_points_carry_requires_base` |
| 6 | Carried base whose `index_value` **differs** from the source point's | REJECTED | `fk_cpi_points_carried_from` |
| 7 | `overall` carried base referencing a **`set`-scope** point | REJECTED | `fk_cpi_points_carried_from` |
| 8 | Initial base with `index_value = 1200` | REJECTED | `ck_cpi_points_initial_base_is_base_value` |
| 9 | Base row carrying a `chain_link_log_return` | REJECTED | `ck_cpi_points_base_has_no_step` |
| 10 | `movers_up + movers_down + movers_flat <> constituent_count` | REJECTED | `ck_cpi_points_movers_sum` |
| 11 | `constituent_count = 231` with all movers `NULL` | REJECTED | `ck_cpi_points_breadth_presence` |
| 12 | `movers_up = 1` with `movers_down` `NULL` (the NULL hole) | REJECTED | `ck_cpi_points_movers_pairing` |
| 13 | Unpublishable row: `index_value` NULL + `unpublishable_reason` | **ACCEPTED** | — |
| 14 | Carried base with `index_value` NULL (the `MATCH SIMPLE` escape hatch) | REJECTED | `ck_cpi_points_base_has_value` |
| 15 | Duplicate `(scope, methodology_version, point_date)` | REJECTED | `uq_cpi_points_point` |
| 16 | `capped_count > constituent_count` | REJECTED | `ck_cpi_points_capped_le_constituents` |
| 17 | `DELETE` a point a later segment carries from | REJECTED | `fk_cpi_points_carried_from` (RESTRICT) |
| 18 | `UPDATE` a carried-from point's `index_value` | REJECTED | `fk_cpi_points_carried_from` (RESTRICT) |
| 19 | Carried base referencing an id that does not exist yet | REJECTED | `fk_cpi_points_carried_from` |

All nineteen behaved as specified. Cases 6 and 7 are the ones worth noting:
**a single composite FK proves both the same-scope requirement and the exact
level equality**, with no trigger and no application-layer check.

Case 14 is the reason `MATCH SIMPLE` is safe here. `MATCH SIMPLE` silently
skips the entire foreign key when any referencing column is NULL, so a carried
base with a NULL `index_value` would slip past the FK unchecked — except that
`ck_cpi_points_base_has_value` rejects it first. The two constraints have to be
read together; neither is sufficient alone.

### 8.6 Replay, idempotency and insertion order

`carried_from_point_id` is a **surrogate** reference, and that has consequences
the job and `--verify` must respect. All three findings below were measured on
the PG18.6 harness described in §8.5.

**1. Idempotent re-run is safe.** Re-running the job over days that already
exist inserts nothing (`ON CONFLICT (scope_kind, scope_key, methodology_version,
point_date) DO NOTHING`), so a carried base's `carried_from_point_id` is never
rewritten. Measured: a second identical run returned no ids and left every row
byte-identical.

**2. Surrogate ids are NOT stable across a rebuild; natural keys are.**
Measured: after truncate-and-replay the same three logical points came back as
ids `7, 8, 9` instead of `1, 2, 3`, with the carry pointing at `8` instead of
`2`. The natural keys were identical. Two rules follow, and both are binding:

- **`--verify` must never compare `carried_from_point_id` as an integer.** It
  resolves the reference to the target's natural key
  `(scope_kind, scope_key, methodology_version, point_date)` and compares
  *that*. The fields compared by `--verify` are: the natural key,
  `index_value`, `is_base`, `chain_link_log_return`, `prior_point_date`,
  `step_days`, `constituent_count`, `eligible_print_count`, the four breadth
  counters, `unpublishable_reason`, the three version columns, and the
  *resolved natural key* of the carry target. It must **not** compare `id`,
  `carried_from_point_id`, `calculated_at` or `created_at`, none of which are
  reproducible.
- **Point ids must never appear in the public API payload.** §12.1 exposes the
  carry as `carried_from_point_date`, resolved by join. A rebuild then changes
  no public value, and no client can ever hold a stale id.

**3. Insertion order is a requirement, not a convention.** The FK is immediate
and non-deferrable, so a carried base can only be inserted **after** its target
exists. Therefore:

- Within a scope, points are inserted in **ascending `point_date` order**.
  Scopes are independent and may be written in any order relative to each
  other.
- A carried base referencing a not-yet-inserted row is rejected outright
  (§8.5 case 19) rather than left dangling. A partial replay that starts after
  its own carry target fails **closed and loudly**, which is the desired
  behaviour.
- `--replay-from <date>` is therefore only valid when every carry target at or
  before that date is still present. The job must assert this before writing
  and refuse otherwise, rather than discovering it as an FK error mid-run.

**4. Acyclicity is a convention, not a schema guarantee — stated plainly.**
The constraints reject a *self*-reference (case 4) but a two-row cycle
(`A → B` and `B → A`) is reachable by a hand-written `UPDATE`; this was
confirmed on the harness, and it succeeded. What actually prevents cycles is
the same thing that protects `market_index_snapshots`: **the code has no
UPDATE path**, and a fresh `INSERT` can only reference a row that already
exists. Postgres will still permit a hand-written `UPDATE`, exactly as the
sibling model's docstring already concedes for its own append-only contract.

Two mitigations, both cheap:

- `ON UPDATE RESTRICT` on the FK already makes a carried-from point's
  `index_value` immutable, so the *level* half of the chain cannot be rewritten
  even by hand.
- `--verify` asserts `target.point_date < row.point_date` for every carry. A
  cycle necessarily violates this, so the replay check catches by
  measurement what the schema cannot catch by declaration.


## 9. Retention dependency — hard, and now explicit

`market_index_snapshots` is deliberately absent from
`app/services/data_retention.py::PRUNABLE_TABLES`. **That absence is what makes
`--verify` and `--replay-from` possible.** The day anyone adds a retention
policy for that table, the Card Pirate Index's verifiability dies quietly: the
stored levels remain, but nothing can prove they were ever right.

`card_pirate_index_points` is likewise not prunable. Two years of the overall
index is 730 rows, roughly 100 kB.

Budget for the parent table's growth instead of pruning it: 4,316 prints ×
791 B × 365 ≈ **1.25 GB/year** at full coverage.

---

## 10. Currency caveat

Every value in this index is JPY, derived from JPY-quoted Japanese sources.

The index is unit-free — it is a ratio of JPY values to JPY values — so it is
internally consistent. But "how the One Piece card market has performed"
implies a currency-neutral claim it is **not** making: a non-JP collector
reading a +5 % move cannot separate card appreciation from yen movement.

This is a documented limitation, not a defect to fix in v1. Any FX-adjusted
variant is a different measurement and would be a new
`methodology_version` — and therefore a new segment.

---

## 11. What is deliberately unchanged

| Surface | Disposition |
| --- | --- |
| `app/services/market_index.py` | **UNCHANGED.** No pricing-semantics change; `INDEX_VERSION` untouched. |
| `app/services/print_market_index.py` | **UNCHANGED.** |
| `app/services/source_semantics.py` | **UNCHANGED.** `SOURCE_SEMANTICS_VERSION` untouched. |
| `app/services/market_index_change.py` | `eligible_contributor_set` **REUSED, not edited.** |
| `app/snapshot_market_index.py` | **UNCHANGED.** Market Index snapshotting is not modified. |
| `app/models/market_index_snapshot.py` | **UNCHANGED.** Append-only contract intact. |
| `GET /analytics/market/bases` | **UNCHANGED** — becomes the basis selector for chart and panels. |
| `GET /analytics/market/filters` | **UNCHANGED** — also supplies the sub-index vocabulary for §14. |
| `GET /analytics/market/overview` | **UNCHANGED** — becomes the market-depth panel beneath the index. |

The Analytics 1A endpoints are current-state only and compute no change, no
trend and no ranking. `market_analytics.py` states the position explicitly:
*"there is no window parameter here at all… Adding one later is additive;
inventing one now would not be."* They are exactly the market-depth panel that
belongs beneath a movement chart, and they repurpose byte-identical.

---

## 12. API contract

```
GET /analytics/index?window=2w|1m|3m|6m|1y|2y|all[&set=OP-01][&rarity=SR]
```

Unauthenticated, on exactly the argument already written at
`app/api/analytics.py:50-61`: every number is an aggregate of data already
public through `GET /prints` and `GET /prints/{id}/market-index`. Cached via
the existing `get_or_set_cache` / `set_cache_headers` pair; TTL can be long,
since data changes once daily at 20:00 UTC.

**Scope grammar: reuse `/analytics/market/overview`'s existing `?set=` /
`?rarity=`.** Do not introduce a `?scope=set:OP-01` form.
`app/services/price_basis.py` exists specifically because two surfaces on one
screen must not have two grammars for the same idea — *"the strip of cards
under a chart could show a print the chart never counted."*
`MarketLandscapeFilters` should drive chart and panels together, unchanged.

### 12.1 Payload

```jsonc
{
  "methodology_version": 1,
  "base_value": 1000,
  "window": "all",
  "window_start": null,                 // null for "all"
  "default_window": "all",              // §13 — the server owns this rule
  "generated_at": "2026-09-07T…Z",
  "scope": { "set": null, "rarity": null },
  "available": true,
  "unavailable_reason": null,           // "no_history_in_window" | "insufficient_constituents"
  "currency": "JPY",                    // §10

  "current": { "date": "2026-09-06", "value": 1000.9577 },

  "windows": {
    "2w":  {"available": false, "covered_days": 4, "required_days": 14},
    "1m":  {"available": false, "covered_days": 4, "required_days": 30},
    "3m":  {"available": false, "covered_days": 4, "required_days": 90},
    "6m":  {"available": false, "covered_days": 4, "required_days": 180},
    "1y":  {"available": false, "covered_days": 4, "required_days": 365},
    "2y":  {"available": false, "covered_days": 4, "required_days": 730},
    "all": {"available": true,  "covered_days": 4, "required_days": null}
  },

  "segments": [{
    "methodology_version": 1, "index_version": 3, "source_semantics_version": 2,
    "base_date": "2026-09-03",
    "carried_from_point_date": null,   // null => initial base; §8.3, §8.6
    "points": [
      {"date":"2026-09-03","value":1000.0000,"is_base":true,
       "prior_point_date":null,"step_days":null,"chain_link_log_return":null,
       "constituent_count":0,"eligible_print_count":231,
       "movers_up":null,"movers_down":null,"movers_flat":null,"capped_count":null},
      {"date":"2026-09-04","value":1000.8409,"is_base":false,
       "prior_point_date":"2026-09-03","step_days":1,
       "chain_link_log_return":0.000840502227,
       "constituent_count":231,"eligible_print_count":281,
       "movers_up":1,"movers_down":0,"movers_flat":230,"capped_count":0}
    ]
  }],

  "breaks": [],                          // §6: none at 2026-09-03

  "coverage": {"earliest":"2026-09-03","latest":"2026-09-06",
               "distinct_days":4,"point_count":4,
               "requested_window_days":null,"covered_window_days":4,
               "covers_requested_window":true,
               "shortfall_reason":null},

  "change": {"absolute":0.9577,"pct":0.095765,
             "from_date":"2026-09-03","to_date":"2026-09-06",
             "spans_break":false},
  "change_unavailable_reason": null    // §5.6: "no_published_point_in_window"
                                       //     | "no_carried_continuity"
}
```

`change` is `null` — not zero, not omitted — whenever §5.6 rule 2 or rule 5
applies, and `change_unavailable_reason` then says which. `from_date` and
`to_date` are the endpoints **actually used**, which for a window whose first
day is unpublishable are not the requested ones.

Point ids are deliberately absent from every object here. The carry is
published as `carried_from_point_date`, resolved by join, because surrogate ids
do not survive a rebuild (§8.6 finding 2).

A `breaks` entry, once one exists:

```jsonc
{"at":"2026-11-14","reason":"index_version_change",
 "from_index_version":3,"to_index_version":4,
 "carried":true,
 "carried_level":1042.1188,"carried_from_point_date":"2026-11-13"}
```

`carried: false` marks a **reset** boundary — a segment that opened at 1000
with no carry. Under this methodology that only happens at a scope's very
first point, and any *later* occurrence is what makes §5.6 rule 5 withhold a
change figure. A `snapshot_gap` break carries neither `carried` nor
`carried_level`; it is a cadence fact, not a methodology one.

`segments` + `breaks` + `coverage` mirror `PrintSeriesHistoryOut` deliberately:
one client-side chart primitive should render both a print's index history and
this index.

### 12.2 Reporting insufficient history honestly

1. **Never 404 and never silently substitute a shorter window.** A `window=2y`
   request with 4 days of data returns those 4 days,
   `covers_requested_window: false`, `covered_window_days: 4`.
2. **Never pad the axis.** Do not emit null points for the 726 missing days and
   do not stretch 4 points across a 2-year axis. The client draws its domain
   from `coverage.earliest`/`latest`; the unmet request is reported, not
   disguised.
3. **The `windows` map is the key affordance.** It lets the frontend render
   2W/1M/3M/6M/1Y/2Y as *disabled* buttons with a reason rather than as
   clickable paths into a misleading chart.
4. **A window is "available" only if the data spans it** — `coverage.earliest
   <= window_start`. Span, not point count, matching the existing
   `covers_7d`/`covers_30d` definition. Sparse history that spans a window
   still covers it; gaps stay gaps.
5. Under §5's carry policy, **a break does not make a window unavailable.**
   The level series is continuous across segments, so a 1Y window spanning
   three segments is available, renderable, and flagged `spans_break: true`.

### 12.3 Change, window by window

Every window resolves its change by §5.6 and nothing else. Availability and
change are **separate questions**: a window can be available and still return
`change: null`.

| Window | Change | `spans_break` |
| --- | --- | --- |
| `2w` `1m` `3m` `6m` `1y` `2y` | Latest published point vs. the earliest published point at or after `window_start`. Unavailable windows return no change, because they return no span. | `true` iff the resolved span crosses at least one boundary |
| `all` | Latest published point vs. the chain's earliest published point. This is the "Since launch" figure. | `true` iff the series contains at least one boundary |

Today every window except `all` is unavailable, `all` gives
`+0.095765 %`, and `spans_break` is `false` everywhere because the series has
no boundary yet.

Three cases where change is `null` rather than a number, restated because they
are easy to get wrong at the call site:

- The window contains **no published point** →
  `"no_published_point_in_window"`. Do not fall back to the base value.
- The span crosses a **reset** rather than a carry →
  `"no_carried_continuity"`. Do not silently shorten the window to the newest
  continuous stretch; that would answer a question the user did not ask.
- A single published point in the window (so `from_point == to_point`) → change
  is `0.0` with `from_date == to_date`, **not** `null`. There is a real
  measurement here: the level did not move because there was nothing to move
  it. This is the one case that is genuinely zero rather than absent.

---

## 13. Product behaviour

### 13.1 Analytics — default window

- **`All` is the default while less than 3 months of history exists.**
- **Once 3M is available (`windows["3m"].available == true`), 3M becomes the
  default.**
- Unavailable timeframe buttons **remain visible but disabled**, never hidden
  and never clickable.

The server publishes `default_window` so the rule lives in one place and is
contract-testable; the client must not re-derive it.

### 13.2 Home — the market snapshot panel

- Show the **current Card Pirate Index level**.
- Secondary line is one change figure, selected by this ladder:
  1. **1M** if `windows["1m"].available`
  2. else **2W** if `windows["2w"].available`
  3. else **"Since launch"** — the `all` window's change, labelled as such
- **No fabricated shorter windows.** Do not invent a 1D or 7D figure merely
  because it is arithmetically computable; the published window grammar is
  2W/1M/3M/6M/1Y/2Y/All and Home draws from it.
- When the `all` window is used, the label is "Since launch" and never "1M" or
  "2W".
- **A change whose span carries `spans_break: true` is still shown** — it is a
  legitimate linked-index return (§5.2) — but never as a bare percentage. It
  carries a visible marker whose tooltip or footnote says the span crosses a
  methodology change. Suppressing the number would be as dishonest as
  presenting it unqualified.
- **If `change` is `null`, Home shows the level and no change line at all.** It
  does not fall back to a shorter window, and it does not print "0 %". The
  ladder above selects a *window*; it never rescues a `null`.

Concretely, on the ladder's eventual 1M rung: once a boundary exists and the
trailing month spans it, Home's 1M figure is computed across the carry and
rendered with the break marker. That is the intended steady state, not an edge
case.

### 13.3 A flat chart is acceptable

**A flat chart must not be cosmetically amplified.** Concretely, for the
frontend tranche:

- The y-domain must include the segment base level and must span **at least
  ±1 %** around it. A +0.096 % total move must render as a visually flat line,
  because that is what it is.
- No auto-zoom to the data range when the data range is smaller than that
  span.
- No baseline truncation that turns a 0.1 % move into a visible slope.

**Breadth is the supporting story while movement is sparse.** `movers_up` /
`movers_down` / `movers_flat` and `constituent_count` are first-class, not
diagnostics: "296 of 296 cards unchanged" is the honest headline on a day like
2026-09-06, and it is more informative than a flat line alone.

### 13.4 Break markers and tooltips

The two break kinds render differently, because they mean different things.

| Break | Line | Marker | Tooltip |
| --- | --- | --- | --- |
| `index_version_change`, `source_semantics_version_change`, `methodology_version_change` | **Solid and continuous through the boundary** — the level really is continuous (§5.1 rule 4) | Vertical rule at the break date, always visible | Names what changed (`index_version 3 → 4`), the carried level, and one sentence: *"Measurement method changed here. Levels are chain-linked across this point; the underlying card prices on either side are not directly comparable."* |
| `snapshot_gap` (`step_days > 1`) | **Dashed across the gap** — there is genuinely no data between the two points | No vertical rule needed | Names the missing days and that the join is a real multi-day return, not interpolation |

Rules that follow:

- **Never draw a discontinuity in the line at a version break.** Dropping the
  line to 1000, or leaving a visual gap, would contradict the stored data.
  The marker carries the meaning; the line carries the level.
- **Never hide a marker because the chart is crowded.** If several breaks fall
  close together, collapse them into one marker whose tooltip lists all of
  them — never drop one.
- Any change figure rendered near the chart and carrying `spans_break: true`
  points at the same explanation, so the chart and the number tell one story.
- A `null` change renders as an explicit "not available across this period"
  affordance, never as a blank or a dash that reads as zero.


---

## 14. Set-level and rarity-level sub-indexes

No source hardcoding is required, because the methodology names no source. It
reads `market_index_snapshots.index_value_jpy`, and `_compute_index_fields` is
source-agnostic by construction — *"it consults no source name, no
reference_type and no evidence type."* A sub-index is a `GROUP BY` on a
constituent attribute and nothing else.

- `scope_kind` / `scope_key` on the point row (§8.4) — already present,
  `'overall'` / `''` today.
- **Set key:** `COALESCE(release_products.official_code,
  card_prints.release_product_code)` via `card_prints.release_product_id`.
- **Rarity key:** reuse
  `app/services/print_catalogue.py::effective_rarity_sql()` — the exact helper
  `market_analytics` already uses for the same filter. Do not restate the
  rarity coalescing.
- **Vocabulary** comes from the existing `GET /analytics/market/filters`,
  which derives set and rarity options from the active catalogue with no
  allowlist.

The daily job loops scopes; each runs the identical `compute_step()` against a
filtered constituent set. One code path, N rows/day.

`MIN_CONSTITUENTS` then gates per scope, **from data, not from a maintained
list of "supported sets"**: on today's staging, ten of thirteen sets and three
of six rarities honestly report `insufficient_constituents`. Each sub-index
scope opens its own `initial` segment at 1000 on its own first eligible day —
which is why §8.3 records the carry as an explicit reference instead of
inferring "initial" from "earliest row".

Adding Card Rush / Mercado / Cardmarket requires **zero** Card Pirate Index
changes. A new source arrives as a resolver in `market_index.py`, lands in
`provenance.source_values`, and enters the contributor-set comparison
automatically. The only index-visible effect is an `INDEX_VERSION` bump if the
combination rule moves — which correctly opens a new segment rather than
silently changing what the index measures.

---

## 15. Rollout sequence

Steps 3–8 are backend-only and independently revertible. The index is not
visible to a collector until step 9.

| # | Step | Detail |
| --- | --- | --- |
| 1 | Foundation audit | **DONE** — `docs/card_pirate_index_foundation_audit_2026-09-07.pdf`, read-only. |
| 2 | This document | **DONE** — freezes §1's constants, the estimator, and the continuous-level segment policy. Audit risks R1, R2, R4, R5, R7 are closed by §13, §2, §5, §6, §13.2 respectively. |
| 3 | Migration + model | Additive, empty, deployable alone. Single linear revision off `b8e3f1a70d95`, no branch. Includes `carried_from_point_id`, its composite FK and `uq_cpi_points_carry_target` from day one — retrofitting the carry later would mean guessing at existing base rows. Optionally the §8.4 covering index. Downgrade drops only the new table, and unlike the snapshot table that loss is **fully recoverable by replay** — say so in the docstring. |
| 4 | `app/services/card_pirate_index.py` | Pure function over fixtures. Named tests for: degenerate-median, degenerate-p99-winsorization, entrant, leaver, gap/`step_days`, version boundary **with level carry**, carry across an unpublishable final point, mixed-version day, below-minimum, cap binding at ±`ln(1.25)`, cap sign preservation, contributor-set churn, sub-index scope opening its own initial segment. Plus a **Postgres-only** constraint suite (`test_card_pirate_index_constraints_postgres.py`) re-running all nineteen §8.5 cases — SQLite proves none of them. |
| 5 | Job with `--dry-run` and `--verify` | Run `--dry-run` against staging read-only; diff against §17's hand-verified expectation. `--verify` compares the §8.6 field list only, resolving carries by natural key, and asserts `target.point_date < row.point_date`. |
| 6 | Replay seed `2026-09-03` → yesterday | Insert in ascending `point_date` per scope (§8.6 finding 3). Verify idempotency by running it twice and confirming the second run inserts nothing and rewrites no carry. Confirm the seeded levels equal §17.1 exactly. |
| 7 | Scheduling | Extend the existing `market-index-snapshot` Railway service's start command to run the index job **after** the snapshot job in the same container run. Do **not** add a second cron — the index must observe the same day's snapshot, and one process guarantees the ordering that two crons twenty minutes apart merely hope for. Add `card_pirate_index` to `LOCK_TTL_SECONDS` at 600 s, matching `market_index_snapshot`. |
| 8 | API route + contract tests | Ship live with no frontend consumer. Verify the `windows` map reports every timeframe but all as unavailable, that `default_window` is `"all"`, that `breaks` is empty, that no point id appears anywhere in the payload (§8.6), and that a synthetic reset yields `change: null` with `"no_carried_continuity"` (§5.6 rule 5). |
| 9 | Frontend tranche A — `/analytics` | Dominant chart, under `docs/ui/ATLAS_LOOP.md`: contract first, fresh visual reviewer, before/after desktop + mobile captures. Removes `MarketMovementUnavailable` (`page.tsx:426`), which exists solely to say the archive cannot answer a movement question. Must implement §13.1, §13.3 and §13.4. |
| 10 | `/clear`, then frontend tranche B | Home market snapshot panel, implementing §13.2. |

Also update `docs/operations.md` with the job-lock row, the cron runbook entry,
and the §9 retention dependency.

---

## 16. Open risks carried forward

| ID | Risk | Status |
| --- | --- | --- |
| R1 | Flat headline chart | **CLOSED by decision.** A flat chart is acceptable and must not be amplified (§13.3). Breadth carries the story. |
| R2 | Median abandoned | **CLOSED by decision.** §2. Recorded in `METHODOLOGY_VERSION = 1`. |
| R3 | Yuyu-Tei batch timeout churns the panel | **OPEN, operational.** 214 eligible × 6.47 s ≈ 23 min against a 1,200 s budget, in id-ascending order, so the newest prints are skipped first. Skipped prints survive the 7-day freshness window, then drop to `coverage_status='none'` in cohorts. §3 rule 4 converts that into a `constituent_count` fall rather than a fake price move — but a large single-day panel change means the index describes a different market. **Mitigation:** `eligible_print_count` is reported beside `constituent_count` on every point; consider flagging a point where `constituent_count` falls >20 % day-over-day. |
| R4 | Rebasing on every methodology change | **CLOSED by decision.** §5's carry policy: the level is continuous, the measurement is not, every crossing is flagged, and change across a carry is a published linked-index return (§5.6). |
| R5 | Chart the v1 archive | **CLOSED by decision.** No — §6. Knowingly dark, not accidentally missing. |
| R6 | Currency | **DOCUMENTED.** §10. Out of scope for v1. |
| R7 | Home snapshot content | **CLOSED by decision.** §13.2 — level plus a 1M → 2W → "Since launch" ladder. |
| R8 | Retention dependency | **DOCUMENTED.** §9, now an explicit hard dependency rather than an implicit absence. |
| R10 | Append-only is a convention, not a schema guarantee | **ACCEPTED, mitigated.** A hand-written `UPDATE` can still create a carry cycle; measured on the PG18.6 harness (§8.6 finding 4). The code has no UPDATE path, `ON UPDATE RESTRICT` freezes a carried-from level, and `--verify` asserts strictly increasing carry dates. This is the same exposure `market_index_snapshot.py` already concedes for its own append-only contract, and it is inherited, not introduced. |
| R9 | Cap headroom is thin | **NEW, monitor.** The largest real same-version daily move to date is +21.43 %, 87 % of the +25 % cap (§17.4). If genuine moves routinely approach the cap, the cap is doing estimation rather than error-suppression and the constant must be revisited — which is a `METHODOLOGY_VERSION` bump and a new segment, not a quiet edit. |

---

## 17. Recomputed staging evidence

Recomputed 2026-09-07 under the frozen §2 algorithm, inside a
`SET TRANSACTION READ ONLY` session over a fresh
`railway connect Postgres --tunnel-only` tunnel, after
`scripts/staging_db_read_check.py` confirmed database identity by schema
fingerprint (all six checks PASS; `canonical_cards=2710`, `card_prints=4316`,
`sources=3`, alembic `b8e3f1a70d95`). No write path was exercised.

### 17.1 The published series

`cap = ln(1.25) = 0.223143551314` · `BASE_VALUE = 1000` ·
`MIN_CONSTITUENTS = 30`

| date | level | step (log) | step (%) | n | up | down | flat | **capped** | eligible | step_days |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-09-03 | **1000.0000** | — *(base)* | — | 0 | — | — | — | 0 | 231 | — |
| 2026-09-04 | **1000.8409** | +0.000840502227 | **+0.084086 %** | 231 | 1 | 0 | 230 | **0** | 281 | 1 |
| 2026-09-05 | **1000.9577** | +0.000116689761 | **+0.011670 %** | 281 | 1 | 0 | 280 | **0** | 296 | 1 |
| 2026-09-06 | **1000.9577** | +0.000000000000 | **0.000000 %** | 296 | 0 | 0 | 296 | **0** | 297 | 1 |

**Cumulative since launch: 1000.0000 → 1000.9577, +0.095765 %** over four days.

Zero constituents excluded by version mismatch (§3 rule 3) and zero by
contributor-set churn (§3 rule 4) on any step — the guards cost nothing today
and are pure insurance. Zero constituents capped. Zero leavers. Zero
multi-day steps. No mixed-version day.

### 17.2 The two movers

| step | print | prior | day | log return | price % | capped? |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 09-03 → 09-04 | OP01-047 SR (`card_prints.id=5686`) | ¥14,000 | ¥17,000 | 0.194156014 | +21.4286 % | no |
| 09-04 → 09-05 | OP01-051 SR (`card_prints.id=5836`) | ¥6,000 | ¥6,200 | 0.032789823 | +3.3333 % | no |

One card moved on each of two days; nothing moved on the third. This is the
market the index has to describe, and it is why §13.3 exists.

### 17.3 Estimator comparison, same constituent sets

| step | n | **frozen: capped mean** | median | p1/p99 winsorized mean | empirical p99 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 09-04 | 231 | **+0.000840502227** | 0.000000000000 | 0.000000000000 | 0.0000000000 |
| 09-05 | 281 | **+0.000116689761** | 0.000000000000 | 0.000000000000 | 0.0000000000 |
| 09-06 | 296 | 0.000000000000 | 0.000000000000 | 0.000000000000 | 0.0000000000 |

| Estimator | Final level | Verdict |
| --- | ---: | --- |
| **Capped equal-weighted mean of log returns** | **1000.9577** | **FROZEN — v1** |
| Median of daily log returns | 1000.0000 | REJECTED — permanently flat |
| p1/p99 winsorized mean | 1000.0000 | REJECTED — **p99 is itself zero**, so it clips away the only signal |

This is the empirical proof of §2.2. With 230 zeros and one positive mover, the
empirical p99 is exactly `0.0`, so winsorizing at p99 sets the mover to zero
and the "outlier-resistant mean" degenerates into the median it was supposed to
improve on.

### 17.4 Cap headroom, and where the archive's big moves actually live

The eight largest absolute daily moves in the entire archive:

| day | print id | prior | day | log return | price % | > cap? | same version pair? |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 2026-09-03 | 5998 | ¥120 | ¥1,310 | +2.390290673 | +991.67 % | YES | **no — v2→v3** |
| 2026-09-02 | 5998 | ¥1,310 | ¥120 | −2.390290673 | −90.84 % | YES | **no — v1→v2** |
| 2026-09-03 | 7 | ¥120 | ¥810 | +1.909542505 | +575.00 % | YES | **no — v2→v3** |
| 2026-09-02 | 7 | ¥810 | ¥120 | −1.909542505 | −85.19 % | YES | **no — v1→v2** |
| 2026-09-01 | 5998 | ¥2,500 | ¥1,310 | −0.646263595 | −47.60 % | YES | yes (v1) |
| 2026-09-03 | 5687 | ¥35,000 | ¥66,000 | +0.634306681 | +88.57 % | YES | **no — v2→v3** |
| 2026-09-02 | 5687 | ¥66,000 | ¥35,000 | −0.634306681 | −46.97 % | YES | **no — v1→v2** |
| 2026-09-02 | 13 | ¥1,040 | ¥580 | −0.583947889 | −44.23 % | YES | **no — v1→v2** |

Six of the eight are **version artefacts, not market moves** — v2 zeroed
fallback values and v3 restored them, so the same print appears to crash and
recover. All six are excluded by §3 rule 3 before the cap is ever consulted.
This is the strongest available argument for the boundary policy in §5: the
largest apparent moves in the archive are precisely the ones that are not
moves at all.

Within a single version pair, the cap has never bound. The largest
same-version move is +21.43 % against a +25 % cap — **87 % of the cap**, which
is thinner headroom than is comfortable. Tracked as R9.

### 17.5 Archive census (whole table, for the record)

| days | index_version | source_semantics_version | rows/day | valued/day | published here |
| --- | ---: | ---: | --- | --- | --- |
| 2026-08-21 → 09-01 | 1 | 1 | 20 → 58 | 20 → 49 | **NO** — below `MIN_CONSTITUENTS` |
| 2026-09-02 | 2 | 1 | 237 | 228 | **NO** — single day, no prior same-version day |
| 2026-09-03 → 09-06 | 3 | 2 | 240 → 306 | 231 → 297 | **YES** |

---

## 18. Worked example — five hypothetical cards

Base 2026-09-03, index 1000.0000.

**Day 0 (base).** A ¥80 (C) · B ¥3,000 (R) · C ¥66,000 (SP manga) · D ¥30 (C)
· E ¥12,900 (L parallel). No prior day → `is_base = true`,
`carried_from_point_id = NULL`, no return, `constituent_count = 0`.

**Day 1.** A ¥80 · B ¥3,300 · C ¥62,000 · D ¥30 · E ¥12,900. All five valued
on both days, all contributor sets identical → `n = 5`.

| Card | P → D | log return |
| --- | --- | ---: |
| A | 80 → 80 | 0 |
| B | 3,000 → 3,300 | +0.0953102 |
| C | 66,000 → 62,000 | −0.0625204 |
| D | 30 → 30 | 0 |
| E | 12,900 → 12,900 | 0 |

Cap ±0.2231436 — neither binds, `capped_count = 0`.

- Median = `0.0000` → index stays `1000.0000`. **← the degeneracy, in five cards**
- p1/p99 winsorized mean = `+0.00655796` here (n=5 makes p1/p99 the extremes
  themselves, so it happens to agree) — but at n=231 with 230 zeros, p99 = 0
  and it collapses to the median. See §17.3.
- **Frozen mean** = `(0 + 0.0953102 − 0.0625204 + 0 + 0) / 5 = +0.00655796`
- **Index = 1000 × exp(0.00655796) = 1006.5795**

Note card C: a ¥4,000 fall on the ¥66,000 card and a ¥300 rise on the ¥3,000
card carry weights of `1/5` each. Under any value-weighted scheme C alone
would be 80 % of the panel.

**Day 2.** A ¥80 · B ¥3,300 · C ¥62,000 · **D drops out** (Yuyu-Tei
observation aged past `YUYUTEI_SELL_MAX_AGE_DAYS = 7` →
`coverage_status='none'`, `index_value_jpy` NULL) · E ¥13,500 · **F enters** at
¥500, its first ever valued day.

| Card | log return | in return set? |
| --- | ---: | --- |
| A | 0 | YES |
| B | 0 | YES |
| C | 0 | YES |
| D | — | **NO — no day-2 value** |
| E | +0.0454624 | YES |
| F | — | **NO — no day-1 value** |

- `n = 4` · mean = `0.0454624 / 4 = +0.01136559`
- **Index = 1006.5795 × exp(0.01136559) = 1018.0851**
- `constituent_count = 4` · `eligible_print_count = 5` (A, B, C, E, F)
- `movers_up = 1` · `movers_down = 0` · `movers_flat = 3` · `capped_count = 0`

**What this proves.** F's ¥500 arriving moved the index by exactly nothing. D's
departure moved it by exactly nothing. Only prints priced at *both* ends of the
step moved the level. That is the chain-link property, and it is the whole
answer to "constituents entering and leaving coverage must not create fake
market movement."

**Day 3 — a version boundary.** `INDEX_VERSION` moves 3 → 4 overnight. Under
§5:

- The old segment closes at its final published level, `1018.0851`.
- A new segment opens: `is_base = true`, `carried_from_point_id = <day 2's
  id>`, `index_value = 1018.0851`. The composite FK proves that level equals
  day 2's exactly and that both rows are the same scope (§8.5 proofs 3, 6, 7).
- `prior_point_date`, `step_days` and `chain_link_log_return` are NULL, and
  `constituent_count = 0`. **No return is calculated across the boundary**,
  under either version.
- A break is emitted at that date with `reason = "index_version_change"`,
  `from_index_version = 3`, `to_index_version = 4`, `carried: true`,
  `carried_level: 1018.0851`, `carried_from_point_date: <day 2>`.
- The chart draws a **solid continuous line** through the boundary with a
  vertical marker (§13.4). It does **not** drop to 1000 and it does **not**
  break the line.
- A change from day 0 to day 4 is now a **linked-index return**: it is
  computed, it is published, and it carries `spans_break: true` plus the
  §13.4 tooltip. It is not withheld — but it is never presented as a bare
  percentage.
- Had the new segment instead opened at 1000 with `carried_from_point_id =
  NULL`, that same change would be `null` with
  `change_unavailable_reason: "no_carried_continuity"` (§5.6 rule 5).

---

*Card Pirate Index — methodology of record · v1 frozen 2026-09-07 · branch
staging @ f736e92 · alembic b8e3f1a70d95. Nothing in this document is
implemented: no model, migration, job, route or frontend exists yet. All
staging figures were recomputed read-only.*
