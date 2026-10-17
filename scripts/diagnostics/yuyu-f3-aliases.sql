-- F3 (owner decision 2026-10-17): Yuyu-Tei categories (set slugs) that resolve to no release
-- product, with sample listings, and where the PRB reprint prints' codes are listed. Read-only;
-- writes no alias. A slug "resolves" when it equals a release product's official code after
-- removing '-', '_' and spaces (source_mapping_proposals._norm).

-- categories
with ys as (select id from sources where name = 'yuyutei'),
rel as (select upper(replace(replace(replace(official_code, '-', ''), '_', ''), ' ', '')) release_n from release_products where official_code is not null),
pg as (
  select distinct on (g.source_candidate_id) g.source_candidate_id cand_id, g.resolution_status,
    g.resolution_reasons_json::jsonb ->> 0 first_reason
  from source_mapping_proposal_groups g
  where g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null
  order by g.source_candidate_id, g.id desc),
yc as (
  select y.id cand_id, y.set_slug, upper(replace(replace(replace(y.set_slug, '-', ''), '_', ''), ' ', '')) slug_n, y.detected_card_code code, y.detected_rarity, y.name_jp,
    substring(y.name_jp from '[(（]([^()（）]*)[)）]') annotation, pg.resolution_status, pg.first_reason
  from yuyutei_candidates y left join pg on pg.cand_id = y.id)
select yc.set_slug, count(*) listings, count(*) filter (where yc.resolution_status = 'release_unresolved') release_unresolved,
  count(*) filter (where yc.resolution_status = 'unresolved_identity') identity_unresolved,
  string_agg(distinct left(yc.code, 4), ',') code_prefixes
from yc where not exists (select 1 from rel where rel.release_n = yc.slug_n)
group by 1 order by 2 desc;

-- category_samples
with ys as (select id from sources where name = 'yuyutei'),
rel as (select upper(replace(replace(replace(official_code, '-', ''), '_', ''), ' ', '')) release_n from release_products where official_code is not null),
pg as (
  select distinct on (g.source_candidate_id) g.source_candidate_id cand_id, g.resolution_status,
    g.resolution_reasons_json::jsonb ->> 0 first_reason
  from source_mapping_proposal_groups g
  where g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null
  order by g.source_candidate_id, g.id desc),
yc as (
  select y.id cand_id, y.set_slug, upper(replace(replace(replace(y.set_slug, '-', ''), '_', ''), ' ', '')) slug_n, y.detected_card_code code, y.detected_rarity, y.name_jp,
    substring(y.name_jp from '[(（]([^()（）]*)[)）]') annotation, pg.resolution_status, pg.first_reason
  from yuyutei_candidates y left join pg on pg.cand_id = y.id)
select set_slug, code, detected_rarity, annotation, left(name_jp, 24) listing_title from (
  select yc.*, row_number() over (partition by yc.set_slug order by md5(yc.cand_id::text || ':d9-f3')) rn
  from yc where not exists (select 1 from rel where rel.release_n = yc.slug_n)) x
where rn <= 5 order by set_slug, rn;

-- prb_reprint_listings
with ys as (select id from sources where name = 'yuyutei'),
rel as (select upper(replace(replace(replace(official_code, '-', ''), '_', ''), ' ', '')) release_n from release_products where official_code is not null),
pg as (
  select distinct on (g.source_candidate_id) g.source_candidate_id cand_id, g.resolution_status,
    g.resolution_reasons_json::jsonb ->> 0 first_reason
  from source_mapping_proposal_groups g
  where g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null
  order by g.source_candidate_id, g.id desc),
yc as (
  select y.id cand_id, y.set_slug, upper(replace(replace(replace(y.set_slug, '-', ''), '_', ''), ' ', '')) slug_n, y.detected_card_code code, y.detected_rarity, y.name_jp,
    substring(y.name_jp from '[(（]([^()（）]*)[)）]') annotation, pg.resolution_status, pg.first_reason
  from yuyutei_candidates y left join pg on pg.cand_id = y.id)
, prb as (
  select p.id print_id, c.card_code, upper(replace(replace(replace(c.card_code, '-', ''), '_', ''), ' ', '')) code_n, rp.official_code release_code, p.official_asset_variant variant
  from card_prints p join canonical_cards c on c.id = p.canonical_card_id join release_products rp on rp.id = p.release_product_id
  where p.is_active and p.verification_status = 'verified' and rp.official_code like 'PRB%' and p.official_asset_variant like 'r%'
    and not exists (select 1 from source_card_mappings m where m.card_print_id = p.id and m.source_id = (select id from ys)
      and m.is_active and m.superseded_at is null and m.review_status = 'approved'))
select prb.release_code, count(distinct prb.print_id) reprint_prints,
  count(distinct prb.print_id) filter (where yc.slug_n = upper(replace(replace(replace(prb.release_code, '-', ''), '_', ''), ' ', ''))) with_listing_on_prb_shelf,
  count(distinct prb.print_id) filter (where yc.annotation ilike '%prb%' or yc.name_jp like '%プレミアムブースター%') with_prb_label_elsewhere,
  count(distinct prb.print_id) filter (where yc.cand_id is null) no_listing_for_code
from prb left join yc on upper(replace(replace(replace(yc.code, '-', ''), '_', ''), ' ', '')) = prb.code_n group by 1 order by 1;

-- prb_listing_samples
with ys as (select id from sources where name = 'yuyutei'),
rel as (select upper(replace(replace(replace(official_code, '-', ''), '_', ''), ' ', '')) release_n from release_products where official_code is not null),
pg as (
  select distinct on (g.source_candidate_id) g.source_candidate_id cand_id, g.resolution_status,
    g.resolution_reasons_json::jsonb ->> 0 first_reason
  from source_mapping_proposal_groups g
  where g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null
  order by g.source_candidate_id, g.id desc),
yc as (
  select y.id cand_id, y.set_slug, upper(replace(replace(replace(y.set_slug, '-', ''), '_', ''), ' ', '')) slug_n, y.detected_card_code code, y.detected_rarity, y.name_jp,
    substring(y.name_jp from '[(（]([^()（）]*)[)）]') annotation, pg.resolution_status, pg.first_reason
  from yuyutei_candidates y left join pg on pg.cand_id = y.id)
, prb as (
  select distinct c.card_code, upper(replace(replace(replace(c.card_code, '-', ''), '_', ''), ' ', '')) code_n, rp.official_code release_code
  from card_prints p join canonical_cards c on c.id = p.canonical_card_id join release_products rp on rp.id = p.release_product_id
  where p.is_active and p.verification_status = 'verified' and rp.official_code like 'PRB%' and p.official_asset_variant like 'r%')
select prb.release_code, prb.card_code, yc.set_slug, yc.detected_rarity, yc.annotation, left(yc.name_jp, 24) listing_title,
  yc.resolution_status from prb join yc on upper(replace(replace(replace(yc.code, '-', ''), '_', ''), ' ', '')) = prb.code_n
order by md5(prb.card_code || yc.set_slug || ':d9-f3'), yc.set_slug limit 30;
