# Manual QA checklist — mobile/tablet/desktop UX

Practical, page-by-page checklist for the Phase 10 responsiveness/UX polish pass. There's no
automated viewport/overflow test yet (see [docs/operations.md](operations.md#phase-10-ux-audit)),
so run this by hand after any layout, table, or filter-bar change. Use the browser devtools device
toolbar (or an actual phone/tablet) at the three widths below.

Breakpoints: **mobile** < 768px (check at 360px), **tablet** 768–1023px (check at 768px),
**desktop** 1024px+ (check at 1440px).

## 1. Desktop (1440px+)

- [ ] Sidebar is visible and fixed; Collector/Analytics/Admin groups are separated.
- [ ] Dense tables show every column without horizontal scroll (unless the table is unusually wide,
      e.g. buy/sell decision candidate tables).
- [ ] Topbar shows the full search bar, "OPTCG Vault" wordmark, and auth control.

## 2. Tablet (768px)

- [ ] Sidebar is a drawer (menu button in topbar), not a squeezed permanent rail.
- [ ] No page has horizontal body scroll — only tables scroll horizontally, in their own container.
- [ ] Command palette trigger is reachable from the topbar.
- [ ] Filter bars wrap cleanly and don't push saved-view controls off-screen.

## 3. Mobile (360px)

- [ ] Topbar fits without overlap: menu button, compact "OPTCG" wordmark, command palette icon,
      "?" shortcuts, auth control.
- [ ] Nav drawer opens over the page (not behind it), separates Collector / Analytics / Admin, and
      highlights the active route.
- [ ] No page has horizontal body scroll (`document.documentElement.scrollWidth <=
      window.innerWidth`, small tolerance ok) — only table scroll containers scroll sideways.
- [ ] Wide tables show the "← scroll horizontally for more columns →" hint and a fade at the
      scrolled edge.
- [ ] Filter bars beyond ~3 controls collapse behind "More filters (N) ▸".

## 4. Card detail (`/cards/[id]`)

- [ ] Desktop: image left, identity right, panels stacked below.
- [ ] Mobile: image/identity first, **price source panel next**, then ownership/wishlist/grading,
      then market context/notes, admin mini-panel last (only visible with an admin token).
- [ ] Every price shows a JPY value *and* a source/basis label (Yuyu-Tei sell/buy, SNKRDUNK floor,
      raw market, graded adjusted) — never a bare number, never "Market" alone.

## 5. Collection vault (`/collection/vault`)

- [ ] Desktop: compact/standard/showcase density all render correctly.
- [ ] Tablet: 2 columns.
- [ ] Mobile: 1 column, card image/frame still readable, price + basis still visible, rarity/variant
      badges don't overflow the tile, tap target covers the whole tile.

## 6. Analytics tables

Buy decisions, sell decisions, portfolio risk, collection/wishlist/grading analytics breakdowns.

- [ ] Table scrolls inside its own container on mobile, never the page.
- [ ] Sticky header stays visible while scrolling the table vertically.
- [ ] First column (score/card/priority) stays visible while scrolling horizontally where applied.
- [ ] No column was removed to make mobile fit.
- [ ] Table text is never smaller than 12px; no cell shows a too-faint gray for anything important.

## 7. Admin tables

Source mapping quality, catalog coverage, price source health, card duplicates, import validation,
cards, SNKRDUNK candidates.

- [ ] Same table rules as analytics tables above.
- [ ] Bulk-action controls and pagination stay usable at 360px (wrap, don't overflow).
- [ ] Dry-run/preview actions are visually distinct from real/destructive actions (dashed blue vs.
      gold preview vs. red).

## 8. Modals / confirmation

Command palette, keyboard shortcuts, confirm-action, save/manage saved views, import validation
detail, merge preview.

- [ ] Modal never exceeds the viewport height; content scrolls internally, action buttons stay
      visible (not scrolled out of view).
- [ ] Esc closes every modal.
- [ ] A destructive/real action still requires its confirmation step (checkbox, typed phrase, or
      both) at every width.
- [ ] On mobile, the primary input (search box, typed-confirmation field) isn't hidden behind the
      on-screen keyboard.

## 9. Command palette

- [ ] Opens via ⌘K/Ctrl+K, the topbar search bar (desktop/tablet), or the topbar search icon
      (mobile).
- [ ] Arrow keys + Enter work; Esc closes it.
- [ ] Usable via touch on mobile (tap to select, on-screen keyboard doesn't cover the results list).

## 10. Saved views

- [ ] "Save current view" and the saved-view selector are always visible.
- [ ] Secondary actions (update/set default/clear default/manage) collapse behind "More…" on
      mobile and expand on tap.
- [ ] No admin token, file input, or confirmation text is ever included in a saved view's filters.

## 11. Price basis labels

- [ ] Every important price (dashboard, collection, vault, card detail, wishlist, grading, every
      analytics page, market opportunities/signals) shows a JPY value.
- [ ] Every price shows its source/basis (Yuyu-Tei sell/buy, SNKRDUNK floor, raw market, graded
      adjusted) — never a bare "Market" label.
- [ ] Stale prices show a "stale" indicator; missing prices show "not available", never a blank
      cell or a literal `null`/`undefined`.

## 12. Empty/loading/error states

- [ ] Empty states are quiet and vault-themed — no bright SaaS illustration, no anime/copyrighted
      art.
- [ ] Loading states show the dark skeleton shimmer, not a spinner or blank flash.
- [ ] Error states include an actionable next step where practical (e.g. "is the backend running?").
- [ ] Nothing renders a literal `null`/`undefined` anywhere on the page.

## 13. Admin safety checks

- [ ] Dry-run buttons are visually distinct (dashed blue) from real actions.
- [ ] A preview/dry-run result is shown before the real action is available, where the feature
      supports it (recheck-quality, bulk merge preview, import validation, backup restore).
- [ ] Real/destructive actions require confirmation (checkbox and/or typed phrase) and use the red
      "danger"/"real-action" treatment — never a plain primary button.
- [ ] Disabled buttons look disabled (dimmed, `cursor-not-allowed`).
- [ ] Success/error results are shown inline after the action runs.
- [ ] The admin token is never visible in a saved view, a recent-workflow entry, or the URL.
- [ ] `AdminAuthGate`'s token-entry form (warning-amber box, "Save token" button) looks the same on
      every admin page that shows it — it's a single shared component, so a difference here means
      something is overriding it.
- [ ] `AdminLogoutButton`'s "Clear admin token" control looks like a plain secondary button, never a
      danger button — clearing a token isn't itself destructive.
- [ ] Visiting an `/admin/*` route with no token set (or an expired one) shows `AdminAuthGate` with a
      clear "Admin token required" message, not a silent blank page or a raw 401.

## 14. Route-by-route styling-consistency check (Phase 10 styling pass)

Spot-check per `docs/frontend_styling_audit.md` — every route below should show a `PageHeader`
(title + description at the top), `StatCard`/`StatGrid` for any top-line numbers, and tables inside
the shared scrollable/sticky-header chrome (no visible difference in table look-and-feel from an
already-established page like `/collection` or `/admin/card-duplicates`).

- [ ] Collector: `/wishlist`, `/grading`, `/activity`
- [ ] Market: `/market/opportunities`, `/market/signals`, `/market/signal-events`,
      `/market/report`, `/market/movers`
- [ ] Analytics: `/analytics/collection`, `/analytics/wishlist`, `/analytics/grading`
- [ ] Admin (raw-table cluster): `/admin/data-retention`, `/admin/file-jobs`, `/admin/card-audit`,
      `/admin/system-check`, `/admin/market-workflow-runs`, `/admin/refresh-runs`,
      `/admin/performance`, `/admin/job-locks`, `/admin/alerts`, `/admin/logs`
- [ ] Admin (header/button cleanup): `/admin/cards`, `/admin/catalog-coverage`,
      `/admin/snkrdunk-candidates`, `/admin/backup`, `/admin/cache`, `/admin/actions`,
      `/admin/release-status`
- [ ] No page shows a `bg-neutral-100`/white-filled button, a bright gradient, or an inverted
      white "selected" tab chip — selected states use the gold-accent pattern
      (`bg-accent-gold`/`ring-accent-gold`).
- [ ] Every badge/status pill on the page (rarity, source, risk, confidence, decision, workflow/job
      status, severity, alert status) renders with a label plus color, and an unrecognized value
      renders a muted "unknown" pill rather than crashing the page.
