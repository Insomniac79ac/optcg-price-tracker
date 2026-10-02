# Yuyu-Tei promotional-price correction — staging

Base: remote staging `2ce865930507acaf50d06dabb50b5100c389227c`.

## Product behavior

A Yuyu observation with `promotion_state=sale` remains immutable internal evidence.
Customer source values are unavailable/null, public source history omits the row,
and normalized pricing excludes it with `sale_price`, `eligible=false`, and
`contributes_to_index=false`. No older regular observation or struck former
price replaces a latest sale. Regular Yuyu and independent SNKRDUNK prices retain
their existing rules.

Source semantics changes **2 → 3**; index combination version remains **3**.
The API response-cache namespace includes the semantics version, preventing an
old cached price from surviving rollout. Existing observations and published
Market Value history are not rewritten. Future Market Index snapshots feed the
corrected inputs into the existing Market Value publication workflow, whose
version-comparison guards continue to apply.

## Pre-deployment impact

Read-only staging database sessions passed all repository schema fingerprints.
SSH tunneling was unavailable because this workspace has no SSH key; the public
Postgres proxy was verified against Railway metadata before accepting the
fingerprinted database. Public GETs independently checked all 94 latest-sale
variants. Collection continued on its existing schedule during the audit.

| Measurement | Before | Projected after |
|---|---:|---:|
| Latest promotional Yuyu observations | 94 | Retained internally |
| Latest promotional Yuyu prices exposed publicly | 94 | 0 |
| Latest promotional Yuyu index contributors | 94 | 0 |
| Priced Market Index variants | 639 | 545 |
| Market Index coverage of 4,316 active prints | 14.8054% | 12.6274% |

Coverage decreases by 94 variants, or 2.1779 percentage points. Comparing every
active print's current index found exactly 94 changed prices, all in the affected
sale set; no other current index value changed.

91 affected variants lose their only current customer-facing source quote.
Three retain a SNKRDUNK ¥1,000 listing quote (prints 12, 14, 17), but these are
platform-floor observations and remain index-ineligible. Thus **zero** affected
variants retain another valid normalized source. This distinguishes an observed
customer-visible quote from an admissible Market Index input.

64 variants have only promotional Yuyu history and no other source history.
95 variants have ever had a sale observation. Historical promotional observation
counts increased from 2,126 to 2,133 during the audit (the supplied earlier count
was 2,113); none were deleted. 94 latest archived index snapshots include sale
contributions under the previous semantics. Those published archives remain
unchanged; future snapshots use v3.

## CardPrint 5661 / OP04-099

The retained HTML snapshot 18732 contains `<del>120 円</del>` alongside current
sale `80 円`. Observation 17075 stores ¥80 with `promotion_state=sale`.

Before: public Yuyu ¥80, Market Index ¥80, one contributor, semantics v2.
After: Yuyu value null; sale rows absent from source history and chart series;
Market Index null with zero contributors; `sale_price` exclusion, semantics v3.
¥120 is never substituted. The raw observation and HTML remain available internally.

## Endpoint and adapter audit

- `/cards/{id}/prices`: promotional source observations excluded.
- `/prints/{id}/prices`: promotional rows excluded; current trend summaries do
  not fall back to an older regular price.
- `/prints/{id}/series`, `/prints/{id}/analytics`: sale source points omitted
  after daily latest selection, preventing same-day fallback; chart source
  extents exclude promotional-only history.
- `/cards/{id}/market-index`, `/prints/{id}/market-index`, print details and
  catalogue/grid adapters: null promotional source value, explicit exclusion.
- Market overview, distributions and source-price cards reuse the corrected
  resolver; constrained coverage now counts promotional exclusions.
- Collection, wishlist, portfolio, buy/sell decision and grading adapters use
  shared latest-price readers that filter **after** latest-row ranking.
- `/market/movers`, `/market/signals`: sale current prices and trend baselines
  excluded; independent source evidence remains usable.
- `/market/signal-events`, `/market/opportunities`, reports and dashboard
  adapters: archived quote payloads sanitized on read against source evidence
  at their original capture time; archives remain unchanged.
- Worker signal, report, portfolio and price-alert readers apply the same
  visibility rule. The worker ORM now reads the existing promotion-state column;
  this adds no database migration.
- Market Value current inputs and future publication inputs reuse corrected
  print indexes. Published Market Value rows and methodology remain unchanged.
- Frontend price adapters already treat backend null as unavailable and request
  uncached pricing data; no frontend price substitution is introduced.

Primary implementation files: `source_semantics.py`, `customer_prices.py`,
`latest_prices.py`, `print_pricing.py`, `market_index.py`, `print_market_index.py`,
`print_series.py`, `print_analytics.py`, `market.py`, `market_signals.py`,
`public_price_payload.py`, and their API/report/dashboard adapters. Worker changes
are confined to the existing model column and price-reading paths. Collection
parsing and storage behavior are unchanged.

## Validation and rollout scope

Regression coverage includes sale-only and mixed-source normalized prices,
regular and legacy-null prices, stale sales, public history, same-day and older
regular fallback prevention, recovery when a regular observation arrives,
archived payload redaction, immutable internal evidence, snapshot/Market Value
inputs, and the OP04-099 ¥80/struck-¥120 parser case.

Deployment is staging only after tests pass. Existing Git deployment triggers
and cron schedules are used unchanged. No manual collector, discovery,
backfill, snapshot or publisher job is run. No mapping approvals, Batch 2,
proposal decisions, due-work activation, production access, database writes,
or capacity changes are part of this correction.

See `yuyu-promotional-price-impact-2026-10-02.json` for the pre-deployment
measurements and affected print IDs. Final test counts and deployment receipts
are reported after rollout verification.

Final local validation before deployment:

- Complete API suite: **4,524 passed, 541 skipped** (415.07 seconds).
- Complete worker suite: **601 passed, 18 skipped** (18.61 seconds).
- Complete Yuyu collector suite: **462 passed, 19 skipped, 42 subtests passed**.
- Additional affected-price/version suite: **320 passed**.
- Archived-price adapter suite: **92 passed**.
- Skips are environment-dependent integration checks, principally tests requiring
  an explicitly configured disposable PostgreSQL database. The staging impact
  calculations additionally exercised current-price queries against PostgreSQL
  in verified read-only sessions.
- No migration is needed. Git diff whitespace validation passed.
