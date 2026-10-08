"""Read-only: share of recent RAW bodies byte-identical to an earlier stored body. No source HTTP, no writes."""
import json
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
import generate_staging_state as state
import mission_baseline as baseline
OUT=Path(__file__).parent
SQL="""with recent as (
  select r.id,s.name,r.parser_version,r.content_hash,r.source_url,pg_column_size(r.raw_content) stored
  from raw_snapshots r join sources s on s.id=r.source_id
  where r.fetched_at>=now()-interval '24 hours')
select name,parser_version,count(*) snapshots,sum(stored) stored_bytes,
  count(*) filter(where exists(select 1 from raw_snapshots o where o.content_hash=recent.content_hash and o.id<recent.id)) identical_to_earlier,
  sum(stored) filter(where exists(select 1 from raw_snapshots o where o.content_hash=recent.content_hash and o.id<recent.id)) identical_bytes,
  count(*) filter(where exists(select 1 from raw_snapshots o where o.content_hash=recent.content_hash and o.source_url=recent.source_url and o.id<recent.id)) identical_same_url,
  count(distinct content_hash) distinct_hashes
from recent group by 1,2 order by 1,2"""
with baseline.connection() as db:
    db.read_only=True
    db.isolation_level=psycopg.IsolationLevel.REPEATABLE_READ
    db.row_factory=dict_row
    now=db.execute('select now() n').fetchone()['n']
    rows=db.execute(SQL).fetchall()
    total=db.execute("select count(*) n,count(distinct content_hash) d from raw_snapshots").fetchone()
    db.rollback()
r={'observed_at':now,'target':'staging','source_http':0,'database_writes':0,'production_accessed':False,'sql':SQL,'recent24h':rows,'all_time':total}
state.atomic_write(OUT/'raw-dedup-24h.json',json.dumps(r,default=state.json_default,indent=2)+'\n')
print(json.dumps(r['recent24h'],default=str,indent=1),total)
