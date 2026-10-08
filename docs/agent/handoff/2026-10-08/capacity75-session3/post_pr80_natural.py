"""Read-only natural operation since PR80 collector rollout (05:21:50Z). No source HTTP, no writes."""
import json
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
import generate_staging_state as state
import mission_baseline as baseline
OUT=Path(__file__).parent
SINCE='2026-10-08T05:21:50Z'
Q={
 'runs':"""select service,count(*) runs,min(created_at) first,max(created_at) last,
   sum((context_json::jsonb->>'claimed')::int) claimed_sum,
   jsonb_agg(context_json::jsonb - 'raw_snapshot_ids' order by created_at) ctx
   from app_log_events where event_type='raw_execution_finished' and created_at>=%(s)s group by 1 order by 1""",
 'attempts':"""select s.name,w.kind,a.outcome,count(*) n,max(extract(epoch from a.finished_at-a.started_at)) max_runtime,
   sum(a.actual_request_cost) requests from freshness_attempts a join freshness_work w on w.id=a.work_id
   join sources s on s.id=w.source_id where a.started_at>=%(s)s group by 1,2,3 order by 1,2,3""",
 'peak_concurrent_yuyu_claims':"""with a as (select a.started_at t0,coalesce(a.finished_at,now()) t1 from freshness_attempts a
   join freshness_work w on w.id=a.work_id join sources s on s.id=w.source_id where s.name='yuyutei' and a.started_at>=%(s)s)
   select coalesce(max(c),0) peak from (select (select count(*) from a b where b.t0<=x.t0 and b.t1>x.t0) c from a x) z""",
 'yuyu_freshness':"""select count(*) filter(where ps.last_successfully_checked_at<now()-interval '24 hours') over24h,
   count(*) filter(where ps.last_successfully_checked_at between now()-interval '24 hours' and now()-interval '23 hours') h23_24,
   count(*) filter(where w.state='pending' and w.next_due_at<=now()) due, count(*) filter(where w.state='claimed') claimed,
   count(*) filter(where w.state='claimed' and w.claim_expires_at<now()) expired
   from freshness_work w join sources s on s.id=w.source_id join freshness_price_states ps on ps.work_id=w.id and ps.price_category='raw'
   where s.name='yuyutei' and w.kind='refresh' and w.state<>'blocked'""",
 'denials':"""select s.name,a.outcome,count(*) from freshness_attempts a join freshness_work w on w.id=a.work_id join sources s on s.id=w.source_id
   where a.started_at>=now()-interval '24 hours' and a.outcome not in ('captured','no_listing','completed') group by 1,2""",
 'writers_ledger':"select count(*) n from raw_snapshot_dictionaries",
 'budgets':"select s.name,b.request_limit,b.window_seconds,b.used_requests,b.reserved_requests from source_dispatch_budgets b join sources s on s.id=b.source_id",
}
with baseline.connection() as db:
    db.read_only=True; db.isolation_level=psycopg.IsolationLevel.REPEATABLE_READ; db.row_factory=dict_row
    r={'observed_at':db.execute('select now() n').fetchone()['n'],'since':SINCE,'target':'staging','source_http':0,'database_writes':0,'production_accessed':False}
    for k,q in Q.items():
        with db.transaction():
            try: r[k]=db.execute(q,{'s':SINCE}).fetchall()
            except Exception as e: r[k]={'unknown':repr(e)}
    db.rollback()
stamp=r['observed_at'].strftime('%Y%m%dT%H%M%SZ')
state.atomic_write(OUT/f'post-pr80-natural-{stamp}.json',json.dumps(r,default=state.json_default,indent=2)+'\n')
for k in Q:
    v=r[k]
    if k=='runs': v=[{x:y for x,y in row.items() if x!='ctx'} for row in v]
    print(k,json.dumps(v,default=str)[:1500])
