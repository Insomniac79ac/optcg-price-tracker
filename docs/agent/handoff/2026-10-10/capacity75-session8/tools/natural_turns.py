"""Read-only: completed natural runs per collector on a given revision, with work/failure/safety sums.
usage: natural_turns.py <revision> <out.json>"""
import json, sys
sys.path.insert(0, '/workspaces/cp-s8/docs/agent/handoff/2026-10-10/capacity75-session8/tools')
from db import connection
rev, out_path = sys.argv[1:3]
SQL = """select service, count(*) runs, min(created_at) first, max(created_at) last,
  count(*) filter (where context_json->'exit'->>'terminal_state'='completed') completed,
  sum((context_json->'work'->>'attempted')::int) attempted, sum((context_json->'work'->>'raw_snapshots')::int) raw,
  sum((context_json->'work'->>'accepted_observations')::int) accepted,
  sum((context_json->'failure'->>'transient')::int + (context_json->'failure'->>'parsing')::int + (context_json->'failure'->>'identity')::int) failures,
  sum((context_json->'failure'->>'http_403')::int + (context_json->'failure'->>'http_429')::int + (context_json->'failure'->>'challenge')::int) denials,
  sum((context_json->'failure'->>'optional_resource')::int) optional_resource,
  sum((context_json->'safety'->>'expired_claims')::int + (context_json->'safety'->>'reservation_overruns')::int + (context_json->'safety'->>'duplicate_requests')::int + (context_json->'safety'->>'wrong_shard')::int) safety_faults,
  max((context_json->'identity'->>'runtime_seconds')::float) max_runtime_s,
  array_agg(distinct context_json->'identity'->>'deployment_id') deployments
  from app_log_events where event_type='raw_execution_finished' and context_json->'identity'->>'revision'=%s
  group by service order by service"""
with connection() as db:
    now = db.execute("select now() at time zone 'utc' t").fetchone()['t']
    rows = db.execute(SQL, (rev,)).fetchall()
    db.rollback()
out = {'observed_at': now, 'revision': rev, 'read_only': True, 'services': rows}
open(out_path, 'w').write(json.dumps(out, indent=1, default=str) + '\n')
for r in rows:
    print(r['service'], r['runs'], r['completed'], 'att', r['attempted'], 'raw', r['raw'], 'fail', r['failures'], 'den', r['denials'], 'opt', r['optional_resource'], 'safety', r['safety_faults'], 'maxrt', round(r['max_runtime_s'] or 0, 1), [d[:8] for d in r['deployments']])
print(now)
