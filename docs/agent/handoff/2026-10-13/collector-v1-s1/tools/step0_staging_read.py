"""Step 0 (Q7) read-only staging check. DATABASE_URL from env; session is read-only."""
import json, os, datetime, sqlalchemy as sa
T = ["market_workflow_runs", "market_signal_events", "market_intelligence_reports", "market_report_digest_sends"]
REF = ["market_index_snapshots", "card_pirate_index_points", "market_value_points"]
u = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
e = sa.create_engine(u, connect_args={"options": "-c default_transaction_read_only=on"})
out = {"observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
with e.connect() as c:
    out["read_only"] = c.execute(sa.text("show transaction_read_only")).scalar()
    names = [r[0] for r in c.execute(sa.text("select relname from pg_stat_user_tables"))]
    ref = [n for n in names if any(k in n for k in ("market_index", "market_value", "card_pirate_index"))]
    rows = c.execute(sa.text("""select relname, n_live_tup, seq_scan, last_seq_scan, idx_scan, last_idx_scan, n_tup_ins, n_tup_upd
        from pg_stat_user_tables where relname = any(:t) order by relname"""), {"t": T + ref}).mappings().all()
    out["table_stats"] = [dict(r) for r in rows]
    out["stats_reset"] = c.execute(sa.text("select stats_reset from pg_stat_database where datname=current_database()")).scalar()
    out["exact_counts"] = {t: c.execute(sa.text(f'select count(*) from "{t}"')).scalar() for t in T}
    out["latest_rows"] = {}
    for t in T:
        cols = [r[0] for r in c.execute(sa.text("select column_name from information_schema.columns where table_name=:t"), {"t": t})]
        ts = [x for x in ("created_at", "started_at", "generated_at", "sent_at") if x in cols]
        if ts: out["latest_rows"][t] = str(c.execute(sa.text(f'select max("{ts[0]}") from "{t}"')).scalar())
    out["dependent_views"] = [dict(r) for r in c.execute(sa.text("""select distinct v.relname as view, t.relname as on_table
        from pg_depend d join pg_rewrite w on w.oid=d.objid join pg_class v on v.oid=w.ev_class
        join pg_class t on t.oid=d.refobjid where t.relname = any(:t) and v.relname <> t.relname"""), {"t": T}).mappings()]
    out["incoming_foreign_keys"] = [dict(r) for r in c.execute(sa.text("""select conrelid::regclass::text as from_table, confrelid::regclass::text as to_table, conname
        from pg_constraint where contype='f' and confrelid::regclass::text = any(:t)"""), {"t": T}).mappings()]
    out["functions_or_triggers_mentioning"] = [r[0] for r in c.execute(sa.text("""select proname from pg_proc p join pg_namespace n on n.oid=p.pronamespace
        where n.nspname='public' and (prosrc ~ 'market_workflow_runs|market_signal_events|market_intelligence_reports|market_report_digest_sends')"""))]
print(json.dumps(out, indent=1, default=str))
