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

## Per-PR mission files (2026-10-19)

Owner decision 2026-10-19 (ROADMAP item 22). The single shared
`STAGING_MISSION.json` made every DATA-lane PR conflict with the one merged
before it, and its hash covered a two-dot diff against the moving `staging` tip,
so any merge made every open mission stale. It is retired; nothing reads it.

- **Mission.** Each DATA-lane PR adds exactly one
  `docs/agent/missions/<name>.json` (name: the branch with `/` as `-`). It holds
  what describes this change: `mission`, `target`, `classification`,
  `red_decisions`, `impacts`, `safeguards`, `diff_sha256`, and in
  `deployment_verification` only `collector_services`,
  `raw_dependency_migration` and, for its own delivery, `yuyu_reader_component`
  / `snkr_component` (`merge` or a full SHA). No other mission file may be
  changed or removed.
- **Fleet state.** `docs/agent/STAGING_FLEET.json` holds what carries from one
  delivery to the next: `deployment_verification` (`api_sha`, `revision`,
  `checks`, components pinned to full SHAs, `yuyu_capacity_cadence`) and
  `operational_notes`. It may never request a rollout or migration. Only PRs
  that move the fleet edit it, and their impacts list it.
- **Hash.** `diff_sha256` covers `git diff --binary --full-index --no-renames` from the
  merge-base to the PR head, excluding the PR's own mission
  (`scripts/staging_mission.py digest`). Merging `staging` in does not change it
  unless the merge changes the PR's own lines; full index lines make it
  independent of the clone.
- **Gate.** `policy-gate` still runs the base branch's `staging_policy.py`. It
  finds the PR's one added mission, composes it with the fleet state at the PR
  head (`staging_mission.compose`, the old manifest shape) and runs the same
  `evaluate()`. Zero, two, changed or removed missions, a mission that sets
  fleet expectations, or fleet state that requests work is RED.
- **Delivery.** The scope step composes the merge's own mission
  (`staging_mission.py compose --base merge^1 --head merge`) into a temporary
  file that the RAW migration, collector rollout and verification steps read.
  A full delivery without exactly one added mission refuses. A documentation or
  PRODUCT merge with no mission uses the fleet state alone. The hand-merge
  `Verify staging merge` composes the same way; verifier `--check` scripts read
  `STAGING_MISSION_MANIFEST`, else the fleet state.
- **After a collector delivery or a migration.** The fleet still pins the
  previous component and Alembic revision, so the next staging merge must be a
  small DATA PR that pins `yuyu_reader_component` / `snkr_component` to the
  merge SHA and `revision` to the new single Alembic head in
  `STAGING_FLEET.json` (the old flow did this in whichever PR came next, with
  the same gap for a PRODUCT merge in between). Nothing enforces it before the
  merge; Verify staging merge fails on a stale pin.
- **Bootstrap and rollback.** The PR that introduced this was evaluated by the
  previous base policy and so carried one last `STAGING_MISSION.json`; the
  workflow uses the legacy path only while the base branch has no
  `scripts/staging_mission.py`. It also adds its own mission file, so a
  delivery after its merge composes. Rollback is a native revert PR plus one
  mission file (the new gate admits it). The revert restores the previous
  `STAGING_MISSION.json`, which the restored old delivery acts on, so the gate
  refuses it while that file requests a rollout or migration the mission does
  not declare: strip those requests in the revert (or declare them on purpose).
  After it merges, the previous single-manifest flow is back and the next DATA
  PR regenerates `STAGING_MISSION.json`.

## Delivery lanes (2026-10-15)

Lanes are defined in [AUTONOMY_POLICY.md](AUTONOMY_POLICY.md#delivery-lanes-owner-decision-2026-10-15).
Everything above is the DATA-lane contract and is unchanged.

**Classification.** `policy-gate` runs the base branch's `staging_policy.py`,
which first asks the base branch's `product_lane.py`. PRODUCT requires all of:

- the PR adds no mission file and does not edit `STAGING_FLEET.json` or
  `STAGING_MISSION.json`;
- every path (merge-base to head) is under `apps/web/` (not `vercel.json`),
  `services/api/tests/`, `docs/` outside `docs/agent/` (plus
  `docs/agent/PRODUCT_LOG.md`), one new file in `services/api/alembic/versions/`,
  or an allowlisted collector-facing API module (`PRODUCT_API`: `app/accounts`
  except valuation/value history, `web_cors`, collection/wishlist/saved-view/
  notes/activity/file-job/grading/alerts/health/version routers) whose name has
  no price/identity/source/Market Value/Index term;
- no changed API path is a collector runtime input at base or head;
- a new migration is structurally allowlisted: only `op`/`sa` imports, literal
  revision assignments, `upgrade()`/`downgrade()`; `upgrade()` only creates new
  tables and adds nullable/defaulted columns, indexes or constraints on tables it
  creates or on the collector-account tables; foreign keys only to `users` or
  those tables; it chains onto the base's single head and leaves one head;
- auth/security paths, and the web app's build and supply chain
  (`package.json`, lockfile, `.npmrc`, Dockerfiles, `apps/web/scripts/`,
  `next.config`), carry an `Independent security review:` line in the PR
  description.

Anything else, or any error, runs today's mission checks unchanged against the
PR's mission.

**Delivery.** A PRODUCT merge still takes the shared concurrency group, merges
natively and verifies. `staging_delivery_scope.py` returns `product`, so collector
rollout and RAW DDL never run. Verification expects the merged API (`api_sha=merge`)
and the repository's single Alembic head. If a merge that adds no mission is
neither documentation nor PRODUCT, delivery fails instead of running a rollout
or DDL nobody declared. A product migration is applied after merge by the
owner-approved `apply-migration` ops-write runbook (docs/agent/OPS_RUNBOOKS.md), never
by hand; until then the receipt fails on the revision, which is the intended signal. Before
arming a PRODUCT PR with a migration, `staging-credential-presence` runs
`scripts/staging_backup_age.py` (read-only) and refuses without a staging
Postgres backup younger than 24 h. Railway's backup record has no status
field, so the check is on age only.

**Arming and timing (all lanes).** `staging-pr-live` reads the live PR before
anything joins the delivery group: a push and `ready_for_review` in the same
second gave PR #123 one run with a stale head and one with a stale draft flag,
so nothing armed until the owner toggled draft. While waiting for the native
merge, `staging-automerge` disarms auto-merge at 19:30 UTC, waits until 20:30
and re-arms the same head, so no merge lands in the market-index window; the
30-minute merge budget is extended by the held time and the job timeout is
240 minutes.

**Owner hold (2026-10-15).** A PR labelled `hold-for-owner` is never armed: `staging-pr-live`
reports it as not current, so `staging-credential-presence` and `staging-automerge` skip and the
owner merges by hand. After a hand merge, `Verify staging merge` (push to `staging`) verifies the
head and regenerates state as usual. Agents may add the label, never remove it
(`.claude/hooks/guard.py`).

**Frontend runtime lag (2026-10-20).** Vercel can report the merge READY before the staging alias
serves it (#189 and #190 failed "Frontend runtime SHA disagrees with platform" 1-2 minutes after
merge; a later Verify staging merge passed). The verifier now polls web `/api/version` every 15 s
until `source_commit` equals the merge, for at most 10 minutes, then fails for real; the receipt
records `frontend_runtime_wait_seconds`. This applies to `staging-automerge`, the reusable delivery
workflow and `Verify staging merge`. To re-verify a merge after a lag failure, dispatch
`Verify staging merge` on `staging` with `expected_sha` = the full merge SHA
(`gh api -X POST repos/{o}/{r}/actions/workflows/staging-verify.yml/dispatches -f ref=staging
-f 'inputs[expected_sha]=<sha>'`). It verifies only while that SHA is still the staging head; an
older SHA exits as obsolete (`scripts/staging_verify_head.py`).

**Web smoke (2026-10-15).** After the delivery verification, `staging-automerge`, the reusable
delivery workflow and `Verify staging merge` run `scripts/staging_web_smoke.py`: signed out, `/`,
`/cards`, `/prints/5661` and `/sign-in` render; `/account`, `/collection` and `/watchlist` land on
`/sign-in?callbackUrl=<path>`; first-screen images on `/cards` and the print page load. The receipt
is `latest-web-smoke.json` in the delivery artifact. It is also the `web-smoke` ops runbook.

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
the PR's mission. `scripts/staging_delivery_scope.py` adds a second, file-based
guard that can only remove those two steps, never add work. It skips them only
when every path changed by the merge (`merge^1..merge`, renames detected) is
`docs/agent/handoff/**` or a `docs/**/*.md` file outside `docs/agent/evidence/`,
plus one added per-PR mission file, and that mission requests neither rollout
nor migration. Paths read by delivery, migration, verification or state code
(`STAGING_FLEET.json`, `STAGING_MISSION.json`, a changed mission,
`CURRENT_STATE.yaml`, `docs/agent/evidence/**`) are never documentation. Renames crossing the allowlist, unknown statuses, an
empty or undeterminable change set, or an unreadable mission run the full
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

### Collector releases refuse while any collector has a GitHub trigger (2026-10-11, session 10)

Session 9 removed the Railway GitHub deployment trigger from all ten collectors
(`serviceInstanceAutoDeployUpdate(enabled:false)`), so a merge that touches a
collector watch path no longer builds every collector at once. A re-enabled
trigger would silently restore that path.

Both forward release paths now refuse first:
- `deploy_staging_collectors.py` (sequential rollout), right after the live
  read and before any pre-change capture, slot wait or upload;
- `collector_variables.change` (settings-only redeploy), before staging any
  variable.

`refuse_github_triggers` reads, for **every** delivered collector (not only the
requested ones), `deploymentTriggers` and `serviceInstanceAutoDeployStatus`.
Any trigger, auto-deploy not exactly `false`, an unreadable status or a
collector missing from live state refuses the release. The rollout receipt
records the result as `github_trigger_preflight`. Rollback
(`collector_variables.restore` and the rollout's automatic restore) never runs
the check, so recovery is never blocked. The API, worker, beat and
market-index-snapshot keep their GitHub triggers by design: the API is
delivered by its GitHub build.

### Handoff checklist: delivery receipts (2026-10-12, session 11)

Every delivery's receipt is already persisted: the CI delivery job uploads it
as a run artifact (`staging-delivery-<merge sha>`, plus
`staging-credential-probe-<head sha>`), kept for 90 days. A handoff must not
depend on that retention or on local scratch space. Session 10 briefly
reported the PR #103 rollout receipt as lost: only local `/tmp` had been
searched, and a Codespace restart had wiped it. Every handoff therefore does
the following.

1. List every delivery that merged since the previous handoff was written,
   including that handoff's own PR, whose receipt only exists after it
   merges.
2. For each one, download all of its CI run's artifacts into the handoff's
   evidence folder, one directory per PR:
   `evidence/pr<N>-delivery/<artifact name>/` (for example
   `gh run download <run id> -n <artifact name> -D evidence/pr<N>-delivery/<artifact name>`).
3. Record in the handoff, for each delivery: PR, merge commit, CI run id,
   artifact names, ids and expiry, delivery scope (`skip` or `full`), and the
   collector deployment count. For `full` scope, the count comes from
   `latest-collector-rollout.json` when a rollout was requested. When none was
   requested, there is no such file and the count is 0; confirm it from
   Railway deployment records.
4. Keep all working files (tools, intermediate output, downloads) in the
   session worktree under `/workspaces`, never in `/tmp`.
5. Name any receipt that is still pending, normally the handoff PR's own, in
   the handoff and in `CONTINUATION.json`, so the next session downloads it
   first.

This is a documentation and operator routine only. No workflow, script or
artifact retention setting changes.

### Provenance follows what each service runs (2026-10-13, session 12)

`deployment-provenance-divergence` used to compare every Railway service with
the repository head. A docs or web merge moves the head while every collector
correctly stays on its release commit, and the API on its last watched build, so
the blocker fired after every such merge. `scripts/generate_staging_state.py`
now records a `provenance` decision per service and raises the blocker only for
services that are not current for what they run:

- **Collectors:** current when no runtime input changed between the deployed
  commit and the head, using `scripts/collector_runtime_inputs.py` (the same
  import graph as the continuity check). That is, the deployed commit is not
  older than the newest commit that changed the collector's runtime inputs.
- **API and market-index-snapshot:** current when no path under their Railway
  watch patterns changed (the same rule as `api_expectation: skip`).
- **Frontend:** built from every staging commit, so it must still equal the head.

Every service's commit must be on the staging history, and the platform SHA and
the exact-commit marker must agree when both are known. An undeterminable import
graph, watch-pattern set or diff counts as a divergence. The blocker now lists
the divergent services. Evidence recorded before this change replays with the
old head rule. Session-12 counterfactual on real history: Yuyu on a852244 would
be flagged (2 runtime inputs changed by a504e47), SNKRDUNK on a852244 would not
(it imports neither), the API on a504e47 would be (104 watched changes).
