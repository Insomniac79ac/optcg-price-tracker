-- Yuyu-Tei mapped URL per print, for one fixed sample of 50 prints: the CP price checker's daily
-- sample of 13 Nov 2026 (content-pipeline cardpirate/price-checks/2026-11-13.md, section
-- "Sample rows (50 ...)", commit 22f529a), so the checker can open the Yuyu-Tei page a print's
-- headline comes from. Read-only. One statement, exactly one row per sample print (50 rows),
-- in the checker's table order (pos). Owner direction 13 Nov 2026: the result must fit the
-- 18,000-character inline summary (scripts/ops/diagnostic.py INLINE_CHARS), because bots cannot
-- fetch artifacts. To keep that bound for any data, a URL longer than 120 characters is not
-- returned (source_url null, url_chars says how long it is); observed Yuyu-Tei card URLs are
-- 44 to 50 characters (https://yuyu-tei.jp/sell/opc/card/<slug>/<id>).
-- mapping_id and source_url are the lowest-id current Yuyu-Tei mapping that prices the print
-- (active, not superseded, approved); mappings counts them (more than 1 is itself a finding;
-- 0 means no current Yuyu-Tei mapping, mapping_id and source_url null). price_at and
-- checked_at are that mapping's raw (ungraded) refresh state, or null when it has none.
-- Release code is left out (the checker's table has it) so the bound holds at the schema's
-- maximum column lengths. Changing the sample is a reviewed PR to this file.

-- sample
with s(print_id, pos) as (values
  (3867,1),(6774,2),(5930,3),(6015,4),(5057,5),(5238,6),(5715,7),(5097,8),(3214,9),(6430,10),
  (4413,11),(4907,12),(4352,13),(4267,14),(4060,15),(3854,16),(4306,17),(3300,18),(6864,19),(6955,20),
  (3132,21),(6883,22),(6021,23),(2,24),(5736,25),(5541,26),(6086,27),(5575,28),(5913,29),(5562,30),
  (5806,31),(5777,32),(5845,33),(5585,34),(5879,35),(6808,36),(5963,37),(6052,38),(6141,39),(5886,40),
  (5797,41),(5566,42),(5351,43),(5335,44),(4805,45),(6724,46),(5102,47),(4894,48),(6580,49),(3723,50)),
ys as (select id from sources where name = 'yuyutei'),
ym as (
  select m.card_print_id print_id, count(*) mappings, min(m.id) mapping_id
  from source_card_mappings m
  where m.source_id = (select id from ys) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved' and m.card_print_id in (select print_id from s)
  group by 1),
st as (
  select w.source_card_mapping_id mapping_id, string_agg(distinct ps.availability, ',') availability,
    max(ps.last_valid_price_observed_at) price_at, max(ps.last_successfully_checked_at) checked_at
  from freshness_work w join freshness_price_states ps on ps.work_id = w.id and ps.price_category = 'raw'
  where w.kind = 'refresh' and w.source_card_mapping_id in (select mapping_id from ym)
  group by 1)
select s.pos, s.print_id, c.card_code, p.official_asset_variant variant,
  coalesce(ym.mappings, 0) mappings, ym.mapping_id,
  case when length(m.source_url) <= 120 then m.source_url end source_url,
  length(m.source_url) url_chars, st.availability, st.price_at, st.checked_at
from s
left join card_prints p on p.id = s.print_id
left join canonical_cards c on c.id = p.canonical_card_id
left join ym on ym.print_id = s.print_id
left join source_card_mappings m on m.id = ym.mapping_id
left join st on st.mapping_id = ym.mapping_id
order by s.pos;
