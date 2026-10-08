# Codespace disk cleanup — 2026-10-08

Written BEFORE any deletion.

## Before (MEASURED, `df -h /workspaces`)

- `/` and `/workspaces` (same overlay/loop4 device, also hosts `/var/lib/docker`): 32G size, 26G used, 4.4G avail, 86% used.
- `/tmp` is a separate 118G disk (7% used); worktrees under `/tmp` do not consume the constrained device.

## Largest consumers (MEASURED, `du -xsh`)

| Path | Size | Decision |
|---|---|---|
| `~/.codex/packages/app-server-daemon/releases/` (9 versions) | 3.7G | delete 8 superseded versions, keep current 0.161.0 |
| `~/.codex/sessions` | 1.2G | KEEP — agent session history, not reproducible |
| `data/official_snapshots/bandai_jp` | 977M | KEEP — raw/source evidence |
| `docs/` | 998M | KEEP — reports/handoffs |
| `apps/web/node_modules` | 752M | KEEP — active build dependency (reinstall would re-consume) |
| `~/.venvs/cardpirate` | 588M | KEEP — active venv |
| Docker local volumes (12) | 3.1G | KEEP — database data |
| Docker images postgres:16/18/16-alpine | 1.6G | KEEP — all referenced by containers incl. running `capacity75-local-pg` |
| `~/.cache/ms-playwright` | 267M | KEEP for now (reproducible, but not needed to hit target) |

## Deletion candidates

| Path | Size | Why reproducible |
|---|---|---|
| `~/.codex/packages/app-server-daemon/releases/0.157.1-x86_64-unknown-linux-musl` | 374M | superseded auto-update binary; `current` and `auto-update-version` point to 0.161.0; re-downloadable |
| `.../releases/0.158.0-...` | 424M | same |
| `.../releases/0.159.0-...` | 424M | same |
| `.../releases/0.159.1-...` | 424M | same |
| `.../releases/0.159.2-...` | 424M | same |
| `.../releases/0.159.3-...` | 425M | same |
| `.../releases/0.160.0-...` | 427M | same |
| `.../releases/0.160.1-...` | 427M | same |
| `~/.npm/_cacache` | 63M | npm download cache |
| `~/.cache/pip` | 16M | pip download cache |
| `git worktree prune` (prunable metadata only) | ~0 | worktree directories already gone; metadata only |

Expected reclaim: ~3.4G → ~7.8G free (~24%).

Never deleted: uncommitted edits, active worktrees (`/tmp/capacity75-*`), handoffs, rollback evidence, raw/source evidence, reports, Docker volumes/DB data.

## After (MEASURED, `df -h /workspaces`)

- 32G size, 23G used, 7.7G avail, 75% used (~24% free). Reclaimed ~3.3G.
- Deleted: 8 superseded codex releases, `~/.npm/_cacache`, `~/.cache/pip`.
- Skipped `git worktree prune` (metadata only, no space gain).
- Codex daemon 0.161.0 still running after cleanup.
- Constraint: Docker volumes (3.1G DB data) and images (1.6G) share this device; keep local build/artifact footprint minimal.
