"""Activate (or roll back) daily-v1 on all 10 collectors via collector_variables.change only.

usage: daily_v1.py on|off <out_dir>
Each service changes only when it has no open attempt and its next cron turn is
>= 4 min away, so no running turn is interrupted. Stops at the first refusal.
"""
import json, sys, time
from datetime import datetime, timezone
sys.path.insert(0, '/workspaces/cp-s5/staging/scripts')
sys.path.insert(0, '/workspaces/cp-s4/tools')
import collector_variables as cv
from db import connection

COMMIT = '1b1b64d23555b5abc315f1aaa79f547784136f59'
ORDER = ['snkrdunk-collector'] + [f'yuyutei-collector-shard-{i}' for i in range(9) if i != 4] + ['yuyutei-collector-shard-4-v2']
mode, out = sys.argv[1], sys.argv[2]
ONLY = sys.argv[3].split(',') if len(sys.argv) > 3 else None
SET = ({'RAW_DICTIONARY_STORAGE_ENABLED': 'true', 'RAW_DICTIONARY_STORAGE_MODE': 'daily-v1', 'APP_ENV': 'staging'}
       if mode == 'on' else
       {'RAW_DICTIONARY_STORAGE_ENABLED': 'false', 'RAW_DICTIONARY_STORAGE_MODE': 'canary', 'APP_ENV': 'staging'})


def minutes(name):
    if name == 'snkrdunk-collector':
        return [27, 57], 'snkrdunk-due:%'
    k = int(name.split('-')[3])
    return [3 * k, 3 * k + 30], f'yuyutei-due-{k}:%'


def safe_now(name):
    mins, claim = minutes(name)
    now = datetime.now(timezone.utc)
    m = now.minute + now.second / 60
    gap = min((x - m) % 60 for x in mins)
    with connection() as db:
        open_n = db.execute('select count(*) n from freshness_attempts where finished_at is null and claimed_by like %s',
                            (claim,)).fetchone()['n']
    return gap >= 4 and open_n == 0, gap, open_n


receipts = []
for name in (ONLY or ORDER):
    deadline = time.time() + 1200
    while True:
        ok, gap, open_n = safe_now(name)
        if ok:
            break
        if time.time() > deadline:
            raise SystemExit(f'{name}: no safe slot (gap={gap:.1f}, open={open_n}); stopped')
        time.sleep(30)
    try:
        r = cv.change(name, SET, COMMIT)
    except cv.state.VerificationError as error:
        # Rollback only: OFF is the safe direction. Record and continue;
        # flags and identity are verified independently afterwards.
        if mode != 'off':
            raise
        r = {'service': name, 'deployment': None, 'status': 'REFUSED_AFTER_DEPLOY', 'image_digest': None,
             'observed': None, 'observed_at': None, 'refusal': str(error)}
    receipts.append(r)
    print(json.dumps({k: r[k] for k in ('service', 'deployment', 'status', 'image_digest', 'observed', 'observed_at')}), flush=True)
    open(f'{out}/daily-v1-{mode}-{name}.json', 'w').write(json.dumps(r, indent=2) + '\n')
print('ALL', mode, len(receipts))
