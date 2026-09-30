# Opt-in collection freshness adapters

Dependent on PR #31 at `2af417e249e0fdf3d9399cef30fb09b6ae154356`.
This slice supplies collector integration and PSA10 storage, **not a public
freshness rollout**. No scheduler, service command, budget, or deployment setting
is activated. The active daily Market Value coordinator is unchanged.

## Shared boundary and packaging

`services/api` now builds the `opcg-collection-services` Python distribution.
Its `app.services.freshness_integration` boundary calls the existing PR #31 policy,
planner, queue, request admission, and completion code against the same ORM models.
Both collector images install that package and `opcg-source-identity` from the same
repository revision. There is no copied scheduler and no internal network API or
new authentication surface. Database credentials and roles remain those of each
caller; imports do not connect, migrate, schedule, or enable budgets.

The package dependencies are SQLAlchemy, psycopg, pydantic-settings and the local
source identity package. Collector-specific browser/parser dependencies remain in
their existing requirements. API deployment continues using its existing source
layout. Discovery workers can install the same distribution when their future
queue consumer is deployed; the optional transport hook itself uses duck typing
and does not import `app` or change the worker's current packaging.

Migration `9d2b7a1c4e60`, after `7c9e4a12b6d0`, adds the nullable JSON field
`freshness_attempts.category_outcomes`. Additive migration `c4e8a1d7b902` follows
it and adds nullable `freshness_price_states.consecutive_failures` (integer,
constrained to 0–8) and `retry_not_before_at` (UTC timestamp). Neither migration
changes existing data or enables dispatch. The foundation migration is unchanged.
The shared package now requires **all three migrations before opt-in execution**;
none has been applied outside disposable local tests.

Selective backup version 18 carries category retry state. Versions 12–17 remain
readable. Missing fields in v16/v17 become NULL (no category retry history), with
no inferred successful check or renewed price. The first subsequent failed check
starts the bounded streak; migration does not reconstruct old attempts. Version
18 round-trips gates and streaks. Restores still disable admission and invalidate
claims, preserving deadlines and category retry history. Older runtimes must
refuse v18 archives rather than silently discard retry state.

## Supported opt-in execution

Existing single-mapping, approved-mapping, validation-only, discovery and cron
invocations retain their existing behavior. New paths, for a separately authorized
future activation, are:

```
python -m snkrdunk_collector.collect --due-work
python -m yuyutei_collector.collect --due-work --shard-count 9 --shard-index K
```

`K` is the existing index 0–8; routing remains `mapping_id % 9`. Legacy mapping
filters and validate-only cannot be combined with these commands. SNKRDUNK holds
its existing `collection_lock` for the entire drain, uses `pinned_session`, and
checks ownership before admission, evidence writes, result writes and commits.
Queue ownership supplements that lock; no additional live concurrency is added.

A caller first invokes `plan_product(session, mapping_id, source_name,
high_interest=..., request_bound=...)` in its own short transaction. Product
interest and a conservative request upper bound must be supplied explicitly.
Planning uses one approved exact-print mapping, including SNKRDUNK's manual
verification gate; it never approves candidates or creates separate grade mapping
lists. Replanning does not reset progress. `plan_refresh`, discovery-scope,
print-discovery and validation planners remain available from the shared package.
No CLI automatically selects interest or enables a source budget.

The shared drain claims each next product just before execution, in bounded chunks
(default 70), and takes another chunk immediately while the existing runtime bound
allows it. It reserves enough remaining runtime for the existing per-product
watchdog. Unstarted tails remain pending, rather than sitting in a prefetched
batch until lease expiry. Existing per-mapping pacing remains. Empty queues,
missing/disabled admission, unaffordable reservations, pauses, or another
consumer's fairness lane cause exit. A later authorized invocation resumes due
work without an embedded eight-hour sleep.

Discovery/validation turns yield to their responsible consumer; collectors do not
steal them. Timely draining of all lanes is an activation dependency. Category
absence/parsing failure retains the outstanding evidence deadline and uses the
shared durable retry policy below.

## Requests, evidence, and atomic completion

An `Attempt` admits each browser request, including warm-up/helper pages,
subresources, history and artwork. Even third-party artwork is charged to the
source conservatively. Service workers are blocked in opt-in contexts and
WebSockets are refused. Browser routing fetches disable transport retries and
redirect following. **Browser redirects fail closed** because interception of
redirect chains is not guaranteed; support for any required redirect must be
reviewed before activation. Artwork API requests also disable redirects/retries.

Each grant commits before I/O and rechecks lease, mapping ownership, source pause,
and the reserved request bound. Admission of a product does not authorize later
requests after a pause. HTTP 403/429 pauses the source immediately; rendered
SNKRDUNK challenges also pause it before further work. Missing costs/limits never
mean unlimited access. Charges count dispatch grants, including requests with
unknown delivery after transport errors; they are conservative accounting, not
proof of source receipt. Crash recovery retains PR #31's full reservation charge.

SNKRDUNK raw HTML is committed before classification/extraction, including helper
and history evidence. Yuyu retains its existing durable raw-before-parse path.
The result transaction fences ownership **before** invoking existing identity and
price writers, then completes the queue claim before committing. A lease or
singleton loss or completion refusal rolls back domain writes. Raw evidence can
survive that rollback. Identical completion replay skips the writer; saved-evidence
replay cannot become a new successful check. Historical sales stay evidence-only
with the source transaction dates; no historical sale is redated as a current ask.

`Attempt.http_get` is injectable into existing SNKRDUNK discovery/sitemap adapters
as `admission=attempt`; `run_probe(..., admission=attempt)` supports Yuyu browser
traffic. HTTP redirects are returned without following them; callers must validate
and separately admit any follow-up, retaining their own pacing. HTTP clients must
have transport retries disabled. These hooks do not own candidates or checkpoints.
For an eventual discovery consumer, call `begin_result`, write candidates and the
existing checkpoint, then `finish(CaptureResult(..., resume_cursor=...))` in the
same transaction. The queue cursor points to the authoritative discovery run.
Continue using `load_latest_checkpoint` and `reconcile_with_sitemap`; never replace
them with a queue-only checkpoint or restart from an empty cursor.

Legacy traffic does not acquire new budgets in this inactive slice. Before any
budget is enabled, **all traffic for that source** must be cut over or stopped,
including legacy validation/discovery and helper traffic. Mixing unmetered legacy
jobs with admitted jobs would invalidate source-wide accounting and is unsupported.

## PSA10 storage and independent category outcomes

SNKRDUNK's existing product extractor reads the exact `PSA10` chip inside the
product's own condition picker. It does not read PSA9, BGS, ARS, recommendation
prices or a separate page. A unique positive integer JPY asking price is required;
duplicate chips, conflicting price/waiting markers, malformed values and missing
containers fail closed. The existing raw A–D minimum and identity/approval,
artwork, independent card-code authority, and release checks are reused unchanged.

| Category | Stored price_type | condition_label | Evidence |
| --- | --- | --- | --- |
| Yuyu raw | `sell` | NULL | Existing agreed sell price |
| SNKRDUNK raw | `floor` | Winning A/B/C/D | Existing raw minimum |
| SNKRDUNK PSA10 | `psa10_asking` | `PSA10` | Exact PSA10 lowest ask |

Both SNKRDUNK observations share the product snapshot, capture timestamp and
mapping/print/source lineage. Neither category's missing price prevents a valid
price in the other. PSA10 is **not** a `floor` observation. It is absent from the
existing raw index input/evidence registry and cannot qualify a print for raw
Market Index snapshots consumed by Market Value/CPI. No valuation arithmetic,
source eligibility, primary instrument registry or daily coordinator was changed.
No price-table migration is needed: the existing typed series columns accommodate
the distinct signature.

`CaptureResult` supplies product outcome, snapshot ID, category observation IDs,
explicit no-listing categories and category outcomes. Persisted category outcomes
are `captured`, `no_listing`, `absent`, or `parsing_failure`; product-level failures
include `source_denial`, `identity_refusal`, and `transient_failure`. An absent chip
is not explicit no-listing. Only the exact awaiting marker establishes no-listing.
A failed identity check invalidates the product, including both grade categories.

`price_facts` returns detached category facts for API readers: policy version,
attempt time, successful check time, valid capture time, observation ID,
availability, category/product outcomes, next due, expiry and freshness verdict.
All categories use PR #31's standard 24-hour or high-interest 4-hour target, with
its execution headroom (one hour by default). No-listing updates check/availability
but retains the old price timestamp; absent/malformed/failed checks update neither.
Successful checks, captures, transaction dates and calculation/publication times
remain distinct. Availability must be displayed alongside any retained old price.

## Remaining rollout work and holds

- Separately authorize migration, package deployment and opt-in service commands.
- Review product-interest inputs, explicit source request bounds/budgets and
  measured latency/cost. Resolve any required redirects, then measure with an
  authorized source test. No live capacity claim is made here.
- Integrate discovery/validation queue consumers with their existing checkpoint
  transactions and all fairness lanes. The transport hooks are ready; those jobs
  are not automatically scheduled or activated by this PR.
- Reconcile existing observation/category evidence before planning large backlogs;
  no backfill or freshness-by-recalculation occurs here.
- Wire the API/UI current-price paths to the shared facts and graded series,
  including clear category/availability labels. Current public endpoints and
  source-specific freshness labels have not been cut over.
- Preserve actual contributing observation IDs/times for derived freshness before
  API/UI publication. Calculation or publication time is never a freshness origin.
- **Yuyu promotion-policy discrepancy and Batch 2 approval hold remain open.**
  This change does not alter promotion semantics, approve mappings/candidates,
  bypass the hold or change the active daily Market Value coordinator.

## Validation and capacity evidence

Tests use fixture/mock transports and disposable local PostgreSQL. They exercise
multi-chunk and interrupted-run tails, independent raw/graded outcomes, identical
source/grade policy, nine-shard routing, singleton contention/loss, per-request
pauses and bounds, transaction rollback, replay, backup compatibility and migration
upgrade/downgrade. Existing checkpoint, collector and backup regressions are run
locally; CI runs the full suites and builds the collector images.

The capacity-shortage test is **synthetic**: a five-request source budget and two
five-request product reservations permit one mocked capture and leave the other
product's original deadline visible. This is not a measured source limit or
throughput recommendation. No live capacity measurements are reported.

During initial test development, a discovery-yield test lacked a browser mock and
unexpectedly attempted outbound requests until its local reservation stopped it.
This violated the requested mock-only boundary. It used disposable local data,
not staging/production credentials or databases. An unconditional browser guard
now fails any unmocked browser invocation in this integration suite; the corrected
test fixes its fairness-cursor assumption. Subsequent integration runs use mock
transports. No source result from that accidental path is used as validation or
capacity evidence.

Local validation results (overlapping runs, not a summed total):

| Focused run | Result |
| --- | --- |
| Adapter PostgreSQL cases, in focused groups | 19 passed |
| Foundation queue and additive migration | 26 passed |
| SNKRDUNK extractor, PSA10, writer and CLI regressions | 121 passed, 4 subtests |
| Existing SNKRDUNK PostgreSQL singleton tests | 32 passed |
| Yuyu writer, raw-before-parse and discovery probe | 79 passed, 3 subtests |
| Existing Yuyu batch/shards/raw/write baseline | 87 passed, 15 subtests |
| Discovery/sitemap/checkpoint regressions | 69 passed |
| Affected backup and backup-version regressions | 61 passed |
| Shared package | Wheel built successfully |

Before publication, read-only project configuration confirmed Railway PR deploys
and bot PR environments are disabled, and all repository triggers target
`staging`. The connected Vercel project targets `staging`, root `apps/web`, with
no deploy hooks. A separate minimal commit excludes only
`feature/collection-freshness-adapters` under `git.deploymentEnabled`, preserving
all existing exclusions. GitHub workflows build/test; they do not deploy. Both
PRs remain unmerged. No platform configuration was changed.

The first CI run passed the full backend/worker suites, frontend and image builds.
The new collector CI job initially supplied PostgreSQL 18 to Yuyu tests which
explicitly require 16; that job failed and canceled its SNKRDUNK matrix sibling.
The follow-up uses PostgreSQL 16 for collector tests, disables matrix fail-fast,
and adds image-build import smoke checks for both opt-in adapters. Backend tests
continue using their existing PostgreSQL 18 service. The sitemap admission
argument also remains after every existing positional constructor argument;
its affected regressions passed (23 tests).


## Pre-rollout correction: durable category retries

Freshness remains `current-price-v1`: 24 hours standard, 4 hours high-interest,
independent of source and category. Retry eligibility is a separate scheduling
fact; it never changes the age or expiry of evidence. With the default one-hour
execution headroom:

- **Confident absence:** a coherent, unambiguous product picker with the category
  absent schedules another check after 23 hours standard / 3 hours high-interest.
  It does not mean explicit no-listing. A missing picker, unlabelled/duplicate
  chips or incomplete picker structure cannot establish confident absence.
- **Parsing/transient failure:** the category's durable failure streak schedules
  15m, 30m, 1h, 2h, 4h, 8h, 16h, then at most 23h between attempts for standard
  products. High-interest retries cap at 3h. The cap is the policy target minus
  configured execution headroom, not a capacity or grade exception. The counter
  saturates at 8. Page-less transient failures advance each unresolved category.
- **Recovery:** a valid capture or explicit no-listing clears only that category's
  streak/gate. Confident absence resolves parsing uncertainty and resets its own
  failure streak, while retaining all old price/check/availability facts. Success
  in the other category never resets an unresolved failure streak.
- **Product dispatch:** effective eligibility is the earliest of each category's
  `max(next_due_at, retry_not_before_at)`. The original minimum evidence deadline
  remains in `work.next_due_at`, so retries do not conceal overdue evidence.
  Planning new demand or increasing interest recomputes eligibility without
  postponing an earlier category deadline. A product fetch evaluates all demanded
  categories once, even if one retry was originally later. Such an opportunistic
  check can recover that category early; its own outcome sets its next retry.
- **Ownership/admission:** the same transaction fences and commits category state,
  observations and claim completion. Duplicate completion is idempotent. Denial
  pauses, identity review blocks, source budgets, lane fairness, runtime bounds
  and discovery checkpoint ownership remain unchanged. No Celery retry layer is
  involved. Non-price discovery scheduling is unchanged.

`price_facts()` now also returns per-category `retry_not_before_at` and
`consecutive_failures`. Existing `next_due_at`, attempt/check/capture times,
category outcomes, availability and policy version retain their meanings.
API/UI consumers still need the wiring listed above; this correction does not
publish customer-facing freshness or activate collectors.

### Offline advancing-clock reproduction

Before changing scheduling code, the harness ran on head
`05e54a2193df2f0057ace7cfd787eebcc8197be6` using disposable localhost PostgreSQL,
synthetic outcomes, a fresh worker/session on each dispatch and duplicate result
delivery. Dispatch advances in 15-minute steps over **inclusive [0h, 48h]**
(193 opportunities). These are **simulated capture/dispatch counts, not source
throughput measurements**. Budgets in the fixtures are synthetic; live budgets
and concurrency were not changed.

| Standard-interest scenario | Before captures | Corrected captures | Corrected capture hours |
| --- | ---: | ---: | --- |
| Raw valid / PSA10 persistently absent | 193 | 3 | 0, 23, 46 |
| PSA10 valid / raw persistently absent | 193 | 3 | 0, 23, 46 |
| Raw valid / PSA10 persistent parsing failure | 193 | 8 | 0, .25, .75, 1.75, 3.75, 7.75, 15.75, 31.75 |
| PSA10 valid / raw persistent parsing failure | 193 | 8 | same |

Before correction, all four cases captured every 15 minutes through hour 48.
After the eighth parsing failure at 31.75h, the next eligible retry is 54.75h;
unavailability is never permanently abandoned. Corrected high-interest absence
also runs for 48 simulated hours: 17 captures at hours 0, 3, …, 48 for either
missing category. Additional simulations cover recovery, absence appearing later,
interest escalation bringing another category due during a retry delay, new
category demand, worker restart, duplicate delivery and archived retry state.
The mock-browser adapter tests independently reproduce the 3/8 capture results
through real extraction and persistence, with one product navigation per capture.

The mixed simulation has three affected products, three ordinary products, two
first-coverage products and two discovery scopes, with one dispatch slot per
15-minute tick. Six products have prior evidence; all ordinary jobs begin due.
No test raises the source budget or changes lane scheduling:

| Cohort | Before dispatches | Corrected dispatches |
| --- | ---: | ---: |
| Affected products | 184 | 9 |
| Ordinary refresh | 3 | 8 |
| First-coverage products (including later refreshes) | 2 | 6 |
| Discovery scopes | 4 | 6 |

The corrected workload uses 29 of 193 slots. All products/scopes receive first
service within 2.5 simulated hours, with subsequent intervals at most 25.5 hours
under this deliberately restricted dispatch schedule. Those delays are visible
capacity limitations of the simulation; this is not proof of real catalogue
capacity or guaranteed deadline attainment. Existing lane admission can still
miss deadlines under insufficient capacity.

The scheduling/adapter test modules share `tests/freshness_offline.py`, which
blocks real HTTP transports, external DNS/sockets, browser startup and external
PostgreSQL connections; mock transports and the explicitly configured disposable
localhost DB are allowed. Migration tests use uniquely named disposable databases
on that same instance. The handoff still requires separately authorized migration,
API/UI/discovery work, measured capacity validation and activation. The exact
branch deployment exclusion, daily Market Value coordinator, Yuyu promotion-policy
discrepancy and Batch 2 approval hold remain unchanged.

Correction validation: 155 focused scheduling/adapter/policy/capacity and affected
backup regressions passed; the final two-case follow-up passed (one strengthened
mixed-population case and one new missing-picker case). This is 156 distinct API
cases across overlapping runs. SNKRDUNK extraction regressions: 39 passed. Full
suite validation is delegated to PR CI. Existing test-library deprecation and
fixture-key warnings do not affect these results.
