"""Read-only: every raw refresh item behind deadline_compliance not_met (never successfully
checked, or last successful check older than 24 h), with card, mapping, work state, age,
since-when and failure class. Same population as the state generator's freshness query.
usage: freshness_detail.py > out.json"""
import json, sys
sys.path.insert(0, '/workspaces/cp-cap12/docs/agent/handoff/2026-10-13/capacity75-session12/tools')
from db import connection
DETAIL = """select s.name source, w.id work_id, w.state work_state, m.id mapping_id, m.is_active, m.review_status,
  m.manual_verified, m.superseded_at is not null superseded, p.id card_print_id, c.card_code, p.official_asset_variant,
  ps.last_successfully_checked_at, round(extract(epoch from now()-ps.last_successfully_checked_at)/3600) age_hours,
  ps.last_valid_price_observed_at, ps.availability, w.last_outcome,
  left(regexp_replace(coalesce(w.last_failure,''),'[0-9]+','N','g'),70) failure_class, w.last_failure_at, w.updated_at
 from freshness_price_states ps join freshness_work w on w.id=ps.work_id join sources s on s.id=w.source_id
 left join source_card_mappings m on m.id=w.source_card_mapping_id left join card_prints p on p.id=m.card_print_id
 left join canonical_cards c on c.id=p.canonical_card_id
 where ps.price_category='raw' and w.kind='refresh'
 and (ps.last_successfully_checked_at is null or ps.last_successfully_checked_at < now()-interval '24 hours')
 order by 1, ps.last_successfully_checked_at nulls first"""
Q = {
 'now': "select now() at time zone 'utc' t",
 'summary': f"""select source, work_state, is_active, review_status, failure_class, count(*) n,
   count(*) filter (where last_successfully_checked_at is null) never_checked,
   min(age_hours) min_age_h, max(age_hours) max_age_h, min(coalesce(last_failure_at, updated_at)) since_min,
   max(coalesce(last_failure_at, updated_at)) since_max from ({DETAIL}) d group by 1,2,3,4,5 order by 1,6 desc""",
 'not_blocked_deficit': f"select count(*) n from ({DETAIL}) d where work_state <> 'blocked'",
 'within_target_nonblocked': """select s.name, count(*) n, max(round(extract(epoch from now()-ps.last_successfully_checked_at)/3600,1)) max_age_h
   from freshness_price_states ps join freshness_work w on w.id=ps.work_id join sources s on s.id=w.source_id
   where ps.price_category='raw' and w.kind='refresh' and w.state<>'blocked' group by 1""",
 'detail': DETAIL,
}
out = {}
with connection() as db:
    for k, sql in Q.items():
        try: out[k] = db.execute(sql).fetchall()
        except Exception as e: db.rollback(); out[k] = {'error': str(e).splitlines()[0]}
    db.rollback()
print(json.dumps(out, indent=1, default=str, ensure_ascii=False))
