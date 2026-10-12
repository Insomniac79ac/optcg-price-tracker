"""Read-only: for every registry proof, does the capture cursor's stored evidence summary
hash (resolver 1.2 rule) to the proof's baseline digest? This is the precondition for the
1.3 legacy bridge. usage: proof_bridge_check.py <repo-root> > out.json"""
import json, sys, hashlib
sys.path.insert(0, '/workspaces/cp-s10/docs/agent/handoff/2026-10-11/capacity75-session10/tools')
from db import connection
root = sys.argv[1]
proofs = json.load(open(root + '/services/api/app/services/evidence/positive_physical_artwork.json'))['proofs']
def d12(e): return hashlib.sha256(json.dumps(e, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
ids = [p['work_id'] for p in proofs]
with connection() as db:
    rows = {r['id']: r for r in db.execute("select id, scope_key, resume_cursor from freshness_work where id = any(%s)", (ids,)).fetchall()}
    approved = db.execute("""select count(*) n from source_mapping_proposal_groups where superseded_at is null and source_id=1
        and review_status='approved' and resolution_status='exact' and evidence_summary_json::jsonb ? 'positive_physical_artwork_proof'""").fetchone()['n']
    db.rollback()
out = {'proofs': len(proofs), 'approved_exact_with_proof_current': approved, 'cursor_found': 0, 'cursor_digest_eq_baseline': 0,
       'legacy_digest_of_stored_summary_eq_baseline': 0, 'stored_summary_has_run_id': 0, 'failures': []}
for p in proofs:
    w = rows.get(p['work_id'])
    if not w: out['failures'].append({'candidate': p['source_candidate_id'], 'why': 'no work'}); continue
    out['cursor_found'] += 1
    c = w['resume_cursor'] or {}
    s = c.get('evidence_summary')
    out['cursor_digest_eq_baseline'] += c.get('evidence_digest') == p['baseline_evidence_digest']
    ok = isinstance(s, dict) and d12(s) == p['baseline_evidence_digest']
    out['legacy_digest_of_stored_summary_eq_baseline'] += ok
    out['stored_summary_has_run_id'] += isinstance(s, dict) and 'discovery_run_id' in s
    if not ok: out['failures'].append({'candidate': p['source_candidate_id'], 'why': 'digest mismatch' if isinstance(s, dict) else 'no stored summary'})
print(json.dumps(out, indent=1))
