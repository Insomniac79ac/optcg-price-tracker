-- Priced prints by rarity and by number of shop sources (new-sources plan S0, owner approved
-- 2026-10-19). Read-only. Population: active verified card_prints (the coverage denominator, as in
-- yuyu-coverage-gap). A print is priced by a source when an eligible mapping (active, current,
-- approved, same print) carries a raw ask observation with a positive price inside the window.
-- Raw asks are the (source, price_type) pairs in `ra` below: Yuyu-Tei sell and the SNKRDUNK raw
-- floor today; each new source adds its pair when its collector is built. Buy quotes, sold rows
-- and graded asks are never counted. Windows: 24 h (the operational freshness target) and 7 days
-- (the Q4 shop-ask rule). This reads observations, not freshness states, so it can differ slightly
-- from yuyu-coverage-gap's state-based "fresh" count.

-- overview
with ra(source, price_type) as (values ('yuyutei', 'sell'), ('snkrdunk', 'floor')),
pr as (
  select p.id print_id from card_prints p where p.is_active and p.verification_status = 'verified'),
ob as (
  select o.card_print_id print_id, s.name source, max(o.observed_at) last_at
  from price_observations o join sources s on s.id = o.source_id
  join ra on ra.source = s.name and ra.price_type = o.price_type
  join source_card_mappings m on m.id = o.source_card_mapping_id and m.card_print_id = o.card_print_id
    and m.is_active and m.superseded_at is null and m.review_status = 'approved'
  where o.observed_at >= now() - interval '7 days' and o.price_jpy > 0 and o.card_print_id is not null
  group by 1, 2),
pc as (
  select pr.print_id, count(ob.source) filter (where ob.last_at >= now() - interval '24 hours') n24,
    count(ob.source) n7
  from pr left join ob using (print_id) group by 1)
select count(*) verified_prints,
  count(*) filter (where n24 > 0) priced_24h, round(100.0 * count(*) filter (where n24 > 0) / nullif(count(*), 0), 1) pct_24h,
  count(*) filter (where n7 > 0) priced_7d, round(100.0 * count(*) filter (where n7 > 0) / nullif(count(*), 0), 1) pct_7d,
  count(*) filter (where n24 = 0) zero_sources_24h, count(*) filter (where n24 = 1) one_source_24h,
  count(*) filter (where n24 >= 2) two_plus_sources_24h,
  count(*) filter (where n7 = 0) zero_sources_7d, count(*) filter (where n7 = 1) one_source_7d,
  count(*) filter (where n7 >= 2) two_plus_sources_7d
from pc;

-- by_rarity
with ra(source, price_type) as (values ('yuyutei', 'sell'), ('snkrdunk', 'floor')),
pr as (
  select p.id print_id, coalesce(nullif(p.official_rarity, ''), c.rarity, '?') rarity
  from card_prints p join canonical_cards c on c.id = p.canonical_card_id
  where p.is_active and p.verification_status = 'verified'),
ob as (
  select o.card_print_id print_id, s.name source, max(o.observed_at) last_at
  from price_observations o join sources s on s.id = o.source_id
  join ra on ra.source = s.name and ra.price_type = o.price_type
  join source_card_mappings m on m.id = o.source_card_mapping_id and m.card_print_id = o.card_print_id
    and m.is_active and m.superseded_at is null and m.review_status = 'approved'
  where o.observed_at >= now() - interval '7 days' and o.price_jpy > 0 and o.card_print_id is not null
  group by 1, 2),
pc as (
  select pr.print_id, pr.rarity, count(ob.source) filter (where ob.last_at >= now() - interval '24 hours') n24,
    count(ob.source) n7
  from pr left join ob using (print_id) group by 1, 2)
select rarity, count(*) prints,
  count(*) filter (where n24 > 0) priced_24h, round(100.0 * count(*) filter (where n24 > 0) / count(*), 1) pct_24h,
  count(*) filter (where n7 > 0) priced_7d, round(100.0 * count(*) filter (where n7 > 0) / count(*), 1) pct_7d,
  count(*) filter (where n24 >= 2) two_plus_24h, count(*) filter (where n7 >= 2) two_plus_7d
from pc group by 1 order by 2 desc, 1;

-- by_rarity_variant
with ra(source, price_type) as (values ('yuyutei', 'sell'), ('snkrdunk', 'floor')),
pr as (
  select p.id print_id, coalesce(nullif(p.official_rarity, ''), c.rarity, '?') rarity,
    case when p.official_asset_variant = 'base' then 'base' when p.official_asset_variant like 'p%' then 'parallel'
      when p.official_asset_variant like 'r%' then 'reprint' else 'unknown' end variant_kind
  from card_prints p join canonical_cards c on c.id = p.canonical_card_id
  where p.is_active and p.verification_status = 'verified'),
ob as (
  select o.card_print_id print_id, s.name source, max(o.observed_at) last_at
  from price_observations o join sources s on s.id = o.source_id
  join ra on ra.source = s.name and ra.price_type = o.price_type
  join source_card_mappings m on m.id = o.source_card_mapping_id and m.card_print_id = o.card_print_id
    and m.is_active and m.superseded_at is null and m.review_status = 'approved'
  where o.observed_at >= now() - interval '7 days' and o.price_jpy > 0 and o.card_print_id is not null
  group by 1, 2),
pc as (
  select pr.print_id, pr.rarity, pr.variant_kind,
    count(ob.source) filter (where ob.last_at >= now() - interval '24 hours') n24, count(ob.source) n7
  from pr left join ob using (print_id) group by 1, 2, 3)
select rarity, variant_kind, count(*) prints, count(*) filter (where n24 > 0) priced_24h,
  count(*) filter (where n7 > 0) priced_7d, count(*) filter (where n7 >= 2) two_plus_7d
from pc group by 1, 2 order by 1, 2;

-- by_source
with ra(source, price_type) as (values ('yuyutei', 'sell'), ('snkrdunk', 'floor')),
pr as (
  select p.id print_id from card_prints p where p.is_active and p.verification_status = 'verified'),
ob as (
  select o.card_print_id print_id, s.name source, max(o.observed_at) last_at
  from price_observations o join sources s on s.id = o.source_id
  join ra on ra.source = s.name and ra.price_type = o.price_type
  join source_card_mappings m on m.id = o.source_card_mapping_id and m.card_print_id = o.card_print_id
    and m.is_active and m.superseded_at is null and m.review_status = 'approved'
  where o.observed_at >= now() - interval '7 days' and o.price_jpy > 0 and o.card_print_id is not null
  group by 1, 2),
obp as (select ob.* from ob join pr using (print_id)),
solo as (select print_id from obp group by 1 having count(*) = 1)
select obp.source, count(*) filter (where obp.last_at >= now() - interval '24 hours') priced_24h,
  count(*) priced_7d, count(*) filter (where solo.print_id is not null) only_source_7d
from obp left join solo using (print_id) group by 1 order by 1;

-- market_index_latest
with d as (select max(snapshot_date) latest_day from market_index_snapshots),
pr as (select p.id print_id from card_prints p where p.is_active and p.verification_status = 'verified')
select d.latest_day snapshot_date, count(pr.print_id) verified_prints,
  count(s.id) snapshot_rows, count(s.id) filter (where s.index_value_jpy is not null) with_index_value,
  count(s.id) filter (where s.source_count >= 2) two_plus_index_sources,
  string_agg(distinct s.coverage_status, ',') coverage_statuses
from d cross join pr
left join market_index_snapshots s on s.card_print_id = pr.print_id and s.snapshot_date = d.latest_day
group by 1;
