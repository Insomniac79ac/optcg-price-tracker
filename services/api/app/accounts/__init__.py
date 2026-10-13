"""Collector accounts v1: collection, watchlist, preferences, export, deletion.

Deliberately a separate package that no collector imports (see
scripts/collector_runtime_inputs.py and tests/test_accounts_import_graph.py):
adding or changing it must never make an API change a collector release. New
tables reference ``users.id`` and ``card_prints.id`` by foreign key only; no
relationship is added to an existing model, and ``app.models`` does not import
this package. ``alembic/env.py`` and ``app/main.py`` import it explicitly.

Values follow the public Market Value rules: archived Market Index values from
receipted days only, Yuyu-Tei sale prices never used, unpriced never shown as 0.
See docs/agent/plans/collector-v1/PLAN.md sections B and C.
"""
