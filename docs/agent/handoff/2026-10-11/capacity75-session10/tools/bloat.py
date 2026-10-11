"""Read-only bloat/growth diagnosis for source_mapping_proposal_groups (session 8).
Usage: python3 bloat.py [out.json]   (uses db.connection(): default_transaction_read_only=on)"""
import sys, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import connection

T = "source_mapping_proposal_groups"
Q = {
 "now": "select now() at time zone 'utc' as observed_at, current_setting('server_version') as server_version",
 "sizes": f"""select c.relname, pg_total_relation_size(c.oid) total, pg_relation_size(c.oid) heap,
   coalesce(pg_total_relation_size(c.reltoastrelid),0) toast, pg_indexes_size(c.oid) idx, c.reloptions, c.relpages, c.reltuples,
   s.n_live_tup,s.n_dead_tup,s.n_tup_ins,s.n_tup_upd,s.n_tup_hot_upd,s.n_tup_del,s.n_mod_since_analyze,
   s.last_vacuum,s.last_autovacuum,s.last_analyze,s.last_autoanalyze,s.vacuum_count,s.autovacuum_count,s.autoanalyze_count
   from pg_class c join pg_stat_user_tables s on s.relid=c.oid
   where c.relname in ('{T}','source_mapping_proposal_alternatives')""",
 "indexes": f"""select indexrelname, pg_relation_size(indexrelid) bytes, idx_scan, pg_get_indexdef(indexrelid) def
   from pg_stat_user_indexes where relname='{T}' order by 2 desc""",
 "autovacuum_settings": """select name, setting, unit from pg_settings where name like 'autovacuum%'
   or name in ('vacuum_cost_limit','vacuum_cost_delay','block_size')""",
 "extensions": "select extname, extversion from pg_extension",
 "row_width": f"""select count(*) n, count(*) filter (where superseded_at is null) current_rows,
   count(*) filter (where superseded_at is not null) superseded_rows,
   avg(pg_column_size(t.*))::int avg_row_bytes, sum(pg_column_size(t.*)) sum_row_bytes, max(pg_column_size(t.*)) max_row_bytes,
   avg(pg_column_size(evidence_summary_json))::int avg_evidence_bytes, sum(pg_column_size(evidence_summary_json)) sum_evidence_bytes,
   avg(pg_column_size(resolution_reasons_json))::int avg_reasons_bytes, avg(pg_column_size(source_url))::int avg_url_bytes
   from {T} t""",
 "alternatives_width": f"""select count(*) alts, count(*) filter (where g.superseded_at is not null) alts_of_superseded,
   avg(pg_column_size(a.*))::int avg_alt_bytes from source_mapping_proposal_alternatives a join {T} g on g.id=a.proposal_group_id""",
 "created_per_day": f"select date_trunc('day',created_at) d, count(*) n from {T} group by 1 order by 1",
 "superseded_per_day": f"select date_trunc('day',superseded_at) d, count(*) n from {T} where superseded_at is not null group by 1 order by 1",
 "created_per_hour_48h": f"select date_trunc('hour',created_at) h, count(*) n from {T} where created_at > now()-interval '48 hours' group by 1 order by 1",
 "versions_per_listing": f"""select n versions, count(*) listings from (select source_id, canonical_source_listing_identity, count(*) n
   from {T} group by 1,2) x group by n order by n""",
 "resolver_versions": f"select resolver_version, count(*) n, min(created_at), max(created_at) from {T} group by 1 order by 3",
 "new_since_1009": f"select count(*) n from {T} where created_at>='2026-10-09'",
 "new_since_1009_material_change": f"""select count(*) n from (select g.id from {T} g join {T} p
   on p.source_id=g.source_id and p.canonical_source_listing_identity=g.canonical_source_listing_identity
   and p.superseded_at between g.created_at and g.created_at+interval '1 minute'
   where g.created_at>='2026-10-09' and ((p.evidence_summary_json::jsonb - 'discovery_run_id')
   is distinct from (g.evidence_summary_json::jsonb - 'discovery_run_id')
   or p.resolution_status<>g.resolution_status or p.resolver_version<>g.resolver_version)) x""",
 "superseded_identical_to_current_minus_run_id": f"""select count(*) n from {T} g where superseded_at is not null
   and review_status='pending' and exists (select 1 from {T} c where c.source_id=g.source_id
   and c.canonical_source_listing_identity=g.canonical_source_listing_identity and c.superseded_at is null
   and c.resolver_version=g.resolver_version and c.resolution_status=g.resolution_status
   and (c.evidence_summary_json::jsonb - 'discovery_run_id')=(g.evidence_summary_json::jsonb - 'discovery_run_id'))""",
 "referencing_fks": f"select conrelid::regclass::text t, conname, confdeltype from pg_constraint where confrelid='{T}'::regclass",
}

def run():
    out = {"queries": Q, "results": {}}
    with connection() as db:
        for k, sql in Q.items():
            out["results"][k] = json.loads(json.dumps(db.execute(sql).fetchall(), default=str))
    return out

if __name__ == "__main__":
    r = run()
    path = sys.argv[1] if len(sys.argv) > 1 else None
    s = json.dumps(r, indent=1, default=str)
    if path:
        open(path, "w").write(s)
    else:
        print(s)
