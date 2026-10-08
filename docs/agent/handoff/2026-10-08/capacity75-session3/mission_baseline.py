"""Read-only staging identity corpus and retained raw evidence."""
import json
import hashlib
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
import generate_staging_state as state
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.services.source_mapping_proposals import analyse_source_mapping_proposals

OUT=Path('/tmp/raw-breakthrough-evidence')
QUERIES={
 'prints': "select p.id,p.canonical_card_id,c.card_code,p.release_product_id,p.official_asset_variant,p.artwork_key,p.official_name,p.official_rarity,p.image_url,p.treatment from card_prints p join canonical_cards c on c.id=p.canonical_card_id where p.is_active and p.verification_status='verified' order by p.id",
 'releases': 'select * from release_products',
 'aliases': 'select * from release_product_aliases',
 'yuyu_candidates': 'select * from yuyutei_candidates order by id',
 'snkr_candidates': 'select * from snkrdunk_candidates order by id',
 'mappings': "select m.id,m.card_print_id,m.source_id,s.name,m.source_url,m.source_card_id,m.review_status,m.manual_verified from source_card_mappings m join sources s on s.id=m.source_id where m.is_active and m.superseded_at is null",
 'quarantines': "select w.id,w.source_card_mapping_id,w.card_print_id,w.last_failure from freshness_work w where w.state='blocked'",
 'proposal_digests': "select id,source_candidate_type,source_candidate_id,resolution_status,review_status,evidence_digest from source_mapping_proposal_groups where superseded_at is null",
 'discovery_scopes': "select id,scope_key,state,last_outcome,next_due_at,resume_cursor from freshness_work where kind='discovery'",
}

def connection():
 state.staging_environment()
 proxy=state.railway(f'query {{ tcpProxies(environmentId:"{state.ENVIRONMENT}", serviceId:"{state.POSTGRES}") {{ domain proxyPort applicationPort }} }}')['tcpProxies']
 assert len(proxy)==1 and proxy[0]['applicationPort']==5432
 variables=state.command_json(['railway','variable','list','-p',state.PROJECT,'-e',state.ENVIRONMENT,'-s',state.POSTGRES,'--json'])
 try:
  return psycopg.connect(host=proxy[0]['domain'],port=proxy[0]['proxyPort'],user=variables['PGUSER'],password=variables['PGPASSWORD'],dbname=variables['PGDATABASE'],connect_timeout=15,options='-c default_transaction_read_only=on -c statement_timeout=30000')
 finally:
  variables.clear()

def main():
 OUT.mkdir(exist_ok=True)
 (OUT/'raw').mkdir(exist_ok=True)
 with connection() as db:
  db.read_only=True
  db.isolation_level=psycopg.IsolationLevel.REPEATABLE_READ
  checks=state.guard.evaluate(state.guard.collect_facts(db),state.guard.expected_revisions_from_repo(str(state.ROOT)))
  assert all(c.ok for c in checks)
  db.row_factory=dict_row
  corpus={name:db.execute(sql).fetchall() for name,sql in QUERIES.items()}
  snapshots=db.execute("select distinct on (r.source_url) r.id,r.source_url,r.http_status,r.fetched_at,r.raw_content from raw_snapshots r join sources s on s.id=r.source_id where s.name='yuyutei' and (r.source_url like '%/sell/opc/s/%' or r.source_url='https://yuyu-tei.jp/') order by r.source_url,r.id desc").fetchall()
  receipts=[]
  for row in snapshots:
   raw=row.pop('raw_content')
   path=OUT/'raw'/f'{row["id"]}.html'
   path.write_text(raw)
   receipts.append({**row,'path':str(path),'sha256':hashlib.sha256(raw.encode()).hexdigest()})
  db.rollback()
 corpus['raw_snapshots']=receipts
 corpus['observed_at']=state.timestamp()
 (OUT/'baseline.json').write_text(json.dumps(corpus,default=state.json_default,indent=2)+'\n')
 engine=create_engine('postgresql+psycopg://',creator=connection)
 try:
  with Session(engine) as session:
   analysis=analyse_source_mapping_proposals(session)
   (OUT/'proposals.json').write_text(json.dumps([p.to_dict() for p in analysis.plans],default=state.json_default,indent=2)+'\n')
   covered=set().union(*(o.covered_print_ids for o in analysis.outcomes))
   mapped={m['card_print_id'] for m in corpus['mappings'] if m['review_status']=='approved'}
   codes={c['detected_card_code'] for name in ('yuyu_candidates','snkr_candidates') for c in corpus[name]}
   queue=[p for p in corpus['prints'] if p['id'] not in covered]
   queue.sort(key=lambda p:(p['id'] in mapped,p['release_product_id'],p['card_code'],p['id']))
   for p in queue:
    p['no_family_evidence']=p['card_code'] not in codes
   evidence={'observed_at':state.timestamp(),'target':'staging','read_only':True,
      'criterion':'No source candidate covering the authoritative exact CardPrint release/family in the current resolver; not proof of catalogue absence',
      'count':len(queue),'no_family_evidence':sum(p['no_family_evidence'] for p in queue),
      'zero_active_source':sum(p['id'] not in mapped for p in queue),'card_prints':queue,
      'resolver_report':analysis.report}
   state.atomic_write(state.ROOT/'docs/agent/evidence/raw-evidence-poor-queue-2026-10-06.json',json.dumps(evidence,default=state.json_default,indent=2)+'\n')
   session.rollback()
 finally:
  engine.dispose()
 print(json.dumps({'observed_at':corpus['observed_at'],'counts':{k:len(v) for k,v in corpus.items() if isinstance(v,list)}}))

if __name__=='__main__':
 try:
  main()
 except Exception as exc:
  raise SystemExit('Read-only baseline failed: '+type(exc).__name__) from None
