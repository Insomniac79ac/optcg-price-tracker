# Coordinator handoff, 2026-11-05 (staging)

From the Claude coordinator session of 2026-10-29 to 2026-11-05 to its successor, the Grok Bot
"CP engineer" (instructions: `Insomniac79ac/content-pipeline` `grokbot/cp-engineer.md`). Read this,
then [ROADMAP.md](../../ROADMAP.md) (sections 1 and 6), [OPS_RUNBOOKS.md](../../OPS_RUNBOOKS.md),
[IDENTITY_REVIEWS.md](../../IDENTITY_REVIEWS.md), [AUTONOMY_POLICY.md](../../AUTONOMY_POLICY.md),
[INVARIANTS.md](../../INVARIANTS.md) and [STAGING_DELIVERY.md](../../STAGING_DELIVERY.md) before
acting. Numbers here are MEASURED at the run ids given and go stale.

Lane note for the successor: nearly everything under "Open work" below is DATA lane (collector
code, collector runtime inputs, ops-write runbooks). Under `cp-engineer.md` you take PRODUCT-lane
missions only until `ops/bots.md` shows `active (full)`, and nothing here is a mission until the
owner approves it in a `grokbot` issue. This list is a backlog in priority order, not an approval.

Historical context: the reasoning behind anything below is in the repo (DECISIONS.md, mission
files under `docs/agent/missions/`, PR descriptions #240 to #269). The previous coordinator chat
is the Claude session https://claude.ai/code/session_015jawj1HMHQvi6mFf9UfmTV; if something is
missing from the repo, ask the owner to look there rather than re-deriving it. The repo stays the
source of truth.

## Owner and standing rules

- Owner: Insomniac (Malaysia, UTC+8, "not a dev"). Terse, plain English, no em-dashes.
- Owner instruction (verbatim): "And if something unexpected happens, never give your best guess.
  Check and report what actually happened".
- Plan and build are separate steps: no build before the owner approves the plan. Offer
  perfectionist vs pragmatist when it matters. Verify before reporting done. Fix root causes.
- UI asks to the owner: click-by-click with exact links. Prompts for other sessions: pasted in full.
- Never print or paste secrets. Staging only (production is RED). PSA10 is off.
- Agents never approve ops-write runs and never remove `hold-for-owner`.
- `.github/**` and `.claude/**` changes get `hold-for-owner`; the owner merges them. Collector
  releases go only through the `staging-automerge` job: open as draft, the owner marks it ready.
- Windows (UTC): collector forward rollouts must START 06:00 to 23:00, so ask the owner to mark a
  collector PR ready only 06:00 to 19:00 UTC (14:00 to 03:00 MYT; a release takes up to about 50
  min). Never merge 19:30 to 20:30 (the 20:00Z market-index-snapshot run); #257 merged at 03:33Z
  and its rollout was refused, recovered by #258. Collector-affecting ops writes are blocked
  02:00 to 06:00.
- Fleet pin rule: the next merge after any collector delivery must set
  `docs/agent/STAGING_FLEET.json` `snkr_component` / `yuyu_reader_component` to that delivery's
  merge commit, or its post-release verify fails with "Adopted component source differs from
  expected runtime inputs". Check what a branch changes with
  `scripts/collector_runtime_inputs.changed_runtime_inputs(base, head, collector)`.
- Sources: honest User-Agent, respect robots.txt, stop on 403/429/challenge, never escalate.
- Never use Railway "Deploy Latest Commit" or the Deploy banner on collectors. Tell the owner
  never to click GitHub "Update branch" on a mission PR (it stales the mission digest).
- Changing SNKRDUNK matcher thresholds or identity rules loosens an identity guard: owner decision.

## State at handoff (2026-11-05 11:10Z)

- staging head c69548ca (#269 merged 10:29Z, delivered 10:50Z, job 127183786799 green). No open
  PR of this session. Fleet pins: `snkr_component` 02be15f4 (#268, the last collector delivery,
  pinned by #269), `yuyu_reader_component` 6c65fa4b. No pin is owed.
- No ops-write run is waiting. Open PR waiting on the owner: #185 (draft, `hold-for-owner`, new
  sources D0 kit), unchanged by this session.
- SNKRDUNK coverage (db-diagnostic snkrdunk-coverage-gap 41988187701, 07:35Z): 102 of 1,556
  target prints fresh (89 on 2026-11-03), 212 mapped and eligible, 843 candidates, 593 mapped
  listings. Gap classes: 530 release has no SNKRDUNK anchor, 429 release anchored but print not
  found, 195 proposal not approved (exact 64, ambiguous 50, release_unresolved 73, mixed 8), 60
  quarantined, 190 all code listings mapped to siblings, 50 mapped with no raw ask in 24 h.
- Approval batches (db-diagnostic snkrdunk-new-mappings 42011604099, 10:4xZ, after #269):
  - Run 41444936669 (2026-11-02, 208 mappings): 118 captured and listed (23 of them the owner
    confirmations below), 58 no listing (6 confirmations), 20 artwork refusals, 12 box-topper
    release refusals.
  - Run 41787151033 (2026-11-04, 32 mappings in OP-05..OP-17, EB-03, EB-04): 21 captured and
    listed, 4 no listing, 4 artwork refusals (mappings 4501, 4505, 4519, 4526), 3 box-topper
    release refusals (4520 EB03-042, 4521 EB04-025, 4522 EB04-012).
- Discovery creates proposals for new listings (#262, `with_proposals`): every candidate created
  after 2026-11-03 13:24Z has a current proposal (statement `proposals` of 42011604099: 65 exact,
  6 ambiguous, 35 release_unresolved, none without). Discovery runs about 100 requests per turn
  and still finds 13 to 20 new listings per turn (snkrdunk-discovery-state 41988430705).
- Quarantine (db-diagnostic snkrdunk-quarantine 41988311436): 137 blocked SNKRDUNK refresh items
  before the requeue below; 70 blocked artwork refusals after it (snkr-refused-photos
  42011747265, none of them an owner-confirmed mapping). The 2026-10-06 placeholder-image and
  2026-10-02 confirmed-refusal groups are older and untouched.
- Storage: about 68 days of runway at the planning rate (storage-rates, 2026-11-04). Flag the
  owner below 45 days.

### Plan B (owner photo confirmations): done

Owner 2026-11-03/04: "for those that the collector is unable to identify, a manual identification
to match would be more accurate"; "OK, build plan B". The owner's observation: SNKRDUNK's
colouration differs from Bandai's official images, a likely cause of the artwork refusals.

- #266 `snkrdunk_collector/owner_artwork.py` + committed `owner_artwork_confirmations.json`: a
  refused comparison of two decoded images becomes a match only for the exact mapping, current
  print, current listing and photo URL the owner confirmed. `snkr-owner-requeue` (ops-write)
  reopens confirmed blocked items. #267 added 26 confirmations (29 in all).
- The first requeue (run 41824225311) was refused again: the collector's own mapping model had no
  `canonical_source_listing_identity`, the hook read it with `getattr(..., None)` and every
  confirmation was skipped (Railway log `owner_confirmed: null`). Fixed in #268 (column added to
  the mirror, read directly, wiring test on the real model).
- Requeue after #268: dry run 41988133502, apply 41997566760 (09:27Z), plan
  115384ad81771a21..., reopened all 29 work items, nothing skipped. By 10:4xZ all 29 were
  re-checked: 23 captured and listed, 6 captured with no listing, 0 refused (42011604099). Not
  yet read directly: the Railway `artwork_comparison_complete` lines with `owner_confirmed` set.

## Open work, in order

### 1. Approve the pending exact SNKRDUNK proposals (DATA lane, ops-write, owner-gated)

Statement `proposals` of 42011604099: 77 exact proposals on listings with no mapping (20 created
before 2026-11-03 13:24Z, 57 after). Next step: `approve-snkr-batch` dry run, owner approves,
apply with the plan SHA, then the 24 h check with db-diagnostic snkrdunk-new-mappings (add the
new run id to the `reviewed_by in (...)` lists in `scripts/diagnostics/snkrdunk-new-mappings.sql`
first). Exact title-kind groups are approvable; ambiguous ones are not.

### 2. Owner verdicts on the remaining artwork refusals (plan B continued)

24 artwork refusals wait for the owner's photo verdict: run 41444936669 mappings 4418, 4424, 4433,
4440, 4358, 4389, 4427, 4430, 4441, 4448, 4419, 4408, 4412, 4395, 4352, 4359, 4312, 4383, 4409,
4455; run 41787151033 mappings 4501, 4505, 4519, 4526. Photo URLs: snkr-refused-photos
42011747265 (rows: mapping, print, listing, work, refused at, photo URL). For each "same" verdict:
add an entry to `owner_artwork_confirmations.json` (format and `confirmed_by: "owner"` as the 29
existing ones; the photo URL must be exactly the one the runbook printed), which is a collector
runtime input, so the PR is a draft snkrdunk-collector release with a mission file (model:
`docs/agent/missions/claude-snkr-owner-confirmations-2.json`) and the fleet pin owed by the last
delivery. After delivery: `snkr-owner-requeue` dry run, owner approves, apply, then
db-diagnostic snkrdunk-new-mappings. A "different" verdict: the mapping is wrong; deactivate it
through the admin mapping path, never edit the confirmations to force it.

### 3. Box-topper refusals (owner decision first)

15 items refused with `release_name_mismatch`: the SNKRDUNK page names a box-topper or edition
product ("BOX封入特典", "エクストラブースター「エッグヘッドクライシス」", "「ワンピース ヒロインズエディション」"),
not the booster the print is in. 12 from run 41444936669 (OP-01 and OP-02 p1 prints), 3 from
41787151033. The owner has not decided what one of these pages is; ask the owner to describe what
one page shows before any plan. Accepting a new product label for a print is an identity rule
change (owner decision, Bandai evidence required as in `bandai-label-evidence`).

### 4. Unresolved new-set labels (release_unresolved)

35 candidates since 2026-11-03 13:24Z have no set code (their title label is not in
`release_product_aliases.py`). Next step: `bandai-label-evidence` (read runbook, about 50 Bandai
requests) and add only labels proven against the capture, as #262 did with
`docs/agent/evidence/bandai-label-evidence-20261103.json`; then `snkr-candidate-refresh`
(ops-write, owner-gated) for the backlog. Collector runtime input: draft collector release.

### 5. Discovery pace and storage (step 3, owner number pending)

The owner chose to measure before raising discovery pace. Measure growth per discovery turn
(storage-rates plus snkrdunk-discovery-state), propose a number, and wait for the owner's OK.

### 6. Offered, no decision

- A read-only comparison of matcher scores (average hash, dhash, phash, aspect) between refused
  and passed listings, as input to a possible matcher change. Any threshold or rule change is the
  owner's decision (identity guard).
- Image review of 9 earlier plus 7 new ambiguous SNKRDUNK groups.

### 7. Carried from the 2026-10-29 handoff

Items 1 (Yuyu-Tei identity reviews) and 3 (smaller items) of
[the 2026-10-29 handoff](../2026-10-29/coordinator-handoff.md) were not worked in this session's
last week (it worked SNKRDUNK, #244 to #269). Re-check their state from ROADMAP section 6 and a
fresh staging-state before planning. The SNKRDUNK price wait (its item 2) was addressed by #245
(embedded chip prices).

## Working notes

- `gh` works over REST only; GraphQL is blocked. Draft and ready, auto-merge and review threads go
  through the `/ccr/` REST routes the error lists. Auto-merge on an already-clean PR is refused:
  open as draft, then ready.
- ops-readonly results: `docs/agent/handoff/2026-10-29/ops_result.py <runbook> [<diagnostic>]
  --out DIR`; ops-write summaries are read the same way (`ops_result.result(run_id)`). Dispatch one
  run at a time. Artifacts cannot be downloaded from an agent workspace.
- db-diagnostic inline budget 18,000 characters; statements past it are listed in
  `rows_omitted`. Keep statements compact (no long titles, Japanese text costs six characters per
  character). A new diagnostic FILE needs a choice in `ops-readonly.yml` (alphabetical order,
  `.github`, owner merge).
- Mission flow: commit, `python3 scripts/staging_mission.py digest --base origin/staging` (take
  `diff_sha256`), write it into the mission, amend (or a new commit on a pushed branch, never a
  force-push), then `python3 scripts/staging_policy.py --base origin/staging --head HEAD`. Effects
  allowed include application, infrastructure, tests, documentation, state_observation.
- Collector tests: from `services/snkrdunk_collector`, `PYTHONPATH=.:../api:../../packages/opcg_source_identity`
  and `SNKRDUNK_TEST_PG_URL` for the Postgres cases. Use the collector's real models in tests, not
  stand-in objects: a stand-in hid the #266 bug.
- A merged collector change that was not released (for example merged in a refused window) is
  recovered by a follow-up PR touching no collector watch path, as #258 did.
- The staging API and website are not reachable from an agent workspace shell; use ops-readonly
  results or the owner's screenshots.
- Scheduled tasks on the owner's account that read this repo: daily source health report (09:40
  MYT), source health alert (every 4 h), and the daily independent review of Grok bot work (10:17
  MYT, may open a `stop` issue and a revert PR held for the owner).
