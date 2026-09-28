# Market Value B — review baseline

The completed collector-facing page is **One Piece Market hero → Market movers
→ Most valuable cards → Compare releases → Release market**.

The hero replaces the generic CPI headline and old Market Snapshot/structure
panels. Performance displays server-authored, coverage-neutral price movement;
tracked value is a partial JPY basket sum, not market cap. Missing movement stays
unavailable, with coverage/history explanations instead of fabricated zeroes.
Persisted dates remain visible. Charts use the CARDPIRATE ATLAS sharing identity.

Movers request separate server-ranked gainers, losers and impact cohorts for the
latest published daily step. Impact emphasizes signed JPY basket contribution.
Most Valuable requests six exact physical prints and preserves server ordering,
including sibling printings. Both sections use full artwork and exact print links.

Comparison starts empty, accepts at most four census-eligible releases, and
supports 7D only. Each selected release supplies its own server performance
series; incompatible periods are rejected rather than interpolated. Failures
stay local. Release Market preserves census ordering, shows coverage and partial
tracked value, searches the entire loaded census, and progressively reveals rows.

One release-summary request supplies the hero selector, comparison eligibility
and release list. Initial load makes four Market Value requests. Scope changes
make three; adding a comparison makes one; removal/search/expansion make none.
The page has no old `/analytics/index`, index movers/composition, or
`/analytics/market/overview` request wiring.

## Reviewed scope

All production changes are under `apps/web/src`. No backend, migration,
methodology, writer/scheduler, staging data or unrelated card-detail files changed.
Shared multi-select additions support disabled explanations and a selection cap.
The existing print-chart palette was extracted without changing its colors or
behavior. PR #18 and its branch remain untouched.

Implementation commits separate hero/contracts, exact-print discovery, and final
page/comparison integration with their coupled tests. Persistent unrelated local
evidence is deliberately excluded from staging.

## Local validation

- 91 focused B1/B2/B3 tests and 321 relevant shared regressions: **412 passed**
  across 28 suites in the final combined run.
- Real staging inspection then exposed an empty Gainers cohort on a non-flat
  negative day. Its message now says “No gainers” instead of claiming no cards
  moved. Two new regressions cover empty directional cohorts; 140 affected
  tests passed after the correction, including all **93 focused tests**.
  TypeScript and touched-file ESLint passed again.
- TypeScript, touched-file ESLint, secret checks and diff whitespace checks pass.
- Prior B3 fixture browser validation: 70 checks at 1500px and 390px, covering
  responsive layout, artwork containment, charts/tooltips/watermarks, eligibility,
  stale responses, failure states, scope navigation and request isolation.
- Disk before publication: 13 GB free, 43% free. No local Docker stack created.

Fixture checks are not a substitute for the subsequent immutable Preview audit.
The manual-review handoff must record actual PR CI, exact deployment SHA, real
staging API/artwork, native Google Chrome checks and network counts.

## Existing unrelated local test debt

`apps/web/src/app/cards/code/[cardCode]/page.test.tsx:135`,
`A. multi-print family > N. keeps an unpriced printing honest`, fails at:

```tsx
expect(screen.getByText(/Index unavailable/i)).toBeInTheDocument();
```

Both this tree and an untouched archive of staging commit
`e2e57b30ffc6d00eb068f92aae8256c10d11c4dd` produced 13 passed / 1 failed.
The archived and current test match SHA-256
`0c05411852c285e43f755f9226111e28aebf9e2704a0de564d59c345c8357e96`.
Neither the test nor its page was modified. This report makes no claim that the
entire frontend Vitest suite passes.

The new PR must remain open and unmerged for human review. No change to PR #18.
