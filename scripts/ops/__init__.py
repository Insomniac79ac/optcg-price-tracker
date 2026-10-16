"""Read-only and owner-gated staging runbooks, run by GitHub Actions (ops-readonly, ops-write).

Agents in cloud sessions never hold staging credentials: they dispatch a runbook and read its
summary. See docs/agent/OPS_RUNBOOKS.md.
"""
