"""Read-only: are all 10 collectors on a504e47 (marker, SUCCESS) with unchanged cron, start command and daily-v1, and does the PR #102 trigger preflight pass? usage: live_a504e47.py > out.json"""
import hashlib, json, sys
sys.path[:0] = ['/workspaces/cp-s10/scripts']
import collector_variables as cv, generate_staging_state as state, deploy_staging_collectors as dsc
S8 = '/workspaces/cp-s10/docs/agent/handoff/2026-10-10/capacity75-session8/'
fleet = json.load(open(S8 + 'evidence/fleet-after-pr98.json'))
pre = json.load(open(S8 + 'evidence/fleet-preflight-A.json'))
COMMIT = 'a504e476d98ab49ad7773a0c8c6b71e9d927b125'
nodes = cv.delivery.inspect()
out = {'observed_at': state.timestamp(), 'commit': COMMIT, 'services': {}}
for name in sorted(cv.delivery.NAMES):
    node = nodes[name]; f = fleet['services'][name]
    latest = node.get('latestDeployment') or {}
    row = {'latest': latest.get('id'), 'status': latest.get('status')}
    try:
        active = cv.delivery.read_deployment(latest['id'], node['serviceId'], COMMIT); row['marker'] = True; row['digest'] = cv.digest(active)
    except Exception as e:
        row['marker'] = False; row['error'] = str(e)
    row['cron_unchanged'] = node.get('cronSchedule') == f['cron']
    row['start_command_unchanged'] = hashlib.sha256((node.get('startCommand') or '').encode()).hexdigest() == pre['services'][name]['start_command_sha256']
    v = cv.read_variables(node['serviceId'])
    row['vars_unchanged'] = {k: v.get(k) for k in ('RAW_DICTIONARY_STORAGE_ENABLED', 'RAW_DICTIONARY_STORAGE_MODE', 'APP_ENV')} == f['variables']
    out['services'][name] = row
try:
    out['trigger_preflight'] = dsc.refuse_github_triggers(nodes)
except Exception as e:
    out['trigger_preflight'] = 'REFUSED/ERROR: %s' % e
out['all_ok'] = all(r['marker'] and r['status']=='SUCCESS' and r['cron_unchanged'] and r['start_command_unchanged'] and r['vars_unchanged'] for r in out['services'].values())
print(json.dumps(out, indent=1, default=str))
