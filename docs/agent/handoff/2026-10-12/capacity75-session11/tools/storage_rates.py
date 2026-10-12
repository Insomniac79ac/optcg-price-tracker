"""Read-only arithmetic over evidence/volume-series.json (Railway DISK_USAGE_GB, hourly).
Planning rate = 7-day average growth ending at the last sample; stress rate = worst rolling 24h
inside that 7 days. Both unit bases: s9 (x1024, kept since session 9) and Railway (x1000).
Reserve line kept from session 10: 3 GiB reserve on the 10 GB volume = room 3,123.4 MB at
3,655.3 MB (s9 basis) -> usable ceiling 6,778.7 MB (s9 basis).
usage: storage_rates.py evidence/volume-series.json > out.json"""
import json, sys, datetime as dt
pts = [(dt.datetime.fromisoformat(p['ts']), p['value']) for p in json.load(open(sys.argv[1]))['measurements']['DISK_USAGE_GB']]
by = dict(pts); last_t, last_v = pts[-1]
def at(h): return by.get(last_t - dt.timedelta(hours=h))
CEIL_S9 = 3655.3 + 3123.4
out = {'last_sample': last_t.isoformat(), 'volume_mb_s9': round(last_v * 1024, 1), 'volume_mb_railway': round(last_v * 1000, 1),
       'room_to_reserve_mb_s9': round(CEIL_S9 - last_v * 1024, 1), 'windows': {}}
for name, h in (('7d', 168), ('72h', 72), ('48h', 48), ('24h', 24)):
    v = at(h)
    out['windows'][name] = {'from': (last_t - dt.timedelta(hours=h)).isoformat(),
                            'mb_day_s9': round((last_v - v) * 1024 * 24 / h, 2), 'mb_day_railway': round((last_v - v) * 1000 * 24 / h, 2)}
worst = max(((t, by[t + dt.timedelta(hours=24)] - v) for t, v in pts
             if t >= last_t - dt.timedelta(hours=168) and t + dt.timedelta(hours=24) in by), key=lambda x: x[1])
out['worst_rolling_24h_in_7d'] = {'start': worst[0].isoformat(), 'mb_day_s9': round(worst[1] * 1024, 2), 'mb_day_railway': round(worst[1] * 1000, 2)}
daily = [(t, by[t + dt.timedelta(hours=24)] - v) for t, v in pts if t.hour == 6 and t + dt.timedelta(hours=24) in by]
out['daily_06z_growth_mb_s9'] = {t.date().isoformat(): round(g * 1024, 1) for t, g in daily}
print(json.dumps(out, indent=1))
