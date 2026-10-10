# Storage (c): run-independent proposal evidence digest. Design and AMBER preflight

Status: **DESIGN ONLY. Not implemented, not delivered.** It goes out as its own collector release
in session 10 or later, after the request-savings evidence (a852244) and the auto-deploy fix are
settled, so that evidence is not mixed. No VACUUM FULL.

## Problem (MEASURED 2026-10-10 22:25Z, `evidence/proposal-versions-24h-2225.txt`)

- `source_mapping_proposal_groups` is 50 MB: 26,967 Yuyu rows, of which 4,183 are current, and
  1,120 SNKR rows, of which 474 are current.
- In the last 24h, Yuyu (source 1) wrote **2,164** new versions. In every one, `discovery_run_id`
  changed and `candidate_id` did not. Only **47** changed any other evidence field, and **0**
  changed `resolution_status`.
- SNKR wrote 0 new versions in 24h.
- Cause: `_candidate_payload` puts `discovery_run_id` into the evidence that `_digest` hashes
  (`services/api/app/services/source_mapping_proposals.py:174` (Yuyu), `:190` (SNKR) → `_make_plan`
  `:248`). Every recurring discovery run therefore produces a new `evidence_digest` for an
  unchanged listing, and `persist` supersedes the current row and inserts a new one (`:955-1000`).
- About 5.3 MB/day (CARRIED FORWARD, session 8 estimate).

## Design (R1)

1. **Digest input.** Compute `evidence_digest` over the evidence **without** `discovery_run_id`.
   `candidate_id` stays: it is stable across runs (2,164 of 2,164).
2. **Provenance kept.**
   - `evidence_summary_json` still records the `discovery_run_id` of the run that **created** the
     version. That record is unchanged.
   - The last run that **saw** an unchanged listing is already recoverable from the discovery run
     and candidate tables (the candidate row is re-observed per run). No new column, and no UPDATE
     on reuse.
   - An UPDATE on every reuse would trade permanent versions for about 4,600 dead tuples per run.
3. **Resolver version.** `RESOLVER_VERSION` goes `source-mapping-proposals/1.2` → `1.3`, so the
   change in digest semantics is explicit. Historical keys (`resolver_version`, `evidence_digest`)
   can never collide between the two digest definitions.
4. **One-time re-version.**
   - On the first run after release, each current group's digest changes once.
   - That is about 4,183 Yuyu plus up to 474 SNKR rows, ≈ 9-10 MB written once (ESTIMATE, from
     the 50 MB / 28,087 rows average).
   - From then on: about 47 versions a day instead of 2,164 (−97.8%, MEASURED basis).
5. **Fences that depend on the digest. This is the main risk.** These all compare
   `evidence_digest`:
   - approval: `source_mapping_proposal_decision.py:181,240,272`, `expected_evidence_digest`;
   - physical-artwork proof: `physical_artwork_proof.py:77,112,125`, `baseline_evidence_digest`;
   - Yuyu candidate approval: `yuyutei_candidate_approval.py:517`;
   - `identity_evidence_scope.py`.

   **298** current approved-exact Yuyu groups carry `positive_physical_artwork_proof`
   (`evidence/proposal-current-status-2225.txt`). The implementation must show, in a mock-backed
   regression test, that a proof bound to a 1.2 digest still re-attaches to the 1.3 version of the
   same unchanged evidence. One way is to accept a proof whose baseline equals the **legacy**
   digest recomputed from the same evidence, as a one-release bridge. If it cannot, exact status
   would be demoted, and the design must change before release.
   - The proof must never transfer across a real evidence change.
   - Approvals stay fenced: an approval request against a superseded digest still fails
     `evidence_digest_changed`.
6. **No change** to identity guards, resolution logic, alternatives, Yuyu sale policy, schedules,
   budgets, pacing or freshness.

## Release class

This is a collector release, because both collector images import `app.services.source_mapping_proposals`
(`scripts/collector_runtime_inputs.py`). Policy: **AMBER**.
- Code PR first, with no rollout requested.
- Then a follow-up delivery PR that touches only `scripts/` or `docs/`, through the sequential
  rollout (`deploy_staging_collectors.py`, 06:00-23:00Z, one collector per safe slot).
- Since session 9 the collectors have no GitHub trigger, so the code merge itself builds nothing.

## Preflight checklist (session 10 must complete each item before merging)

| # | Check | Pass condition |
|---|---|---|
| 1 | Impact | 10 collectors. DB writes: one-time ≈ 4.7k group inserts, then ≈ 47 a day. 0 source requests added |
| 2 | Tests | Unit: an unchanged listing across two runs gives the same digest and `reused`, not `superseded`. A changed price gives a new version. Each fence above still fences. The 298-proof bridge holds, and a proof does not transfer across changed evidence |
| 3 | Backup / rollback | No schema change. Rollback = restore every collector to its a852244 image via `collector_variables.restore` (redeployable sources in session-8 `fleet-after-pr98.json`). Rows written under 1.3 stay valid history. 1.2 code would re-version once more (≈ 10 MB) |
| 4 | Baselines before release | Current groups by source and status (`proposal-current-status-2225.txt`), count with proof = 298, approved exact = 2,019 Yuyu and 151 SNKR, versions per 24h = 2,164 |
| 5 | Rollback triggers | Any drop in approved exact or with-proof counts. Any `stored proposal differs` RuntimeError. Any discovery failure. Re-versioning still > 200/day after the first full discovery cycle |
| 6 | Post-release verification | One natural discovery turn per shard. Second-cycle versions ≈ changed listings only. Lossless still green. Table growth measured over 24h |

## Not proposed

- VACUUM FULL or `pg_repack`, which take an ACCESS EXCLUSIVE lock.
- Deleting superseded history, which is identity evidence.
- R3 per-table autovacuum: about 4 MB, low value.
