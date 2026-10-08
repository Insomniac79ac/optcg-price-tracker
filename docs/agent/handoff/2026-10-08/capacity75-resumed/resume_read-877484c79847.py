"""Pinned staging SELECT/provider-only resume census. No source requests."""
import sys, json, hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path('/tmp/capacity75-resume-20261008')
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'services/api'), str(ROOT/'packages/opcg_source_identity/src')]
import generate_staging_state as state
import mission_baseline as baseline
from psycopg.rows import dict_row
from opcg_source_identity.raw_payload import PREFIX, decode, sha256

OUT=Path('/tmp/capacity75-read-20261008')
SHA='c444790fcff71a99d6ff9fb548d133bc1b1dff66'

def flags(edge):
    n=edge['node']
    v=state.command_json(['railway','variable','list','-p',state.PROJECT,'-e',state.ENVIRONMENT,'-s',n['serviceId'],'--json'])
    try:
        assert v['RAILWAY_PROJECT_ID']==state.PROJECT and v['RAILWAY_ENVIRONMENT_ID']==state.ENVIRONMENT
        keys=['RAW_DICTIONARY_STORAGE_ENABLED','RAW_DICTIONARY_STORAGE_MODE','APP_ENV','SCRAPING_MODE','LEGACY_PRICE_REFRESH_ENABLED','MARKET_WORKFLOW_ENABLED','DATA_RETENTION_ENABLED','MOCK_MODE','RAW_RETENTION_ENABLED','PSA10_ENABLED','SNKRDUNK_PSA10_ENABLED','YUYUTEI_ENABLED','SNKRDUNK_ENABLED','YUYUTEI_DISCOVERY_ENABLED','COLLECTORS_ENABLED']
        return {'name':n['serviceName'],'service_id':n['serviceId'],'flags':{k:v.get(k) for k in keys},'schedule':n.get('cronSchedule'),'start_command':n.get('startCommand'),'deployment_id':(n.get('latestDeployment') or {}).get('id')}
    finally:v.clear()

def main():
    e=state.staging_environment()
    edges=[r for r in e['serviceInstances']['edges'] if r['node']['serviceName'].startswith('yuyutei-collector-shard-') or r['node']['serviceName'] in {'snkrdunk-collector','optcg-price-tracker','worker','beat'}]
    with ThreadPoolExecutor(max_workers=3) as pool: fs=list(pool.map(flags,edges))
    live=state.collect_live()
    assert live['repository']['sha']==SHA
    import verify_yuyu_raw_reader_component as y
    import verify_snkr_published_discovery_component as s
    adoption={'yuyu':y.verify(live,SHA,SHA),'snkr':s.verify(live,SHA,SHA,SHA)}
    result={'target':'staging','observed_at':state.timestamp(),'source_requests':0,'database_writes':0,'production_accessed':False,'flags':fs,'adoption':adoption,'queries':{}}
    with baseline.connection() as db:
        assert all(c.ok for c in state.guard.evaluate(state.guard.collect_facts(db),state.guard.expected_revisions_from_repo(str(ROOT))))
        db.row_factory=dict_row
        queries={
          'ledger':"select d.*,r.source_id,s.name,r.content_hash,r.fetched_at,r.source_url,pg_column_size(r.raw_content) stored_bytes,r.raw_content like 'OPCG_RAW_ZSTD_V1:%' encoded from raw_snapshot_dictionaries d join raw_snapshots r on r.id=d.id join sources s on s.id=r.source_id order by d.id",
          'completed_intents':"select id,scope_key,state,last_outcome,next_due_at,attempt_count from freshness_work where id in (3676,3677)",
          'next_snkr':"select min(next_due_at) next_due,count(*) rows from freshness_work w join sources s on s.id=w.source_id where s.name='snkrdunk' and w.state='pending' and kind='refresh'",
          'owners24h':"select distinct split_part(a.claimed_by,':',1) owner,s.name,w.kind from freshness_attempts a join freshness_work w on w.id=a.work_id join sources s on s.id=w.source_id where a.started_at>=now()-interval '24 hours' order by 2,1,3",
          'psa10':"select (select count(*) from freshness_price_states where price_category='psa10') states,(select count(*) from price_observations where price_type='psa10_asking') observations",
          'database_size':"select pg_database_size(current_database()) bytes",
          'latest_runs':"select distinct on(service) service,context_json from app_log_events where event_type='raw_execution_finished' and created_at>=now()-interval '3 hours' order by service,id desc",
        }
        for name,q in queries.items():
            print('READ',name,flush=True)
            result['queries'][name]=db.execute(q).fetchall()
        old=json.loads(Path('/workspaces/optcg-price-tracker/docs/agent/handoff/2026-10-07/capacity75/worker-beat-native-reader-identity.json').read_text())
        result['legacy_reader_identity']=[]
        for proof in old['services']:
            node=next(r['node'] for r in edges if r['node']['serviceName']==proof['service'])
            assert node['latestDeployment']['id']==proof['deployment_id']
            assert node['latestDeployment']['meta']['commitHash']==proof['native_commit']
            fsrow=next(r for r in fs if r['name']==proof['service'])
            assert fsrow['flags']['LEGACY_PRICE_REFRESH_ENABLED'] in (None,'false')
            assert fsrow['flags']['DATA_RETENTION_ENABLED'] in (None,'false')
            result['legacy_reader_identity'].append({'service':proof['service'],'deployment_id':proof['deployment_id'],'source':proof['native_commit'],'legacy_price_refresh_enabled':False,'data_retention_enabled':False})
        result['lossless_original_canary']=[]
        rawout=OUT/('original-canary-raw-'+state.timestamp().replace(':','').replace('-','')[:15])
        rawout.mkdir(exist_ok=False)
        originals=db.execute('''select d.*,r.source_url,r.source_id,r.parser_version,
          r.fetched_at,r.content_hash,r.raw_content stored,b.raw_content base_stored,
          b.content_hash base_hash,b.source_url base_url,b.source_id base_source,
          b.parser_version base_parser
          from raw_snapshot_dictionaries d join raw_snapshots r on r.id=d.id
          join raw_snapshots b on b.id=d.base_snapshot_id order by d.id''').fetchall()
        assert len(originals)==16
        for row in originals:
            # Retain received stored values before decoding; all source evidence
            # was already persisted by its natural capture, not fetched here.
            state.atomic_write(rawout/f'{row["id"]}.stored',row['stored'])
            state.atomic_write(rawout/f'{row["base_snapshot_id"]}.base',row['base_stored'])
            assert row['base_snapshot_id']<row['id']
            assert (row['source_url'],row['source_id'],row['parser_version'])==(row['base_url'],row['base_source'],row['base_parser'])
            base_body=row['base_stored'].encode()
            assert not row['base_stored'].startswith(PREFIX)
            assert sha256(base_body)==row['base_hash']==row['base_sha256']
            body=decode(row['stored'],expected_hash=row['content_hash'],load_base=lambda _,b=base_body:b) if row['stored'].startswith(PREFIX) else row['stored'].encode()
            assert sha256(body)==row['content_hash']==row['original_sha256']
            assert len(body)==row['original_bytes']
            retained=Path('/workspaces/optcg-price-tracker/docs/agent/handoff/2026-10-07/capacity75-resumed/natural-plaintext')/f'{row["id"]}.html'
            assert retained.read_bytes()==body
            result['lossless_original_canary'].append({'id':row['id'],'base_id':row['base_snapshot_id'],'original_sha256':sha256(body),'original_bytes':len(body),'encoded':row['stored'].startswith(PREFIX),'fetched_at':row['fetched_at'],'previous_retained_plaintext_identical':True})
        db.rollback()
    stamp=state.timestamp().replace(':','').replace('-','')[:15]
    path=OUT/f'resume-census-{stamp}.json'
    assert not path.exists()
    state.atomic_write(path,json.dumps(result,default=state.json_default,indent=2)+'\n')
    print(path)
    print(json.dumps({'all10_adoption':'verified','ledger_rows':len(result['queries']['ledger']),'encoded':sum(r['encoded'] for r in result['queries']['ledger']),'next_snkr':result['queries']['next_snkr'],'psa10':result['queries']['psa10'],'database_size':result['queries']['database_size'],'writers':{r['name']:r['flags']['RAW_DICTIONARY_STORAGE_ENABLED'] for r in fs}},default=state.json_default))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        import traceback
        print([(f.filename,f.lineno,f.name) for f in traceback.extract_tb(exc.__traceback__)])
        raise SystemExit('Read census refused: '+type(exc).__name__) from None
