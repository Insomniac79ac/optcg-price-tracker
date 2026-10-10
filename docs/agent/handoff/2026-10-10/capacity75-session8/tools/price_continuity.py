"""Read-only: for Yuyu/SNKR observations linked to attempts claimed in [start, end), compare each
price/stock/promotion with the same mapping's previous observation. usage: price_continuity.py <start> <end> <out.json>"""
import json, sys
sys.path.insert(0, '/workspaces/cp-s8/docs/agent/handoff/2026-10-10/capacity75-session8/tools')
from db import connection
start, end, out_path = sys.argv[1:4]
SQL = """with cur as (
  select o.id, o.source_card_mapping_id m, o.price_type, o.price_jpy, o.stock_status, o.promotion_state, o.observed_at, s.name
  from freshness_attempts a join price_observations o on o.raw_snapshot_id=a.raw_snapshot_id join sources s on s.id=o.source_id
  where a.claimed_at >= %s::timestamptz and a.claimed_at < %s::timestamptz)
select c.*, p.price_jpy prev_price, p.stock_status prev_stock, p.promotion_state prev_promo, p.observed_at prev_at
from cur c left join lateral (select * from price_observations q where q.source_card_mapping_id=c.m and q.price_type=c.price_type
  and q.observed_at < c.observed_at order by q.observed_at desc limit 1) p on true order by c.id"""
with connection() as db:
    rows = db.execute(SQL, (start, end)).fetchall(); db.rollback()
summary = {'observations': len(rows), 'with_previous': sum(r['prev_price'] is not None for r in rows),
           'identical_price': sum(r['prev_price'] == r['price_jpy'] for r in rows),
           'identical_price_stock_promo': sum((r['prev_price'], r['prev_stock'], r['prev_promo']) == (r['price_jpy'], r['stock_status'], r['promotion_state']) for r in rows),
           'changed': [{k: r[k] for k in ('m', 'price_type', 'prev_price', 'price_jpy', 'prev_stock', 'stock_status', 'prev_at', 'observed_at')} for r in rows if r['prev_price'] != r['price_jpy']]}
json.dump({'window': [start, end], 'read_only': True, 'summary': summary, 'rows': rows}, open(out_path, 'w'), indent=1, default=str)
print(json.dumps(summary, indent=1, default=str))
