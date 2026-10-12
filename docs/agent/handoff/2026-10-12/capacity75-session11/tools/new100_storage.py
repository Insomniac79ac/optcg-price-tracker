"""Arithmetic only (no DB, no source): 90-day storage fit for NEW100 / NEW50 / NEW25.

Inputs (all files in this session's evidence/):
- storage-rates.json: planning rate (7-day average) and stress rate (worst rolling 24h in 7 days),
  room to the 3 GiB reserve (s9 basis);
- new100-replan.json: eligible candidates in plan order and their official sibling counts;
- identity-capture-sizes.txt figures (re-measured, unchanged since 2026-10-06): per stored image
  635,067 B Yuyu / 291,299 B official, product page 37,082 B avg and 37,456 B max;
- recurring cost per refresh capture: 24h volume growth / 24h attempts (overstates per capture).
Batch N = the first N eligible candidates of the re-plan.
Need over 90 days = base_rate x 90 + one_off(N) + recurring(N) x 90; fits if need <= room.
usage: new100_storage.py <24h-attempts> > out.json
"""
import json, sys, math
E = '/workspaces/cp-s11/docs/agent/handoff/2026-10-12/capacity75-session11/evidence/'
rates = json.load(open(E + 'storage-rates.json'))
replan = json.load(open(E + 'new100-replan.json'))
attempts_24h = int(sys.argv[1])
MB = 1_000_000  # session-10 convention for byte -> MB in the NEW100 figures (887,045,884 B = 887.0 MB)
B64_BOUND = math.ceil(2 * 1024 * 1024 / 3) * 4 + 2048  # base64 of MAX_IMAGE_BYTES (2 MiB) + 2 KB, as session 10
YUYU_AVG, OFFICIAL_AVG, PAGE_AVG, PAGE_MAX = 635_067, 291_299, 37_082, 37_456
PAGES_PER_FAMILY = 2  # the 2026-10-07 plan: 100 families -> 200 HTML pages
room = rates['room_to_reserve_mb_s9']
recurring_per_capture_mb = rates['windows']['24h']['mb_day_s9'] / attempts_24h
eligible = [r for r in replan['records'] if r['eligible']]

def batch(n):
    fam = eligible[:n]
    official = sum(len(r['considered_print_ids']) for r in fam)
    images = n + official
    return {'families': n, 'yuyu_images': n, 'official_images': official,
            'one_off_hard_bound_mb': round((images * B64_BOUND + n * PAGES_PER_FAMILY * PAGE_MAX) / MB, 1),
            'one_off_estimate_mb': round((n * YUYU_AVG + official * OFFICIAL_AVG + n * PAGES_PER_FAMILY * PAGE_AVG) / MB, 1),
            'recurring_mb_day': round(n * recurring_per_capture_mb, 3)}

out = {'room_to_reserve_mb_s9': room, 'recurring_mb_per_capture': round(recurring_per_capture_mb, 5),
       'attempts_24h': attempts_24h, 'b64_bound_bytes_per_image': B64_BOUND, 'batches': {}, 'rates': {}}
RATES = {'planning_7d_avg': rates['windows']['7d']['mb_day_s9'],
         'stress_worst_rolling_24h': rates['worst_rolling_24h_in_7d']['mb_day_s9'],
         # context only, NOT decision rates:
         'context_72h': rates['windows']['72h']['mb_day_s9'], 'context_48h': rates['windows']['48h']['mb_day_s9'],
         'context_24h': rates['windows']['24h']['mb_day_s9'], 'context_s10_24h_CF': 18.83, 'context_s10_worst_CF': 34.18}
for n in (100, 50, 25):
    out['batches'][f'NEW{n}'] = batch(n)
for rname, rate in RATES.items():
    base = rate * 90
    row = {'mb_day': rate, 'base_90d_mb': round(base, 1), 'runway_days_no_batch': round(room / rate, 1) if rate > 0 else None, 'fit': {}}
    for bname, b in out['batches'].items():
        for basis in ('one_off_hard_bound_mb', 'one_off_estimate_mb'):
            need = base + b[basis] + b['recurring_mb_day'] * 90
            row['fit'][f'{bname}:{basis.split("_")[2]}'] = {'need_mb': round(need, 1), 'margin_mb': round(room - need, 1), 'fits': need <= room}
    row['largest_fitting_hard_bound'] = next((b for b in ('NEW100', 'NEW50', 'NEW25') if row['fit'][f'{b}:hard']['fits']), None)
    out['rates'][rname] = row
print(json.dumps(out, indent=1))
