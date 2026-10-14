"""Read-only staging facts for collector v1 S3. Every connection forces
default_transaction_read_only=on (tools/db.py); the legacy dry run additionally
sets its own transaction READ ONLY and rolls back.

usage: staging_readonly.py {state|dry-run} > out.json
  state    alembic head, account tables (exist, rows, bytes), legacy row counts
  dry-run  python -m app.accounts.migrate_legacy --dry-run, against staging
"""
import datetime, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import db as staging

TABLES = ("collection_entries", "collection_entry_events", "watchlist_entries",
          "user_preferences", "collection_value_points")
LEGACY = ("users", "collection_items", "wishlist_items", "cards", "saved_views", "search_history")


def state():
    out = {"observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    with staging.connection() as c:
        assert c.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"] == "on"
        out["alembic"] = [r["version_num"] for r in c.execute("SELECT version_num FROM alembic_version")]
        out["table_count"] = c.execute(
            "SELECT count(*) AS n FROM information_schema.tables WHERE table_schema='public'"
        ).fetchone()["n"]
        out["account_tables"] = {}
        for t in TABLES:
            exists = c.execute("SELECT to_regclass(%s) IS NOT NULL AS e", (t,)).fetchone()["e"]
            row = {"exists": exists}
            if exists:
                row["rows"] = c.execute(f'SELECT count(*) AS n FROM "{t}"').fetchone()["n"]
                row["total_bytes"] = c.execute("SELECT pg_total_relation_size(%s) AS b", (t,)).fetchone()["b"]
                row["indexes"] = [r["indexname"] for r in c.execute(
                    "SELECT indexname FROM pg_indexes WHERE tablename=%s ORDER BY indexname", (t,))]
                row["columns"] = c.execute(
                    "SELECT count(*) AS n FROM information_schema.columns WHERE table_name=%s", (t,)
                ).fetchone()["n"]
            out["account_tables"][t] = row
        out["legacy_rows"] = {t: c.execute(f'SELECT count(*) AS n FROM "{t}"').fetchone()["n"] for t in LEGACY}
        out["database_bytes"] = c.execute("SELECT pg_database_size(current_database()) AS b").fetchone()["b"]
    return out


def dry_run():
    from sqlalchemy.orm import Session
    from app.accounts.migrate_legacy import run
    engine = staging.engine()
    with Session(engine) as session:
        assert session.execute(__import__("sqlalchemy").text("SHOW transaction_read_only")).scalar() == "on"
        session.rollback()
        report = run(session, write_rows=False)
    engine.dispose()
    return report


if __name__ == "__main__":
    print(json.dumps({"state": state, "dry-run": dry_run}[sys.argv[1]](), indent=1, default=str))
