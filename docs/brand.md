# Brand — CardPirate Atlas

This document is the reference for the product's working brand: what it's
called, why it looks the way it does, what it may never do, and how to
replace it later if domain/trademark clearance fails. For CSS tokens,
components and layout conventions, see `docs/interface_design_system.md` -
this file covers naming, voice, legal constraints and the design rationale
behind the tokens, not their implementation.

## Status

**Working brand, pending formal domain and trademark clearance.**
"CardPirate Atlas" / "CardPirateTCG" are placeholders chosen for this build,
not confirmed-available legal names. Do not commission physical goods,
register social handles, or make public announcements using this name
without separate clearance. See "Replacing the brand later" below for what
that would involve in this codebase.

## Brand architecture

| Element | Value |
|---|---|
| Product name | CardPirate Atlas |
| Short name | Atlas |
| Parent/endorsing brand | CardPirateTCG |
| Endorsement line | "by CardPirateTCG" |
| Primary tagline | "Map your collection. Find your next treasure." |
| Supporting line | "Collect the story. Know the value." |
| Brand promise | A place to remember what you own, discover what to chase, and understand value without turning collecting into trading. |

All of the above live in exactly one place in code:
`apps/web/src/lib/brand.ts`. Nothing else in the codebase should hardcode
the product name, tagline, or legal disclaimer text - it should import
`brand` from `@/lib/brand` instead. This is the single edit point if the
name changes later.

## Naming hierarchy / what's retained

The brand pass is a naming, tone, and visual-identity change - it does not
touch functional navigation labels, which stay exactly as they were:
Discover, Cards, Market Index, My Collection (with a Vault View sub-view),
Wishlist, Grading, Activity, Admin. "Vault" survives as a *view name*
(Vault View - the artwork-grid view of My Collection), not as the product
name; it predates this rebrand and reads as a generic collection term, not
as the deprecated "OPTCG Vault" product name.

## Colour tokens

Defined in `apps/web/src/app/globals.css`, documented in full (with
Tailwind utility names) in `docs/interface_design_system.md`. Summary:

| Role | Token | Value |
|---|---|---|
| Deep background | `--bg-page` | `#171717` |
| Raised surface | `--bg-elevated` | `#242528` |
| Secondary surface | `--bg-card` | `#363638` |
| Soft foreground (primary text) | `--text-primary` | `#F4F0E8` |
| Weathered parchment | `--parchment` | `#E8DEC7` |
| Treasure gold | `--accent-gold` | `#C79A4B` |
| Sea-glass teal | `--accent-teal` | `#4F8D86` |
| Restrained coral | `--accent-coral` | `#C8624D` |

### Colour rules

- **Gold** = rarity, meaningful highlights, milestones (a completed set, a
  rare pull). Never used decoratively just to add warmth.
- **Teal** = navigation, discovery, trusted information (links, the Market
  Index's own accent, "explore" actions).
- **Coral** = a *limited* warning/emphasis colour. Not the default
  treatment for price movement, and not used broadly enough to compete
  with gold/teal for attention.
- Price-movement (up/down) is deliberately **not** given a dominant
  red/green treatment anywhere collector-facing - that vocabulary
  (`--signal-green`/`--signal-red`) is reserved for the admin/operational
  surface (risk levels, match confidence, dense tables), unchanged by this
  rebrand.
- Not every surface is a bordered card. Depth comes from the three-tier
  surface scale (`bg-page` → `bg-elevated` → `bg-card`), spacing, and the
  existing restrained `glow-gold`/`glow-purple` edge treatments for
  real-rarity-backed variants - never a fabricated foil state.

### Contrast decisions

All pairs below were checked against WCAG 2.1 (4.5:1 for normal text,
3:1 for large text/UI components) using the actual token hex values:

| Pair | Ratio | Meets |
|---|---|---|
| `text-primary` (`#F4F0E8`) on `bg-page` | 15.77:1 | AA (normal text) |
| `text-secondary` (`#A9A395`) on `bg-page` | 7.14:1 | AA (normal text) |
| `text-secondary` on `bg-card` | 4.80:1 | AA (normal text) |
| `text-muted` (`#8B8672`) on `bg-page` | 4.91:1 | AA (normal text) |
| `text-faint` (`#6B6656`) on `bg-page` | 3.12:1 | AA (large text/UI only - unchanged use as decorative/non-essential labels) |
| `accent-gold` (`#C79A4B`) on `bg-page` | 6.96:1 | AA (normal text) |
| `accent-gold` on `bg-card` | 4.68:1 | AA (normal text) |
| `accent-teal` (`#4F8D86`) on `bg-page` | 4.68:1 | AA (normal text) |
| `accent-teal` on `bg-card` | 3.15:1 | AA (large text/UI only) |
| `accent-coral` (`#C8624D`) on `bg-page` | 4.53:1 | AA (normal text, at the threshold) |
| `accent-coral` on `bg-card` | 3.05:1 | AA (large text/UI only) |
| black text on `accent-gold` (button) | 8.15:1 | AA |
| black text on `accent-teal` (button) | 5.49:1 | AA |
| `parchment` (`#E8DEC7`) on `bg-page` | 13.41:1 | AA (normal text) |

Computed directly from the hex values actually committed in `globals.css`
(`docs/brand.md` previously carried placeholder ratios ahead of the CSS
existing - these are the real numbers).

Practical rule: teal/coral text on the `bg-card` surface must be large
text (≥18.66px bold or ≥24px regular) or a non-text UI element (icon,
border, fill) - small body copy in teal/coral belongs on `bg-page`/
`bg-surface`, not `bg-card`. `text-faint` is the one tier that stays
below 4.5:1 by design - it's used only for genuinely non-essential
decorative labels (a chevron hint, a faint timestamp aside), matching its
pre-existing role; every tier improved over the previous palette's
equivalent ratio (previous faint was 2.5:1, previous muted was 4.1:1).

## Typography

- **Display** (`--font-display`, Fraunces): headings, hero copy, the
  wordmark. Used sparingly - never body text or dense tables.
- **UI/body** (`--font-sans`, Manrope): everything else.
- **Monospace** (`--font-mono`, IBM Plex Mono, unchanged): card codes, set
  codes, timestamps, and other small technical/admin metadata only.
- Both Manrope and Fraunces are self-hosted at build time via
  `next/font/google` (no runtime font fetch, no CSP change needed) and use
  `display: "swap"` with next/font's automatic fallback-metric matching, so
  there's no layout shift while the real face loads.
- Japanese card names (`name_jp`) fall back per-glyph to system CJK faces
  (Hiragino/Yu Gothic/Yu Mincho/Noto Sans JP) appended to the end of both
  the sans and display font stacks - deliberately not a self-hosted CJK
  webfont, which would be hundreds of KB to megabytes for a single field.

## Logo usage

Original maritime-cartography mark (`apps/web/src/components/brand/
AtlasMark.tsx`): a vertical trading-card silhouette with a clipped
top-right corner, a two-tone compass needle (gold north / teal south) at
its center, and a faint dashed route line. Pure inline SVG, no image asset.

- `AtlasMark` - the icon alone. `tone="onDark"` (default, used everywhere
  in the app's dark interface) or `tone="onLight"` (rare light contexts -
  print, email, light embeds).
- `AtlasCompactMark` - icon + short "Atlas" wordmark, used in the topbar
  and other tight chrome. Always carries a visually-hidden ("sr-only")
  full product name for assistive tech, even when only the short name is
  visible.
- `AtlasLogo` - the full horizontal lockup (mark + "CardPirate Atlas" +
  "by CardPirateTCG"), used on the sign-in page, 404/error pages, and
  anywhere else there's room for the complete identity.
- Favicon: `apps/web/src/app/icon.svg` (static, scalable, legible at 16px).
  `apple-icon.tsx` and `opengraph-image.tsx` render simplified PNG variants
  at request time via Next.js's built-in `next/og` `ImageResponse` - no
  binary asset checked into the repo, no new dependency.

**What the mark deliberately avoids**: no skull-and-crossbones, no straw
hat, no Jolly Roger, no official One Piece symbol, no copied franchise
artwork or typography. See "Legal/IP constraints" below.

## Copy principles

- Functional navigation labels are never replaced with pirate/cartography
  terminology (see "Naming hierarchy" above).
- Pirate/cartography flavour is used in *supporting* copy only: section
  titles ("Recent Finds", "On Your Radar"), empty states ("Your collection
  starts here"), and success moments - never as a substitute for a clear
  label.
- Avoid repeated novelty terms: "ahoy", "captain", "loot", "bounty",
  "matey", "walk the plank". None of these appear anywhere in the product
  copy. The brand reads as mature and collector-led, not novelty-themed.
- Market Index copy never uses "signals", "buy", "sell", or "opportunities"
  as public-facing headings - it explains coverage, freshness and sourcing
  in plain language and is explicit that it is reference information, not
  investment advice.
- Financial gain/loss is never the headline of a collector-facing page
  (My Collection, Wishlist, Discover) - it can appear in a summary or
  supporting panel, never as the page's primary visual weight.

## Emotional hierarchy

Applied consistently across Discover, Cards, Card detail, My Collection,
and Wishlist:

1. Card artwork
2. Card name and identity
3. Set, rarity, variant
4. Collector relationship (owned/wishlisted/graded)
5. Market Index and source context

Price-movement arrows, terminal-style status strings, dense source
statistics, technical coverage language, and operational timestamps are
kept out of the primary view and live in secondary panels, tooltips, or a
card's expanded source-evidence section instead.

## Public vs. admin

The collector shell (`AppShell`/`TopBar`/`SidebarNav`) is shared by every
route, including admin - there is no separate "admin shell" to maintain.
What differs:

- **Shared, everywhere**: the restrained `AtlasCompactMark` in the topbar,
  the same dark palette, the same footer disclaimer.
- **Collector/public only**: the emotional hierarchy above, editorial
  display type on headings, warm microcopy, artwork-forward layouts.
- **Admin only**: `AdminSubNav` (the full flat list of ~20 operational
  routes) and every admin page's own dense table/form content - none of
  this inherits the collector pages' decorative treatment. No admin
  control is reachable from a public/collector page, and no collector page
  links directly into operational tooling.
- Admin authentication (`ADMIN_TOKEN` gate on the API, the staging
  Credentials login on the frontend) is unchanged by this rebrand.

## Legal / IP constraints

- CardPirate Atlas is described everywhere (footer, metadata) as an
  **independent collector tool**, not affiliated with, endorsed by, or
  sponsored by Bandai, Shueisha, Toei Animation, or any other rights
  holder connected to One Piece. This disclaimer text lives in
  `brand.legalDisclaimer` (`apps/web/src/lib/brand.ts`) and is rendered by
  `apps/web/src/components/Footer.tsx` on every page.
- No official One Piece, Bandai, Shueisha, or Toei branding, logos,
  typography, or character art appears anywhere in the product.
- The brand mark avoids every specifically-called-out franchise motif
  (skull-and-crossbones, straw hat, Jolly Roger) - see "Logo usage".
- Card artwork itself is sourced per the existing image-import provenance
  system (`docs/market_index.md`) and is out of scope for this rebrand -
  no change to how card images are sourced or validated.

## Replacing the brand later

Because naming/copy is centralized in `apps/web/src/lib/brand.ts` and
colours/fonts are centralized in `apps/web/src/app/globals.css` +
`apps/web/src/app/layout.tsx`, replacing the working brand (if clearance
fails, or a different name is chosen) means:

1. Edit the string values in `brand.ts` (name, tagline, disclaimer, nav
   labels if needed) - every page that imports `brand` picks up the change
   automatically.
2. Replace the mark in `AtlasMark.tsx` (the SVG paths) if the visual
   identity itself needs to change, not just the name - `AtlasLogo`/
   `AtlasCompactMark` don't need to change since they just compose
   `AtlasMark` + `brand` values.
3. Update the CSS custom properties in `globals.css` if the colour
   direction changes; the Tailwind utilities (`bg-accent-gold`, etc.) don't
   need to change since they're aliases, not hardcoded hexes.
4. Re-run the repository-wide search this rebrand itself used
   (`grep -rniE "OPTCG|TCG Vault|Price Tracker"`) to confirm no old name
   leaked back in, and re-generate `icon.svg`/`apple-icon.tsx`/
   `opengraph-image.tsx` if the mark changed.
5. No backend, database, or ingestion code needs to change - this rebrand
   is entirely `apps/web` (frontend/presentation), by design.
