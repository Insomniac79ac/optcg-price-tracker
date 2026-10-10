"""Read-only lossless verification of every daily-v1 ledger row (id > 37711). No writes, no source HTTP.

usage: verify_all.py <out.json>
Same checks as session-7a verify_canary.py, batched by ledger id with a base-body cache so
no single statement transfers every body. Each row is reconstructed by an independent
zstd path and by the package decoder; both must match ledger original_sha256/bytes and
the snapshot content_hash.
"""
import base64, hashlib, json, sys
sys.path[:0] = ['/workspaces/cp-s8/scripts', '/workspaces/cp-s8/packages/opcg_source_identity/src',
                '/workspaces/cp-s8/docs/agent/handoff/2026-10-10/capacity75-session8/tools']
import zstandard as zstd
from opcg_source_identity.raw_payload import PREFIX, decode
from db import connection

H = lambda b: hashlib.sha256(b).hexdigest()
FLOOR, BATCH = 37711, 100


def independent(stored, base):
    env = json.loads(stored[len(PREFIX):])
    comp = base64.b64decode(env['data'], validate=True)
    d = zstd.ZstdCompressionDict(base, dict_type=zstd.DICT_TYPE_RAWCONTENT)
    return env, zstd.ZstdDecompressor(dict_data=d).decompress(comp, max_output_size=16 * 1024**2)


res = {'target': 'staging', 'read_only': True, 'source_requests': 0, 'database_writes': 0,
       'ledger_id_floor_exclusive': FLOOR, 'failures': [], 'expanded': [], 'by_source': {}}
bases, ok, n, last = {}, True, 0, FLOOR
with connection() as db:
    db.read_only = True
    res['ledger_max_id'] = db.execute('select max(id) m from raw_snapshot_dictionaries').fetchone()['m']
    while True:
        rows = db.execute('''select d.*, r.source_url, r.source_id, r.parser_version, r.http_status, r.content_hash,
              r.raw_content stored, s.name source from raw_snapshot_dictionaries d join raw_snapshots r on r.id=d.id
              join sources s on s.id=r.source_id where d.id > %s and d.id <= %s order by d.id limit %s''',
                          (last, res['ledger_max_id'], BATCH)).fetchall()
        if not rows:
            break
        for r in rows:
            last = r['id']; n += 1
            agg = res['by_source'].setdefault(r['source'], {'rows': 0, 'original_bytes': 0, 'encoded_bytes': 0})
            agg['rows'] += 1; agg['original_bytes'] += r['original_bytes']; agg['encoded_bytes'] += r['encoded_bytes']
            stored = r['stored']
            if r['expanded_at'] is not None and not stored.startswith(PREFIX):
                good = H(stored.encode()) == r['original_sha256'] == r['content_hash']
                res['expanded'].append({'id': r['id'], 'ok': good}); ok &= good
                continue
            bid = r['base_snapshot_id']
            if bid not in bases:
                bases[bid] = db.execute('select id, raw_content, content_hash, source_url, source_id, parser_version from raw_snapshots where id=%s', (bid,)).fetchone()
                if len(bases) > 400:
                    bases.pop(next(iter(bases)))
            b = bases[bid]; base = b['raw_content'].encode()
            checks = {
                'encoded': stored.startswith(PREFIX),
                'base_plain_older_same_scope': (not b['raw_content'].startswith(PREFIX) and bid < r['id']
                    and (r['source_url'], r['source_id'], r['parser_version']) == (b['source_url'], b['source_id'], b['parser_version'])),
                'base_hash': H(base) == b['content_hash'] == r['base_sha256'],
            }
            try:
                env, body = independent(stored, base)
                pkg = decode(stored, expected_hash=r['content_hash'], load_base=lambda _: base)
                checks.update({
                    'envelope_base_id': env['base_id'] == bid,
                    'independent_sha': H(body) == r['original_sha256'] == r['content_hash'] == env['sha256'],
                    'independent_len': len(body) == r['original_bytes'] == env['byte_length'],
                    'package_equals_independent': pkg == body,
                })
            except Exception as exc:
                checks['decode_error'] = False; checks['error'] = repr(exc)[:200]
            checks['encoded_bytes'] = len(stored.encode()) == r['encoded_bytes']
            checks['http200'] = r['http_status'] == 200
            good = all(v for k, v in checks.items() if k != 'error')
            if not good:
                res['failures'].append({'id': r['id'], 'checks': checks}); ok = False
        print(f'verified through {last} ({n} rows), failures={len(res["failures"])}', flush=True)
    db.rollback()
res['rows_checked'] = n
res['last_id'] = last
res['all_lossless'] = ok and n > 0
open(sys.argv[1], 'w').write(json.dumps(res, default=str, indent=1) + '\n')
print(json.dumps({k: v for k, v in res.items()}, default=str)[:3000])
