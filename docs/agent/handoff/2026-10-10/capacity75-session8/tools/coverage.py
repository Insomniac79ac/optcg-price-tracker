"""Pinned SELECT-only consistent coverage and current due-work capacity."""
import json
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import generate_staging_state as state
import mission_baseline as baseline
from mission_operational_audit import ELIGIBLE

engine = create_engine('postgresql+psycopg://', creator=baseline.connection,
                       isolation_level='REPEATABLE READ')
try:
    with Session(engine) as session:
        now = session.scalar(text('select now()'))
        denominator = session.scalar(text("select count(*) from card_prints where is_active and verification_status='verified' and language='jp'"))
        assert denominator == 4316
        rows = session.execute(text(ELIGIBLE)).mappings().all()
        mapped = {r['card_print_id'] for r in rows}
        operational = {r['card_print_id'] for r in rows if r['open'] and r['state'] != 'blocked'
                       and r['last_successfully_checked_at']
                       and now - timedelta(hours=24) <= r['last_successfully_checked_at'] <= now}
        fresh = {r['card_print_id'] for r in rows if r['open'] and r['state'] != 'blocked'
                 and r['availability'] == 'listed' and r['last_valid_price_observed_at']
                 and now - timedelta(hours=4 if r['high_interest'] else 24) <= r['last_valid_price_observed_at'] <= now
                 and r['price_jpy'] and r['price_jpy'] > 0
                 and (r['name'] != 'yuyutei' or r['promotion_state'] != 'sale')
                 and (r['name'] != 'snkrdunk' or r['price_jpy'] > 1000)}
        duplicates = session.scalar(text("select count(*) from (select source_id,card_print_id from source_card_mappings where is_active and superseded_at is null and card_print_id is not null group by 1,2 having count(*)>1) d"))
        assert duplicates == 0
        workload = session.execute(text("""select s.name,w.kind,count(*) total,
            count(*) filter(where w.state='blocked') blocked,
            count(*) filter(where w.state='claimed') claimed,
            count(*) filter(where w.state='claimed' and w.claim_expires_at<now()) expired_claims,
            count(*) filter(where w.state='pending' and w.next_due_at<=now()) due,
            min(w.next_due_at) filter(where w.state='pending' and w.next_due_at<=now()) oldest_due
            from freshness_work w join sources s on s.id=w.source_id group by 1,2 order by 1,2""")).mappings().all()
        result = {'target': 'staging', 'observed_at': now, 'read_only': True,
                  'production_accessed': False, 'source_requests': 0, 'database_writes': 0,
                  'coverage': {'denominator': denominator, 'exact_mapped': len(mapped),
                               'operational': len(operational), 'fresh_regular_usable_price': len(fresh),
                               'dual_mapped':sum(len({r['name'] for r in rows if r['card_print_id']==i})==2 for i in mapped),
                               'zero_mapped':denominator-len(mapped),
                               'change_from2630_operational':len(operational)-2630,
                               'remaining_to75':max(0,3237-len(operational))},
                  'duplicate_exact_print_source_groups': duplicates,
                  'existing_open_nonblocked_checks_older_than_24h': len({r['card_print_id'] for r in rows
                      if r['open'] and r['state'] != 'blocked' and r['last_successfully_checked_at']
                      and r['last_successfully_checked_at'] < now - timedelta(hours=24)}),
                  'open_nonblocked_without_first_success': len({r['card_print_id'] for r in rows
                      if r['open'] and r['state'] != 'blocked' and not r['last_successfully_checked_at']}),
                  'workload': [dict(r) for r in workload]}
        session.rollback()
finally:
    engine.dispose()
output = Path(__file__).parent/'coverage-latest.json'
state.atomic_write(output, json.dumps(result, default=state.json_default, indent=2) + '\n')
print(json.dumps(result, default=state.json_default))
