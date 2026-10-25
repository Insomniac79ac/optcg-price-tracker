-- Catalogue coverage by product (owner request 2026-10-25: promos, Premium Card Collections,
-- tins, Flagship/judge cards and DON!! are missing from the main list). Read-only. Per release
-- product (one row per Bandai Card List series the catalogue imported): active and verified
-- prints, prints with an active approved price-source mapping per source. Then prints with no
-- product by card-code prefix, cards and prints by card type (DON!! included), prints by language.

-- products
with m as (
  select sm.card_print_id, s.name source
  from source_card_mappings sm join sources s on s.id = sm.source_id
  where sm.is_active and sm.superseded_at is null and sm.review_status = 'approved' and sm.card_print_id is not null
  group by sm.card_print_id, s.name)
select rp.source_catalogue catalogue, rp.source_series_id series_id, rp.official_code code, rp.display_name name,
  rp.verification_status status, rp.released_on,
  count(distinct p.id) filter (where p.is_active) prints,
  count(distinct p.id) filter (where p.is_active and p.verification_status = 'verified') verified,
  count(distinct p.id) filter (where p.is_active and exists (select 1 from m where m.card_print_id = p.id and m.source = 'yuyutei')) yuyu_mapped,
  count(distinct p.id) filter (where p.is_active and exists (select 1 from m where m.card_print_id = p.id and m.source = 'snkrdunk')) snkr_mapped
from release_products rp left join card_prints p on p.release_product_id = rp.id
group by rp.id
order by rp.source_catalogue, rp.official_code nulls last, rp.display_name;

-- no_product_by_prefix
select split_part(c.card_code, '-', 1) prefix, count(*) prints,
  count(*) filter (where p.verification_status = 'verified') verified, min(c.card_code) example
from card_prints p join canonical_cards c on c.id = p.canonical_card_id
where p.is_active and p.release_product_id is null
group by 1 order by 2 desc;

-- by_card_type
select c.card_type, count(distinct c.id) cards, count(p.id) filter (where p.is_active) prints
from canonical_cards c left join card_prints p on p.canonical_card_id = c.id
group by 1 order by 2 desc;

-- by_language
select p.language, count(*) prints from card_prints p where p.is_active group by 1 order by 2 desc;
