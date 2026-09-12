# DESIGN 9B — opt-in Atlas visual primitives

Implemented for review on 2026-09-12. Uncommitted. No production route adopts
these components yet. Existing fonts, global tokens, navigation, auth, data
access and all price/source contracts are unchanged.

## Use

Import from `apps/web/src/components/ui/AtlasPrimitives.tsx`. Wrap an adopting
subtree in `AtlasVisualSystem`; its CSS-module scope defines the local tokens.
Do not apply this wrapper to the whole application as a migration shortcut.

```tsx
<AtlasVisualSystem>
  <section aria-labelledby="printings">
    <AtlasSectionIntro id="printings" number="01" title="Explore printings" />
    <AtlasArtworkStage
      image={{
        imageUrl: print.imageUrl,
        alt: `${print.displayName} (${print.cardCode})`,
        cardCode: print.cardCode,
        geometry: print.imageGeometry,
      }}
      caption={print.displayName}
    />
  </section>
</AtlasVisualSystem>
```

The caller supplies real data and controls the section/layout. An intro supports
H2 or H3 and an optional description. Its number is hidden from assistive
technology. No Japanese secondary copy is added without editorial approval.

`AtlasDivider` and `AtlasMapSurface` use decorative, nonfocusable SVG geometry.
Only the SVG viewport clips; content and focus rings do not. Map geometry sits
behind content, has no pointer interaction, and disappears in forced colours.

`AtlasArtworkStage` delegates image selection inputs, contain fit, intrinsic-size
validation, bounded geometry and image-error handling to `CardImageFrame`.
It always requests full-width padded framing, caps the surround at 22rem and
puts captions outside the frame. No image filters, rotation, metadata overlays,
or replacement rendering. Its scoped fallback metadata is enlarged to 14px.

`AtlasReleaseDestination` takes an actual `releaseCode` and a caller-supplied
`href`. It does not derive release names, counts, membership or URLs. The native
link has a minimum 44px target and a visible 2px outline with 4px offset.

Consumer grids should accommodate enlarged text, for example
`repeat(auto-fit, minmax(min(100%, 10rem), 1fr))` for release destinations.
Do not impose a minimum card count or clip a section to a fixed height.

## Local tokens

All names below are prefixed `--atlas-`. No `:root` values are replaced.

| Role | Token suffix | Value / existing alias |
| --- | --- | --- |
| Primary dark | `surface-primary` | `--bg-page`, #171717 |
| Secondary/hover | `surface-secondary` | `--bg-card`, #363638 |
| Map ground | `surface-map` | `--bg-surface`, #1d1e1f |
| Chart line | `chart-line` | parchment at 5.5% opacity |
| Route line | `route-line` | gold at 22% opacity |
| Parchment text | `text-parchment` | `--parchment`, #e8dec7 |
| Subdued text | `text-subdued` | #b6b0a3 |
| Waypoint/gold | `waypoint` | `--accent-gold`, #c79a4b |
| Navigation/focus | `navigation` | #80b4ab |
| Display | `font-display` | existing Fraunces role |
| Body | `font-body` | existing Manrope role |
| Metadata | `font-metadata` | existing IBM Plex Mono role |
| Artwork depth | `artwork-shadow` | restrained black shadow |

No new display font was necessary after reviewing real artwork. Display
headings use normal title/sentence case; mono is confined to codes, dates and
technical metadata. Artwork supplies most of the colour.

Minimum contrast across #171717 / #1d1e1f / #363638 is 9.02:1 for parchment,
5.59:1 for subdued text, 4.68:1 for gold, and 5.19:1 for teal. Low-contrast chart
lines carry no information. New essential primitive text is at least 14px;
section headings are at least 24px. Colour is never the only label.

## Specimen and evidence

The standalone Vite harness is `/tmp/design9b`, outside production source.
Its README records exact replay commands, local artwork/font provenance and
the harness-only Link/environment adapters. No packages were installed.
The shared semantic components' compact text is enlarged by specimen-only CSS;
their production defaults and logic were not modified.

Public staging response bytes were stored in `/tmp/design9b/raw` before parsing.
The harness uses frozen records, not live requests or Claude mock data:

| State | Evidence |
| --- | --- |
| Exact print / single-card section | Roronoa Zoro OP01-001, print 1; real mirrored-image SHA-256 and full-canvas geometry |
| Distinct siblings | Nami OP01-016, prints 6009 / 6010, canonical card 5409; original and alternate artwork |
| Simple low-value print | Koza EB01-004, print 3452, Market Index ¥30 |
| Constrained source | Charlotte Compote EB01-055, print 3517; Yuyu-Tei ¥30, SNKRDUNK ¥1,000 platform minimum, excluded from Market Index |
| Archive/current distinction | Zoro archived index dated September 11; current source observations September 12 |
| Missing artwork | Explicitly labelled image-failure fixture using Nami's identity and existing fallback |
| Unavailable/empty | Actual unavailable Nami indexes; separately labelled empty-list fixture |

Official artwork is copied unchanged from the existing local snapshot. The
mirrored Zoro image matches its exact stored hash; other files match the exact
official asset basename, never just a card-code guess.

Screenshots and measurement JSON: `/tmp/design9b/evidence/`.

- `desktop.png`, `desktop-viewport.png`: 1440×900.
- `mobile.png`, `mobile-viewport.png`: 390×844.
- `mobile-constraints.png`, `mobile-unavailable.png`, `mobile-releases.png`:
  readable mobile section details.
- `narrow.png`: 320×844.
- `zoom-200.png`: 720×450 effective-viewport simulation of desktop 200% zoom.
- `text-200-mobile.png`: 390×844 with 200% root text size.
- `*-focus.png`, `*-keyboard.json`: visible focus and complete release-link order.

Final measurements: no horizontal overflow in any of the five modes; every
artwork asset loaded with contain fit and no filter; every release link exceeds
44px height; no browser errors. The zoom evidence is an effective-viewport
simulation plus a separate actual text-resize check, not browser-toolbar zoom.

Fresh independent visual review: PASS after fixing two specimen-only issues:
stacking spotlight/date panels earlier and replacing fixed source/release
columns with font-relative auto-fit columns. The enlarged-text overflow was
retested at 390px, with final document width exactly 390px and intact codes.

## Checks and scope

- Focused AtlasPrimitives, CardImageFrame and SourceContributionNote tests:
  35 passed.
- `tsc --noEmit --incremental false`: passed.
- ESLint for both new TSX files: passed.
- `git diff --check`, plus whitespace checks covering the new untracked files.
- No tracked pre-existing files changed; additions are the primitives TSX,
  scoped CSS module, focused tests and this note. Existing unrelated untracked
  files are retained. Nothing staged, committed, pushed or deployed.

Deliberately rejected from 3a: blue-black wholesale recolouring, new font
migration, overlapping/tilted card artwork, italic all-caps headings, fake
coordinates, giant section numbers, decorative Japanese copy, stamped returns,
invented data/actions, and fixed-height or bottom-bar mobile compositions.
