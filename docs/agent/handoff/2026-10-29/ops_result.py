"""Dispatch an ops-readonly runbook and read its summary from the check-run annotations.

usage: python3 ops_result.py <runbook> [<diagnostic>] [--out DIR]
  python3 ops_result.py db-diagnostic identity-capture-work
  python3 ops_result.py staging-state
Writes <out>/<name>.json (default ./ops-out). Needs `gh` authenticated (REST only).
Summaries arrive as "ops-summary i/n" annotations of up to 4000 bytes, possibly out of order;
a preflight 1/1 annotation precedes the result. Workflow artifacts are not downloadable from
the agent workspace (blob storage is blocked), so the inline summary is the only channel.
Dispatch one run at a time: dispatch() finds the new run by comparing the latest run id.
"""
import json, os, subprocess, sys, time
REPO="repos/Insomniac79ac/optcg-price-tracker"
def gh(*a):
    return subprocess.run(["gh","api",*a],capture_output=True,text=True).stdout
def dispatch(runbook, diagnostic=None):
    args=["-X","POST",f"{REPO}/actions/workflows/ops-readonly.yml/dispatches","-f","ref=staging","-f",f"inputs[runbook]={runbook}"]
    if diagnostic: args+=["-f",f"inputs[diagnostic]={diagnostic}"]
    before=json.loads(gh(f"{REPO}/actions/workflows/ops-readonly.yml/runs?per_page=1"))["workflow_runs"][0]["id"]
    gh(*args)
    for _ in range(40):
        time.sleep(5)
        rid=json.loads(gh(f"{REPO}/actions/workflows/ops-readonly.yml/runs?per_page=1"))["workflow_runs"][0]["id"]
        if rid!=before: return rid
    raise SystemExit("no run")
def result(rid):
    for _ in range(80):
        if json.loads(gh(f"{REPO}/actions/runs/{rid}"))["status"]=="completed": break
        time.sleep(10)
    parts=[]
    for j in json.loads(gh(f"{REPO}/actions/runs/{rid}/jobs"))["jobs"]:
        for a in json.loads(gh(f"{REPO}/check-runs/{j['id']}/annotations?per_page=100")):
            t=(a.get("title") or "")
            if not t.startswith("ops-summary"): continue
            i,n=t.split()[-1].split("/")
            parts.append((int(n),int(i),a["message"]))
    if not parts: return {"raw":[]}
    groups={}
    for n,i,m in parts: groups.setdefault(n,[]).append((i,m))
    docs=[]
    for n,items in groups.items():
        starts=[m for i,m in items if i==1]
        if n==1:
            for m in starts:
                try: docs.append(json.loads(m))
                except Exception: pass
        else:
            try: docs.append(json.loads("".join(m for i,m in sorted(items))))
            except Exception: pass
    final=[d for d in docs if d.get("status")!="preflight-ok"]
    return (final or docs or [{"raw":[m for _,_,m in parts]}])[-1]
if __name__=="__main__":
    argv=sys.argv[1:]
    outdir="ops-out"
    if "--out" in argv:
        i=argv.index("--out"); outdir=argv[i+1]; del argv[i:i+2]
    os.makedirs(outdir, exist_ok=True)
    runbook=argv[0]; diag=argv[1] if len(argv)>1 else None
    rid=dispatch(runbook,diag)
    out=result(rid); out["_run_id"]=rid
    name=diag or runbook
    json.dump(out,open(os.path.join(outdir,f"{name}.json"),"w"),ensure_ascii=False,indent=1)
    print(name, rid, out.get("status"))
