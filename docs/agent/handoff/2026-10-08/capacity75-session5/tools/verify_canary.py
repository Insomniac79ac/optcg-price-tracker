"""Read-only verification of one SNKR dictionary canary turn. No writes, no source HTTP.

usage: verify_canary.py <turn_start_utc> <turn_end_utc> <ledger_max_id_before> <out.json>
Each new ledger row is reconstructed twice: an independent zstd path written
here, and the package decoder. Both must equal the ledger original_sha256 /
original_bytes and the snapshot content_hash.
"""
import base64, hashlib, json, sys
sys.path[:0] = ['/workspaces/cp-s5/staging/scripts', '/workspaces/cp-s5/staging/packages/opcg_source_identity/src']
sys.path.insert(0, '/workspaces/cp-s4/tools')
import zstandard as zstd
from opcg_source_identity.raw_payload import PREFIX, decode
from db import connection

start, end, before_max, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
H = lambda b: hashlib.sha256(b).hexdigest()


def independent(stored, base):
    env = json.loads(stored[len(PREFIX):])
    comp = base64.b64decode(env['data'], validate=True)
    d = zstd.ZstdCompressionDict(base, dict_type=zstd.DICT_TYPE_RAWCONTENT)
    body = zstd.ZstdDecompressor(dict_data=d).decompress(comp, max_output_size=16 * 1024**2)
    return env, body


res = {'target': 'staging', 'read_only': True, 'source_requests': 0, 'database_writes': 0,
       'turn': [start, end], 'ledger_max_id_before': before_max, 'rows': []}
with connection() as db:
    db.read_only = True
    rows = db.execute('''
      select d.*, r.source_id, r.source_url, r.parser_version, r.http_status, r.content_hash, r.fetched_at,
             r.raw_content stored, pg_column_size(r.raw_content) stored_col_bytes,
             b.raw_content base_stored, b.content_hash base_hash, b.source_url base_url, b.source_id base_source,
             b.parser_version base_parser, pg_column_size(b.raw_content) base_col_bytes
      from raw_snapshot_dictionaries d join raw_snapshots r on r.id=d.id join raw_snapshots b on b.id=d.base_snapshot_id
      where d.id > %s order by d.id''', (before_max,)).fetchall()
    ok = True
    for r in rows:
        stored, base = r['stored'], r['base_stored'].encode()
        if r['expanded_at'] is not None and not stored.startswith(PREFIX):
            res['rows'].append({'id': r['id'], 'expanded_at': str(r['expanded_at']),
                                'plaintext_sha_ok': H(stored.encode()) == r['original_sha256'] == r['content_hash']})
            ok &= res['rows'][-1]['plaintext_sha_ok']
            continue
        checks = {
            'encoded': stored.startswith(PREFIX),
            'base_plain_older_same_scope': (not r['base_stored'].startswith(PREFIX) and r['base_snapshot_id'] < r['id']
                and (r['source_url'], r['source_id'], r['parser_version']) == (r['base_url'], r['base_source'], r['base_parser'])),
            'base_hash': H(base) == r['base_hash'] == r['base_sha256'],
        }
        env, body = independent(stored, base)
        pkg = decode(stored, expected_hash=r['content_hash'], load_base=lambda _: base)
        checks.update({
            'envelope_base_id': env['base_id'] == r['base_snapshot_id'],
            'independent_sha': H(body) == r['original_sha256'] == r['content_hash'] == env['sha256'],
            'independent_len': len(body) == r['original_bytes'] == env['byte_length'],
            'package_equals_independent': pkg == body,
            'encoded_bytes': len(stored.encode()) == r['encoded_bytes'],
            'http200': r['http_status'] == 200,
        })
        ok &= all(checks.values())
        res['rows'].append({'id': r['id'], 'base_id': r['base_snapshot_id'], 'url': r['source_url'],
            'parser': r['parser_version'], 'fetched_at': str(r['fetched_at']), 'created_at': str(r['created_at']),
            'original_sha256': r['original_sha256'], 'original_bytes': r['original_bytes'],
            'encoded_bytes': r['encoded_bytes'], 'stored_col_bytes': r['stored_col_bytes'],
            'base_col_bytes': r['base_col_bytes'], 'checks': checks})
    res['all_lossless'] = ok and bool(rows)
    res['encoded_rows'] = len(rows)
    res['original_bytes_total'] = sum(r['original_bytes'] for r in rows)
    res['encoded_bytes_total'] = sum(r['encoded_bytes'] for r in rows)
    # Physical comparison: what PostgreSQL would store for the same plaintext ~= base column size.
    res['stored_col_bytes_total'] = sum(r['stored_col_bytes'] for r in rows)
    res['plaintext_col_bytes_estimate'] = sum(r['base_col_bytes'] for r in rows)
    # Turn accounting
    res['snkr_raw_in_turn'] = db.execute('''select count(*) n, count(*) filter (where r.http_status=200) ok200,
        count(*) filter (where r.raw_content like %s) encoded, sum(pg_column_size(r.raw_content)) col_bytes
        from raw_snapshots r join sources s on s.id=r.source_id
        where s.name='snkrdunk' and r.fetched_at between %s and %s''', (PREFIX + '%', start, end)).fetchone()
    res['snkr_attempts_in_turn'] = db.execute('''select a.outcome, count(*) n, sum(a.charged_request_cost) charged,
        min(a.claimed_at) first_claim, max(a.finished_at) last_finish,
        extract(epoch from max(a.finished_at)-min(a.claimed_at)) span_s
        from freshness_attempts a join freshness_work w on w.id=a.work_id join sources s on s.id=w.source_id
        where s.name='snkrdunk' and a.claimed_at between %s and %s group by 1''', (start, end)).fetchall()
    res['leases'] = db.execute('''select count(*) filter (where claim_expires_at<now()) expired,
        count(*) filter (where claim_token is not null) claimed from freshness_work w join sources s on s.id=w.source_id
        where s.name='snkrdunk' ''').fetchone()
    res['open_attempts'] = db.execute('select count(*) n from freshness_attempts where finished_at is null').fetchone()['n']
    res['budget'] = db.execute('''select b.* from source_dispatch_budgets b join sources s on s.id=b.source_id
        where s.name='snkrdunk' ''').fetchone()
    res['ledger_total'] = db.execute('select count(*) n from raw_snapshot_dictionaries').fetchone()['n']
    # Lookup cost: EXPLAIN ANALYZE of the writer's bounded scope-id query, per encoded URL.
    plans = []
    for r in rows[:10]:
        p = db.execute('''explain (analyze, buffers, format json) select r.id from raw_snapshots r
            where r.source_id=%s and r.parser_version=%s and md5(r.source_url)=md5(%s) and r.source_url=%s
            and r.http_status=200 order by r.id desc limit 32''',
            (r['source_id'], r['parser_version'], r['source_url'], r['source_url'])).fetchone()
        plan = list(p.values())[0][0]
        plans.append({'id': r['id'], 'execution_ms': plan['Execution Time'], 'planning_ms': plan['Planning Time'],
                      'shared_hit': plan['Plan'].get('Shared Hit Blocks'), 'shared_read': plan['Plan'].get('Shared Read Blocks')})
    res['lookup_explain'] = plans
    db.rollback()
open(out, 'w').write(json.dumps(res, default=str, indent=2) + '\n')
print(json.dumps({k: v for k, v in res.items() if k not in ('rows',)}, default=str, indent=1)[:4000])
