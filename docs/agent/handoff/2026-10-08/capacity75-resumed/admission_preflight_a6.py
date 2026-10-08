"""Fresh staging-only fleet preflight; no source invocation or database write."""
import sys, json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path('/tmp/capacity75-native-a6c0809')
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'services/api'),str(ROOT/'packages/opcg_source_identity/src')]
import generate_staging_state as state
import mission_baseline as baseline
from resume_pr78_read import flags
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'services/api'),str(ROOT/'packages/opcg_source_identity/src')]
from psycopg.rows import dict_row
SHA='a6c080902895922ba60c4161d417255006b2bd1f'
OLD='49950079b6fad1e865a74b345e34b27e9e2955f3'
OUT=Path('/tmp/capacity75-read-20261008')
def main():
    env=state.staging_environment()
    edges=[r for r in env['serviceInstances']['edges'] if r['node']['serviceName'].startswith('yuyutei-collector-shard-') or r['node']['serviceName'] in {'snkrdunk-collector','optcg-price-tracker','worker','beat'}]
    with ThreadPoolExecutor(max_workers=3) as pool:fs=list(pool.map(flags,edges))
    assert len(fs)==13 and all(r['flags']['RAW_DICTIONARY_STORAGE_ENABLED'] in (None,'false') for r in fs)
    live=state.collect_live()
    assert live['repository']['sha']==SHA and live['database']['revision']==[{'version_num':'f9e5b4a8c012'}]
    import verify_yuyu_raw_reader_component as y
    import verify_snkr_published_discovery_component as s
    adoption={'yuyu':y.verify(live,SHA,OLD),'snkr':s.verify(live,SHA,snkr_expected=OLD,api_expected=SHA)}
    collectors=[r for r in fs if r['name'].startswith('yuyutei-collector-shard-') or r['name']=='snkrdunk-collector']
    recovery_query='query { '+ ' '.join(f'd{i}: deployment(id:"{r["deployment_id"]}") {{ id projectId environmentId serviceId status canRedeploy }}' for i,r in enumerate(collectors))+' }'
    recovery=state.railway(recovery_query)
    for i,r in enumerate(collectors):
        d=recovery[f'd{i}'];assert d['projectId']==state.PROJECT and d['environmentId']==state.ENVIRONMENT and d['serviceId']==r['service_id'] and d['status']=='SUCCESS' and d['canRedeploy']
    old=json.loads(Path('/workspaces/optcg-price-tracker/docs/agent/handoff/2026-10-07/capacity75/worker-beat-native-reader-identity.json').read_text())
    legacy=[]
    for proof in old['services']:
        n=next(r['node'] for r in edges if r['node']['serviceName']==proof['service'])
        assert n['latestDeployment']['id']==proof['deployment_id'] and n['latestDeployment']['meta']['commitHash']==proof['native_commit']
        f=next(r for r in fs if r['name']==proof['service'])
        assert f['flags']['LEGACY_PRICE_REFRESH_ENABLED'] in (None,'false') and f['flags']['DATA_RETENTION_ENABLED'] in (None,'false')
        legacy.append({'name':proof['service'],'deployment_id':proof['deployment_id'],'source_sha':proof['native_commit']})
    queries={
      'budgets':"select s.name,b.* from source_dispatch_budgets b join sources s on s.id=b.source_id order by s.name",
      'active_claims':"select s.name,count(*) active from freshness_attempts a join freshness_work w on w.id=a.work_id join sources s on s.id=w.source_id where a.outcome is null group by s.name",
      'actionable_raw':"select s.name,count(*) filter(where ps.last_successfully_checked_at is null) never,count(*) filter(where ps.last_successfully_checked_at<now()-interval '24 hours') older24,count(*) filter(where w.next_due_at<=now()) due from freshness_work w join sources s on s.id=w.source_id join freshness_price_states ps on ps.work_id=w.id and ps.price_category='raw' where w.state in ('pending','claimed') group by s.name",
      'protected_ledger':"select d.id,d.base_snapshot_id,d.original_sha256,d.original_bytes,r.content_hash,r.raw_content like 'OPCG_RAW_ZSTD_V1:%' encoded,pg_column_size(r.raw_content) physical_bytes from raw_snapshot_dictionaries d join raw_snapshots r on r.id=d.id order by d.id",
      'psa10':"select (select count(*) from freshness_price_states where price_category='psa10') states,(select count(*) from price_observations where price_type='psa10_asking') observations",
      'duplicate_exact':"select count(*) n from (select card_print_id,source_id from source_card_mappings where is_active and superseded_at is null and card_print_id is not null group by 1,2 having count(*)>1) g",
      'completed_intents':"select id,state,last_outcome,next_due_at from freshness_work where id in (3676,3677)",
      'latest_runs':"select distinct on(service) service,context_json from app_log_events where event_type='raw_execution_finished' and created_at>=now()-interval '3 hours' order by service,id desc",
    }
    with baseline.connection() as db:
        assert all(c.ok for c in state.guard.evaluate(state.guard.collect_facts(db),state.guard.expected_revisions_from_repo(str(ROOT))))
        db.row_factory=dict_row
        data={k:db.execute(q).fetchall() for k,q in queries.items()}
        from app.services.operational_health_sql import BUDGET_SQL
        data['operational_budgets']=db.execute(BUDGET_SQL).fetchall()
        assert all(not r['reservation_mismatch'] for r in data['operational_budgets'])
        for r in data['budgets']:
            if r['name']=='yuyutei':assert (r['request_limit'],r['window_seconds'])==(9000,1800)
            if r['name']=='snkrdunk':assert (r['request_limit'],r['window_seconds'])==(3100,1800)
            assert r['enabled'] and r['pause_reason'] is None and r['paused_until'] is None
            assert r['used_requests']+r['reserved_requests']<=r['request_limit']
        assert all(r['active']<=4 for r in data['active_claims'] if r['name']=='yuyutei')
        assert all(r['never']==r['older24']==0 for r in data['actionable_raw'])
        assert data['duplicate_exact'][0]['n']==0
        assert data['psa10'][0]['states']==data['psa10'][0]['observations']==0
        ledger=data['protected_ledger'];assert len(ledger)==16 and sum(r['encoded'] for r in ledger)==15
        previous=json.loads((OUT/'resume-census-20261008T031814.json').read_text())['queries']['ledger']
        assert [(r['id'],r['base_snapshot_id'],r['original_sha256'],r['original_bytes'],r['content_hash']) for r in ledger]==[(r['id'],r['base_snapshot_id'],r['original_sha256'],r['original_bytes'],r['content_hash']) for r in previous]
        assert len(data['completed_intents'])==2 and all(r['state']=='pending' and r['last_outcome']=='completed' for r in data['completed_intents'])
        db.rollback()
    metrics=state.command_json(['railway','metrics','-p',state.PROJECT,'-e',state.ENVIRONMENT,'-s',state.POSTGRES,'--since','1d','--volume','--json'])
    assert metrics['environment']=='staging' and metrics['service']=='Postgres'
    volume=next(v for v in metrics['volumes'] if v['name']=='postgres-volume')
    assert volume['limit_mb']==10000
    result={'target':'staging','observed_at':state.timestamp(),'source_sha':SHA,'installed_collector_sha':OLD,'source_requests':0,'database_writes':0,'source_jobs_triggered':0,'production_accessed':False,'flags':fs,'legacy':legacy,'adoption':adoption,'recovery_deployments':recovery,'queries':data,'volume':volume,'purpose':'AMBER ten-service native deployment of bounded claim wait and already merged bounded RAW query. No source job, cadence, budget, mapping, writer or migration changes.'}
    path=OUT/('admission-preflight-'+state.timestamp().replace(':','').replace('-','')[:15]+'.json')
    assert not path.exists();state.atomic_write(path,json.dumps(result,default=state.json_default,indent=2)+'\n')
    print(path)
if __name__=='__main__':
    try:main()
    except Exception as exc:
        import traceback
        print([(f.filename,f.lineno,f.name) for f in traceback.extract_tb(exc.__traceback__)])
        raise SystemExit('Admission preflight refused: '+type(exc).__name__) from None
