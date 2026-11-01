-- SNKRDUNK ambiguous proposals by listing kind, read-only (owner 2026-11-01, revised step 2 part 1).
-- Measures how many current pending ambiguous SNKRDUNK proposal groups a listing-kind rule (Yuyu-Tei
-- F1's uniqueness test) could resolve from the title alone, before any rule is built. Listing kind
-- from the stored candidate: special (コミパラ, SP/SPC, スーパーパラレル, 手配書 tokens), parallel (parsed
-- treatment or a "-P" token or パラレル), plain (any other titled card code). Print kind as
-- print_listing_kind: foil treatment, special official rarity (SPカード, SP P, TR), plain (base, rN),
-- parallel (pN). same_kind = alternatives whose kind equals the listing's: 1 would resolve.
-- overview
with g as (
  select distinct on (source_candidate_id) id, source_candidate_id
  from source_mapping_proposal_groups
  where source_candidate_type = 'snkrdunk_candidate' and superseded_at is null
    and review_status = 'pending' and resolution_status = 'ambiguous'
  order by source_candidate_id, id desc),
lk as (
  select g.id gid, c.id cid,
    case
      when c.title ~ '(コミパラ|スーパーパラレル|SPC|-SP[^A-Z]|-SP$|手配書)' then 'special'
      when c.detected_variant ~* 'parallel' or c.title ~ '[A-Z]-P[^A-Z]' or c.title ~ 'パラレル' then 'parallel'
      when c.detected_card_code is not null then 'plain'
    end kind
  from g join snkrdunk_candidates c on c.id = g.source_candidate_id),
pk as (
  select a.proposal_group_id gid, a.card_print_id,
    case
      when coalesce(p.treatment, '') ~* '(foil|フォイル)' then 'foil'
      when p.official_rarity in ('SPカード', 'SP P', 'TR') then 'special'
      when coalesce(p.official_asset_variant, '') ~ '^(base|r[1-9][0-9]*)$' then 'plain'
      when coalesce(p.official_asset_variant, '') ~ '^p[1-9][0-9]*$' then 'parallel'
    end kind
  from source_mapping_proposal_alternatives a join card_prints p on p.id = a.card_print_id
  where a.proposal_group_id in (select id from g)),
s as (
  select lk.gid, lk.kind listing_kind,
    count(*) filter (where pk.kind = lk.kind) same_kind,
    count(*) filter (where pk.kind is null) unknown_print_kind,
    count(*) alternatives
  from lk join pk on pk.gid = lk.gid group by 1, 2)
select coalesce(listing_kind, 'unknown') listing_kind,
  case when listing_kind is null or unknown_print_kind > 0 then 'undecidable'
       when same_kind = 1 then 'would_resolve'
       when same_kind = 0 then 'no_print_of_that_kind'
       else 'same_kind_siblings_need_review' end outcome,
  count(*) groups, sum(alternatives) alternatives
from s group by 1, 2 order by 1, 2;

-- sample
with g as (
  select distinct on (source_candidate_id) id, source_candidate_id
  from source_mapping_proposal_groups
  where source_candidate_type = 'snkrdunk_candidate' and superseded_at is null
    and review_status = 'pending' and resolution_status = 'ambiguous'
  order by source_candidate_id, id desc)
select c.id cid, left(c.title, 90) title, c.detected_rarity rarity, c.detected_variant variant,
  (select string_agg(p.id || ':' || coalesce(p.official_asset_variant, '?') || ':'
       || coalesce(p.official_rarity, '?'), ' ' order by p.id)
     from source_mapping_proposal_alternatives a join card_prints p on p.id = a.card_print_id
     where a.proposal_group_id = g.id) prints
from g join snkrdunk_candidates c on c.id = g.source_candidate_id
order by c.id limit 60;
