-- SNKRDUNK approve-snkr-batch outcomes and discovery proposals, read-only (owner 2026-11-03, "ok",
-- 2026-11-05, "yes, build the diagnostic PR", and 2026-11-09 Mission 4 item 3).
-- batch and refused take every approve-snkr-batch apply. f1_approve.batch_reviewed_by writes
-- ops-write:approve-snkr-batch:<GITHUB_RUN_ID or local>, and the decision service stores that
-- lowercased. The predicate is f1_approve.batch_reviewed_by_pattern("snkrdunk"): anchored, so
-- approve-f1-batch, a longer runbook name, and a manual email do not match. The run column is
-- that suffix. The first two applies (41444936669, 41787151033) match it; later applies do too.
-- batch: each run's mappings, found through their proposal group's candidate listing, counted by
-- refresh work state, last outcome, raw availability and refusal reason (digits folded to N).
-- refused: each blocked refresh item of either run with its print and reason (listings and photos
-- come from snkr-refused-photos). proposals: SNKRDUNK candidates created since 2026-11-02 10:00Z
-- (the seed-priority planner), split at 2026-11-03 13:24Z (discovery creates proposals from then),
-- counted by set code present, listing already mapped and current proposal status (none = no
-- current proposal group). Kept compact for the summary.
-- batch
with ss as (select id from sources where name = 'snkrdunk'),
g as (
  select substring(g.reviewed_by from '^ops-write:approve-snkr-batch:([0-9]+|local)$') run,
    g.source_candidate_id cid
  from source_mapping_proposal_groups g
  where g.source_candidate_type = 'snkrdunk_candidate'
    and g.reviewed_by ~ '^ops-write:approve-snkr-batch:([0-9]+|local)$'),
bm as (
  select distinct g.run, m.id mapping_id from g
  join snkrdunk_candidates c on c.id = g.cid
  join source_card_mappings m on m.source_id = (select id from ss)
    and m.canonical_source_listing_identity
      = substring(c.source_url from '^https://snkrdunk\.com/(?:apparels|en/trading-cards)/([0-9]+)')
    and m.is_active and m.superseded_at is null),
wk as (
  select bm.run, bm.mapping_id, w.state, w.last_outcome,
    left(regexp_replace(coalesce(w.last_failure, ''), '[0-9]+', 'N', 'g'), 40) reason,
    (select string_agg(distinct ps.availability, ',') from freshness_price_states ps
      where ps.work_id = w.id and ps.price_category = 'raw') availability
  from bm left join freshness_work w on w.source_card_mapping_id = bm.mapping_id and w.kind = 'refresh')
select run, (select count(*) from g where g.run = wk.run) groups,
  (select count(*) from bm where bm.run = wk.run) mappings,
  state, last_outcome, availability, reason, count(*) n
from wk group by run, state, last_outcome, availability, reason order by run, n desc;

-- refused
with ss as (select id from sources where name = 'snkrdunk'),
g as (
  select substring(g.reviewed_by from '^ops-write:approve-snkr-batch:([0-9]+|local)$') run,
    g.source_candidate_id cid
  from source_mapping_proposal_groups g
  where g.source_candidate_type = 'snkrdunk_candidate'
    and g.reviewed_by ~ '^ops-write:approve-snkr-batch:([0-9]+|local)$')
select distinct g.run, w.id work_id, m.id mapping_id, cc.card_code code, p.official_asset_variant variant,
  rp.official_code release,
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
order by g.run desc, reason, code, w.id;

-- proposals
with ss as (select id from sources where name = 'snkrdunk'),
mapped as (
  select m.canonical_source_listing_identity listing from source_card_mappings m
  where m.source_id = (select id from ss) and m.is_active and m.superseded_at is null
    and m.canonical_source_listing_identity is not null)
select case when c.created_at >= timestamptz '2026-11-03 13:24:00+00' then 'after' else 'before' end
    created_vs_1324z,
  c.detected_set_code is not null has_set_code,
  substring(c.source_url from '^https://snkrdunk\.com/(?:apparels|en/trading-cards)/([0-9]+)')
    in (select listing from mapped) listing_mapped,
  coalesce(g.resolution_status, 'none') proposal, count(*) n,
  min(c.created_at) first_created, max(c.created_at) last_created
from snkrdunk_candidates c
left join lateral (
  select g.resolution_status from source_mapping_proposal_groups g
  where g.source_candidate_type = 'snkrdunk_candidate' and g.source_candidate_id = c.id
    and g.superseded_at is null
  order by g.id desc limit 1) g on true
where c.created_at >= timestamptz '2026-11-02 10:00:00+00'
group by 1, 2, 3, 4 order by 1 desc, 5 desc;
