# Interface design system — "TCG Vault"

This document describes the frontend visual identity and shared component
system introduced for the collector/admin dashboard (`apps/web`). It exists
so future work extends the same system instead of re-inventing ad hoc
styling per page.

## Visual identity summary

Dark collector terminal + TCG vault + market dashboard. The product is a
serious, dense, data-first tool for collectors and traders who watch prices,
P/L, spreads, source gaps, stale data, and buy/sell decisions — plus an
admin surface for catalog imports, matching, source mappings, duplicates,
and price source health.

Core feeling: serious, dense, premium, collector-focused, slightly
underground. Explicitly **not**: generic SaaS, Web3 gradient UI, gacha/casino,
or childish anime UI.

## Tokens

Defined once in `apps/web/src/app/globals.css` as plain CSS variables in
`:root`, then aliased into Tailwind v4's `@theme inline` block so the same
values are available both as `var(--bg-page)` in hand-written CSS and as
generated Tailwind utilities (`bg-bg-page`, `text-text-primary`, ...).

| Token | Value | Tailwind utility |
|---|---|---|
| `--bg-page` | `#0B0B0D` | `bg-bg-page` |
| `--bg-surface` | `#141416` | `bg-bg-surface` |
| `--bg-elevated` | `#1B1B1F` | `bg-bg-elevated` |
| `--bg-card` | `#202024` | `bg-bg-card` |
| `--border-default` | `#2C2C32` | `border-border-default` |
| `--border-muted` | `rgba(255,255,255,0.08)` | `border-border-muted` |
| `--text-primary` | `#F4F4F5` | `text-text-primary` |
| `--text-secondary` | `#A1A1AA` | `text-text-secondary` |
| `--text-muted` | `#71717A` | `text-text-muted` |
| `--text-faint` | `#52525A` | `text-text-faint` |
| `--accent-gold` | `#D6A84F` | `bg-/text-accent-gold` |
| `--accent-gold-hover` | `#E6BD6A` | `bg-/text-accent-gold-hover` |
| `--signal-green` | `#22C55E` | `bg-/text-signal-green` |
| `--signal-red` | `#EF4444` | `bg-/text-signal-red` |
| `--signal-blue` | `#38BDF8` | `bg-/text-signal-blue` |
| `--signal-purple` | `#A78BFA` | `bg-/text-signal-purple` |
| `--signal-warning` | `#F59E0B` | `bg-/text-signal-warning` |

Radii: `rounded-control` (6px, inputs/small controls), `rounded-panel` (8px,
cards/panels), `rounded-panel-lg` (10px, larger elevated panels),
`rounded-modal` (12px, modals only).

Existing badge components (`RarityBadge`, `SourceBadge`, `PriceTypeBadge`,
`CollectionStatusBadge`, etc.) keep their original Tailwind hues (rose/amber/
emerald/sky/violet) rather than being rewritten onto the raw `--signal-*`
hex values — they already map color→meaning consistently, and forcing every
existing badge onto new hex values would be high-churn for no visual gain.
New shared badges (`RiskBadge`, `ConfidenceBadge`, `SourceHealthBadge`,
`DecisionBadge`) use the new signal tokens/utility classes directly.

## Typography

- `next/font/google` self-hosts IBM Plex Sans (`--font-ibm-plex-sans`) and
  IBM Plex Mono (`--font-ibm-plex-mono`), wired in `app/layout.tsx` and
  consumed by the `--font-sans`/`--font-mono` theme tokens (with system-font
  fallback chains, so a slow/missing weight degrades gracefully).
- Use `.mono` (mono font + tabular numerals) for prices, IDs, card codes,
  timestamps, and compact metadata. Use `.tabular` alone when the font
  should stay sans but numerals must still align.
- Minimum label text: **11px** (`text-[11px]`). Minimum table text: **12px**
  (the `.data-table` class sets this). Sub-11px (`text-[10px]`/`text-[9px]`)
  is only acceptable for genuinely decorative micro-labels (a chevron, a
  keyboard-shortcut hint) — never for scannable metadata like a set code,
  score, or date.
- `text-text-secondary` (`#A1A1AA`) for metadata users need to scan.
  `text-text-muted`/`text-text-faint` only for low-priority supporting text.

## Spacing / density

Dense throughout — compact stat cards, compact filters, tight table rows.
Page padding follows the existing `mx-auto max-w-7xl px-4 py-6` convention;
no marketing-page-style whitespace.

## Layout shell

`components/ui/AppShell.tsx` (+ `SidebarNav.tsx`, `TopBar.tsx`) replaces the
old flat `AppHeader` nav bar with a sidebar (Collector section / divider /
Admin section, active-route highlighting) + a compact sticky topbar (product
mark, global search-as-link with the existing Ctrl/Cmd+K shortcut, sign-in/
out). `components/AppHeader.tsx` is now a one-line re-export of `AppShell`,
so every existing page picks up the new shell automatically without any
per-page edit.

**Nav mapping notes:**
- Routes the design brief didn't explicitly list (`/analytics/collection`,
  `/analytics/wishlist`, `/analytics/grading`, the `/market/*` sub-pages)
  are nested under their closest parent nav item rather than removed.
- Several existing admin routes not named in the brief (alerts, cache,
  data-retention, file-jobs, job-locks, market-workflow-runs, refresh-runs,
  release-status) live in a collapsed "Admin · More" group — reachable, not
  promoted.
- "Source Mappings" from the brief's nav list has no corresponding route
  (only `/admin/source-mapping-quality` exists) and was intentionally
  **not** added as a nav entry, per "do not invent route links".
- The topbar does **not** show a global source-health/last-sync badge —
  faking it (or firing an admin API call on every anonymous page load)
  would violate "static placeholder should not fake health". Real
  freshness/health data stays on `/dashboard` (its `data_freshness` widget)
  and `/admin/price-source-health` (which already fetches it).

## Component usage rules

All new shared components live under `apps/web/src/components/ui/`.
Existing components (badges, `StateBlocks`, `PaginationControls`, `FormField`)
were kept in place and either left as-is or restyled internally — their
export names and prop APIs are unchanged, so no call site needed editing
for the tokens/shell to apply.

| Component | Use for |
|---|---|
| `PageHeader` | Title + description + actions slot (replaces repeated h1/p blocks) |
| `StatCard` / `StatGrid` | Dense stat tiles (replaces 4x copy-pasted stat-tile components) |
| `FilterBar`, `FILTER_INPUT_CLASS`, `FILTER_LABEL_CLASS` | Filter row wrapper + consistent input styling |
| `DataTableShell` + `.data-table` | Table outer chrome, empty state, horizontal scroll |
| `PriceCell` / `PriceBasisLabel` | Every price display — see rules below |
| `ActionButton` | All buttons — variant encodes admin-safety tier (see below) |
| `AdminActionPanel` | Groups action buttons + description for an admin action block |
| `ConfirmActionModal` | Confirmation gate for real/destructive admin actions (see below) |
| `RiskBadge`, `ConfidenceBadge`, `SourceHealthBadge`, `DecisionBadge`, `VariantBadge` | Canonical badge vocabularies (see Badges below) |
| `CardImageFrame`, `CardIdentityBlock`, `CardVaultTile`, `CardPricePanel`, `SourceComparisonPanel` | Collector vault / card-identity treatment (see below) |
| `SkeletonBlock` / `SkeletonRows` | Loading shimmer (used inside `LoadingState`) |

## Price display rules

Every important price display must show:
- A JPY value in `.mono .tabular` numerals — **never** raw `null`/`undefined`;
  missing values render as literal text `"not available"`.
- A source/basis label near the value: `SNKRDUNK floor`, `Yuyu-Tei sell`,
  `Yuyu-Tei buy`, `Raw market`, or `Graded adjusted` — never a bare,
  ambiguous `"Market"` value with no basis stated.
- A stale badge when the underlying observation is old (`PriceCell` flags
  anything older than 48h by default).
- Percent alongside JPY when both exist.

`PriceCell` (`components/ui/PriceCell.tsx`) implements all of this in one
place: pass `signed` for P/L-style deltas (colors green/red by sign via
`.price-positive`/`.price-negative`; unsigned prices stay neutral), and
either `source`+`priceType` or `mode` ("raw_market"/"graded_adjusted") for
the basis chip.

## Card vault rules

- `CardImageFrame` renders a slab/vault-style frame (inner border, dark
  sleeve background) for a card image. When `imageUrl` is missing, it shows
  a clean placeholder with `card_code`, `rarity`, and `set_code` — never a
  broken image or blank box.
- Rare variants (Manga, SP, SEC via `VariantBadge`'s gold family; Parallel,
  Alt Art via its purple family) get a **restrained** accent
  (`.glow-gold`/`.glow-purple` — a soft 1px ring + subtle glow). No flashing,
  no casino-style shine.
- Card detail pages (`/cards/[id]`) prioritize, top to bottom: card image →
  card_code/name/rarity/variant/language (`CardIdentityBlock` with
  `asHeading`) → ownership/grading status → price source comparison.
- `CardVaultTile` is the compact tile for top-holdings/wishlist-hit/
  priority-card lists: image or placeholder, identity, badges, price with
  basis, optional status pill.

## Admin safety rules

`ActionButton` variants map directly to the admin-safety tiers:

| Variant | Look | Use for |
|---|---|---|
| `default` | Neutral border | Read-only / low-stakes actions |
| `primary` | Gold fill | The "main" positive action on a page (Save, Replace & approve) |
| `dry-run` | Blue/cyan dashed outline | Any dry-run/preview-only action |
| `preview` | Gold outline | A preview step that isn't yet a real write |
| `real` | Red outline (not filled) | A real write that's about to happen, before the confirm gate |
| `danger` | Solid red | The final confirmed destructive/real action |

`ConfirmActionModal` is the confirmation gate itself, in two configurations:
- **No `confirmPhrase`**: plain Confirm/Cancel dialog with an optional
  "affected records" preview — used for single-row or small destructive
  actions (e.g. source-mapping-quality's row-level reject/deactivate,
  replacing the old bare `window.confirm()` calls).
- **With `confirmPhrase`** (`"MERGE"`, `"RUN"`, `"RESTORE"`, `"IMPORT"`):
  the confirm button stays disabled until the exact word is typed — used
  for higher-blast-radius actions (card-duplicates' merge execute,
  source-mapping-quality's bulk real recheck run).

No page in this pass adds new destructive *behavior* — only the
confirmation/safety UI around actions that already existed.

## Table rules

`DataTableShell` + the `.data-table` CSS class (in `globals.css`) together
give: a sticky header, ~12px+ text, mono/tabular numeric cells (add `.mono
.tabular` per cell), a subtle row divider, a hover highlight, horizontal
scroll for wide tables, and a built-in empty state (`isEmpty`/`emptyLabel`
props) — no more hand-rolled `overflow-x-auto rounded border` wrappers.
`.data-table tbody tr.row-warning` is available for a very subtle
attention-flag background (e.g. a stale/missing-data row) — use sparingly,
never as a primary signal (pair it with a badge).

## Badge color meaning

| Badge | Vocabulary | Color mapping |
|---|---|---|
| `RiskBadge` | low / medium / high / critical | green / blue / amber / red |
| `ConfidenceBadge` | exact / high / medium / low / very_low / unknown | gold / green / blue / amber / red / neutral |
| `SourceHealthBadge` | healthy / degraded / stale / blocked / error / unknown | green / blue / amber / red / red / neutral |
| `DecisionBadge` | review_buy / review_sell / wait / hold / monitor / grade_first / missing_data / skip | green / blue / amber / neutral / cyan / purple / red / neutral |
| `RarityBadge` (existing) | L / SR / SEC / R / UC / C | amber / violet / rose / sky / emerald / neutral |
| `SourceBadge` (existing) | Yuyu-Tei / SNKRDUNK | sky / fuchsia |
| `VariantBadge` | Manga / SP / SEC (gold family), Parallel / Alt Art (purple family), other (neutral) | see Card vault rules |

Some pages keep a locally-scoped vocabulary rather than being forced onto a
canonical badge when the two don't cleanly map — e.g.
source-mapping-quality's own `ok`/`review`/`warning`/`critical` risk labels
match its own filter-button vocabulary exactly, so it keeps its local
`RiskBadge` (built on the shared `Badge` primitive) instead of adopting the
app-wide low/medium/high/critical one, which would create a labeling
mismatch against its own filters.

## Do-not list

- Do not make it generic SaaS.
- Do not use bright Web3 gradients.
- Do not use anime screenshots or copyrighted card/franchise art — this
  redesign adds no new external or copyrighted assets.
- Do not make the UI look like a casino/gacha (no flashing, no shine sweeps).
- Do not hide the source/basis for a price.
- Do not render literal `null`/`undefined` — always a descriptive fallback
  ("not available", "missing", or "—" per existing convention).
- Do not use a red/danger button for a real action without a confirmation
  step in front of it.
- Do not make tables spacious — keep them dense.
- Do not use sub-11px text for anything the user needs to scan.

## Pages fully migrated in this pass

`/dashboard`, `/collection`, `/search`, `/cards/[id]`,
`/analytics/digest`, `/analytics/buy-decisions`, `/analytics/sell-decisions`,
`/analytics/portfolio-risk`, `/admin/catalog-ops`, `/admin/import-validation`,
`/admin/card-duplicates`, `/admin/source-mapping-quality`,
`/admin/price-source-health`.

Every other existing page gets the new shell/tokens/fonts for free (via the
`AppHeader` shim + global CSS) but keeps its previous internal markup.

## TODO — pages not yet deeply migrated

These pages render inside the new shell already, but their internal
tables/stat tiles/badges have not yet been converted to the shared
components above. Recommended order: highest-traffic collector pages
first, then remaining admin utility pages.

- `/wishlist`
- `/grading`
- `/activity`
- `/market/movers`, `/market/opportunities`, `/market/report`,
  `/market/signal-events`, `/market/signals`
- `/analytics/collection`, `/analytics/wishlist`, `/analytics/grading`
- `/admin/cards`, `/admin/card-audit`, `/admin/catalog-coverage`,
  `/admin/snkrdunk-candidates`, `/admin/system-check`
- `/admin/actions`, `/admin/alerts`, `/admin/backup`, `/admin/cache`,
  `/admin/data-retention`, `/admin/file-jobs`, `/admin/job-locks`,
  `/admin/logs`, `/admin/market-workflow-runs`, `/admin/performance`,
  `/admin/refresh-runs`, `/admin/release-status`
