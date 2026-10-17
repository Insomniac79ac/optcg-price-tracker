# Plan: profile overview, sign-out cleanup, grouped number input

Status: plan only, nothing built. Product lane, staging only.
Requested 2026-10-17 by the owner (pragmatist scope, final).

## Base

#163 (`design-cleanup/b-profile-shell`) is still open as a draft, so this plan
and the build branch **stack on `design-cleanup/b-profile-shell`** (dc54fff).
When #163 merges, rebase the build branch on `origin/staging` before marking
it ready. Nothing here edits a file #163 changes.

## 1. Overview strip on /account

### What the collector sees
A row of four tiles directly under the account hero, above "01 Profile",
in the current account surface style (AccountSurface panels, the collection
page's up/down colours). Two by two at 320 to 639 px, four across from 640 px.
Every tile is one link with a 44 px minimum target.

| Tile | Shows | Links to |
| --- | --- | --- |
| Collection value | `yen(summary.value_jpy)` and the 7D change (`history.change`, same figure as the 7D chip on /collection), or "7D: reason" via `unavailableReason` | /collection |
| Cards | `summary.total_cards` cards, with "N priced" when coverage is partial | /collection |
| Watching | number of watch entries, with "N with a target" | /watchlist |
| Closest to target | card name and `targetDistance(entry)` ("¥300 above your target", "At your target") | /watchlist |

### Data (no new endpoints)
- `GET /me/collection/value?window=7d` already returns `summary` (value,
  total cards, coverage, the same `_coverage()` as `/me/collection`) and
  `history.change` (the 7D figure). One call covers tiles 1 and 2.
- `GET /me/watchlist` covers tiles 3 and 4 (`entries`, `target_jpy`,
  `target_gap_jpy`, `print`).
- Both are fetched in `loadAccountOverview` with the token it already mints,
  in parallel with profile and preferences. Each is `.catch(() => null)`, so a
  failed tile reads "Not available right now" and the rest of the page renders.
  The `disabled` and `error` states for profile/preferences stay as they are
  (no strip).

### Closest-to-target rule (default picked)
Among watches with both a target and a price (`target_gap_jpy !== null`):
1. Any at or below target wins ("At your target" / "¥X below your target"),
   the largest drop below target first.
2. Otherwise the smallest gap relative to the target (`gap / target`), so a
   ¥500 card ¥50 over does not beat a ¥30,000 card ¥600 over.
The words shown are the API's gap through the existing `targetDistance`.
The ratio is used only to order, never shown.

### Empty states
- Zero cards: value tile "No cards yet", cards tile "0 cards", both still link
  to /collection (its own empty state explains how to add one).
- No prices yet: value tile "No prices yet" (never ¥0).
- Zero watches: watching tile "0 cards", closest tile "Not watching any cards
  yet".
- Watches but no targets: "No targets set". Targets but none priced: "No
  prices for your targets yet".

### Files
- `apps/web/src/lib/accountServer.ts`: widen `getMe` path type, add the two
  reads, add `collection: CollectionValue | null` and
  `watchlist: WatchlistResponse | null` to the `ok` state.
- `apps/web/src/lib/watchlist.ts`: add `closestToTarget(entries)` (pure).
- `apps/web/src/components/account/AccountOverviewStrip.tsx` (new, server
  component): the four tiles.
- `apps/web/src/components/ui/AccountSurface.module.css`: tile grid and tile
  styles. Plain `content:` only (see web CSS gotcha); check computed style in
  a real browser.
- `apps/web/src/app/account/page.tsx`: render the strip under the hero.

## 2. Remove the bottom "Sign out" on /account

### Header check (done for this plan, against #163)
- 640 px and up: `TopBar` `AuthControl` shows "Sign out" in the header
  (`hidden sm:flex` for collectors).
- Below 640 px (#163's one-row phone header): the button leaves the header and
  the ☰ drawer (`SidebarNav`, below `md` on public-shell routes, which include
  /account) ends with "Sign out". Screenshot evidence:
  `reports/design-cleanup/b/after/drawer-signed-in-320.png` and `-390.png`.
- So sign-out is reachable everywhere, one tap deeper on phones.
- Staging without #163: the header button is always visible.

### Change
- `apps/web/src/app/account/page.tsx`: delete the bottom sign-out section and
  the one in the `Unavailable` state (the header covers that state too, it
  depends only on the session).
- `apps/web/src/app/account/AccountActions.tsx`: delete `SignOutButton` (no
  other user) and the now unused `ActionButton` import. `DeleteAccount` keeps
  its own `signOut` after a delete.

## 3. One grouped number input

### Where it is used (every collector yen or quantity field)
All three live in `components/ui/PrintCollectorActions.tsx` and render in
three places: the print page (/prints/[id]), the /collection edit sheet and
the /watchlist edit sheet (`CollectionEditSheet.tsx`).
- `CollectionForm`: "How many" (1 to 9,999) and "What you paid per card"
  (0 to 100,000,000).
- `WatchForm`: "Target price" (1 to 100,000,000).
Admin number fields (limits, days, scores) are not yen or quantity and stay as
they are.

### Component
`apps/web/src/components/ui/GroupedNumberInput.tsx` (client) plus pure helpers
in `apps/web/src/lib/groupedNumber.ts`.
- Props: `value` (plain digit string, the form's state), `onValueChange(digits)`,
  plus pass-through `id`, `placeholder`, `className`, `aria-*`.
- Renders `<input type="text" inputMode="numeric" autoComplete="off">`.
  No `pattern="[0-9]*"`: commas would fail it and trip `:invalid` styling.
  `inputMode="numeric"` alone opens the number pad on iOS and Android.
- Display is the digits grouped with commas (`30000` shows `30,000`). State,
  validation and the request body stay plain numbers: forms keep `parseYen`
  (already strips commas) and `Number()`.

### Behaviour
- Typing: after each input, strip to digits, regroup, then put the caret after
  the same number of digits it was after before (count digits left of the
  caret, not characters).
- Backspace onto a comma (`30,|000`): delete the digit before the comma, not
  the comma (`3,000`). Delete forward onto a comma removes the digit after it.
  Read `inputType` from `beforeinput`.
- Paste: normalise, then keep digits only when the text is digits with
  separators, spaces, `¥`, `￥` or `円` (`¥30,000`, `30000円`). Anything else
  (a decimal like `1,200.50`, letters) is kept as typed so the existing
  "whole number of yen" message shows, rather than silently becoming 120050.
- Full-width: `０-９` become `0-9`; `，` and `、` count as separators.
- Japanese IME: do not reformat between `compositionstart` and
  `compositionend`; normalise once on `compositionend`.
- Leading zeros collapse (`007` to `7`); a lone `0` stays (paid allows ¥0).
- Selection replaced by typing, cut, undo: same digit-count caret rule.
- Over the maximum: no truncation; the existing range message shows on submit.

### Files
- New `apps/web/src/lib/groupedNumber.ts`: `normaliseDigits`, `groupDigits`,
  `caretForDigitIndex`, `digitIndexAt`.
- New `apps/web/src/components/ui/GroupedNumberInput.tsx`.
- `apps/web/src/components/ui/PrintCollectorActions.tsx`: swap the three
  inputs; `parseYen` also accepts full-width digits; seed state with the plain
  number as today.

## Tests

- `lib/groupedNumber.test.ts`: grouping, full-width, separators, leading zeros,
  caret mapping (start, middle, end, around commas), paste cases above.
- `components/ui/GroupedNumberInput.test.tsx` (fireEvent, jsdom): shows
  `30,000` for `30000`; reports plain digits; backspace before a comma; no
  reformat during composition; `inputmode="numeric"`, no `pattern`.
- `components/ui/PrintCollectorActions.test.tsx`: typing `30000` sends
  `paid_jpy_per_card: 30000`, target `5,000` sends `target_jpy: 5000`;
  quantity `1,200` is still refused above 9,999; existing cases unchanged.
- `lib/watchlist.test.ts`: `closestToTarget` order and every empty case.
- `lib/accountServer.test.ts`: four reads with one token; a failed value or
  watchlist read gives `null`, not an error state; 404 still means disabled.
- `app/account/page.test.tsx`: tiles and links; every empty state; no
  "Sign out" button on the page in ok and unavailable states (the existing
  "shows ... sign out" case is rewritten); delete still signs out.
- Real browser (Playwright, the design-cleanup harness with the mock API):
  caret position after typing in the middle, backspace at a comma, paste
  `¥30,000`, on Chromium at 390 px; computed style of the new tile classes.
- Screenshots before and after: /account signed in at 320, 390, 1440 with
  data, zero cards and zero watches; the print page add/watch forms and both
  edit sheets at 390 and 1440. Fresh `cardpirate-visual-reviewer` pass.
- `npm test -- --maxWorkers=2`, `npx tsc --noEmit`, lint;
  `python scripts/product_lane.py --base origin/staging` shows PRODUCT and no
  collector import graph reason. No security paths touched, so no security
  review line needed.

## PR split

One PR, three commits (overview strip, sign-out removal, grouped input), all
in `apps/web` plus a `PRODUCT_LOG.md` line. Draft first; marked ready only
after #163 has merged and been verified, with no delivery running and no
`hold-for-owner` PR waiting (today #165). If the visual reviewer wants the
input change judged on its own, split commit 3 into a second PR; no code
change needed for that.

## Overlap with open PRs

- **#163** (design-cleanup/b-profile-shell, draft): base of this work. It
  changes TopBar, SidebarNav, AppShell, PublicBottomNav, publicNavigation and
  the drawer CSS. This plan touches none of them and relies on its drawer
  "Sign out" for phones. Only shared file: `docs/agent/PRODUCT_LOG.md`
  (append, trivial conflict).
- **#154** (design-cleanup/a-dead-code, delivering): deletes unused
  components and globals.css rules. No file in common except PRODUCT_LOG.
  It does not touch AccountSurface, PrintCollectorActions or the account
  page.
- **#162** (security account export validation, draft): API only
  (`accounts/schemas.py`, `service.py`, tests). Quantity, paid and target
  bounds are unchanged there (9,999 and 100,000,000), so the input limits stay
  correct. Its new `acquired_on` range check is server-side and does not
  change the form. No file in common except PRODUCT_LOG.
- **#165** (CSP enforce, hold-for-owner): `next.config.ts` only. No inline
  scripts or styles are added here, so the tighter CSP does not affect it.
  Owner-held, so it delivers before this PR.
- `design-cleanup/c-public-pages` (stacked on #163, no PR yet) changes
  `PrintClient.tsx` and TopBar; this plan touches neither.

## Later phase: collection analytics (not built)

Most of the data is already in `/me/collection/value`; /collection shows parts
of it today. Efforts are S (under a day), M (one to two days), L (more).

| Item | What exists | Work | Effort |
| --- | --- | --- | --- |
| Gain/loss vs paid, total | `paid` summary (paid, priced today, change %); shown on /collection "What you paid" | Add a tile to the /account strip | S |
| Gain/loss vs paid, per card | `paid_jpy_per_card` and `value_per_card_jpy` per entry | API field `paid_change_jpy` per entry (keeps "every number is the API's"), sortable list on /collection | M |
| Set breakdown | `by_release` with share and window change; shown on /collection "By set" | Share bar or ranked list, link to set pages | S to M |
| Rarity mix | Not in the API: `print_summaries` lacks `CardPrint.official_rarity` | Add rarity to the print summary and a `by_rarity` block in the value response; check lane with product_lane.py first | M to L |
| Top movers | `movers.up/down` and `cards[]` per window; shown on /collection "What moved" | Top 3 up/down on /account, 30D and ALL toggles | S |
| Value over time on /account | `history.points` | Small sparkline in the value tile, reuse CollectionHistoryChart styles | S |
