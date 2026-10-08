"""Pinned, read-only natural-operation and physical-storage census. No source HTTP."""
import json
from pathlib import Path
from datetime import datetime, timezone
import psycopg
from psycopg.rows import dict_row
import generate_staging_state as state
import mission_baseline as baseline

OUT = Path(__file__).parent
QUERIES = {
    "relations": """select c.relname, pg_total_relation_size(c.oid) total_bytes,
        pg_table_size(c.oid) table_bytes, pg_indexes_size(c.oid) index_bytes,
        c.reltuples estimated_rows, st.n_live_tup,st.n_dead_tup,st.last_autovacuum
        from pg_class c join pg_namespace n on n.oid=c.relnamespace
        left join pg_stat_user_tables st on st.relid=c.oid
        where n.nspname='public' and c.relkind='r'
        order by total_bytes desc""",
    "indexes": """select tablename,indexname,pg_relation_size(indexrelid) bytes
        from pg_indexes i join pg_stat_user_indexes s on s.indexrelname=i.indexname
        where i.schemaname='public' order by bytes desc""",
    "budgets": """select s.name,b.* from source_dispatch_budgets b
        join sources s on s.id=b.source_id""",
    "natural_runs72h": """select id,created_at,service,context_json from app_log_events
        where event_type='raw_execution_finished' and created_at>=now()-interval '72 hours'
        order by created_at""",
    "attempts72h": """select a.id,a.work_id,a.claimed_by,a.started_at,a.finished_at,a.outcome,
        a.actual_request_cost,a.charged_request_cost,a.raw_snapshot_id,s.name,w.kind,
        m.id%9 shard, extract(epoch from a.finished_at-a.started_at) runtime_seconds
        from freshness_attempts a join freshness_work w on w.id=a.work_id
        join sources s on s.id=w.source_id
        left join source_card_mappings m on m.id=w.source_card_mapping_id
        where a.finished_at>=now()-interval '72 hours' order by a.finished_at""",
    "raw_daily7d": """select date_trunc('day',r.fetched_at) as day_utc,s.name,
        count(*) snapshots, sum(pg_column_size(r.raw_content)) stored_payload_bytes,
        sum(pg_column_size(r)) stored_row_bytes
        from raw_snapshots r join sources s on s.id=r.source_id
        where r.fetched_at>=now()-interval '7 days' group by 1,2 order by 1,2""",
    "raw_hourly24h": """select date_trunc('hour',r.fetched_at) as hour_utc,s.name,
        count(*) snapshots,sum(pg_column_size(r.raw_content)) stored_payload_bytes
        from raw_snapshots r join sources s on s.id=r.source_id
        where r.fetched_at>=now()-interval '24 hours' group by 1,2 order by 1,2""",
    "observation_daily7d": """select date_trunc('day',observed_at) as day_utc,source_id,
        count(*) rows,sum(pg_column_size(p)) row_bytes from price_observations p
        where observed_at>=now()-interval '7 days' group by 1,2 order by 1,2""",
    "events_daily7d": """select date_trunc('day',created_at) as day_utc,count(*) rows,
        sum(pg_column_size(a)) row_bytes from app_log_events a
        where created_at>=now()-interval '7 days' group by 1 order by 1""",
    "workload": """select s.name,m.id%9 shard,w.kind,w.state,
        count(*) total,count(*) filter(where w.next_due_at<=now()) due,
        count(*) filter(where ps.last_successfully_checked_at>=now()-interval '23 hours') within23h,
        count(*) filter(where ps.last_successfully_checked_at<now()-interval '23 hours'
        and ps.last_successfully_checked_at>=now()-interval '24 hours') between23and24h,
        count(*) filter(where ps.last_successfully_checked_at<now()-interval '24 hours') over24h,
        count(*) filter(where ps.last_successfully_checked_at is null) never_checked,
        count(*) filter(where ps.retry_not_before_at>now()) backoff,
        count(*) filter(where w.state='claimed' and w.claim_expires_at<now()) expired_claims,
        min(w.next_due_at) oldest_next_due
        from freshness_work w join sources s on s.id=w.source_id
        left join source_card_mappings m on m.id=w.source_card_mapping_id
        left join freshness_price_states ps on ps.work_id=w.id and ps.price_category='raw'
        where ps.price_category='raw'
        group by 1,2,3,4 order by 1,2,3,4""",
    "next_due24h": """select s.name,m.id%9 shard,
        floor(greatest(extract(epoch from w.next_due_at-now()),0)/1800)::int half_hour,
        count(*) items from freshness_work w join sources s on s.id=w.source_id
        join source_card_mappings m on m.id=w.source_card_mapping_id
        where w.kind='refresh' and w.state in ('pending','claimed')
        and m.is_active and m.superseded_at is null and m.review_status='approved'
        and exists(select 1 from freshness_price_states ps where ps.work_id=w.id and ps.price_category='raw') and w.next_due_at<=now()+interval '24 hours'
        group by 1,2,3 order by 1,3,2""",
    "raw_body_reference72h": """select s.name,w.kind,count(*) bodies,
        avg(pg_column_size(r.raw_content)) mean_stored_bytes,
        percentile_cont(.95) within group(order by pg_column_size(r.raw_content)) p95_stored_bytes,
        max(pg_column_size(r.raw_content)) max_stored_bytes
        from freshness_attempts a join freshness_work w on w.id=a.work_id
        join sources s on s.id=w.source_id join raw_snapshots r on r.id=a.raw_snapshot_id
        where a.finished_at>=now()-interval '72 hours' group by 1,2""",
    "locks": "select * from job_locks",
    "object_columns": """select table_name,column_name,data_type from information_schema.columns
        where table_schema='public' and (column_name like '%object%' or column_name like '%storage%'
        or column_name like '%byte%' or column_name like '%size%') order by 1,2""",
}

def main():
    result = {"target": "staging", "source_http": 0, "database_writes": 0,
              "production_accessed": False, "queries": QUERIES, "measurements": {}}
    with baseline.connection() as db:
        db.read_only = True
        db.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        checks = state.guard.evaluate(state.guard.collect_facts(db),
                                      state.guard.expected_revisions_from_repo(str(state.ROOT)))
        assert all(c.ok for c in checks)
        db.row_factory = dict_row
        result["observed_at"] = db.execute('select now() now').fetchone()['now']
        result["database_bytes"] = db.execute('select pg_database_size(current_database()) bytes').fetchone()['bytes']
        for name, sql in QUERIES.items():
            started = datetime.now(timezone.utc)
            with db.transaction():
                try:
                    rows = db.execute(sql).fetchall()
                    result["measurements"][name] = rows
                except Exception as exc:
                    result["measurements"][name] = {"unknown": type(exc).__name__}
                    rows = []
            print(name, len(rows), round((datetime.now(timezone.utc)-started).total_seconds(),3), flush=True)
        db.rollback()
    stamp = result['observed_at'].strftime('%Y%m%dT%H%M%SZ')
    path = OUT / f'baseline-{stamp}.json'
    assert not path.exists()
    state.atomic_write(path, json.dumps(result, default=state.json_default, indent=2)+'\n')
    print(path)

if __name__ == '__main__':
    main()
