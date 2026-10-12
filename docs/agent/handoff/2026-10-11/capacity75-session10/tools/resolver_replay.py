"""Read-only resolver replay for a sample of physical-proof candidates, against staging,
for the code at <code-root>. Connection forced read-only; no persist, no commit.
usage: resolver_replay.py <code-root> <every-nth> > out.json"""
import json, os, sys
code, nth = sys.argv[1], int(sys.argv[2])
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'   # the app's own engine is never used
os.environ['APP_ENV'] = os.environ['ENVIRONMENT'] = 'staging'
sys.path.insert(0, '/workspaces/cp-s10/scripts')
import generate_staging_state as state  # may add its own repo paths; the code root must win
sys.path[:0] = [code + '/services/api', code + '/packages/opcg_source_identity/src']
for m in [m for m in sys.modules if m in ('app', 'opcg_source_identity') or m.startswith(('app.', 'opcg_source_identity.'))]:
    del sys.modules[m]  # the state tool's own imports; re-import from the code root under test
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
state.staging_environment()
proxy = state.railway(f'query {{ tcpProxies(environmentId:"{state.ENVIRONMENT}", serviceId:"{state.POSTGRES}") {{ domain proxyPort applicationPort }} }}')['tcpProxies'][0]
v = state.command_json(['railway', 'variable', 'list', '-p', state.PROJECT, '-e', state.ENVIRONMENT, '-s', state.POSTGRES, '--json'])
engine = create_engine('postgresql+psycopg://', connect_args=dict(host=proxy['domain'], port=proxy['proxyPort'], user=v['PGUSER'], password=v['PGPASSWORD'], dbname=v['PGDATABASE'], options='-c default_transaction_read_only=on -c statement_timeout=120000'))
v.clear()
from app.services import source_mapping_proposals as smp
assert smp.__file__.startswith(code), smp.__file__
proofs = json.load(open(code + '/services/api/app/services/evidence/positive_physical_artwork.json'))['proofs']
sample = sorted(p['source_candidate_id'] for p in proofs)[::nth]
with Session(engine) as db:
    a = smp.analyse_source_mapping_proposals(db, smp.ProposalFilters(source='yuyutei', candidate_ids=tuple(sample)), ignore_existing_mappings=True, build_report=False)
    db.rollback()
rows = [{'candidate': o.candidate_id, 'status': o.resolution_status,
         'proof': bool(o.proposal and 'positive_physical_artwork_proof' in o.proposal.evidence_summary),
         'digest': o.proposal.evidence_digest if o.proposal else None} for o in a.outcomes if o.candidate_id in set(sample)]
print(json.dumps({'code_root': code, 'module_file': smp.__file__, 'resolver_version': smp.RESOLVER_VERSION, 'sample': len(sample), 'read_only': True,
                  'exact_with_proof': sum(r['proof'] for r in rows), 'statuses': {s: sum(r['status'] == s for r in rows) for s in {r['status'] for r in rows}},
                  'rows': rows}, indent=1))
