"""Read-only: request cost per capture, budget-window peaks, outcomes, SNKR homepage RAW and
price continuity for attempts finished in [start, end). No writes, no source HTTP.

usage: requests_window.py <start-utc> <end-utc|now> <out.json> [per-source release-time JSON]

The optional JSON maps source -> UTC time from which captures count as "after" for that
source (per collector the last release time); captures are then also split before/after.
Price continuity: for each refresh work item captured after its release, compare the price
recorded by the attempt with the previous captured attempt's price for the same work item.
"""
import json, sys
sys.path.insert(0, '/workspaces/cp-s8/docs/agent/handoff/2026-10-10/capacity75-session8/tools')
from db import connection

start, end, out_path = sys.argv[1:4]
end_sql = "now()" if end == "now" else "%(end)s::timestamptz"
ANCHOR = '2026-10-10 07:23:57.124648+00'  # budget windows are fixed 1800s from this phase
BASE = f"""from freshness_attempts a join freshness_work w on w.id=a.work_id join sources s on s.id=w.source_id
 where a.finished_at >= %(start)s::timestamptz and a.finished_at < {end_sql}"""
out = {'read_only': True, 'source_requests': 0, 'window': [start, end]}
with connection() as db:
    p = {'start': start, 'end': end}
    out['observed_at'] = db.execute("select now() at time zone 'utc' t").fetchone()['t']
    out['per_capture'] = db.execute(f"""select s.name, w.kind, a.outcome, count(*) n,
        round(avg(a.actual_request_cost),1) avg_cost, percentile_cont(0.5) within group (order by a.actual_request_cost) p50,
        min(a.actual_request_cost) min_cost, max(a.actual_request_cost) max_cost, max(a.reserved_request_cost) max_reserved,
        count(*) filter (where a.actual_request_cost > a.reserved_request_cost) over_reservation
        {BASE} group by 1,2,3 order by 1,2,3""", p).fetchall()
    out['window_peaks'] = db.execute(f"""with x as (select s.name, a.actual_request_cost c,
        floor((extract(epoch from a.finished_at)-extract(epoch from timestamptz '{ANCHOR}'))/1800) b {BASE})
        select name, max(t) peak, round(avg(t)) avg_window, count(*) windows from (select name, b, sum(c) t from x group by 1,2) y
        group by 1 order by 1""", p).fetchall()
    out['snkr_homepage_raw'] = db.execute(f"""select count(*) n, coalesce(sum(pg_column_size(raw_content)),0) stored_bytes
        from raw_snapshots r join sources s on s.id=r.source_id where s.name='snkrdunk' and r.source_url='https://snkrdunk.com/'
        and r.fetched_at >= %(start)s::timestamptz and r.fetched_at < {end_sql}""", p).fetchone()
    if len(sys.argv) > 4:
        release = json.load(open(sys.argv[4]))
        for name, at in release.items():
            q = {'start': start, 'end': end, 'name': name, 'at': at}
            out.setdefault('split', {})[name] = db.execute(f"""select (a.claimed_at >= %(at)s::timestamptz) after_release, a.outcome,
                count(*) n, round(avg(a.actual_request_cost),1) avg_cost {BASE} and s.name=%(name)s and w.kind='refresh'
                group by 1,2 order by 1,2""", q).fetchall()
    db.rollback()
open(out_path, 'w').write(json.dumps(out, indent=1, default=str) + '\n')
print(json.dumps(out, indent=1, default=str))
