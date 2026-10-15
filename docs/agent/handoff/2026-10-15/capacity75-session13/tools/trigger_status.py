"""Read-only: GitHub deployment triggers and auto-deploy status for every staging service.
usage: trigger_status.py > out.json"""
import json, sys
sys.path[:0] = ['/workspaces/cp-cap13/scripts']
import collector_variables as cv, generate_staging_state as state
state.staging_environment()
P, E = state.PROJECT, state.ENVIRONMENT
assert E == '05d1eac2-510d-4bd3-999e-fea9ead766b7', 'not staging'
svcs = state.railway(f'query {{ project(id:"{P}") {{ services {{ edges {{ node {{ id name }} }} }} }} }}')['project']['services']['edges']
out = {'observed_at': state.timestamp(), 'environment': E, 'services': {}}
for s in svcs:
    s = s['node']
    q = state.railway(
        f'query {{ serviceInstanceAutoDeployStatus(environmentId:"{E}", projectId:"{P}", serviceId:"{s["id"]}") {{ enabled canEnable reason }} '
        f'deploymentTriggers(projectId:"{P}", environmentId:"{E}", serviceId:"{s["id"]}") {{ edges {{ node {{ id provider repository branch checkSuites }} }} }} }}')
    out['services'][s['name']] = {'collector': s['name'] in cv.delivery.NAMES, 'auto': q['serviceInstanceAutoDeployStatus'],
                                  'triggers': [e['node'] for e in q['deploymentTriggers']['edges']]}
out['collectors_with_triggers'] = sorted(n for n, r in out['services'].items() if r['collector'] and r['triggers'])
print(json.dumps(out, indent=1))
