"""Redeploy the verified SNKR upload (exact commit 1b1b64d) via the delivery script's own
deploymentRedeploy path. No variable, cron, start-command or source-job change."""
import sys, json
sys.path.insert(0, '/workspaces/cp-s5/staging/scripts')
import generate_staging_state as state, deploy_staging_collectors as d

SID = '2d7ab69b-ec1f-4c66-8da1-9c8769a6d14a'
UP = 'f3286a0a-421e-42f1-bc4b-b917a98cad3b'
EXPECT = '1b1b64d23555b5abc315f1aaa79f547784136f59'

env = state.staging_environment()
src = d.read_deployment(UP, SID, EXPECT)  # destination + exact-commit marker check
assert src['canRedeploy']
svc = [e['node'] for e in env['serviceInstances']['edges'] if e['node']['serviceId'] == SID][0]
assert svc['cronSchedule'] == '27,57 * * * *'
assert svc['startCommand'] == 'python -m snkrdunk_collector.collect --due-work'
res = state.railway(
    f'mutation {{ deploymentRedeploy(id:"{UP}",usePreviousImageTag:false) {{ id status meta }} }}'
)['deploymentRedeploy']
new = d.read_deployment(res['id'], SID, EXPECT)  # clone must keep the exact-commit marker
print(json.dumps({'at': state.timestamp(), 'source_upload': UP, 'new_deployment': new['id'],
                  'status': new['status'], 'cliMessage': new['meta'].get('cliMessage')}))
