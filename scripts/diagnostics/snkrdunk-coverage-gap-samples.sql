-- SNKRDUNK raw coverage gap for the high-rarity target prints. Owner task (2026-10-18), read-only,
-- modelled on yuyu-coverage-gap (D9). Population: active verified card_prints; target = every print
-- except base (non-parallel) C, UC, R and SR, which are reported once in `excluded`. PSA10 is not read.
-- Classes per print: fresh = an eligible SNKRDUNK mapping (active, current, approved and
-- manual_verified, as freshness_queue requires for SNKRDUNK) with a listed raw (floor) price observed
-- in the last 24 h; c = eligible mapping but no fresh raw price; d = the mapped product was checked in
-- the last 24 h and has no raw ask, or every SNKRDUNK candidate for the code is already mapped to a
-- sibling print (probably not sold raw; ESTIMATE until a page check); b = a SNKRDUNK candidate carries
-- the code and its listing is not mapped, or the print has only a non-eligible mapping; a = no
-- SNKRDUNK candidate carries the code; e = eligible mapping whose stored listing identity does not
-- match its URL (refresh refuses it). Listing kind is read from the candidate title (manga, SP,
-- parallel, plain); print kind from official rarity and asset variant (the catalogue has no manga mark).
-- Codes compare after removing '-', '_' and spaces, as source_mapping_proposals._norm does.
-- This file: 20 deterministic random target prints from the biggest gap class and 3 from each other
-- class, with the best same-code SNKRDUNK candidate (same kind, then same release first).

-- biggest_class
with ss as (select id from sources where name = 'snkrdunk'),
pr as (
  select p.id print_id, c.card_code code, upper(replace(replace(replace(c.card_code, '-', ''), '_', ''), ' ', '')) code_n,
    coalesce(nullif(p.official_rarity, ''), c.rarity, '?') rarity,
    case when p.official_asset_variant = 'base' then 'base' when p.official_asset_variant like 'p%' then 'parallel'
      when p.official_asset_variant like 'r%' then 'reprint' else 'unknown' end variant_kind,
    p.official_asset_variant variant, p.release_product_id, rp.official_code release_code,
    upper(replace(replace(replace(rp.official_code, '-', ''), '_', ''), ' ', '')) release_n
  from card_prints p join canonical_cards c on c.id = p.canonical_card_id
  left join release_products rp on rp.id = p.release_product_id
  where p.is_active and p.verification_status = 'verified'),
tp as (
  select pr.*, not (pr.rarity in ('C', 'UC', 'R', 'SR') and pr.variant_kind <> 'parallel') target,
    case when pr.rarity like 'SP%' then 'sp' when pr.variant_kind = 'parallel' then 'parallel' else 'plain' end print_kind
  from pr),
sm as (
  select m.card_print_id print_id,
    bool_or(m.is_active and m.superseded_at is null and m.review_status = 'approved' and m.manual_verified) eligible,
    string_agg(distinct case when m.superseded_at is not null then 'superseded' when not m.is_active then 'inactive'
      when m.review_status <> 'approved' then m.review_status when not m.manual_verified then 'not_manual_verified' end,
      ',') other_states, string_agg(distinct m.canonical_source_listing_identity, ',') all_listings
  from source_card_mappings m where m.source_id = (select id from ss) and m.card_print_id is not null group by 1),
sf as (
  select m.card_print_id print_id,
    bool_or(ps.availability = 'listed' and ps.last_valid_price_observed_at >= now() - interval '24 hours') fresh,
    bool_or(m.canonical_source_listing_identity
      = substring(m.source_url from '^https://snkrdunk\.com/(?:apparels|en/trading-cards)/([0-9]+)')) identity_ok,
    bool_or(w.id is not null) planned, bool_or(w.state = 'blocked') blocked,
    max(ps.last_successfully_checked_at) checked_at, max(ps.last_valid_price_observed_at) price_at,
    string_agg(distinct ps.availability, ',') availability
  from source_card_mappings m
  left join freshness_work w on w.source_card_mapping_id = m.id and w.kind = 'refresh'
  left join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where m.source_id = (select id from ss) and m.is_active and m.superseded_at is null and m.review_status = 'approved'
    and m.manual_verified and m.card_print_id is not null
  group by 1),
ml as (
  select distinct m.canonical_source_listing_identity listing from source_card_mappings m
  where m.source_id = (select id from ss) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved'),
pg as (
  select distinct on (g.source_candidate_id) g.source_candidate_id cand_id, g.resolution_status, g.review_status,
    g.release_product_id
  from source_mapping_proposal_groups g
  where g.source_candidate_type = 'snkrdunk_candidate' and g.superseded_at is null
  order by g.source_candidate_id, g.id desc),
sc as (
  select s.id cand_id, s.title, s.created_at, upper(replace(replace(replace(s.detected_card_code, '-', ''), '_', ''), ' ', '')) code_n,
    upper(replace(replace(replace(s.detected_set_code, '-', ''), '_', ''), ' ', '')) set_n, pg.release_product_id prop_release_id,
    substring(s.source_url from '^https://snkrdunk\.com/(?:apparels|en/trading-cards)/([0-9]+)') listing,
    ml.listing is not null listing_mapped, coalesce(pg.resolution_status, 'none') proposal,
    case when s.title ~* '(コミパラ|コミック|マンガ|漫画|manga)' then 'manga'
      when s.title ~ '(SP|ＳＰ|スペシャル)' or upper(coalesce(s.detected_rarity, '')) like '%SP%' then 'sp'
      when s.title ~* '(パラレル|parallel)' or coalesce(s.detected_variant, '') ~ '^p[0-9]' then 'parallel'
      else 'plain' end listing_kind
  from snkrdunk_candidates s
  left join ml on ml.listing = substring(s.source_url from '^https://snkrdunk\.com/(?:apparels|en/trading-cards)/([0-9]+)')
  left join pg on pg.cand_id = s.id
  where s.detected_card_code is not null),
pc as (
  select tp.print_id, count(sc.cand_id) cands_code,
    count(sc.cand_id) filter (where sc.prop_release_id = tp.release_product_id or sc.set_n = tp.release_n) cands_release,
    count(sc.cand_id) filter (where not sc.listing_mapped) cands_unmapped,
    string_agg(distinct sc.proposal, ',') filter (where not sc.listing_mapped) unmapped_proposals,
    string_agg(distinct sc.listing_kind, ',') filter (where not sc.listing_mapped) unmapped_kinds
  from tp join sc on sc.code_n = tp.code_n group by 1),
ra as (
  select tp.release_product_id, count(*) anchors from tp join sm using (print_id)
  where sm.eligible and tp.release_product_id is not null group by 1),
cls as (
  select tp.*, coalesce(sm.eligible, false) mapped, sm.other_states, sf.fresh, sf.checked_at, sf.price_at,
    sf.availability, sm.all_listings, coalesce(pc.cands_code, 0) cands_code, coalesce(pc.cands_release, 0) cands_release,
    coalesce(pc.cands_unmapped, 0) cands_unmapped, pc.unmapped_proposals, pc.unmapped_kinds,
    case
      when coalesce(sf.fresh, false) then 'fresh'
      when coalesce(sm.eligible, false) and not coalesce(sf.identity_ok, false) then 'e'
      when coalesce(sm.eligible, false) and sf.planned and not sf.blocked and sf.checked_at >= now() - interval '24 hours'
        and sf.availability = 'no_listing' then 'd'
      when coalesce(sm.eligible, false) then 'c'
      when coalesce(pc.cands_unmapped, 0) > 0 or sm.other_states is not null then 'b'
      when coalesce(pc.cands_code, 0) > 0 then 'd'
      else 'a' end klass,
    case
      when coalesce(sf.fresh, false) then 'fresh'
      when coalesce(sm.eligible, false) and not coalesce(sf.identity_ok, false) then 'e_mapping_listing_identity_invalid'
      when coalesce(sm.eligible, false) then
        case when not sf.planned then 'c_no_refresh_work' when sf.blocked then 'c_quarantined'
          when sf.checked_at is null then 'c_never_checked'
          when sf.checked_at < now() - interval '24 hours' then 'c_check_older_than_24h'
          when sf.availability = 'no_listing' then 'd_mapped_no_raw_ask_24h'
          else 'c_checked_no_valid_price_24h' end
      when sm.other_states like '%not_manual_verified%' then 'b_mapping_not_manual_verified'
      when coalesce(pc.cands_unmapped, 0) > 0 then 'b_proposal:' || coalesce(pc.unmapped_proposals, 'none')
      when sm.other_states is not null then 'b_mapping:' || sm.other_states
      when coalesce(pc.cands_code, 0) > 0 then 'd_est_all_code_listings_mapped_to_siblings'
      when tp.release_product_id is null then 'a_release_uncoded'
      when ra.anchors is not null then 'a_release_has_snkrdunk_anchor'
      else 'a_release_has_no_snkrdunk_anchor' end subclass
  from tp left join sm using (print_id) left join sf using (print_id) left join pc using (print_id)
  left join ra on ra.release_product_id = tp.release_product_id), big as (select klass from cls where target and klass <> 'fresh' group by 1 order by count(*) desc limit 1)
select cls.klass, cls.subclass, cls.code, cls.rarity, cls.variant, cls.release_code release, cls.print_kind,
  t.listing, left(t.title, 40) title, t.listing_kind, t.proposal
from cls left join lateral (
  select sc.listing, sc.title, sc.listing_kind, sc.proposal from sc
  where sc.code_n = cls.code_n and (cls.klass <> 'b' or not sc.listing_mapped
    or sc.listing = any(string_to_array(cls.all_listings, ',')))
  order by (sc.listing = any(string_to_array(cls.all_listings, ','))) desc, (sc.listing_kind = cls.print_kind) desc,
    (sc.prop_release_id = cls.release_product_id or sc.set_n = cls.release_n) desc, sc.cand_id limit 1) t on true
where cls.target and cls.klass = (select klass from big)
order by md5('snk-gap-' || cls.print_id::text) limit 20;

-- other_classes
with ss as (select id from sources where name = 'snkrdunk'),
pr as (
  select p.id print_id, c.card_code code, upper(replace(replace(replace(c.card_code, '-', ''), '_', ''), ' ', '')) code_n,
    coalesce(nullif(p.official_rarity, ''), c.rarity, '?') rarity,
    case when p.official_asset_variant = 'base' then 'base' when p.official_asset_variant like 'p%' then 'parallel'
      when p.official_asset_variant like 'r%' then 'reprint' else 'unknown' end variant_kind,
    p.official_asset_variant variant, p.release_product_id, rp.official_code release_code,
    upper(replace(replace(replace(rp.official_code, '-', ''), '_', ''), ' ', '')) release_n
  from card_prints p join canonical_cards c on c.id = p.canonical_card_id
  left join release_products rp on rp.id = p.release_product_id
  where p.is_active and p.verification_status = 'verified'),
tp as (
  select pr.*, not (pr.rarity in ('C', 'UC', 'R', 'SR') and pr.variant_kind <> 'parallel') target,
    case when pr.rarity like 'SP%' then 'sp' when pr.variant_kind = 'parallel' then 'parallel' else 'plain' end print_kind
  from pr),
sm as (
  select m.card_print_id print_id,
    bool_or(m.is_active and m.superseded_at is null and m.review_status = 'approved' and m.manual_verified) eligible,
    string_agg(distinct case when m.superseded_at is not null then 'superseded' when not m.is_active then 'inactive'
      when m.review_status <> 'approved' then m.review_status when not m.manual_verified then 'not_manual_verified' end,
      ',') other_states, string_agg(distinct m.canonical_source_listing_identity, ',') all_listings
  from source_card_mappings m where m.source_id = (select id from ss) and m.card_print_id is not null group by 1),
sf as (
  select m.card_print_id print_id,
    bool_or(ps.availability = 'listed' and ps.last_valid_price_observed_at >= now() - interval '24 hours') fresh,
    bool_or(m.canonical_source_listing_identity
      = substring(m.source_url from '^https://snkrdunk\.com/(?:apparels|en/trading-cards)/([0-9]+)')) identity_ok,
    bool_or(w.id is not null) planned, bool_or(w.state = 'blocked') blocked,
    max(ps.last_successfully_checked_at) checked_at, max(ps.last_valid_price_observed_at) price_at,
    string_agg(distinct ps.availability, ',') availability
  from source_card_mappings m
  left join freshness_work w on w.source_card_mapping_id = m.id and w.kind = 'refresh'
  left join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where m.source_id = (select id from ss) and m.is_active and m.superseded_at is null and m.review_status = 'approved'
    and m.manual_verified and m.card_print_id is not null
  group by 1),
ml as (
  select distinct m.canonical_source_listing_identity listing from source_card_mappings m
  where m.source_id = (select id from ss) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved'),
pg as (
  select distinct on (g.source_candidate_id) g.source_candidate_id cand_id, g.resolution_status, g.review_status,
    g.release_product_id
  from source_mapping_proposal_groups g
  where g.source_candidate_type = 'snkrdunk_candidate' and g.superseded_at is null
  order by g.source_candidate_id, g.id desc),
sc as (
  select s.id cand_id, s.title, s.created_at, upper(replace(replace(replace(s.detected_card_code, '-', ''), '_', ''), ' ', '')) code_n,
    upper(replace(replace(replace(s.detected_set_code, '-', ''), '_', ''), ' ', '')) set_n, pg.release_product_id prop_release_id,
    substring(s.source_url from '^https://snkrdunk\.com/(?:apparels|en/trading-cards)/([0-9]+)') listing,
    ml.listing is not null listing_mapped, coalesce(pg.resolution_status, 'none') proposal,
    case when s.title ~* '(コミパラ|コミック|マンガ|漫画|manga)' then 'manga'
      when s.title ~ '(SP|ＳＰ|スペシャル)' or upper(coalesce(s.detected_rarity, '')) like '%SP%' then 'sp'
      when s.title ~* '(パラレル|parallel)' or coalesce(s.detected_variant, '') ~ '^p[0-9]' then 'parallel'
      else 'plain' end listing_kind
  from snkrdunk_candidates s
  left join ml on ml.listing = substring(s.source_url from '^https://snkrdunk\.com/(?:apparels|en/trading-cards)/([0-9]+)')
  left join pg on pg.cand_id = s.id
  where s.detected_card_code is not null),
pc as (
  select tp.print_id, count(sc.cand_id) cands_code,
    count(sc.cand_id) filter (where sc.prop_release_id = tp.release_product_id or sc.set_n = tp.release_n) cands_release,
    count(sc.cand_id) filter (where not sc.listing_mapped) cands_unmapped,
    string_agg(distinct sc.proposal, ',') filter (where not sc.listing_mapped) unmapped_proposals,
    string_agg(distinct sc.listing_kind, ',') filter (where not sc.listing_mapped) unmapped_kinds
  from tp join sc on sc.code_n = tp.code_n group by 1),
ra as (
  select tp.release_product_id, count(*) anchors from tp join sm using (print_id)
  where sm.eligible and tp.release_product_id is not null group by 1),
cls as (
  select tp.*, coalesce(sm.eligible, false) mapped, sm.other_states, sf.fresh, sf.checked_at, sf.price_at,
    sf.availability, sm.all_listings, coalesce(pc.cands_code, 0) cands_code, coalesce(pc.cands_release, 0) cands_release,
    coalesce(pc.cands_unmapped, 0) cands_unmapped, pc.unmapped_proposals, pc.unmapped_kinds,
    case
      when coalesce(sf.fresh, false) then 'fresh'
      when coalesce(sm.eligible, false) and not coalesce(sf.identity_ok, false) then 'e'
      when coalesce(sm.eligible, false) and sf.planned and not sf.blocked and sf.checked_at >= now() - interval '24 hours'
        and sf.availability = 'no_listing' then 'd'
      when coalesce(sm.eligible, false) then 'c'
      when coalesce(pc.cands_unmapped, 0) > 0 or sm.other_states is not null then 'b'
      when coalesce(pc.cands_code, 0) > 0 then 'd'
      else 'a' end klass,
    case
      when coalesce(sf.fresh, false) then 'fresh'
      when coalesce(sm.eligible, false) and not coalesce(sf.identity_ok, false) then 'e_mapping_listing_identity_invalid'
      when coalesce(sm.eligible, false) then
        case when not sf.planned then 'c_no_refresh_work' when sf.blocked then 'c_quarantined'
          when sf.checked_at is null then 'c_never_checked'
          when sf.checked_at < now() - interval '24 hours' then 'c_check_older_than_24h'
          when sf.availability = 'no_listing' then 'd_mapped_no_raw_ask_24h'
          else 'c_checked_no_valid_price_24h' end
      when sm.other_states like '%not_manual_verified%' then 'b_mapping_not_manual_verified'
      when coalesce(pc.cands_unmapped, 0) > 0 then 'b_proposal:' || coalesce(pc.unmapped_proposals, 'none')
      when sm.other_states is not null then 'b_mapping:' || sm.other_states
      when coalesce(pc.cands_code, 0) > 0 then 'd_est_all_code_listings_mapped_to_siblings'
      when tp.release_product_id is null then 'a_release_uncoded'
      when ra.anchors is not null then 'a_release_has_snkrdunk_anchor'
      else 'a_release_has_no_snkrdunk_anchor' end subclass
  from tp left join sm using (print_id) left join sf using (print_id) left join pc using (print_id)
  left join ra on ra.release_product_id = tp.release_product_id), big as (select klass from cls where target and klass <> 'fresh' group by 1 order by count(*) desc limit 1),
r as (select cls.*, row_number() over (partition by klass order by md5('snk-gap-' || print_id::text)) rn
  from cls where target and klass not in ('fresh', (select klass from big)))
select cls.klass, cls.subclass, cls.code, cls.rarity, cls.variant, cls.release_code release, cls.print_kind,
  t.listing, left(t.title, 40) title, t.listing_kind, t.proposal
from r cls left join lateral (
  select sc.listing, sc.title, sc.listing_kind, sc.proposal from sc
  where sc.code_n = cls.code_n and (cls.klass <> 'b' or not sc.listing_mapped
    or sc.listing = any(string_to_array(cls.all_listings, ',')))
  order by (sc.listing = any(string_to_array(cls.all_listings, ','))) desc, (sc.listing_kind = cls.print_kind) desc,
    (sc.prop_release_id = cls.release_product_id or sc.set_n = cls.release_n) desc, sc.cand_id limit 1) t on true
where cls.rn <= 3 order by 1, 2;
