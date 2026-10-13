"""Read-only: versions in the 24 h after the first full cycle, early-signal window, listings
versioned more than once. usage: trigger_window.py <cycle_end_utc> > out.json"""
import json, sys
sys.path.insert(0, '/workspaces/cp-cap12/docs/agent/handoff/2026-10-13/capacity75-session12/tools')
from db import connection
END = sys.argv[1]
MERGE = '2026-10-11 15:51:23+00'
Q = {
 'now': "select now() at time zone 'utc' t",
 'window': f"select timestamptz '{END}' start_utc, timestamptz '{END}' + interval '24 hours' end_utc",
 'versions_24h_after_cycle': f"""select source_id, resolver_version, review_status, resolution_status, count(*) n
     from source_mapping_proposal_groups where created_at > timestamptz '{END}'
     and created_at <= timestamptz '{END}' + interval '24 hours' group by 1,2,3,4 order by 5 desc""",
 'versions_24h_total': f"""select count(*) n from source_mapping_proposal_groups where created_at > timestamptz '{END}'
     and created_at <= timestamptz '{END}' + interval '24 hours'""",
 'early_signal_2026_10_13_0112_0415': """select count(*) n, min(created_at), max(created_at) from source_mapping_proposal_groups
     where created_at >= '2026-10-13 01:12+00' and created_at < '2026-10-13 04:16+00'""",
 'early_signal_attempts': """select count(*) n, count(*) filter (where a.outcome='completed') completed, sum(a.actual_request_cost) req
     from freshness_attempts a join freshness_work w on w.id=a.work_id
     where w.source_id=1 and w.kind='discovery' and a.started_at >= '2026-10-13 01:12+00' and a.started_at < '2026-10-13 04:16+00'""",
 'what_superseded_in_window': f"""select old.resolver_version, old.review_status, count(*) n from source_mapping_proposal_groups old
     where old.superseded_at > timestamptz '{END}' and old.superseded_at <= timestamptz '{END}' + interval '24 hours' group by 1,2""",
 'listings_versioned_more_than_once_since_merge': f"""select source_id, count(*) listings, max(c) max_versions from (
     select source_id, canonical_source_listing_identity, count(*) c from source_mapping_proposal_groups
     where created_at > '{MERGE}' group by 1,2 having count(*) > 1) x group by 1""",
 'reasons_for_window_versions': f"""select r.reason, count(*) n from source_mapping_proposal_groups g,
     jsonb_array_elements_text(coalesce(g.resolution_reasons_json::jsonb,'[]'::jsonb)) r(reason)
     where g.created_at > timestamptz '{END}' and g.created_at <= timestamptz '{END}' + interval '24 hours'
     group by 1 order by 2 desc limit 15""",
}
out = {}
with connection() as db:
    for k, sql in Q.items():
        try: out[k] = db.execute(sql).fetchall()
        except Exception as e: db.rollback(); out[k] = {'error': str(e).splitlines()[0]}
    db.rollback()
print(json.dumps(out, indent=1, default=str))
