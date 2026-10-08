"""Read-only physical recurring growth; no provider quota inference."""
import json
from pathlib import Path
from psycopg.rows import dict_row
import generate_staging_state as state
import mission_baseline as baseline
OUT=Path(__file__).parent
with baseline.connection() as db:
 db.row_factory=dict_row
 now=db.execute('select now() n').fetchone()['n']
 rows=db.execute("""select s.name,r.parser_version,count(*) snapshots,sum(pg_column_size(r.raw_content)) stored_payload_bytes,sum(pg_column_size(r)) stored_row_bytes from raw_snapshots r join sources s on s.id=r.source_id where r.fetched_at>=now()-interval '24 hours' group by 1,2 order by 1,2""").fetchall()
 obs=db.execute("select count(*) rows,sum(pg_column_size(p)) row_bytes from price_observations p where observed_at>=now()-interval '24 hours'").fetchone()
 events=db.execute("select count(*) rows,sum(pg_column_size(e)) row_bytes from app_log_events e where created_at>=now()-interval '24 hours'").fetchone()
 db.rollback()
metrics=state.command_json(['railway','metrics','-p',state.PROJECT,'-e',state.ENVIRONMENT,'-s',state.POSTGRES,'--since','1d','--volume','--json'])
assert metrics['environment']=='staging' and metrics['service']=='Postgres'
v=next(v for v in metrics['volumes'] if v['name']=='postgres-volume')
r={'observed_at':now,'target':'staging','production_accessed':False,'source_http':0,'database_writes':0,'payload_by_parser24h':rows,'observations24h':obs,'events24h':events,'volume':v,'projection_semantics':'Current writer flags OFF, global all-time cap200; no continuous canary savings assumed. Partial calendar days and one-shot image/sitemap envelopes are separate. Payload is physically PostgreSQL-compressed; row bytes overlap payload and cannot be added again. Relation/index deltas and provider growth include overhead and variable WAL; these are not a stable recurring slope.','unknowns':['R2 quota','shared asset bucket footprint','provider log byte retention','ephemeral disk headroom','process-level browser RSS','future source allocation of607 exact identities']}
state.atomic_write(OUT/'storage-projection-inputs.json',json.dumps(r,default=state.json_default,indent=2)+'\n')
print(json.dumps(r,default=state.json_default))
