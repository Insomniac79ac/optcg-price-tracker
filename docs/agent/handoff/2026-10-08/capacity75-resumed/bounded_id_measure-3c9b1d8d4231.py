"""Read-only staging index/codec SELECT benchmark, zero source HTTP."""
import sys,json,hashlib,time
from pathlib import Path
ROOT=Path('/tmp/capacity75-native-4995007')
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'services/api'),str(ROOT/'packages/opcg_source_identity/src')]
import generate_staging_state as state
import mission_baseline as baseline
from psycopg.rows import dict_row
OUT=Path('/tmp/capacity75-read-20261008')
def main():
    result={'target':'staging','production_accessed':False,'source_requests':0,'database_writes':0,'benchmark_semantics':'SELECT-only installed lookup benchmark, not enabled writer or continuous storage proof.'}
    with baseline.connection() as db:
        assert all(c.ok for c in state.guard.evaluate(state.guard.collect_facts(db),state.guard.expected_revisions_from_repo(str(ROOT))))
        db.row_factory=dict_row
        result['observed_at']=state.timestamp()
        result['indexes']=db.execute("select indexname,indexdef,pg_relation_size(format('%I.%I',schemaname,indexname)::regclass) bytes from pg_indexes where schemaname=current_schema() and indexname in ('ix_raw_dictionary_created','ix_raw_snapshot_dictionary_scope') order by indexname").fetchall()
        assert len(result['indexes'])==2
        selected=db.execute("select distinct on(r.source_id,r.source_url) s.name,r.source_id,r.source_url,r.parser_version,r.id from raw_snapshots r join sources s on s.id=r.source_id where r.id>(select max(id)-1500 from raw_snapshots) and r.http_status=200 and r.parser_version in ('yuyutei-collector-v3','snkrdunk-collector-v2') order by r.source_id,r.source_url,r.id desc").fetchall()
        result['scoped_lookup']=[]
        for name in ('yuyutei','snkrdunk'):
            for r in [x for x in selected if x['name']==name][:12]:
                scope=(r['source_id'],r['parser_version'],r['source_url'],r['source_url'],'OPCG_RAW_ZSTD_V1:%')
                plans={}
                for direction,limit in [('desc',32),('asc',1)]:
                    q="EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) select id,raw_content like %s encoded from raw_snapshots where source_id=%s and parser_version=%s and md5(source_url)=md5(%s) and source_url=%s and http_status=200 order by id "+direction+" limit "+str(limit)
                    ids=db.execute('select id from raw_snapshots where source_id=%s and parser_version=%s and md5(source_url)=md5(%s) and source_url=%s and http_status=200 order by id '+direction+' limit '+str(limit),scope[:4]).fetchall()
                    plans[direction]=db.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) select id,raw_content like %s encoded from raw_snapshots where id=ANY(%s) order by id '+direction,(scope[4],[x['id'] for x in ids])).fetchone()['QUERY PLAN'][0]
                result['scoped_lookup'].append({'source':name,'latest_snapshot_id':r['id'],'plans':plans})
        result['ledger_plan']=db.execute("EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT count(*),coalesce(sum(encoded_bytes),0) FROM raw_snapshot_dictionaries WHERE created_at >= date_trunc('day', CURRENT_TIMESTAMP AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' AND created_at < (date_trunc('day',CURRENT_TIMESTAMP AT TIME ZONE 'UTC')+interval '1 day') AT TIME ZONE 'UTC'").fetchone()['QUERY PLAN'][0]
        result['raw_relation_bytes']=db.execute("select pg_total_relation_size('raw_snapshots') bytes").fetchone()['bytes']
        db.rollback()
    stamp=state.timestamp().replace(':','').replace('-','')[:15]
    path=OUT/f'bounded-id-measure-{stamp}.json';state.atomic_write(path,json.dumps(result,default=state.json_default,indent=2)+'\n')
    print(path);print('index_bytes',sum(r['bytes'] for r in result['indexes']));print('recent_lookup_ms',[(r['source'],r['plans']['desc']['Execution Time']) for r in result['scoped_lookup']])
if __name__=='__main__':
    try:main()
    except Exception as exc:raise SystemExit('Read-only index measurement refused: '+type(exc).__name__) from None
