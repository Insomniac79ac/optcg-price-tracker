"""Session-6 collector settings driver; only scripts/collector_variables (merged) is used.

usage: rollout.py trial|on|off <out_dir> [service,service,...]
  trial: OFF->OFF no-op on the given services; digest must be unchanged.
  on:    daily-v1 on all 10, one at a time. Any failure restores every service
         touched so far to its ORIGINAL verified image with the writer OFF, then stops.
  off:   restore all 10 (or the given ones) to their original image, writer OFF.
Each service changes only with no open attempt and >= 4 min to its next cron turn.
"""
import json, sys, time
sys.path.insert(0, '/workspaces/cp-s6/staging/scripts')
sys.path.insert(0, '/workspaces/cp-s4/tools')
import collector_variables as cv
import generate_staging_state as state
from datetime import datetime, timezone
from db import connection

COMMIT = '1b1b64d23555b5abc315f1aaa79f547784136f59'
ORIGINAL = {k: v['digest'] for k, v in json.load(open('/workspaces/cp-s6/evidence/collectors-start.json')).items()}
ORDER = ['snkrdunk-collector'] + [f'yuyutei-collector-shard-{i}' for i in range(9) if i != 4] + ['yuyutei-collector-shard-4-v2']
OFF = {'RAW_DICTIONARY_STORAGE_ENABLED': 'false', 'RAW_DICTIONARY_STORAGE_MODE': 'canary', 'APP_ENV': 'staging'}
ON = {'RAW_DICTIONARY_STORAGE_ENABLED': 'true', 'RAW_DICTIONARY_STORAGE_MODE': 'daily-v1', 'APP_ENV': 'staging'}
mode, out = sys.argv[1], sys.argv[2]
targets = sys.argv[3].split(',') if len(sys.argv) > 3 else ORDER
assert set(targets) <= set(ORDER) and len(ORIGINAL) == 10


def wait_safe(name):
    mins, claim = ([27, 57], 'snkrdunk-due:%') if name == 'snkrdunk-collector' else \
        ((lambda k: ([3 * k, 3 * k + 30], f'yuyutei-due-{k}:%'))(int(name.split('-')[3])))
    deadline = time.time() + 1200
    while True:
        now = datetime.now(timezone.utc)
        gap = min((x - (now.minute + now.second / 60)) % 60 for x in mins)
        with connection() as db:
            busy = db.execute('select count(*) n from freshness_attempts where finished_at is null and claimed_by like %s',
                              (claim,)).fetchone()['n']
        if gap >= 4 and busy == 0:
            return
        if time.time() > deadline:
            raise cv.state.VerificationError(f'{name}: no safe slot')
        time.sleep(30)


def save(tag, name, body):
    open(f'{out}/{mode}-{tag}-{name}.json', 'w').write(json.dumps(body, indent=2, default=str) + '\n')
    print(json.dumps({'step': tag, 'service': name, **{k: body.get(k) for k in (
        'deployment', 'image_digest', 'original_digest', 'observed', 'observed_at', 'build_log_lines', 'error')}},
        default=str), flush=True)


def restore_all(names, reason):
    ok = True
    for name in names:
        wait_safe(name)
        try:
            save('restore', name, cv.restore(name, OFF, COMMIT, ORIGINAL[name]))
        except Exception as error:  # keep restoring the rest; report loudly
            ok = False
            save('restore', name, {'error': f'RESTORE FAILED: {error}'})
    print('RESTORED' if ok else 'RESTORE INCOMPLETE', reason, flush=True)
    return ok


if mode == 'off':
    restore_all(targets, 'requested')
    sys.exit(0)

values = ON if mode == 'on' else OFF
done = []
for name in targets:
    wait_safe(name)
    done.append(name)
    try:
        receipt = cv.change(name, values, COMMIT, expect_digest=ORIGINAL[name])
    except Exception as error:
        save('refused', name, {'error': str(error), 'receipt': getattr(error, 'receipt', None)})
        if mode == 'on':
            restore_all([n for n in done if n != name or not getattr(error, 'receipt', {}).get('rollback_ok')],
                        f'{name} failed')
        raise SystemExit(f'STOPPED at {name}: {error}')
    if receipt['image_digest'] != ORIGINAL[name]:  # belt and braces; change() already enforces
        raise SystemExit(f'STOPPED: digest drift on {name}')
    save('ok', name, receipt)
print('ALL', mode, len(done), state.timestamp())
