"""Read-only: are the S2 variable NAMES present? Values are never printed or stored.
Railway: staging API service. Vercel: optcg-price-tracker-staging, production target (= staging)."""
import datetime, json, re, subprocess
RAILWAY_SERVICE, RAILWAY_ENV = "5290becf-6956-4c5c-ab16-01d865587e07", "05d1eac2-510d-4bd3-999e-fea9ead766b7"
out = {"observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "note": "key names only; no values read into this file"}
raw = subprocess.run(["railway", "variables", "--project", "c613898d-bf03-43a6-8813-761f72e1c00a", "--service", RAILWAY_SERVICE, "--environment", RAILWAY_ENV, "--json"], capture_output=True, text=True)
if raw.returncode == 0:
    keys = set(json.loads(raw.stdout))
    out["railway_api"] = {k + "_present": k in keys for k in ("SENTRY_DSN", "SENTRY_ENVIRONMENT", "RAILWAY_GIT_COMMIT_SHA")}
else:
    out["railway_api"] = {"error": raw.stderr.strip()[-300:]}
del raw
ls = subprocess.run(["vercel", "env", "ls", "production", "--project", "prj_DCbF7bhFkkAdfMQLZWvOQbxEDDhr"], capture_output=True, text=True)
names = set(re.findall(r"^\s*([A-Z][A-Z0-9_]+)\s", ls.stdout, re.M))
out["vercel_production"] = {k + "_present": k in names for k in ("NEXT_PUBLIC_SENTRY_DSN", "NEXT_PUBLIC_VERCEL_WEB_ANALYTICS", "NEXT_PUBLIC_APP_ENV")} if ls.returncode == 0 else {"error": ls.stderr.strip()[-300:]}
print(json.dumps(out, indent=1))
