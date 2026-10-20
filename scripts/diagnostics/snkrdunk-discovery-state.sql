-- SNKRDUNK discovery state, read-only. Owner task (2026-10-19): why discovery stopped.
-- intents: every SNKRDUNK discovery work item (published `snkr-published:` scopes and any other)
-- with its bounds and recorded result. attempts: their attempts. legacy_runs: the older
-- snkrdunk_discovery_runs path by status. anchors_by_release: approved, manually verified
-- SNKRDUNK mappings (the only anchors published discovery accepts) per release, with stored
-- candidates whose stored set code names that release. budget: the SNKRDUNK dispatch budget.
-- intents
select w.id, w.scope_key, w.state, w.last_outcome, w.attempt_count, w.next_due_at, w.updated_at,
  json_array_length(coalesce(w.resume_cursor -> 'anchor_mapping_ids', '[]'::json)) anchors,
  w.resume_cursor ->> 'radius_start' radius_start, w.resume_cursor ->> 'radius_end' radius_end,
  w.resume_cursor ->> 'max_products' max_products, w.resume_cursor ->> 'published_urls_observed' published_urls,
  json_array_length(coalesce(w.resume_cursor -> 'inspected_identities', '[]'::json)) inspected,
  json_array_length(coalesce(w.resume_cursor -> 'new_candidate_ids', '[]'::json)) new_candidates,
  left(w.last_failure, 80) last_failure
from freshness_work w join sources s on s.id = w.source_id
where s.name = 'snkrdunk' and w.kind = 'discovery' order by w.id;

-- attempts
select w.id work_id, a.claimed_at, a.finished_at, a.outcome, a.actual_request_cost
from freshness_attempts a join freshness_work w on w.id = a.work_id join sources s on s.id = w.source_id
where s.name = 'snkrdunk' and w.kind = 'discovery' order by a.id;

-- legacy_runs
select status, count(*) n, min(started_at) first_started, max(finished_at) last_finished,
  sum(candidates_found) found
from snkrdunk_discovery_runs group by 1 order by 1;

-- anchors_by_release
with ss as (select id from sources where name = 'snkrdunk'),
an as (
  select coalesce(rp.official_code, '?') release, count(distinct m.canonical_source_listing_identity) anchors
  from source_card_mappings m join card_prints p on p.id = m.card_print_id
  left join release_products rp on rp.id = p.release_product_id
  where m.source_id = (select id from ss) and m.is_active and m.superseded_at is null
    and m.review_status = 'approved' and m.manual_verified
  group by 1),
cd as (
  select upper(replace(replace(replace(detected_set_code, '-', ''), '_', ''), ' ', '')) set_n, count(*) candidates
  from snkrdunk_candidates group by 1),
pr as (
  select coalesce(rp.official_code, '?') release, upper(replace(replace(replace(rp.official_code, '-', ''), '_', ''), ' ', '')) release_n,
    count(*) prints
  from card_prints p left join release_products rp on rp.id = p.release_product_id
  where p.is_active and p.verification_status = 'verified' group by 1, 2)
select coalesce(pr.release, an.release, '?') release, coalesce(pr.prints, 0) verified_prints,
  coalesce(an.anchors, 0) anchors, coalesce(cd.candidates, 0) candidates
from pr full join an on an.release = pr.release
left join cd on cd.set_n = pr.release_n
order by 1;

-- budget
select b.enabled, b.request_limit, b.window_seconds, b.window_started_at, b.used_requests, b.reserved_requests,
  b.paused_until, b.pause_reason
from source_dispatch_budgets b join sources s on s.id = b.source_id where s.name = 'snkrdunk';
