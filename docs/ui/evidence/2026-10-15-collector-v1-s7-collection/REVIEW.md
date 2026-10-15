# Review: Collector v1 S7, collection page

Fresh `cardpirate-visual-reviewer` agent (did not build the tranche), local
evidence only (staging alias not reachable from the cloud session).

## Round 1: PASS

Scores: emotional relevance 4, design coherence 4, originality 4,
functionality 4, craft and accessibility 4. Checked: PLAN E2 order; unpriced
"No price yet", never ¥0; 30D unavailable shows "—" with its reason, never
0%; preview dashed and labelled; grid 5/2/1 columns at 1440/390/320; art
`object-fit: contain`; 0px horizontal overflow; no banned words; no bright
red/green.

Defects raised and what happened:

1. Preview line outweighed the short recorded line. Fixed: preview thinner,
   sparser dash, 55% opacity.
2. 320px single column makes a long page. Kept: the contract (PLAN E2)
   asks for one column at 320px.
3. Edit buttons exactly 44px. Fixed: 48px.
4. By set "— 7D" had no reason in words. Fixed: "— 7D: No price yet" or the
   window's reason.
5. Movers named two versions of one card alike. Fixed: printing label
   ("Alt Art") next to the name.
6. Empty state leaves a dark gap above the footer. Kept for now (same
   pattern as /sign-in).
7. Keep the value headline single, no sparkline. Kept as is.

After shots in `after/` were re-taken after the fixes.
