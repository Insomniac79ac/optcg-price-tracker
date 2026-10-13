"""Read-only NEW100 re-plan on current (resolver 1.3) digests and per-candidate guard evaluation.

For each of the 100 candidates in the 2026-10-07 plan, rerun the canonical resolver
(`resolve_current_candidate_proposal`, the same call the collector's `load_intent` makes at
claim time) over a read-only staging connection, and evaluate:
- ambiguous family plan with a complete bounded sibling set (2..MAX_SIBLINGS), as load_intent requires;
- authoritative release: every considered CardPrint's release_product_id equals the plan's,
  and all share the plan's canonical card (never inferred from a card-code prefix);
- no active Yuyu mapping on any considered print, and none for this listing;
- virgin family: no prior identity-capture scope for the candidate and no reviewed proposal;
- candidate listing identity matches its stored set/product (load_intent's check);
- no considered print shared with another planned candidate.
No writes (default_transaction_read_only=on, session rolled back), no source requests.
usage: new100_replan.py <old-manifest.json> > out.json
"""
import json, sys
sys.path[:0] = ['/workspaces/cp-cap12/services/api', '/workspaces/cp-cap12/packages/opcg_source_identity/src',
                '/workspaces/cp-cap12/docs/agent/handoff/2026-10-13/capacity75-session12/tools']
from collections import Counter
from sqlalchemy import text
from sqlalchemy.orm import Session
import db as dbtool
from opcg_source_identity import yuyutei_listing_identity
from app.models import YuyuteiCandidate
from app.services.source_mapping_proposals import resolve_current_candidate_proposal, RESOLVER_VERSION
from app.services.identity_evidence_scope import identity_evidence_scope

MAX_SIBLINGS = 12  # services/yuyutei_collector/yuyutei_collector/identity_evidence.py
old = json.load(open(sys.argv[1]))
records = old['records']
out = {'read_only': True, 'source_requests': 0, 'database_writes': 0, 'resolver_version': RESOLVER_VERSION,
       'old_manifest_observed_at': old['observed_at'], 'records': []}

with Session(dbtool.engine()) as s:
    out['observed_at'] = s.execute(text("select now()")).scalar().isoformat()
    for r in records:
        cid = r['candidate_id']
        row = {'candidate_id': cid, 'card_code': r['card_code'], 'old_digest': r['evidence_digest'],
               'old_considered_print_ids': r['considered_print_ids'], 'guards': {}}
        cand = s.get(YuyuteiCandidate, cid)
        plan = resolve_current_candidate_proposal(s, source_name='yuyutei', candidate_id=cid)
        g = row['guards']
        g['candidate_listing_identity'] = cand is not None and yuyutei_listing_identity(cand.source_url) == (cand.set_slug, cand.product_id)
        if plan is None:
            g['current_plan'] = False
            out['records'].append(row); continue
        ids = sorted(a.card_print_id for a in plan.alternatives)
        row.update({'resolution_status': plan.resolution_status, 'evidence_digest': plan.evidence_digest,
                    'resolver_version': plan.resolver_version, 'release_product_id': plan.release_product_id,
                    'canonical_card_id': plan.canonical_card_id, 'considered_print_ids': ids,
                    'source_url': plan.source_url, 'evidence_summary': plan.evidence_summary})
        g['current_plan'] = True
        g['ambiguous_family'] = plan.resolution_status == 'ambiguous'
        g['bounded_sibling_set'] = 2 <= len(ids) <= MAX_SIBLINGS
        row['siblings_changed'] = ids != sorted(r['considered_print_ids'])
        prints = s.execute(text("select id, release_product_id, canonical_card_id from card_prints where id = any(:ids)"),
                           {'ids': ids}).mappings().all()
        g['prints_exist'] = len(prints) == len(ids)
        g['authoritative_release'] = (plan.release_product_id is not None and bool(prints)
                                      and all(p['release_product_id'] == plan.release_product_id for p in prints))
        g['same_canonical_card'] = bool(prints) and all(p['canonical_card_id'] == plan.canonical_card_id for p in prints)
        active = s.execute(text("""select id, card_print_id, source_url from source_card_mappings where source_id=1
            and is_active and superseded_at is null and (card_print_id = any(:ids) or source_url = :url)"""),
            {'ids': ids, 'url': plan.source_url}).mappings().all()
        row['active_yuyu_mappings'] = [dict(a) for a in active]
        g['no_active_yuyu_mapping'] = not active
        prior = s.execute(text("""select id, scope_key, state from freshness_work
            where scope_key = :legacy or scope_key like :pattern"""),
            {'legacy': f'yuyu-identity:{cid}', 'pattern': f'yuyu-identity:{cid}:%'}).mappings().all()
        row['prior_capture_scopes'] = [dict(p) for p in prior]
        g['no_prior_capture_scope'] = not prior
        reviewed = s.execute(text("""select count(*) from source_mapping_proposal_groups where source_id=1
            and source_candidate_id=:cid and reviewed_at is not null"""), {'cid': cid}).scalar()
        g['no_reviewed_decision'] = reviewed == 0
        stored = s.execute(text("""select evidence_digest, resolver_version, resolution_status, review_status
            from source_mapping_proposal_groups where source_id=1 and source_candidate_id=:cid and superseded_at is null"""),
            {'cid': cid}).mappings().all()
        row['stored_current_groups'] = [dict(x) for x in stored]
        row['stored_digest_equals_live'] = len(stored) == 1 and stored[0]['evidence_digest'] == plan.evidence_digest
        row['scope_key'] = identity_evidence_scope(cid, plan.evidence_digest, 2)
        out['records'].append(row)
    s.rollback()

shared = Counter(i for row in out['records'] for i in row.get('considered_print_ids', []))
for row in out['records']:
    row['guards']['no_shared_print_with_other_planned'] = all(shared[i] == 1 for i in row.get('considered_print_ids', []))
    row['eligible'] = all(row['guards'].values())
out['summary'] = {
    'planned': len(records), 'eligible': sum(r['eligible'] for r in out['records']),
    'guard_failures': dict(Counter(k for r in out['records'] for k, v in r['guards'].items() if not v)),
    'digest_changed_from_2026_10_07': sum(r.get('evidence_digest') != r['old_digest'] for r in out['records']),
    'siblings_changed': sum(bool(r.get('siblings_changed')) for r in out['records']),
    'stored_group_still_resolver_1_2': sum(any(g['resolver_version'].endswith('1.2') for g in r.get('stored_current_groups', [])) for r in out['records']),
    'stored_digest_equals_live': sum(bool(r.get('stored_digest_equals_live')) for r in out['records']),
    'official_sibling_images': sum(len(r.get('considered_print_ids', [])) for r in out['records'] if r['eligible']),
    'yuyu_images': sum(1 for r in out['records'] if r['eligible']),
}
print(json.dumps(out, indent=1, default=str, ensure_ascii=False))
