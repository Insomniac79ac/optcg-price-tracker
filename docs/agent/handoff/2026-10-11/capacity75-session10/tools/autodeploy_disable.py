"""AMBER (session 9): stop Railway's GitHub integration from deploying ONE collector.

usage: autodeploy_disable.py <collector-name> <out.json> [--restore]

Mechanism (read-only evidence: evidence/autodeploy-status-before.json): each collector
carries one GitHub DeploymentTrigger (repo Insomniac79ac/optcg-price-tracker, branch
staging). That trigger is what built PR #96 on every collector at once. The never-used
parent `yuyutei-collector` already has auto-deploy disabled and no trigger.

Forward: in the collector's own safe slot (deploy_staging_collectors.wait_for_slot) and
inside 06:00-23:00 UTC, call the documented serviceInstanceAutoDeployUpdate(enabled:false)
("Disable automatic deployments"); if a trigger remains, deploymentTriggerDelete it.
Then require: no trigger, auto-deploy disabled, no new deployment record, the same
active deployment and verified a852244 image digest, cron/start command unchanged and
an empty staged-changes patch. No image is built, redeployed or replaced.
Rollback (--restore, or automatically on any failed check): deploymentTriggerCreate
with the recorded provider/repository/branch/checkSuites, then re-read.
"""
import hashlib, json, sys, time
sys.path[:0] = ['/workspaces/cp-s10/scripts']
import collector_variables as cv, deploy_staging_collectors as rollout, generate_staging_state as state

S8 = '/workspaces/cp-s10/docs/agent/handoff/2026-10-10/capacity75-session8/'
S9 = '/workspaces/cp-s10/docs/agent/handoff/2026-10-10/capacity75-session9/'
fleet = json.load(open(S8 + 'evidence/fleet-after-pr98.json'))
before_all = json.load(open(S9 + 'evidence/autodeploy-status-before.json'))['services']
name, out_path = sys.argv[1:3]
restore_only = '--restore' in sys.argv
assert name in fleet['services'] and name in cv.delivery.NAMES, 'not a delivered collector'
state.staging_environment()
assert state.ENVIRONMENT == '05d1eac2-510d-4bd3-999e-fea9ead766b7', 'not staging'
F = fleet['services'][name]; SID = F['service_id']; P, E = state.PROJECT, state.ENVIRONMENT
REPO, BRANCH = 'Insomniac79ac/optcg-price-tracker', 'staging'
log = {'service': name, 'service_id': SID, 'environment': E, 'started_at': state.timestamp(), 'steps': []}


def step(what, **kw):
    log['steps'].append({'at': state.timestamp(), 'what': what, **kw}); print(what, json.dumps(kw, default=str)[:300])


def read():
    q = state.railway(
        f'query {{ serviceInstanceAutoDeployStatus(environmentId:"{E}", projectId:"{P}", serviceId:"{SID}") {{ enabled canEnable reason }} '
        f'deploymentTriggers(projectId:"{P}", environmentId:"{E}", serviceId:"{SID}") {{ edges {{ node {{ id provider repository branch checkSuites }} }} }} '
        f'deployments(first:20, input:{{projectId:"{P}", environmentId:"{E}", serviceId:"{SID}"}}) {{ edges {{ node {{ id status createdAt }} }} }} '
        f'environmentStagedChanges(environmentId:"{E}") {{ id patch }} }}')
    node = cv.delivery.inspect()[name]
    latest = (node.get('latestDeployment') or {}).get('id')
    active = cv.delivery.read_deployment(latest, SID, fleet['commit'])
    return {
        'auto': q['serviceInstanceAutoDeployStatus'],
        'triggers': [e['node'] for e in q['deploymentTriggers']['edges']],
        'deployment_ids': [e['node']['id'] for e in q['deployments']['edges']],
        'staged_patch': q['environmentStagedChanges']['patch'],
        'latest': latest, 'latest_status': (node.get('latestDeployment') or {}).get('status'),
        'digest': cv.digest(active), 'cron': node.get('cronSchedule'),
        'start_command_sha256': hashlib.sha256((node.get('startCommand') or '').encode()).hexdigest(),
    }


def restore(trigger):
    t = trigger
    state.railway(
        f'mutation {{ deploymentTriggerCreate(input:{{projectId:"{P}", environmentId:"{E}", serviceId:"{SID}", '
        f'provider:"{t["provider"]}", repository:"{t["repository"]}", branch:"{t["branch"]}", '
        f'checkSuites:{"true" if t["checkSuites"] else "false"}}}) {{ id }} }}')
    after = read(); step('restored', after=after)
    return after


original = before_all[name]['triggers']
assert len(original) == 1 and original[0]['repository'] == REPO and original[0]['branch'] == BRANCH \
    and original[0]['provider'] == 'github', 'unexpected recorded trigger'
try:
    if restore_only:
        restore(original[0]); log['result'] = 'RESTORED'; sys.exit(0)
    rollout.outside_busy_window()
    pre = read(); step('pre', state=pre)
    assert pre['latest'] == F['active_deployment'] and pre['latest_status'] == 'SUCCESS', 'active deployment moved'
    assert pre['digest'] == F['image_digest'], 'digest not the verified a852244 image'
    assert pre['triggers'] == original, 'trigger changed since the read-only record'
    assert pre['staged_patch'] == {}, 'environment has staged changes; refuse'
    rollout.wait_for_slot(name, pre['cron']); step('safe slot')
    rollout.outside_busy_window()
    log['mutated'] = True
    try:
        r = state.railway(f'mutation {{ serviceInstanceAutoDeployUpdate(input:{{environmentId:"{E}", projectId:"{P}", serviceId:"{SID}", enabled:false}}) {{ enabled }} }}')
        step('serviceInstanceAutoDeployUpdate', result=r)
    except state.VerificationError as error:
        step('serviceInstanceAutoDeployUpdate refused', error=str(error))
    time.sleep(5)
    mid = read()
    for t in mid['triggers']:
        state.railway(f'mutation {{ deploymentTriggerDelete(id:"{t["id"]}") }}'); step('deploymentTriggerDelete', id=t['id'])
    time.sleep(60)  # any deployment or staged change the change might cause has time to appear
    post = read(); step('post', state=post)
    checks = {
        'no_trigger': post['triggers'] == [],
        'auto_deploy_disabled': post['auto']['enabled'] is False,
        'no_new_deployment_record': post['deployment_ids'] == pre['deployment_ids'],
        'same_active_deployment': post['latest'] == pre['latest'] and post['latest_status'] == 'SUCCESS',
        'same_verified_digest': post['digest'] == F['image_digest'],
        'cron_unchanged': post['cron'] == pre['cron'],
        'start_command_unchanged': post['start_command_sha256'] == pre['start_command_sha256'],
        'no_staged_changes': post['staged_patch'] == {},
        'variables_unchanged': {k: cv.read_variables(SID).get(k) for k in F['variables']} == F['variables'],
    }
    log['checks'] = checks
    if not all(checks.values()):
        step('CHECK FAILED; restoring', checks=checks); restore(original[0]); log['result'] = 'FAILED_RESTORED'
        raise SystemExit('check failed: ' + json.dumps(checks))
    log['result'] = 'DISABLED'
except BaseException as error:
    if log.get('mutated') and 'result' not in log:
        step('ERROR after mutation; restoring', error=repr(error))
        try:
            restore(original[0]); log['result'] = 'ERROR_RESTORED'
        except BaseException as again:
            log['result'] = 'ROLLBACK FAILED: ' + repr(again)
    raise
finally:
    log['finished_at'] = state.timestamp()
    json.dump(log, open(out_path, 'w'), indent=1, default=str)
