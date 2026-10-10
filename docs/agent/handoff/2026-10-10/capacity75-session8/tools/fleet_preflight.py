"""Read-only collector fleet preflight for a native collector release.

Pins, per collector: service id, active (activation) deployment, its exact-commit
marker, image digest, canRedeploy of a same-image recovery source, cron, start
command hash and RAW writer variables. Makes no change and no source request.
"""
import hashlib, json, sys
sys.path[:0] = ['/workspaces/cp-s8/scripts']
import collector_variables as cv, generate_staging_state as state
COMMIT = '1b1b64d23555b5abc315f1aaa79f547784136f59'
nodes = cv.delivery.inspect()
out = {'observed_at': state.timestamp(), 'component_commit': COMMIT, 'services': {}}
for name in sorted(cv.delivery.NAMES):
    node = nodes[name]
    active, source = cv.verified_active(node, COMMIT)
    out['services'][name] = {
        'service_id': node['serviceId'],
        'active_deployment': active['id'],
        'active_status': active['status'],
        'marker': active['meta'].get('cliMessage'),
        'image_digest': cv.digest(active),
        'recovery_source_deployment': source['id'],
        'recovery_source_can_redeploy': source.get('canRedeploy'),
        'recovery_source_digest': cv.digest(source),
        'cron': node.get('cronSchedule'),
        'start_command_sha256': hashlib.sha256((node.get('startCommand') or '').encode()).hexdigest(),
        'variables': cv.read_variables(node['serviceId']),
    }
print(json.dumps(out, indent=1, default=str))
