"""Read-only: is every collector still on its verified 05f099d image (restored 11:00Z),
with unchanged cron/start command/daily-v1, and has any deployment appeared since?
usage: live_now.py <since-iso> [commit]; digest check applies only to 05f099d"""
import hashlib, json, sys
sys.path[:0] = ['/workspaces/cp-s8/scripts']
import collector_variables as cv, generate_staging_state as state
HERE = '/workspaces/cp-s8/docs/agent/handoff/2026-10-10/capacity75-session8/'
fleet = json.load(open(HERE + 'evidence/fleet-after-pr95.json'))
pre = json.load(open(HERE + 'evidence/fleet-preflight-A.json'))
COMMIT = sys.argv[2] if len(sys.argv) > 2 else fleet['commit']; SINCE = sys.argv[1]
nodes = cv.delivery.inspect()
out = {'observed_at': state.timestamp(), 'expected_commit': COMMIT, 'since': SINCE, 'services': {}}
for name in sorted(cv.delivery.NAMES):
    node = nodes[name]; f = fleet['services'][name]
    latest = node.get('latestDeployment') or {}
    row = {'latest': latest.get('id'), 'status': latest.get('status')}
    try:
        active = cv.delivery.read_deployment(latest['id'], node['serviceId'], COMMIT)
        row['marker_05f099d'] = True; row['digest_is_verified_05f099d'] = cv.digest(active) == f['image_digest']
    except state.VerificationError as e:
        row['marker_05f099d'] = False; row['error'] = str(e)
    row['cron'] = node.get('cronSchedule'); row['cron_unchanged'] = node.get('cronSchedule') == f['cron']
    row['start_command_unchanged'] = hashlib.sha256((node.get('startCommand') or '').encode()).hexdigest() == pre['services'][name]['start_command_sha256']
    v = cv.read_variables(node['serviceId'])
    row['vars'] = {k: v.get(k) for k in ('RAW_DICTIONARY_STORAGE_ENABLED', 'RAW_DICTIONARY_STORAGE_MODE', 'APP_ENV')}
    row['vars_unchanged'] = row['vars'] == f['variables']
    deps = state.railway(f'query {{ deployments(first:10, input:{{projectId:"{state.PROJECT}", environmentId:"{state.ENVIRONMENT}", serviceId:"{node["serviceId"]}"}}) {{ edges {{ node {{ id status createdAt }} }} }} }}')['deployments']['edges']
    row['deployments_since'] = [e['node'] for e in deps if e['node']['createdAt'] > SINCE]
    out['services'][name] = row
out['all_ok'] = all(r.get('digest_is_verified_05f099d') and r['status'] == 'SUCCESS' and r['cron_unchanged'] and r['start_command_unchanged'] and r['vars_unchanged'] for r in out['services'].values())
print(json.dumps(out, indent=1, default=str))
