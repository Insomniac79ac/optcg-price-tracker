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

## Documentation-only scope and verifier timeouts (2026-10-08)

Collector rollout and RAW DDL are already opt-in per PR: they act only on
`deployment_verification.collector_services` / `raw_dependency_migration` in
the PR's manifest. `scripts/staging_delivery_scope.py` adds a second, file-based
guard that can only remove those two steps, never add work. It skips them only
when every path changed by the merge (`merge^1..merge`, renames detected) is
`docs/agent/handoff/**` or a `docs/**/*.md` file outside `docs/agent/evidence/`,
plus the per-PR manifest declaration, and that manifest requests neither
rollout nor migration. Paths read by delivery, migration, verification or state
code (`STAGING_MISSION.json`, `CURRENT_STATE.yaml`, `docs/agent/evidence/**`)
are never documentation. Renames crossing the allowlist, unknown statuses, an
empty or undeterminable change set, or an unreadable manifest run the full
delivery unchanged. Verification and state regeneration always run; the
decision and file list are written to `latest-delivery-scope.json` and embedded
as `delivery_scope` in `latest-staging-delivery.json`.

Read-only verifier GETs retry only a socket timeout, at most twice (2s, 5s
backoff), and the caller applies the identical assertion to the response. HTTP
errors, redirects, content and invariant failures are never retried. Retries are
recorded as `get_timeout_retries` in the delivery receipt. PR80's CI verify step
failed on one such timeout among ~452 sale-exclusion GETs; an identical local
rerun passed at 2026-10-08T05:53:31Z.

## Collector variables and skipped API builds (2026-10-08, session 5)

A plain `railway variable set` on a GitHub-connected collector rebuilds it from
the branch head and replaces the verified `railway up` upload, losing its
exact-commit marker (snkrdunk-collector 0da9274b at 07:25Z and 518080ff at
08:36Z). The verified upload f3286a0a was restored at 09:10Z (18f66771).
`scripts/collector_variables.py` is now the only supported path. It accepts
only the RAW writer keys and `APP_ENV=staging`. It requires the active
deployment to carry the exact-commit marker. It stages with `--skip-deploys`
and proves no deployment started. It then redeploys the newest marked,
redeployable deployment with the identical image digest, because Railway
refuses to redeploy the active one. Finally it waits for SUCCESS and checks
schedule, start command, digest and read-back values. A repository scan test
fails if any other tooling sets Railway variables. The admin password-hash
helper is exempt only while it sets nothing but `ADMIN_LOGIN_*` keys with
`--skip-deploys`, which never triggers a rebuild. An explicit collector refusal
in it is deferred to the next collector release, because `services/api` is a
collector image input and editing it now would break verified-upload
continuity. `scripts/snkr_storage_canary.py` is the re-pinned canary helper on
this path.

Manifests may keep `api_sha: merge`. The verifier resolves it from the merge
diff, the API service's Railway watch patterns, and Railway's record for the
merge commit:

- A watched change requires a build at the merge. A SKIPPED record fails as a
  missing build.
- An unwatched change requires a SKIPPED record. The active API must stay on
  its previous SHA, with the watched tree byte-identical to the merge; any
  build at the merge fails as unexpected.
- An undeterminable diff, empty patterns or negated patterns demand a build.

The decision is recorded as `api_expectation` in the delivery receipt. PR81
(f4b632d) replays as `skip` on 1b1b64d.

PR83's delivery (852ccdc) showed every Railway service SKIPPED and the main
verifier resolved `api_sha: merge` correctly. It still failed, because the SNKR
component check read `merge` from the manifest itself and expected the API at
head. The verifier now exports its resolved API SHA to repository checks as
`STAGING_RESOLVED_API_SHA`. The SNKR check uses it only for `merge` and only
when it is a full SHA, otherwise head. Its API-input continuity check still
applies. A read-only replay against 852ccdc passed (SNKR runtime 18f66771 on
1b1b64d).

### Image reuse for settings-only redeploys (2026-10-08, session 6)

Build logs show that `deploymentRedeploy(usePreviousImageTag:false)` schedules a
build every time. 0edb80c6 used the cached layers and kept its digest; shard-6
954d0f1d ran a full `pip install` rebuild and changed it.
`collector_variables` now redeploys with `usePreviousImageTag:true`. Railway's
docs and CLI do not describe that flag, so its effect is not trusted: every
digest, marker, schedule, active-deployment and read-back check still applies.
`--expect-digest` pins the original verified image, and a different active image
is refused before any change. Any post-redeploy failure restores the previous
effective values on the original verified upload, re-verifies it and refuses,
or reports `ROLLBACK FAILED`. `--restore` puts the original image back
explicitly. The build-log line count is recorded as evidence only.

### Collector continuity follows the import graph (2026-10-09, session 7)

Both collector images `pip install services/api`, but that installs only the
`app` package and its package data, and a collector process executes only the
`app` modules it can reach by import. `scripts/collector_runtime_inputs.py`
derives that set from Git objects at the installed component and at head
(union), starting from every non-test module in the collector directory. It
follows transitive and function-local imports and package `__init__` chains.
Both SNKR and Yuyu component checks use it through `collector_continuity`.

A change still fails continuity when it touches:

- the collector directory, its Dockerfile or `packages/opcg_source_identity`;
- an imported `app` module at either commit, including one a new import adds;
- any non-Python file under `services/api/app` (package data);
- `services/api` packaging or requirements files.

`services/api` files that collectors never install (`alembic/`, `tests/`,
`scripts/`, `data/`, API service files) and unimported `app` modules no longer
make an API change a collector release. The check fails closed: an unreadable
commit, unparsable reachable module, unresolved `app` import or any dynamic
import (`importlib.import_module`, `__import__`, etc.) falls back to the
previous whole-directory path set. The only named exceptions are the untracked
deploy-time markers `app.services.collector_build` and `*_delivery_revision`,
which carry only the deployed revision and have no Git source to compare.

Collector Railway watch patterns cover only their own directory and
Dockerfile, so an API merge has never rebuilt a collector. The narrowing
removes only the verification refusal. It does not change any image,
deployment, schedule, budget or writer. Evidence:
`evidence/collector-continuity-preflight-20261009.json`. The static set was
compared with the `app` modules actually loaded by importing every collector
module: SNKR 58 loaded, 62 static; Yuyu 65 loaded, 73 static; none missing.

### Branch previews disabled (2026-10-10)

`apps/web/vercel.json` now sets `git.deploymentEnabled` to `{"**": false,
"staging": true}`. Vercel deploys a branch when any matching rule is true
(minimatch), so only `staging` builds. `verify_staging_delivery.py` and the
state generator read only the project's `production` target, which is the
`staging` branch, so delivery is unchanged. Previews were already behind
Vercel Authentication (`ssoProtection: all_except_custom_domains`): an
unauthenticated GET of a preview URL answers 302 to Vercel SSO. No Preview
environment variable applies to an arbitrary branch, and `ADMIN_TOKEN` is
Production-only. Branch-scoped Preview variables remain for five legacy
branches. Vercel reads `vercel.json` from the pushed commit, so a branch
created before this change still builds a preview until it is rebased.

### Collector releases roll out one at a time (2026-10-10, session 8)

`deploy_staging_collectors.py` previously uploaded every requested collector
at once and polled them together, with no automatic rollback. It now releases
them **one at a time**, in manifest order:

1. **Before any change**, for every requested collector: the active deployment
   must be SUCCESS and carry an exact-commit marker. Its image digest, commit,
   schedule, start command and writer flags are recorded, and
   `collector_variables.original_source` must find a redeployable copy of that
   exact image. A collector without a proven rollback refuses the whole
   release before any upload.
2. A forward release may start only between 06:00 and 23:00 UTC, so the
   180-minute delivery job cannot reach the 02:00-06:00 UTC busy window.
3. Each collector is uploaded only in its own safe slot: at least 5 minutes
   after a scheduled fire, at least 8 minutes before the next, and with no open
   `freshness_attempts` claim of its own (read-only query).
4. It is followed to SUCCESS (one bounded build retry and one watched-snapshot
   redeploy, as before). Then marker, SUCCESS, schedule, start command and
   writer flags are re-verified before the next collector is touched.
5. **Any failure** restores every collector touched so far, newest first,
   through `collector_variables.restore` to its recorded original image and
   flags, verifying each. Rollback slots ignore the busy window. A success
   receipt is never written; the error states whether rollback was complete.

The receipt (`schema_version` 2) adds `sequential`, each collector's
before-image, commit and flags, and the per-collector after-digest and
verification time. The delivery jobs' timeout is now 180 minutes.

### Collector-directory merges deploy every collector at once (2026-10-10, session 8)

Railway's watch patterns for the collectors are their own directory and
Dockerfile, for example `services/yuyutei_collector/**` and
`deploy/railway/yuyutei-collector.Dockerfile`. A merge that changes those
paths therefore makes Railway's GitHub integration build and deploy the merge
on **every** matching collector at once. Those builds carry no exact-commit
marker.

This happened with PR #96 (419210d):
- At 09:57:17Z, all ten collectors were rebuilt from GitHub in parallel.
- The sequential rollout then refused before any upload ("Collector
  identity/scheduled due-work configuration changed"), because the active
  deployment was no longer a verified upload.
- All ten were then restored, one at a time, to their verified 05f099d images
  through `collector_variables.restore`.
- The first restore attempt aborted before making any change: a marked
  SKIPPED record with no image stopped the recovery scan.
  `original_source` now skips such records.

**Rule until the watch-pattern trigger is resolved.** Keep collector code
changes out of the merge that requests the rollout, so that merge builds
nothing on GitHub:
1. Land the code with a manifest that requests no rollout. This is not
   possible today, because continuity then fails.
2. Or, as was done here: after a code merge has already landed, deliver it
   with a follow-up PR that touches only `scripts/` or `docs/`. Its merge
   commit contains the code, and the sequential rollout uploads it, verified,
   one collector at a time.

Disabling GitHub auto-deploys on the collector services would remove the
trigger. That is a staging infrastructure change for a later session (AMBER),
because the collectors are only ever delivered by `railway up`.

**PR edits re-run delivery.** Editing a PR's title or description after
opening it fires a `pull_request: edited` CI run. If the PR has merged by the
time that run's delivery job holds the lock, the job takes the replay path and
re-runs the collector rollout for the merged commit. For PR #95, a description
edit at 08:04Z caused a second rollout of 05f099d from 09:00 to 09:29Z. Every
upload came back SKIPPED and resolved to the deployments that were already
active, so no collector was redeployed. It left marked SKIPPED records and held
the delivery lock until 09:40Z. Do not edit a delivery PR after
opening it; comment instead.

### A failed merge poll no longer drops the rollout (2026-10-10, session 8)

PR #97's delivery job armed native auto-merge at 11:34:08Z and then polled
the PR. One poll answered `HTTP 504` at 11:42:38Z, and `bash -e` failed the
job. The cleanup step read `merged: false` and disarmed auto-merge, but
GitHub merged the PR at 11:42:44Z anyway. Staging therefore held 3d8421b
(PR #96's per-turn browser code) with **no rollout**: the collectors stayed
on their verified 05f099d images, and no collector was rebuilt, since the
merge touched no watch path (each collector gained one SKIPPED record).

The merge-wait loops in `ci.yml` and `staging-delivery.yml` now treat a
failed or unparsable PR read as one failed poll. They retry within the same
120-poll (30-minute) budget. Every successful read is still checked for
head, merged and open state exactly as before, so a closed PR or a moved
head still fails. Arming and disarming are unchanged.

**Remaining race (not fixed):** disarming auto-merge after a failure can
lose to a merge already in flight. If a delivery job fails while its PR
still merges, staging holds the code with no rollout. Recover with a
follow-up PR that touches no collector watch path, as was done here (PR #98
re-requests the same sequential release). Do not re-run the failed job: it
would replay a merge it no longer owns.
