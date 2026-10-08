"""Session 7a read-only census since daily-v1 activation. No source HTTP, no writes."""
import sys, json
sys.path[:0] = ['/workspaces/cp-s7a/staging/scripts', '/workspaces/cp-s7a/staging/packages/opcg_source_identity/src', '/workspaces/cp-s4/tools']
import generate_staging_state as state
from opcg_source_identity.raw_payload import PREFIX
from db import connection
ACT = '2026-10-08T13:45:05Z'   # first activation (snkrdunk); last 13:56:11Z
MAXID = int(sys.argv[1]); out = sys.argv[2]
Q = {
 'ledger_by_collector': """select coalesce(split_part(a.claimed_by,':',1), case when s.name='snkrdunk' then 'snkrdunk-due' else 'unattributed:'||s.name end) collector,
     r.parser_version, count(*) rows, min(d.id) min_id, max(d.id) max_id, sum(d.original_bytes) original_bytes,
     sum(d.encoded_bytes) encoded_bytes, sum(pg_column_size(b.raw_content)) base_col_bytes
     from raw_snapshot_dictionaries d join raw_snapshots r on r.id=d.id join sources s on s.id=r.source_id
     join raw_snapshots b on b.id=d.base_snapshot_id
     left join freshness_attempts a on a.raw_snapshot_id=r.id
     where d.id>37711 and d.id<=%(m)s group by 1,2 order by 1,2""",
 'raw_since_activation': """select s.name, r.parser_version, r.http_status, (r.raw_content like %(p)s) encoded,
     exists(select 1 from raw_snapshot_dictionaries d where d.id=r.id) in_ledger,
     count(*) n, sum(pg_column_size(r.raw_content)) col_bytes, sum(octet_length(r.raw_content)) text_bytes
     from raw_snapshots r join sources s on s.id=r.source_id where r.fetched_at>=%(a)s and r.id<=(select max(id) from raw_snapshots where id<=%(rm)s)
     group by 1,2,3,4,5 order by 1,2,3,4,5""",
 'runs': """select service, count(*) runs,
     count(*) filter (where (context_json::jsonb->'work'->>'claimed')::int>0) work_runs,
     round(avg((context_json::jsonb->'identity'->>'runtime_seconds')::numeric) filter (where (context_json::jsonb->'work'->>'claimed')::int>0),1) avg_work_runtime_s,
     round(max((context_json::jsonb->'identity'->>'runtime_seconds')::numeric),1) max_runtime_s,
     sum((context_json::jsonb->'work'->>'claimed')::int) claimed, sum((context_json::jsonb->'work'->>'raw_snapshots')::int) raw_snapshots,
     sum((context_json::jsonb->'safety'->>'expired_claims')::int) expired_claims,
     sum((context_json::jsonb->'safety'->>'claims_remaining')::int) claims_remaining,
     sum((context_json::jsonb->'safety'->>'reservation_overruns')::int) reservation_overruns,
     sum((context_json::jsonb->'safety'->>'duplicate_requests')::int) duplicate_requests,
     sum((context_json::jsonb->'safety'->>'wrong_shard')::int) wrong_shard,
     sum((context_json::jsonb->'failure'->>'http_403')::int) http_403, sum((context_json::jsonb->'failure'->>'http_429')::int) http_429,
     sum((context_json::jsonb->'failure'->>'challenge')::int) challenge, sum((context_json::jsonb->'failure'->>'transient')::int) transient,
     sum((context_json::jsonb->'failure'->>'parsing')::int) parsing, sum((context_json::jsonb->'failure'->>'identity')::int) identity_fail,
     sum((context_json::jsonb->'failure'->>'unexpected_skip')::int) unexpected_skip,
     count(*) filter (where context_json::jsonb->'exit'->>'terminal_state'<>'completed') not_completed,
     array_agg(distinct context_json::jsonb->'identity'->>'deployment_id') deployments,
     array_agg(distinct context_json::jsonb->'identity'->>'revision') revisions,
     min(created_at) first, max(created_at) last
     from app_log_events where event_type='raw_execution_finished' and created_at>=%(a)s group by 1 order by 1""",
 'runs_post_activation': """with act(service, at) as (values ('snkrdunk-collector','2026-10-08 13:45:05Z'::timestamptz),('yuyutei-collector-shard-0','2026-10-08 13:46:16Z'),
     ('yuyutei-collector-shard-1','2026-10-08 13:47:37Z'),('yuyutei-collector-shard-2','2026-10-08 13:48:46Z'),('yuyutei-collector-shard-3','2026-10-08 13:50:06Z'),
     ('yuyutei-collector-shard-5','2026-10-08 13:51:20Z'),('yuyutei-collector-shard-6','2026-10-08 13:52:42Z'),('yuyutei-collector-shard-7','2026-10-08 13:53:46Z'),
     ('yuyutei-collector-shard-8','2026-10-08 13:55:17Z'),('yuyutei-collector-shard-4-v2','2026-10-08 13:56:11Z'))
     select e.service, count(*) runs, count(*) filter (where (e.context_json::jsonb->'work'->>'claimed')::int>0) work_runs,
     sum((e.context_json::jsonb->'work'->>'claimed')::int) claimed,
     round(avg((e.context_json::jsonb->'identity'->>'runtime_seconds')::numeric) filter (where (e.context_json::jsonb->'work'->>'claimed')::int>0),1) avg_work_s,
     round(max((e.context_json::jsonb->'identity'->>'runtime_seconds')::numeric),1) max_s,
     array_agg(distinct e.context_json::jsonb->'identity'->>'deployment_id') deployments
     from app_log_events e join act on act.service=e.service
     where e.event_type='raw_execution_finished' and (e.context_json::jsonb->'identity'->>'started_at')::timestamptz>=act.at group by 1 order by 1""",
 'started_without_finish': """select st.service, st.context_json::jsonb->'identity'->>'execution_id' ex, st.created_at from app_log_events st
     where st.event_type='raw_execution_started' and st.created_at>=%(a)s and not exists (select 1 from app_log_events f
     where f.event_type='raw_execution_finished' and f.context_json::jsonb->'identity'->>'execution_id'=st.context_json::jsonb->'identity'->>'execution_id')""",
 'attempt_outcomes': """select s.name, w.kind, a.outcome, count(*) n from freshness_attempts a join freshness_work w on w.id=a.work_id
     join sources s on s.id=w.source_id where a.claimed_at>=%(a)s group by 1,2,3 order by 1,2,3""",
 'peak_concurrent_yuyu_claims': """with a as (select a.claimed_at t0,coalesce(a.finished_at,now()) t1 from freshness_attempts a
     join freshness_work w on w.id=a.work_id join sources s on s.id=w.source_id where s.name='yuyutei' and a.claimed_at>=%(a)s)
     select coalesce(max(c),0) peak from (select (select count(*) from a b where b.t0<=x.t0 and b.t1>x.t0) c from a x) z""",
 'claims_now': """select s.name, count(*) filter (where w.claim_token is not null) claimed,
     count(*) filter (where w.claim_token is not null and w.claim_expires_at<now()) expired from freshness_work w join sources s on s.id=w.source_id group by 1""",
 'open_attempts': "select count(*) n, min(claimed_at) oldest from freshness_attempts where finished_at is null",
 'other_events': "select event_type, service, count(*) n from app_log_events where created_at>=%(a)s and event_type not like 'raw_execution_%%' group by 1,2",
 'due_work': """select s.name, count(*) total,
     count(*) filter(where ps.last_successfully_checked_at>=now()-interval '23 hours') le23h,
     count(*) filter(where ps.last_successfully_checked_at<now()-interval '23 hours' and ps.last_successfully_checked_at>=now()-interval '24 hours') h23_24,
     count(*) filter(where ps.last_successfully_checked_at<now()-interval '24 hours') gt24h,
     count(*) filter(where ps.last_successfully_checked_at is null) never_checked,
     count(*) filter(where w.next_due_at<=now() and w.state<>'blocked') due_unblocked,
     count(*) filter(where w.next_due_at<=now()) due_all,
     count(*) filter(where ps.last_successfully_checked_at<now()-interval '24 hours' or ps.last_successfully_checked_at is null) overdue_gt24_or_never,
     count(*) filter(where ps.retry_not_before_at>now()) backoff,
     count(*) filter(where w.state='claimed') claimed,
     count(*) filter(where w.state='claimed' and w.claim_expires_at<now()) expired_claims,
     count(*) filter(where w.state='blocked') blocked
     from freshness_work w join sources s on s.id=w.source_id
     join freshness_price_states ps on ps.work_id=w.id and ps.price_category='raw'
     where w.kind='refresh' group by 1 order by 1""",
 'budgets': "select s.name,b.request_limit,b.window_seconds,b.window_started_at,b.used_requests,b.reserved_requests,b.paused_until,b.pause_reason from source_dispatch_budgets b join sources s on s.id=b.source_id",
 'ledger_total': "select count(*) n, max(id) max_id from raw_snapshot_dictionaries",
 'db': "select pg_database_size(current_database()) db_bytes, pg_total_relation_size('raw_snapshots') raw_bytes, pg_total_relation_size('raw_snapshot_dictionaries') ledger_bytes, now()",
}
res = {'target': 'staging', 'read_only': True, 'source_requests': 0, 'database_writes': 0, 'since': ACT, 'max_ledger_id': MAXID}
with connection() as db:
    db.read_only = True
    for k, q in Q.items():
        res[k] = db.execute(q, {'a': ACT, 'm': MAXID, 'p': PREFIX + '%', 'rm': 10**12}).fetchall()
    db.rollback()
m = state.command_json(['railway', 'metrics', '-p', state.PROJECT, '-e', state.ENVIRONMENT, '-s', state.POSTGRES, '--since', '1d', '--volume', '--json'])
res['volume'] = {'observed_at': state.timestamp(), 'environment': m.get('environment'), 'service': m.get('service'),
                 'volumes': [v for v in m['volumes'] if v['name'] == 'postgres-volume']}
open(out, 'w').write(json.dumps(res, default=str, indent=1) + '\n')
for k, v in res.items():
    print(k, json.dumps(v, default=str)[:3000])
