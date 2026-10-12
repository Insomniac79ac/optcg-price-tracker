"""Read-only: stored bytes per refresh capture in [start,end) by source, from the rows each attempt wrote
(raw_snapshots row incl. raw_content, daily-v1 ledger encoded bytes, price_observations, the attempt row).
Heap/row sizes only; index overhead is applied separately from table totals. usage: per_capture.py <start> <end>"""
import json, sys
sys.path.insert(0, '/workspaces/cp-s10/docs/agent/handoff/2026-10-11/capacity75-session10/tools')
from db import connection
s, e = sys.argv[1:3]
with connection() as db:
    rows = db.execute("""select s.name, count(distinct a.id) attempts,
        sum(pg_column_size(r.*)) raw_row_bytes,
        (select coalesce(sum(d.encoded_bytes),0) from raw_snapshot_dictionaries d where d.created_at >= %(s)s::timestamptz and d.created_at < %(e)s::timestamptz) ledger_all_bytes,
        sum((select coalesce(sum(pg_column_size(o.*)),0) from price_observations o where o.raw_snapshot_id=a.raw_snapshot_id)) obs_bytes,
        sum(pg_column_size(a.*)) attempt_bytes
        from freshness_attempts a join freshness_work w on w.id=a.work_id join sources s on s.id=w.source_id
        left join raw_snapshots r on r.id=a.raw_snapshot_id
        where w.kind='refresh' and a.finished_at >= %(s)s::timestamptz and a.finished_at < %(e)s::timestamptz group by 1""", {'s': s, 'e': e}).fetchall()
    raw_all = db.execute("""select s.name, count(*) n, sum(pg_column_size(r.*)) bytes from raw_snapshots r join sources s on s.id=r.source_id
        where r.fetched_at >= %(s)s::timestamptz and r.fetched_at < %(e)s::timestamptz group by 1""", {'s': s, 'e': e}).fetchall()
    sizes = db.execute("""select relname, pg_total_relation_size(oid) total, pg_relation_size(oid) heap from pg_class
        where relname in ('raw_snapshots','price_observations','freshness_attempts','raw_snapshot_dictionaries','app_log_events','source_mapping_proposal_groups')""").fetchall()
    db.rollback()
print(json.dumps({'window': [s, e], 'per_source_refresh': rows, 'raw_snapshots_all_in_window': raw_all, 'relation_sizes': sizes}, indent=1, default=str))
