"""Read-only arithmetic: current-code storage rates with the NEW50 one-off removed.

Same window and definitions as storage_rates_current.py (samples strictly after the a852244
rollout; planning = average daily growth; stress = worst rolling 24 h; s9 basis; same reserve
line). The batch one-off is not base growth: counting it in the base rate would charge NEW50's
one-off once more per day of the horizon. So the single 5-minute step that contains the NEW50
captures (2026-10-13 16:11:42-16:23:28Z, new50-evidence.json) is removed from every sample after
it. Two stress variants are reported, nothing is dropped silently:
- A (as observed): every sample, including the 2026-10-14 04Z transient that recovered the next hour;
- B (settled): the same with that transient's samples excluded (only windows ending/starting on it).
usage: storage_rates_ex_batch.py evidence/volume-series-5min.json > out.json
"""
import json, sys, datetime as dt
UTC = dt.timezone.utc
START = dt.datetime(2026, 10, 10, 14, 31, 0, 430268, tzinfo=UTC)
CEIL_S9 = 3655.3 + 3123.4
CAPTURE = (dt.datetime(2026, 10, 13, 16, 5, tzinfo=UTC), dt.datetime(2026, 10, 13, 16, 30, tzinfo=UTC))
pts = [(dt.datetime.fromisoformat(p['ts']), p['value'] * 1024) for p in json.load(open(sys.argv[1]))['measurements']['DISK_USAGE_GB']]
pts = [(t, v) for t, v in pts if t > START and v is not None]
# The NEW50 step: the whole rise across the capture window (16:05Z sample before the first
# capture to the 16:30Z sample after the last), spread over the samples it actually rose in.
raw = dict(pts)
step_mb = raw[CAPTURE[1]] - raw[CAPTURE[0]]
step_at = CAPTURE[0]
adj = [(t, v - (min(v, raw[CAPTURE[1]]) - raw[CAPTURE[0]] if t > CAPTURE[0] else 0.0)) for t, v in pts]
# The transient: samples on 2026-10-14 04:10-05:10Z more than 5 MB above the settled line
# (linear between the 04:05Z and 05:15Z samples).
by = dict(adj)
a0, a1 = dt.datetime(2026, 10, 14, 4, 5, tzinfo=UTC), dt.datetime(2026, 10, 14, 5, 15, tzinfo=UTC)
def settled(t):
    return by[a0] + (by[a1] - by[a0]) * (t - a0).total_seconds() / (a1 - a0).total_seconds()
transient = [t for t, v in adj if a0 < t < a1 and v - settled(t) > 5]
peak = max(((t, by[t] - settled(t)) for t in transient), key=lambda x: x[1]) if transient else None
(t0, v0), (t1, v1) = adj[0], adj[-1]
hours = (t1 - t0).total_seconds() / 3600

def worst(points):
    d = dict(points)
    roll = [(t, d[t + dt.timedelta(hours=24)] - v) for t, v in points if t + dt.timedelta(hours=24) in d]
    w = max(roll, key=lambda x: x[1])
    return {'start': w[0].isoformat(), 'mb_day_s9': round(w[1], 2), 'windows_compared': len(roll)}

room = round(CEIL_S9 - pts[-1][1], 1)
out = {'window': {'first_sample': t0.isoformat(), 'last_sample': t1.isoformat(), 'hours': round(hours, 2), 'samples': len(adj)},
       'volume_mb_s9': round(pts[-1][1], 1), 'room_to_reserve_mb_s9': room,
       'new50_step': {'from': CAPTURE[0].isoformat(), 'to': CAPTURE[1].isoformat(), 'mb_s9': round(step_mb, 1)},
       'transient_2026_10_14_04z': {'samples': len(transient), 'peak_above_settled_mb': round(peak[1], 1) if peak else 0,
                                    'peak_at': peak[0].isoformat() if peak else None},
       'planning_mb_day_s9': round((v1 - v0) * 24 / hours, 2),
       'stress_A_as_observed': worst(adj),
       'stress_B_settled': worst([(t, v) for t, v in adj if t not in transient])}
d = dict(adj)
out['last_24h_mb_s9'] = round(v1 - d[t1 - dt.timedelta(hours=24)], 2) if t1 - dt.timedelta(hours=24) in d else None
for name, rate in (('planning', out['planning_mb_day_s9']), ('stress_A', out['stress_A_as_observed']['mb_day_s9']),
                   ('stress_B', out['stress_B_settled']['mb_day_s9'])):
    out[f'runway_days_no_batch_{name}'] = round(room / rate, 1)
print(json.dumps(out, indent=1))
