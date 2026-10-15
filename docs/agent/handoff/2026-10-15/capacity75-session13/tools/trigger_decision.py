"""Read-only: session-12 rollback-trigger decision for the a504e47 resolver-1.3 release.

1. First full recurring discovery cycle: when every recurring (non-parked) Yuyu discovery item
   had a completed attempt on a504e47, and whether all 1.2 pending groups were re-versioned once.
2. The 24 h after that cycle: new proposal versions (rows created), by source, resolver, status.
3. Early signal: versions created 2026-10-13 01:12-04:15Z (repeat pass) vs the 915 baseline.
4. Approved exact counts, proofs, approved superseded/demoted, reviews (auto-approval), failures.
usage: trigger_decision.py > out.json
"""
import json, sys
sys.path.insert(0, '/workspaces/cp-cap13/docs/agent/handoff/2026-10-15/capacity75-session13/tools')
from db import connection

MERGE = '2026-10-11 15:51:23+00'
ROLLOUT_END = '2026-10-11 16:31:08+00'
PARKED = '2100-01-01'
Q = {
 'now': "select now() at time zone 'utc' t",
 'recurring_items': f"""select count(*) n,
     count(*) filter (where last_attempted_at > '{ROLLOUT_END}') attempted_on_a504e47,
     count(*) filter (where last_success_at > '{ROLLOUT_END}') succeeded_on_a504e47
     from freshness_work where source_id=1 and kind='discovery' and next_due_at < '{PARKED}'""",
 'recurring_first_attempts': f"""select w.id, min(a.started_at) first_start, min(a.finished_at) first_finish,
     (array_agg(a.outcome order by a.started_at))[1] first_outcome, count(*) attempts
     from freshness_work w join freshness_attempts a on a.work_id=w.id
     where w.source_id=1 and w.kind='discovery' and w.next_due_at < '{PARKED}' and a.started_at > '{ROLLOUT_END}'
     group by w.id order by first_finish""",
 'discovery_attempts_by_day': f"""select date_trunc('day', a.started_at) d, a.outcome, count(*) n, sum(a.actual_request_cost) req
     from freshness_attempts a join freshness_work w on w.id=a.work_id
     where w.source_id=1 and w.kind='discovery' and a.started_at > '{ROLLOUT_END}' group by 1,2 order by 1,2""",
 'discovery_failures_since_rollout': f"""select count(*) n from freshness_attempts a join freshness_work w on w.id=a.work_id
     where w.source_id=1 and w.kind='discovery' and a.started_at > '{ROLLOUT_END}' and a.outcome not in ('completed')""",
 'pending_resolver_1_2_current': """select source_id, count(*) n from source_mapping_proposal_groups
     where superseded_at is null and review_status='pending' and resolver_version like '%%1.2' group by 1""",
 'current_by_resolver': """select source_id, resolver_version, review_status, count(*) n from source_mapping_proposal_groups
     where superseded_at is null group by 1,2,3 order by 1,2,3""",
 'listings_versioned_more_than_once_since_merge': f"""select source_id, count(*) listings from (
     select source_id, source_listing_key, count(*) c from source_mapping_proposal_groups
     where created_at > '{MERGE}' group by 1,2 having count(*) > 1) x group by 1""",
 'versions_by_hour_since_merge': f"""select source_id, date_trunc('hour', created_at) h, resolver_version, count(*) n
     from source_mapping_proposal_groups where created_at > '{MERGE}' group by 1,2,3 order by 2,1""",
 'approved_now': """select source_id,
     count(*) filter (where review_status='approved' and resolution_status='exact') approved_exact,
     count(*) filter (where review_status='approved' and resolution_status='exact'
                      and evidence_summary_json::jsonb ? 'positive_physical_artwork_proof') approved_with_proof
     from source_mapping_proposal_groups where superseded_at is null group by 1 order by 1""",
 'approved_superseded_since_merge': f"""select count(*) n from source_mapping_proposal_groups
     where review_status='approved' and superseded_at > '{MERGE}'""",
 'approved_demoted_or_changed_since_merge': f"""select count(*) n from source_mapping_proposal_groups
     where reviewed_at <= '{MERGE}' and review_status <> 'approved' and updated_at > '{MERGE}'
     and id in (select id from source_mapping_proposal_groups where review_status='approved')""",
 'reviews_since_merge': f"""select source_id, review_status, resolution_status, reviewed_by, count(*) n
     from source_mapping_proposal_groups where reviewed_at > '{MERGE}' group by 1,2,3,4""",
 'approved_created_since_merge': f"""select count(*) n from source_mapping_proposal_groups
     where review_status='approved' and created_at > '{MERGE}'""",
 'active_mappings': """select source_id, count(*) n from source_card_mappings where is_active group by 1 order by 1""",
 'table_sizes': """select pg_total_relation_size('source_mapping_proposal_groups') groups_bytes,
     pg_total_relation_size('source_mapping_proposal_alternatives') alts_bytes,
     (select count(*) from source_mapping_proposal_groups) group_rows""",
}
out = {}
with connection() as db:
    for k, sql in Q.items():
        try:
            out[k] = db.execute(sql).fetchall()
        except Exception as e:  # report a bad column name instead of hiding it
            db.rollback(); out[k] = {'error': str(e).splitlines()[0]}
    db.rollback()
print(json.dumps(out, indent=1, default=str))
