"""Apply (or roll back) migration 3b7d9c1a5e20 on STAGING, the documented way:
`alembic upgrade <rev>` from services/api with DATABASE_URL pointing at the
staging Postgres TCP proxy (docs/railway_staging.md section 3). Credentials are
read from Railway at run time and never printed or written.

usage: apply_migration.py upgrade|downgrade > evidence/migration-....json
  upgrade    6c2242f6f439 -> 3b7d9c1a5e20 (refuses unless head is 6c2242f6f439)
  downgrade  3b7d9c1a5e20 -> 6c2242f6f439 (the migration itself refuses non-empty tables)

lock_timeout=10s: if a long transaction holds users/card_prints, the DDL aborts
and rolls back instead of queueing collector reads behind it.
"""
import datetime, json, os, subprocess, sys
from pathlib import Path
from urllib.parse import quote
sys.path.insert(0, str(Path(__file__).resolve().parent))
import db as staging
from staging_readonly import state

PARENT, REVISION = "6c2242f6f439", "3b7d9c1a5e20"
API = Path("/workspaces/cp-cv1-s3/services/api")


def database_url():
    s = staging.state
    s.staging_environment()
    assert s.ENVIRONMENT == "05d1eac2-510d-4bd3-999e-fea9ead766b7", "not staging"
    proxy = s.railway(f'query {{ tcpProxies(environmentId:"{s.ENVIRONMENT}", serviceId:"{s.POSTGRES}") {{ domain proxyPort applicationPort }} }}')["tcpProxies"]
    assert len(proxy) == 1 and proxy[0]["applicationPort"] == 5432
    v = s.command_json(["railway", "variable", "list", "-p", s.PROJECT, "-e", s.ENVIRONMENT, "-s", s.POSTGRES, "--json"])
    try:
        return (f"postgresql+psycopg://{quote(v['PGUSER'])}:{quote(v['PGPASSWORD'])}@"
                f"{proxy[0]['domain']}:{proxy[0]['proxyPort']}/{v['PGDATABASE']}"), proxy[0]["proxyPort"]
    finally:
        v.clear()


def main(action):
    target = {"upgrade": REVISION, "downgrade": PARENT}[action]
    expect_before = {"upgrade": PARENT, "downgrade": REVISION}[action]
    out = {"action": action, "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    out["before"] = state()
    if out["before"]["alembic"] != [expect_before]:
        out["refused"] = f"alembic head is {out['before']['alembic']}, expected [{expect_before}]"
        return out
    url, out["proxy_port"] = database_url()
    env = dict(os.environ, DATABASE_URL=url, PGOPTIONS="-c lock_timeout=10s -c statement_timeout=120s")
    result = subprocess.run([sys.executable, "-m", "alembic", action, target], cwd=API, env=env,
                            capture_output=True, text=True, timeout=600)
    del env, url
    out["alembic_exit"] = result.returncode
    out["alembic_log"] = [l for l in (result.stdout + result.stderr).splitlines()
                          if "Running" in l or "Error" in l or "Refusing" in l][-20:]
    out["after"] = state()
    out["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return out


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1]), indent=1, default=str))
