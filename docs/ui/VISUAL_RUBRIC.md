# Visual rubric

The fixed scoring reference for the `cardpirate-visual-reviewer` agent and
for anyone manually grading a CardPirate Atlas UI tranche (see
`docs/ui/ATLAS_LOOP.md`). Five criteria, each scored **1–5**.

**Passing bar:** every criterion ≥ 4, and no critical functional or
accessibility defect. Falling short on any one criterion is a FAIL,
regardless of how well the others score — this is a gate, not an average.

Score what is actually rendered (desktop and mobile), not what the code
"should" produce. Compare against the tranche's before screenshots and its
stated emotional outcome (`docs/ui/TRANCHE_TEMPLATE.md`), not against a
generic UI checklist.

---

## 1. Emotional relevance

Does this make a collector curious, attached, or motivated? Is it obvious
within five seconds why this page matters?

**Strong (4–5):**
- Artwork leads the experience — a card, a set, a collection moment is the
  first thing that registers, not a headline.
- Copy connects to owning, chasing, or discovering cards ("the ones you're
  still chasing," "your collection has a story"), not to metrics or
  process.
- The visitor can say, unprompted, why this page exists and what it's for.

**Weak (1–3):**
- A generic title plus two buttons, with nothing underneath that
  demonstrates the product.
- Methodology, coverage statistics, or source-freshness explanations
  appear before any card does.
- An empty or near-empty dashboard standing in for a collector moment.
- Price or Market Index treated as the point of the page, rather than
  context alongside a card.

## 2. Design coherence

Do typography, colour, artwork treatment, layout, and spacing read as one
deliberate identity, not a stack of independently-styled sections?

**Strong (4–5):**
- Display type (Fraunces) used only where the brand calls for it —
  headings/hero — body and metadata stay on the sans/mono stack per
  `docs/interface_design_system.md` "Typography."
- Colour follows the token rules: gold for rarity/highlights, teal for
  navigation/discovery, coral used sparingly for emphasis — see
  `docs/brand.md` "Colour rules."
- Spacing and rhythm feel consistent section-to-section; nothing looks
  bolted on.

**Weak (1–3):**
- Mixed treatments that each look fine alone but don't cohere (e.g. one
  section dense/bordered, the next airy and borderless, with no reason).
- Colour used decoratively rather than by its assigned meaning (gold on a
  non-rare element, teal as a generic accent everywhere).
- Inconsistent corner radii, shadow, or border treatment across adjacent
  panels.

## 3. Originality

Does this feel deliberately designed for CardPirate Atlas, or could it be
any product with the logo swapped?

**Strong (4–5):**
- Deliberate cartography-inspired composition (a fanned card stack, a
  route/compass motif used sparingly, a "map" framing) — not a literal
  compass sticker on an otherwise generic layout.
- Clear CardPirate visual identity carried through artwork treatment
  (`CardImageFrame`'s vault/slab framing), not a stock card/image grid.
- Interaction and hierarchy choices that make sense specifically for
  *cards* (fanning, stacking, artwork-first tiles) rather than a
  repurposed generic content layout.

**Weak (1–3):**
- Standard three-column "feature" SaaS sections (icon, heading, one-line
  description, repeated 3×).
- Excessive rounded panels/cards used as the default container for
  everything, regardless of content.
- A generic gradient hero (especially a purple/blue Web3-style gradient)
  standing in for the brand's warm-dark palette.
- Repetitive stat-card rows that could belong to any analytics product.
- A crypto-dashboard treatment: large numeric tickers, sparklines, or
  green/red delta arrows as the visual centerpiece of a collector page.

## 4. Functionality

Is the primary purpose obvious, and do the actions/layouts actually work?

**Strong (4–5):**
- The primary and secondary actions are unambiguous and go where a
  collector would expect.
- Real data renders correctly (including the small/sparse staging
  dataset) — no dead links, no console errors, no silently-empty section
  where an empty *state* should be.
- Responsive layouts hold up structurally at both the desktop and mobile
  widths captured for the tranche — no overlap, no cut-off content, no
  horizontal scroll outside an intentional table/carousel.

**Weak (1–3):**
- A CTA that goes to the wrong route, a 404, or nothing.
- Interactive elements that don't respond, or respond only on
  desktop/mouse and not on touch.
- A layout that only works at one specific viewport width.

## 5. Craft and accessibility

**Strong (4–5):**
- Consistent spacing scale and clear visual hierarchy (the eye knows what
  to read first, second, third).
- Text contrast meets the ratios already established in `docs/brand.md`
  "Contrast decisions" — no new low-contrast combinations introduced.
- Visible keyboard focus on every interactive element.
- Accessible names are correct and non-redundant (one name per control,
  no name doubled by a decorative child — see the Discover-page logo fix
  as the canonical example of what *not* to reintroduce).
- Loading states reserve real layout space (skeletons sized like the real
  content) — no content "pop-in" or reflow once data arrives.
- Motion, if any, respects `prefers-reduced-motion` and is restrained
  (no shine sweeps, no flashing — see `docs/interface_design_system.md`
  "Do-not list").

**Weak (1–3):**
- Ad-hoc spacing that doesn't match the established scale.
- Low-contrast text, especially small metadata text on `bg-card` (see
  `docs/brand.md` "Practical rule" on teal/coral at small sizes).
- No visible focus ring, or focus order that doesn't match visual order.
- A link/button whose accessible name is missing, generic ("click here"),
  or duplicated.
- Skeleton/placeholder sized differently than the real content, causing
  layout shift on load.

---

## Critical defects (auto-fail regardless of scores)

Any of the following fails the tranche outright, even if every criterion
above would otherwise score ≥ 4:

- Broken primary action (can't reach the stated destination).
- Content that doesn't render at one of the two required viewports.
- Fabricated data of any kind — invented popularity, trends, rankings,
  collection stats, or prices not returned by the real API.
- A regression to a previously-fixed accessibility issue (e.g. a
  duplicated accessible name, missing focus indicator on a previously
  fixed control).
- Any change outside the tranche's declared scope.
