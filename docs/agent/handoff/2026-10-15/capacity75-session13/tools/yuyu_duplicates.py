"""Read-only: owner decision 3 (2026-10-14) evidence for Yuyu work rows 2628-2630.

For each blocked work row: its inactive mapping, and the active exact mapping on the same
card print and source (must exist, be approved/unsuperseded, and be fresh). Also what a
"close" would touch: freshness_work allows only pending/claimed/blocked, so closing means a
row delete, which cascades (ON DELETE CASCADE) to freshness_attempts and
freshness_price_states. Those dependent rows are exported here in full so any later write
has an exact rollback. No writes, no source HTTP.
usage: yuyu_duplicates.py > out.json
"""
import json, sys
sys.path.insert(0, '/workspaces/cp-cap13/docs/agent/handoff/2026-10-15/capacity75-session13/tools')
from db import connection

WORK = (2628, 2629, 2630)
out = {'read_only': True, 'source_requests': 0, 'database_writes': 0, 'work_ids': WORK, 'items': []}
with connection() as db:
    out['observed_at'] = db.execute("select now() at time zone 'utc' t").fetchone()['t']
    out['state_constraint'] = db.execute("""select pg_get_constraintdef(oid) d from pg_constraint
        where conrelid='freshness_work'::regclass and conname='ck_freshness_work_state'""").fetchone()['d']
    out['cascades_from_freshness_work'] = db.execute("""select conrelid::regclass::text tbl, confdeltype
        from pg_constraint where confrelid='freshness_work'::regclass and contype='f' order by 1""").fetchall()
    for wid in WORK:
        w = db.execute("select to_jsonb(w) j from freshness_work w where id=%s", (wid,)).fetchone()['j']
        m = db.execute("select to_jsonb(m) j from source_card_mappings m where id=%s", (w['source_card_mapping_id'],)).fetchone()['j']
        active = db.execute("""select m.id, m.review_status, m.manual_verified, m.superseded_at, m.canonical_source_listing_identity,
            m.source_url, w.id work_id, w.state work_state, ps.last_successfully_checked_at,
            round(extract(epoch from now()-ps.last_successfully_checked_at)/3600,1) age_hours
            from source_card_mappings m left join freshness_work w on w.source_card_mapping_id=m.id and w.kind='refresh'
            left join freshness_price_states ps on ps.work_id=w.id and ps.price_category='raw'
            where m.source_id=%s and m.card_print_id=%s and m.is_active and m.id<>%s""",
            (m['source_id'], m['card_print_id'], m['id'])).fetchall()
        attempts = [r['j'] for r in db.execute("select to_jsonb(a) j from freshness_attempts a where work_id=%s order by id", (wid,))]
        states = [r['j'] for r in db.execute("select to_jsonb(p) j from freshness_price_states p where work_id=%s order by id", (wid,))]
        ok = (w['state'] == 'blocked' and not m['is_active'] and len(active) == 1
              and active[0]['review_status'] == 'approved' and active[0]['superseded_at'] is None
              and active[0]['work_state'] == 'pending')
        out['items'].append({
            'work_id': wid, 'card_code': m['source_card_id'], 'card_print_id': m['card_print_id'],
            'inactive_mapping': {k: m[k] for k in ('id', 'is_active', 'review_status', 'canonical_source_listing_identity', 'source_url', 'created_at', 'updated_at')},
            'work_failure': w['last_failure'], 'active_exact_mappings': active,
            'duplicates_an_active_exact_mapping': ok,
            'rows_a_close_would_remove': {'freshness_work': 1, 'freshness_attempts': len(attempts), 'freshness_price_states': len(states)},
            'export': {'freshness_work': w, 'freshness_attempts': attempts, 'freshness_price_states': states},
        })
    out['counts'] = {
        'refresh_work_blocked': db.execute("select count(*) n from freshness_work where kind='refresh' and state='blocked'").fetchone()['n'],
        'yuyu_refresh_work_on_inactive_mappings': db.execute("""select count(*) n from freshness_work w join source_card_mappings m
            on m.id=w.source_card_mapping_id join sources s on s.id=w.source_id where s.name='yuyutei' and w.kind='refresh' and not m.is_active""").fetchone()['n'],
    }
    db.rollback()
out['all_qualify'] = all(i['duplicates_an_active_exact_mapping'] for i in out['items'])
print(json.dumps(out, indent=1, default=str))
