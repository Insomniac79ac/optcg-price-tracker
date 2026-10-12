"""Read-only: for each collector, is a redeployable a852244 rollback source available
(collector_variables.original_source, the same lookup the restore path uses)?
usage: rollback_source_check.py > out.json"""
import json, sys
sys.path[:0] = ['/workspaces/cp-s10/scripts']
import collector_variables as cv, generate_staging_state as state
R = json.load(open('/workspaces/cp-s10/docs/agent/handoff/2026-10-11/capacity75-session10/evidence/pr103-delivery/staging-delivery-a504e476d98ab49ad7773a0c8c6b71e9d927b125/evidence/latest-collector-rollout.json'))
nodes = cv.delivery.inspect()
out = {'observed_at': state.timestamp(), 'services': {}}
for name, b in sorted(R['before'].items()):
    try:
        c = cv.original_source(nodes[name], b['commit'], b['image_digest'])
        out['services'][name] = {'ok': True, 'source_deployment': c['id'], 'status': c.get('status'), 'can_redeploy': c.get('canRedeploy'), 'digest': c['meta']['imageDigest'], 'is_receipt_before': c['id'] == b['deployment_id']}
    except Exception as e:
        out['services'][name] = {'ok': False, 'error': str(e)[:200]}
out['all_ok'] = all(r['ok'] for r in out['services'].values())
print(json.dumps(out, indent=1, default=str))
