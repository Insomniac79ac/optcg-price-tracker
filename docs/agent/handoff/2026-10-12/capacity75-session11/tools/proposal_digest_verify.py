"""Read-only: natural verification of the resolver 1.3 proposal-digest release (a504e47).

Measures, since the PR #103 merge / rollout:
- Yuyu discovery attempts and failures on a504e47, and first-cycle progress over the
  recurring (non-parked) discovery items;
- new proposal versions (rows created) by source, resolver, status and hour, plus groups
  reused (touched but not re-created);
- approved exact counts, approved-with-proof, approved superseded / re-reviewed since the
  merge (replacement, demotion or auto-approval);
- proposal table sizes.
usage: proposal_digest_verify.py > out.json
"""
import json, sys
sys.path.insert(0, '/workspaces/cp-s11/docs/agent/handoff/2026-10-12/capacity75-session11/tools')
from db import connection

MERGE = '2026-10-11 15:51:23+00'      # PR #103 merge
ROLLOUT_END = '2026-10-11 16:31:08+00'  # last collector on a504e47 (receipt completed_at)
PARKED = '2100-01-01'                   # completed explicit identity captures, never re-run

Q = {
 'now': "select now() at time zone 'utc' t",
 'discovery_attempts': f"""select a.outcome, count(*) n, min(a.started_at) first, max(a.finished_at) last,
     sum(a.actual_request_cost) requests from freshness_attempts a join freshness_work w on w.id=a.work_id
     where w.source_id=1 and w.kind='discovery' and a.started_at > '{ROLLOUT_END}' group by 1""",
 'discovery_cycle': f"""select (next_due_at >= '{PARKED}') parked, state, count(*) n,
     count(*) filter (where last_attempted_at > '{ROLLOUT_END}') attempted_on_a504e47,
     min(next_due_at) filter (where last_attempted_at <= '{ROLLOUT_END}') next_unattempted_due,
     max(next_due_at) filter (where last_attempted_at <= '{ROLLOUT_END}') last_unattempted_due
     from freshness_work where source_id=1 and kind='discovery' group by 1,2 order by 1,2""",
 'discovery_failures': f"""select w.id, w.state, w.last_failure, w.last_failure_at from freshness_work w
     where w.source_id=1 and w.kind='discovery' and w.last_failure_at > '{ROLLOUT_END}'""",
 'stored_differs_errors': f"""select count(*) n from freshness_work where last_failure_at > '{MERGE}'
     and last_failure ilike '%%stored proposal differs%%'""",
 'versions_since_merge': f"""select source_id, resolver_version, review_status, resolution_status, count(*) n
     from source_mapping_proposal_groups where created_at > '{MERGE}' group by 1,2,3,4 order by 1,5 desc""",
 'versions_by_hour': f"""select source_id, date_trunc('hour', created_at) h, count(*) n from source_mapping_proposal_groups
     where created_at > now() - interval '72 hours' group by 1,2 order by 2,1""",
 'versions_by_day': """select source_id, date_trunc('day', created_at) d, count(*) n from source_mapping_proposal_groups
     where created_at > now() - interval '14 days' group by 1,2 order by 2,1""",
 'reused_since_merge': f"""select source_id, count(*) n from source_mapping_proposal_groups
     where created_at <= '{MERGE}' and updated_at > '{MERGE}' and superseded_at is null group by 1""",
 'superseded_since_merge': f"""select source_id, review_status, resolution_status, count(*) n
     from source_mapping_proposal_groups where superseded_at > '{MERGE}' group by 1,2,3 order by 1,4 desc""",
 'approved_now': """select source_id,
     count(*) filter (where review_status='approved' and resolution_status='exact') approved_exact,
     count(*) filter (where review_status='approved' and resolution_status='exact'
                      and evidence_summary_json::jsonb ? 'positive_physical_artwork_proof') approved_with_proof,
     count(*) filter (where review_status='approved' and resolution_status<>'exact') approved_not_exact,
     count(*) current_groups
     from source_mapping_proposal_groups where superseded_at is null group by 1 order by 1""",
 'approved_superseded_since_merge': f"""select count(*) n from source_mapping_proposal_groups
     where review_status='approved' and superseded_at > '{MERGE}'""",
 'reviews_since_merge': f"""select source_id, review_status, resolution_status, reviewed_by, count(*) n
     from source_mapping_proposal_groups where reviewed_at > '{MERGE}' group by 1,2,3,4""",
 'approved_created_since_merge': f"""select count(*) n from source_mapping_proposal_groups
     where review_status='approved' and created_at > '{MERGE}'""",
 'table_sizes': """select pg_total_relation_size('source_mapping_proposal_groups') groups_bytes,
     pg_total_relation_size('source_mapping_proposal_alternatives') alts_bytes,
     (select count(*) from source_mapping_proposal_groups) group_rows,
     (select count(*) from source_mapping_proposal_alternatives) alt_rows""",
}

out = {}
with connection() as db:
    for k, sql in Q.items():
        out[k] = db.execute(sql).fetchall()
    db.rollback()
print(json.dumps(out, indent=1, default=str))
