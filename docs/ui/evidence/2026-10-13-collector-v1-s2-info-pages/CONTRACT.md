# Tranche: Collector v1 S2 — info pages and footer links

Plan: `docs/agent/plans/collector-v1/PLAN.md` §G and §H row S2 (on `plan/collector-v1`).
Owner decisions already made (Q3, Q8; session brief 2026-10-13). Staging only.

## Page or component
`/about`, `/methodology`, `/privacy` (draft), `/terms` (draft), and the
site-wide `Footer` link row. One shared reading layout for the four pages.

## Emotional outcome
A collector can see plainly who runs Card Pirate and how its prices are
made, so the numbers feel trustworthy.

## User's five-second impression
"This is a small independent tool, it tells me exactly where its prices come
from, and its legal pages are honestly marked as drafts."

## Must visibly change
- Footer gains a quiet link row: About, How we price cards, Privacy, Terms.
- `/about` and `/methodology` render as calm long-form reading pages
  (Fraunces title, Manrope body, ~70ch measure), not 404s.
- `/privacy` and `/terms` render with a visible "Draft – under review" banner
  and `[CONTACT EMAIL]` / `[GOVERNING LAW]` placeholders.
- Methodology has an in-page contents list so the long page is navigable on
  mobile.

## Must not change
- Header/nav, `/`, `/cards`, `/prints/*`, `/analytics` layout and data.
- Footer disclaimer and image credit text.
- Market Index, Market Value, CPI calculations or wording on other pages.
- Admin shell (footer links appear there too, same quiet treatment).

## Real data available
- No API data. Copy only, sourced from `docs/market_value.md`,
  `docs/market_index.md`, `docs/agent/INVARIANTS.md` and
  `docs/collector_accounts.md`. No numbers, cards, or prices are shown.
- No authentication state used.

## Before evidence
- `docs/agent/handoff/2026-10-13/collector-v1-s2/evidence/screens/before_*`
  (desktop 1440, mobile 390, full page and footer crops).
- Problems: all four routes answer 404; footer has no links at all, so there
  is no way to find who operates the site or how prices are made.

## Acceptance criteria
1. All four routes answer 200 and render the shared header and footer.
2. Footer links to all four pages on every page, including 320px width,
   without horizontal scroll.
3. `/privacy` and `/terms`: `<meta name="robots">` contains `noindex`, a
   visible draft banner (`data-draft-banner`), absent from sitemap.
4. `/about` and `/methodology`: indexable, canonical URL set, in sitemap.
5. No "portfolio", no personal name; operator is "Card Pirate".
6. Methodology claims trace to the source docs above (no new claims).
7. Body text contrast ≥ 4.5:1 (uses `--text-secondary`/`--text-primary`).

## Verification
- Vitest page render + metadata tests; footer link test; publicRoutes test.
- `next build`.
- Desktop and mobile screenshots after (local build, then staging alias).
- Fresh `cardpirate-visual-reviewer` score.

## Commit
One focused commit for the pages and footer (analytics and Sentry are
separate commits in the same PR: they are not visual).
