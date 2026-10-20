-- F1 approval receipt (owner questions 2026-10-20 09:46Z on batch-2 apply 39386848341). Read-only.
-- For every proposal group an approve-f1-batch apply approved (reviewed_by
-- 'ops-write:approve-f1-batch:<run id>'): whether the approval created its mapping or reused one
-- that already existed (mapping created before its run's first approval: a new mapping's
-- created_at is its approval transaction's start, several seconds before reviewed_at) or that
-- another approved group also resolved to (two candidates of one listing), and whether the mapping has its raw
-- refresh row (freshness_work kind 'refresh', planned at approval since #189 or by
-- plan-refresh-backfill), with that row's state and last successful check.

-- runs
with g as (
  select g.id, g.reviewed_by, g.reviewed_at, m.id mapping_id,
    m.created_at < (select min(r.reviewed_at) from source_mapping_proposal_groups r where r.reviewed_by = g.reviewed_by) reused,
    exists (select 1 from source_mapping_proposal_groups o where o.resulting_source_card_mapping_id = m.id and o.id <> g.id
      and o.review_status = 'approved') shared,
    w.id work_id, w.state, w.last_successfully_checked_at
  from source_mapping_proposal_groups g
  join source_card_mappings m on m.id = g.resulting_source_card_mapping_id
  left join freshness_work w on w.kind = 'refresh' and w.source_card_mapping_id = m.id
  where g.reviewed_by like 'ops-write:approve-f1-batch:%' and g.review_status = 'approved')
select reviewed_by, count(*) groups, min(reviewed_at) first_review, max(reviewed_at) last_review,
  count(*) filter (where not reused) mappings_created, count(*) filter (where reused) mappings_reused,
  count(*) filter (where shared) mapping_shared_with_other_group,
  count(*) filter (where work_id is not null) with_refresh_work, count(*) filter (where work_id is null) without_refresh_work,
  count(*) filter (where last_successfully_checked_at is not null) refresh_checked_once,
  count(*) filter (where last_successfully_checked_at > now() - interval '24 hours') refresh_checked_24h
from g group by 1 order by 1;

-- refresh_states
select g.reviewed_by, coalesce(w.state, 'no_row') state, count(*) n, min(w.next_due_at) next_due_min, max(w.next_due_at) next_due_max
from source_mapping_proposal_groups g
join source_card_mappings m on m.id = g.resulting_source_card_mapping_id
left join freshness_work w on w.kind = 'refresh' and w.source_card_mapping_id = m.id
where g.reviewed_by like 'ops-write:approve-f1-batch:%' and g.review_status = 'approved'
group by 1, 2 order by 1, 2;

-- reused
select g.id group_id, g.reviewed_by, c.card_code code, p.id print_id, p.official_rarity rarity, p.official_asset_variant variant,
  g.canonical_source_listing_identity listing, m.id mapping_id, m.created_at mapping_created_at, m.updated_at mapping_updated_at,
  g.reviewed_at, m.is_active, m.review_status, m.superseded_at, m.manual_verified, m.match_confidence_label,
  left(m.review_notes, 160) review_notes,
  (select string_agg(o.id::text || ':' || o.review_status || ':' || coalesce(o.reviewed_by, '-'), ',' order by o.id)
    from source_mapping_proposal_groups o where o.resulting_source_card_mapping_id = m.id and o.id <> g.id) other_groups
from source_mapping_proposal_groups g
join source_card_mappings m on m.id = g.resulting_source_card_mapping_id
join card_prints p on p.id = m.card_print_id join canonical_cards c on c.id = p.canonical_card_id
where g.reviewed_by like 'ops-write:approve-f1-batch:%' and g.review_status = 'approved'
  and (m.created_at < (select min(r.reviewed_at) from source_mapping_proposal_groups r where r.reviewed_by = g.reviewed_by)
    or exists (select 1 from source_mapping_proposal_groups o where o.resulting_source_card_mapping_id = m.id and o.id <> g.id
      and o.review_status = 'approved'))
order by g.id;

-- without_refresh_work
select g.id group_id, g.reviewed_by, c.card_code code, m.id mapping_id, g.canonical_source_listing_identity listing,
  m.is_active, m.review_status, m.superseded_at, p.is_active print_active, p.verification_status,
  (select string_agg(w.id::text || ':' || w.source_card_mapping_id::text, ',') from freshness_work w
    join source_card_mappings o on o.id = w.source_card_mapping_id
    where w.kind = 'refresh' and o.canonical_source_listing_identity = m.canonical_source_listing_identity
      and o.source_id = m.source_id and o.id <> m.id) listing_work_under_other_mapping
from source_mapping_proposal_groups g
join source_card_mappings m on m.id = g.resulting_source_card_mapping_id
join card_prints p on p.id = m.card_print_id join canonical_cards c on c.id = p.canonical_card_id
where g.reviewed_by like 'ops-write:approve-f1-batch:%' and g.review_status = 'approved'
  and not exists (select 1 from freshness_work w where w.kind = 'refresh' and w.source_card_mapping_id = m.id)
order by g.id;
