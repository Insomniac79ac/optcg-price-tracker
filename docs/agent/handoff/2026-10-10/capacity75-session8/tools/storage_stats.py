"""Read-only storage snapshot: relation sizes, tuple stats (heap + TOAST), DB size."""
import json, sys
sys.path.insert(0, '/workspaces/cp-s8/docs/agent/handoff/2026-10-10/capacity75-session8/tools')
from db import connection
Q = {
 'db': "select now() at time zone 'utc' observed_at, pg_database_size(current_database()) db_bytes",
 'tables': """select c.relname, pg_total_relation_size(c.oid) total, pg_relation_size(c.oid) heap,
   pg_relation_size(c.reltoastrelid) toast, pg_indexes_size(c.oid) idx, s.n_live_tup, s.n_dead_tup,
   s.n_tup_ins, s.n_tup_upd, s.n_tup_hot_upd, s.n_tup_del, s.last_autovacuum, s.autovacuum_count, s.last_autoanalyze
   from pg_class c join pg_stat_user_tables s on s.relid=c.oid
   where c.relname in ('raw_snapshots','raw_snapshot_dictionaries','source_mapping_proposal_groups','freshness_attempts','freshness_work','price_observations')""",
 'toast': """select t.relname, pg_relation_size(t.oid) bytes, s.n_live_tup, s.n_dead_tup, s.n_tup_ins, s.n_tup_upd, s.n_tup_del,
   s.last_autovacuum, s.autovacuum_count from pg_class c join pg_class t on t.oid=c.reltoastrelid
   join pg_stat_all_tables s on s.relid=t.oid where c.relname in ('raw_snapshots','source_mapping_proposal_groups')""",
 'ledger_today': """select count(*) rows, coalesce(sum(encoded_bytes),0) bytes, max(id) max_id from raw_snapshot_dictionaries
   where created_at >= date_trunc('day', now() at time zone 'utc') at time zone 'utc'""",
 'raw_max_id': "select max(id) max_id from raw_snapshots",
}
out = {}
with connection() as db:
    for k, q in Q.items():
        out[k] = db.execute(q).fetchall()
print(json.dumps(out, default=str, indent=1))
