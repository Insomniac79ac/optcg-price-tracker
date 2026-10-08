"""Read-only exact due timestamps and proposed dictionary query costs; no source HTTP."""
import json
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
import generate_staging_state as state
import mission_baseline as baseline
OUT=Path(__file__).parent

def main():
    result={'target':'staging','source_http':0,'database_writes':0,'production_accessed':False}
    with baseline.connection() as db:
        db.read_only=True
        db.isolation_level=psycopg.IsolationLevel.REPEATABLE_READ
        checks=state.guard.evaluate(state.guard.collect_facts(db),state.guard.expected_revisions_from_repo(str(state.ROOT)))
        assert all(c.ok for c in checks)
        db.row_factory=dict_row
        result['observed_at']=db.execute('select now() now').fetchone()['now']
        result['raw_due_inputs']=db.execute('''
            select s.name,m.id mapping_id,m.id%9 shard,w.id work_id,w.state,w.priority,
             w.next_due_at,w.estimated_request_cost,w.claim_expires_at,
             ps.last_successfully_checked_at,ps.retry_not_before_at,w.last_outcome,
             ps.consecutive_failures
            from freshness_work w join sources s on s.id=w.source_id
            join source_card_mappings m on m.id=w.source_card_mapping_id
            join freshness_price_states ps on ps.work_id=w.id and ps.price_category='raw'
            where w.kind='refresh' and w.state in ('pending','claimed')
             and m.is_active and m.superseded_at is null and m.review_status='approved'
            order by s.name,w.next_due_at,m.id''').fetchall()
        result['discovery_due_inputs']=db.execute('''
            select s.name,w.id work_id,w.state,w.scope_key,w.priority,w.next_due_at,
             w.estimated_request_cost,w.claim_expires_at
            from freshness_work w join sources s on s.id=w.source_id
            where w.kind='discovery' and w.state in ('pending','claimed')
             and w.next_due_at<=now()+interval '48 hours'
            order by s.name,w.next_due_at,w.id''').fetchall()
        result['max_mapping_id']=db.execute('select max(id) id from source_card_mappings').fetchone()['id']
        result['budgets']=db.execute('select s.name,b.* from source_dispatch_budgets b join sources s on s.id=b.source_id').fetchall()
        selected=db.execute('''select * from (select s.name,r.source_id,r.parser_version,r.source_url,r.id,
            row_number() over(partition by r.source_id order by r.id desc) position
            from raw_snapshots r join sources s on s.id=r.source_id
            where r.http_status=200 and r.parser_version in ('yuyutei-collector-v3','snkrdunk-collector-v2')) ranked
            where position<=20 order by position,name''').fetchall()
        seen=set();queries=[]
        for row in selected:
            key=(row['source_id'],row['source_url'],row['parser_version'])
            if key in seen:continue
            seen.add(key)
            plan=db.execute('''EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON)
              select id,pg_column_size(raw_content) from raw_snapshots
              where source_id=%s and source_url=%s and parser_version=%s
               and http_status=200 and raw_content not like %s
              order by id desc limit 1''',(*key,'OPCG_RAW_ZSTD_V1:%')).fetchone()['QUERY PLAN'][0]
            queries.append({'source':row['name'],'snapshot_id':row['id'],
              'same_url_query_execution_ms':plan['Execution Time'],
              'planning_ms':plan['Planning Time'],'plan':plan['Plan']})
            if len(queries)>=12:break
        result['dictionary_query_benchmark']=queries
        result['benchmark_semantics']='Read-only PostgreSQL query benchmark on retained staging rows, not natural enabled-writer runtime proof. No FOR SHARE locks or body transfers. Full natural runtime must still be measured.'
        db.rollback()
    stamp=result['observed_at'].strftime('%Y%m%dT%H%M%SZ')
    path=OUT/f'capacity-inputs-{stamp}.json';assert not path.exists()
    state.atomic_write(path,json.dumps(result,default=state.json_default,indent=2)+'\n')
    print(path)
    print('actionable_raw',len(result['raw_due_inputs']),'ordinary_discovery_next48h',len(result['discovery_due_inputs']))
    print('dictionary_queries_ms',[q['same_url_query_execution_ms'] for q in queries])

if __name__=='__main__':main()
