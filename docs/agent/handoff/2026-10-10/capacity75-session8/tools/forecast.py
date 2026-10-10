"""Offline arithmetic over session-7 evidence. No network, no database."""
import json
from datetime import datetime
E = 'evidence/'
c = json.load(open(E + 'census.json'))
a = json.load(open(E + 'attribution.json'))
pre = {'volume_mb': 3477.6769626112, 'volume_at': '2026-10-08T13:43:29Z', 'db': 2641794751, 'raw': 2492243968, 'db_at': '2026-10-08T13:43:25Z'}
s7a = {'volume_mb': 3568.06, 'db': 2709567167, 'raw': 2555740160, 'at': '2026-10-08T22:12:37Z'}
t = lambda s: datetime.fromisoformat(s.replace('Z', '+00:00'))
vol = c['volume']['volumes'][0]; vol_at = c['volume']['observed_at']
now = a['now']
days = lambda a0, a1: (t(a1) - t(a0)).total_seconds() / 86400
rates = {
  'volume_24h_mb_day': (vol['current_mb'] - pre['volume_mb']) / days(pre['volume_at'], vol_at),
  'db_24h_mb_day': (now['db_bytes'] - pre['db']) / 1e6 / days(pre['db_at'], now['now'].replace(' ', 'T')),
  'raw_24h_mb_day': (now['raw_total'] - pre['raw']) / 1e6 / days(pre['db_at'], now['now'].replace(' ', 'T')),
  'volume_since_7a_mb_day': (vol['current_mb'] - s7a['volume_mb']) / days(s7a['at'], vol_at),
  'db_since_7a_mb_day': (now['db_bytes'] - s7a['db']) / 1e6 / days(s7a['at'], now['now'].replace(' ', 'T')),
  'raw_since_7a_mb_day': (now['raw_total'] - s7a['raw']) / 1e6 / days(s7a['at'], now['now'].replace(' ', 'T')),
}
LIMIT, RESERVE, NEW100 = vol['limit_mb'], 3 * 1024**3 / 1e6, 887045884 / 1e6
room = LIMIT - RESERVE - vol['current_mb']
out = {'inputs': {'volume_now_mb': vol['current_mb'], 'volume_at': vol_at, 'limit_mb': LIMIT, 'reserve_mb_3GiB': RESERVE,
                  'new100_image_bound_mb': NEW100, 'pre_activation': pre, 'session7a': s7a},
       'rates_mb_per_day': {k: round(v, 1) for k, v in rates.items()}, 'room_to_reserve_mb': round(room, 1), 'scenarios': {}}
for name, r in (('conservative_full_24h_volume', rates['volume_24h_mb_day']), ('steady_since_7a_db', rates['db_since_7a_mb_day'])):
    out['scenarios'][name] = {
      'rate_mb_day': round(r, 1),
      'days_to_reserve': round(room / r, 1), 'days_to_full': round((LIMIT - vol['current_mb']) / r, 1),
      'volume_30d_mb': round(vol['current_mb'] + 30 * r), 'volume_90d_mb': round(vol['current_mb'] + 90 * r),
      'need_30d_incl_reserve_mb': round(vol['current_mb'] + 30 * r + RESERVE), 'need_90d_incl_reserve_mb': round(vol['current_mb'] + 90 * r + RESERVE),
      'new100_days_to_reserve': round((room - NEW100) / r, 1),
      'new100_need_30d_incl_reserve_mb_all_snkr': round(vol['current_mb'] + NEW100 + 30 * (r + 6.9) + RESERVE),
      'new100_need_90d_incl_reserve_mb_all_snkr': round(vol['current_mb'] + NEW100 + 90 * (r + 6.9) + RESERVE),
    }
out['new100_recurring_assumption'] = 'all-SNKR worst case +6.9 MB/day stored (100 x (65 KB homepage delta + 4 KB item delta), measured per-row averages); all-Yuyu +0.2 MB/day'
json.dump(out, open(E + 'forecast.json', 'w'), indent=1)
print(json.dumps(out, indent=1))
