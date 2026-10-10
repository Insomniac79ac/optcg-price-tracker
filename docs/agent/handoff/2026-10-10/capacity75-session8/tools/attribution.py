"""Session 7 read-only storage attribution. No source HTTP, no writes.

usage: attribution.py <out.json>

Compares physical stored column bytes of NEW raw_snapshots rows in the 24h
daily-v1 window with the 24h writer-off window before activation, and
estimates the transient plaintext TOAST written by the writer's
insert-then-update path (raw_dictionary_storage._encode_new_snapshot flushes
the pending plaintext INSERT before setting the encoded representation).
"""
import json, sys
sys.path[:0] = ['/workspaces/cp-s8/scripts', '/workspaces/cp-s8/packages/opcg_source_identity/src',
                '/workspaces/cp-s8/docs/agent/handoff/2026-10-10/capacity75-session8/tools']
import generate_staging_state as state
from opcg_source_identity.raw_payload import PREFIX
from db import connection

ACT = '2026-10-08 13:45:05Z'
WINDOWS = {
    'pre_d2': ('2026-10-06 13:45:05Z', '2026-10-07 13:45:05Z'),
    'pre_d1': ('2026-10-07 13:45:05Z', ACT),
    'on_seg1_to_7a': (ACT, '2026-10-08 22:12:37Z'),
    'on_seg2_from_7a': ('2026-10-08 22:12:37Z', '2026-10-09 13:56:11Z'),
    'on_24h': (ACT, '2026-10-09 13:45:05Z'),
}
BY_KIND = """
select s.name source, r.parser_version, r.http_status, (d.id is not null and d.expanded_at is null) encoded,
  count(*) n,
  sum(pg_column_size(r.raw_content)) stored_col_bytes,
  sum(coalesce(d.original_bytes, octet_length(r.raw_content))) logical_bytes,
  sum(pg_column_size(b.raw_content)) base_col_bytes,
  count(*) filter (where pg_column_size(r.raw_content) > 2000) toasted_rows
from raw_snapshots r join sources s on s.id = r.source_id
left join raw_snapshot_dictionaries d on d.id = r.id
left join raw_snapshots b on b.id = d.base_snapshot_id
where r.fetched_at >= %(a)s and r.fetched_at < %(b)s
group by 1,2,3,4 order by 1,2,3,4"""
BY_COLLECTOR = """
select coalesce(split_part(a.claimed_by, ':', 1), 'no-attempt:' || s.name) collector,
  r.parser_version, (d.id is not null and d.expanded_at is null) encoded, count(*) n,
  sum(pg_column_size(r.raw_content)) stored_col_bytes,
  sum(coalesce(d.original_bytes, octet_length(r.raw_content))) logical_bytes,
  sum(pg_column_size(b.raw_content)) base_col_bytes
from raw_snapshots r join sources s on s.id = r.source_id
left join freshness_attempts a on a.raw_snapshot_id = r.id
left join raw_snapshot_dictionaries d on d.id = r.id
left join raw_snapshots b on b.id = d.base_snapshot_id
where r.fetched_at >= %(a)s and r.fetched_at < %(b)s
group by 1,2,3 order by 1,2,3"""
# SNKR/Yuyu per-URL physical comparison: each encoded row against the median
# stored size of writer-off plaintext rows of the SAME URL+parser before activation.
SAME_URL = """
with enc as (
  select r.id, s.name source, r.source_url, r.parser_version, pg_column_size(r.raw_content) enc_col,
         d.original_bytes, pg_column_size(b.raw_content) base_col, d.base_snapshot_id,
         extract(epoch from r.fetched_at - b.fetched_at)/86400.0 base_age_days, r.fetched_at
  from raw_snapshot_dictionaries d join raw_snapshots r on r.id = d.id join sources s on s.id = r.source_id
  join raw_snapshots b on b.id = d.base_snapshot_id where d.id > 37711),
pre as (
  select r.source_url, r.parser_version, percentile_cont(0.5) within group (order by pg_column_size(r.raw_content)) med_col,
         percentile_cont(0.5) within group (order by octet_length(r.raw_content)) med_len, count(*) n
  from raw_snapshots r where r.fetched_at < %(act)s and r.http_status = 200 and not exists (select 1 from raw_snapshot_dictionaries x where x.id = r.id)
    and r.source_url in (select source_url from enc) group by 1,2)
select enc.source, count(*) rows, count(pre.n) rows_with_pre,
  sum(enc.enc_col) enc_col, sum(enc.base_col) base_col, sum(pre.med_col) filter (where pre.n is not null) pre_med_col,
  sum(enc.enc_col) filter (where pre.n is not null) enc_col_with_pre,
  sum(enc.original_bytes) original_bytes, sum(pre.med_len) filter (where pre.n is not null) pre_med_len,
  round(avg(enc.base_age_days)::numeric, 2) avg_base_age_days
from enc left join pre on pre.source_url = enc.source_url and pre.parser_version = enc.parser_version
group by 1 order by 1"""
# Delta size against base age: dictionary freshness.
AGE = """
select s.name source, width_bucket(extract(epoch from r.fetched_at - b.fetched_at)/86400.0, 0, 8, 8) age_bucket_days,
  count(*) n, round(avg(pg_column_size(r.raw_content))) avg_enc_col, round(avg(pg_column_size(b.raw_content))) avg_base_col,
  round(avg(d.original_bytes)) avg_original, round(sum(pg_column_size(r.raw_content))::numeric / sum(pg_column_size(b.raw_content)), 4) enc_over_base
from raw_snapshot_dictionaries d join raw_snapshots r on r.id = d.id join sources s on s.id = r.source_id
join raw_snapshots b on b.id = d.base_snapshot_id where d.id > %(m)s group by 1,2 order by 1,2"""
SNKR_TURNS = """
select date_trunc('hour', r.fetched_at) hr, count(*) n, round(avg(pg_column_size(r.raw_content))) avg_enc_col,
  round(avg(pg_column_size(b.raw_content))) avg_base_col, round(avg(d.original_bytes)) avg_orig,
  round(1 - sum(pg_column_size(r.raw_content))::numeric / sum(pg_column_size(b.raw_content)), 4) saved_vs_base_col,
  round(1 - sum(pg_column_size(r.raw_content))::numeric / sum(d.original_bytes), 4) saved_vs_logical,
  round(avg(extract(epoch from r.fetched_at - b.fetched_at)/86400.0)::numeric, 2) avg_base_age_days,
  count(distinct r.source_url) urls
from raw_snapshot_dictionaries d join raw_snapshots r on r.id = d.id join sources s on s.id = r.source_id
join raw_snapshots b on b.id = d.base_snapshot_id where s.name = 'snkrdunk' and d.id > 37600 group by 1 order by 1"""
RELATIONS = """
select c.relname, c.relkind, pg_total_relation_size(c.oid) total, pg_relation_size(c.oid) main,
  coalesce(pg_relation_size(nullif(c.reltoastrelid, 0)), 0) toast, pg_indexes_size(c.oid) idx,
  st.n_live_tup, st.n_dead_tup, st.n_tup_ins, st.n_tup_upd, st.n_tup_del
from pg_class c left join pg_stat_user_tables st on st.relid = c.oid
where c.relkind = 'r' and c.relnamespace = 'public'::regnamespace order by 3 desc limit 15"""
NOW = """select now(), pg_database_size(current_database()) db_bytes, pg_total_relation_size('raw_snapshots') raw_total,
  pg_relation_size('raw_snapshots') raw_heap, pg_indexes_size('raw_snapshots') raw_idx,
  pg_relation_size((select reltoastrelid from pg_class where oid='raw_snapshots'::regclass)) raw_toast,
  (select sum(pg_relation_size(indexrelid)) from pg_index where indrelid=(select reltoastrelid from pg_class where oid='raw_snapshots'::regclass)) raw_toast_idx,
  pg_current_wal_lsn()::text lsn"""
TOAST_STATS = """select relname, n_live_tup, n_dead_tup, n_tup_ins, n_tup_upd, n_tup_del, autovacuum_count, last_autovacuum,
  n_ins_since_vacuum from pg_stat_all_tables where relid in ('raw_snapshots'::regclass,
  (select reltoastrelid from pg_class where oid='raw_snapshots'::regclass))"""
WAL = "select * from pg_stat_wal"
WALDIR = "select count(*) files, sum(size) bytes from pg_ls_waldir()"

res = {'target': 'staging', 'read_only': True, 'source_requests': 0, 'database_writes': 0, 'windows': WINDOWS}
with connection() as db:
    db.read_only = True
    res['now'] = db.execute(NOW).fetchone()
    res['toast_stats'] = db.execute(TOAST_STATS).fetchall()
    res['wal_stats'] = db.execute(WAL).fetchone()
    try:
        res['wal_dir'] = db.execute(WALDIR).fetchone()
    except Exception as exc:  # pg_ls_waldir needs pg_monitor; record the refusal.
        db.rollback(); db.read_only = True
        res['wal_dir'] = {'error': type(exc).__name__, 'message': str(exc).splitlines()[0]}
    res['by_kind'] = {k: db.execute(BY_KIND, {'a': a, 'b': b, 'p': PREFIX + '%'}).fetchall() for k, (a, b) in WINDOWS.items()}
    res['by_collector'] = {k: db.execute(BY_COLLECTOR, {'a': a, 'b': b, 'p': PREFIX + '%'}).fetchall()
                           for k, (a, b) in WINDOWS.items() if k in ('pre_d1', 'on_24h')}
    res['same_url_vs_pre_activation'] = db.execute(SAME_URL, {'act': ACT, 'p': PREFIX + '%'}).fetchall()
    res['delta_vs_base_age'] = db.execute(AGE, {'m': 37711}).fetchall()
    res['snkr_by_hour_incl_canary'] = db.execute(SNKR_TURNS).fetchall()
    res['relations'] = db.execute(RELATIONS).fetchall()
    db.rollback()
open(sys.argv[1], 'w').write(json.dumps(res, default=str, indent=1) + '\n')
print(json.dumps({k: v for k, v in res.items() if k not in ('by_collector', 'relations')}, default=str, indent=1)[:12000])
