-- SNKRDUNK approve-snkr-batch outcome and new discovery listings, read-only (owner 2026-11-03, "ok").
-- batch: the mappings approved by ops-write:approve-snkr-batch:41444936669 (2026-11-02, 208 groups),
-- found through their proposal group's candidate listing, counted by refresh work state, last
-- outcome, raw availability and refusal reason (digits folded to N). refused: each blocked refresh
-- item of that batch with its print, listing and stored candidate title. new_listings: SNKRDUNK
-- candidates created since 2026-11-02 10:00Z (the seed-priority planner) with their stored set code,
-- rarity token, title and current proposal (status and last reason). Kept compact for the summary.
-- batch
with ss as (select id from sources where name = 'snkrdunk'),
g as (
  select g.source_candidate_id cid from source_mapping_proposal_groups g
  where g.source_candidate_type = 'snkrdunk_candidate'
    and g.reviewed_by = 'ops-write:approve-snkr-batch:41444936669'),
bm as (
  select distinct m.id mapping_id from g
  join snkrdunk_candidates c on c.id = g.cid
  join source_card_mappings m on m.source_id = (select id from ss)
    and m.canonical_source_listing_identity
      = substring(c.source_url from '^https://snkrdunk\.com/(?:apparels|en/trading-cards)/([0-9]+)')
    and m.is_active and m.superseded_at is null),
wk as (
  select bm.mapping_id, w.state, w.last_outcome,
    left(regexp_replace(coalesce(w.last_failure, ''), '[0-9]+', 'N', 'g'), 40) reason,
    (select string_agg(distinct ps.availability, ',') from freshness_price_states ps
      where ps.work_id = w.id and ps.price_category = 'raw') availability
  from bm left join freshness_work w on w.source_card_mapping_id = bm.mapping_id and w.kind = 'refresh')
select (select count(*) from g) groups, (select count(*) from bm) mappings,
  state, last_outcome, availability, reason, count(*) n
from wk group by state, last_outcome, availability, reason order by n desc;

-- refused
with ss as (select id from sources where name = 'snkrdunk'),
g as (
  select g.source_candidate_id cid from source_mapping_proposal_groups g
  where g.source_candidate_type = 'snkrdunk_candidate'
    and g.reviewed_by = 'ops-write:approve-snkr-batch:41444936669')
select w.id work_id, m.id mapping_id, cc.card_code code, p.official_asset_variant variant,
  rp.official_code release, m.canonical_source_listing_identity listing, left(c.title, 50) title,
  left(regexp_replace(coalesce(w.last_failure, ''), '[0-9]+', 'N', 'g'), 30) reason
from g
join snkrdunk_candidates c on c.id = g.cid
join source_card_mappings m on m.source_id = (select id from ss)
  and m.canonical_source_listing_identity
    = substring(c.source_url from '^https://snkrdunk\.com/(?:apparels|en/trading-cards)/([0-9]+)')
  and m.is_active and m.superseded_at is null
join freshness_work w on w.source_card_mapping_id = m.id and w.kind = 'refresh' and w.state = 'blocked'
left join card_prints p on p.id = m.card_print_id
left join canonical_cards cc on cc.id = p.canonical_card_id
left join release_products rp on rp.id = p.release_product_id
order by reason, code, w.id;

-- new_listings
select c.id cid, substring(c.source_url from '([0-9]+)$') listing, c.detected_card_code code,
  c.detected_set_code set_code, c.detected_rarity rarity, left(c.title, 60) title,
  g.resolution_status proposal,
  g.resolution_reasons_json ->> (json_array_length(g.resolution_reasons_json) - 1) last_reason
from snkrdunk_candidates c
left join lateral (
  select g.resolution_status, g.resolution_reasons_json from source_mapping_proposal_groups g
  where g.source_candidate_type = 'snkrdunk_candidate' and g.source_candidate_id = c.id
    and g.superseded_at is null
  order by g.id desc limit 1) g on true
where c.created_at >= timestamptz '2026-11-02 10:00:00+00'
order by c.id;
