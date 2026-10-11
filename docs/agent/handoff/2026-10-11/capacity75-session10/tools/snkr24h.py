"""Read-only SNKRDUNK 24h detail: per-window requests (time series), per-turn homepage RAW,
turn counts, failures/denials, and the Yuyu window series. usage: snkr24h.py <start> <end> <out.json>"""
import json, sys
sys.path.insert(0, '/workspaces/cp-s10/docs/agent/handoff/2026-10-11/capacity75-session10/tools')
from db import connection
start, end, out_path = sys.argv[1:4]
ANCHOR = '2026-10-10 07:23:57.124648+00'
p = {'s': start, 'e': end}
out = {'read_only': True, 'window': [start, end]}
with connection() as db:
    out['observed_at'] = db.execute("select now() at time zone 'utc' t").fetchone()['t']
    out['windows'] = db.execute(f"""select s.name, to_char(to_timestamp(extract(epoch from timestamptz '{ANCHOR}') + 1800*floor((extract(epoch from a.finished_at)-extract(epoch from timestamptz '{ANCHOR}'))/1800)) at time zone 'utc','MM-DD HH24:MI') win,
        count(*) n, sum(a.actual_request_cost) req from freshness_attempts a join freshness_work w on w.id=a.work_id join sources s on s.id=w.source_id
        where a.finished_at >= %(s)s::timestamptz and a.finished_at < %(e)s::timestamptz group by 1,2 order by 1,2""", p).fetchall()
    out['snkr_turns'] = db.execute("""select count(*) runs,
        count(*) filter (where (context_json->'work'->>'attempted')::int > 0) runs_with_work,
        sum((context_json->'work'->>'attempted')::int) attempted,
        sum((context_json->'failure'->>'transient')::int + (context_json->'failure'->>'parsing')::int + (context_json->'failure'->>'identity')::int) failures,
        sum((context_json->'failure'->>'http_403')::int) http_403, sum((context_json->'failure'->>'http_429')::int) http_429,
        sum((context_json->'failure'->>'challenge')::int) challenge,
        sum((context_json->'safety'->>'expired_claims')::int + (context_json->'safety'->>'reservation_overruns')::int + (context_json->'safety'->>'duplicate_requests')::int + (context_json->'safety'->>'wrong_shard')::int) safety_faults
        from app_log_events where event_type='raw_execution_finished' and service='snkrdunk-collector'
        and created_at >= %(s)s::timestamptz and created_at < %(e)s::timestamptz""", p).fetchone()
    out['homepage_per_turn'] = db.execute("""with t as (select created_at, (context_json->'work'->>'attempted')::int att,
          lag(created_at) over (order by created_at) prev from app_log_events where event_type='raw_execution_finished' and service='snkrdunk-collector'
          and created_at >= %(s)s::timestamptz - interval '1 hour' and created_at < %(e)s::timestamptz)
        select t.created_at, t.att, (select count(*) from raw_snapshots r join sources s on s.id=r.source_id where s.name='snkrdunk'
          and r.source_url='https://snkrdunk.com/' and r.fetched_at > coalesce(t.prev, t.created_at - interval '1 hour') and r.fetched_at <= t.created_at) homepage
        from t where t.created_at >= %(s)s::timestamptz and t.att > 0 order by 1""", p).fetchall()
    out['snkr_by_hour'] = db.execute("""select to_char(date_trunc('hour', a.finished_at at time zone 'utc'),'MM-DD HH24') h, a.outcome, count(*) n, sum(a.actual_request_cost) req
        from freshness_attempts a join freshness_work w on w.id=a.work_id join sources s on s.id=w.source_id
        where s.name='snkrdunk' and a.finished_at >= %(s)s::timestamptz and a.finished_at < %(e)s::timestamptz group by 1,2 order by 1,2""", p).fetchall()
    out['snkr_due_state'] = db.execute("""select w.state, count(*) n, count(*) filter (where w.next_due_at < now()) due_now from freshness_work w join sources s on s.id=w.source_id
        where s.name='snkrdunk' group by 1 order by 1""").fetchall()
    db.rollback()
json.dump(out, open(out_path, 'w'), indent=1, default=str)
for r in out['windows']: print(r)
print(out['snkr_turns'])
hp = out['homepage_per_turn']; print('turns_with_work', len(hp), 'homepage rows', sum(r['homepage'] for r in hp), 'max per turn', max([r['homepage'] for r in hp] or [0]))
for r in out['snkr_by_hour']: print(r)
print(out['snkr_due_state'])
