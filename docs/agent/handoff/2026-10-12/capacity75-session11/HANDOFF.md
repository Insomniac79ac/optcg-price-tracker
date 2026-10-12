# Capacity / RAW75: session 11 handoff (2026-10-12)

STAGING ONLY. Production RED, untouched. PSA10 OFF.
- No source job was triggered manually.
- No collector release, rollback or setting change.
- No mapping approval. NEW100 not approved. No SNKRDUNK discovery.
- No schedule, budget, pacing or freshness change.
- No RAW evidence deleted. No resize, no infrastructure change.
- Every database read used `default_transaction_read_only=on`. 0 writes, 0 source requests.
- **One delivery:** this handoff (docs only).

Numbers are **MEASURED** (source under `evidence/`, read-only tools in `tools/`) unless marked
CARRIED FORWARD (CF) or ESTIMATE. The session ran 06:09-06:4xZ, after the 06:00Z start gate.

## 0. Start gate (06:10-06:12Z)

| Check | Result | Evidence |
|---|---|---|
| PR #104 (session-10 handoff) landed | Yes, merge `e6d0ca7` | `evidence/pr104-delivery/` |
| All 10 collectors on `a504e47` | Yes. The active deployment and image digest equal the PR #103 receipt on all 10, with the exact-commit marker and SUCCESS. **0 deployment records** on any collector since the rollout (16:31:08Z), so the #104 and #105 merges touched no collector | `live-state-start.json`, `fleet-vs-receipt-start.json` |
| Cron, start command, daily-v1 variables | Unchanged on all 10 | `live-state-start.json` |
| GitHub triggers | None on any collector; auto-deploy `false` on all 10 | `trigger-status-start.json` |
| Backups | Manual `2135eec8…` (2026-10-11 15:20Z, 14.9 h old); daily schedule `22 9 * * *`, 6-day retention | `backups-start.json` |
| State regenerated | `CURRENT_STATE-start.yaml` (06:12:26Z), `evidence/staging-state-f998000adfd6da30.json` | |

**Blockers: 3**
- `freshness-deadline-deficit`, unchanged.
- `snkrdunk-identity-quarantine` (23), unchanged.
- `deployment-provenance-divergence`, **returned, but it is not a real divergence.** The generator flags any service whose SHA differs from the repository head. The head is now `5a9ac46`, after #104 (docs) and #105 (web). The API, market-index-snapshot and all collectors correctly stay on `a504e47`: both receipts show `api_expectation: skip`, and no collector record was created. It clears at the next release that moves the services to the head. Do not "fix" it by redeploying.

## 1. Proposal-digest release: natural verification (read-only)

`evidence/proposal-digest-verify-0615Z.json`, `-end.json` (06:28Z), `evidence/reversion-check-0616Z.txt`.

**Discovery on `a504e47`.** The first natural Yuyu discovery turns ran 01:13:38 → 04:14:43Z:
- 15 attempts, all `completed`, 835 requests;
- 0 discovery failures;
- 0 `stored proposal differs` errors.

**What a "full discovery cycle" is (finding).** There are 582 pending Yuyu discovery items plus 3 blocked:
- **515 are completed one-off explicit identity captures**, parked with `next_due_at` in 2126 and last attempted on 2026-10-06. They are not recurring discovery and will never run again.
- **The recurring cycle is the other 67 items.** They produce the daily re-versioning: 52 + 15 items, the same split as on 10-11.
- Session 10 defined the cycle as complete "when every pending item has an attempt". Taken literally, that can never be met. This handoff reads it as **all 67 recurring items attempted on `a504e47`**.

| | MEASURED |
|---|---|
| Recurring items attempted on `a504e47` | **15 / 67** |
| Remaining 52 | due 13:43:17 → 14:15:53Z today |
| New proposal versions since the merge | **915**, all `source-mapping-proposals/1.3`, all `pending` (451 release_unresolved, 249 unresolved_identity, 209 ambiguous, 5 conflict, 1 exact-pending) |
| Superseded since the merge | 915, **all resolver 1.2** |
| Listings re-versioned twice since the merge | **0** |
| Yuyu pending groups still on 1.2 | 1,249 (the 13-14h batch; 915 + 1,249 = 2,164, the expected one-time re-version) |
| SNKR new versions | 0 |
| Approved exact Yuyu / SNKR | **2,019 / 151**, unchanged |
| …Yuyu approved with proof | **298**, unchanged |
| Approved groups superseded since the merge | **0** |
| Reviews of any kind since the merge (auto-approval check) | **0**; approved groups created since the merge: 0 |
| Proposal tables | groups 59,613,184 B + alternatives 15,556,608 B, 31,166 group rows. **+2.74 MB since 2026-10-11 23:27Z**, about 2,990 B per version |

**Trigger verdict: NOT DECIDABLE YET. The first full cycle has not completed. Do not decide early.**
- The 915 versions so far are exactly the expected one-time re-version of 1.2 pending groups: same hours and same counts as every earlier day (265/34/476/140), all replacing 1.2 rows, none twice.
- **Proof trigger: not fired.** 298 proofs, 0 approved superseded.
- **Versions trigger: cannot be measured** until 24 h after the cycle completes, about **2026-10-13 14:16Z**.
- **Early signal:** at 2026-10-13 01:12-04:15Z the same 15 items run again, now with 1.3 digests stored. Unchanged listings should be reused. Expect roughly the real-change count (about 47/day CF s9, pro rata), not 915.
- **Expected storage after the one-time re-version:** at most 200 versions/day × 2,990 B ≈ 0.6 MB/day (ESTIMATE from MEASURED).

Rollback targets and procedure are unchanged: session-10 HANDOFF §4, the a852244 deployments.

**Lossless** (`evidence/verify-lossless-from-47829.json`): every daily-v1 ledger row from 47829 to 50071:
- 2,207 rows (Yuyu 2,151, SNKR 56);
- **0 failures, 0 expanded**, `all_lossless: true`;
- 0 writes, 0 source requests.

## 2. Receipts in every handoff (docs only)

- **Checklist added** to `docs/agent/STAGING_DELIVERY.md`, "Handoff checklist: delivery receipts". For every delivery since the previous handoff:
  - download all CI run artifacts into `evidence/pr<N>-delivery/`;
  - record PR, merge, run, artifact ids and expiry, scope and the collector deployment count;
  - keep all working files in the `/workspaces` worktree, never `/tmp`;
  - name pending receipts, normally the handoff PR's own, for the next session.
- **Done for this session:**

| PR | Merge | CI run | Artifacts (id, expiry) | Scope | Collector deployments |
|---|---|---|---|---|---|
| #104 session-10 handoff | `e6d0ca7` | 38201814308 | `staging-delivery-e6d0ca7…` (11725513787), `staging-credential-probe-5527765…` (11725242388); expire 2027-01-10 | `skip` (84 docs files) | **0** (no rollout step ran) |
| #105 web: chart-export flake fix | `5a9ac46` | 38208340029 | `staging-delivery-5a9ac46…` (11728708387), `staging-credential-probe-64f68a3…` (11727819407); expire 2027-01-10 | `full` (4 `apps/web/src` files; no `collector_services`, no RAW migration) | **0**. No `latest-collector-rollout.json`; the verifier reads all 10 collectors still on `a504e47` with `source_jobs_triggered: 0`; and Railway shows 0 records since the rollout |
| This handoff | see PR | see PR | **PENDING: session 12 downloads it first** | expected `skip` | expected 0 |

## 3. NEW100: re-planned on 1.3 digests. NOT APPROVED (storage)

`evidence/new100-replan.json` (`tools/new100_replan.py`), `evidence/new100-storage.json`
(`tools/new100_storage.py`), `evidence/storage-rates.json`, `evidence/volume-series.json`.

**Re-plan.** The 100 candidates of the 2026-10-07 plan were re-resolved read-only with the
canonical resolver: the same `resolve_current_candidate_proposal` call the collector's
`load_intent` makes at claim time. Results:
- all 100 are still ambiguous families;
- **all 100 digests changed** (1.2 → 1.3);
- 0 sibling sets changed;
- one-off images: 100 Yuyu + 217 official, as before.
- New `scope_key` values (`yuyu-identity:<id>:sha256:<1.3 digest>`) are in the file.
- **Caveat:** the stored groups for all 100 are still 1.2 until today's 13:43-14:16Z re-version. The digests above are the live 1.3 resolver output now. Any real listing change before an apply makes a digest stale. `load_intent` refuses such an intent (fail closed), so **re-run the re-plan immediately before any apply.**
- No committed tool exists to enqueue capture intents; the 2026-10-06 batches were enqueued ad hoc. An apply needs a reviewed, guarded writer.

**Guards:**

| Guard | Result | Evidence |
|---|---|---|
| Exact CardPrint identity (ambiguous family, 2-12 complete siblings, all prints exist, same canonical card) | **PASS 100/100** | `new100-replan.json` |
| No duplicate active Yuyu mapping (no active mapping on any considered print or listing) | **PASS 100/100** | same |
| Authoritative `release_product_id` (every considered print's release equals the plan's; never from code prefix) | **PASS 100/100** | same |
| Virgin family (no prior capture scope, no reviewed decision) and no print shared between planned candidates | **PASS 100/100** | same |
| Safe shard distribution | **PASS.** Capture intents are claimable by all 9 shards (`kind != refresh`). Refresh after a later mapping approval is split by mapping id mod 9; today it is 290-292 per shard | `yuyu-shard-balance.txt` |
| 23h/24h feasibility at about 31 requests per capture | **PASS.** (2,814 + 100) × 31.2 = 90.9k/day vs 9,000 per 1,800 s = 432k/day (21%). One-off captures: 100 × 58.1 = 5.8k requests (ESTIMATE from MEASURED) | `requests-24h-a504e47.json`, `identity-capture-requests.txt` |
| Measured source capacity | **PASS.** Yuyu 24 h: 2,814 captured, 1 transient failure, 0 denials; busiest window 4,522 / 9,000 (50%). SNKR: 0 denials, 403, 429 or challenges | same, `snkr-24h-detail.json` |
| Freshness not degraded | **PASS.** Freshness block identical to session-10 end; 0 open non-blocked checks older than 24 h | `CURRENT_STATE-start.yaml`, `coverage-start.json` |
| **Storage** (no resize, 3 GiB reserve, 90 days) | **FAIL at both owner-defined rates** (below) | `new100-storage.json` |

**Storage.** s9 basis (GB × 1024); Railway basis is in `storage-rates.json`. Room to the reserve is
**3,110.4 MB** (volume 3,668.3 MB at 06:00Z).

| Rate | MB/day | Runway with no batch | Largest batch that fits (hard bound) |
|---|---|---|---|
| **Planning: 7-day average** (10-05 06:00 → 10-12 06:00Z) | **232.6** | 13.4 days | **none** |
| **Stress: worst rolling 24 h in those 7 days** (from 10-05 18:00Z) | **1,060.1** | 2.9 days | **none** |
| Context only, not a decision rate: 72 h | 26.8 | 116 days | NEW50 |
| Context only: 48 h | 9.5 | 329 days | NEW100 |
| Context only: 24 h | 20.9 | 149 days | NEW100 |
| CF s10: 24 h on a852244 / worst | 18.8 / 34.2 | 165 / 91 days | NEW100 / none |

Daily growth at 06:00Z (MB):

| Day | 10-03 | 10-04 | 10-05 | 10-06 | 10-07 | 10-08 | 10-09 | 10-10 | 10-11 |
|---|---|---|---|---|---|---|---|---|---|
| Growth | 217.5 | 185.5 | 188.8 | **959.9** | 248.4 | 150.3 | 61.6 | −1.9 | 20.9 |

The 7-day window still includes the identity-capture batches (10-06) and the pre-encode code.

Re-measured NEW costs, using the re-plan's actual sibling counts:

| Batch | One-off hard bound | One-off measured-average estimate | Recurring |
|---|---|---|---|
| NEW100 (100 + 217 images) | **894.5 MB** (887.0 image bound + 7.5 MB HTML at the 37,456 B max) | **134.1 MB** | **0.66 MB/day** (24 h growth / 3,169 attempts = 6.58 KB per capture, overstated) |
| NEW50 (50 + 102) | 429.1 MB | 65.2 MB | 0.33 MB/day |
| NEW25 (25 + 51) | 214.5 MB | 32.6 MB | 0.16 MB/day |

Image sizes are unchanged since 10-06: 516 Yuyu images averaging 635,067 B, 1,059 official averaging 291,299 B, product pages averaging 37,082 B.

**Verdict: NOT APPROVED.** NEW100, NEW50 and NEW25 all fail at the planning rate and at the stress
rate. At the planning rate, the base growth alone fills the room in 13.4 days.

**Owner question.** The literal 7-day window still contains 10-05 → 10-08. Should the planning and
stress rates use only days on the current collector code (a852244 from 10-10, `a504e47` from
10-11 16:31Z)? On those windows NEW100 would fit at the hard bound, at 9.5-20.9 MB/day. At the
session-10 worst rolling rate (34.2) and at 72 h (26.8) it would not; NEW50 fits at 26.8.

The 7-day window stops containing 10-06 after 2026-10-13 06:00Z, and stops containing 10-08 after
10-15 06:00Z. If the owner keeps the literal definition, re-evaluate then.

## 4. SNKRDUNK headroom (read-only)

`evidence/snkr-24h-detail.json`, `evidence/requests-24h-a504e47.json`, `evidence/snkr-admission-estimates.txt`.
Last 24 h = 2026-10-11 06:00 → 10-12 06:00Z.

| | MEASURED |
|---|---|
| Busiest half-hour | **2,875 / 3,100 (92.7%)** at the 10-11 11:53Z window. Next: 2,832, 2,820, 2,808 |
| Average | 1,995 over the 13 windows with work; 540 over all 48 |
| Windows over 95% (2,945) | **none** |
| Attempts | 287 (50 captured at 98.9 req, 237 no_listing at 88.6); max 178; 0 over reservation |
| Denials / 403 / 429 / challenges / failures | 0 / 0 / 0 / 0 / 0 (49 runs, 13 with work) |
| Homepage RAW | 13 rows, 1 per turn with work, 884,431 B |

**What drives the peak.** Every SNKR work item has `estimated_request_cost` 300, and every
attempt reserves 300. Actual use is about 90. Admission keeps claiming while at least 300 requests
remain, so a turn with enough due work stops at about 3,100 − 300 + one attempt's actual. That is
2,800-2,875, the four peaks seen. It is the **admission fill ceiling**, independent of backlog
size, which is why the peak did not fall as the backlog drained.
- It cannot exceed 3,100: the reservation (300) is larger than the largest actual attempt (178).
- Lowering the peak would mean changing the reservation or budget. Not done: budgets and pacing are out of scope.

This 24 h window overlaps session 10's: SNKR had no due work from 16:33Z to 06:00Z. Due now:
290 pending (not due), 89 blocked (the known blockers, CF s9).

## 5. Coverage, freshness, due work, Market Value

`evidence/coverage-start.json` (06:26:24Z), `CURRENT_STATE-start.yaml`.

- **Coverage** (denominator 4,316):
  - mapped 2,635;
  - **operational 2,630, a change of 0 from 2,630**, with 607 to the 75% target of 3,237;
  - fresh usable 2,398; both sources 334; zero sources 1,681;
  - duplicate exact-print source groups 0.
- **Freshness:** identical to session-10 end.
  - Yuyu: 2,619 mappings; 1 never checked; 2 checks older than 24 h.
  - SNKR: 353; 22 never checked; 44 older than 24 h (blocked); 278 no_listing.
  - Deadline compliance `not_met`; sustained compliance unknown.
- **Open non-blocked work:** 0 checks older than 24 h, 0 without a first success.
- **Due now:**
  - Yuyu refresh: 81 due, oldest 05:27Z (normal turnover);
  - Yuyu discovery: 0 due;
  - SNKR: 0 due, plus 66 blocked refresh and 23 blocked validation.
- **Market Value:** latest atomic receipt for 2026-10-11 (2,626/2,626 rows). The 09-27/28 gaps are intact (0 rows). Next run about 20:00Z today.

## 6. End-of-session state

`CURRENT_STATE-end.yaml` (06:28:20Z), `evidence/staging-state-88a3b552bc932e22.json`.
- Same 3 blockers as the start (§0).
- Proposal counts unchanged from §1 at 06:28Z.
- The canonical `docs/agent/CURRENT_STATE.yaml` and `docs/agent/evidence/` are not changed by this docs-only PR. CI regenerates them as run artifacts.

## Quiet windows

| Window | Status |
|---|---|
| 02:00-06:00Z | No collector change, ever |
| Collector releases | 06:00-23:00Z only, one collector per safe slot, via the CI delivery path |
| 19:30-20:30Z | No API or migration merge (daily snapshot and receipt about 20:00-20:05Z) |
| **Today 13:43-14:16Z** | The last 52 recurring Yuyu discovery items run on `a504e47` (second half of the first cycle, about 1,249 re-versions). Leave the collectors alone |
| **2026-10-13 01:12-04:15Z** | First repeat pass on stored 1.3 digests: the early signal for the versions trigger |
| Until 2026-10-13 about 14:16Z | 24 h trigger-measurement window. No collector change unless a rollback trigger fires |
| NEW100 | Not approved. Nothing to observe |

## Session 12 must verify

1. **Download this handoff PR's CI receipt first** into `evidence/pr<N>-delivery/`, per the new checklist. Expect scope `skip` and 0 collector deployments.
2. **First cycle complete.** After about 14:16Z on 10-12:
   - all 67 recurring Yuyu discovery items attempted on `a504e47`;
   - 0 discovery failures;
   - the 1,249 remaining 1.2 pending groups re-versioned to 1.3, none twice;
   - 298 proofs, 2,019 / 151 approved, 0 approved superseded, 0 reviews.
3. **Rollback trigger decision** with the 24 h after the cycle, ending about 2026-10-13 14:16Z.
   - Fires if there are **more than 200 new proposal versions** in that 24 h, or any proof is lost.
   - If it fires: sequential restore to the a852244 deployments (session-10 HANDOFF §4), inside 06:00-23:00Z.
   - Early signal at 2026-10-13 01:12-04:15Z (§1).
   - Also record proposal-table growth per day.
4. **Owner decision on the storage planning and stress rates** (§3), before any NEW100 re-evaluation. If NEW100 is later approved:
   - re-run `tools/new100_replan.py` immediately before applying;
   - the apply needs a reviewed, guarded enqueue writer (none is committed);
   - verify only through ordinary scheduled runs.
5. **Lossless** from ledger id 50072.
6. **SNKR headroom:** the peak is the admission fill ceiling (§4). Flag any window over 95% (2,945).
7. **Never replay:**
   - SNKR 3676/3677
   - RAW recovery 35175
   - Yuyu canary evidence
   - completed deliveries PR77-105 and this handoff PR

**PSA10:** NOT READY, not activated.
