"""Read-only: Railway staging deployment records per service created since a UTC time.
Usage: deploy_records.py <since-iso>   (railway api GraphQL reads only)"""
import json, subprocess, sys, datetime
PROJECT = "c613898d-bf03-43a6-8813-761f72e1c00a"
ENVIRONMENT = "05d1eac2-510d-4bd3-999e-fea9ead766b7"
def q(query):
    r = json.loads(subprocess.run(["railway", "api", query], capture_output=True, text=True, check=True).stdout)
    assert not r.get("errors") and r.get("data"), r
    return r["data"]
since = sys.argv[1]
services = q(f'query {{ project(id:"{PROJECT}") {{ services {{ edges {{ node {{ id name }} }} }} }} }}')["project"]["services"]["edges"]
out = {"observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "since": since, "services": {}}
for s in sorted((e["node"] for e in services), key=lambda n: n["name"]):
    rows = q(f'query {{ deployments(first:10, input:{{projectId:"{PROJECT}", environmentId:"{ENVIRONMENT}", serviceId:"{s["id"]}"}}) '
             f'{{ edges {{ node {{ id status createdAt meta }} }} }} }}')["deployments"]["edges"]
    recs = []
    for e in rows:
        n = e["node"]; m = n.get("meta") or {}; m = json.loads(m) if isinstance(m, str) else m
        if n["createdAt"] >= since:
            recs.append({"id": n["id"], "status": n["status"], "createdAt": n["createdAt"], "commitHash": m.get("commitHash")})
    out["services"][s["name"]] = {"since": recs, "latest": rows[0]["node"]["id"] if rows else None}
col = {k: v for k, v in out["services"].items() if "collector" in k}
out["collector_services"] = len(col)
out["collector_deployments_since"] = sum(len(v["since"]) for v in col.values())
print(json.dumps(out, indent=1))
