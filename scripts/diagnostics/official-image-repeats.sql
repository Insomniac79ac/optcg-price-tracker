-- Official card images retained by identity captures: how many were already stored earlier with the
-- same bytes (storage option B) and how many the R2 official-image mirror already holds (option D).
-- Owner ask 2026-10-18 13:51Z. Read-only, MEASURED: content_hash and pg_column_size only, nothing
-- is decoded or detoasted.
-- Official image: a raw_snapshots row with parser_version 'yuyu-identity-evidence-v1' whose
-- source_url is a www.onepiece-cardgame.com card image. raw_content is a deterministic JSON envelope
-- of the base64 body (identity_evidence.retain_image), so the same content_hash means the same bytes.
-- repeat: an earlier official-image row (fetched_at, then id) has the same content_hash.
-- mirrored: a card_print_image_assets row for the same source_url has sha256 equal to the
-- artwork_key the capture recorded for that print (physical_artwork_proof requires the retained
-- body to hash to it). unreferenced: no capture's resume_cursor names the row (unfinished capture).
-- Bytes are pg_column_size (stored). Days are UTC.

-- by_day
with oi as (
  select r.id, date_trunc('day', r.fetched_at at time zone 'UTC') d, r.source_url, r.content_hash,
    pg_column_size(r.raw_content) stored_bytes,
    row_number() over (partition by r.content_hash order by r.fetched_at, r.id) > 1 is_repeat
  from raw_snapshots r
  where r.parser_version = 'yuyu-identity-evidence-v1'
    and r.source_url like 'https://www.onepiece-cardgame.com/images/cardlist/card/%'),
refs as (
  select distinct on ((o ->> 'raw_snapshot_id')::bigint) (o ->> 'raw_snapshot_id')::bigint snapshot_id,
    o ->> 'artwork_key' artwork_key
  from freshness_work w
  cross join lateral jsonb_array_elements(coalesce(w.resume_cursor::jsonb -> 'official_images', '[]'::jsonb)) o
  where w.kind = 'discovery' and w.resume_cursor is not null
    and w.resume_cursor::jsonb ->> 'explicit_identity_capture' = 'true'
  order by 1, w.id),
x as (
  select oi.*, refs.snapshot_id is not null referenced,
    exists (select 1 from card_print_image_assets a
            where a.source_url = oi.source_url and a.sha256 = refs.artwork_key) mirrored
  from oi left join refs on refs.snapshot_id = oi.id)
select d day_utc, count(*) snapshots, sum(stored_bytes) stored_bytes,
  count(*) filter (where is_repeat) repeat_snapshots, coalesce(sum(stored_bytes) filter (where is_repeat), 0) repeat_bytes,
  count(*) filter (where mirrored) mirrored_snapshots, coalesce(sum(stored_bytes) filter (where mirrored), 0) mirrored_bytes,
  count(*) filter (where is_repeat or mirrored) repeat_or_mirrored_snapshots,
  count(*) filter (where not referenced) unreferenced, count(distinct content_hash) distinct_images
from x where d >= date_trunc('day', now() at time zone 'UTC') - interval '13 days'
group by 1 order by 1;

-- windows
with oi as (
  select r.id, date_trunc('day', r.fetched_at at time zone 'UTC') d, r.source_url, r.content_hash,
    pg_column_size(r.raw_content) stored_bytes,
    row_number() over (partition by r.content_hash order by r.fetched_at, r.id) > 1 is_repeat
  from raw_snapshots r
  where r.parser_version = 'yuyu-identity-evidence-v1'
    and r.source_url like 'https://www.onepiece-cardgame.com/images/cardlist/card/%'),
refs as (
  select distinct on ((o ->> 'raw_snapshot_id')::bigint) (o ->> 'raw_snapshot_id')::bigint snapshot_id,
    o ->> 'artwork_key' artwork_key
  from freshness_work w
  cross join lateral jsonb_array_elements(coalesce(w.resume_cursor::jsonb -> 'official_images', '[]'::jsonb)) o
  where w.kind = 'discovery' and w.resume_cursor is not null
    and w.resume_cursor::jsonb ->> 'explicit_identity_capture' = 'true'
  order by 1, w.id),
x as (
  select oi.*, refs.snapshot_id is not null referenced,
    exists (select 1 from card_print_image_assets a
            where a.source_url = oi.source_url and a.sha256 = refs.artwork_key) mirrored
  from oi left join refs on refs.snapshot_id = oi.id),
w as (
  select 'last_14_days' win, x.* from x where d >= date_trunc('day', now() at time zone 'UTC') - interval '13 days'
  union all
  select 'all_time', x.* from x)
select win, count(*) snapshots, sum(stored_bytes) stored_bytes,
  coalesce(sum(stored_bytes) filter (where is_repeat), 0) repeat_bytes,
  round(100.0 * coalesce(sum(stored_bytes) filter (where is_repeat), 0) / nullif(sum(stored_bytes), 0), 1) repeat_pct_bytes,
  round(100.0 * count(*) filter (where is_repeat) / nullif(count(*), 0), 1) repeat_pct_snapshots,
  coalesce(sum(stored_bytes) filter (where mirrored), 0) mirrored_bytes,
  round(100.0 * coalesce(sum(stored_bytes) filter (where mirrored), 0) / nullif(sum(stored_bytes), 0), 1) mirrored_pct_bytes,
  round(100.0 * coalesce(sum(stored_bytes) filter (where is_repeat or mirrored), 0) / nullif(sum(stored_bytes), 0), 1) repeat_or_mirrored_pct_bytes,
  count(distinct content_hash) distinct_images, count(*) filter (where not referenced) unreferenced
from w group by 1 order by 1 desc;
