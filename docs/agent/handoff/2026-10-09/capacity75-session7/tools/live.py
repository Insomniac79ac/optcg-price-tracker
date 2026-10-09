import sys, json
sys.path[:0] = ['/workspaces/cp-s7/scripts']
import collector_variables as cv, generate_staging_state as state
H='/workspaces/cp-s7/docs/agent/handoff/2026-10-08/capacity75-session6/daily/'
ORIG={k:v['digest'] for k,v in json.load(open('/workspaces/cp-s7/docs/agent/handoff/2026-10-08/capacity75-session6/collectors-start.json')).items()}
ACT={}
for k in ORIG:
    ACT[k]=json.load(open(H+f'on-ok-{k}.json'))
COMMIT='1b1b64d23555b5abc315f1aaa79f547784136f59'
nodes=cv.delivery.inspect()
out={'observed_at':state.timestamp(),'services':{}}
for name in ORIG:
    node=nodes[name]; latest=node.get('latestDeployment') or {}
    d=cv.delivery.read_deployment(latest['id'], node['serviceId'], COMMIT)
    deps=state.railway(f'query {{ deployments(first:5, input:{{projectId:"{state.PROJECT}", environmentId:"{state.ENVIRONMENT}", serviceId:"{node["serviceId"]}"}}) {{ edges {{ node {{ id status createdAt }} }} }} }}')['deployments']['edges']
    after=[e['node'] for e in deps if e['node']['createdAt']>ACT[name]['observed_at'][:19]]
    v=cv.read_variables(node['serviceId'])
    out['services'][name]={'latest':latest['id'],'status':latest.get('status'),'activation_deployment':ACT[name]['deployment'],
      'same_as_activation':latest['id']==ACT[name]['deployment'],'digest':cv.digest(d),'digest_is_original':cv.digest(d)==ORIG[name],
      'vars':{k:v.get(k) for k in ('RAW_DICTIONARY_STORAGE_ENABLED','RAW_DICTIONARY_STORAGE_MODE','APP_ENV')},
      'deployments_created_after_activation':after}
print(json.dumps(out,indent=1,default=str))
