-- Yuyu identity-capture work (scope yuyu-identity:<candidate>:...) written by the #116 enqueue
-- tool: totals by state, the newest 100 work items with their state and attempt outcomes, and
-- outcome totals for the last 24 h, so capture progress, denials and transient failures are
-- readable from the summary. Older items (500+ on staging) stay out of the summary budget.
-- states
select w.state, count(*) n, min(w.id) min_work_id, max(w.id) max_work_id,
  count(*) filter (where w.attempt_count = 0) never_attempted
from freshness_work w join sources s on s.id = w.source_id
where s.name = 'yuyutei' and w.scope_key like 'yuyu-identity:%'
group by 1 order by 1;

-- review_pack
with ys as (select id from sources where name = 'yuyutei'),
cap as (
  select w.id work_id, w.resume_cursor::jsonb c
  from freshness_work w
  where w.source_id = (select id from ys) and w.kind = 'discovery' and w.scope_key like 'yuyu-identity:%'
    and w.attempt_count = 1 and w.last_outcome = 'completed'
    and w.resume_cursor::jsonb ? 'source_image_snapshot_id'),
g as (
  select distinct on (source_candidate_id) source_candidate_id, resolution_status, review_status, evidence_digest
  from source_mapping_proposal_groups
  where source_candidate_type = 'yuyutei_candidate' and superseded_at is null
  order by source_candidate_id, id desc)
select (cap.c ->> 'candidate_id')::int cand, cap.work_id work, y.set_slug || '/' || y.product_id listing,
  y.detected_card_code code, (cap.c ->> 'release_product_id')::int rp, coalesce((cap.c ->> 'version')::int, 1) v,
  cap.c ->> 'evidence_digest' digest, left(nullif(g.evidence_digest, cap.c ->> 'evidence_digest'), 12) moved,
  (cap.c ->> 'source_product_snapshot_id')::int psnap, ps.content_hash phash,
  (cap.c ->> 'source_image_snapshot_id')::int isnap,
  left(substring(left(isn.raw_content, 200) from '"body_sha256":"([0-9a-f]{64})"'), 12) isha,
  (select string_agg((o ->> 'card_print_id') || ':' || (o ->> 'raw_snapshot_id') || ':'
       || coalesce(cp.official_asset_variant, '?') || ':' || left(coalesce(cp.artwork_key, ''), 12), ' '
       order by (o ->> 'card_print_id')::int)
     from jsonb_array_elements(cap.c -> 'official_images') o
     left join card_prints cp on cp.id = (o ->> 'card_print_id')::int) official
from cap
join yuyutei_candidates y on y.id = (cap.c ->> 'candidate_id')::int
join g on g.source_candidate_id = y.id and g.resolution_status = 'ambiguous' and g.review_status = 'pending'
left join raw_snapshots ps on ps.id = (cap.c ->> 'source_product_snapshot_id')::int
left join raw_snapshots isn on isn.id = (cap.c ->> 'source_image_snapshot_id')::int
order by 1, 2 limit 40;

-- latest_work
select w.id work_id, split_part(w.scope_key, ':', 2) candidate_id, w.state, w.attempt_count,
  w.last_outcome, w.last_attempted_at,
  count(a.id) filter (where a.outcome = 'source_denial') denials,
  count(a.id) filter (where a.outcome = 'transient_failure') transient_failures
from freshness_work w join sources s on s.id = w.source_id
left join freshness_attempts a on a.work_id = w.id
where s.name = 'yuyutei' and w.scope_key like 'yuyu-identity:%'
group by w.id order by w.id desc limit 100;

-- outcomes_24h
select a.outcome, count(*) n, count(distinct a.work_id) work_items, max(a.finished_at) last_finished
from freshness_attempts a join freshness_work w on w.id = a.work_id join sources s on s.id = w.source_id
where s.name = 'yuyutei' and w.scope_key like 'yuyu-identity:%' and a.started_at > now() - interval '24 hours'
group by 1 order by 1;
