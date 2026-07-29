# The ATLAS loop

A lightweight, repeatable process for small, screenshot-driven CardPirate
Atlas frontend tranches. It exists so visual work stays scoped, gets judged
on how it actually looks and feels (not just that tests pass), and always
lands in a clean, shippable state.

One tranche = one page or component group, one emotional outcome, one
commit. Use `docs/ui/TRANCHE_TEMPLATE.md` to write the contract for each
tranche before touching code, `docs/ui/VISUAL_RUBRIC.md` as the scoring
reference, and the `cardpirate-visual-reviewer` agent as the fresh grader.
See also the `cardpirate-collector-ui` skill for the product principles
this loop is judged against.

## Aim

The operator (human) defines, before any code is written:

- one page or component group;
- one emotional outcome the visitor should walk away with;
- what must visibly change;
- what must not change;
- acceptance criteria.

This is the "what are we actually trying to make someone feel" step — skip
it and every later step has nothing concrete to check against.

## Trace

Claude, before writing implementation code:

- inspects the current code for the target page/component group;
- identifies existing components, data, and API calls that can be reused
  rather than duplicated;
- captures **before** screenshots at desktop and mobile widths;
- proposes a concise tranche contract (`docs/ui/TRANCHE_TEMPLATE.md`)
  covering scope, emotional outcome, real data available, and acceptance
  criteria;
- waits for explicit approval whenever a meaningful visual decision is
  still unresolved (a layout direction, a copy direction, which real data
  to lead with) — do not silently pick one and proceed.

Trace ends with an agreed contract, not a diff.

## Lay down

Claude implements, and only:

- the agreed scope from the tranche contract — no opportunistic redesign
  of adjacent pages or components;
- reusing existing data, components, tokens, and typography rather than
  inventing a parallel system;
- runs focused tests for the changed area (not necessarily the full suite
  yet — that happens at Ship).

If something in scope turns out to need a decision the contract didn't
cover, stop and ask rather than expanding scope unilaterally.

## Audit

A **fresh** `cardpirate-visual-reviewer` agent — a new context, not the
context that built the tranche — reviews the result:

- examines the rendered page (desktop and mobile);
- compares before/after screenshots against the tranche contract;
- scores the fixed rubric (`docs/ui/VISUAL_RUBRIC.md`);
- gives specific, concrete criticism (component/region-level, not generic
  opinions) and the three highest-impact improvements;
- states PASS or FAIL explicitly.

The builder may perform **at most two** visual revision rounds in response
to reviewer feedback. If the tranche still fails after two rounds, **stop**
and hand it back to the operator for direction rather than broadening
scope, changing the acceptance criteria, or trying a third unreviewed
attempt.

Functional tests passing is never sufficient on its own — the reviewer's
score is the gate for anything visual.

## Ship

Only once the tranche has passed audit:

1. Run TypeScript and the focused tests for the changed area.
2. Run the production build.
3. Create **one** focused commit for the whole tranche.
4. Push to `staging`.
5. Deploy (the project's existing manual deploy step — deploys are not
   git-triggered here, see `docs/staging_deployment.md`).
6. Verify the stable staging URL actually serves the change.
7. Save final desktop/mobile screenshots as the tranche's evidence.
8. Leave the working tree clean — no stray files, no uncommitted changes.

## Between tranches

Run `/clear` before starting an unrelated tranche. Each tranche is a fresh
Aim → Trace → Lay down → Audit → Ship pass — carrying over context from a
previous, unrelated tranche invites scope creep.
