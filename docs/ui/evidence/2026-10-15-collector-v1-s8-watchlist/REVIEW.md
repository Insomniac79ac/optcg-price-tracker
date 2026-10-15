# S8 /watchlist: fresh visual review

## Round 1: FAIL

Scores: emotional 3, coherence 4, originality 3, functionality 4, craft 3.

Findings:
- Rows led with labelled numbers next to a small thumbnail, so the page was not art first.
- Row heights were uneven.
- Card-name links measured just under 44px (sub-pixel).

Fixes applied:
- Rebuilt as the /collection tile: full uncropped art first, then name, value as of the day, target and distance, 7D, freshness, and Edit pinned to the bottom of the tile.
- Name links now measure 44px or more.
- Edit's accessible name now reads "Edit target for <card>, <version>".

## Round 2: PASS

Scores: emotional 4, coherence 4, originality 4, functionality 4, craft 4. No critical defect.

What happened to each suggestion:
1. Two columns at 320px. Kept at one column. It matches /collection (PLAN E2: 1 column at 320, 2 at 390), and at 320 two columns would shrink the art to about 140px.
2. A richer empty state. Kept, the same as /collection. It has a gold "Find a card" button that says what to do; inventing placeholder cards would fake content.
3. Contrast. Measured, no change needed. `--subdued` #a0b2b6 on #111b20 is 7.9:1, teal #8dc9c4 is 9.4:1 and body #b5c6cd is 9.9:1. All exceed WCAG AA (4.5:1).
4. Tile text rhythm. Kept. Edit is pinned to the bottom of each tile, and the length of a reason is real information.
5. Evidence hygiene. Noted. The fixed bottom nav overlaps full-page mobile captures, which is a capture artifact. The states/ folder shows the sheet and the saved tile at every width.
