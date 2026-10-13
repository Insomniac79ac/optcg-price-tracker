"""Read-only: active collector deployment and digest vs the PR #103 a504e47 rollout receipt, and
deployment records created after the rollout. usage: fleet_vs_receipt.py <live-state.json> > out.json"""
import json, sys
sys.path[:0] = ['/workspaces/cp-cap12/scripts']
import generate_staging_state as state, collector_variables as cv
R = json.load(open('/workspaces/cp-cap12/docs/agent/handoff/2026-10-11/capacity75-session10/evidence/pr103-delivery/staging-delivery-a504e476d98ab49ad7773a0c8c6b71e9d927b125/evidence/latest-collector-rollout.json'))
L = json.load(open(sys.argv[1]))
nodes = cv.delivery.inspect()
out = {'observed_at': state.timestamp(), 'receipt_completed_at': R['completed_at'], 'services': {}}
for name, live in sorted(L['services'].items()):
    rec = R['deployments'][name]
    deps = state.railway(f'query {{ deployments(first:10, input:{{projectId:"{state.PROJECT}", environmentId:"{state.ENVIRONMENT}", serviceId:"{nodes[name]["serviceId"]}"}}) {{ edges {{ node {{ id status createdAt }} }} }} }}')['deployments']['edges']
    after = [e['node'] for e in deps if e['node']['createdAt'] > R['completed_at']]
    out['services'][name] = {'receipt_deployment': rec.get('deployment_id') or rec.get('id'), 'live_deployment': live['latest'],
                             'receipt_digest': rec.get('image_digest') or rec.get('digest'), 'live_digest': live['digest'],
                             'records_after_rollout': after}
    r = out['services'][name]
    r['match'] = r['receipt_deployment'] == r['live_deployment'] and r['receipt_digest'] == r['live_digest'] and not after
out['all_match'] = all(r['match'] for r in out['services'].values())
print(json.dumps(out, indent=1))
