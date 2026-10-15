"""Read-only: why SNKRDUNK health and raw_due_work are DEGRADED. Same eligibility as
app.services.operational_health_sql.ELIGIBLE, split by work state, with block timing.
usage: degraded_signals.py > out.json"""
import json, sys
sys.path[:0] = ['/workspaces/cp-cap13/services/api', '/workspaces/cp-cap13/docs/agent/handoff/2026-10-15/capacity75-session13/tools']
from app.services.operational_health_sql import ELIGIBLE
from db import connection
Q = {
 'now': "select now() at time zone 'utc' t",
 'by_source_state': f"""with e as ({ELIGIBLE}) select source, coalesce(state,'unplanned') state, count(*) n,
   count(*) filter (where checked_at is null or checked_at < now()-interval '24 hours') overdue,
   count(*) filter (where checked_at is null) never_checked,
   count(*) filter (where checked_at < now()-interval '24 hours') over_24h,
   count(*) filter (where retry_not_before_at > now()) backoff
   from e group by 1,2 order by 1,2""",
 'snkr_blocked_timing': f"""with e as ({ELIGIBLE}) select count(*) n, min(w.updated_at) first_blocked_update, max(w.updated_at) last_blocked_update,
   min(w.last_failure_at) min_failure_at, max(w.last_failure_at) max_failure_at, min(e.checked_at) oldest_success, max(e.checked_at) newest_success
   from e join freshness_work w on w.id=e.work_id where e.source='snkrdunk' and e.state='blocked'""",
 'snkr_blocked_failure_class': f"""with e as ({ELIGIBLE}) select w.last_outcome, left(regexp_replace(coalesce(w.last_failure,''),'[0-9]+','N','g'),60) failure_class, count(*) n
   from e join freshness_work w on w.id=e.work_id where e.state='blocked' group by 1,2 order by 3 desc""",
 'snkr_overdue_not_blocked': f"""with e as ({ELIGIBLE}) select count(*) n from e where source='snkrdunk' and coalesce(state,'')<>'blocked'
   and (checked_at is null or checked_at < now()-interval '24 hours')""",
 'snkr_validation_blocked': """select w.kind, w.state, count(*) n, min(w.updated_at), max(w.updated_at) from freshness_work w join sources s on s.id=w.source_id
   where s.name='snkrdunk' and w.kind='validation' group by 1,2""",
 'yuyu_overdue': f"""with e as ({ELIGIBLE}) select coalesce(state,'unplanned') state, count(*) n from e where source='yuyutei'
   and (checked_at is null or checked_at < now()-interval '24 hours') group by 1""",
}
out = {}
with connection() as db:
    for k, sql in Q.items():
        try: out[k] = db.execute(sql).fetchall()
        except Exception as e: db.rollback(); out[k] = {'error': str(e).splitlines()[0]}
    db.rollback()
print(json.dumps(out, indent=1, default=str))
