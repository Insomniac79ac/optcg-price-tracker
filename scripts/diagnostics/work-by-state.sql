-- Freshness work by source, kind and state, with due, expired-claim and blocked counts.
-- work
select s.name source, w.kind, w.state, count(*) n,
  count(*) filter (where w.state = 'pending' and w.next_due_at <= now()) due_now,
  min(w.next_due_at) filter (where w.state = 'pending' and w.next_due_at <= now()) oldest_due,
  count(*) filter (where w.state = 'claimed' and w.claim_expires_at < now()) expired_claims,
  min(w.updated_at) filter (where w.state = 'blocked') oldest_blocked_update
from freshness_work w join sources s on s.id = w.source_id
group by 1, 2, 3 order by 1, 2, 3;

-- attempts_24h
select s.name source, w.kind, a.outcome, count(*) n, sum(a.actual_request_cost) requests
from freshness_attempts a join freshness_work w on w.id = a.work_id join sources s on s.id = w.source_id
where a.started_at > now() - interval '24 hours'
group by 1, 2, 3 order by 1, 2, 4 desc;
