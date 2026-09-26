# Atlas Market Value methodology

This document describes the A2 calculation boundary. The design authority and
audit evidence are [A0](reports/public-ux-market-value-a0-2026-09-26.md) and
[A1](reports/public-ux-market-value-a1-2026-09-26.md). A2 adds a pure engine
and a read-only diagnostic; it does not add persistence or a public API.

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
