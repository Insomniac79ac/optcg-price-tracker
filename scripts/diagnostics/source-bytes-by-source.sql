-- Bytes stored per source per UTC day (new-sources plan S0, owner approved 2026-10-19). Read-only.
-- Attributes database growth to a source so a new-source storage check (Dorasuta cap 1.5 MB/day
-- over 48 h, decision N6) can overlap Yuyu-Tei batches without mixing the numbers. RAW bytes are
-- pg_column_size(raw_content) (stored, after TOAST compression; a dictionary-encoded row stores
-- its encoded text) and octet_length (the text before TOAST compression). Row bytes are
-- pg_column_size(row) (heap tuple data only; indexes and page overhead are not included, so the
-- disk figure from storage-rates stays the total). Window: the last 8 UTC days.

-- raw_by_source_day
select s.name source, date_trunc('day', r.fetched_at) day_utc, count(*) snapshots,
  sum(pg_column_size(r.raw_content)) stored_bytes, sum(octet_length(r.raw_content)) text_bytes,
  count(x.id) encoded
from raw_snapshots r join sources s on s.id = r.source_id left join raw_snapshot_dictionaries x on x.id = r.id
where r.fetched_at >= date_trunc('day', now()) - interval '7 days'
group by 1, 2 order by 2, 1;

-- observations_by_source_day
select s.name source, date_trunc('day', o.observed_at) day_utc, o.price_type, count(*) observation_rows,
  sum(pg_column_size(o.*)) row_bytes
from price_observations o join sources s on s.id = o.source_id
where o.observed_at >= date_trunc('day', now()) - interval '7 days'
group by 1, 2, 3 order by 2, 1, 3;

-- attempts_by_source_day
select s.name source, date_trunc('day', a.selected_at) day_utc, count(*) attempt_rows,
  sum(pg_column_size(a.*)) row_bytes, count(*) filter (where a.source_denied) denied
from source_collection_attempts a join sources s on s.id = a.source_id
where a.selected_at >= date_trunc('day', now()) - interval '7 days'
group by 1, 2 order by 2, 1;

-- last_48h_by_source
with raw as (
  select r.source_id, sum(pg_column_size(r.raw_content)) b from raw_snapshots r
  where r.fetched_at >= now() - interval '48 hours' group by 1),
obs as (
  select o.source_id, sum(pg_column_size(o.*)) b from price_observations o
  where o.observed_at >= now() - interval '48 hours' group by 1),
att as (
  select a.source_id, sum(pg_column_size(a.*)) b from source_collection_attempts a
  where a.selected_at >= now() - interval '48 hours' group by 1)
select s.name source, coalesce(raw.b, 0) raw_stored_bytes, coalesce(obs.b, 0) observation_row_bytes,
  coalesce(att.b, 0) attempt_row_bytes,
  round((coalesce(raw.b, 0) + coalesce(obs.b, 0) + coalesce(att.b, 0)) / 2.0 / 1048576, 3) mb_per_day
from sources s left join raw on raw.source_id = s.id left join obs on obs.source_id = s.id
left join att on att.source_id = s.id
order by 5 desc, 1;
