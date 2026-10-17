-- F1 sizing (owner decision 2026-10-17): how many ambiguous prints a two-way-unique rule over
-- stored Yuyu-Tei listing evidence would match. Read-only; writes no rule and no proposal.
-- Target: verified prints with no approved Yuyu mapping whose same-release Yuyu listings include
-- an unmapped ambiguous/pending one and no queued capture intent (the D9 class
-- b_proposal:ambiguous/pending). Listing kind: parallel when the name carries パラレル or the
-- rarity token starts with P-; special for SP/TR tokens; plain otherwise; unknown with no token.
-- Print kind: special for SPカード/SP P/TR; plain for base and r<N>; parallel for p<N>.
-- strict_match: in the card's release exactly one listing and exactly one print of that kind,
-- counting mapped ones too. unmapped_match: exactly one of each among the unmapped ones (weaker:
-- it relies on the existing mappings being right). Same normalisation as yuyu-coverage-gap.

-- summary
with ys as (select id from sources where name = 'yuyutei'),
pr as (
  select p.id print_id, c.card_code code, upper(replace(replace(replace(c.card_code, '-', ''), '_', ''), ' ', '')) code_n, rp.official_code release_code,
    upper(replace(replace(replace(rp.official_code, '-', ''), '_', ''), ' ', '')) release_n, p.official_asset_variant variant, p.treatment,
    coalesce(nullif(p.official_rarity, ''), c.rarity, '?') rarity,
    case when p.official_rarity in ('SPカード', 'SP P', 'TR') then 'special'
      when p.official_asset_variant = 'base' or p.official_asset_variant like 'r%' then 'plain'
      when p.official_asset_variant like 'p%' then 'parallel' else 'unknown' end kind,
    exists (select 1 from source_card_mappings m where m.card_print_id = p.id and m.source_id = (select id from ys)
      and m.is_active and m.superseded_at is null and m.review_status = 'approved') mapped
  from card_prints p join canonical_cards c on c.id = p.canonical_card_id
  left join release_products rp on rp.id = p.release_product_id
  where p.is_active and p.verification_status = 'verified'),
ml as (
  select distinct m.canonical_source_listing_identity listing from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null and m.review_status = 'approved'),
pg as (
  select distinct on (g.source_candidate_id) g.source_candidate_id cand_id, g.resolution_status || '/' || g.review_status proposal
  from source_mapping_proposal_groups g
  where g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null
  order by g.source_candidate_id, g.id desc),
iw as (
  select distinct w.resume_cursor::jsonb ->> 'candidate_id' cand_key from freshness_work w
  where w.kind = 'discovery' and w.source_id = (select id from ys) and w.resume_cursor is not null
    and w.resume_cursor::jsonb ->> 'candidate_id' is not null),
yc as (
  select y.id cand_id, upper(replace(replace(replace(y.detected_card_code, '-', ''), '_', ''), ' ', '')) code_n, upper(replace(replace(replace(y.set_slug, '-', ''), '_', ''), ' ', '')) slug_n, y.name_jp, y.detected_rarity,
    substring(y.name_jp from '[(（]([^()（）]*)[)）]') annotation, ml.listing is not null listing_mapped,
    coalesce(pg.proposal, 'none') proposal, iw.cand_key is not null has_intent,
    case when y.detected_rarity is null then 'unknown'
      when y.detected_rarity in ('SP', 'TR') then 'special'
      when y.name_jp like '%パラレル%' or y.detected_rarity like 'P-%' then 'parallel'
      else 'plain' end kind
  from yuyutei_candidates y
  left join ml on ml.listing = lower(y.set_slug) || ':' || y.product_id
  left join pg on pg.cand_id = y.id
  left join iw on iw.cand_key = y.id::text
  where y.detected_card_code is not null),
fam as (
  select pr.code_n, pr.release_n, pr.kind, count(*) prints_all, count(*) filter (where not pr.mapped) prints_unmapped
  from pr where pr.release_n is not null group by 1, 2, 3),
fl as (
  select yc.code_n, yc.slug_n release_n, yc.kind, count(*) listings_all,
    count(*) filter (where not yc.listing_mapped) listings_unmapped
  from yc group by 1, 2, 3),
target as (
  select pr.* from pr
  where not pr.mapped and exists (select 1 from yc where yc.code_n = pr.code_n and yc.slug_n = pr.release_n
      and not yc.listing_mapped and yc.proposal = 'ambiguous/pending')
    and not exists (select 1 from yc where yc.code_n = pr.code_n and yc.slug_n = pr.release_n
      and not yc.listing_mapped and yc.has_intent)),
tm as (
  select t.*, coalesce(f.prints_all, 0) prints_all, coalesce(f.prints_unmapped, 0) prints_unmapped,
    coalesce(l.listings_all, 0) listings_all, coalesce(l.listings_unmapped, 0) listings_unmapped,
    t.kind in ('plain', 'parallel') and f.prints_all = 1 and l.listings_all = 1 strict_match,
    t.kind in ('plain', 'parallel') and f.prints_unmapped = 1 and l.listings_unmapped = 1 unmapped_match
  from target t left join fam f on f.code_n = t.code_n and f.release_n = t.release_n and f.kind = t.kind
  left join fl l on l.code_n = t.code_n and l.release_n = t.release_n and l.kind = t.kind)
select kind, count(*) target_prints, count(*) filter (where strict_match) strict_match,
  count(*) filter (where unmapped_match) unmapped_match
from tm group by 1 order by 1;

-- by_release
with ys as (select id from sources where name = 'yuyutei'),
pr as (
  select p.id print_id, c.card_code code, upper(replace(replace(replace(c.card_code, '-', ''), '_', ''), ' ', '')) code_n, rp.official_code release_code,
    upper(replace(replace(replace(rp.official_code, '-', ''), '_', ''), ' ', '')) release_n, p.official_asset_variant variant, p.treatment,
    coalesce(nullif(p.official_rarity, ''), c.rarity, '?') rarity,
    case when p.official_rarity in ('SPカード', 'SP P', 'TR') then 'special'
      when p.official_asset_variant = 'base' or p.official_asset_variant like 'r%' then 'plain'
      when p.official_asset_variant like 'p%' then 'parallel' else 'unknown' end kind,
    exists (select 1 from source_card_mappings m where m.card_print_id = p.id and m.source_id = (select id from ys)
      and m.is_active and m.superseded_at is null and m.review_status = 'approved') mapped
  from card_prints p join canonical_cards c on c.id = p.canonical_card_id
  left join release_products rp on rp.id = p.release_product_id
  where p.is_active and p.verification_status = 'verified'),
ml as (
  select distinct m.canonical_source_listing_identity listing from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null and m.review_status = 'approved'),
pg as (
  select distinct on (g.source_candidate_id) g.source_candidate_id cand_id, g.resolution_status || '/' || g.review_status proposal
  from source_mapping_proposal_groups g
  where g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null
  order by g.source_candidate_id, g.id desc),
iw as (
  select distinct w.resume_cursor::jsonb ->> 'candidate_id' cand_key from freshness_work w
  where w.kind = 'discovery' and w.source_id = (select id from ys) and w.resume_cursor is not null
    and w.resume_cursor::jsonb ->> 'candidate_id' is not null),
yc as (
  select y.id cand_id, upper(replace(replace(replace(y.detected_card_code, '-', ''), '_', ''), ' ', '')) code_n, upper(replace(replace(replace(y.set_slug, '-', ''), '_', ''), ' ', '')) slug_n, y.name_jp, y.detected_rarity,
    substring(y.name_jp from '[(（]([^()（）]*)[)）]') annotation, ml.listing is not null listing_mapped,
    coalesce(pg.proposal, 'none') proposal, iw.cand_key is not null has_intent,
    case when y.detected_rarity is null then 'unknown'
      when y.detected_rarity in ('SP', 'TR') then 'special'
      when y.name_jp like '%パラレル%' or y.detected_rarity like 'P-%' then 'parallel'
      else 'plain' end kind
  from yuyutei_candidates y
  left join ml on ml.listing = lower(y.set_slug) || ':' || y.product_id
  left join pg on pg.cand_id = y.id
  left join iw on iw.cand_key = y.id::text
  where y.detected_card_code is not null),
fam as (
  select pr.code_n, pr.release_n, pr.kind, count(*) prints_all, count(*) filter (where not pr.mapped) prints_unmapped
  from pr where pr.release_n is not null group by 1, 2, 3),
fl as (
  select yc.code_n, yc.slug_n release_n, yc.kind, count(*) listings_all,
    count(*) filter (where not yc.listing_mapped) listings_unmapped
  from yc group by 1, 2, 3),
target as (
  select pr.* from pr
  where not pr.mapped and exists (select 1 from yc where yc.code_n = pr.code_n and yc.slug_n = pr.release_n
      and not yc.listing_mapped and yc.proposal = 'ambiguous/pending')
    and not exists (select 1 from yc where yc.code_n = pr.code_n and yc.slug_n = pr.release_n
      and not yc.listing_mapped and yc.has_intent)),
tm as (
  select t.*, coalesce(f.prints_all, 0) prints_all, coalesce(f.prints_unmapped, 0) prints_unmapped,
    coalesce(l.listings_all, 0) listings_all, coalesce(l.listings_unmapped, 0) listings_unmapped,
    t.kind in ('plain', 'parallel') and f.prints_all = 1 and l.listings_all = 1 strict_match,
    t.kind in ('plain', 'parallel') and f.prints_unmapped = 1 and l.listings_unmapped = 1 unmapped_match
  from target t left join fam f on f.code_n = t.code_n and f.release_n = t.release_n and f.kind = t.kind
  left join fl l on l.code_n = t.code_n and l.release_n = t.release_n and l.kind = t.kind)
select release_code, count(*) target_prints, count(*) filter (where strict_match) strict_match,
  count(*) filter (where unmapped_match) unmapped_match
from tm group by 1 order by 1;

-- by_rarity
with ys as (select id from sources where name = 'yuyutei'),
pr as (
  select p.id print_id, c.card_code code, upper(replace(replace(replace(c.card_code, '-', ''), '_', ''), ' ', '')) code_n, rp.official_code release_code,
    upper(replace(replace(replace(rp.official_code, '-', ''), '_', ''), ' ', '')) release_n, p.official_asset_variant variant, p.treatment,
    coalesce(nullif(p.official_rarity, ''), c.rarity, '?') rarity,
    case when p.official_rarity in ('SPカード', 'SP P', 'TR') then 'special'
      when p.official_asset_variant = 'base' or p.official_asset_variant like 'r%' then 'plain'
      when p.official_asset_variant like 'p%' then 'parallel' else 'unknown' end kind,
    exists (select 1 from source_card_mappings m where m.card_print_id = p.id and m.source_id = (select id from ys)
      and m.is_active and m.superseded_at is null and m.review_status = 'approved') mapped
  from card_prints p join canonical_cards c on c.id = p.canonical_card_id
  left join release_products rp on rp.id = p.release_product_id
  where p.is_active and p.verification_status = 'verified'),
ml as (
  select distinct m.canonical_source_listing_identity listing from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null and m.review_status = 'approved'),
pg as (
  select distinct on (g.source_candidate_id) g.source_candidate_id cand_id, g.resolution_status || '/' || g.review_status proposal
  from source_mapping_proposal_groups g
  where g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null
  order by g.source_candidate_id, g.id desc),
iw as (
  select distinct w.resume_cursor::jsonb ->> 'candidate_id' cand_key from freshness_work w
  where w.kind = 'discovery' and w.source_id = (select id from ys) and w.resume_cursor is not null
    and w.resume_cursor::jsonb ->> 'candidate_id' is not null),
yc as (
  select y.id cand_id, upper(replace(replace(replace(y.detected_card_code, '-', ''), '_', ''), ' ', '')) code_n, upper(replace(replace(replace(y.set_slug, '-', ''), '_', ''), ' ', '')) slug_n, y.name_jp, y.detected_rarity,
    substring(y.name_jp from '[(（]([^()（）]*)[)）]') annotation, ml.listing is not null listing_mapped,
    coalesce(pg.proposal, 'none') proposal, iw.cand_key is not null has_intent,
    case when y.detected_rarity is null then 'unknown'
      when y.detected_rarity in ('SP', 'TR') then 'special'
      when y.name_jp like '%パラレル%' or y.detected_rarity like 'P-%' then 'parallel'
      else 'plain' end kind
  from yuyutei_candidates y
  left join ml on ml.listing = lower(y.set_slug) || ':' || y.product_id
  left join pg on pg.cand_id = y.id
  left join iw on iw.cand_key = y.id::text
  where y.detected_card_code is not null),
fam as (
  select pr.code_n, pr.release_n, pr.kind, count(*) prints_all, count(*) filter (where not pr.mapped) prints_unmapped
  from pr where pr.release_n is not null group by 1, 2, 3),
fl as (
  select yc.code_n, yc.slug_n release_n, yc.kind, count(*) listings_all,
    count(*) filter (where not yc.listing_mapped) listings_unmapped
  from yc group by 1, 2, 3),
target as (
  select pr.* from pr
  where not pr.mapped and exists (select 1 from yc where yc.code_n = pr.code_n and yc.slug_n = pr.release_n
      and not yc.listing_mapped and yc.proposal = 'ambiguous/pending')
    and not exists (select 1 from yc where yc.code_n = pr.code_n and yc.slug_n = pr.release_n
      and not yc.listing_mapped and yc.has_intent)),
tm as (
  select t.*, coalesce(f.prints_all, 0) prints_all, coalesce(f.prints_unmapped, 0) prints_unmapped,
    coalesce(l.listings_all, 0) listings_all, coalesce(l.listings_unmapped, 0) listings_unmapped,
    t.kind in ('plain', 'parallel') and f.prints_all = 1 and l.listings_all = 1 strict_match,
    t.kind in ('plain', 'parallel') and f.prints_unmapped = 1 and l.listings_unmapped = 1 unmapped_match
  from target t left join fam f on f.code_n = t.code_n and f.release_n = t.release_n and f.kind = t.kind
  left join fl l on l.code_n = t.code_n and l.release_n = t.release_n and l.kind = t.kind)
select rarity, kind, count(*) target_prints, count(*) filter (where strict_match) strict_match,
  count(*) filter (where unmapped_match) unmapped_match
from tm group by 1, 2 order by 1, 2;

-- unmatched_shapes
with ys as (select id from sources where name = 'yuyutei'),
pr as (
  select p.id print_id, c.card_code code, upper(replace(replace(replace(c.card_code, '-', ''), '_', ''), ' ', '')) code_n, rp.official_code release_code,
    upper(replace(replace(replace(rp.official_code, '-', ''), '_', ''), ' ', '')) release_n, p.official_asset_variant variant, p.treatment,
    coalesce(nullif(p.official_rarity, ''), c.rarity, '?') rarity,
    case when p.official_rarity in ('SPカード', 'SP P', 'TR') then 'special'
      when p.official_asset_variant = 'base' or p.official_asset_variant like 'r%' then 'plain'
      when p.official_asset_variant like 'p%' then 'parallel' else 'unknown' end kind,
    exists (select 1 from source_card_mappings m where m.card_print_id = p.id and m.source_id = (select id from ys)
      and m.is_active and m.superseded_at is null and m.review_status = 'approved') mapped
  from card_prints p join canonical_cards c on c.id = p.canonical_card_id
  left join release_products rp on rp.id = p.release_product_id
  where p.is_active and p.verification_status = 'verified'),
ml as (
  select distinct m.canonical_source_listing_identity listing from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null and m.review_status = 'approved'),
pg as (
  select distinct on (g.source_candidate_id) g.source_candidate_id cand_id, g.resolution_status || '/' || g.review_status proposal
  from source_mapping_proposal_groups g
  where g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null
  order by g.source_candidate_id, g.id desc),
iw as (
  select distinct w.resume_cursor::jsonb ->> 'candidate_id' cand_key from freshness_work w
  where w.kind = 'discovery' and w.source_id = (select id from ys) and w.resume_cursor is not null
    and w.resume_cursor::jsonb ->> 'candidate_id' is not null),
yc as (
  select y.id cand_id, upper(replace(replace(replace(y.detected_card_code, '-', ''), '_', ''), ' ', '')) code_n, upper(replace(replace(replace(y.set_slug, '-', ''), '_', ''), ' ', '')) slug_n, y.name_jp, y.detected_rarity,
    substring(y.name_jp from '[(（]([^()（）]*)[)）]') annotation, ml.listing is not null listing_mapped,
    coalesce(pg.proposal, 'none') proposal, iw.cand_key is not null has_intent,
    case when y.detected_rarity is null then 'unknown'
      when y.detected_rarity in ('SP', 'TR') then 'special'
      when y.name_jp like '%パラレル%' or y.detected_rarity like 'P-%' then 'parallel'
      else 'plain' end kind
  from yuyutei_candidates y
  left join ml on ml.listing = lower(y.set_slug) || ':' || y.product_id
  left join pg on pg.cand_id = y.id
  left join iw on iw.cand_key = y.id::text
  where y.detected_card_code is not null),
fam as (
  select pr.code_n, pr.release_n, pr.kind, count(*) prints_all, count(*) filter (where not pr.mapped) prints_unmapped
  from pr where pr.release_n is not null group by 1, 2, 3),
fl as (
  select yc.code_n, yc.slug_n release_n, yc.kind, count(*) listings_all,
    count(*) filter (where not yc.listing_mapped) listings_unmapped
  from yc group by 1, 2, 3),
target as (
  select pr.* from pr
  where not pr.mapped and exists (select 1 from yc where yc.code_n = pr.code_n and yc.slug_n = pr.release_n
      and not yc.listing_mapped and yc.proposal = 'ambiguous/pending')
    and not exists (select 1 from yc where yc.code_n = pr.code_n and yc.slug_n = pr.release_n
      and not yc.listing_mapped and yc.has_intent)),
tm as (
  select t.*, coalesce(f.prints_all, 0) prints_all, coalesce(f.prints_unmapped, 0) prints_unmapped,
    coalesce(l.listings_all, 0) listings_all, coalesce(l.listings_unmapped, 0) listings_unmapped,
    t.kind in ('plain', 'parallel') and f.prints_all = 1 and l.listings_all = 1 strict_match,
    t.kind in ('plain', 'parallel') and f.prints_unmapped = 1 and l.listings_unmapped = 1 unmapped_match
  from target t left join fam f on f.code_n = t.code_n and f.release_n = t.release_n and f.kind = t.kind
  left join fl l on l.code_n = t.code_n and l.release_n = t.release_n and l.kind = t.kind)
select kind, prints_unmapped, listings_unmapped, prints_all, listings_all, count(*) prints
from tm where not unmapped_match group by 1, 2, 3, 4, 5 order by 6 desc limit 25;

-- samples
with ys as (select id from sources where name = 'yuyutei'),
pr as (
  select p.id print_id, c.card_code code, upper(replace(replace(replace(c.card_code, '-', ''), '_', ''), ' ', '')) code_n, rp.official_code release_code,
    upper(replace(replace(replace(rp.official_code, '-', ''), '_', ''), ' ', '')) release_n, p.official_asset_variant variant, p.treatment,
    coalesce(nullif(p.official_rarity, ''), c.rarity, '?') rarity,
    case when p.official_rarity in ('SPカード', 'SP P', 'TR') then 'special'
      when p.official_asset_variant = 'base' or p.official_asset_variant like 'r%' then 'plain'
      when p.official_asset_variant like 'p%' then 'parallel' else 'unknown' end kind,
    exists (select 1 from source_card_mappings m where m.card_print_id = p.id and m.source_id = (select id from ys)
      and m.is_active and m.superseded_at is null and m.review_status = 'approved') mapped
  from card_prints p join canonical_cards c on c.id = p.canonical_card_id
  left join release_products rp on rp.id = p.release_product_id
  where p.is_active and p.verification_status = 'verified'),
ml as (
  select distinct m.canonical_source_listing_identity listing from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null and m.review_status = 'approved'),
pg as (
  select distinct on (g.source_candidate_id) g.source_candidate_id cand_id, g.resolution_status || '/' || g.review_status proposal
  from source_mapping_proposal_groups g
  where g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null
  order by g.source_candidate_id, g.id desc),
iw as (
  select distinct w.resume_cursor::jsonb ->> 'candidate_id' cand_key from freshness_work w
  where w.kind = 'discovery' and w.source_id = (select id from ys) and w.resume_cursor is not null
    and w.resume_cursor::jsonb ->> 'candidate_id' is not null),
yc as (
  select y.id cand_id, upper(replace(replace(replace(y.detected_card_code, '-', ''), '_', ''), ' ', '')) code_n, upper(replace(replace(replace(y.set_slug, '-', ''), '_', ''), ' ', '')) slug_n, y.name_jp, y.detected_rarity,
    substring(y.name_jp from '[(（]([^()（）]*)[)）]') annotation, ml.listing is not null listing_mapped,
    coalesce(pg.proposal, 'none') proposal, iw.cand_key is not null has_intent,
    case when y.detected_rarity is null then 'unknown'
      when y.detected_rarity in ('SP', 'TR') then 'special'
      when y.name_jp like '%パラレル%' or y.detected_rarity like 'P-%' then 'parallel'
      else 'plain' end kind
  from yuyutei_candidates y
  left join ml on ml.listing = lower(y.set_slug) || ':' || y.product_id
  left join pg on pg.cand_id = y.id
  left join iw on iw.cand_key = y.id::text
  where y.detected_card_code is not null),
fam as (
  select pr.code_n, pr.release_n, pr.kind, count(*) prints_all, count(*) filter (where not pr.mapped) prints_unmapped
  from pr where pr.release_n is not null group by 1, 2, 3),
fl as (
  select yc.code_n, yc.slug_n release_n, yc.kind, count(*) listings_all,
    count(*) filter (where not yc.listing_mapped) listings_unmapped
  from yc group by 1, 2, 3),
target as (
  select pr.* from pr
  where not pr.mapped and exists (select 1 from yc where yc.code_n = pr.code_n and yc.slug_n = pr.release_n
      and not yc.listing_mapped and yc.proposal = 'ambiguous/pending')
    and not exists (select 1 from yc where yc.code_n = pr.code_n and yc.slug_n = pr.release_n
      and not yc.listing_mapped and yc.has_intent)),
tm as (
  select t.*, coalesce(f.prints_all, 0) prints_all, coalesce(f.prints_unmapped, 0) prints_unmapped,
    coalesce(l.listings_all, 0) listings_all, coalesce(l.listings_unmapped, 0) listings_unmapped,
    t.kind in ('plain', 'parallel') and f.prints_all = 1 and l.listings_all = 1 strict_match,
    t.kind in ('plain', 'parallel') and f.prints_unmapped = 1 and l.listings_unmapped = 1 unmapped_match
  from target t left join fam f on f.code_n = t.code_n and f.release_n = t.release_n and f.kind = t.kind
  left join fl l on l.code_n = t.code_n and l.release_n = t.release_n and l.kind = t.kind)
select t.code, t.release_code, yc.name_jp listing_title, yc.annotation, yc.detected_rarity rarity_token,
  t.variant proposed_variant, t.rarity proposed_rarity, t.treatment, t.strict_match, yc.cand_id
from tm t join yc on yc.code_n = t.code_n and yc.slug_n = t.release_n and yc.kind = t.kind and not yc.listing_mapped
where t.unmapped_match
order by md5(yc.cand_id::text || ':d9-f1') limit 20;
