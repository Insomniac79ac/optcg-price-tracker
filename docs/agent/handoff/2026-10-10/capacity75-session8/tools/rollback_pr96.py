"""All-or-nothing rollback after PR #96's merge auto-built 419210d on every collector via
Railway's GitHub integration (no exact-commit marker), outside the verified sequential path.

Restores each collector, one at a time and only in its own safe slot, to its verified
05f099d image (digest from fleet-after-pr95.json) with unchanged daily-v1 values, through
deploy_staging_collectors.roll_back -> collector_variables.restore, verifying each.
Waits for any in-flight deployment on a collector to finish before touching it.
usage: rollback_pr96.py <out.json>
"""
import json, sys, time
sys.path.insert(0, '/workspaces/cp-s8/scripts')
import generate_staging_state as state
import deploy_staging_collectors as delivery

HERE = '/workspaces/cp-s8/docs/agent/handoff/2026-10-10/capacity75-session8/'
fleet = json.load(open(HERE + 'evidence/fleet-after-pr95.json'))
COMMIT = fleet['commit']
ORDER = ['snkrdunk-collector'] + [f'yuyutei-collector-shard-{i}' for i in range(9) if i != 4] + ['yuyutei-collector-shard-4-v2']
state.staging_environment()
before = {}
for name in ORDER:
    s = fleet['services'][name]
    before[name] = {'service_id': s['service_id'], 'schedule_utc': s['cron'], 'commit': COMMIT,
                    'digest': s['image_digest'], 'variables': s['variables']}


def settled_slot(name, schedule):
    deadline = time.monotonic() + 900
    while (delivery.inspect()[name].get('latestDeployment') or {}).get('status') not in {'SUCCESS', 'FAILED', 'CRASHED', 'REMOVED', 'SKIPPED'}:
        if time.monotonic() > deadline:
            raise state.VerificationError('in-flight deployment did not settle: ' + name)
        time.sleep(15)
    delivery.wait_for_slot(name, schedule)
    print(json.dumps({'slot': name, 'at': state.timestamp()}), flush=True)


started = state.timestamp()
# roll_back restores newest-first; pass the reverse so it restores in ORDER.
results = delivery.roll_back(list(reversed(ORDER)), before, slot=settled_slot)
out = {'started_at': started, 'completed_at': state.timestamp(), 'commit': COMMIT, 'results': results,
       'all_ok': all(r['ok'] for r in results.values()), 'source_jobs_triggered': 0, 'production_accessed': False}
open(sys.argv[1], 'w').write(json.dumps(out, indent=1, default=str) + '\n')
print(json.dumps({'all_ok': out['all_ok'], 'completed_at': out['completed_at']}), flush=True)
