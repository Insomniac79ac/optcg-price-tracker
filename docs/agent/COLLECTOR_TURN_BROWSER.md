# One warmed browser per due-work turn (2026-10-10, session 8)

Until now, both collectors launched a new browser, a new context and a
homepage warm-up for **every** capture. Interception disables Playwright's
cache, so each capture downloaded the homepage and all its scripts and styles
again. Measured over 24h (`freshness_attempts.actual_request_cost`):

- Yuyu: 55.3 requests per capture.
- SNKR: 162.3 requests per capture.
- Budget peaks over 72h: Yuyu 8,745/9,000 and SNKR 2,959/3,100.

The homepage is roughly 45% of each capture (estimate from a local,
fully-aborted replay of retained RAW). The SNKR homepage was also stored as
RAW on every attempt (18.9 MB/day).

## What changed

- `run_due` opens one `TurnBrowser` per scheduled turn. Each attempt opens its
  own page in that context.
- A single context-level `TurnMeter` forwards a request to the bound
  attempt's existing handler, but only when it comes from that attempt's own
  page. The handler (admission, charging, redirects, denial, settle fence) is
  unchanged.
- Everything else is aborted before it is sent and never charged:
  - requests while no attempt is bound;
  - requests from a closed page;
  - requests from a page-less worker.
- Each attempt settles before it is unbound.
- Only an attempt that finds the turn cold warms the homepage, and it pays
  for that warm-up within its own reservation. SNKR still stores and gates on
  the homepage at every warm-up, so it stores one homepage row per warm-up
  instead of one per attempt.
- The turn stays warm only after a clean capture: usable homepage, HTTP 200,
  normal page, attempt neither stopped nor denied, settle and page close
  succeeded. Anything else discards the browser, and the next attempt starts
  exactly like today's per-capture run.
- Discovery claims discard the turn first, because a second sync Playwright
  cannot start in the same thread while the turn's is running.
- Planned SNKR recovery and explicit runners keep the per-capture path.
- Unchanged: schedules, budgets, 300-request reservations, inter-attempt
  delay, claim caps, drain, parsers and RAW policy. The page context options
  (user agent, viewport, locale, Accept-Language, service workers blocked)
  are identical. Nothing is spoofed, rotated or newly blocked.

## Expected effect (estimate) and how it is verified

| Source | Requests per capture | Budget peak |
|---|---|---|
| Yuyu | 31–37, was 55.3 | ~55–65%, was 97% |
| SNKR | 82–106, was 162.3 | Stays high while SNKR is budget-bound |

- SNKR completes its due work in fewer windows, and its daily requests fall.
- SNKR homepage RAW drops to about one row per warm-up, roughly 18.9 → ~1–3
  MB/day.

Verify on natural turns against the pre-release 24h baseline:

- average `actual_request_cost` per source and the peak per window;
- captured and no_listing rates;
- identical extracted prices on sampled URLs before and after;
- due and overdue unchanged;
- 0 for 403, 429, challenge and `source_denial`, with no rise in
  `optional_resource`;
- `turn_browser_summary` launches and warm-ups;
- SNKR homepage RAW rows per day.

Preflight: `evidence/turn-warmed-context-preflight-20261010.json`.
