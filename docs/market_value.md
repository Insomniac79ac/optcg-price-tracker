# Atlas Market Value methodology

This document describes the frozen A2 calculation boundary and the A3A
persistence boundary, and the A4A persisted public read contract. The design authority and
audit evidence are [A0](reports/public-ux-market-value-a0-2026-09-26.md) and
[A1](reports/public-ux-market-value-a1-2026-09-26.md). A2 adds a pure engine
and a read-only diagnostic. A3A adds append-only replay storage and
verification. A4A reads that stored evidence without a scheduler or request-time replay.

## Frozen v1 rule ledger

The implementation treats the following as versioned rules, not tuning
parameters:

- The basket contains one copy of each active, verified Japanese physical
  print in the recorded scope membership. A release scope is the exact
  `CardPrint.release_product_id`; neither a card-code prefix nor an original
  set code can assign membership.
- A usable value is a positive archived Atlas Market Index JPY value. There is
  no inferred price, forward fill, zero fill, or nearest-date lookup.
- A comparable print is present and usable on both adjacent UTC dates, keeps
  the same release assignment for a release scope, has matching index and
  source-semantics versions, and has the same nonempty contributing `(source,
  reference_type)` set. Missing contributor-role provenance fails closed.
- An entrant, leaver, or first observation after re-entry changes the literal
  tracked sum but contributes no return. Re-entry becomes comparable only on
  its next adjacent stable pair. Contributor churn excludes that transition.
- A day with mixed measurement versions, a cross-version transition, a
  membership break, a skipped date, an invalid denominator, or any failed
  coverage gate starts a new segment. A new segment is based at `1`; no
  displayed 7D/30D window may cross the break.
- The return estimator uses the comparable prior/current sums directly. It
  does not adjust a raw sum, clip per-print returns, import CPI weighting, or
  maintain a divisor. Chaining multiplies only fully publishable adjacent-day
  ratios.
- Current release prominence uses the same size-aware count/physical-breadth
  thresholds as movement, applied to currently priced prints. It does not use
  the 80% comparable-value test because no prior/current panel is involved.
- Existing archive replay uses one explicitly named digest of the current
  corrected active catalogue and release FKs. Future published points must
  freeze their own membership revision; a later correction applies forward
  and cannot silently rewrite already published history.

## Two separate measurements

One basket constituent is one active, verified Japanese physical `CardPrint`.
Release membership comes only from `CardPrint.release_product_id`. Card code,
canonical family, rarity, and artwork similarity never assign a print to a
release.

**Current tracked value** is the literal sum of every positive usable current
Atlas Market Index JPY value in the selected scope:

`S(s,d) = sum(v(i,d) for i in E(s,d))`

The result carries priced-print count, physical-print count, coverage, and an
explicit partial/no-prices state. No prices yields `null`, not `¥0`. The
literal sum is not chain-linked and never implies unpriced prints are
worthless. Its collector-facing name remains **Current tracked value** or
**Current tracked release value**, with coverage beside it.

**Price movement** measures only adjacent-day changes among comparable
physical prints. For prior day `p` and current day `d`, the comparable set `C`
contains a print only when it has a positive value at both endpoints, stable
physical and release identity for the selected scope, equal index and source
semantics versions, and the same nonempty contributing `(source,
reference_type)` set.

`P = sum(v(i,p) for i in C)`

`Q = sum(v(i,d) for i in C)`

`R = Q / P`

`r = R - 1`

Within a continuous valid segment, `F(base) = 1` and `F(d) = F(p) * R`.
`F` is dimensionless performance. It is separate from the current literal JPY
sum. Higher-value prints naturally have more effect because the estimator sums
yen before taking the ratio; there is no equal weighting and no CPI daily cap.
Per-print market impact is `delta_jpy = v(i,d) - v(i,p)` and percentage-point
contribution is `100 * delta_jpy / P`.

JPY inputs and comparable sums remain integers. Non-terminating ratios use a
private 50-significant-digit Decimal context, independent of mutable process
state, with no display quantization. Window and segment chains multiply the
integer numerators and denominators first and convert the resulting exact
rational once, avoiding sequential rounding drift.

## Coverage neutrality and breaks

An entrant is excluded from its first transition. A leaver is excluded from
the transition on which its price disappears. A returning print is an entrant
after its gap and cannot bridge the missing day. Contributor-set, index-version,
and source-semantics changes exclude the affected print. A day containing
mixed methodology versions, or a transition between different single
methodologies, is not publishable.

There is no forward fill, zero fill, nearest-date lookup, or inferred price.
Every 7D or 30D window needs all adjacent UTC-day snapshots and every step must
pass. A missing day or failed gate creates a segment break. An unavailable
movement is `null` with machine-readable reasons; it is never a fabricated
`0%`.

New durable points must freeze the active/verified print membership and
release assignment used for that date. Release corrections start a release
segment break. A release reassignment alone does not change the physical-print
identity of the Overall basket. Since existing `market_index_snapshots` do not
store historical membership, the A2 diagnostic explicitly replays them using
one digest of the current corrected catalogue. This is an assumption recorded
in the output, not a claim about the membership published on old dates.

## Publication gates

Arithmetic and publication eligibility are separate engine calls. Every
published step also requires `P > 0` and comparable prints representing at
least 80% of the priced JPY value at both endpoints:

`P / S(s,p) >= 0.80` and `Q / S(s,d) >= 0.80`.

Release gates are size-aware and apply at both endpoints:

- `N >= 30`: at least 30 comparable prints and at least 40% physical coverage.
- `10 <= N < 30`: at least `max(10, ceil(0.80 * N))` comparable prints and at
  least 80% physical coverage.
- `N < 10`: release movement is unavailable in methodology v1.

Overall requires at least 300 comparable prints and at least 10% physical
coverage at both endpoints, plus the same 80% comparable-value guard.

The current release headline uses the same size-aware count and physical
coverage thresholds on currently priced prints. Below it, the partial literal
sum may appear only as detail with coverage. Overall may display any nonempty
literal tracked sum, but must always identify it as partial when the catalogue
is not completely priced.

## Read-only replay

Run the diagnostic from `services/api` against an explicitly supplied database
environment:

```console
python -m app.market_value_replay_report --require-postgres-read-only --pretty
```

On PostgreSQL, the command makes `SET TRANSACTION ISOLATION LEVEL REPEATABLE
READ READ ONLY` its first statement, verifies `transaction_read_only=on`,
performs only `SELECT` queries, then rolls back and closes. It projects archived
`market_index_snapshots`, current `CardPrint.release_product_id` membership,
and current stored price observations into the pure engine in memory. It does
not fetch a source, generate a snapshot, persist a point, or run a collector.

The implementation is intentionally separate from Card Pirate Index. CPI
remains its existing equal-weight, capped, base-1000 series; changing either
algorithm does not change the other.

## Persisted replay evidence

`market_value_points` stores one Overall or Release point per archived UTC
snapshot day and Market Value methodology version. Release identity is the
`ReleaseProduct` foreign key; the database rejects a release row without that
FK and an Overall row with one. Its natural keys are:

- Overall: `(methodology_version, point_date)` under `scope_kind=overall`.
- Release: `(release_product_id, methodology_version, point_date)` under
  `scope_kind=release`.

These are separate partial unique indexes because PostgreSQL otherwise treats
NULL release IDs as distinct and would permit duplicate Overall points. The
internal surrogate ID is not a public identity.

The row records the literal `tracked_value_jpy` and its priced/physical counts
separately from movement evidence: prior endpoint facts, comparable count,
integer `P` and `Q`, exact Decimal `Q/P`, segment number, and the dimensionless
performance factor. It does not create an anchored monetary chart level.
Physical coverage and comparable JPY-value coverage remain exactly derivable
from those source facts, so rounded percentages are not stored. An unavailable
step keeps its ordered A2 reason tuple and a nonpublishable flag; it never
stores a fabricated return. A factor of `1` on such a row is only the frozen
A2 new-segment base, not `0%` movement.

Each point also freezes the current-corrected catalogue membership digest and
canonical index/source-semantics version-pair sets used by replay. It does not
copy constituent IDs into aggregate rows or create another historical card
catalogue. The immutable `market_index_snapshots` archive remains the detailed
source evidence.

The writer accepts already-derived drafts; it contains no basket arithmetic or
membership decisions. Drafts are sorted by natural key, inserted with `ON
CONFLICT DO NOTHING`, and immediately compared with the stored row. An
identical rerun is a verified no-op. A natural-key collision with any different
fact is an integrity error and is never overwritten. The independent verify
path recomputes drafts from archived snapshots and compares every deterministic
field by natural key, ignoring only the surrogate ID and `created_at`.

Application backup v14 introduced the existing CPI historical-evidence policy
for Market Value (retained in v15, which also includes snapshot completion receipts):
Market Value points are exported and restored when `include_prices=true`, and
are intentionally absent when price history is excluded. The points remain
fully replayable from retained snapshot evidence; backup inclusion preserves
the exact series Atlas had persisted rather than changing its derivation.

## Public persisted read API (A4A)

`GET /analytics/market-value?release_product_id=<positive ID>&window=7d|30d|all`
is public. The default is Overall and `7d`; Overall has null release fields.
Release IDs, codes and display names come from `ReleaseProduct`, including
legitimate uncoded products when their series exists. Unknown IDs return 404;
invalid IDs/windows return 422. Missing Overall v1 data, or a known release
without a persisted v1 series, returns 503 with
`{"detail":"market_value_not_seeded"}`.

`as_of` is the latest persisted UTC date **for the selected scope**. It is not
the HTTP request time or a live quote timestamp. The initial staging series
ends on **2026-09-26**; API requests neither advance it nor invent a bridge to
today. Version 1 is selected explicitly, so another methodology cannot extend
or mix into its history.

The response separates three measurements:

- `tracked_value`: literal partial JPY sum, priced/physical counts, physical
  coverage percentage and `is_partial`. No prices means null JPY, not zero.
  Zero physical population means null coverage. This is not market cap and
  does not estimate unpriced prints.
- `movement`: requested window, availability, exact required start/end dates,
  return fraction/percent, and a stable reason. Every required UTC date and
  adjacent stored prior-date link must exist. Each step must be publishable,
  with a positive comparable P/Q pair and unchanged segment. The return is
  `product(stored Q) / product(stored P) - 1`, multiplying integers and then
  dividing once with the frozen 50-digit Decimal precision. This is the A2
  rule applied to persisted chain evidence; it never divides tracked sums.
  Unavailable fractions/percentages are null. `all` measures the entire stored
  date span and is unavailable if any break exists, or fewer than two dates.
- `series`: only the stored points within the requested inclusive date span
  (8 endpoints for a complete 7D window; 31 for 30D). Each carries date, literal
  JPY value, counts, daily publication flag/reason and server-calculated
  performance. Missing dates are not filled.

Chart performance is `100 * (F(date) / F(anchor) - 1)`, using persisted
`performance_factor` and a private 50-digit Decimal context. The anchor is
the first visible positive-value point with a publishable step, or the initial
series base when it has a value. Its performance is 0%. A failed step's reset
factor of 1 is **not** a zero return: that chart point is null. Any subsequent
gap, failed step or segment change ends the anchor's comparable span; later
performance stays null instead of connecting an independently rebased segment.
Selecting a shorter window can expose a later valid segment with its own
first-visible anchor. Literal historical JPY sums remain present independently
and must not be presented as coverage-neutral values.

Decimal percentages and fractions serialize as JSON strings, following the
existing API's Decimal convention. JPY values and counts are JSON integers.
Surrogate point IDs, membership digests, serialized version pairs, factors,
and writer/job metadata are excluded from public responses.

`GET /analytics/market-value/releases` returns `items` and `ordering_basis`.
Every active coded, verified JP release in the persisted model is included,
even with sparse or no prices. `ReleaseProduct` has no active flag; active
membership is therefore the latest **persisted** positive physical count,
not a query of today's mutable `CardPrint` catalogue. Each row has its own
`as_of`, identity, version, tracked value, and separate 7D/30D availability,
percentage and reason. The read fetch is bounded to the last 31 stored points
per scope. It shares `/releases` ordering: official `released_on` descending,
undated last, then catalogue/code/name/ID as deterministic ties. Those ties
do not assert chronology.

The service performs SELECTs only against `market_value_points` and
`release_products`, with autoflush disabled. It never invokes the writer,
replays snapshots, computes live prices, or accesses a source. Local tests
use mock persisted rows, an A2 oracle comparison, explicit forbidden-call/SQL
guards, and PostgreSQL REPEATABLE READ READ ONLY. The frozen census regression
uses the audited 59-release counts/sums with synthetic chain evidence;
independent staging validation compares the service with the real Sep-26
persisted rows before publication of the PR.

## Monetary rankings (A4B)

Both ranking endpoints are public and SELECT-only. Optional positive
`release_product_id` selects the authoritative ReleaseProduct FK; omission
selects Overall. Unknown IDs are 404. Missing Overall data or a known release
without its own persisted series is 503 `market_value_not_seeded`, as in A4A.
Neither endpoint changes the A4A release table or adds per-release queries to it.

### Daily Market Movers

`GET /analytics/market-value/movers?order=gainers|losers|impact&limit=10`
selects the newest persisted **publication-eligible daily step** for the scope.
There is no 7D/30D attribution parameter: daily denominators compound, and
multi-day attribution remains deferred. `scope_as_of` is the latest persisted
scope date; `step_date` and `prior_date` identify the actual selected daily
step, even when it is older. An older step is never called today's movement.

Only those two exact snapshot dates are read. The frozen A2 pure engine
reconstructs comparability, contributions and publication eligibility. Before
any ranking is returned, the service requires exact agreement with the stored
point's dates, P/Q/C, ratio, publication decision/reasons, version-pair sets,
membership revision, and both endpoints' tracked values and counts. It never
uses live PriceObservations, the current price resolver, full archive replay,
the writer, or CPI movers.

All comparable prints, including flat ones, participate in reconciliation:

- `sum(delta_jpy) = Q - P`, exactly in integer JPY.
- Each contribution is the frozen A2 50-significant-digit Decimal value
  `100 * delta_jpy / P`. The Decimal sum must equal `100 * (Q - P) / P`
  within only the sum of individual and aggregate half-ULP rounding bounds at
  that precision. There is no price/percentage epsilon, correction bucket,
  cap, or adjusted contribution. Persisted ratios must match exactly; the
  rounding allowance applies only to summing independently rounded fractions.

Ranking occurs over the full qualifying population, then truncates to `limit`
(default 10, 1–50). Gainers are positive deltas sorted by move fraction DESC;
losers are negative deltas sorted by move fraction ASC; impact is every
non-flat delta sorted by absolute JPY change DESC. All ties use print ID ASC.
The payload retains signed deltas and signed percentage-point contributions.
A ¥100,000 print gaining ¥10,000 outranks a ¥500 print gaining 100% by impact,
while the cheap print wins by percentage gain. No CPI equal weighting or
`approx_index_points` is reused.

Response: `available`, `reason`, scope/release identity, methodology version,
the three dates, `panel` (C, P, Q, basket JPY delta and percent), `order`,
`total_ranked`, `returned`, `truncated`, and `movers`. Rows include exact print
identity, prior/current JPY, signed delta, Decimal move fraction/percent,
percentage-point contribution, direction and full-population rank. If no
published step exists, return 200 with `available=false`,
`reason=no_published_daily_step`, null step dates/panel measurements, and
`movers=[]`. This is different from a published flat panel, whose actual
movement is zero and whose ranking can legitimately be empty.

### Most Valuable exact physical prints

`GET /analytics/market-value/most-valuable?limit=10&offset=0` decomposes the
selected scope's latest persisted partial tracked basket. It reads only
`snapshot_date == as_of`, never a newer live price. `limit` is 1–50 and offset
is nonnegative. Every positive snapshot value is eligible; null, zero and
negative values are excluded. Exact siblings remain separate.

Before sorting/pagination, the **entire** eligible population must match the
persisted priced count and JPY sum. Its version set must match persistence,
and every eligible row must share one UTC `calculated_at` whose calendar date
equals `as_of`. Mixed batches fail closed, even if the conflicting row would
fall outside the returned page. An unpriced basket has zero eligible items,
null calculation time and an empty list, not an invented zero-JPY valuation.

Sort is snapshot JPY DESC, print ID ASC. Response: scope/release identity,
methodology version, `as_of`, `calculated_at`, `total_eligible`, `limit`,
`offset`, `items`. Each item has print/canonical IDs, card code, preferred
catalogue name, the exact print's official rarity (nullable), treatment,
official asset variant, authoritative release identity, structured display
image, snapshot JPY and calculation timestamp. There is no family collapse,
confidence/investment score, or internal snapshot ID.

### Membership, images, and integrity failures

Initial replay froze a **global** digest of active verified JP print IDs and
release FKs, including uncoded releases. Both rankings reproduce that same
digest before using today's identity metadata. Even a change outside the
selected release conservatively refuses decomposition: the archive has no
historical membership ledger with which to prove a narrower correction safe.
The digest algorithm and evidence serializers are shared pure helpers,
extracted unchanged from A2/A3; HTTP imports neither replay nor persistence.

Names/artwork remain current stored presentation metadata. Only returned
prints are image-enriched in one batched read using the existing display-image
helper: verified stored artwork, canonical fallback, then null if absent.
No image is fetched. Unexpected database/enrichment failures propagate as on
the print catalogue; prices and identity are not fabricated to hide them.

Integrity errors return typed HTTP 503:
`{"detail":{"code":"market_value_integrity_mismatch","reason":"..."}}`.
Stable reasons are `membership_revision_mismatch`, `persisted_step_mismatch`,
`panel_reconciliation_failed`, `tracked_value_mismatch`,
`mixed_valuation_batch`, and `snapshot_version_mismatch`. No partial ranking
is returned. Internal digests, raw version serialization and job metadata are
not public. Fractions/percentages serialize as Decimal strings; JPY/counts
are integers. Tests enforce bounded snapshot dates, forbidden replay/writer/
source/current-price/CPI calls, no autoflush, and PostgreSQL READ ONLY.

Optional release-table top movers are deferred: these dedicated endpoints
must not produce 59 independent attribution/reconstruction queries per table
request. A future batched design must retain the same reconciliation authority.
