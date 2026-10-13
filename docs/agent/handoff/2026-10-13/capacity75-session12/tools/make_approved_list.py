"""Approved list for scripts/yuyu_identity_capture_enqueue.py from a fresh re-plan:
the first N eligible candidates in plan order (the batch the storage fit was computed for).
Refuses if any of those N is not eligible. Prints the SHA-256 to pin.
usage: make_approved_list.py <new100-replan.json> <N> <out.json>"""
import hashlib, json, sys
replan, n, out = json.load(open(sys.argv[1])), int(sys.argv[2]), sys.argv[3]
eligible = [r for r in replan['records'] if r['eligible']]
if len(eligible) < n:
    sys.exit(f'only {len(eligible)} eligible candidates; refusing NEW{n}')
chosen = eligible[:n]
doc = {'batch': f'NEW{n}', 'expected_count': n, 'replan_observed_at': replan['observed_at'],
       'resolver_version': replan['resolver_version'],
       'entries': [{'candidate_id': r['candidate_id'], 'evidence_digest': r['evidence_digest'],
                    'release_product_id': r['release_product_id'], 'considered_print_ids': r['considered_print_ids']}
                   for r in chosen]}
data = (json.dumps(doc, indent=1) + '\n').encode()
open(out, 'wb').write(data)
print(json.dumps({'out': out, 'sha256': hashlib.sha256(data).hexdigest(), 'entries': n,
                  'official_images': sum(len(e['considered_print_ids']) for e in doc['entries'])}))
