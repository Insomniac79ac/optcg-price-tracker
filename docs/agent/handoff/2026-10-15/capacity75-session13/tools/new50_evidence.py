"""Read-only: natural evidence for the NEW50 Yuyu identity-capture intents (work ids 3678-3727).

Per work row: attempts, outcomes, request cost, claiming shard, and the RAW snapshots its cursor
records (product page, Yuyu image, official images). Bytes are pg_column_size(raw_content), i.e.
what the row stores. Also: Yuyu denials (403/429/challenge/source_denial) and RAW HTTP statuses
since the enqueue, proposal reviews / approvals / mapping writes since the enqueue, and the
cursor identity statuses. No writes, no source HTTP.
usage: new50_evidence.py > out.json
"""
import json, sys
from collections import Counter
sys.path.insert(0, '/workspaces/cp-cap13/docs/agent/handoff/2026-10-15/capacity75-session13/tools')
from db import connection

LO, HI = 3678, 3727
ENQUEUED = '2026-10-13 16:06:12+00'
out = {'read_only': True, 'source_requests': 0, 'work_ids': [LO, HI], 'enqueued_at': ENQUEUED}
with connection() as db:
    out['observed_at'] = db.execute("select now() at time zone 'utc' t").fetchone()['t']
    work = db.execute("""select id, state, last_outcome, attempt_count, scope_key, next_due_at,
        last_successfully_checked_at, last_failure, resume_cursor::jsonb cur from freshness_work
        where id between %s and %s order by id""", (LO, HI)).fetchall()
    attempts = db.execute("""select work_id, outcome, actual_request_cost, reserved_request_cost, claimed_by,
        started_at, finished_at, raw_snapshot_id from freshness_attempts where work_id between %s and %s
        order by work_id, started_at""", (LO, HI)).fetchall()
    snap_ids = {}
    for w in work:
        c = w['cur'] or {}
        ids = {'product': [c.get('source_product_snapshot_id')], 'yuyu_image': [c.get('source_image_snapshot_id')],
               'official_image': [o.get('raw_snapshot_id') for o in c.get('official_images', [])]}
        snap_ids[w['id']] = {k: [i for i in v if i] for k, v in ids.items()}
    all_ids = sorted({i for s in snap_ids.values() for v in s.values() for i in v})
    sizes = {r['id']: r for r in db.execute("""select id, source_url, http_status, fetched_at,
        pg_column_size(raw_content) stored, length(raw_content) len from raw_snapshots where id = any(%s)""",
        (all_ids,)).fetchall()}
    # Are any of these snapshots referenced by another work row's cursor (shared, not one-off)?
    out['snapshot_refs_outside_new50'] = db.execute("""select count(*) n from freshness_work w
        where w.id not between %s and %s and w.resume_cursor is not null and (
          (w.resume_cursor::jsonb->>'source_product_snapshot_id')::int = any(%s)
          or (w.resume_cursor::jsonb->>'source_image_snapshot_id')::int = any(%s))""",
        (LO, HI, all_ids, all_ids)).fetchone()['n']
    out['yuyu_attempt_outcomes_since_enqueue'] = db.execute("""select w.kind, a.outcome, count(*) n
        from freshness_attempts a join freshness_work w on w.id=a.work_id join sources s on s.id=w.source_id
        where s.name='yuyutei' and a.started_at > %s group by 1,2 order by 1,2""", (ENQUEUED,)).fetchall()
    out['yuyu_raw_http_status_since_enqueue'] = db.execute("""select r.http_status, count(*) n
        from raw_snapshots r join sources s on s.id=r.source_id where s.name='yuyutei' and r.fetched_at > %s
        group by 1 order by 1""", (ENQUEUED,)).fetchall()
    out['yuyu_denial_failures_since_enqueue'] = db.execute("""select count(*) n from freshness_work w
        join sources s on s.id=w.source_id where s.name='yuyutei' and w.last_failure_at > %s
        and (w.last_failure ilike '%%403%%' or w.last_failure ilike '%%429%%' or w.last_failure ilike '%%challenge%%'
             or w.last_failure ilike '%%denial%%')""", (ENQUEUED,)).fetchone()['n']
    out['decisions_since_enqueue'] = {
        'proposal_reviews': db.execute("""select count(*) n from source_mapping_proposal_groups
            where reviewed_at > %s""", (ENQUEUED,)).fetchone()['n'],
        'approved_groups_created': db.execute("""select count(*) n from source_mapping_proposal_groups
            where review_status='approved' and created_at > %s""", (ENQUEUED,)).fetchone()['n'],
        'mappings_created': db.execute("""select count(*) n from source_card_mappings
            where created_at > %s""", (ENQUEUED,)).fetchone()['n'],
        'mappings_updated': db.execute("""select count(*) n from source_card_mappings
            where updated_at > %s""", (ENQUEUED,)).fetchone()['n'],
    }
    db.rollback()

by_work = {}
for a in attempts:
    by_work.setdefault(a['work_id'], []).append(a)
rows, tot = [], Counter()
for w in work:
    ids = snap_ids[w['id']]
    b = {k: sum(sizes[i]['stored'] for i in v if i in sizes) for k, v in ids.items()}
    a = by_work.get(w['id'], [])
    rows.append({'work_id': w['id'], 'state': w['state'], 'last_outcome': w['last_outcome'],
                 'attempts': [{'outcome': x['outcome'], 'cost': x['actual_request_cost'], 'shard': x['claimed_by'].split(':')[0],
                               'started_at': x['started_at'], 'finished_at': x['finished_at']} for x in a],
                 'identity_status': (w['cur'] or {}).get('identity_status'), 'official_images': len(ids['official_image']),
                 'bytes': b, 'bytes_total': sum(b.values()), 'next_due_at': w['next_due_at']})
    for k, v in b.items():
        tot[k] += v
    tot['images_official'] += len(ids['official_image'])
costs = [x['actual_request_cost'] for x in attempts if x['actual_request_cost'] is not None]
out['summary'] = {
    'work_rows': len(work), 'attempts': len(attempts),
    'outcomes': dict(Counter(x['outcome'] for x in attempts)),
    'work_state': dict(Counter(f"{w['state']}/{w['last_outcome']}" for w in work)),
    'first_start': min(x['started_at'] for x in attempts) if attempts else None,
    'last_finish': max(x['finished_at'] for x in attempts) if attempts else None,
    'shards': dict(Counter(x['claimed_by'].split(':')[0] for x in attempts)),
    'request_cost': {'total': sum(costs), 'avg': round(sum(costs) / len(costs), 2) if costs else None,
                     'min': min(costs, default=None), 'max': max(costs, default=None),
                     'over_reservation': sum(1 for x in attempts if (x['actual_request_cost'] or 0) > x['reserved_request_cost'])},
    'identity_status': dict(Counter((w['cur'] or {}).get('identity_status') for w in work)),
    'parked_after_capture': sum(1 for w in work if str(w['next_due_at']) >= '2100'),
    'snapshots': len(all_ids), 'snapshots_found': len(sizes),
    'http_status': dict(Counter(s['http_status'] for s in sizes.values())),
    'yuyu_images': sum(len(s['yuyu_image']) for s in snap_ids.values()),
    'official_images': tot['images_official'],
    'stored_bytes': {'product_html': tot['product'], 'yuyu_image': tot['yuyu_image'], 'official_image': tot['official_image'],
                     'total': tot['product'] + tot['yuyu_image'] + tot['official_image']},
}
s = out['summary']
s['stored_mb'] = round(s['stored_bytes']['total'] / 1_000_000, 2)
s['stored_bytes_per_capture'] = round(s['stored_bytes']['total'] / max(1, len(work)))
out['records'] = rows
print(json.dumps(out, indent=1, default=str))
