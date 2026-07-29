# Tranche contract template

Copy this into the PR description, a scratch file, or the conversation
itself at the **Aim**/**Trace** step of `docs/ui/ATLAS_LOOP.md`, before any
implementation code is written. Keep every section short — this is a
contract, not a design doc.

```markdown
# Tranche: [name]

## Page or component
[one route or component group]

## Emotional outcome
[one sentence describing what the user should feel or understand]

## User's five-second impression
[what should be immediately obvious]

## Must visibly change
- [maximum five items]

## Must not change
- [explicit out-of-scope areas]

## Real data available
- images
- card data
- Market Index
- authentication state

## Before evidence
- desktop screenshot
- mobile screenshot
- current problems

## Acceptance criteria
- [maximum seven testable criteria]

## Verification
- focused tests
- build
- desktop screenshot
- mobile screenshot
- fresh visual-reviewer score

## Commit
One focused commit only.
```

## Filling it in

- **Page or component** — one route or one component group. If the
  answer is "several pages," split it into separate tranches.
- **Emotional outcome** — one sentence, plain language, no jargon. If you
  can't state it in one sentence, the tranche is probably still two
  tranches.
- **Five-second impression** — what a first-time visitor should get
  without reading anything closely: what this page is, why it matters.
- **Must visibly change** — a short, capped list. If it's growing past
  five items, the tranche is too big.
- **Must not change** — name the adjacent pages/components/behaviour
  explicitly (e.g. "`/cards` grid layout," "Market Index calculation,"
  "admin shell"). This is what keeps `docs/ui/ATLAS_LOOP.md`'s Lay-down
  step from turning into an opportunistic redesign.
- **Real data available** — list only what's actually returned by the
  existing API for this page today. Anything not listed here should not
  appear in the tranche's UI (see the collector-UI skill's "do not
  fabricate" rule).
- **Before evidence** — screenshots captured during Trace, plus a short,
  concrete list of what's currently wrong (not "needs polish" — name the
  actual problem: "hero is a headline and two buttons with nothing else
  above the fold").
- **Acceptance criteria** — testable, not aspirational. "Hero shows up to
  3 real card images, capped, with no layout shift on load" is testable.
  "Feels more premium" is not — that judgement belongs to the visual
  rubric, not the acceptance criteria.
- **Verification** — every item must actually be run, not assumed. The
  visual-reviewer score is mandatory before Ship, per
  `docs/ui/ATLAS_LOOP.md` "Audit."
- **Commit** — the tranche ships as one focused commit. If the diff needs
  more than one commit to explain, the tranche was too big.
