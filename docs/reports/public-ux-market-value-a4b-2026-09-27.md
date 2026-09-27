# Public UX Market Value A4B — verification evidence

## A4A deployment gate

PR #22 was re-fetched OPEN, targeting staging, at exactly
`11ae9d6e0ee76a5522cb0abfbba83cf8973d99c1`, with its original three commits
and all 12 configured checks successful (CI run `36324478767`). It was merged
with the exact-head guard, producing
`a71a1d127636604f4012b42c0c01e4cc713fcb97` at
`2026-09-27T14:34:18Z`.

Normal Railway staging API deployment
`b5a10c10-02cf-43b7-b2ad-2f3f44ec1fa4` reached SUCCESS at that merge SHA.
No manual redeployment was triggered. `/health` returned 200 with staging
identity and database/Redis connected. Both live A4A routes returned 200:
Overall Sep-26 ¥262,279, 639/4,316 priced, 7D −3.9439823271…%; 59 release
summaries, nine available 7D and zero available 30D movements.

The A4B branch starts at this exact staging merge. PR #18 remains untouched.

## A4B scope and authority

Added public GET `/analytics/market-value/movers` and
`/analytics/market-value/most-valuable`; contracts and formulas are documented
in [market_value.md](../market_value.md#monetary-rankings-a4b).

Movers reconstruct only the selected persisted published daily step's two
snapshot dates through the frozen A2 engine. They check P/Q/C, ratio, dates,
publication decision/reasons, versions, membership and endpoint tracked facts,
then reconcile the full panel before ranking/truncation. Impact is signed
JPY change ranked by absolute JPY, not CPI equal-weight attribution.

Most Valuable reads only the selected scope's persisted as_of date. The full
positive-valued exact-print cohort must match persisted count and JPY sum,
version state and one coherent calculation instant before pagination.

The original global current-corrected membership digest and canonical
evidence serializers were extracted unchanged into a pure helper. No HTTP
call imports or invokes replay, persistence/writer, current valuation, source
fetching or collectors. SELECT-only tests cover both public routes, stored
image enrichment, forbidden calls, bounded dates and disabled autoflush.

## Staging read-only reconciliation

The local A4B service was exercised directly against staging, without deploying
A4B. Project/environment/service identity and current PostgreSQL TCP proxy
were verified before connecting. Credentials were held in memory and never
printed. PostgreSQL enforced `REPEATABLE READ READ ONLY` with a statement
timeout; a SQL guard allowed only SELECT/SHOW. Transactions were rolled back.

Alembic remained `d5f7a9c2e4b6`. Inventory remained 2,220 Market Value points:
37 Overall, 2,183 Release, 59 release scopes, through Sep-26 only. Full-table
fingerprints before/after were equal. Each comparison used 54 read statements.

| Scope | Sep-26 tracked basket | Published daily step | Full comparable P → Q | C |
| --- | ---: | --- | ---: | ---: |
| Overall | ¥262,279 / 639 prints | Sep-25 → 26 | ¥265,539 → ¥262,279 | 639 |
| OP-01 | ¥48,300 / 81 prints | Sep-25 → 26, genuinely flat | ¥48,300 → ¥48,300 | 81 |
| OP-05 | ¥480 / 4 prints | Unavailable; no published step | null | null |
| OP-17 | ¥14,780 / 20 prints | Unavailable; no published step | null | null |

All four Most Valuable cohorts reconciled to their persisted count and sum.
Their common valuation instant was `2026-09-26T20:01:03.890495Z`.
Overall daily delta was exactly −¥3,260; basket movement was
−1.2276916008571245655063851261020038487755094355255%.
Overall had three non-flat impact-ranked prints. OP-01 had an available flat
step with zero ranked movers, distinct from OP-05/OP-17's unavailable state.

Most valuable Overall was exact print 5687 (OP01-078, official p2, physically
in OP-04), ¥63,000. That cross-code example retained its authoritative release
FK rather than inferring membership from `card_code`.

## Validation boundary

Local regression suite: 600 passed, covering unchanged A4A, A2, A3
persistence/writer, CPI, backup/migration, release chronology and catalogue
contracts. PostgreSQL tests used isolated disposable local databases, never
staging writes. Focused A4B tests additionally cover public contracts, order/
ties/pagination, exact siblings, integrity refusals, coherent batches, real
NUMERIC precision and server-enforced read-only HTTP execution. The test
fixtures use mock prices and an A2-derived oracle; production contains no
hardcoded Sep-26 values.

No migrations, frontend, Market Value writes, scheduler, source fetch,
collectors, production access or Railway/Vercel configuration changes.
No local production Docker build. A4B must remain unmerged pending review;
Market UI is outside this tranche. The PR records the exact final test counts,
head SHA and actual GitHub CI run/check results.
