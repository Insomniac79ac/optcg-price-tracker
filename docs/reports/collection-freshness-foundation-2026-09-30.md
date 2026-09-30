# Collection freshness foundation — validation and capacity

Base: `e8d016c4bc62bed90402270bdebb8761895030e5` (`staging`).
Branch: `feature/collection-freshness-foundation`.
Contract: [shared freshness foundation](../collection_freshness_foundation.md).

## Synthetic capacity simulation

**Assumed timings; not measured live throughput.** Reproduce from `services/api`:

```sh
python -m app.simulate_freshness_capacity
```

The [saved JSON report](collection-freshness-capacity-2026-09-30.json) simulates seven
days with 5,000 source products: 500 high-interest and 4,500 ordinary, plus 250 daily
discovery scopes and 250 daily first-coverage scopes. Raw and PSA10 share each product
capture. Each capture is assumed to cost two requests. Headroom is one hour, giving
3-hour and 23-hour check cadences. Initial refresh deadlines are uniformly phased.
The simulation uses one serial worker for each scenario, immediate continuation
between processing chunks of 70, successful captures only, no denial pauses, and no
additional validation traffic. Seconds per capture include assumed pacing and
navigation time. These assumptions are optimistic and are not approved source limits.

This population offers 9,195.65 captures / 18,391.30 requests per day. Capacity is the
smaller of the assumed serial processing rate and the configured simulated request
budget. The targets never change when that capacity is insufficient.

| Scenario | Assumed seconds/capture | Assumed requests/day limit | Capacity upper bound, captures/day | Offered-load deficit/day | Deadlines met in simulation? |
| --- | ---: | ---: | ---: | ---: | --- |
| Yuyu serial | 6 | 24,000 | 12,000 | 0 | Yes |
| SNKRDUNK singleton | 20 | 20,000 | 4,320 | 4,875.65 | No |
| Yuyu constrained budget | 6 | 10,000 | 5,000 | 4,195.65 | No |

Each cell below is **outstanding due work / expired current prices / net backlog
change since the prior day**. Outstanding work includes a capture still in flight at
the sampling boundary. Discovery and first coverage contribute to due work, not to
priced-product freshness counts.

| Day | Yuyu serial | SNKRDUNK singleton | Yuyu constrained budget |
| --- | --- | --- | --- |
| 1 | 1 / 0 / +1 | 3,139 / 2,981 / +3,139 | 2,870 / 2,446 / +2,870 |
| 2 | 0 / 0 / -1 | 3,141 / 2,981 / +2 | 2,150 / 1,902 / -720 |
| 3 | 0 / 0 / 0 | 3,141 / 2,979 / 0 | 2,150 / 2,000 / 0 |
| 4 | 1 / 0 / +1 | 3,142 / 2,980 / +1 | 2,152 / 2,000 / +2 |
| 5 | 1 / 0 / 0 | 3,141 / 2,979 / -1 | 2,154 / 2,000 / +2 |
| 6 | 0 / 0 / -1 | 3,141 / 2,980 / 0 | 2,156 / 2,000 / +2 |
| 7 | 2 / 0 / +2 | 3,141 / 2,979 / 0 | 2,158 / 1,999 / +2 |

Coalescing bounds the number of product jobs. An overloaded queue can therefore
plateau while repeatedly missing price deadlines; a small daily net backlog change
does not establish sufficient capacity. The offered-load deficit and expired-price
counts expose that condition. Live timings, request costs, category coverage and
source limits must be measured/reviewed separately before activation.

## Validation scope

Validation uses synthetic fixtures, mock transports and disposable local PostgreSQL
16. No source-site request, staging database write, external job, deployment or
scheduler activation is part of this change. Existing collector files, discovery
checkpoint code, local artifacts, Yuyu approvals and promotion policy remain unchanged.
The only change to a Market Value test is its expected selective backup version.

The focused suite covers policy boundaries and derived input lineage; product/category
coalescing; unchanged recapture; no-listing and failures; concurrent ownership and
expiry; result replay; bounded fairness and tail resumption; source budgets and pauses;
Yuyu routing; additive migration upgrade/downgrade; and selective backup compatibility.
The migration is exercised on a uniquely named disposable database and compared with
the ORM schema. Existing backup and latest-price regressions are included.

| Local validation run | Result |
| --- | --- |
| Focused freshness, capacity, migration, backup, receipt-backup and latest-price tests | 96 passed |
| Final queue and migration verification after category/capture lineage review | 25 passed |
| Final unknown-policy-version refusal check | 1 passed |
| Worker discovery checkpoint resume and existing job locks | 32 passed |
| Yuyu nine-shard routing and collection telemetry | 92 passed, 15 subtests passed |
| SNKRDUNK existing fair selection and real PostgreSQL singleton ownership | 53 passed |
| Capacity report regression after request-cost accounting review | 2 passed |

The API runs overlap; these counts are not a summed total. PostgreSQL tests ran
without skips. Existing dependency warnings concern Starlette/httpx and test JWT
key length. New Python modules/tests are Black formatted; changed Python files
compile, the diff passes whitespace checks, and the repository secret scanner passes.

CI runs the repository's full suite after PR publication. Local validation stays
focused on the changed contract and the existing collector boundaries.

## Deployment exclusion audit

Read-only configuration inspection confirmed one connected Vercel project for this
repository: `optcg-price-tracker-staging`, root `apps/web`, Git target branch `staging`,
with no deploy hooks. The separate configuration commit disables only
`feature/collection-freshness-foundation` under `git.deploymentEnabled`, retaining
the existing explicit exclusions.

Railway project `glistening-peace` has `prDeploys=false` and
`botPrEnvironments=false`. Every repository trigger reported by its service
configuration targets `staging`; none targets this feature branch. The repository
has only the existing CI workflow, triggered by PRs or pushes to `main`; its jobs
build/test but do not deploy. No Railway settings or deployment triggers were changed.
A feature push and this PR therefore select CI without an application deployment.

Stop condition: the PR remains open and unmerged. Applying the migration, configuring
budgets, integrating collectors/APIs and enabling source admission require a later,
separately authorized rollout.
