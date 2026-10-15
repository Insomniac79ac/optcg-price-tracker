# Proposal: additive `closed` state for freshness work (data-lane follow-up, not built)

Owner decision (b), 2026-10-15: do not delete Yuyu work rows 2628-2630 or their attempt history.
Close them with an additive state instead. This is a proposal only; nothing is built.

## Problem

`ck_freshness_work_state` allows `pending`, `claimed` and `blocked`. Work for a contained or deactivated mapping can only stay
`blocked` (reported as quarantine) or be deleted. A delete cascades (`ON DELETE CASCADE`) to `freshness_attempts` and
`freshness_price_states`, which destroys attempt history.

## Change

1. **Migration (additive, AMBER):** widen the check to `state IN ('pending','claimed','blocked','closed')`.
   - Add nullable `closed_at timestamptz` and `closed_reason varchar(200)`.
   - Add a check that `state='closed'` iff `closed_at IS NOT NULL`.
   - The claim check already requires no claim fields when `state <> 'claimed'`.
   - Downgrade: refuse while any row is `closed` (no silent reopen); otherwise drop the columns and restore the check.
2. **Planners and claims** (`app/services/freshness_queue.py`):
   - `claim_due` and `_recover_expired` already select `state == 'pending'` or `'claimed'` only, so closed rows are never claimed. Add a test that pins this.
   - `_upsert_work` uses `ON CONFLICT (work_key) DO NOTHING`, so re-planning never reopens a closed row. Pin this too.
   - `plan_refresh` already refuses inactive or superseded mappings (`_eligible_mapping`).
   - Reopening is never implicit. It needs an explicit, reviewed tool.
3. **Reporting:**
   - `ELIGIBLE`/`DUE_SQL` already exclude inactive mappings.
   - The state `freshness` query and `quarantine_reporting` (PR #125) exclude `closed` from the population and report a `closed` count separately. History is kept, not hidden.
4. **Guarded close tool** (`scripts/`, dry run by default, `--apply` explicit), modelled on `yuyu_identity_capture_enqueue.py`. It closes a work row only if all of these hold:
   - the row is `blocked`;
   - its mapping is inactive;
   - exactly one active, approved, unsuperseded exact mapping exists on the same print and source;
   - that mapping's refresh work is `pending`.

   It is all or nothing and idempotent, and it never touches the active mapping, attempts, price states or RAW. Rollback: set `state='blocked'` and null the close fields for the listed ids.

## Release impact

`app/services/freshness_queue.py` and `operational_health_sql.py` are **collector runtime inputs**. If step 2 or 3 edits them,
the change is a collector release:
- one collector per safe slot, 06:00-23:00Z, all-or-nothing rollback;
- plus an API build for the migration (not 19:30-20:30Z).

If only the migration, the state tooling and the script change (no runtime module edit), there are 0 collector deployments. That is
possible because the existing state filters already skip any non-`pending` row. Prefer that path.

## First use

Work rows 2628, 2629 and 2630 (evidence: `evidence/yuyu-duplicates-evidence.json`; active mappings 1944, 1945 and 1437, all fresh).
