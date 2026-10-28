-- Market Value publication vs today's catalogue (owner 2026-10-28, plan A: freeze each day's membership). Read-only.
-- The nightly market-index-snapshot run aborts market value with "persisted publication history conflicts with
-- deterministic replay" because the replay checks every published day against ONE digest of today's catalogue
-- (app.services.market_value_provenance.membership_revision). published: what is stored, per membership revision.
-- reconstruction: the digest of today's active/verified/jp/release catalogue restricted to prints created by the
-- last publication; equal to the stored revision proves the legacy membership can be rebuilt exactly.
-- changed_since: prints touched after the last publication. scope_drift: per release, stored count (latest day)
-- vs rebuilt vs today, only where they differ. coded_since: coded releases created or edited since.
-- published
select p.membership_revision, count(*) points, count(distinct p.point_date) dates,
  count(distinct coalesce(p.release_product_id, 0)) scopes, min(p.point_date) first_date, max(p.point_date) last_date,
  max(p.created_at) last_written
from market_value_points p group by 1 order by last_date;

-- reconstruction
with t as (select max(created_at) at from market_value_points),
cand as (
  select cp.id, cp.release_product_id from card_prints cp, t
  where cp.is_active and cp.verification_status = 'verified' and cp.language = 'jp'
    and cp.release_product_id is not null and cp.created_at <= t.at),
now_set as (
  select cp.id, cp.release_product_id from card_prints cp
  where cp.is_active and cp.verification_status = 'verified' and cp.language = 'jp'
    and cp.release_product_id is not null)
select (select at from t) last_publication,
  (select count(*) from cand) rebuilt_count,
  'current-corrected-card-print-release-v1:' || encode(sha256(convert_to(
    (select string_agg(id::text || ':' || release_product_id::text, E'\n' order by id) from cand), 'UTF8')), 'hex')
    rebuilt_revision,
  (select count(*) from now_set) current_count,
  'current-corrected-card-print-release-v1:' || encode(sha256(convert_to(
    (select string_agg(id::text || ':' || release_product_id::text, E'\n' order by id) from now_set), 'UTF8')), 'hex')
    current_revision,
  (select p.total_physical_print_count from market_value_points p
    where p.scope_kind = 'overall' order by p.point_date desc limit 1) stored_overall_count,
  (select p.membership_revision from market_value_points p order by p.point_date desc limit 1) stored_revision;

-- changed_since
with t as (select max(created_at) at from market_value_points)
select (cp.created_at > t.at) created_after, cp.is_active, cp.verification_status, cp.language,
  rp.official_code, rp.source_series_id, count(*) n, min(cp.updated_at) first_touch, max(cp.updated_at) last_touch
from card_prints cp cross join t left join release_products rp on rp.id = cp.release_product_id
where cp.updated_at > t.at or cp.created_at > t.at
group by 1, 2, 3, 4, 5, 6 order by n desc limit 80;

-- scope_drift
with t as (select max(created_at) at from market_value_points),
last_day as (select max(point_date) d from market_value_points),
stored as (
  select p.release_product_id, p.total_physical_print_count n from market_value_points p, last_day
  where p.scope_kind = 'release' and p.point_date = last_day.d),
rebuilt as (
  select cp.release_product_id, count(*) n from card_prints cp, t
  where cp.is_active and cp.verification_status = 'verified' and cp.language = 'jp'
    and cp.release_product_id is not null and cp.created_at <= t.at group by 1),
today as (
  select cp.release_product_id, count(*) n from card_prints cp
  where cp.is_active and cp.verification_status = 'verified' and cp.language = 'jp'
    and cp.release_product_id is not null group by 1),
coded as (
  select id, official_code from release_products
  where source_catalogue = 'bandai_jp' and official_code is not null and verification_status = 'verified')
select coalesce(s.release_product_id, c.id) release_product_id, c.official_code, s.n stored, r.n rebuilt, d.n today
from stored s full outer join coded c on c.id = s.release_product_id
left join rebuilt r on r.release_product_id = coalesce(s.release_product_id, c.id)
left join today d on d.release_product_id = coalesce(s.release_product_id, c.id)
where (s.n is null and d.n is not null) or s.n is distinct from r.n or s.n is distinct from d.n
order by 2 limit 80;

-- coded_since
with t as (select max(created_at) at from market_value_points)
select rp.id, rp.official_code, rp.source_catalogue, rp.verification_status, rp.created_at, rp.updated_at
from release_products rp cross join t
where rp.official_code is not null and (rp.created_at > t.at or rp.updated_at > t.at)
order by rp.updated_at desc limit 40;
