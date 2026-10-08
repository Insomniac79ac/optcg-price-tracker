"""Offline arithmetic; configured slots are never labelled measured throughput."""
import json
import statistics
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path

OUT=Path(__file__).parent
d=json.loads(sorted(OUT.glob('baseline-*.json'))[-1].read_text())
m=d['measurements']; now=datetime.fromisoformat(d['observed_at'])
def percentile(values,q):
    if not values:return None
    s=sorted(values); pos=(len(s)-1)*q; lo=int(pos)
    return s[lo]+(s[min(lo+1,len(s)-1)]-s[lo])*(pos-lo)
def stats(values):
    return {'n':len(values),'sum':sum(values),'p50':percentile(values,.5),
            'p95':percentile(values,.95),'max':max(values,default=None)}
by_owner=defaultdict(list)
for a in m['attempts72h']:by_owner[a['claimed_by']].append(a)
groups=defaultdict(list)
for r in m['natural_runs72h']:
    c=r['context_json']; i=c['identity']
    if datetime.fromisoformat(i['finished_at'])<now-timedelta(hours=24):continue
    if i['source']=='yuyutei' and i['revision'] not in {'3a084f29679509d378eb71f6acd79bad7bc41f3d','d65a523486290f5af480acb50907ff0b9976855c','bf4475a47ccdf8b06ef93a1a1cd4f29779834f64','a1c4a4f4b66df50a4be1e6119cc8675abc62bedf','c444790fcff71a99d6ff9fb548d133bc1b1dff66'}:continue
    aa=by_owner[i['execution_id']]
    c['measured_requests']=sum(a['actual_request_cost'] or 0 for a in aa)
    c['measured_raw_attempts']=sum(a['kind']=='refresh' for a in aa)
    c['measured_discovery_attempts']=sum(a['kind']=='discovery' for a in aa)
    c['observed_requests_per_minute']=c['measured_requests']*60/i['runtime_seconds'] if i['runtime_seconds'] else 0
    groups[(i['source'],i['shard'])].append(c)
summary={}
for (source,shard),runs in sorted(groups.items(),key=str):
    key=f'{source}:{shard}'
    summary[key]={
        'natural_completed_runs24h':len(runs),
        'active_runs24h':sum(c['work']['attempted']>0 for c in runs),
        'runtime_seconds_all':stats([c['identity']['runtime_seconds'] for c in runs]),
        'runtime_seconds_active':stats([c['identity']['runtime_seconds'] for c in runs if c['work']['attempted']]),
        'checks_per_execution':stats([c['work']['attempted'] for c in runs]),
        'requests_per_execution':stats([c['measured_requests'] for c in runs]),
        'requests_per_minute_active':stats([c['observed_requests_per_minute'] for c in runs if c['work']['attempted']]),
        'work':{k:sum(c['work'].get(k,0) or 0 for c in runs) for k in ('attempted','listed','no_listing','raw_snapshots','accepted_observations','completed','discovery_progress')},
        'failure':{k:sum(c['failure'].get(k,0) or 0 for c in runs) for k in runs[0]['failure']},
        'safety_max':{k:max(c['safety'].get(k,0) or 0 for c in runs) for k in ('claims_remaining','expired_claims','reservations_remaining','reservation_overruns','duplicate_requests','wrong_shard')},
        'deadline_miss_snapshot_max':max(c['freshness']['deadline_misses'] for c in runs),
        'stopped_reasons':dict(Counter(c['exit']['stopped_reason'] for c in runs)),
        'trigger_provenance':'unknown in receipts; ordinary due-path operation, no operator source invocation',
    }
item_groups=defaultdict(list)
for a in m['attempts72h']:
    if datetime.fromisoformat(a['finished_at'])>=now-timedelta(hours=24):
        item_groups[(a['name'],a['kind'],a['outcome'])].append(a)
items={str(k):{'attempts':len(v),'request_cost':stats([a['actual_request_cost'] or 0 for a in v]),
              'runtime_seconds':stats([float(a['runtime_seconds'] or 0) for a in v])} for k,v in item_groups.items()}
result={'observed_at':d['observed_at'],'source_http':0,'database_writes':0,'natural_runs':summary,
        'attempt_outcomes24h':items,'database_bytes':d['database_bytes'],'relations':m['relations'],
        'raw_daily7d':m['raw_daily7d'],'workload':m['workload'],
        'storage_semantics':'pg_column_size measures PostgreSQL stored/compressed payload sizes; relation bytes include TOAST/index/page overhead. Calendar boundary days are partial. One-shot artwork captures are separated from recurring RAW costs.',
        'unknowns':['R2 total footprint/quota until staging-only bucket ownership verified','provider log retention byte usage','ephemeral disk not reported by provider disk metric']}
(OUT/('analysis-'+now.strftime('%Y%m%dT%H%M%SZ')+'.json')).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'natural_runs':summary,'attempts':items},indent=2))
