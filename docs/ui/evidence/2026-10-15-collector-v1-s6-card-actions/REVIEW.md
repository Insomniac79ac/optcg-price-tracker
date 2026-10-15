# S6 visual review (fresh `cardpirate-visual-reviewer`, screenshots only)

Evidence: `before/` (origin/staging 7ca4024), `after/`, `states/` (collector
panel form states on an unowned version; `report.json` = measured horizontal
overflow and any target under 44px: none). Local dev server, mock API test
data, placeholder card art (image hosts unreachable from the cloud session).
Mobile full-page captures show the fixed bottom nav mid-page (capture artifact).

## Round 1: REVISE

1. Sign-in/account used the old chrome (large wordmark, grey page), not the
   homepage's. Fixed: `/sign-in` and `/account` join the public shell.
2. Sign-in privacy line orphaned below the hero. Fixed: moved into the hero.
3. Account used a narrow column at desktop; delete button low contrast. Fixed:
   two-column chapters at >=1024px; coral delete button.
4. Signed-out "Sign in to add it" was a second gold CTA. Fixed: teal outline.
5. Form states and 320px unverified. Fixed: `states/` crops and `report.json`.

## Round 2: PASS

All criteria pass. Minor, not fixed: empty space between hero and footer on
sign-in at 1440; "Home" link wraps alone at 320/390 on sign-in.
