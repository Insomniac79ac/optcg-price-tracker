# Frontend styling audit — Phase 10 consistency pass

Route-by-route classification of every actual route under `apps/web/src/app`
(43 `page.tsx` files, verified via `find apps/web/src/app -name page.tsx` —
no invented routes) against the TCG Vault design system
(`docs/interface_design_system.md`).

Categories:
- **A** — Fully styled with the TCG Vault system (uses `PageHeader`/
  `StatCard`/`DataTableShell`/`FilterBar`/shared badges as appropriate; this
  is exactly the design doc's own "Pages fully migrated in this pass" list).
- **B** — Partially styled: renders inside the shared `AppShell`/dark tokens
  (every page gets this for free) and uses *some* real shared components
  (`SavedViewBar`, `StateBlocks`, shared badges, `DataTableShell` via a
  sub-component, `QuickActionBar`), but still has ad-hoc headers/stat tiles/
  tables, or a leftover pre-design-system button style.
- **C** — Old/generic styling: raw `<table>` markup and essentially no
  shared-component adoption beyond the automatic shell wrapper.
- **D** — Broken/unused route. None found — every route in this table
  resolves to real page content and is reachable per `docs/route_inventory.md`.

All 43 routes were inspected (component imports + a grep for legacy
Tailwind patterns: `bg-white`, `text-blue-*`, `rounded-xl`, `bg-gradient-*`,
`bg-neutral-100 ... hover:bg-white`, raw `<table>` without `DataTableShell`).

## Collector pages

| Route | Category | Main issues | Components used | Fixed in this pass | Notes |
|---|---|---|---|---|---|
| `/dashboard` | A | None | `PageHeader`, `StatCard`, `PinnedViewsSection`, `VaultHighlightsSection`, `WorkflowShortcutsSection`, `ActionButton`, `StateBlocks`, badges | No | 786 lines; already a Part 2 model page |
| `/collection` | A | None | `PageHeader`, `FilterBar`, `DataTableShell`, `SavedViewBar`, `QuickActionBar`, `PriceCell`, `ConfirmActionModal`, `ActionButton`, badges | No | 1375 lines, largest collector page |
| `/collection/vault` | A | None | `PageHeader`, `FilterBar`, `SavedViewBar`, `QuickActionBar`, `CardVaultTile`, `StateBlocks`, badges | No | Vault grid reference implementation |
| `/search` | A | None | `PageHeader`, `StateBlocks`, `PaginationControls`, `SearchTypeBadge` | No | |
| `/cards/[id]` | A | None | `CardImageFrame`, `CardIdentityBlock`, `CardPricePanel`, `OwnershipSummaryPanel`, `WishlistSummaryPanel`, `GradingSummaryPanel`, `MarketContextPanel`, `CardActivityPanel`, `DataTableShell`, `VariantBadge`, `ActionButton` | No | 960 lines; card detail reference implementation |
| `/wishlist` | B | No `PageHeader`/`StatCard`; three buttons still use the pre-design-system light style `bg-neutral-100 ... text-neutral-900 hover:bg-white` (lines 501, 917, 1054) instead of `ActionButton` | `DataTableShell`, `SavedViewBar`, `QuickActionBar`, `PaginationControls`, `WishlistPriorityBadge`, `WishlistStatusBadge`, `RarityBadge`, `FormField`, `WishlistImportExport` | No | 1069 lines |
| `/grading` | B | No `PageHeader`/`StatCard`; one button still uses the legacy `bg-neutral-100 ... hover:bg-white` style (line 610) | `DataTableShell`, `SavedViewBar`, `QuickActionBar`, `PaginationControls`, `GradingStatusBadge`, `FormField` | No | 847 lines |
| `/activity` | B | No `PageHeader`; plain `<h1>`/list markup instead of `DataTableShell` (this page is a timeline list, not tabular, so `DataTableShell` may not fit — needs `PageHeader` at minimum) | `StateBlocks`, `PaginationControls`, `SearchTypeBadge` | No | 189 lines, small page |

## Analytics pages

| Route | Category | Main issues | Components used | Fixed in this pass | Notes |
|---|---|---|---|---|---|
| `/analytics/digest` | A | None | `StatCard`, `DataTableShell`, `RiskBadge`, `SeverityBadge`, `ActionButton`, `SavedViewBar`, `StateBlocks` | No | |
| `/analytics/buy-decisions` | A | None | `StatCard`, `SavedViewBar`, `QuickActionBar`, `ActionButton`, `BuyDecisionCandidateTable` (uses `DataTableShell` internally) | No | |
| `/analytics/sell-decisions` | A | None | `StatCard`, `SavedViewBar`, `QuickActionBar`, `ActionButton`, `SellDecisionCandidateTable` (uses `DataTableShell` internally) | No | |
| `/analytics/portfolio-risk` | A | None | `StatCard`, `DataTableShell`, `RiskBadge`, `SeverityBadge`, `RarityBadge`, `SavedViewBar` | No | |
| `/analytics/collection` | B | No `PageHeader`/`StatCard` for the summary numbers (ad-hoc stat markup) | `DataTableShell`, `SavedViewBar`, `CollectionAnalyticsBreakdownChart`, `CollectionAnalyticsBreakdownTable` (uses `DataTableShell` internally), `RarityBadge`, `CollectionStatusBadge`, `StateBlocks` | No | 505 lines |
| `/analytics/wishlist` | B | No `PageHeader`/`StatCard` | `SavedViewBar`, `WishlistAnalyticsBreakdownChart`, `WishlistAnalyticsBreakdownTable`, `WishlistAnalyticsTargetTable` (tables use `DataTableShell` internally), `StateBlocks` | No | 337 lines |
| `/analytics/grading` | B | No `PageHeader`/`StatCard` | `SavedViewBar`, `GradingAnalyticsBreakdownTable`, `GradingSubmissionTable` (tables use `DataTableShell` internally), `StateBlocks` | No | 433 lines |

## Admin pages

| Route | Category | Main issues | Components used | Fixed in this pass | Notes |
|---|---|---|---|---|---|
| `/admin/catalog-ops` | A | None | `PageHeader`, `StatCard`, `PinnedViewsSection`, `QuickActionBar` | No | Catalog-ops landing page, reference implementation |
| `/admin/import-validation` | A | None | `PageHeader`, `DataTableShell`, `ActionButton`, `QuickActionBar` | No | |
| `/admin/card-duplicates` | A | None | `PageHeader`, `StatCard`, `FilterBar`, `DataTableShell`, `SavedViewBar`, `QuickActionBar`, `ConfirmActionModal`, `ActionButton`, `Badge`, `VariantBadge`, `RarityBadge` | No | |
| `/admin/source-mapping-quality` | A | None | `PageHeader`, `StatCard`, `FilterBar`, `DataTableShell`, `SavedViewBar`, `QuickActionBar`, `AdminActionPanel`, `ConfirmActionModal`, `ActionButton`, `Badge`, `ConfidenceBadge` | No | 840 lines |
| `/admin/price-source-health` | A | None | `PageHeader`, `StatCard`, `DataTableShell`, `SavedViewBar`, `PriceCell`, `RiskBadge`, `SourceHealthBadge` | No | |
| `/admin/cards` | B | No `PageHeader`/`StatCard`; one legacy `bg-neutral-100 ... hover:bg-white` button (line 461) | `DataTableShell`, `SavedViewBar`, `PaginationControls`, `RarityBadge`, `FormField` | No | 613 lines |
| `/admin/catalog-coverage` | B | No `PageHeader`/`StatCard` for coverage numbers | `DataTableShell`, `SavedViewBar`, `PaginationControls` | No | 508 lines |
| `/admin/snkrdunk-candidates` | B | No `PageHeader`/`StatCard` | `DataTableShell`, `SavedViewBar`, `MatchStatusBadge`, `PaginationControls` | No | 738 lines |
| `/admin/card-audit` | B | No `PageHeader`/`StatCard`/`SavedViewBar`; raw `<table>` instead of `DataTableShell` | `SeverityBadge`, `AdminAuthGate` | No | 408 lines |
| `/admin/system-check` | B | No `PageHeader`/`DataTableShell`; raw `<table>` | `SeverityBadge`, `VersionFooter`, `AdminAuthGate` | No | 380 lines |
| `/admin/market-workflow-runs` | B | No `PageHeader`/`DataTableShell`; raw `<table>` | `MarketWorkflowRunStatusBadge`, `PaginationControls` | No | 339 lines |
| `/admin/refresh-runs` | B | No `PageHeader`/`DataTableShell`; raw `<table>` | `RunStatusBadge`, `PaginationControls` | No | 237 lines |
| `/admin/performance` | B | No `PageHeader`/`DataTableShell`; 3 raw `<table>` blocks | `SeverityBadge`, `StateBlocks`, `VersionFooter` | No | 423 lines |
| `/admin/job-locks` | B | No `PageHeader`/`DataTableShell`; raw `<table>` | `StateBlocks`, `VersionFooter` | No | 372 lines |
| `/admin/alerts` | B | No `PageHeader`/`DataTableShell`; 2 raw `<table>` blocks | `AlertStatusBadge` | No | 359 lines |
| `/admin/logs` | B | No `PageHeader`/`DataTableShell`; raw `<table>`; one legacy `bg-neutral-100 ... hover:bg-white` button (line 634) | `LogLevelBadge`, `StateBlocks`, `PaginationControls` | No | 651 lines |
| `/admin/backup` | B | No `PageHeader`; two legacy `bg-neutral-100 ... hover:bg-white` buttons (lines 198, 404) | `FileJobTracker`, `AdminAuthGate` | No | 559 lines; dry-run/restore confirm flow already exists and is fine |
| `/admin/cache` | B | No `PageHeader`/`StatCard` (plain `<h1 className="text-lg font-semibold text-neutral-100">`) | `AdminAuthGate` only | No | 309 lines |
| `/admin/actions` | B | No `PageHeader`; one legacy `bg-neutral-100 ... hover:bg-white` button (line 693) | `VersionFooter`, `AdminAuthGate` | No | 768 lines, largest admin page — mostly action buttons |
| `/admin/release-status` | B | No `PageHeader`/`StatCard` for the readiness rollup | `AdminAuthGate` only | No | 353 lines |
| `/admin/data-retention` | C | No `PageHeader`; 2 raw `<table>` blocks; one legacy `bg-neutral-100 ... hover:bg-white` button (line 311); no shared badges/`StateBlocks`/`SavedViewBar` at all | `AdminAuthGate` only | No | 416 lines |
| `/admin/file-jobs` | C | No `PageHeader`; raw `<table>`; one legacy `bg-neutral-100 ... hover:bg-white` button (line 415); no shared badges/`StateBlocks`/`SavedViewBar` | `AdminAuthGate` only | No | 441 lines |

## Market pages

| Route | Category | Main issues | Components used | Fixed in this pass | Notes |
|---|---|---|---|---|---|
| `/market/opportunities` | B | No `PageHeader`/`StatCard` | `DataTableShell`, `SavedViewBar`, `OpportunityCategoryBadge`, `WishlistPriorityBadge`, `GradingStatusBadge`, `MarketSignalEventStatusBadge`, `RarityBadge`, `CollectorTagBadge`, `CollectorGroupLabel`, `StateBlocks`, `PaginationControls` | No | 648 lines |
| `/market/signals` | B | No `PageHeader`; raw `<table>` instead of `DataTableShell` | `SavedViewBar`, `RarityBadge`, `SeverityBadge` | No | 505 lines |
| `/market/signal-events` | B | No `PageHeader`; raw `<table>` instead of `DataTableShell` | `SavedViewBar`, `MarketSignalEventStatusBadge`, `RarityBadge`, `SeverityBadge`, `StateBlocks`, `PaginationControls` | No | 573 lines |
| `/market/report` | B | No `PageHeader`; raw `<table>` instead of `DataTableShell` | `OpportunityCategoryBadge`, `StateBlocks` | No | 482 lines |
| `/market/movers` | C | No `PageHeader`; raw `<table>`; no `StateBlocks`/`SavedViewBar` — the only public anonymous-visitor landing page, minimal shared-component adoption | `PriceTypeBadge`, `RarityBadge`, `SourceBadge` | No | 313 lines; public, no auth |

## Misc

| Route | Category | Main issues | Components used | Fixed in this pass | Notes |
|---|---|---|---|---|---|
| `/` (root) | A | None — 5-line redirect to `/dashboard`, no rendered UI of its own | n/a | No | Not a real page to style |

## Summary counts

- **A (fully styled):** 15 routes (`/`, `/dashboard`, `/collection`, `/collection/vault`, `/search`, `/cards/[id]`, `/analytics/digest`, `/analytics/buy-decisions`, `/analytics/sell-decisions`, `/analytics/portfolio-risk`, `/admin/catalog-ops`, `/admin/import-validation`, `/admin/card-duplicates`, `/admin/source-mapping-quality`, `/admin/price-source-health`)
- **B (partially styled):** 24 routes
- **C (old/generic):** 4 routes (`/admin/data-retention`, `/admin/file-jobs`, `/market/movers`, and effectively the raw-table cluster bordering C — see notes)
- **D (broken/unused):** 0 routes

## Prioritized fix list for Parts 2–4

**Collector (Part 2):** `/wishlist`, `/grading`, `/activity` — mostly need `PageHeader` added and the three leftover `bg-neutral-100 ... hover:bg-white` buttons replaced with `ActionButton`.

**Analytics (Part 3):** `/analytics/collection`, `/analytics/wishlist`, `/analytics/grading` — add `PageHeader` + convert ad-hoc summary numbers to `StatCard`.

**Admin (Part 4):** Highest priority — the raw-`<table>` cluster with zero/near-zero shared-component adoption: `/admin/data-retention`, `/admin/file-jobs`, `/admin/card-audit`, `/admin/system-check`, `/admin/market-workflow-runs`, `/admin/refresh-runs`, `/admin/performance`, `/admin/job-locks`, `/admin/alerts`, `/admin/logs` (convert to `DataTableShell` + add `PageHeader`). Lower priority (no raw table, just missing `PageHeader`/legacy buttons): `/admin/cards`, `/admin/catalog-coverage`, `/admin/snkrdunk-candidates`, `/admin/backup`, `/admin/cache`, `/admin/actions`, `/admin/release-status`.

**Market (part of Part 2/3 scope):** `/market/movers`, `/market/signals`, `/market/signal-events`, `/market/report` need `DataTableShell` + `PageHeader`; `/market/opportunities` just needs `PageHeader`/`StatCard` polish.
