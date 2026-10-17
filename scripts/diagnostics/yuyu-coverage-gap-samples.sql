-- Yuyu-Tei coverage gap: the survey's sample prints, per-release gaps and examples per subclass.
-- Owner task D9 (2026-10-16), read-only. Population: active verified card_prints (the coverage
-- denominator). Classes per print: fresh = an eligible Yuyu mapping (active, current, approved)
-- with a listed price observed in the last 24 h; c = eligible mapping but no fresh price;
-- b = discovery found a Yuyu listing for the code but this print has no eligible mapping
-- (proposal/identity unresolved, mapping not approved, or listed only in another category);
-- d_est = every same-release Yuyu listing for the code is already mapped to a sibling print
-- (Yuyu probably does not list this print; ESTIMATE until a page check); a = no Yuyu candidate
-- carries the code. A listing counts as mapped only under an approved current mapping.
-- Codes, slugs and release codes compare after removing '-', '_' and spaces, as
-- source_mapping_proposals._norm does.

-- sample
with ys as (select id from sources where name = 'yuyutei'),
pr as (
  select p.id print_id, c.card_code code, upper(replace(replace(replace(c.card_code, '-', ''), '_', ''), ' ', '')) code_n,
    coalesce(nullif(p.official_rarity, ''), c.rarity, '?') rarity,
    case when p.official_asset_variant = 'base' then 'base' when p.official_asset_variant like 'p%' then 'parallel'
      when p.official_asset_variant like 'r%' then 'reprint' else 'unknown' end variant_kind,
    p.official_asset_variant variant, rp.official_code release_code, upper(replace(replace(replace(rp.official_code, '-', ''), '_', ''), ' ', '')) release_n
  from card_prints p join canonical_cards c on c.id = p.canonical_card_id
  left join release_products rp on rp.id = p.release_product_id
  where p.is_active and p.verification_status = 'verified'),
ym as (
  select m.card_print_id print_id,
    bool_or(m.is_active and m.superseded_at is null and m.review_status = 'approved') eligible,
    string_agg(distinct case when m.superseded_at is not null then 'superseded' when not m.is_active then 'inactive'
      when m.review_status <> 'approved' then m.review_status end, ',') other_states
  from source_card_mappings m where m.source_id = (select id from ys) and m.card_print_id is not null group by 1),
yf as (
  select m.card_print_id print_id,
    bool_or(ps.availability = 'listed' and ps.last_valid_price_observed_at >= now() - interval '24 hours') fresh,
    bool_or(w.id is not null) planned, bool_or(w.state = 'blocked') blocked,
    max(ps.last_successfully_checked_at) checked_at, max(ps.last_valid_price_observed_at) price_at,
    string_agg(distinct ps.availability, ',') availability
  from source_card_mappings m
  left join freshness_work w on w.source_card_mapping_id = m.id and w.kind = 'refresh'
  left join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null and m.review_status = 'approved'
    and m.card_print_id is not null
  group by 1),
ml as (
  select distinct m.canonical_source_listing_identity listing from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved'),
pg as (
  select distinct on (g.source_candidate_id) g.source_candidate_id cand_id, g.resolution_status, g.review_status
  from source_mapping_proposal_groups g
  where g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null
  order by g.source_candidate_id, g.id desc),
iw as (
  select w.resume_cursor::jsonb ->> 'candidate_id' cand_key, string_agg(distinct w.state, ',') intent_state
  from freshness_work w
  where w.kind = 'discovery' and w.source_id = (select id from ys) and w.resume_cursor is not null
    and w.resume_cursor::jsonb ->> 'candidate_id' is not null
  group by 1),
yc as (
  select y.id cand_id, upper(replace(replace(replace(y.detected_card_code, '-', ''), '_', ''), ' ', '')) code_n, upper(replace(replace(replace(y.set_slug, '-', ''), '_', ''), ' ', '')) slug_n, y.match_status,
    y.matched_card_print_id, ml.listing is not null listing_mapped,
    coalesce(pg.resolution_status, 'none') || '/' || coalesce(pg.review_status, '-') proposal, iw.intent_state
  from yuyutei_candidates y
  left join ml on ml.listing = lower(y.set_slug) || ':' || y.product_id
  left join pg on pg.cand_id = y.id
  left join iw on iw.cand_key = y.id::text
  where y.detected_card_code is not null),
pc as (
  select pr.print_id, count(yc.cand_id) cands_code,
    count(yc.cand_id) filter (where yc.slug_n = pr.release_n) cands_release,
    count(yc.cand_id) filter (where yc.slug_n = pr.release_n and not yc.listing_mapped) cands_release_unmapped,
    bool_or(yc.matched_card_print_id = pr.print_id) print_matched_self,
    string_agg(distinct yc.match_status, ',') match_states,
    string_agg(distinct yc.proposal, ',') filter (where yc.slug_n = pr.release_n and not yc.listing_mapped) unmapped_proposals,
    string_agg(distinct yc.intent_state, ',') filter (where yc.slug_n = pr.release_n and not yc.listing_mapped) intent_states
  from pr join yc on yc.code_n = pr.code_n group by 1),
pa as (
  select a.card_print_id print_id,
    string_agg(distinct g.resolution_status || '/' || g.review_status || case when a.recommended then '/rec' else '' end, ',') alt_states
  from source_mapping_proposal_alternatives a join source_mapping_proposal_groups g on g.id = a.proposal_group_id
  where g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null group by 1),
sl as (
  select upper(replace(replace(replace(e.k, '-', ''), '_', ''), ' ', '')) slug_n, max(r.finished_at) last_complete
  from yuyutei_discovery_runs r cross join lateral json_each(coalesce(r.per_slug_metrics_json, '{}'::json)) e(k, v)
  where r.status = 'completed' and (e.v ->> 'enumeration_complete') = 'true' group by 1),
sa as (
  select distinct upper(replace(replace(replace(s.k, '-', ''), '_', ''), ' ', '')) slug_n
  from yuyutei_discovery_runs r cross join lateral json_array_elements_text(coalesce(r.requested_set_slugs, '[]'::json)) s(k)),
cls as (
  select pr.*, coalesce(ym.eligible, false) mapped, ym.other_states, yf.fresh, yf.planned, yf.blocked, yf.checked_at,
    yf.price_at, yf.availability, coalesce(pc.cands_code, 0) cands_code, coalesce(pc.cands_release, 0) cands_release,
    coalesce(pc.cands_release_unmapped, 0) cands_release_unmapped, pc.print_matched_self, pc.match_states,
    pc.unmapped_proposals, pc.intent_states, pa.alt_states, sl.last_complete release_last_enumerated,
    case
      when coalesce(yf.fresh, false) then 'fresh'
      when coalesce(ym.eligible, false) then 'c'
      when coalesce(pc.cands_release_unmapped, 0) > 0 or ym.other_states is not null then 'b'
      when coalesce(pc.cands_release, 0) > 0 then 'd_est'
      when coalesce(pc.cands_code, 0) > 0 then 'b'
      else 'a' end klass,
    case
      when coalesce(yf.fresh, false) then 'fresh'
      when coalesce(ym.eligible, false) then
        case when not yf.planned then 'c_no_refresh_work' when yf.blocked then 'c_quarantined'
          when yf.checked_at is null then 'c_never_checked'
          when yf.checked_at < now() - interval '24 hours' then 'c_check_older_than_24h'
          when yf.availability like '%no_listing%' then 'c_no_listing'
          else 'c_checked_no_valid_price_24h' end
      when coalesce(pc.cands_release_unmapped, 0) > 0 then
        case when pc.intent_states is not null then 'b_capture_intent:' || pc.intent_states
          else 'b_proposal:' || coalesce(pc.unmapped_proposals, 'none') end
      when ym.other_states is not null then 'b_mapping:' || ym.other_states
      when coalesce(pc.cands_release, 0) > 0 then 'd_release_listings_all_mapped_to_siblings'
      when coalesce(pc.cands_code, 0) > 0 then 'b_code_listed_only_in_other_category'
      when pr.release_n is null then 'a_release_uncoded'
      when sl.slug_n is not null then 'a_release_enumerated_code_absent'
      when sa.slug_n is not null then 'a_release_enumeration_incomplete'
      else 'a_release_never_enumerated' end subclass
  from pr left join ym using (print_id) left join yf using (print_id) left join pc using (print_id)
  left join pa using (print_id) left join sl on sl.slug_n = pr.release_n left join sa on sa.slug_n = pr.release_n)
select code, rarity, variant, release_code, klass, subclass, mapped, other_states, fresh, blocked, checked_at, price_at,
  availability, cands_code, cands_release, cands_release_unmapped, print_matched_self, match_states, unmapped_proposals,
  intent_states, alt_states, release_last_enumerated
from cls where code in ('OP05-074', 'OP05-091', 'OP05-093', 'OP05-100', 'OP05-118', 'OP13-118') order by code, variant;

-- releases
with ys as (select id from sources where name = 'yuyutei'),
pr as (
  select p.id print_id, c.card_code code, upper(replace(replace(replace(c.card_code, '-', ''), '_', ''), ' ', '')) code_n,
    coalesce(nullif(p.official_rarity, ''), c.rarity, '?') rarity,
    case when p.official_asset_variant = 'base' then 'base' when p.official_asset_variant like 'p%' then 'parallel'
      when p.official_asset_variant like 'r%' then 'reprint' else 'unknown' end variant_kind,
    p.official_asset_variant variant, rp.official_code release_code, upper(replace(replace(replace(rp.official_code, '-', ''), '_', ''), ' ', '')) release_n
  from card_prints p join canonical_cards c on c.id = p.canonical_card_id
  left join release_products rp on rp.id = p.release_product_id
  where p.is_active and p.verification_status = 'verified'),
ym as (
  select m.card_print_id print_id,
    bool_or(m.is_active and m.superseded_at is null and m.review_status = 'approved') eligible,
    string_agg(distinct case when m.superseded_at is not null then 'superseded' when not m.is_active then 'inactive'
      when m.review_status <> 'approved' then m.review_status end, ',') other_states
  from source_card_mappings m where m.source_id = (select id from ys) and m.card_print_id is not null group by 1),
yf as (
  select m.card_print_id print_id,
    bool_or(ps.availability = 'listed' and ps.last_valid_price_observed_at >= now() - interval '24 hours') fresh,
    bool_or(w.id is not null) planned, bool_or(w.state = 'blocked') blocked,
    max(ps.last_successfully_checked_at) checked_at, max(ps.last_valid_price_observed_at) price_at,
    string_agg(distinct ps.availability, ',') availability
  from source_card_mappings m
  left join freshness_work w on w.source_card_mapping_id = m.id and w.kind = 'refresh'
  left join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null and m.review_status = 'approved'
    and m.card_print_id is not null
  group by 1),
ml as (
  select distinct m.canonical_source_listing_identity listing from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved'),
pg as (
  select distinct on (g.source_candidate_id) g.source_candidate_id cand_id, g.resolution_status, g.review_status
  from source_mapping_proposal_groups g
  where g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null
  order by g.source_candidate_id, g.id desc),
iw as (
  select w.resume_cursor::jsonb ->> 'candidate_id' cand_key, string_agg(distinct w.state, ',') intent_state
  from freshness_work w
  where w.kind = 'discovery' and w.source_id = (select id from ys) and w.resume_cursor is not null
    and w.resume_cursor::jsonb ->> 'candidate_id' is not null
  group by 1),
yc as (
  select y.id cand_id, upper(replace(replace(replace(y.detected_card_code, '-', ''), '_', ''), ' ', '')) code_n, upper(replace(replace(replace(y.set_slug, '-', ''), '_', ''), ' ', '')) slug_n, y.match_status,
    y.matched_card_print_id, ml.listing is not null listing_mapped,
    coalesce(pg.resolution_status, 'none') || '/' || coalesce(pg.review_status, '-') proposal, iw.intent_state
  from yuyutei_candidates y
  left join ml on ml.listing = lower(y.set_slug) || ':' || y.product_id
  left join pg on pg.cand_id = y.id
  left join iw on iw.cand_key = y.id::text
  where y.detected_card_code is not null),
pc as (
  select pr.print_id, count(yc.cand_id) cands_code,
    count(yc.cand_id) filter (where yc.slug_n = pr.release_n) cands_release,
    count(yc.cand_id) filter (where yc.slug_n = pr.release_n and not yc.listing_mapped) cands_release_unmapped,
    bool_or(yc.matched_card_print_id = pr.print_id) print_matched_self,
    string_agg(distinct yc.match_status, ',') match_states,
    string_agg(distinct yc.proposal, ',') filter (where yc.slug_n = pr.release_n and not yc.listing_mapped) unmapped_proposals,
    string_agg(distinct yc.intent_state, ',') filter (where yc.slug_n = pr.release_n and not yc.listing_mapped) intent_states
  from pr join yc on yc.code_n = pr.code_n group by 1),
pa as (
  select a.card_print_id print_id,
    string_agg(distinct g.resolution_status || '/' || g.review_status || case when a.recommended then '/rec' else '' end, ',') alt_states
  from source_mapping_proposal_alternatives a join source_mapping_proposal_groups g on g.id = a.proposal_group_id
  where g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null group by 1),
sl as (
  select upper(replace(replace(replace(e.k, '-', ''), '_', ''), ' ', '')) slug_n, max(r.finished_at) last_complete
  from yuyutei_discovery_runs r cross join lateral json_each(coalesce(r.per_slug_metrics_json, '{}'::json)) e(k, v)
  where r.status = 'completed' and (e.v ->> 'enumeration_complete') = 'true' group by 1),
sa as (
  select distinct upper(replace(replace(replace(s.k, '-', ''), '_', ''), ' ', '')) slug_n
  from yuyutei_discovery_runs r cross join lateral json_array_elements_text(coalesce(r.requested_set_slugs, '[]'::json)) s(k)),
cls as (
  select pr.*, coalesce(ym.eligible, false) mapped, ym.other_states, yf.fresh, yf.planned, yf.blocked, yf.checked_at,
    yf.price_at, yf.availability, coalesce(pc.cands_code, 0) cands_code, coalesce(pc.cands_release, 0) cands_release,
    coalesce(pc.cands_release_unmapped, 0) cands_release_unmapped, pc.print_matched_self, pc.match_states,
    pc.unmapped_proposals, pc.intent_states, pa.alt_states, sl.last_complete release_last_enumerated,
    case
      when coalesce(yf.fresh, false) then 'fresh'
      when coalesce(ym.eligible, false) then 'c'
      when coalesce(pc.cands_release_unmapped, 0) > 0 or ym.other_states is not null then 'b'
      when coalesce(pc.cands_release, 0) > 0 then 'd_est'
      when coalesce(pc.cands_code, 0) > 0 then 'b'
      else 'a' end klass,
    case
      when coalesce(yf.fresh, false) then 'fresh'
      when coalesce(ym.eligible, false) then
        case when not yf.planned then 'c_no_refresh_work' when yf.blocked then 'c_quarantined'
          when yf.checked_at is null then 'c_never_checked'
          when yf.checked_at < now() - interval '24 hours' then 'c_check_older_than_24h'
          when yf.availability like '%no_listing%' then 'c_no_listing'
          else 'c_checked_no_valid_price_24h' end
      when coalesce(pc.cands_release_unmapped, 0) > 0 then
        case when pc.intent_states is not null then 'b_capture_intent:' || pc.intent_states
          else 'b_proposal:' || coalesce(pc.unmapped_proposals, 'none') end
      when ym.other_states is not null then 'b_mapping:' || ym.other_states
      when coalesce(pc.cands_release, 0) > 0 then 'd_release_listings_all_mapped_to_siblings'
      when coalesce(pc.cands_code, 0) > 0 then 'b_code_listed_only_in_other_category'
      when pr.release_n is null then 'a_release_uncoded'
      when sl.slug_n is not null then 'a_release_enumerated_code_absent'
      when sa.slug_n is not null then 'a_release_enumeration_incomplete'
      else 'a_release_never_enumerated' end subclass
  from pr left join ym using (print_id) left join yf using (print_id) left join pc using (print_id)
  left join pa using (print_id) left join sl on sl.slug_n = pr.release_n left join sa on sa.slug_n = pr.release_n)
select release_code, count(*) prints, count(*) filter (where klass = 'fresh') fresh,
  count(*) filter (where klass = 'a') a, count(*) filter (where klass = 'b') b, count(*) filter (where klass = 'c') c,
  count(*) filter (where klass = 'd_est') d_est, max(release_last_enumerated) last_enumerated
from cls group by 1 having count(*) filter (where klass <> 'fresh') > 0 order by 1;

-- examples
with ys as (select id from sources where name = 'yuyutei'),
pr as (
  select p.id print_id, c.card_code code, upper(replace(replace(replace(c.card_code, '-', ''), '_', ''), ' ', '')) code_n,
    coalesce(nullif(p.official_rarity, ''), c.rarity, '?') rarity,
    case when p.official_asset_variant = 'base' then 'base' when p.official_asset_variant like 'p%' then 'parallel'
      when p.official_asset_variant like 'r%' then 'reprint' else 'unknown' end variant_kind,
    p.official_asset_variant variant, rp.official_code release_code, upper(replace(replace(replace(rp.official_code, '-', ''), '_', ''), ' ', '')) release_n
  from card_prints p join canonical_cards c on c.id = p.canonical_card_id
  left join release_products rp on rp.id = p.release_product_id
  where p.is_active and p.verification_status = 'verified'),
ym as (
  select m.card_print_id print_id,
    bool_or(m.is_active and m.superseded_at is null and m.review_status = 'approved') eligible,
    string_agg(distinct case when m.superseded_at is not null then 'superseded' when not m.is_active then 'inactive'
      when m.review_status <> 'approved' then m.review_status end, ',') other_states
  from source_card_mappings m where m.source_id = (select id from ys) and m.card_print_id is not null group by 1),
yf as (
  select m.card_print_id print_id,
    bool_or(ps.availability = 'listed' and ps.last_valid_price_observed_at >= now() - interval '24 hours') fresh,
    bool_or(w.id is not null) planned, bool_or(w.state = 'blocked') blocked,
    max(ps.last_successfully_checked_at) checked_at, max(ps.last_valid_price_observed_at) price_at,
    string_agg(distinct ps.availability, ',') availability
  from source_card_mappings m
  left join freshness_work w on w.source_card_mapping_id = m.id and w.kind = 'refresh'
  left join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null and m.review_status = 'approved'
    and m.card_print_id is not null
  group by 1),
ml as (
  select distinct m.canonical_source_listing_identity listing from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved'),
pg as (
  select distinct on (g.source_candidate_id) g.source_candidate_id cand_id, g.resolution_status, g.review_status
  from source_mapping_proposal_groups g
  where g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null
  order by g.source_candidate_id, g.id desc),
iw as (
  select w.resume_cursor::jsonb ->> 'candidate_id' cand_key, string_agg(distinct w.state, ',') intent_state
  from freshness_work w
  where w.kind = 'discovery' and w.source_id = (select id from ys) and w.resume_cursor is not null
    and w.resume_cursor::jsonb ->> 'candidate_id' is not null
  group by 1),
yc as (
  select y.id cand_id, upper(replace(replace(replace(y.detected_card_code, '-', ''), '_', ''), ' ', '')) code_n, upper(replace(replace(replace(y.set_slug, '-', ''), '_', ''), ' ', '')) slug_n, y.match_status,
    y.matched_card_print_id, ml.listing is not null listing_mapped,
    coalesce(pg.resolution_status, 'none') || '/' || coalesce(pg.review_status, '-') proposal, iw.intent_state
  from yuyutei_candidates y
  left join ml on ml.listing = lower(y.set_slug) || ':' || y.product_id
  left join pg on pg.cand_id = y.id
  left join iw on iw.cand_key = y.id::text
  where y.detected_card_code is not null),
pc as (
  select pr.print_id, count(yc.cand_id) cands_code,
    count(yc.cand_id) filter (where yc.slug_n = pr.release_n) cands_release,
    count(yc.cand_id) filter (where yc.slug_n = pr.release_n and not yc.listing_mapped) cands_release_unmapped,
    bool_or(yc.matched_card_print_id = pr.print_id) print_matched_self,
    string_agg(distinct yc.match_status, ',') match_states,
    string_agg(distinct yc.proposal, ',') filter (where yc.slug_n = pr.release_n and not yc.listing_mapped) unmapped_proposals,
    string_agg(distinct yc.intent_state, ',') filter (where yc.slug_n = pr.release_n and not yc.listing_mapped) intent_states
  from pr join yc on yc.code_n = pr.code_n group by 1),
pa as (
  select a.card_print_id print_id,
    string_agg(distinct g.resolution_status || '/' || g.review_status || case when a.recommended then '/rec' else '' end, ',') alt_states
  from source_mapping_proposal_alternatives a join source_mapping_proposal_groups g on g.id = a.proposal_group_id
  where g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null group by 1),
sl as (
  select upper(replace(replace(replace(e.k, '-', ''), '_', ''), ' ', '')) slug_n, max(r.finished_at) last_complete
  from yuyutei_discovery_runs r cross join lateral json_each(coalesce(r.per_slug_metrics_json, '{}'::json)) e(k, v)
  where r.status = 'completed' and (e.v ->> 'enumeration_complete') = 'true' group by 1),
sa as (
  select distinct upper(replace(replace(replace(s.k, '-', ''), '_', ''), ' ', '')) slug_n
  from yuyutei_discovery_runs r cross join lateral json_array_elements_text(coalesce(r.requested_set_slugs, '[]'::json)) s(k)),
cls as (
  select pr.*, coalesce(ym.eligible, false) mapped, ym.other_states, yf.fresh, yf.planned, yf.blocked, yf.checked_at,
    yf.price_at, yf.availability, coalesce(pc.cands_code, 0) cands_code, coalesce(pc.cands_release, 0) cands_release,
    coalesce(pc.cands_release_unmapped, 0) cands_release_unmapped, pc.print_matched_self, pc.match_states,
    pc.unmapped_proposals, pc.intent_states, pa.alt_states, sl.last_complete release_last_enumerated,
    case
      when coalesce(yf.fresh, false) then 'fresh'
      when coalesce(ym.eligible, false) then 'c'
      when coalesce(pc.cands_release_unmapped, 0) > 0 or ym.other_states is not null then 'b'
      when coalesce(pc.cands_release, 0) > 0 then 'd_est'
      when coalesce(pc.cands_code, 0) > 0 then 'b'
      else 'a' end klass,
    case
      when coalesce(yf.fresh, false) then 'fresh'
      when coalesce(ym.eligible, false) then
        case when not yf.planned then 'c_no_refresh_work' when yf.blocked then 'c_quarantined'
          when yf.checked_at is null then 'c_never_checked'
          when yf.checked_at < now() - interval '24 hours' then 'c_check_older_than_24h'
          when yf.availability like '%no_listing%' then 'c_no_listing'
          else 'c_checked_no_valid_price_24h' end
      when coalesce(pc.cands_release_unmapped, 0) > 0 then
        case when pc.intent_states is not null then 'b_capture_intent:' || pc.intent_states
          else 'b_proposal:' || coalesce(pc.unmapped_proposals, 'none') end
      when ym.other_states is not null then 'b_mapping:' || ym.other_states
      when coalesce(pc.cands_release, 0) > 0 then 'd_release_listings_all_mapped_to_siblings'
      when coalesce(pc.cands_code, 0) > 0 then 'b_code_listed_only_in_other_category'
      when pr.release_n is null then 'a_release_uncoded'
      when sl.slug_n is not null then 'a_release_enumerated_code_absent'
      when sa.slug_n is not null then 'a_release_enumeration_incomplete'
      else 'a_release_never_enumerated' end subclass
  from pr left join ym using (print_id) left join yf using (print_id) left join pc using (print_id)
  left join pa using (print_id) left join sl on sl.slug_n = pr.release_n left join sa on sa.slug_n = pr.release_n)
select subclass, code, rarity, variant, release_code from (
  select cls.*, row_number() over (partition by subclass order by code, variant) rn from cls where klass <> 'fresh') x
where rn <= 3 order by subclass, rn;
