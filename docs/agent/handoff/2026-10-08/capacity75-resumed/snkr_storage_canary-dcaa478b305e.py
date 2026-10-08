"""Fresh bounded SNKR config canary; never dispatches source work."""
import argparse, hashlib, json, subprocess, sys
from pathlib import Path
ROOT=Path('/tmp/capacity75-native-4995007')
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'services/api'),str(ROOT/'packages/opcg_source_identity/src')]
import generate_staging_state as state
import mission_baseline as baseline
from resume_pr78_read import flags
from psycopg.rows import dict_row
SHA='49950079b6fad1e865a74b345e34b27e9e2955f3'
SID='2d7ab69b-ec1f-4c66-8da1-9c8769a6d14a'
NAME='snkrdunk-collector'
OUT=Path('/tmp/capacity75-read-20261008')
ACTIVATION=OUT/'snkr-storage-canary-activation-4995007.json'
def set_variables(enabled):
    args=['railway','variable','set','-p',state.PROJECT,'-e',state.ENVIRONMENT,'-s',SID,
          'RAW_DICTIONARY_STORAGE_ENABLED='+('true' if enabled else 'false'),
          'RAW_DICTIONARY_STORAGE_MODE=canary','APP_ENV=staging']
    r=subprocess.run(args,capture_output=True,text=True,timeout=90)
    if r.returncode:raise RuntimeError('Pinned SNKR configuration change failed')
def main():
    p=argparse.ArgumentParser();p.add_argument('--activate',action='store_true');p.add_argument('--off',action='store_true');p.add_argument('--delivery',type=Path);a=p.parse_args()
    assert not(a.activate and a.off)
    env=state.staging_environment()
    edges=[r for r in env['serviceInstances']['edges'] if r['node']['serviceName'].startswith('yuyutei-collector-shard-') or r['node']['serviceName'] in {'snkrdunk-collector','optcg-price-tracker','worker','beat'}]
    before=[flags(r) for r in edges]
    target=next(r for r in before if r['service_id']==SID)
    assert target['name']==NAME and target['schedule']=='27,57 * * * *' and target['start_command']=='python -m snkrdunk_collector.collect --due-work'
    if a.off:
        set_variables(False)
        stamp=state.timestamp().replace(':','').replace('-','')[:15]
        state.atomic_write(OUT/f'snkr-storage-canary-off-{stamp}.json',json.dumps({'target':'staging','observed_at':state.timestamp(),'service_id':SID,'before':target,'requested_writer':False,'mode':'canary','source_jobs_triggered':0,'production_accessed':False},indent=2)+'\n')
        print('SNKR writer OFF requested; effective deployment/natural receipt still requires verification');return
    assert len(before)==13
    assert all(r['flags']['RAW_DICTIONARY_STORAGE_ENABLED'] in (None,'false') for r in before)
    assert not ACTIVATION.exists()
    assert a.delivery and a.delivery.exists()
    delivery=json.loads(a.delivery.read_text())
    assert delivery['expected_commit']==SHA and delivery['migration_revision']=='f9e5b4a8c012' and delivery['production_accessed'] is False
    assert delivery['sale_invariant']['sale_index_inputs']==delivery['sale_invariant']['gap_receipts']==0
    live=state.collect_live()
    import verify_yuyu_raw_reader_component as y
    import verify_snkr_published_discovery_component as s
    adoption={'yuyu':y.verify(live,SHA,SHA),'snkr':s.verify(live,SHA,SHA,SHA)}
    snapshot=state.write_snapshot(live,Path('/workspaces/optcg-price-tracker/docs/agent/CURRENT_STATE.yaml'))
    with baseline.connection() as db:
        assert all(c.ok for c in state.guard.evaluate(state.guard.collect_facts(db),state.guard.expected_revisions_from_repo(str(ROOT))))
        db.row_factory=dict_row
        ledger=db.execute('select count(*) used,max(id) last_id from raw_snapshot_dictionaries').fetchone()
        assert ledger['used']==16
        assert db.execute("select count(*) n from pg_indexes where schemaname=current_schema() and indexname in ('ix_raw_dictionary_created','ix_raw_snapshot_dictionary_scope')").fetchone()['n']==2
        from app.services.operational_health_sql import BUDGET_SQL
        budget=next(r for r in db.execute(BUDGET_SQL).fetchall() if r['name']=='snkrdunk')
        assert not budget['reservation_mismatch']
        raw_budget=db.execute("select b.* from source_dispatch_budgets b join sources s on s.id=b.source_id where s.name='snkrdunk'").fetchone()
        assert raw_budget['enabled'] and raw_budget['pause_reason'] is None and raw_budget['paused_until'] is None
        assert raw_budget['request_limit']==3100 and raw_budget['window_seconds']==1800 and raw_budget['used_requests']+raw_budget['reserved_requests']<=3100
        assert db.execute("select count(*) n from freshness_attempts where claimed_by like 'snkrdunk-due:%' and outcome is null").fetchone()['n']==0
        assert db.execute("select count(*) n from freshness_work w join freshness_price_states ps on ps.work_id=w.id and ps.price_category='raw' where w.state in ('pending','claimed') and (ps.last_successfully_checked_at is null or ps.last_successfully_checked_at<now()-interval '24 hours')").fetchone()['n']==0
        assert db.execute("select count(*) n from freshness_price_states where price_category='psa10'").fetchone()['n']==0
        assert db.execute("select count(*) n from freshness_work where id in (3676,3677) and last_outcome='completed' and next_due_at>now()+interval '365 days'").fetchone()['n']==2
        next_due=db.execute("select min(next_due_at) next_due from freshness_work w join sources s on s.id=w.source_id where s.name='snkrdunk' and kind='refresh' and state='pending'").fetchone()
        db.rollback()
    metrics=state.command_json(['railway','metrics','-p',state.PROJECT,'-e',state.ENVIRONMENT,'-s',state.POSTGRES,'--since','1d','--volume','--json'])
    assert metrics['environment']=='staging' and metrics['service']=='Postgres'
    volume=next(v for v in metrics['volumes'] if v['name']=='postgres-volume')
    free=(volume['limit_mb']-max(volume['current_mb'],volume['max_mb']))*1000000
    assert volume['limit_mb']==10000 and free>3*1024**3+(200-ledger['used'])*8*1024**2
    receipt={'target':'staging','classification':'AMBER','observed_at':state.timestamp(),'source_sha':SHA,'schema':'f9e5b4a8c012','before':before,'service_id':SID,'mode':'canary','global_all_time_limit':200,'global_already_charged':ledger['used'],'remaining_global_rows':200-ledger['used'],'worst_recovery_plaintext_bytes':(200-ledger['used'])*8*1024**2,'reserve_bytes':3*1024**3,'volume':volume,'free_bytes':free,'adoption':adoption,'next_regular_due':next_due,'source_jobs_triggered':0,'source_requests_added':0,'production_accessed':False,'mapping_writes':0,'writer_changes':1,'exact_variables':['RAW_DICTIONARY_STORAGE_ENABLED','RAW_DICTIONARY_STORAGE_MODE','APP_ENV'],'source_requests':'Only existing ordinary scheduled due work; no intent creation, due advancement, cron/budget/pacing change or replay.','rollback':'Run this exact helper --off. Disables only SNKR and restores canary mode, retaining staging APP_ENV/readers/f9/e8/dependencies and protected old rows. OFF path tested. This is config containment, not historical RAW expansion.','recovery':'Retain newly encoded and base values before independent hash/length decode. Any expansion must select only new writer-owned IDs under existing OFF expand_snapshot, with separately rechecked space. Original35175 recovery never replayed.','failure_triggers':['hash or source/parser/fullURL/older-base/price lineage mismatch','source403/429/challenge or duplicate/uncontrolled requests','lease/reservation/singleton failure','new actionable >24h backlog','RAW run runtime greater than previous293.052s plus10s; investigate before continuity activation','physical volume reserve threatened'],'observation':'Wait for first two positive scheduled RAW turns or40 encodings, then OFF promptly. Empty turns are not writer proof. Global200 safeguard remains if monitoring delayed. Validate independent byte hashes, ledger/index overhead, natural runtime and budget safety. Daily mode remains OFF.','delivery_sha256':hashlib.sha256(a.delivery.read_bytes()).hexdigest(),'current_state':snapshot['evidence'],'official_checked':'2026-10-08 Railway5.62.1 local help, docs.railway.com/cli/variable, variables, cron-jobs, integrations/api/manage-variables'}
    stamp=state.timestamp().replace(':','').replace('-','')[:15]
    state.atomic_write(OUT/f'snkr-storage-canary-preflight-{stamp}.json',json.dumps(receipt,default=state.json_default,indent=2)+'\n')
    if a.activate:
        set_variables(True)
        receipt['activated_at']=state.timestamp()
        state.atomic_write(ACTIVATION,json.dumps(receipt,default=state.json_default,indent=2)+'\n')
    print(json.dumps({'activated':a.activate,'remaining_global_rows':200-ledger['used'],'next_regular_due':next_due,'free_bytes':free},default=state.json_default))
if __name__=='__main__':
    try:main()
    except Exception as exc:
        import traceback
        print([(f.filename,f.lineno,f.name) for f in traceback.extract_tb(exc.__traceback__)])
        raise SystemExit('SNKR storage safeguard refused: '+type(exc).__name__) from None
