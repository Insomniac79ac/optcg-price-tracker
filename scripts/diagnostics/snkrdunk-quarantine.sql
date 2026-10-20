-- Quarantined (blocked) SNKRDUNK freshness work, one row per item, for owner review. Read-only.
-- Owner task (2026-10-19). reasons: every distinct block reason (digits folded to N) with counts by
-- kind. items: each blocked refresh item with its print, listing, reason key (first 48 characters
-- of the folded reason) and whether the print is a high-rarity target (all but base C, UC, R and
-- SR, as in snkrdunk-coverage-gap). validation: blocked validation work, which prices nothing.
-- reasons
select w.kind, left(regexp_replace(coalesce(w.last_failure, ''), '[0-9]+', 'N', 'g'), 240) reason,
  w.last_outcome, count(*) n, min(coalesce(w.last_failure_at, w.updated_at))::date since_min,
  max(coalesce(w.last_failure_at, w.updated_at))::date since_max
from freshness_work w join sources s on s.id = w.source_id
where s.name = 'snkrdunk' and w.state = 'blocked'
group by 1, 2, 3 order by 1, 4 desc;

-- items
select w.id work_id, m.id mapping_id, c.card_code code,
  coalesce(nullif(p.official_rarity, ''), c.rarity, '?') rarity, p.official_asset_variant variant,
  rp.official_code release, not (coalesce(nullif(p.official_rarity, ''), c.rarity, '?') in ('C', 'UC', 'R', 'SR')
    and coalesce(p.official_asset_variant, '') not like 'p%') target,
  m.canonical_source_listing_identity listing,
  left(regexp_replace(coalesce(w.last_failure, ''), '[0-9]+', 'N', 'g'), 48) reason_key,
  coalesce(w.last_failure_at, w.updated_at)::date since,
  (select max(ps.last_successfully_checked_at) from freshness_price_states ps
    where ps.work_id = w.id and ps.price_category = 'raw')::date raw_checked
from freshness_work w join sources s on s.id = w.source_id
left join source_card_mappings m on m.id = w.source_card_mapping_id
left join card_prints p on p.id = coalesce(w.card_print_id, m.card_print_id)
left join canonical_cards c on c.id = p.canonical_card_id
left join release_products rp on rp.id = p.release_product_id
where s.name = 'snkrdunk' and w.state = 'blocked' and w.kind = 'refresh'
order by reason_key, c.card_code, w.id;

-- validation
select w.id work_id, w.scope_key, left(regexp_replace(coalesce(w.last_failure, ''), '[0-9]+', 'N', 'g'), 60) reason,
  coalesce(w.last_failure_at, w.updated_at)::date since
from freshness_work w join sources s on s.id = w.source_id
where s.name = 'snkrdunk' and w.state = 'blocked' and w.kind = 'validation'
order by w.id;
