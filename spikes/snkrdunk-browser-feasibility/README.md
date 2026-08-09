# SNKRDUNK browser-access feasibility spike

Standalone, isolated spike. Not part of the application - does not import
from `services/*` or `apps/*`, does not touch the application database, and
is not wired into any deploy path.

## Goal

Determine whether an ordinary Playwright Chromium session, run from a
temporary Railway service (`snkrdunk-feasibility`, project `glistening-peace`
/ `staging`), can reliably reach SNKRDUNK's public ONE PIECE pages, and if
so, extract exact-print raw-market data (floor price, recent sold history)
for one of the 20 already-verified `card_prints` in the application
database.

This is discovery/extraction-only. It does not create a SNKRDUNK source
mapping, does not write observations, does not modify Market Index logic,
and does not stand up a permanent collector or cron.

## Rules honored

- No stealth plugins, no fingerprint spoofing beyond ordinary Playwright
  context options (UA, viewport, locale, Accept-Language).
- No proxy rotation - Railway Static Outbound IPs only, one fixed set.
- No CAPTCHA-solving.
- No sign-in / account creation / stored credentials.
- No repeated retries after a 403/429 - the access stage stops immediately
  on the first blocked or challenged response.
- No attempt to bypass a rendered challenge page - only records what
  rendered.
- Deterministic extraction only (regex/DOM/embedded-JSON parsing) - no AI
  model calls.
- One navigation attempt per URL per run.
- Historical SNKRDUNK discovery/matching code under
  `services/worker/worker/` (`snkrdunk_discovery.py`, `snkrdunk_matcher.py`,
  etc.) is **not** imported or relied on as source of truth for current site
  structure - this spike verifies independently against the live site.

## Stages

`spike.py --stage <name>`:

- `access` (default) - navigates, in order: SNKRDUNK homepage ->
  `/brands/onepiece` -> `/brands/onepiece/categories/33`. Classifies each
  response (`normal_page` / `static_403` / `static_429` /
  `challenge_or_captcha` / `error`), saves rendered HTML + screenshot per
  step, and a Playwright trace. Stops immediately after the first
  blocked/challenged/errored response. On the category page, additionally
  harvests every `<a href>` on the page (deterministic, no market data) to
  `output/<run_id>/02_category_33_links.json` for offline discovery-surface
  review.
- `full` - reserved for the complete access -> discover -> extract session
  once real site structure from an `access` run informs the discover/extract
  implementation (spec sections 6-12). Not yet implemented beyond `access`.

## Known prints reference

`known_prints.py` holds frozen, hand-copied identity fields (card code,
names, treatment, official Bandai artwork URL) for the top-preference
candidates from the 20 verified `card_prints`, sourced by a one-time
read-only query against the staging database. This spike never connects to
Postgres itself; `known_prints.py` is the only offline reference used for
exact-print verification (section 7).

## Running locally

```bash
cd spikes/snkrdunk-browser-feasibility
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chromium
python3 spike.py --stage access
cat output/<run_id>/result.json
```

## Running on Railway

Deployed as the temporary `snkrdunk-feasibility` service (no public domain,
`restartPolicyType=NEVER`, no database/Redis reference, no cron, Static
Outbound IPs enabled). Each deploy runs one bounded session to completion
and exits. Structured per-step results are printed as compact JSON to
stdout (`railway logs`) as both individual `navigate_result` events and one
final `RESULT_JSON=...` line, so evidence is recoverable via logs alone even
without pulling files off the ephemeral container.

## Output

Written to `output/<run_id>/` (gitignored):

- `00_homepage.png` / `.html`
- `01_brand_onepiece.png` / `.html`
- `02_category_33.png` / `.html` (+ `02_category_33_links.json` if reached)
- `trace.zip` - open with `playwright show-trace trace.zip`
- `result.json` - status/title/URL/classification per step
