"""Step 0 (Q7): forward import closure from Market Value / Card Pirate Index /
market-index-snapshot / public API entry points, searched for any reference to
the market workflow's outputs. Read-only; local files only."""
import ast, json, re, sys
from pathlib import Path
ROOT = Path(sys.argv[1]) / "services/api"
ENTRIES = ["app.market_index_daily_pipeline", "app.snapshot_market_index", "app.card_pirate_index_writer",
           "app.market_value_publisher", "app.market_value_writer", "app.market_value_replay_report",
           "app.api.market_value", "app.api.prints", "app.api.releases", "app.api.cards"]
PATTERN = re.compile(r"MarketSignalEvent|MarketIntelligenceReport|MarketWorkflowRun|MarketReportDigestSend|"
                     r"market_signal_events|market_intelligence_reports|market_workflow_runs|market_report_digest_sends|"
                     r"market_signals|opportunity_scoring|market_report|market_workflow")
def path_of(mod):
    p = ROOT / (mod.replace(".", "/") + ".py")
    if p.exists(): return p
    p = ROOT / mod.replace(".", "/") / "__init__.py"
    return p if p.exists() else None
def imports(mod, p):
    tree = ast.parse(p.read_text())
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:
                pkg = mod.split(".")[: -n.level] if not p.name == "__init__.py" else mod.split(".")[: len(mod.split(".")) - n.level + 1]
                base = ".".join(pkg + ([base] if base else []))
            out.add(base)
            out |= {f"{base}.{a.name}" for a in n.names}
    return {m for m in out if m.startswith("app")}
seen, stack = {}, list(ENTRIES)
while stack:
    m = stack.pop()
    if m in seen: continue
    p = path_of(m)
    if not p: continue
    seen[m] = p
    stack.extend(imports(m, p))
# models/__init__ re-exports every model (including the workflow ones); report model hits separately.
hits = {}
for m, p in sorted(seen.items()):
    if m.startswith("app.models"): continue
    lines = [f"{i}: {l.strip()[:120]}" for i, l in enumerate(p.read_text().splitlines(), 1) if PATTERN.search(l)]
    if lines: hits[m] = lines
print(json.dumps({"entries": ENTRIES, "closure_size": len(seen),
                  "non_model_modules_referencing_workflow_outputs": hits,
                  "closure": sorted(seen)}, indent=1))
