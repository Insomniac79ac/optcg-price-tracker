"""Generic source records for shop sources added after Yuyu-Tei and SNKRDUNK.

New-sources plan §2.2 and §2.7 (docs/agent/plans/new-sources/PLAN.md, branch plan/new-sources).
Nothing in app.models imports this package, so the Yuyu-Tei and SNKRDUNK collectors never load it
and a change here never redeploys them (scripts/collector_runtime_inputs.py). Import
app.source_products.models explicitly where the tables are needed.
"""
