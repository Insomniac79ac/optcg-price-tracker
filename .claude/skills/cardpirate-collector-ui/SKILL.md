---
name: cardpirate-collector-ui
description: >
  Product and visual-design principles for CardPirate Atlas's public/
  collector-facing frontend - Discover, Cards, Card detail, Market Index
  preview, My Collection, Wishlist, and any new collector-facing visual
  tranche under apps/web. Load this before designing, implementing, or
  reviewing collector-facing UI: choosing layout/copy/imagery direction,
  writing a tranche contract (docs/ui/TRANCHE_TEMPLATE.md), or running the
  ATLAS loop (docs/ui/ATLAS_LOOP.md). Not for admin pages, backend/API
  code, ingestion, or database work - see docs/brand.md "Public vs. admin"
  for what the admin surface keeps instead.
---

# CardPirate Atlas — collector UI principles

CardPirate Atlas is a collector product, not a trading terminal. Every
public/collector-facing surface is judged on that basis first, functional
correctness second. Full brand rationale, legal constraints, and token/
component detail live in `docs/brand.md` and
`docs/interface_design_system.md` - this file is the short version to load
before touching collector-facing UI, not a replacement for either.

## Product principles

- The card artwork is experienced before its price. Price is context, not
  the reason a page exists.
- Information hierarchy, top to bottom, on every collector-facing page:
  1. artwork
  2. card identity
  3. set, rarity, and variant
  4. collector relationship (owned / wishlisted / graded)
  5. Market Index and source context
- UI should create curiosity, attachment, discovery, and a sense of
  collection progress - never urgency, competition, or trading pressure.
- The Market Index is supporting context, not the emotional centre of any
  collector-facing page. It never leads a hero, and it never gets larger
  visual weight than the card it describes.
- Visual flavour is original maritime-cartography (compass, route line,
  card-as-map-fragment) - never novelty pirate language ("ahoy," "loot,"
  "bounty," "matey"). See `docs/brand.md` "Copy principles."
- Avoid generic SaaS layouts and generic AI-generated-looking aesthetics:
  no three-column feature grids, no gradient hero, no repetitive stat-card
  rows standing in for a real collector moment. See
  `docs/ui/VISUAL_RUBRIC.md` "Originality" for concrete examples.
- Avoid dense borders, excessive metrics, bright red/green price framing,
  and terminal-style typography on anything collector-facing - that
  vocabulary is reserved for the admin/operational surface. See
  `docs/interface_design_system.md` "Do-not list."
- Never fabricate cards, popularity, trends, rankings, collection
  statistics, or prices. Every number and every card shown must come from
  the real API response for that page - omit a section entirely rather
  than inventing data to fill it.
- Preserve accessibility, `prefers-reduced-motion`, and mobile usability
  in every change - these are not optional polish. See
  `docs/ui/VISUAL_RUBRIC.md` "Craft and accessibility."

## Brand tokens (summary — full detail in `docs/interface_design_system.md`)

| Token | Value | Use |
|---|---|---|
| `--bg-page` | `#171717` | deep background |
| `--bg-elevated` | `#242528` | raised surface |
| `--bg-card` | `#363638` | secondary surface |
| `--text-primary` | `#F4F0E8` | primary text |
| `--parchment` | `#E8DEC7` | weathered-parchment accent |
| `--accent-gold` | `#C79A4B` | rarity, meaningful highlights - never decorative filler |
| `--accent-teal` | `#4F8D86` | navigation, discovery, trusted info |
| `--accent-coral` | `#C8624D` | limited warning/emphasis only |

`--signal-green`/`--signal-red` exist but are reserved for the admin/
operational surface - collector-facing price movement never gets a
dominant red/green treatment.

## Typography

- **Display** (`--font-display`, Fraunces): headings, hero copy, the
  wordmark. Sparingly - never body text or tables.
- **UI/body** (`--font-sans`, Manrope): everything else.
- **Monospace** (`--font-mono`, IBM Plex Mono): card codes, set codes,
  timestamps, and other small technical metadata only - never a page's
  primary voice.
- Both self-hosted via `next/font/google`, `display: "swap"`, with system
  CJK fallbacks appended for `name_jp` - see `docs/brand.md` "Typography."

## Component reuse

Reuse existing collector-facing primitives before building new ones -
`CardImageFrame`, `CollectorCardTile`, `CardGrid`/`CardGridSkeleton`,
`MarketIndexValue`, `StateBlocks` (`LoadingState`/`ErrorState`/
`EmptyState`), `CollectorEmptyState`, and the `AtlasMark`/`AtlasLogo`
family. See `docs/interface_design_system.md` "Component usage rules" for
the full inventory. A new visual tranche building a second, competing tile
or card-frame system is a design smell, not a feature.

## Using this with the ATLAS loop

This skill states *what* good collector-facing UI looks like.
`docs/ui/ATLAS_LOOP.md` states *how* to get there in a small, reviewable
tranche, `docs/ui/TRANCHE_TEMPLATE.md` is the contract to fill in first,
and `docs/ui/VISUAL_RUBRIC.md` plus the `cardpirate-visual-reviewer` agent
are how the result gets judged - against these principles, not just
against passing tests.
