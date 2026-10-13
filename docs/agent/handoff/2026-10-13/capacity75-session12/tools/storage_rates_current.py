"""Read-only arithmetic: storage rates over current collector code only (owner decision
2026-10-12): samples strictly after the a852244 rollout (2026-10-10T14:31:00.430268Z,
PR #98 receipt completed_at) up to the last sample. Requires >= 72 h.
Planning rate = average daily growth over that window; stress rate = worst rolling 24 h
inside it. Units: s9 basis (GB x 1024) as since session 9; reserve line from session 10:
usable ceiling 6,778.7 MB (s9) = 3 GiB reserve on the 10 GB volume.
usage: storage_rates_current.py evidence/volume-series-5min.json > out.json"""
import json, sys, datetime as dt
START = dt.datetime(2026, 10, 10, 14, 31, 0, 430268, tzinfo=dt.timezone.utc)
CEIL_S9 = 3655.3 + 3123.4
pts = [(dt.datetime.fromisoformat(p['ts']), p['value']) for p in json.load(open(sys.argv[1]))['measurements']['DISK_USAGE_GB']]
pts = [(t, v) for t, v in pts if t > START and v is not None]
(t0, v0), (t1, v1) = pts[0], pts[-1]
hours = (t1 - t0).total_seconds() / 3600
out = {'window': {'rollout_completed_at': START.isoformat(), 'first_sample': t0.isoformat(), 'last_sample': t1.isoformat(),
                  'hours': round(hours, 2), 'samples': len(pts), 'meets_72h': hours >= 72},
       'volume_mb_s9': round(v1 * 1024, 1), 'room_to_reserve_mb_s9': round(CEIL_S9 - v1 * 1024, 1)}
out['planning_mb_day_s9'] = round((v1 - v0) * 1024 * 24 / hours, 2)
by = dict(pts)
rolling = [(t, by[t + dt.timedelta(hours=24)] - v) for t, v in pts if t + dt.timedelta(hours=24) in by]
worst = max(rolling, key=lambda x: x[1]); best = min(rolling, key=lambda x: x[1])
out['stress_worst_rolling_24h'] = {'start': worst[0].isoformat(), 'mb_day_s9': round(worst[1] * 1024, 2), 'windows_compared': len(rolling)}
out['context_min_rolling_24h_mb_s9'] = round(best[1] * 1024, 2)
out['last_24h_mb_s9'] = round((v1 - by[t1 - dt.timedelta(hours=24)]) * 1024, 2) if t1 - dt.timedelta(hours=24) in by else None
out['daily_from_rollout_mb_s9'] = {}
t = t0
while t + dt.timedelta(hours=24) <= t1:
    out['daily_from_rollout_mb_s9'][t.isoformat()] = round((by[t + dt.timedelta(hours=24)] - by[t]) * 1024, 1); t += dt.timedelta(hours=24)
for name, rate in (('planning', out['planning_mb_day_s9']), ('stress', out['stress_worst_rolling_24h']['mb_day_s9'])):
    out[f'runway_days_no_batch_{name}'] = round(out['room_to_reserve_mb_s9'] / rate, 1) if rate > 0 else None
print(json.dumps(out, indent=1))
