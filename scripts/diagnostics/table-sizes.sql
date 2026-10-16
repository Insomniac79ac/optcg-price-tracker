-- Database and largest-table sizes (session 13 db-size-end.txt). Read-only catalogue reads.
-- database
select now() at time zone 'utc' observed_at, pg_database_size(current_database()) db_bytes;

-- largest_tables
select c.relname table_name, pg_total_relation_size(c.oid) total_bytes, pg_relation_size(c.oid) heap_bytes,
  c.reltuples::bigint estimated_rows
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where c.relkind = 'r' and n.nspname = 'public'
order by pg_total_relation_size(c.oid) desc
limit 25;
