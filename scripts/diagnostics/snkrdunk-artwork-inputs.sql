-- SNKRDUNK artwork refusals of the approve-snkr-batch mappings, read-only (owner 2026-11-03: the
-- owner identified three refused parallels as correct and asked why the collector refuses them).
-- The collector compares the listing photo with card_prints.image_url of the MAPPED print
-- (snkrdunk_collector/collect.py). Per artwork-refused mapping: the mapped print, its image file
-- name, every active sibling of the same card code and release with its image file name, and whether
-- the mapped print's image URL equals the base print's.
-- artwork_inputs
-- Owner 2026-11-03: for each artwork-refused batch mapping, the official image the collector
-- compares against (card_prints.image_url of the mapped print, file name only) and the image of
-- every active sibling print of that card code in the same release, so a parallel mapped to a print
-- carrying base artwork (or the reverse) is visible. same_as_base: mapped image equals the base's.
with ss as (select id from sources where name = 'snkrdunk'),
g as (
  select g.source_candidate_id cid from source_mapping_proposal_groups g
  where g.source_candidate_type = 'snkrdunk_candidate'
    and g.reviewed_by = 'ops-write:approve-snkr-batch:41444936669'),
bm as (
  select distinct m.id mapping_id, m.card_print_id, w.last_failure
  from g join snkrdunk_candidates c on c.id = g.cid
  join source_card_mappings m on m.source_id = (select id from ss)
    and m.canonical_source_listing_identity
      = substring(c.source_url from '^https://snkrdunk\.com/(?:apparels|en/trading-cards)/([0-9]+)')
    and m.is_active and m.superseded_at is null
  join freshness_work w on w.source_card_mapping_id = m.id and w.kind = 'refresh' and w.state = 'blocked'
  where w.last_failure like 'artwork_not_confirmed_match%')
select bm.mapping_id, p.id print_id, cc.card_code code, p.official_asset_variant variant,
  substring(p.image_url from '[^/]+$') image,
  (select string_agg(s.official_asset_variant || '=' || coalesce(substring(s.image_url from '[^/]+$'), '-'), ' '
     order by s.official_asset_variant)
   from card_prints s where s.canonical_card_id = p.canonical_card_id and s.release_product_id = p.release_product_id
     and s.is_active and s.id <> p.id) siblings,
  p.image_url = (select b.image_url from card_prints b where b.canonical_card_id = p.canonical_card_id
     and b.release_product_id = p.release_product_id and b.official_asset_variant = 'base' and b.is_active
     limit 1) same_as_base
from bm join card_prints p on p.id = bm.card_print_id
join canonical_cards cc on cc.id = p.canonical_card_id
order by cc.card_code, p.official_asset_variant;
