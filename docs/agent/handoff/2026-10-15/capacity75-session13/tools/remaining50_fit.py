"""Arithmetic only (no DB, no source): 90-day storage fit of the remaining 50 on NEW50's MEASURED costs.

Owner decision 2026-10-14: strict rule (fit at BOTH planning and stress), one-off from NEW50's real
measured costs instead of the image hard bound.
- One-off: NEW50 per-unit stored bytes (new50-evidence.json: product page, Yuyu image, official image)
  applied to the remaining 50's unit counts (new100-replan.json eligible records), converted to the
  volume (s9) basis with NEW50's measured physical/logical ratio (volume step / stored bytes).
- Recurring: captures are parked after capture (next_due 2126), so 0 MB/day while unmapped; the
  session-12 0.45 MB/day for 50 is kept as a conservative allowance for later refresh.
- Base rates: storage-rates-ex-new50.json (planning; stress A as observed; stress B settled).
Need = rate x 90 + one_off + recurring x 90; fits if need <= room.
usage: remaining50_fit.py > out.json
"""
import json
E = '/workspaces/cp-cap13/docs/agent/handoff/2026-10-15/capacity75-session13/evidence/'
ev = json.load(open(E + 'new50-evidence.json'))['summary']
rp = json.load(open(E + 'new100-replan.json'))
rt = json.load(open(E + 'storage-rates-ex-new50.json'))
HORIZON, RECURRING = 90, 0.45
b = ev['stored_bytes']
unit = {'product_html': b['product_html'] / ev['work_rows'], 'yuyu_image': b['yuyu_image'] / ev['yuyu_images'],
        'official_image': b['official_image'] / ev['official_images']}
el = [r for r in rp['records'] if r['eligible']]
counts = {'product_html': len(el), 'yuyu_image': len(el), 'official_image': sum(len(r['considered_print_ids']) for r in el)}
logical = sum(unit[k] * counts[k] for k in unit)
ratio = rt['new50_step']['mb_s9'] / (b['total'] / 1_000_000)  # s9 MB of volume per stored MB
one_off = logical / 1_000_000 * ratio
room = rt['room_to_reserve_mb_s9']
out = {'unit_stored_bytes': {k: round(v) for k, v in unit.items()}, 'remaining50_counts': counts,
       'one_off_stored_mb': round(logical / 1_000_000, 2), 'physical_per_stored_ratio': round(ratio, 3),
       'one_off_mb_s9': round(one_off, 1), 'recurring_mb_day_allowance': RECURRING, 'room_to_reserve_mb_s9': room,
       'horizon_days': HORIZON, 'rates': {}}
for name, rate in (('planning', rt['planning_mb_day_s9']), ('stress_A_as_observed', rt['stress_A_as_observed']['mb_day_s9']),
                   ('stress_B_settled', rt['stress_B_settled']['mb_day_s9'])):
    need = rate * HORIZON + one_off + RECURRING * HORIZON
    out['rates'][name] = {'mb_day': rate, 'need_mb': round(need, 1), 'margin_mb': round(room - need, 1), 'fits': need <= room,
                          'margin_no_batch_mb': round(room - rate * HORIZON, 1),
                          'runway_days_with_batch': round((room - one_off) / (rate + RECURRING), 1)}
out['fits_planning_and_stress_A'] = out['rates']['planning']['fits'] and out['rates']['stress_A_as_observed']['fits']
out['fits_planning_and_stress_B'] = out['rates']['planning']['fits'] and out['rates']['stress_B_settled']['fits']
print(json.dumps(out, indent=1))
