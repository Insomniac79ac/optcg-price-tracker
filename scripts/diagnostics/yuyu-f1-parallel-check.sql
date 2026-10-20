-- F1 multi-parallel check (owner question 2026-10-20 06:41Z, batch-2 sample row 8 OP14-118).
-- Read-only. The F1 rule (unique_listing_kind_resolves_one_release_sibling) counts only active
-- verified prints and stored Yuyu-Tei listings of the SAME release. This file looks wider: every
-- print of the card code in any release or status, and every stored Yuyu listing of the code in
-- any category, to find a second parallel (manga, super or reprint parallel) the rule could miss.
-- Kinds mirror source_mapping_proposals.yuyu_listing_kind and print_listing_kind; a listing or
-- print the rule cannot type is 'unknown' (special = SPカード/SP P/TR print).
-- Codes and slugs compare after removing '-', '_' and spaces, as _norm does.

-- detail_prints
select p.id print_id, c.card_code code, p.language, coalesce(rp.official_code, p.release_product_code) release_code,
  p.official_rarity rarity, p.official_asset_variant variant, p.treatment, p.is_active active, p.verification_status,
  case when p.treatment ~* '(foil|フォイル)' then 'foil'
    when p.official_rarity in ('SPカード', 'SP P', 'TR') then 'special'
    when p.official_asset_variant ~ '^(base|r[1-9][0-9]*)$' then 'plain'
    when p.official_asset_variant ~ '^p[1-9][0-9]*$' then 'parallel' else 'unknown' end kind,
  exists (select 1 from source_card_mappings m join sources s on s.id = m.source_id and s.name = 'yuyutei'
    where m.card_print_id = p.id and m.is_active and m.superseded_at is null and m.review_status = 'approved') yuyu_mapped
from card_prints p join canonical_cards c on c.id = p.canonical_card_id
left join release_products rp on rp.id = p.release_product_id
where upper(replace(replace(replace(c.card_code, '-', ''), '_', ''), ' ', '')) = 'OP14118'
order by p.id;

-- detail_listings
select y.id cand_id, lower(y.set_slug) || ':' || y.product_id listing, y.name_jp title, y.detected_rarity rarity,
  y.price_jpy, y.availability, y.updated_at,
  case when y.name_jp ~ '(ラメフォイル|海賊旗フォイル)' then 'foil'
    when trim(y.detected_rarity) ~ '^P-(C|UC|R|SR|SEC|L)$' then 'parallel'
    when trim(y.detected_rarity) in ('C', 'UC', 'R', 'SR', 'SEC', 'L') then
      case when y.name_jp like '%パラレル%' then 'parallel' else 'plain' end
    else 'unknown' end kind,
  (select g.resolution_status || '/' || g.review_status from source_mapping_proposal_groups g
    where g.source_candidate_type = 'yuyutei_candidate' and g.source_candidate_id = y.id and g.superseded_at is null
    order by g.id desc limit 1) proposal
from yuyutei_candidates y
where upper(replace(replace(replace(y.detected_card_code, '-', ''), '_', ''), ' ', '')) = 'OP14118'
order by y.id;

-- f1_shapes
with pk as (
  select p.id print_id, upper(replace(replace(replace(c.card_code, '-', ''), '_', ''), ' ', '')) code_n, p.is_active,
    p.verification_status,
    case when p.treatment ~* '(foil|フォイル)' then 'foil'
      when p.official_rarity in ('SPカード', 'SP P', 'TR') then 'special'
      when p.official_asset_variant ~ '^(base|r[1-9][0-9]*)$' then 'plain'
      when p.official_asset_variant ~ '^p[1-9][0-9]*$' then 'parallel' else 'unknown' end kind
  from card_prints p join canonical_cards c on c.id = p.canonical_card_id),
lk as (
  select upper(replace(replace(replace(y.detected_card_code, '-', ''), '_', ''), ' ', '')) code_n,
    case when y.name_jp ~ '(ラメフォイル|海賊旗フォイル)' then 'foil'
      when trim(y.detected_rarity) ~ '^P-(C|UC|R|SR|SEC|L)$' then 'parallel'
      when trim(y.detected_rarity) in ('C', 'UC', 'R', 'SR', 'SEC', 'L') then
        case when y.name_jp like '%パラレル%' then 'parallel' else 'plain' end
      else 'unknown' end kind
  from yuyutei_candidates y where y.detected_card_code is not null),
f1 as (
  select g.id group_id, pk.code_n, pk.kind
  from source_mapping_proposal_groups g
  join source_mapping_proposal_alternatives a on a.proposal_group_id = g.id and a.recommended
  join pk on pk.print_id = a.card_print_id
  where g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null and g.review_status = 'pending'
    and g.resolution_status = 'exact'
    and g.resolution_reasons_json::jsonb @> '["unique_listing_kind_resolves_one_release_sibling"]'::jsonb),
shape as (
  select f1.group_id, f1.code_n, f1.kind,
    (select count(*) from pk where pk.code_n = f1.code_n and pk.kind = f1.kind) same_kind_prints_any,
    (select count(*) from pk where pk.code_n = f1.code_n and pk.kind = f1.kind and pk.is_active
      and pk.verification_status = 'verified') same_kind_prints_verified,
    (select count(*) from pk where pk.code_n = f1.code_n and pk.kind in ('unknown', 'special')) untyped_prints,
    (select count(*) from lk where lk.code_n = f1.code_n and lk.kind = f1.kind) same_kind_listings_any,
    (select count(*) from lk where lk.code_n = f1.code_n and lk.kind = 'unknown') untyped_listings
  from f1)
select group_id, code_n, kind, same_kind_prints_any p_any, same_kind_prints_verified p_ver, untyped_prints p_unk,
  same_kind_listings_any l_any, untyped_listings l_unk
from shape
where same_kind_prints_any > 1 or same_kind_listings_any > 1 or untyped_prints > 0 or untyped_listings > 0
order by kind, code_n, group_id;

-- f1_shape_counts
with pk as (
  select p.id print_id, upper(replace(replace(replace(c.card_code, '-', ''), '_', ''), ' ', '')) code_n,
    case when p.treatment ~* '(foil|フォイル)' then 'foil'
      when p.official_rarity in ('SPカード', 'SP P', 'TR') then 'special'
      when p.official_asset_variant ~ '^(base|r[1-9][0-9]*)$' then 'plain'
      when p.official_asset_variant ~ '^p[1-9][0-9]*$' then 'parallel' else 'unknown' end kind
  from card_prints p join canonical_cards c on c.id = p.canonical_card_id),
lk as (
  select upper(replace(replace(replace(y.detected_card_code, '-', ''), '_', ''), ' ', '')) code_n,
    case when y.name_jp ~ '(ラメフォイル|海賊旗フォイル)' then 'foil'
      when trim(y.detected_rarity) ~ '^P-(C|UC|R|SR|SEC|L)$' then 'parallel'
      when trim(y.detected_rarity) in ('C', 'UC', 'R', 'SR', 'SEC', 'L') then
        case when y.name_jp like '%パラレル%' then 'parallel' else 'plain' end
      else 'unknown' end kind
  from yuyutei_candidates y where y.detected_card_code is not null),
f1 as (
  select g.id group_id, pk.code_n, pk.kind
  from source_mapping_proposal_groups g
  join source_mapping_proposal_alternatives a on a.proposal_group_id = g.id and a.recommended
  join pk on pk.print_id = a.card_print_id
  where g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null and g.review_status = 'pending'
    and g.resolution_status = 'exact'
    and g.resolution_reasons_json::jsonb @> '["unique_listing_kind_resolves_one_release_sibling"]'::jsonb)
select f1.kind, count(*) f1_groups,
  count(*) filter (where (select count(*) from pk where pk.code_n = f1.code_n and pk.kind = f1.kind) > 1) multi_print_any_release,
  count(*) filter (where (select count(*) from lk where lk.code_n = f1.code_n and lk.kind = f1.kind) > 1) multi_listing_any_category,
  count(*) filter (where (select count(*) from pk where pk.code_n = f1.code_n and pk.kind in ('unknown', 'special')) > 0) untyped_print,
  count(*) filter (where (select count(*) from lk where lk.code_n = f1.code_n and lk.kind = 'unknown') > 0) untyped_listing
from f1 group by 1 order by 1;
