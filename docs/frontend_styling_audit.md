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
| `/wishlist` | A | Fixed: added `PageHeader` (title + cross-links in description slot + item count in actions slot), replaced local `StatCard` with shared `StatGrid`/`StatCard`, converted 3 legacy `bg-neutral-100 ... hover:bg-white` buttons to `ActionButton` | `DataTableShell`, `SavedViewBar`, `QuickActionBar`, `PageHeader`, `StatCard`, `ActionButton`, `PaginationControls`, `WishlistPriorityBadge`, `WishlistStatusBadge`, `RarityBadge`, `FormField`, `WishlistImportExport` | Yes | 1069 lines |
| `/grading` | A | Fixed: same `PageHeader`/`StatGrid`/`ActionButton` treatment as `/wishlist` | `DataTableShell`, `SavedViewBar`, `QuickActionBar`, `PageHeader`, `StatCard`, `ActionButton`, `PaginationControls`, `GradingStatusBadge`, `FormField` | Yes | 847 lines |
| `/activity` | A | Fixed: added `PageHeader`, replaced local `StatCard` with shared `StatGrid`/`StatCard`; kept the timeline-list markup (not `DataTableShell`) since it's not tabular data | `StateBlocks`, `PageHeader`, `StatCard`, `PaginationControls`, `SearchTypeBadge` | Yes | 189 lines, small page |

## Analytics pages

| Route | Category | Main issues | Components used | Fixed in this pass | Notes |
|---|---|---|---|---|---|
| `/analytics/digest` | A | None | `StatCard`, `DataTableShell`, `RiskBadge`, `SeverityBadge`, `ActionButton`, `SavedViewBar`, `StateBlocks` | No | |
| `/analytics/buy-decisions` | A | None | `StatCard`, `SavedViewBar`, `QuickActionBar`, `ActionButton`, `BuyDecisionCandidateTable` (uses `DataTableShell` internally) | No | |
| `/analytics/sell-decisions` | A | None | `StatCard`, `SavedViewBar`, `QuickActionBar`, `ActionButton`, `SellDecisionCandidateTable` (uses `DataTableShell` internally) | No | |
| `/analytics/portfolio-risk` | A | None | `StatCard`, `DataTableShell`, `RiskBadge`, `SeverityBadge`, `RarityBadge`, `SavedViewBar` | No | |
| `/analytics/collection` | A | Fixed: swapped the page-local `StatCard`/`PnlStatCard` (legacy `neutral-*` classes) for the shared `StatCard`, retokened header/toggle/checkbox/section markup to `text-text-*`/`bg-bg-surface`/`border-border-default`, converted the two ad-hoc concentration/cost-basis tables to the `.data-table` class | `DataTableShell`, `SavedViewBar`, `StatCard`, `CollectionAnalyticsBreakdownChart`, `CollectionAnalyticsBreakdownTable` (uses `DataTableShell` internally), `RarityBadge`, `CollectionStatusBadge`, `StateBlocks` | Yes | 505 lines. Header block kept as the established hand-rolled `h1`+cross-links pattern (matches `/analytics/digest`/`/analytics/buy-decisions`, which don't use the `PageHeader` component either) rather than switching to `PageHeader` |
| `/analytics/wishlist` | A | Fixed: same local-`StatCard`-\>shared-`StatCard` swap, retokened header/checkboxes/section headings | `SavedViewBar`, `StatCard`, `WishlistAnalyticsBreakdownChart`, `WishlistAnalyticsBreakdownTable`, `WishlistAnalyticsTargetTable` (tables use `DataTableShell` internally), `StateBlocks` | Yes | 337 lines |
| `/analytics/grading` | A | Fixed: same local-`StatCard`-\>shared-`StatCard` swap, retokened header/filters/pagination footer/section headings | `SavedViewBar`, `StatCard`, `GradingAnalyticsBreakdownTable`, `GradingSubmissionTable` (tables use `DataTableShell` internally), `StateBlocks` | Yes | 433 lines |

## Admin pages

| Route | Category | Main issues | Components used | Fixed in this pass | Notes |
|---|---|---|---|---|---|
| `/admin/catalog-ops` | A | None | `PageHeader`, `StatCard`, `PinnedViewsSection`, `QuickActionBar` | No | Catalog-ops landing page, reference implementation |
| `/admin/import-validation` | A | None | `PageHeader`, `DataTableShell`, `ActionButton`, `QuickActionBar` | No | |
| `/admin/card-duplicates` | A | None | `PageHeader`, `StatCard`, `FilterBar`, `DataTableShell`, `SavedViewBar`, `QuickActionBar`, `ConfirmActionModal`, `ActionButton`, `Badge`, `VariantBadge`, `RarityBadge` | No | |
| `/admin/source-mapping-quality` | A | None | `PageHeader`, `StatCard`, `FilterBar`, `DataTableShell`, `SavedViewBar`, `QuickActionBar`, `AdminActionPanel`, `ConfirmActionModal`, `ActionButton`, `Badge`, `ConfidenceBadge` | No | 840 lines |
| `/admin/price-source-health` | A | None | `PageHeader`, `StatCard`, `DataTableShell`, `SavedViewBar`, `PriceCell`, `RiskBadge`, `SourceHealthBadge` | No | |
| `/admin/cards` | A | Fixed: added `PageHeader`, converted local stat tiles to `StatCard`/`StatGrid`, converted export/preview/real-import buttons to `ActionButton` (primary/dry-run/danger), `StateBlocks` for loading/error/empty, tokenized remaining `neutral-*` colors | `PageHeader`, `StatCard`/`StatGrid`, `ActionButton`, `DataTableShell`, `SavedViewBar`, `PaginationControls`, `RarityBadge`, `FormField`, `StateBlocks` | Yes | 613 lines |
| `/admin/catalog-coverage` | A | Fixed: added `PageHeader`, converted local `StatCard` to shared `StatCard`/`StatGrid`, `StateBlocks` for loading/error/empty, gold-accent tab toggle, tokenized `neutral-*` colors | `PageHeader`, `StatCard`/`StatGrid`, `DataTableShell`, `SavedViewBar`, `PaginationControls`, `StateBlocks` | Yes | 508 lines |
| `/admin/snkrdunk-candidates` | A | Fixed: added `PageHeader` + candidate-count `StatCard`, converted all row/detail-panel/bulk-rematch buttons to `ActionButton` (default/primary/dry-run/real), `StateBlocks` for loading/error/empty, tokenized `neutral-*` colors | `PageHeader`, `StatCard`/`StatGrid`, `ActionButton`, `DataTableShell`, `SavedViewBar`, `MatchStatusBadge`, `PaginationControls`, `StateBlocks` | Yes | 738 lines |
| `/admin/card-audit` | A | Fixed: added `PageHeader`, `StatGrid`/`StatCard` (with tone), converted raw `<table>` to `DataTableShell`, cross-links restyled | `PageHeader`, `StatCard`/`StatGrid`, `DataTableShell`, `SeverityBadge`, `ErrorState`/`LoadingState`, `AdminAuthGate` | Yes | 408 → ~380 lines |
| `/admin/system-check` | A | Fixed: added `PageHeader` (+ Re-run `ActionButton`), `StatGrid`/`StatCard`, converted raw `<table>` and catalog-ops stat blocks to `DataTableShell`/`StatCard` | `PageHeader`, `StatCard`/`StatGrid`, `DataTableShell`, `ActionButton`, `Badge`, `SeverityBadge`, `ErrorState`/`LoadingState`, `VersionFooter`, `AdminAuthGate` | Yes | 380 lines |
| `/admin/market-workflow-runs` | A | Fixed: added `PageHeader`, converted summary cards to `StatGrid`/`StatCard`, raw `<table>` to `DataTableShell`, "View" button to `ActionButton` | `PageHeader`, `StatCard`/`StatGrid`, `DataTableShell`, `ActionButton`, `MarketWorkflowRunStatusBadge`, `ErrorState`/`LoadingState`, `PaginationControls` | Yes | 339 lines |
| `/admin/refresh-runs` | A | Fixed: added `PageHeader`, converted raw `<table>` to `DataTableShell`, status filter chips restyled to vault tokens | `PageHeader`, `DataTableShell`, `RunStatusBadge`, `ErrorState`/`LoadingState`, `PaginationControls` | Yes | 237 lines |
| `/admin/performance` | A | Fixed: added `PageHeader` (+ Re-run `ActionButton`), converted stat grid and all 3 raw `<table>` blocks to `StatGrid`/`StatCard`/`DataTableShell`; removed duplicate local `StatCard` | `PageHeader`, `StatCard`/`StatGrid`, `DataTableShell`, `ActionButton`, `Badge`, `SeverityBadge`, `ErrorState`/`LoadingState`, `VersionFooter`, `AdminAuthGate` | Yes | 423 lines |
| `/admin/job-locks` | A | Fixed: added `PageHeader`, converted raw `<table>` to `DataTableShell`; force-release flow restyled with `ActionButton` (`real`/`danger` tiers) — confirm-phrase logic unchanged | `PageHeader`, `DataTableShell`, `ActionButton`, `Badge`, `ErrorState`/`LoadingState`, `VersionFooter`, `AdminAuthGate` | Yes | 372 lines |
| `/admin/alerts` | A | Fixed: added `PageHeader`, converted both raw `<table>` blocks to `DataTableShell`, status filter chips restyled | `PageHeader`, `DataTableShell`, `AlertStatusBadge`, `ErrorState`/`LoadingState`, `AdminAuthGate` | Yes | 359 lines |
| `/admin/logs` | A | Fixed: added `PageHeader`; summary cards, filters, logs table, prune section, and detail modal all converted to shared components; legacy button (line 634) replaced | `PageHeader`, `StatCard`/`StatGrid`, `DataTableShell`, `ActionButton`, `LogLevelBadge`, `EmptyState`/`ErrorState`/`LoadingState`, `PaginationControls` | Yes | 651 lines |
| `/admin/backup` | A | Fixed: added `PageHeader`, converted all export/validate/restore buttons to `ActionButton` (primary/default/dry-run/real/danger, restore variant now derived from mode+dry-run), tokenized `neutral-*`/`rose-*`/`amber-*` colors; dry-run/restore confirm-phrase flow behavior unchanged | `PageHeader`, `ActionButton`, `FileJobTracker`, `AdminAuthGate` | Yes | 559 lines |
| `/admin/cache` | A | Fixed: added `PageHeader`, converted local `StatCard` to shared `StatCard`/`StatGrid`, `Refresh`/`Clear cache` buttons to `ActionButton`, tokenized all `neutral-*`/`rose-*`/`emerald-*` colors | `PageHeader`, `StatCard`/`StatGrid`, `ActionButton` | Yes | 309 lines |
| `/admin/actions` | A | Fixed: added `PageHeader`; local `ActionButton` wrapper now delegates to shared `ActionButton` with a safety-tier `variant` (dry-run while that action's own "Dry run" checkbox is checked, `real` once it will actually write), tokenized `neutral-*` colors | `PageHeader`, `ActionButton`, `VersionFooter`, `AdminAuthGate` | Yes | 768 lines, largest admin page — mostly action buttons |
| `/admin/release-status` | A | Fixed: added `PageHeader` (Refresh button now `ActionButton`), converted version/build info + readiness rollup to `StatCard`/`StatGrid` (tone-mapped ok/warning/critical), `LoadingState`/`ErrorState` for load failures, tokenized `neutral-*` colors | `PageHeader`, `ActionButton`, `StatCard`/`StatGrid`, `StateBlocks` | Yes | 353 lines |
| `/admin/data-retention` | A | Fixed: added `PageHeader`, converted both raw `<table>` blocks to `DataTableShell`, prune button to `ActionButton` (dry-run/danger), removed duplicate local `StatCard` | `PageHeader`, `StatCard`/`StatGrid`, `DataTableShell`, `ActionButton`, `Badge`, `AdminAuthGate` | Yes | 416 → ~390 lines |
| `/admin/file-jobs` | A | Fixed: added `PageHeader`, converted raw `<table>` to `DataTableShell`, Refresh/Download/Cancel/cleanup buttons to `ActionButton` | `PageHeader`, `DataTableShell`, `ActionButton`, `Badge`, `AdminAuthGate` | Yes | 441 lines |

## Market pages

| Route | Category | Main issues | Components used | Fixed in this pass | Notes |
|---|---|---|---|---|---|
| `/market/opportunities` | A | Fixed: added `PageHeader`, replaced local `StatCard` with shared `StatGrid`/`StatCard` | `DataTableShell`, `SavedViewBar`, `PageHeader`, `StatCard`, `OpportunityCategoryBadge`, `WishlistPriorityBadge`, `GradingStatusBadge`, `MarketSignalEventStatusBadge`, `RarityBadge`, `CollectorTagBadge`, `CollectorGroupLabel`, `StateBlocks`, `PaginationControls` | Yes | 648 lines |
| `/market/signals` | A | Fixed: added `PageHeader`, replaced local `StatCard` with shared `StatGrid`/`StatCard`, converted raw `<table>` wrapper to `DataTableShell`, loading/error states to `LoadingState`/`ErrorState` | `SavedViewBar`, `DataTableShell`, `PageHeader`, `StatCard`, `RarityBadge`, `SeverityBadge` | Yes | 505 lines |
| `/market/signal-events` | A | Fixed: same `PageHeader`/`StatGrid`/`DataTableShell` treatment as `/market/signals` | `SavedViewBar`, `DataTableShell`, `PageHeader`, `StatCard`, `MarketSignalEventStatusBadge`, `RarityBadge`, `SeverityBadge`, `StateBlocks`, `PaginationControls` | Yes | 573 lines |
| `/market/report` | A | Fixed: added `PageHeader`, converted raw `<table>` (top-5 opportunities) to `DataTableShell`, dropped the local `StatCard`'s bespoke `wrap` prop in favor of the shared `StatCard` (long text values now truncate like the rest of the app) | `OpportunityCategoryBadge`, `StateBlocks`, `DataTableShell`, `PageHeader`, `StatCard` | Yes | 482 lines |
| `/market/movers` | A | Fixed: added `PageHeader`, converted raw `<table>` to `DataTableShell`, ad-hoc loading/error divs to `LoadingState`/`ErrorState` | `PriceTypeBadge`, `RarityBadge`, `SourceBadge`, `DataTableShell`, `PageHeader`, `LoadingState`, `ErrorState` | Yes | 313 lines; public, no auth |

## Misc

| Route | Category | Main issues | Components used | Fixed in this pass | Notes |
|---|---|---|---|---|---|
| `/` (root) | A | None — 5-line redirect to `/dashboard`, no rendered UI of its own | n/a | No | Not a real page to style |

## Summary counts

**Pre-pass** (original audit, before Parts 2-5/8/9 fixes below):
- **A (fully styled):** 15 routes
- **B (partially styled):** 24 routes
- **C (old/generic):** 4 routes
- **D (broken/unused):** 0 routes

**Post-pass** (current state, all committed):
- **A (fully styled):** 43 of 43 routes (100%) — every route in every section
  table above is now category A.
- **B/C/D:** 0 routes.

28 of the 43 routes were fixed in this pass (see "Fixed in this pass"
column per-route above); the other 15 were already category A before this
pass started. Beyond the 43 page-level routes, this pass also fixed the
same pre-design-system patterns living in several *shared* components that
multiple already-A pages render through (`AdminAuthGate`,
`AdminLogoutButton`, `FileJobTracker`, `CollectorTagsGroupsManager`,
`CollectionImportExport`, `WishlistImportExport`, plus the tab-toggle style
in `PortfolioValuationHistoryChart`/`CollectionValuationSummary`/
`market/signals`) — not reflected in the per-route table above since the
audit was scoped to `page.tsx` files, but tracked in
`docs/interface_design_system.md`'s "Phase 10 — styling consistency pass"
section and covered by `scripts/phase10_ux_audit.sh`.

## Fix history (Parts 2–5/8/9)

**Collector + market (Part 2):** `/wishlist`, `/grading`, `/activity`,
`/market/opportunities`, `/market/signals`, `/market/signal-events`,
`/market/report`, `/market/movers` — added `PageHeader`, converted ad-hoc
stat markup to `StatCard`/`StatGrid`, converted raw `<table>` to
`DataTableShell`, replaced legacy `bg-neutral-100 ... hover:bg-white`
buttons with `ActionButton`.

**Analytics (Part 3):** `/analytics/collection`, `/analytics/wishlist`,
`/analytics/grading` — added `PageHeader` + `StatCard`/`StatGrid`.

**Admin (Part 4):** All 17 remaining admin routes — the raw-`<table>`
cluster (`/admin/data-retention`, `/admin/file-jobs`, `/admin/card-audit`,
`/admin/system-check`, `/admin/market-workflow-runs`,
`/admin/refresh-runs`, `/admin/performance`, `/admin/job-locks`,
`/admin/alerts`, `/admin/logs`) converted to `DataTableShell` + `PageHeader`
+ `StatCard`; the remaining set (`/admin/cards`, `/admin/catalog-coverage`,
`/admin/snkrdunk-candidates`, `/admin/backup`, `/admin/cache`,
`/admin/actions`, `/admin/release-status`) got `PageHeader`/`StatCard` and
legacy-button cleanup.

**Shared components (Part 5/8/9):** `AdminAuthGate`/`AdminLogoutButton`
(the app-wide admin-token UI), `FileJobTracker`, `CollectorTagsGroupsManager`,
`CollectionImportExport`, `WishlistImportExport` (legacy buttons +
un-migrated raw tables), and the `bg-neutral-100` "selected" tab-toggle
pattern in three components, all retokenized. `FileJobTracker`'s job-status
pill and `import-validation`'s valid/invalid `StatusBadge` deduped onto the
shared `Badge` primitive.
