"""Pinned SELECT-only operational coverage and recurrence evidence."""
import json
from collections import Counter
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from psycopg.rows import dict_row
import mission_baseline as baseline
import generate_staging_state as state
from app.services.source_mapping_proposals import analyse_source_mapping_proposals, RESOLVER_VERSION

ELIGIBLE = """select m.card_print_id,s.name,w.state,w.high_interest,
 ps.last_successfully_checked_at,ps.last_valid_price_observed_at,ps.availability,
 po.price_jpy,po.promotion_state,
 (b.enabled and (b.pause_reason is null or b.paused_until<=now())) open
 from source_card_mappings m join sources s on s.id=m.source_id
 join card_prints p on p.id=m.card_print_id
 join source_dispatch_budgets b on b.source_id=s.id
 left join freshness_work w on w.source_card_mapping_id=m.id and w.kind='refresh'
 left join freshness_price_states ps on ps.work_id=w.id and ps.price_category='raw'
 left join price_observations po on po.id=ps.last_observation_id
 where m.is_active and m.superseded_at is null and m.review_status='approved'
 and p.is_active and p.verification_status='verified' and p.language='jp'
 and s.name in ('yuyutei','snkrdunk') and (s.name!='snkrdunk' or m.manual_verified)"""


def main():
    from datetime import timedelta
    engine = create_engine('postgresql+psycopg://', creator=baseline.connection, isolation_level='REPEATABLE READ')
    try:
      with Session(engine) as session:
        db = session.connection().connection.driver_connection
        def read(query):
            with db.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query)
                return cursor.fetchall()
        checks = state.guard.evaluate(state.guard.collect_facts(db), state.guard.expected_revisions_from_repo(str(state.ROOT)))
        assert all(c.ok for c in checks)
        now = read("select now() n")[0]["n"]
        rows = read(ELIGIBLE)
        mapped = {r['card_print_id'] for r in rows}
        operational = {r['card_print_id'] for r in rows if r['open'] and r['state'] != 'blocked' and r['last_successfully_checked_at'] and now-timedelta(hours=24) <= r['last_successfully_checked_at'] <= now}
        fresh = {r['card_print_id'] for r in rows if r['open'] and r['state'] != 'blocked' and r['availability']=='listed' and r['last_valid_price_observed_at'] and now-timedelta(hours=4 if r['high_interest'] else 24) <= r['last_valid_price_observed_at'] <= now and r['price_jpy'] and r['price_jpy']>0 and (r['name']!='yuyutei' or r['promotion_state']!='sale') and (r['name']!='snkrdunk' or r['price_jpy']>1000)}
        counts = {}
        for row in rows: counts.setdefault(row['card_print_id'],set()).add(row['name'])
        evidence = {'target':'staging','observed_at':now,'read_only':True,'production_accessed':False,'resolver_version':RESOLVER_VERSION,
          'coverage':{'denominator':4316,'exact_mapped':len(mapped),'operational':len(operational),'fresh_regular_usable_price':len(fresh),'dual_mapped':sum(len(names)==2 for names in counts.values()),'zero_mapped':4316-len(mapped)},
          'fresh_price_definition':'Current listed RAW state, within the unchanged applicable 24h/4h target, non-paused source, positive regular price; Yuyu sale and SNKRDUNK platform-minimum constraints excluded.'}
        evidence['attempts_since_boundary_change'] = read("""select s.name,w.kind,a.outcome,count(*) attempts,round(avg(a.actual_request_cost),2) mean_requests,max(a.actual_request_cost) max_requests,round(avg(extract(epoch from a.finished_at-a.started_at)),2) mean_runtime,max(extract(epoch from a.finished_at-a.started_at)) max_runtime from freshness_attempts a join freshness_work w on w.id=a.work_id join sources s on s.id=w.source_id where a.started_at>='2026-10-06T03:10:59Z' group by 1,2,3""")
        evidence['latest_finished_executions'] = read("""select distinct on(service) service,context_json from app_log_events where event_type='raw_execution_finished' and created_at>=now()-interval '3 hours' order by service,created_at desc,id desc""")
        evidence['budgets'] = read("""select s.name,b.enabled,b.request_limit,b.window_seconds,b.used_requests,b.reserved_requests,b.pause_reason,b.paused_until from source_dispatch_budgets b join sources s on s.id=b.source_id""")
        evidence['source_scheduled_turn_capacity'] = read("""select service,context_json::jsonb->'identity'->>'revision' revision,count(*) finished_turns,min(created_at) first_at,max(created_at) last_at,max((context_json::jsonb->'identity'->>'runtime_seconds')::numeric) max_runtime_seconds,min((context_json::jsonb->'work'->>'attempted')::int) min_attempts,max((context_json::jsonb->'work'->>'attempted')::int) max_attempts from app_log_events where event_type='raw_execution_finished' and created_at>='2026-10-06T03:45:00Z' and service like 'yuyutei-collector-shard-%' and context_json::jsonb->'work'->>'max_work'='16' group by 1,2 order by 1,2""")
        evidence['source_workload'] = read("""select s.name,count(*) eligible,count(*) filter(where w.high_interest) high_interest,count(*) filter(where w.state='blocked') blocked,count(*) filter(where w.state='claimed') claims,min(w.estimated_request_cost) min_reservation,max(w.estimated_request_cost) max_reservation from freshness_work w join sources s on s.id=w.source_id join source_card_mappings m on m.id=w.source_card_mapping_id join card_prints p on p.id=m.card_print_id where w.kind='refresh' and m.is_active and m.superseded_at is null and m.review_status='approved' and p.is_active and p.verification_status='verified' and p.language='jp' and (s.name!='snkrdunk' or m.manual_verified) group by 1""")
        evidence['latest_source_denials'] = read("""select distinct on(s.name) s.name,a.id attempt_id,w.id work_id,w.source_card_mapping_id mapping_id,w.kind,a.started_at,a.finished_at,a.actual_request_cost from freshness_attempts a join freshness_work w on w.id=a.work_id join sources s on s.id=w.source_id where a.outcome='source_denial' order by s.name,a.id desc""")
        evidence['duplicate_current_exact_print_sources'] = read("select s.name,m.card_print_id,array_agg(m.id order by m.id) mapping_ids,array_agg(m.review_status order by m.id) review_statuses from source_card_mappings m join sources s on s.id=m.source_id where m.is_active and m.superseded_at is null and m.card_print_id is not null group by s.name,m.card_print_id having count(*)>1")
        evidence['recovery_work'] = read("select id,state,last_outcome,attempt_count,last_failure,resume_cursor,claim_expires_at from freshness_work where scope_key like 'source-recovery:snkrdunk:%'")
        evidence['recovery_attempts'] = read("select a.id,a.work_id,a.outcome,a.started_at,a.finished_at,a.actual_request_cost,a.charged_request_cost,a.raw_snapshot_id from freshness_attempts a join freshness_work w on w.id=a.work_id where w.scope_key like 'source-recovery:snkrdunk:%' order by a.id")
        for raw in read("select r.id,r.http_status,r.source_url,r.raw_content from raw_snapshots r join freshness_attempts a on a.raw_snapshot_id=r.id join freshness_work w on w.id=a.work_id where w.scope_key like 'source-recovery:snkrdunk:%'"):
            from pathlib import Path
            Path(f'/tmp/raw-breakthrough-evidence/snkr-recovery-{raw["id"]}.html').write_text(raw.pop('raw_content'))
            evidence.setdefault('recovery_raw_metadata',[]).append(raw)
        analysis = analyse_source_mapping_proposals(session, build_report=False)
        exact = {a.card_print_id for p in analysis.plans if p.resolution_status=='exact' for a in p.alternatives if a.recommended}
        evidence['exact_evidence_ceiling'] = len(mapped | exact)
        evidence['new_first_source_identities_still_needed_for_60'] = max(0,2590-len(mapped | exact))
        evidence['proposal_states'] = {source:dict(Counter(p.resolution_status for p in analysis.plans if p.source_name==source)) for source in ('yuyutei','snkrdunk')}
        evidence['first_source_exact_ready_by_source'] = {source:len({a.card_print_id for p in analysis.plans if p.source_name==source and p.resolution_status=='exact' for a in p.alternatives if a.recommended}-mapped) for source in ('yuyutei','snkrdunk')}
        session.rollback()
    finally:
        engine.dispose()
    state.atomic_write(state.ROOT/'docs/agent/evidence/raw-operational-audit-2026-10-06.json',json.dumps(evidence,default=state.json_default,indent=2)+'\n')
    print(json.dumps({k:v for k,v in evidence.items() if k in ('coverage','exact_evidence_ceiling','new_first_source_identities_still_needed_for_60','proposal_states','first_source_exact_ready_by_source','latest_source_denials')},default=state.json_default))


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        detail = str(exc) if isinstance(exc, state.VerificationError) else type(exc).__name__
        raise SystemExit('Read-only operational audit refused: '+detail) from None
