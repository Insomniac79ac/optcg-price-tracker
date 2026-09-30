# Shared freshness and due-work foundation

This is an inactive foundation. The dependent [collector adapter slice](collection_freshness_adapters.md)
adds explicit opt-in consumers; default collectors, cron, Celery entry points,
customer APIs and valuation readers do not call it. Migration `7c9e4a12b6d0` adds four empty tables on top
of `e6a8b0c3d5f7`; it does not backfill prices, create source limits, or enable work.
Source admission also requires an explicitly enabled budget row. Importing the
modules performs no scheduling, collection, or database writes.

## Freshness contract

`app.services.freshness_policy.FreshnessPolicy`, version `current-price-v1`, is the
single policy for every source and every current-price category:

| Product interest | Current-price target | Default dispatch due |
| --- | --- | --- |
| Standard | 24 hours after capture | Capture + 23 hours |
| High interest | 4 hours after capture | Capture + 3 hours |

Interest is an explicit product decision supplied by the planner. Neither source,
raw/graded category, availability, nor available capacity changes the target.
Execution headroom defaults to one hour and is configurable in whole seconds,
strictly between zero and four hours. The version's targets are fixed. Deadlines
are exclusive: a price is stale at exactly capture + target. All clocks are
injectable and all accepted timestamps are aware UTC. Future/unknown timestamps
cannot yield a fresh verdict. There is no seven-day source or raw-price exception.

These facts remain distinct:

| Fact | Authoritative foundation field |
| --- | --- |
| Claim/selection | Work and attempt `claimed_at` |
| Last attempted source request | Work `last_attempted_at`, attempt `started_at`, set by request admission |
| Last successful product check | Work `last_successfully_checked_at` |
| Last successful category check | Price state `last_successfully_checked_at` |
| Last valid current-price capture | Price state `last_valid_price_observed_at` and `last_observation_id` |
| Current category availability | Price state `availability`: unknown, listed, no_listing |
| Next check due | Category and work `next_due_at` |
| Failure retry gate | Work `retry_not_before_at`, separate from an overdue deadline |
| Most recent failure | Work `last_failure` and `last_failure_at`; retained after recovery |
| Most recent outcome | Work `last_outcome` and immutable terminal attempt outcome |

A new successful capture can reaffirm the same JPY value. Completion requires a
new successful raw snapshot fetched during the owned attempt, correct source and
mapping/print lineage, and observations matching the category's existing writer
signature (`price_type`, `condition_label`). The persisted freshness origin is the
snapshot's capture time, never the later parse time. Reusing a snapshot for another
attempt is refused. An observation dated before the capture is historical evidence
and cannot become current by passing it through this service.

No-listing is an explicit successful check of named categories. It updates their
check cadence and availability, retaining any old price timestamp. Failed fetches
and identity refusals change neither availability nor successful-check/price times.
An omitted category remains due; this also protects new demand added during a claim.
The foundation never rewrites existing observations or changes a valuation formula.

`derived_freshness` consumes only the observation times of the **actual contributing
inputs**. The oldest input determines expiry; any unknown lineage gives `unknown`.
`calculated_at`, publication time, and saved-evidence reprocessing are not inputs.
An explicit historical value returns `historical`. Contributor/expected counts report
coverage independently: partial coverage can contain fresh inputs, and full coverage
can be stale. No current endpoint has been switched to this contract in this slice.

## Durable records and lineage

| Table | Purpose and identity |
| --- | --- |
| `freshness_work` | One source-product refresh, source discovery/validation scope, or source/print discovery recheck. Durable deadline, priority, policy version/headroom, state, cursor, owner and lease. |
| `freshness_price_states` | One category per refresh work item, with separate evidence signature, availability, check time, price time and due date. |
| `freshness_attempts` | One UUID claim token per attempt, ordered request grants, outcome, actual and charged request costs, evidence link and result digest. |
| `source_dispatch_budgets` | One source-wide enabled flag, fixed-window request limit, outstanding reservations, charges, pause and fairness cursor. |

Refresh identity uses the existing canonical source listing identity, scoped to the
source. A unique source/product constraint and deterministic hashed work key coalesce
raw/PSA10 demand into one capture. Grade is not part of the job key. Category names
may differ from stored price types; `PriceCategory` records the existing writer's
signature, including its condition label when needed. This does not introduce a
new grade taxonomy or alter existing source eligibility.

Refresh planning and dispatch require a current approved active mapping onto an
active verified exact CardPrint. SNKRDUNK additionally retains its existing manual
verification gate. The composite mapping/print/source FK prevents mismatched lineage.
Unestablished canonical product identity is refused. A product remapped to a different
mapping/print requires explicit reconciliation; the planner neither duplicates that
product nor carries the previous print's price state onto a new print.

Discovery and validation scopes contain no approved mapping ID. Print discovery
contains the authoritative CardPrint ID and source, with no invented mapping. Scope
keys must describe stable source work (for example a sitemap shard or release scope).
Repeated planning preserves claims, completion deadlines and cursors. Category demand
is upserted atomically; tighter product priority can advance outstanding deadlines.
It cannot hide overdue work by relaxing a target.

## Claiming, fairness and admission

`claim_due` reserves at most 100 work items in a short PostgreSQL transaction. The
source budget row serializes admission from every kind of work; due rows use
`FOR UPDATE SKIP LOCKED`. The returned `Claim` values are detached data and remain
usable after commit. No row lock needs to survive a source request.

The persistent source cursor cycles through high, ordinary, high, discovery, high,
ordinary, high, coverage. With all lanes due and affordable, every eight admitted
jobs include four high-interest refreshes, two ordinary refreshes, one discovery or
validation job, and one first-coverage job. Empty lanes yield to available work.
All newly mapped products enter coverage, including high-interest products, until
their first successful check. Within a lane: earliest due time, least recent claim
sequence, priority, then ID. The sequence breaks frozen-clock resume ties so a
low-ID scope cannot continually jump ahead of its tail. Bounds are in admissions;
capacity or source pauses can still make time deadlines unattainable.

Yuyu's optional shard filter keeps `mapping_id % 9 == shard_index`. It cannot steal
another lane's source-wide turn: it yields when the appropriate existing worker
must drain that lane. The next integration must arrange timely draining of all
lanes rather than run independent queues which compete for the remaining budget.
A chunk of 70 has no calendar meaning; the next due chunk can be claimed immediately.

Every source request, including a canary, discovery page, validation request or
retry, must obtain `admit_request` in a fresh short transaction. A claim alone is
not dispatch permission. Request ordinals are idempotent: a replay returns False
and must not send another request. Admission rechecks ownership, the source-wide
pause and the reserved upper bound. An already-claimed job cannot bypass a later
pause. This is a scheduling contract; wiring the browser/request meter is a future
adapter requirement.

Limits must be configured explicitly. There is no unlimited fallback. Reserve a
conservative request-cost upper bound, not a product count; actual costs are recorded
separately at completion and unused reservations released. Outstanding reservations
survive window rollover. An expired claim is recovered in bounded groups of 100:
its full reservation is charged conservatively, while `actual_request_cost` stays
NULL because it is unknown. A reported cost overrun is retained and pauses the source.
A denial records `source_denial` and an indefinite source pause. There is no automatic
retry or timed unpause after denial. Identity refusal blocks that work for explicit
review; transient failure uses a separate retry-not-before timestamp.

Before domain result writes, call `lock_for_result` in the same database transaction
as the existing writer and `complete_claim`. False means the delivery already
completed and the writer must be skipped. Completion checks the UUID and lease again,
uses a digest to accept identical replay and reject conflicting replay, and settles
cost/evidence/cursor/deadlines together. Expired workers cannot publish through a
replacement token. This is at-least-once work with idempotent handling, not a claim
of exactly-once network delivery. Roll back domain writes on any completion refusal.

## Integration points for the next slice

1. **Yuyu collection:** feed approved product/category demand into `plan_refresh`;
   retain `yuyutei_collector.batch` eligibility, nine-shard membership, pacing,
   watchdogs, raw-before-parse flow, identity checks and telemetry. Existing workers
   consume their routed claims and call request admission for all source I/O.
2. **SNKRDUNK raw/PSA10:** extend the current product capture through its existing
   extractor/writer work. Plan both categories on one product, report each observed
   or explicitly unlisted category, and retain `collection_lock`, `pinned_session`
   and `assert_lock_owned`. Queue ownership supplements that singleton; it does not
   replace it or authorize extra live concurrency. Preserve the current PSA10 work
   and its chosen observation signature.
3. **Discovery:** use `plan_discovery_scope` and `plan_print_discovery` for durable
   demand. Retain `worker.jobs.snkrdunk_checkpoint` as the existing checkpoint
   authority: a versioned queue cursor may point to the current discovery run, and
   candidates, its checkpoint and queue completion must commit together. Continue
   `load_latest_checkpoint`/`reconcile_with_sitemap`; never restart from an empty or
   older checkpoint. Yuyu can carry its existing slug/page progress the same way.
   Validation uses `plan_validation` and the same source budget. No candidate or
   mapping approval is created by queue planning.
4. **Customer APIs/UI:** add policy version, capture/checked/attempted times,
   availability, due/expiry, freshness verdict and coverage as separate response
   fields in the current-price read paths (`latest_prices`, `print_pricing`,
   catalogue/card detail and current Market Value reads). Replace source-specific
   freshness labels during that reviewed cutover. Do not label a successful
   no-listing check as a fresh price or a historical sale as a current listing.
5. **Derived values:** retain contributor observation IDs and capture timestamps
   in the calculation lineage, then call `derived_freshness` on only those inputs.
   Missing lineage yields unknown. Leave source eligibility, valuation arithmetic,
   historical series, snapshot receipts and the daily Market Value coordinator
   unchanged. Publication cannot upgrade an old contributor's freshness.

A collector adapter must ship this central service through a reviewed shared
integration boundary (an internal dispatch API or the same Python service package),
not duplicate its policy or create a second scheduler. That boundary, transport
authentication and collector packaging are deliberately not activated here.

## Migration, backup and activation requirements

Apply the additive migration only in a separately authorized rollout, before code
that uses the new backup registry is deployed. A downgrade drops only the four new
tables; export scheduler state first once it has been used. No existing price or
mapping data is transformed in either direction.

Selective JSON backup version 16 includes the new records in FK-safe order. Versions
12–15 remain readable without inventing due work or source limits. Excluded raw and
price data have scheduler pointers explicitly nulled and counted in
`freshness_provenance`; captured timestamps remain evidence, not invented lineage
for a derived value. Clean-database restore is tested with and without those options.
The existing restriction on replacing identity parents while omitting existing price
history remains intact. Restore disables source admission, invalidates active claim
tokens, conservatively charges outstanding reservations, and preserves due dates and
resumable progress. Operator review is required before enabling restored budgets.

Activation still requires: approved source-wide request limits and measured cost
instrumentation; product interest selection; bounded lease/runtime configuration;
collector request/result adapters; draining all fairness lanes; reconciliation of
existing category evidence and discovery checkpoints; and an explicitly authorized
API/UI cutover. Migration alone enables none of these. No source limits or worker
concurrency values in the simulation are deployment instructions.

See the [capacity and validation report](reports/collection-freshness-foundation-2026-09-30.md)
and the [complete synthetic simulation output](reports/collection-freshness-capacity-2026-09-30.json).
