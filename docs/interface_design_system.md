# Interface design system — CardPirate Atlas

This document describes the frontend visual identity and shared component
system introduced for the collector/admin dashboard (`apps/web`). It exists
so future work extends the same system instead of re-inventing ad hoc
styling per page. For naming, voice, and legal constraints (as opposed to
CSS tokens and component conventions), see `docs/brand.md`.

## Visual identity summary

An original maritime-cartography collector identity, warm-dark rather than
cold-terminal: a collector maps and tends a real collection first, with
Market Index and dense operational data as supporting context. The admin
surface stays dense/data-first (catalog imports, matching, source mappings,
duplicates, price source health) - see `docs/brand.md` "Public vs. admin".

Core feeling on collector/public pages: warm, premium, collector-led,
artwork-forward. Explicitly **not**: generic SaaS, Web3 gradient UI,
gacha/casino, childish anime UI, or a crypto trading terminal.

## Tokens

Defined once in `apps/web/src/app/globals.css` as plain CSS variables in
`:root`, then aliased into Tailwind v4's `@theme inline` block so the same
values are available both as `var(--bg-page)` in hand-written CSS and as
generated Tailwind utilities (`bg-bg-page`, `text-text-primary`, ...).

| Token | Value | Tailwind utility |
|---|---|---|
| `--bg-page` | `#171717` | `bg-bg-page` |
| `--bg-surface` | `#1D1E1F` | `bg-bg-surface` |
| `--bg-elevated` | `#242528` | `bg-bg-elevated` |
| `--bg-card` | `#363638` | `bg-bg-card` |
| `--border-default` | `#3A3B3D` | `border-border-default` |
| `--border-muted` | `rgba(244,240,232,0.08)` | `border-border-muted` |
| `--text-primary` | `#F4F0E8` | `text-text-primary` |
| `--text-secondary` | `#A9A395` | `text-text-secondary` |
| `--text-muted` | `#8B8672` | `text-text-muted` |
| `--text-faint` | `#6B6656` | `text-text-faint` |
| `--parchment` | `#E8DEC7` | `bg-/text-parchment` |
| `--accent-gold` | `#C79A4B` | `bg-/text-accent-gold` |
| `--accent-gold-hover` | `#D9AE66` | `bg-/text-accent-gold-hover` |
| `--accent-teal` | `#4F8D86` | `bg-/text-accent-teal` |
| `--accent-teal-hover` | `#5FA39B` | `bg-/text-accent-teal-hover` |
| `--accent-coral` | `#C8624D` | `bg-/text-accent-coral` |
| `--signal-green` | `#22C55E` | `bg-/text-signal-green` |
| `--signal-red` | `#EF4444` | `bg-/text-signal-red` |
| `--signal-blue` | `#38BDF8` | `bg-/text-signal-blue` |
| `--signal-purple` | `#A78BFA` | `bg-/text-signal-purple` |
| `--signal-warning` | `#F59E0B` | `bg-/text-signal-warning` |

Colour rules (full rationale in `docs/brand.md`): gold = rarity/milestones,
teal = navigation/discovery/trusted info, coral = a limited warning/emphasis
accent. Collector-facing price movement deliberately does not get a
dominant red/green treatment - `--signal-green`/`--signal-red` stay reserved
for the admin/operational surface (risk levels, match confidence, dense
tables), unchanged by the rebrand.

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

- `next/font/google` self-hosts Manrope (`--font-manrope`, UI/body) and
  Fraunces (`--font-fraunces`, editorial display/headings), plus IBM Plex
  Mono (`--font-ibm-plex-mono`, unchanged) - all wired in `app/layout.tsx`
  and consumed by the `--font-sans`/`--font-display`/`--font-mono` theme
  tokens, each with a system-font (and CJK) fallback chain via `display:
  "swap"`, so a slow/missing weight degrades gracefully with no layout
  shift and `name_jp` still renders correctly.
- Use `font-display` (the Tailwind utility generated from `--font-display`)
  sparingly - headings, hero copy, the wordmark - never body text or dense
  tables, which stay on `font-sans`.
- Use `.mono` (mono font + tabular numerals) for prices, IDs, card codes,
  timestamps, and compact metadata. Use `.tabular` alone when the font
  should stay sans but numerals must still align.
- Minimum label text: **11px** (`text-[11px]`). Minimum table text: **12px**
  (the `.data-table` class sets this). Sub-11px (`text-[10px]`/`text-[9px]`)
  is only acceptable for genuinely decorative micro-labels (a chevron, a
  keyboard-shortcut hint) — never for scannable metadata like a set code,
  score, or date.
- `text-text-secondary` (`#A9A395`) for metadata users need to scan.
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
| `SavedViewBar`, `SaveViewModal`, `ManageSavedViewsModal`, `SavedViewPill`, `PinnedViewsSection` | Saved filter/sort/column presets (see below) |
| `CommandPalette`, `KeyboardShortcutsModal`, `QuickActionBar`, `WorkflowShortcutsSection` | Global Cmd/Ctrl+K palette, shortcuts reference, per-page shortcut pills (see "Command palette and workflow shortcuts" below) |

## Saved views

Single-user saved filter presets (name a filter combination, reapply it later, optionally pin/default it) - backed by the `/saved-views` API (see docs/operations.md, "Saved views workflow"). No multi-user accounts or new permissions: the feature reuses the existing per-session bearer-token auth (`require_current_user`) purely as a sign-in gate, not for per-account scoping - `saved_views` is one shared, global preset store, like `dashboard_preferences`.

- **`SavedViewBar`** is the per-page integration point. Every page that has it builds a plain `currentFilters` object from its own filter `useState` variables and passes an `onApply` that calls the matching setters back - none of this app's pages read filters from the URL, so applying a view always means updating local state, never a query-string rewrite. Pagination offset is never included (every paginated page already resets its own offset to 0 on any filter change - persisting it would just get immediately stomped).
- **`SaveViewModal`** is the name/description/pinned/default/density form, in the same modal chrome as `ConfirmActionModal` (`rounded-modal`, `bg-bg-elevated`) but not a confirm-phrase gate - just a form.
- **`ManageSavedViewsModal`** lists every saved view for the current page's route+view_type: pin/unpin, set/clear default, edit, delete (delete goes through `ConfirmActionModal`'s plain no-phrase mode).
- **`SavedViewPill`** is the one deliberately fully-rounded badge shape in the app (`!rounded-full`, gold-tinted) - everything else uses the small `rounded-control` corner radius. Reserved for "this saved view is currently active," nothing else.
- **`PinnedViewsSection`** renders pinned views across every scope on `/dashboard` (as a standalone section, not a `DashboardWidgetId` - it isn't personalization-scoped, so it doesn't touch `DashboardPreferences`) and `/admin/catalog-ops` (as "Pinned Admin Views," between the stat tiles and the nav-card grid). Links only navigate to the bare `route_path` - they can't pre-apply the view's filters (see the URL-params limitation above), so visiting the page and picking the view from its own `SavedViewBar` is still required. Unrelated to `DashboardPreferences.pinned_cards` (an existing, separately-schemaed, currently-unused field for pinning individual *cards*, not saved views) - don't conflate the two.
- **Density**: `SaveViewModal`'s compact/comfortable selector is stored on the row (`density`) but no page currently reads it back - it's schema-ready for a future page to start honoring, not yet wired to any actual layout change. Whichever value a page eventually uses it for, the "dense" 11px/12px minimums from this doc still apply in both modes - `comfortable` should only ever mean more row padding, never smaller text.

## Command palette and workflow shortcuts

Global `Cmd/Ctrl+K` command palette (navigation + card search + saved views
+ recent workflows), a per-page `QuickActionBar`, a keyboard-shortcuts
reference modal, and a dashboard "Workflow Shortcuts" section - navigation
convenience layered on top of the existing sidebar, not a replacement for
it.

- **`CommandPalette`** mounts once, globally, in `AppShell` (so every page
  gets it with zero per-page wiring). Sources merged per keystroke: (1) the
  static `commandRegistry.ts` list (fuzzy-ish substring match against
  label/description/keywords), (2) saved views (`fetchSavedViews`, fetched
  once when the palette opens, filtered client-side - not on every
  keystroke), (3) recent workflows (from `localStorage`, shown when the
  query is empty), (4) card search (`fetchSearch({ types: ["cards"] })`,
  only once the query is 2+ characters, 250ms debounced, stale requests
  dropped via a request-id guard). `Cmd/Ctrl+K` toggles it, `Esc` closes,
  `↑`/`↓` move the selection, `Enter` activates.
- **`commandRegistry.ts`** is a static list covering only routes that
  actually exist - if a route named in a future brief doesn't exist yet
  (e.g. there is no standalone `/admin/source-mappings`, only
  `/admin/source-mapping-quality`), it's omitted rather than linked as a
  dead end, same rule `SidebarNav` already follows.
- **Admin/dangerous commands never execute directly from the palette.** A
  global component can't reach into a specific page's mounted React state,
  so every command in the registry is navigation-only - it routes to the
  admin page where the real dry-run/confirm button already lives, it never
  re-implements that page's write logic. The palette's `dangerous` +
  `ConfirmActionModal` typed-phrase code path is implemented generically
  (in case a future command needs it), but no command in the current
  registry sets `dangerous: true`.
- **`QuickActionBar`** is the actual place a real dry-run/preview trigger
  lives: a small, deliberately dumb row of pills per page, each either
  `{ label, href }` (a `Link`) or `{ label, onClick, variant? }` (an
  `ActionButton` calling a handler the page already owns - e.g.
  source-mapping-quality's own `runRecheck(true)`, card-duplicates' own
  `runBulkPreview()`). It never contains its own mutation logic.
- **Recent-workflow tracking is `localStorage`-only** (`lib/recentWorkflows.ts`),
  not a new backend table - this is ephemeral, single-browser, low-stakes
  UX convenience, not data that needs to survive a device change or appear
  in backups. The stored shape mirrors what a backend table would look
  like, so it could migrate later with no data-shape change. It never
  stores an admin token, file contents, or confirmation text - only
  `item_type`/`label`/`route_path`/`payload_json`/`last_used_at`/`usage_count`.
- **Keyboard shortcuts**: `Cmd/Ctrl+K` (palette), `Esc` (close), `/`
  (open palette, when nothing else is focused and no modal is open), `?`
  (open `KeyboardShortcutsModal`), and `g` then a key for direct
  navigation (`g d` dashboard, `g c` collection, `g v` vault, `g w`
  wishlist, `g b` buy decisions, `g s` sell decisions, `g r` portfolio
  risk, `g a` admin catalog ops). All single-key shortcuts are guarded
  against firing while focus is inside an input/textarea/select/
  contenteditable, or while the palette/shortcuts modal is open - `Esc`
  and `Cmd/Ctrl+K` are the only two that always fire.
- **Saved-view palette entries navigate to the bare `route_path`** - same
  limitation `PinnedViewsSection` already documented: no page in this app
  reads filters from the URL, so a saved view's filters can't be
  pre-applied via a link click.

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
- `CardVaultTile` is the tile for top-holdings/wishlist-hit/priority-card
  lists and the `/collection/vault` grid: image or placeholder, identity,
  badges, price with basis, optional status pill.

### Card detail layout (full hero + panel-grid version)

`/cards/[id]` is an inventory record + trading terminal, not a flat stack of
sections. Order, top to bottom:

1. **Hero**: `CardImageFrame` (large, `size="lg"`) + `CardIdentityBlock`
   (`asHeading`) + a compact metadata grid (cost/power/counter/attribute/
   color/type/artist/character/release date - each field only rendered if
   the card actually has it; catalog enrichment is sparse, so this section
   can legitimately show very little for an older card) + effect/trigger
   text (only when present).
2. **Ownership / wishlist / grading** (`OwnershipSummaryPanel` /
   `WishlistSummaryPanel` / `GradingSummaryPanel`, side by side on wide
   screens) - each has its own quiet empty state ("Not in collection yet.",
   "Not on wishlist.", "No grading submissions.") and its own existing
   add-action slotted in, never a shared generic "no data" box.
3. **Price source panel** (`CardPricePanel`, 4 lines: Yuyu-Tei sell/buy,
   SNKRDUNK floor, SNKRDUNK sold - the last one is genuinely new to this
   panel and follows the same "not available" fallback as the other three).
4. ~~Market context (`MarketContextPanel`)~~ - **removed from this page** in
   the collector-first redesign audit (see `docs/market_index.md` "Market
   Index wording") - opportunity scores + buy/sell-decision links are exactly
   the trading-signal framing that audit's Phase 8 rules out for a page every
   anonymous visitor reaches. `MarketContextPanel` itself, and the signal-
   events/opportunities APIs/pages it linked to, are unchanged and still
   directly reachable - just no longer rendered here.
5. **Notes/activity** (`CardActivityPanel`).
6. **Admin mini-panel** (source mappings) - only rendered for admin-token
   holders, styled with `.admin-preview` (the gold-outline admin treatment,
   not a full page section) to read as clearly admin-only at a glance.
7. Price history chart + price observations table (unchanged from before).

### Card vault tile density

`CardVaultTile`'s `density` prop is `"compact" | "standard" | "showcase"`
(default `"standard"`):
- `"compact"` - image+code+name+one price line+status pill only. Used for
  dashboard/pinned-card contexts where many tiles need to fit densely.
- `"standard"` - adds quantity/condition, a second signed P&L price line,
  and a target-sell/target-hit row. The default for `/collection/vault`.
- `"showcase"` - same content as `"standard"` with a larger
  (`CardImageFrame size="md"`) image - a deliberate, occasional "look at
  this card" mode, not the default grid density (avoid making every page
  showcase-dense, which would fight the "dense throughout" rule elsewhere
  in this doc).

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

## Pages fully migrated

As of the Phase 10 styling-consistency pass (see "Phase 10 — styling
consistency pass" below and `docs/frontend_styling_audit.md` for the
route-by-route detail), every one of the 43 actual routes under
`apps/web/src/app` is category A ("fully styled") except `/` itself, which
is a 5-line redirect with no rendered UI of its own. There is no longer a
"not yet migrated" list — see "Remaining known styling debt" below for the
few small, deliberately-deferred items instead.

## Phase 10 — mobile/tablet responsiveness and UX polish

This pass fixed responsive behavior, table usability, and consistency
issues without redesigning the app or adding product features. It's a
polish pass on top of everything above, not a replacement for it.

### Responsive layout rules

- Breakpoints: **mobile** < 768px, **tablet** 768–1023px, **desktop**
  1024px+ (Tailwind `lg`). The fixed 224px sidebar (`AppShell`) and its
  `lg:pl-56` body clearance only apply at `lg`+ — tablet (768px) keeps the
  same drawer nav as mobile rather than squeezing a permanently-open rail
  next to a narrow content column.
- `TopBar` always shows: a menu button (drawer toggle, hidden at `lg`+), a
  compact "OPTCG" wordmark (full "OPTCG Vault" from `sm`+), a command
  palette trigger (icon-only below `sm`, full search bar from `sm`+), and
  the keyboard-shortcuts/auth controls — every element has a `h-9 w-9`
  minimum touch target below `lg`.
- `SidebarNav` groups are Collector / Analytics / Admin / Admin · More —
  Analytics routes (including the per-domain `analytics/collection`,
  `analytics/wishlist`, `analytics/grading`) live in their own group rather
  than nested under Collector items, so the mobile drawer separates the
  three clearly (per the design brief).
- No page should rely on horizontal body scroll — the only horizontal
  scroll containers are table scroll containers (see below).

### Mobile table rules

- `TableScrollContainer` (in `components/ui/DataTableShell.tsx`) is the
  shared wrapper for every wide table: horizontal + capped vertical scroll
  inside its own box (never the page), a CSS-only "scroll shadow" fade at
  the leading/trailing edge (`.table-scroll-fade` in `globals.css` — no JS
  scroll listener needed), and a one-line `ColumnOverflowHint` ("← scroll
  horizontally for more columns →") on mobile. `DataTableShell` builds on
  it and keeps its existing `isEmpty`/`emptyLabel` API plus an optional
  `minWidth`.
- `STICKY_TABLE_HEADER_CLASS` (`sticky-thead`) - add to a bespoke table's
  `<thead>` for the same sticky-header behavior `.data-table` gets for
  free.
- `STICKY_FIRST_COLUMN_CLASS` (`sticky-col-first`) - add to a table's first
  `<th>` and every first `<td>` to keep that identifying column in view
  while the rest of a wide row scrolls underneath it. Applied to the
  highest-value dense tables (buy/sell decision candidates, wishlist
  targets, grading submissions, wishlist table, market opportunities).
- `MobileRecordList` - a card-per-row fallback for the rare table that's
  genuinely unusable even with horizontal scroll. Not used anywhere in this
  pass (horizontal scroll was always workable) - available for a future
  table where it isn't.
- Never remove columns globally to make mobile fit — scroll instead.
  Minimum table text stays 12px (`text-xs`).

### Filter/saved-view collapse rules

- `FilterBar` shows every filter inline on tablet/desktop; on mobile
  (< `sm`, 640px) only the first 3 filter controls stay visible, the rest
  collapse behind a "More filters (N) ▸" toggle — generic (based on child
  count), so no per-page filter-priority wiring was needed.
- `SavedViewBar`'s secondary actions (Update current view / Set default /
  Clear default / Manage views) collapse behind a "More…" toggle on
  mobile; "Save current view" and the saved-view select stay always
  visible.
- `QuickActionBar` wraps (`flex-wrap`) rather than scrolling — acceptable
  per the design brief ("wrap **or** horizontal-scroll pills").
- Never render a file upload input, an admin token, or confirmation text
  into a saved view — verified: every page's `currentFilters` is built from
  plain filter state (strings/numbers/booleans/enums) only.

### Modal responsiveness

- Every modal (`ConfirmActionModal`, `SaveViewModal`, `ManageSavedViewsModal`,
  `CommandPalette`, `KeyboardShortcutsModal`, and the per-page detail/preview
  modals) caps at `max-h-[80–90vh]` with internal `overflow-y-auto`, and a
  responsive `max-w-*` — action buttons stay in the (non-scrolling) footer.
- Esc closes every modal: `CommandPalette`/`KeyboardShortcutsModal` already
  got this from `AppShell`'s global key handler; the standalone modals
  (`ConfirmActionModal`, `SaveViewModal`, `ManageSavedViewsModal`) now use
  the shared `useEscapeKey` hook (`lib/useEscapeKey.ts`).

### Price/source display audit rules

Already-established rule (see "Price display rules" above), re-verified
across every page in the design brief's Part 7 list during this pass — no
"Market" label appears without a source/basis, and `PriceCell`/
`PriceBasisLabel` are the only price-display path used.

### Admin safety UI rules

Already-established rules (see "Admin safety rules" above) — re-verified,
no changes needed. `admin/backup`'s restore action already gates behind a
dry-run checkbox + typed confirmation + a distinct red button only in real
"replace" mode.

## Phase 10 — styling consistency pass

A final sweep bringing every remaining route (mostly built before this
design system existed) up to the same visual language as the pages above.
Not a redesign, not a new feature — see `docs/frontend_styling_audit.md`
for the full route-by-route before/after detail this section summarizes.

### Final component inventory

`apps/web/src/components/ui/` (the design-system layer):

| Component | Purpose |
|---|---|
| `AppShell`, `TopBar`, `SidebarNav` | Persistent layout shell (see "Layout shell") |
| `PageHeader` | Title + description + actions header, one per page |
| `StatCard` / `StatGrid` | Dense top-line stat tiles |
| `DataTableShell` / `TableScrollContainer` / `MobileRecordList` | Table chrome: scroll, empty state, sticky header, mobile fallback |
| `FilterBar` (+ `FILTER_INPUT_CLASS`/`FILTER_LABEL_CLASS`) | Inline filter row with mobile collapse |
| `SavedViewBar`, `SaveViewModal`, `ManageSavedViewsModal`, `SavedViewPill`, `PinnedViewsSection` | Saved views/filter presets |
| `CommandPalette`, `KeyboardShortcutsModal`, `QuickActionBar`, `WorkflowShortcutsSection` | Command palette and workflow shortcuts |
| `CardVaultTile`, `CardImageFrame`, `CardIdentityBlock`, `CardPricePanel`, `CardActivityPanel` | Card identity/detail building blocks |
| `OwnershipSummaryPanel`, `WishlistSummaryPanel`, `GradingSummaryPanel`, `MarketContextPanel`, `SourceComparisonPanel` | Card-detail side panels |
| `PriceCell`, `PriceBasisLabel` | Canonical price + basis display (see "Price/source display examples") |
| `Badge` (primitive), `VariantBadge`, `RiskBadge`, `ConfidenceBadge`, `SourceHealthBadge`, `DecisionBadge` | Shared status/category pills (see "Badge/status mapping" below) |
| `ActionButton` | Button with admin-safety-tier variants (`default`/`primary`/`dry-run`/`preview`/`real`/`danger`) |
| `ConfirmActionModal`, `AdminActionPanel` | Destructive-action confirmation gates |
| `SkeletonBlock` (`SkeletonRows`) | Loading shimmer |

`apps/web/src/components/` (domain-specific, built on the primitives above):
`RarityBadge`, `SourceBadge`, and one status badge per domain vocabulary
(`AlertStatusBadge`, `CollectionStatusBadge`, `GradingStatusBadge`,
`LogLevelBadge`, `MarketSignalEventStatusBadge`,
`MarketWorkflowRunStatusBadge`, `MatchStatusBadge`,
`OpportunityCategoryBadge`, `PriceTypeBadge`, `RunStatusBadge`,
`SearchTypeBadge`, `SeverityBadge`, `StockStatusBadge`,
`WishlistPriorityBadge`, `WishlistStatusBadge`, `CollectorTagBadge`) — kept
separate from `components/ui/` deliberately, see "Page adoption rules"
below. `StateBlocks.tsx` exports `LoadingState`/`ErrorState`/`EmptyState`/
`MissingValue`, the shared loading/error/empty/missing-value primitives
every page uses instead of hand-rolled boxes. `AdminAuthGate` (the single
admin-token entry form every `/admin/*` page renders) and
`AdminLogoutButton` are the canonical admin-token UI (see "Admin token UX"
below).

### Page adoption rules

- A page's own header is always `PageHeader`, not a hand-rolled `<h1>`.
- Top-line numbers are always `StatCard`/`StatGrid`, not ad-hoc `<div>`
  markup — even a single-page-local stat tile should use the shared
  component rather than duplicating its className string.
- Every table wider than a couple columns renders inside
  `DataTableShell`/`TableScrollContainer` with the `.data-table` CSS class
  on the `<table>` element — no hand-rolled `overflow-x-auto rounded
  border` wrapper.
- A domain that already has its own status vocabulary that doesn't cleanly
  map onto an app-wide badge (e.g. `source-mapping-quality`'s
  `ok`/`review`/`warning`/`critical`, which matches its own filter buttons
  exactly) may keep a locally-scoped badge built on the shared `Badge`
  primitive rather than being forced onto a mismatched canonical one — this
  is why `components/` still holds many domain-specific badge files
  alongside the smaller canonical set in `components/ui/`. What's not
  acceptable is a badge that isn't built on `Badge` at all (hand-rolled
  `<span>` with its own ring/bg/padding classes).
- Every button maps to an `ActionButton` variant — never a raw `<button
  className="...">` with hand-typed colors.
- Buttons/tabs that need a "selected" state use the gold-accent pattern
  (`bg-accent-gold text-black/80 ring-accent-gold` selected, `bg-bg-surface
  text-text-muted ring-border-default hover:text-text-primary`
  unselected) — not an inverted white/light chip.

### Badge/status mapping table

Extends "Badge color meaning" above with the full category → component
mapping from the design brief's Part 7:

| Category | Component | Notes |
|---|---|---|
| Rarity | `RarityBadge` | L / SR / SEC / R / UC / C |
| Variant | `VariantBadge` | Manga/SP/SEC gold family, Parallel/Alt Art purple family |
| Source | `SourceBadge` | Yuyu-Tei / SNKRDUNK |
| Valuation mode | `PriceBasisLabel` (`mode` prop) | Raw market / Graded adjusted |
| Decision action | `DecisionBadge` | review_buy / review_sell / wait / hold / monitor / grade_first / missing_data / skip |
| Risk level | `RiskBadge` | low / medium / high / critical |
| Confidence label | `ConfidenceBadge` | exact / high / medium / low / very_low / unknown |
| Source health | `SourceHealthBadge` | healthy / degraded / stale / blocked / error / unknown |
| Review status (source mapping quality) | local `RiskBadge`-style badge on `Badge` | own `ok`/`review`/`warning`/`critical` vocabulary, matches its filters |
| Review status (SNKRDUNK candidates) | `MatchStatusBadge` | own matched/unmatched/rejected vocabulary |
| Job status (file jobs) | `Badge` (via `FileJobTracker`'s `STATUS_STYLES` map) | queued/running/success/failed/cancelled |
| Import validation status | `Badge` (via `import-validation`'s `StatusBadge`) | valid/invalid |
| Workflow status | `MarketWorkflowRunStatusBadge` | market workflow runs |
| Refresh run status | `RunStatusBadge` | price refresh runs |
| Alert status | `AlertStatusBadge` | alert events |
| Log level | `LogLevelBadge` | structured app logs |
| Severity (audits) | `SeverityBadge` | card audit, system check, performance |

An unknown/unrecognized status value must always render as a muted
"unknown" badge (every badge component above falls back to a neutral
style + the raw value as label when it doesn't recognize the value) — never
throw or render blank.

### Price/source display examples

The only two price-display building blocks a page should ever need:

```tsx
// A price with its basis, staleness, and missing-value handling all built in
<PriceCell
  valueJpy={card.latest_price_jpy}
  source="snkrdunk"
  priceType="floor"
  observedAt={card.observed_at}
/>
// renders: "¥1,234" + a "SNKRDUNK floor" basis chip (+ a "stale" chip if
// observedAt is >48h old), or "not available" if valueJpy is null/undefined

// A basis label on its own (e.g. next to a manually-formatted price)
<PriceBasisLabel mode="graded_adjusted" />
// renders: "Graded adjusted" — never a bare "Market"
```

`formatJpy`/`formatSignedJpy`/`formatSignedPct`/`formatDate`/
`formatDateTime` (`@/lib/format`) are the only JPY/date formatters used
app-wide; all fall back to `"—"` (or `formatJPY`/`formatPercent`/
`formatPriceOrMissing`'s more descriptive `"not available"`/`"missing"`
variants) rather than a raw `null`/`undefined`. `PriceCell`'s internal
`isStale()` (48h threshold against `observedAt`) is the one staleness rule
in the app — no page re-implements it.

### Admin safety component examples

```tsx
// A read-only/low-stakes action
<ActionButton variant="default" onClick={refresh}>Refresh</ActionButton>

// The page's main positive action
<ActionButton variant="primary" onClick={save}>Save</ActionButton>

// A dry-run/preview-only trigger
<ActionButton variant="dry-run" onClick={runDryRun}>Dry run</ActionButton>

// A real write about to happen, before the confirm gate
<ActionButton variant="real" onClick={openConfirm}>Restore backup</ActionButton>

// The final confirmed destructive action, only inside a confirm gate
<ActionButton variant="danger" onClick={executeDelete}>Delete</ActionButton>

// Confirmation gate for a small/single-row destructive action
<ConfirmActionModal
  open={confirmOpen}
  title="Reject this match?"
  onConfirm={reject}
  onCancel={() => setConfirmOpen(false)}
/>

// Confirmation gate for a high-blast-radius action - stays disabled until
// the exact phrase is typed
<ConfirmActionModal
  open={confirmOpen}
  title="Merge these cards?"
  confirmPhrase="MERGE"
  onConfirm={merge}
  onCancel={() => setConfirmOpen(false)}
/>
```

Admin token entry is a single component (`AdminAuthGate`) rendered by every
`/admin/*` page's auth gate — never a per-page hand-rolled token form. The
token is only ever read/written via `getAdminToken`/`setAdminToken`/
`clearAdminToken` in `lib/api.ts`; it is never rendered into page text,
never included in a saved view's `currentFilters` payload, and never
logged. `AdminLogoutButton` (the "Clear admin token" control) is the one
shared "clear token" component, styled as a plain `ActionButton
variant="default"` — never styled to look like a primary/destructive
action, since clearing a token isn't itself destructive.

### Remaining known styling debt

Small, deliberately-deferred items that don't block calling this pass
complete:

- `CollectorTagsGroupsManager`, `CollectionValuationSummary`'s non-button
  markup (inputs, containers) and a handful of other shared
  components/tables still use `neutral-*`/`rose-*` Tailwind colors directly
  instead of the `text-*`/`bg-*`/`border-*` semantic tokens — visually
  equivalent (the token values point at the same palette) but not yet
  swapped to the token classes. Low priority: no visual inconsistency, just
  a maintainability nit for a future pass.
- `catalog-coverage`'s `SeverityPill` intentionally keeps its own `review`
  status label rather than mapping onto the shared `SeverityBadge`'s
  `info` vocabulary — a deliberate exception (see "Page adoption rules"),
  not debt, but noted here since it's easy to mistake for an inconsistency.
- The mobile-vs-desktop responsive rules (Phase 10 §"mobile/tablet
  responsiveness") were verified for every page that existed at the time of
  that pass; the newly-migrated pages in this pass reuse the same
  `TableScrollContainer`/`FilterBar`/`SavedViewBar` collapse behavior, so
  no separate re-audit was needed, but a fresh manual pass on a real mobile
  viewport is still worthwhile before calling Phase 10 fully closed (see
  `docs/manual_qa_checklist.md`).
