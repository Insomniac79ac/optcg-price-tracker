"""Read-only: cross-check the ORIGINAL PR #103 collector rollout receipt (CI artifact) against
primary sources: Railway deployment history, the session-8 a852244 fleet record, and GitHub.
Every field not readable from a source is reported as UNKNOWN. usage: receipt_crosscheck.py > out.json"""
import json, subprocess, sys
sys.path[:0] = ['/workspaces/cp-s10/scripts']
import generate_staging_state as state
H = '/workspaces/cp-s10/docs/agent/handoff/'
R = json.load(open(H + '2026-10-11/capacity75-session10/evidence/pr103-delivery/staging-delivery-a504e476d98ab49ad7773a0c8c6b71e9d927b125/evidence/latest-collector-rollout.json'))
F = json.load(open(H + '2026-10-10/capacity75-session8/evidence/fleet-after-pr98.json'))
MERGE_AT = '2026-10-11T15:51:23Z'
state.staging_environment()
def gh(path):
    return json.loads(subprocess.check_output(['gh', 'api', path]))
pr = gh('repos/Insomniac79ac/optcg-price-tracker/pulls/103')
run = gh('repos/Insomniac79ac/optcg-price-tracker/actions/runs/38151886392')
arts = gh('repos/Insomniac79ac/optcg-price-tracker/actions/runs/38151886392/artifacts')['artifacts']
out = {'observed_at': state.timestamp(), 'label': 'CROSS-CHECK of ORIGINAL receipt (not reconstructed)',
       'github': {'pr': 103, 'merged_at': pr.get('merged_at') or 'UNKNOWN', 'merge_commit': pr.get('merge_commit_sha') or 'UNKNOWN',
                  'receipt_source_sha_matches_merge': pr.get('merge_commit_sha') == R['source_sha'],
                  'ci_run': {'id': run['id'], 'head_sha': run['head_sha'], 'conclusion': run['conclusion'], 'created_at': run['created_at'], 'updated_at': run['updated_at']},
                  'artifacts': [{k: a[k] for k in ('id', 'name', 'size_in_bytes', 'created_at', 'expires_at')} for a in arts]},
       'receipt': {k: R[k] for k in ('started_at', 'completed_at', 'source_sha', 'sequential', 'natural_runs_not_yet_verified', 'production_accessed')},
       'services': {}}
for name, d in sorted(R['deployments'].items()):
    sid = d['service_id']; b = R['before'][name]; f = F['services'].get(name, {})
    edges = state.railway(f'query {{ deployments(first:20, input:{{projectId:"{state.PROJECT}", environmentId:"{state.ENVIRONMENT}", serviceId:"{sid}"}}) {{ edges {{ node {{ id status createdAt meta }} }} }} }}')['deployments']['edges']
    nodes = {e['node']['id']: e['node'] for e in edges}
    new = nodes.get(d['deployment_id']); old = nodes.get(b['deployment_id'])
    since_merge = [{'id': e['node']['id'], 'status': e['node']['status'], 'createdAt': e['node']['createdAt']} for e in edges if e['node']['createdAt'] > MERGE_AT]
    def meta(n, k): return ((n or {}).get('meta') or {}).get(k, 'UNKNOWN') if n else 'UNKNOWN'
    out['services'][name] = {
        'new_deployment': d['deployment_id'],
        'railway_new_found': bool(new), 'railway_new_status': (new or {}).get('status', 'UNKNOWN'), 'railway_new_created_at': (new or {}).get('createdAt', 'UNKNOWN'),
        'railway_new_digest_matches_receipt': meta(new, 'imageDigest') == d['image_digest'],
        'railway_new_cli_message_has_sha': R['source_sha'] in str(meta(new, 'cliMessage')),
        'receipt_verified_at': d['verified_at'],
        'deployments_since_merge': since_merge,
        'rollback_target_deployment': b['deployment_id'], 'rollback_target_commit': b['commit'], 'rollback_target_digest': b['image_digest'],
        'rollback_target_equals_session8_active': b['deployment_id'] == f.get('active_deployment'),
        'rollback_target_digest_equals_session8': b['image_digest'] == f.get('image_digest'),
        'railway_rollback_target_found': bool(old), 'railway_rollback_target_status': (old or {}).get('status', 'UNKNOWN'),
        'railway_rollback_target_digest_matches': meta(old, 'imageDigest') == b['image_digest'] if old else 'UNKNOWN',
    }
s = out['services'].values()
out['summary'] = {
    'all_new_found_success_digest_match': all(r['railway_new_found'] and r['railway_new_status'] == 'SUCCESS' and r['railway_new_digest_matches_receipt'] and r['railway_new_cli_message_has_sha'] for r in s),
    'exactly_one_deployment_per_collector_since_merge': all(len(r['deployments_since_merge']) == 1 and r['deployments_since_merge'][0]['id'] == r['new_deployment'] for r in s),
    'rollback_targets_equal_session8': all(r['rollback_target_equals_session8_active'] and r['rollback_target_digest_equals_session8'] for r in s),
    'rollback_targets_present_in_railway': all(r['railway_rollback_target_found'] for r in s),
    'trigger_preflight_in_receipt': R.get('github_trigger_preflight'),
}
print(json.dumps(out, indent=1, default=str))
