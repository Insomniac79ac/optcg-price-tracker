# Canonical staging delivery

Mission: 2026-10-04, staging only. Production access and changes remain RED.

## Provenance and reconciliation

The initial live generator observation is `staging-state-283aa82e7283f0d3.json`.
Remote staging was `cabe07f7f3411e28d9d2bcb5629a57fb1b05e742`, while the canonical
staging alias served CLI deployment `dpl_BeBb7N2wXSMw68Ak45PUcn8qu92J`, source
`0211aa6715036f2457bbc130efe3bbeccb4af5d9`. Its `source` is `cli`, `gitSource` is
null, and its branch metadata is `fix/market-history-display`.

This is proven source divergence, not an inference from dates. The retained
Vercel upload manifest's content hashes match **577 frontend files** in that
commit, with zero differences. Only `.gitignore` and `.dockerignore` are omitted.
See [source comparison](evidence/staging-source-comparison-2026-10-04.json).

Two accessible local commits had never reached staging:

- `d01bbdb748571696777e858d08c34143f14dd103`: preserved the already deployed
  homepage positioning (originally a six-file uncommitted upload).
- `0211aa6715036f2457bbc130efe3bbeccb4af5d9`: separated JPY history rendering
  from performance eligibility, retained genuine missing dates as null markers,
  and preserved unavailable movement and Sets on the Move rules.

They are merged with original history/authorship, not reconstructed from prose.
The application changes cover homepage/share descriptions and `/analytics`.
No database, source mapping, pricing method, authentication policy, or immutable
publication changes are needed. `/api/version` additionally reports a compiled
`source_commit`, independent of mutable runtime environment overrides.

The dedicated Vercel project is `prj_DCbF7bhFkkAdfMQLZWvOQbxEDDhr`, root
`apps/web`, Git repository `Insomniac79ac/optcg-price-tracker`, Git production
branch **staging**, alias `optcg-price-tracker-staging.vercel.app`.
`gitProviderOptions.createDeployments=enabled`, `autoAssignCustomDomains=true`,
ignored-build command is null, and `lastRollbackTarget` is null. The existing
branch exclusions in `apps/web/vercel.json` are retained. This project's platform
`production` target is the business **staging** frontend.

## CI and policy contract

`engineering-gate` aggregates every existing CI job: secrets, prod-compose with
mock credentials, release checks, backend, worker, both collectors, five Railway
image builds, frontend build and Node tests, deploy-script/config checks, and
state-generator tests. Full frontend Vitest coverage and policy/verifier tests
are added. No failing test is skipped. The fixture fixes align legacy copy with
the existing UI and provide the established server-authorized admin context.

Every staging engineering PR supplies `docs/agent/STAGING_MISSION.json`. Explicit
impact entries cover every changed file once, declare effects, assess every RED
category, and bind the assessment to the exact binary Git diff SHA-256 (excluding
the manifest itself). File paths impose conservative AMBER floors; they are not
the sole classification input. Missing, stale or unknown evidence blocks merge.

- GREEN: complete, consistent metadata plus all required CI.
- AMBER: also bounded resource/route/dependency impact, persisted-write and
  source-request counts, rollback trigger/procedure, a resolvable Git recovery
  commit, retained validation artifacts, and referenced post-change checks.
  Successful safeguards require no human approval.
- RED: named human decision; automation refuses the PR. This includes explicit
  production, pricing/identity/security policy, published-history, and major
  product/brand effects, regardless of where files live.

CI runs the **base branch's** policy implementation after bootstrap. The initial
mission establishes that implementation under explicit mission authority.
Metadata is an accountable impact declaration, not a semantic proof that arbitrary
application code is safe. Review remains necessary for truthful impact assessment.

## Activation boundary — currently blocked

Observed GitHub facts: native auto-merge is false, staging is unprotected, and the
current app receives HTTP 403 `Resource not accessible by integration` both for
PATCH repository `allow_auto_merge` and PUT staging branch protection. These are
platform permissions, not a request for intermediate mission approval. Do not
use a PAT or write-token workaround.

A repository owner must enable **Settings → General → Pull Requests → Allow
 auto-merge** and configure **staging only** to require `engineering-gate`, require
branches to be up to date, disallow force pushes/deletion, and enforce checks for
administrators. Merge commits remain the established merge method. This does not
change main or any production destination.

Before setting `STAGING_AUTONOMY_ENABLED=true`, provision the `staging-delivery`
GitHub environment with **staging-only** credentials named `STAGING_RAILWAY_TOKEN`
and `STAGING_VERCEL_READ_TOKEN`. Do not copy an account/team token that can access
production. Existing credential capabilities could not be inspected or installed:
GitHub secrets administration is also HTTP 403. If isolated provider access is
unavailable, keep activation disabled and obtain a human security decision; do
not broaden credential policy to make the workflow run.

No production secret names or destinations are referenced by these workflows.
They cannot run delivery for main, forks, or PRs targeting anything but staging.
No provider deploy, variable, migration, collector or source-job mutation command
exists in them. Vercel's existing Git integration performs the frontend build.
Production infrastructure was not inspected, so this document does not claim a
new audit of its existing platform protections.

## Serialization and verification

The native GitHub concurrency group `card-pirate-staging-delivery` is acquired
**before** enabling the PR's native auto-merge, and held through merge, Vercel Git
build, baseline verification and state regeneration. Other autonomous mission PRs
can run CI, but cannot enable their merge while that job owns staging. Obsolete
pending jobs may be replaced; `cancel-in-progress: false` protects active work.
An unmerged auto-merge request is disarmed on job failure. The push verifier uses
the same group and exits for obsolete commits. GitHub-token merges do not produce
recursive push workflows, so the owning delivery job performs verification itself.

All future stateful staging migration/deployment workflows must use that same
concurrency group with no in-progress cancellation. This mission adds no migration
execution. Native concurrency does **not** fence manual dashboard deployments,
manual merges or out-of-band CLI actions; staging operators must use the delivery
path. Activation and the full autonomous end-to-end flow remain unproven while
the platform prerequisites above are unavailable.

The baseline `scripts/verify_staging_delivery.py` requires an exact frontend SHA,
expected API Git SHA (or `merge` in mission metadata), and migration revision.
It verifies canonical frontend build identity, API staging health and platform
identity, auth session HTTP success, homepage/card/Market browser rendering with
no runtime/hydration errors, catalogue bounds, duplicate exact-print mappings,
Yuyu sale history/current/index inputs, absent historical-gap rows and receipts.
State is observed again after the checks before a success receipt is written.
API runtime SHA may still be unknown; the verifier explicitly records that its
identity evidence is Railway's deployment metadata, not an independent byte hash.

Additional mission checks may be attached with `--check relative/script.py`.
They are trusted repository verification code, not downloaded PR-body commands.
CURRENT_STATE and content-addressed evidence are regenerated and uploaded as run
artifacts; no automatic commit loop is created. Failed checks never write a success
receipt. Natural source health/freshness deficits remain visible in state and are
not recast as healthy merely because frontend delivery succeeds.

## Recovery and expected commit

The expected canonical commit is the GitHub merge commit of PR #36 at its checked
head. Before verification, pin the returned merge SHA; Vercel's source SHA and
compiled `source_commit` must both equal it. Do not infer identity from a URL date.

The retained READY artifact `dpl_BeBb7N2wXSMw68Ak45PUcn8qu92J` and its byte-matched
source `0211aa6` are the recovery path. Restore only that artifact within the
pinned staging project if health, source identity or preserved behavior fails,
then repair forward through staging. No persistent database mutation occurs, so
no database restore is applicable. Do not revert away the recovered application
behavior or rewrite history. Automatic containment after a post-merge failure
still requires a verified recovery executor; the inactive workflow fails closed
and retains evidence rather than possessing a broad provider write token.

Official interfaces checked 2026-10-04, installed gh 2.88.0, Vercel 60.1.3,
Railway 5.62.1:

- [GitHub native auto-merge](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/automatically-merging-a-pull-request)
- [GitHub deployment concurrency](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments)
- [Vercel Git deployment](https://vercel.com/docs/git)
- [Vercel Git configuration](https://vercel.com/docs/project-configuration/git-configuration)
