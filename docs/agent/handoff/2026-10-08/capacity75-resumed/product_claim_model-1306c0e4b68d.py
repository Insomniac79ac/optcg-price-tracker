"""Forecast from exact staging due times, measured request/runtime bounds. Not natural proof."""
import json,heapq,copy
from pathlib import Path
from datetime import datetime
from collections import Counter
OUT=Path(__file__).parent
d=json.loads(sorted(OUT.glob('capacity-inputs-*.json'))[-1].read_text())
b=json.loads(sorted(OUT.glob('baseline-*.json'))[-1].read_text())
origin=datetime.fromisoformat(d['observed_at']).timestamp()
raw=[{'id':r['work_id'],'due':datetime.fromisoformat(r['next_due_at']).timestamp()-origin,'shard':r['shard'],'reserve':r['estimated_request_cost'],'kind':'refresh','lane':'high' if r['priority']==100 else 'ordinary','interval':10800 if r['priority']==100 else 82800} for r in d['raw_due_inputs'] if r['name']=='yuyutei']
disco=[{'id':r['work_id'],'due':datetime.fromisoformat(r['next_due_at']).timestamp()-origin,'shard':None,'reserve':r['estimated_request_cost'],'kind':'discovery','lane':'discovery','interval':86400} for r in d['discovery_due_inputs'] if r['name']=='yuyutei']
cycle=['high','ordinary','high','discovery','high','ordinary','high','coverage']

def model(batch,added=0,seconds=8.2,boot=302,cadence=1800,active_cap=9,stagger=180,reserve=300,captures=0,capture_seconds=90.237,capture_spacing=0):
    jobs=copy.deepcopy(raw+disco)
    for j in jobs:
        if j['kind']=='refresh':j['reserve']=reserve
    # Planned future population is phased uniformly; first-source capture/review is separate.
    for i in range(added):jobs.append({'id':100000+i,'due':i*82800/max(1,added),'shard':(3329+i)%9,'reserve':reserve,'kind':'refresh','lane':'ordinary','interval':82800})
    for i in range(captures):jobs.append({'id':200000+i,'due':i*capture_spacing,'shard':None,'reserve':100,'kind':'discovery','lane':'discovery','interval':86400*36500,'seconds':capture_seconds,'requests':60})
    start_budget=next(r for r in d.get('budgets',b['measurements']['budgets']) if r['name']=='yuyutei')
    reset=datetime.fromisoformat(start_budget['window_started_at']).timestamp()-origin
    used=start_budget['used_requests'];reserved=start_budget['reserved_requests'];seq=start_budget['claim_sequence']
    events=[];busy=[False]*9;counts=[0]*9;stop=[0]*9
    for shard in range(9):
        offset=shard*stagger
        first=((int(origin)//cadence)*cadence + offset%cadence+boot)-origin
        while first<=0:first+=cadence
        heapq.heappush(events,(first,0,shard,None))
    late=[];checks=0;requests=0;max_reserved=0;skipped=0;admission=0;max_active=0;active=0;per_window=[];turns=0
    horizon=72*3600
    while events:
        t,event,shard,j=heapq.heappop(events)
        if t>horizon:break
        if t>=reset+1800:
            per_window.append(used);reset+=int((t-reset)//1800)*1800;used=0
        if event==0:
            heapq.heappush(events,(t+cadence,0,shard,None))
            if busy[shard]:skipped+=1;continue
            busy[shard]=True;counts[shard]=0;stop[shard]=t+1020;turns+=1
        else:
            reserved-=j['reserve'];used+=j.get('requests',56);requests+=j.get('requests',56);checks+=1;active-=1
            if j['kind']=='refresh' and t>j['due']+3600:late.append({'id':j['id'],'shard':shard,'lag':t-j['due'],'time':t})
            j['due']=t+j['interval'];j['claimed']=False;counts[shard]+=1
        if counts[shard]>=batch or t+180>stop[shard] or active>=active_cap:busy[shard]=False;continue
        eligible=[x for x in jobs if not x.get('claimed') and x['due']<=t and (x['shard'] is None or x['shard']==shard) and x['reserve']<=9000-used-reserved]
        lane=cycle[seq%len(cycle)]
        lanejobs=[x for x in eligible if x['lane']==lane]
        if not eligible:
            if any(x['due']<=t and (x['shard'] is None or x['shard']==shard) for x in jobs):admission+=1
            busy[shard]=False;continue
        j=min(lanejobs or eligible,key=lambda x:(x['due'],x['id']))
        seq+=1;j['claimed']=True;reserved+=j['reserve'];max_reserved=max(max_reserved,reserved);active+=1;max_active=max(max_active,active)
        # Set back to eligible only when completion is processed.
        heapq.heappush(events,(t+j.get('seconds',12.8 if j['kind']=='discovery' else seconds)+1,1,shard,j))
    return {'batch':batch,'cadence_seconds':cadence,'stagger_seconds':stagger,'active_cap':active_cap,'raw_reservation':reserve,'added_phased_raw_mappings':added,'seconds_per_raw':seconds,'boot_delay_proxy_seconds':boot,'completed':checks,'requests':requests,'deadline_misses':len(late),'worst_lateness_seconds':max((r['lag']-3600 for r in late),default=0),'late_by_shard':dict(Counter(r['shard'] for r in late)),'admission_stops':admission,'max_active_item_model':max_active,'same_shard_overlap_skips':skipped,'max_reserved':max_reserved,'max_used_lazy_window':max(per_window+[used]),'examples':late[:10]}

if __name__=='__main__':
    scenarios=[]
    for cadence,stagger in [(1800,180),(900,60),(600,60),(300,30)]:
        for added in [0,100,607]:
            for seconds in [8.2,603.164/16]:
                scenarios.append(model(16,added,seconds,cadence=cadence,stagger=stagger,active_cap=4))
    result={'semantics':'Offline forecast only. Corrected PR77 cap applies to active PRODUCT claims, not the number of live consumer processes. Existing modulo9, lane cycle, source budgets/pacing untouched. Exact retained due inputs and original lazy budget reset. Natural evidence still required.','source_input':d['observed_at'],'source_http':0,'database_writes':0,'scenarios':scenarios}
    (OUT/'product-claim-cap-model-20261008.json').write_text(json.dumps(result,indent=2)+'\n')
    for r in scenarios:print({k:r[k] for k in ['cadence_seconds','added_phased_raw_mappings','seconds_per_raw','deadline_misses','worst_lateness_seconds','max_active_item_model','max_used_lazy_window']})
