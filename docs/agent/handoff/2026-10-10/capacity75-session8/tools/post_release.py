"""Read-only post-release check for a sequential collector release.

usage: post_release.py <collector-rollout-receipt.json> <baseline storage_stats.json> <out.json>

Per collector: attempts claimed after its new deployment was verified, by outcome, and any
open attempt. Fleet: ledger rows since the first release vs raw_snapshots UPDATE and TOAST
delete deltas against the pre-release baseline (encode-before-insert should stop both
tracking new encoded rows). No writes, no source HTTP.
"""
import json, sys
sys.path.insert(0, '/workspaces/cp-s8/docs/agent/handoff/2026-10-10/capacity75-session8/tools')
from db import connection

receipt, baseline = (json.load(open(p)) for p in sys.argv[1:3])
prefix = lambda n: 'snkrdunk-due' if n == 'snkrdunk-collector' else 'yuyutei-due-' + n.split('-')[3]
out = {'read_only': True, 'source_requests': 0, 'collectors': {}}
with connection() as db:
    out['observed_at'] = db.execute("select now() at time zone 'utc' t").fetchone()['t']
    for name, d in receipt['deployments'].items():
        rows = db.execute("""select outcome, count(*) n, max(finished_at) last, sum(actual_request_cost) cost
            from freshness_attempts where claimed_by like %s and claimed_at > %s group by outcome""",
                          (prefix(name) + ':%', d['verified_at'])).fetchall()
        open_ = db.execute("select count(*) n from freshness_attempts where finished_at is null and claimed_by like %s",
                           (prefix(name) + ':%',)).fetchone()['n']
        out['collectors'][name] = {'verified_at': d['verified_at'], 'deployment': d['deployment_id'],
                                   'outcomes': rows, 'open_attempts': open_,
                                   'natural_turn_seen': any(r['n'] for r in rows)}
    first = min(d['verified_at'] for d in receipt['deployments'].values())
    last = max(d['verified_at'] for d in receipt['deployments'].values())
    out['ledger_since_last_release'] = db.execute(
        "select count(*) n, coalesce(sum(encoded_bytes),0) bytes, min(id) min_id from raw_snapshot_dictionaries where created_at > %s",
        (last,)).fetchone()
    out['raw_since_last_release'] = db.execute(
        "select count(*) n, min(id) min_id from raw_snapshots where fetched_at > %s", (last,)).fetchone()
    stat = db.execute("""select s.n_tup_ins, s.n_tup_upd, t.n_tup_del toast_del, t.n_tup_ins toast_ins
        from pg_stat_user_tables s join pg_class c on c.oid=s.relid join pg_stat_all_tables t on t.relid=c.reltoastrelid
        where s.relname='raw_snapshots'""").fetchone()
    base_raw = next(t for t in baseline['tables'] if t['relname'] == 'raw_snapshots')
    base_toast = next(t for t in baseline['toast'] if t['n_tup_ins'])
    out['raw_stat_now'] = stat
    out['raw_stat_delta_vs_baseline'] = {'ins': stat['n_tup_ins'] - base_raw['n_tup_ins'],
                                        'upd': stat['n_tup_upd'] - base_raw['n_tup_upd'],
                                        'toast_del': stat['toast_del'] - base_toast['n_tup_del']}
    out['denials_since_first_release'] = db.execute(
        "select outcome, count(*) n from freshness_attempts where claimed_at > %s and outcome not in ('captured','no_listing','completed') group by outcome",
        (first,)).fetchall()
    out['budgets'] = db.execute("""select s.name, b.used_requests, b.reserved_requests, b.request_limit, b.window_started_at,
        b.paused_until from source_dispatch_budgets b join sources s on s.id=b.source_id""").fetchall()
    db.rollback()
open(sys.argv[3], 'w').write(json.dumps(out, indent=1, default=str) + '\n')
print(json.dumps(out, indent=1, default=str))
