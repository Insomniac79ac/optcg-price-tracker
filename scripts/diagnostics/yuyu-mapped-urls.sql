-- Yuyu-Tei mapped URLs per print: for the CP price checker to compare a print's Yuyu-Tei headline
-- with its source page. Read-only. Population: Yuyu-Tei mappings that price a print today
-- (active, current, approved, card_print_id set), one row per mapping, ordered by mapping id.
-- The runner returns at most 500 rows per statement, so the list is split into pages of 500
-- (urls_01 .. urls_12, up to 6,000 mappings); totals.mappings says how many exist, so a reader
-- can tell when the pages do not cover them all. price_at and checked_at are the raw (ungraded)
-- refresh state of that mapping, or null when it has none.

-- totals
with ys as (select id from sources where name = 'yuyutei')
select count(*) mappings, count(distinct m.card_print_id) prints, 12 * 500 page_capacity
from source_card_mappings m
where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null
  and m.review_status = 'approved' and m.card_print_id is not null;

-- urls_01
with ys as (select id from sources where name = 'yuyutei'),
ym as (
  select m.id mapping_id, m.card_print_id print_id, m.source_url,
    row_number() over (order by m.id) rn
  from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved' and m.card_print_id is not null),
st as (
  select w.source_card_mapping_id mapping_id, string_agg(distinct ps.availability, ',') availability,
    max(ps.last_valid_price_observed_at) price_at, max(ps.last_successfully_checked_at) checked_at
  from freshness_work w join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where w.kind = 'refresh' and w.source_card_mapping_id in (select mapping_id from ym where rn between 1 and 500)
  group by 1)
select ym.print_id, c.card_code, p.official_asset_variant variant, rp.official_code release_code,
  ym.mapping_id, ym.source_url, st.availability, st.price_at, st.checked_at
from ym join card_prints p on p.id = ym.print_id join canonical_cards c on c.id = p.canonical_card_id
left join release_products rp on rp.id = p.release_product_id
left join st on st.mapping_id = ym.mapping_id
where ym.rn between 1 and 500
order by ym.rn;

-- urls_02
with ys as (select id from sources where name = 'yuyutei'),
ym as (
  select m.id mapping_id, m.card_print_id print_id, m.source_url,
    row_number() over (order by m.id) rn
  from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved' and m.card_print_id is not null),
st as (
  select w.source_card_mapping_id mapping_id, string_agg(distinct ps.availability, ',') availability,
    max(ps.last_valid_price_observed_at) price_at, max(ps.last_successfully_checked_at) checked_at
  from freshness_work w join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where w.kind = 'refresh' and w.source_card_mapping_id in (select mapping_id from ym where rn between 501 and 1000)
  group by 1)
select ym.print_id, c.card_code, p.official_asset_variant variant, rp.official_code release_code,
  ym.mapping_id, ym.source_url, st.availability, st.price_at, st.checked_at
from ym join card_prints p on p.id = ym.print_id join canonical_cards c on c.id = p.canonical_card_id
left join release_products rp on rp.id = p.release_product_id
left join st on st.mapping_id = ym.mapping_id
where ym.rn between 501 and 1000
order by ym.rn;

-- urls_03
with ys as (select id from sources where name = 'yuyutei'),
ym as (
  select m.id mapping_id, m.card_print_id print_id, m.source_url,
    row_number() over (order by m.id) rn
  from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved' and m.card_print_id is not null),
st as (
  select w.source_card_mapping_id mapping_id, string_agg(distinct ps.availability, ',') availability,
    max(ps.last_valid_price_observed_at) price_at, max(ps.last_successfully_checked_at) checked_at
  from freshness_work w join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where w.kind = 'refresh' and w.source_card_mapping_id in (select mapping_id from ym where rn between 1001 and 1500)
  group by 1)
select ym.print_id, c.card_code, p.official_asset_variant variant, rp.official_code release_code,
  ym.mapping_id, ym.source_url, st.availability, st.price_at, st.checked_at
from ym join card_prints p on p.id = ym.print_id join canonical_cards c on c.id = p.canonical_card_id
left join release_products rp on rp.id = p.release_product_id
left join st on st.mapping_id = ym.mapping_id
where ym.rn between 1001 and 1500
order by ym.rn;

-- urls_04
with ys as (select id from sources where name = 'yuyutei'),
ym as (
  select m.id mapping_id, m.card_print_id print_id, m.source_url,
    row_number() over (order by m.id) rn
  from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved' and m.card_print_id is not null),
st as (
  select w.source_card_mapping_id mapping_id, string_agg(distinct ps.availability, ',') availability,
    max(ps.last_valid_price_observed_at) price_at, max(ps.last_successfully_checked_at) checked_at
  from freshness_work w join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where w.kind = 'refresh' and w.source_card_mapping_id in (select mapping_id from ym where rn between 1501 and 2000)
  group by 1)
select ym.print_id, c.card_code, p.official_asset_variant variant, rp.official_code release_code,
  ym.mapping_id, ym.source_url, st.availability, st.price_at, st.checked_at
from ym join card_prints p on p.id = ym.print_id join canonical_cards c on c.id = p.canonical_card_id
left join release_products rp on rp.id = p.release_product_id
left join st on st.mapping_id = ym.mapping_id
where ym.rn between 1501 and 2000
order by ym.rn;

-- urls_05
with ys as (select id from sources where name = 'yuyutei'),
ym as (
  select m.id mapping_id, m.card_print_id print_id, m.source_url,
    row_number() over (order by m.id) rn
  from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved' and m.card_print_id is not null),
st as (
  select w.source_card_mapping_id mapping_id, string_agg(distinct ps.availability, ',') availability,
    max(ps.last_valid_price_observed_at) price_at, max(ps.last_successfully_checked_at) checked_at
  from freshness_work w join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where w.kind = 'refresh' and w.source_card_mapping_id in (select mapping_id from ym where rn between 2001 and 2500)
  group by 1)
select ym.print_id, c.card_code, p.official_asset_variant variant, rp.official_code release_code,
  ym.mapping_id, ym.source_url, st.availability, st.price_at, st.checked_at
from ym join card_prints p on p.id = ym.print_id join canonical_cards c on c.id = p.canonical_card_id
left join release_products rp on rp.id = p.release_product_id
left join st on st.mapping_id = ym.mapping_id
where ym.rn between 2001 and 2500
order by ym.rn;

-- urls_06
with ys as (select id from sources where name = 'yuyutei'),
ym as (
  select m.id mapping_id, m.card_print_id print_id, m.source_url,
    row_number() over (order by m.id) rn
  from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved' and m.card_print_id is not null),
st as (
  select w.source_card_mapping_id mapping_id, string_agg(distinct ps.availability, ',') availability,
    max(ps.last_valid_price_observed_at) price_at, max(ps.last_successfully_checked_at) checked_at
  from freshness_work w join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where w.kind = 'refresh' and w.source_card_mapping_id in (select mapping_id from ym where rn between 2501 and 3000)
  group by 1)
select ym.print_id, c.card_code, p.official_asset_variant variant, rp.official_code release_code,
  ym.mapping_id, ym.source_url, st.availability, st.price_at, st.checked_at
from ym join card_prints p on p.id = ym.print_id join canonical_cards c on c.id = p.canonical_card_id
left join release_products rp on rp.id = p.release_product_id
left join st on st.mapping_id = ym.mapping_id
where ym.rn between 2501 and 3000
order by ym.rn;

-- urls_07
with ys as (select id from sources where name = 'yuyutei'),
ym as (
  select m.id mapping_id, m.card_print_id print_id, m.source_url,
    row_number() over (order by m.id) rn
  from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved' and m.card_print_id is not null),
st as (
  select w.source_card_mapping_id mapping_id, string_agg(distinct ps.availability, ',') availability,
    max(ps.last_valid_price_observed_at) price_at, max(ps.last_successfully_checked_at) checked_at
  from freshness_work w join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where w.kind = 'refresh' and w.source_card_mapping_id in (select mapping_id from ym where rn between 3001 and 3500)
  group by 1)
select ym.print_id, c.card_code, p.official_asset_variant variant, rp.official_code release_code,
  ym.mapping_id, ym.source_url, st.availability, st.price_at, st.checked_at
from ym join card_prints p on p.id = ym.print_id join canonical_cards c on c.id = p.canonical_card_id
left join release_products rp on rp.id = p.release_product_id
left join st on st.mapping_id = ym.mapping_id
where ym.rn between 3001 and 3500
order by ym.rn;

-- urls_08
with ys as (select id from sources where name = 'yuyutei'),
ym as (
  select m.id mapping_id, m.card_print_id print_id, m.source_url,
    row_number() over (order by m.id) rn
  from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved' and m.card_print_id is not null),
st as (
  select w.source_card_mapping_id mapping_id, string_agg(distinct ps.availability, ',') availability,
    max(ps.last_valid_price_observed_at) price_at, max(ps.last_successfully_checked_at) checked_at
  from freshness_work w join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where w.kind = 'refresh' and w.source_card_mapping_id in (select mapping_id from ym where rn between 3501 and 4000)
  group by 1)
select ym.print_id, c.card_code, p.official_asset_variant variant, rp.official_code release_code,
  ym.mapping_id, ym.source_url, st.availability, st.price_at, st.checked_at
from ym join card_prints p on p.id = ym.print_id join canonical_cards c on c.id = p.canonical_card_id
left join release_products rp on rp.id = p.release_product_id
left join st on st.mapping_id = ym.mapping_id
where ym.rn between 3501 and 4000
order by ym.rn;

-- urls_09
with ys as (select id from sources where name = 'yuyutei'),
ym as (
  select m.id mapping_id, m.card_print_id print_id, m.source_url,
    row_number() over (order by m.id) rn
  from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved' and m.card_print_id is not null),
st as (
  select w.source_card_mapping_id mapping_id, string_agg(distinct ps.availability, ',') availability,
    max(ps.last_valid_price_observed_at) price_at, max(ps.last_successfully_checked_at) checked_at
  from freshness_work w join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where w.kind = 'refresh' and w.source_card_mapping_id in (select mapping_id from ym where rn between 4001 and 4500)
  group by 1)
select ym.print_id, c.card_code, p.official_asset_variant variant, rp.official_code release_code,
  ym.mapping_id, ym.source_url, st.availability, st.price_at, st.checked_at
from ym join card_prints p on p.id = ym.print_id join canonical_cards c on c.id = p.canonical_card_id
left join release_products rp on rp.id = p.release_product_id
left join st on st.mapping_id = ym.mapping_id
where ym.rn between 4001 and 4500
order by ym.rn;

-- urls_10
with ys as (select id from sources where name = 'yuyutei'),
ym as (
  select m.id mapping_id, m.card_print_id print_id, m.source_url,
    row_number() over (order by m.id) rn
  from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved' and m.card_print_id is not null),
st as (
  select w.source_card_mapping_id mapping_id, string_agg(distinct ps.availability, ',') availability,
    max(ps.last_valid_price_observed_at) price_at, max(ps.last_successfully_checked_at) checked_at
  from freshness_work w join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where w.kind = 'refresh' and w.source_card_mapping_id in (select mapping_id from ym where rn between 4501 and 5000)
  group by 1)
select ym.print_id, c.card_code, p.official_asset_variant variant, rp.official_code release_code,
  ym.mapping_id, ym.source_url, st.availability, st.price_at, st.checked_at
from ym join card_prints p on p.id = ym.print_id join canonical_cards c on c.id = p.canonical_card_id
left join release_products rp on rp.id = p.release_product_id
left join st on st.mapping_id = ym.mapping_id
where ym.rn between 4501 and 5000
order by ym.rn;

-- urls_11
with ys as (select id from sources where name = 'yuyutei'),
ym as (
  select m.id mapping_id, m.card_print_id print_id, m.source_url,
    row_number() over (order by m.id) rn
  from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved' and m.card_print_id is not null),
st as (
  select w.source_card_mapping_id mapping_id, string_agg(distinct ps.availability, ',') availability,
    max(ps.last_valid_price_observed_at) price_at, max(ps.last_successfully_checked_at) checked_at
  from freshness_work w join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where w.kind = 'refresh' and w.source_card_mapping_id in (select mapping_id from ym where rn between 5001 and 5500)
  group by 1)
select ym.print_id, c.card_code, p.official_asset_variant variant, rp.official_code release_code,
  ym.mapping_id, ym.source_url, st.availability, st.price_at, st.checked_at
from ym join card_prints p on p.id = ym.print_id join canonical_cards c on c.id = p.canonical_card_id
left join release_products rp on rp.id = p.release_product_id
left join st on st.mapping_id = ym.mapping_id
where ym.rn between 5001 and 5500
order by ym.rn;

-- urls_12
with ys as (select id from sources where name = 'yuyutei'),
ym as (
  select m.id mapping_id, m.card_print_id print_id, m.source_url,
    row_number() over (order by m.id) rn
  from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved' and m.card_print_id is not null),
st as (
  select w.source_card_mapping_id mapping_id, string_agg(distinct ps.availability, ',') availability,
    max(ps.last_valid_price_observed_at) price_at, max(ps.last_successfully_checked_at) checked_at
  from freshness_work w join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where w.kind = 'refresh' and w.source_card_mapping_id in (select mapping_id from ym where rn between 5501 and 6000)
  group by 1)
select ym.print_id, c.card_code, p.official_asset_variant variant, rp.official_code release_code,
  ym.mapping_id, ym.source_url, st.availability, st.price_at, st.checked_at
from ym join card_prints p on p.id = ym.print_id join canonical_cards c on c.id = p.canonical_card_id
left join release_products rp on rp.id = p.release_product_id
left join st on st.mapping_id = ym.mapping_id
where ym.rn between 5501 and 6000
order by ym.rn;
