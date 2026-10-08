import sys, json
sys.path[:0] = ['/workspaces/cp-s7a/staging/packages/opcg_source_identity/src', '/workspaces/cp-s4/tools']
from opcg_source_identity.raw_payload import PREFIX, encode, sha256
from db import connection
out = []
with connection() as db:
    db.read_only = True
    for sid in (38417, 38440, 38442):
        r = db.execute('select id, source_id, parser_version, source_url, raw_content, content_hash, fetched_at, fetched_at created_at from raw_snapshots where id=%s', (sid,)).fetchone()
        ids = [x['id'] for x in db.execute('''select id from raw_snapshots where source_id=%s and parser_version=%s and md5(source_url)=md5(%s)
              and source_url=%s and http_status=200 and id<%s order by id desc limit 32''', (r['source_id'], r['parser_version'], r['source_url'], r['source_url'], sid)).fetchall()]
        recent = db.execute('select id, raw_content like %s enc from raw_snapshots where id = any(%s) order by id desc', (PREFIX + '%', ids)).fetchall()
        base_id = next((x['id'] for x in recent if not x['enc']), None)
        b = db.execute('select id, raw_content, content_hash, pg_column_size(raw_content) col from raw_snapshots where id=%s', (base_id,)).fetchone()
        body = r['raw_content'].encode()
        packed = encode(body, base_id=b['id'], base_body=b['raw_content'].encode())
        pb = len(packed.encode())
        # concurrent writers: other encodings created within +-10 s of this row
        near = db.execute('''select d.id, d.created_at, a.claimed_by from raw_snapshot_dictionaries d left join freshness_attempts a on a.raw_snapshot_id=d.id
              where d.created_at between %s - interval '15 seconds' and %s + interval '15 seconds' order by d.id''', (r['created_at'], r['created_at'])).fetchall()
        attempts = db.execute('''select a.claimed_by, a.claimed_at, a.finished_at from freshness_attempts a
              where a.claimed_at <= %s + interval '1 second' and coalesce(a.finished_at, now()) >= %s - interval '1 second' order by a.claimed_at''', (r['fetched_at'], r['fetched_at'])).fetchall()
        out.append({'id': sid, 'url': r['source_url'], 'fetched_at': r['fetched_at'], 'created_at': r['created_at'], 'hash_ok': sha256(body) == r['content_hash'],
                    'bytes': len(body), 'recent_scope_rows': len(ids), 'plaintext_in_recent': sum(not x['enc'] for x in recent), 'would_be_base': base_id,
                    'base_col_bytes': b['col'], 'packed_bytes': pb, 'savings_threshold_pass': pb * 4 <= b['col'] * 3,
                    'ledger_rows_created_within_15s': [dict(x) for x in near], 'overlapping_attempts': [dict(x) for x in attempts]})
    db.rollback()
json.dump(out, open(sys.argv[1], 'w'), default=str, indent=1)
print(json.dumps(out, default=str, indent=1))
