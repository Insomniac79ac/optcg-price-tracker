# Tranche: Collector v1 S5 — sign-in invite and account section

Plan: `docs/agent/plans/collector-v1/PLAN.md` §D1, §D4, §D5 and §H row S5 (on
`plan/collector-v1`, APPROVED). Owner decision Q2 approved. Staging only.

## Page or component
`/sign-in` (the invite every collector route sends a non-collector to) and
the new `/account` page. One component group: the collector's way in and
their account.

## Emotional outcome
A collector understands what an account is for and how to get one, and,
once signed in, feels in control of their own data.

## User's five-second impression
Signed out: "Sign in with Google to track what my cards are worth; it's
invite-only for now, and I can keep browsing without it."
Signed in: "This is my account: who I am, my currency, and buttons to take
my data or delete it."

## Must visibly change
- `/sign-in`: a short purpose-led invite ("Track what your cards are
  worth…") on the Atlas map-surface header; no mention of the deleted
  grading pages; invite-only note while Google is in Testing mode; an
  admin session is told collector features need a Google account.
- `/sign-in` when Google is not configured: says collector sign-in is not
  open yet and offers the public routes, never "nothing to sign in to".
- New `/account` (noindex): Profile, Preferences (currency JPY only),
  Export my data (JSON and two CSVs), Delete my account (typed
  confirmation), Sign out.
- Signed-in header gains an "Account" link.

## Must not change
- `/`, `/cards`, `/prints/*`, `/analytics`, info pages, admin shell and
  `/admin/login`.
- The legacy `/collection` and `/wishlist` pages themselves (S7/S8).
- Header layout for signed-out visitors and admins.

## Real data available
- Authentication state (signed out, collector, admin).
- `GET /me/profile` (email, name, member since) and `GET /me/preferences`
  through the server; Google avatar from the session.
- No prices or cards on these pages.

## Before evidence
- `screens-before/` (staging, desktop 1440 and mobile 390): `/sign-in`,
  `/collection` (redirects to `/sign-in`), `/account` (404), `/`.
- Problems: the invite says "Collector accounts are not enabled yet, so
  there is nothing to sign in to" (a dead end) and lists grading, which S1
  deleted; there is no account page.

## Acceptance criteria
1. Signed-out `/collection`, `/account` and the homepage "My collection"
   link land on `/sign-in` with the callback kept, and the page offers a
   next step (Google button, or public links when sign-in is closed).
2. An admin session on `/collection` or `/account` gets the same invite.
3. `/account` shows profile, currency (JPY selected, others disabled),
   export links, delete with typed confirmation, sign out; noindex.
4. When the accounts API is switched off, `/account` says so plainly
   instead of erroring.
5. No horizontal overflow at 390 and 320 px; 44 px touch targets on mobile.
6. No bearer token anywhere in the page, its scripts or the session JSON.

## Verification
- focused tests (sign-in page, account page, proxy guard, BFF)
- build
- desktop and mobile screenshots (local build with a test collector session
  and a local API; staging alias for the signed-out states)
- fresh visual-reviewer score

## Commit
One focused commit for the UI tranche.
