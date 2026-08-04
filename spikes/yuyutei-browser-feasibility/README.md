# Yuyu-Tei browser-access feasibility spike

Standalone, isolated spike. Not part of the application - does not import
from `services/*` or `apps/*`, does not touch the application database, and
is not wired into any deploy path.

## Goal

Determine whether a real Chromium browser session (via Playwright) can load
and read Yuyu-Tei One Piece card pages that return HTTP 403 to `curl` /
WebFetch. Prior comparison work (see `output/` from earlier runs, gitignored)
found the 403 uniform across browser engines/channels/contexts in a
datacenter environment - this local test re-checks from an ordinary
user-owned computer and network.

## Rules honored

- No proxy rotation. Optional outbound proxy support (see below) is a
  single fixed/sticky endpoint only, off by default, and never used against
  Yuyu-Tei without explicit approval.
- No CAPTCHA-solving services.
- No fingerprint spoofing beyond supported Playwright context options - no
  impersonation of a specific person, no manually set `Sec-Fetch-*` or other
  browser-controlled headers.
- No attempt to bypass a challenge/access-denied page if one renders; the
  spike only records what rendered.
- No writes to the application database.
- No deployment.
- No stealth plugins or CAPTCHA solving.
- Deterministic extraction only (regex/DOM selectors) - no AI model calls.
- Maximum one navigation attempt per URL per run.

## Optional fixed outbound proxy

Off by default. Set all of `YUYUTEI_PROXY_SERVER`, `YUYUTEI_PROXY_USERNAME`,
and `YUYUTEI_PROXY_PASSWORD` (username/password optional if the endpoint
doesn't require them) to route the browser through a single fixed/sticky
endpoint - no rotation, no provider selected or purchased by this spike.
Never commit credentials; they are read from the environment only and are
never printed to logs (only whether a proxy is configured is logged).

## What the local test does

`spike.py --mode persistent_chrome` (the default for the run scripts below):

- Launches **headed branded Google Chrome** (Playwright `channel="chrome"`).
- Uses a **dedicated persistent profile** at `.chrome-profile/persistent_chrome/`
  inside this spike directory (gitignored) - ordinary cookies/storage are
  retained across the run, never a person's real browser profile.
- Visits, in order: Yuyu-Tei homepage -> OP01 category page -> OP01-001 Zoro
  parallel product page.
- Records per page: HTTP status, page title, final URL, navigator UA,
  response classification (`normal_product` / `static_403` /
  `challenge_or_captcha` / other), and elapsed time.
- Saves a screenshot, rendered HTML, a Playwright trace, and `result.json`
  for the run.
- Runs deterministic product-field extraction only when the product page
  classifies as `normal_product`.

Other modes from the earlier browser/engine comparison (`control_*`,
`desktop_context_*`, `chrome_channel_*`, `firefox_*`, `webkit_*`) still exist
in `spike.py --mode <name>` for manual use, but are not run by the local
scripts.

## Windows

```powershell
# 1. Create a virtual environment
cd spikes\yuyutei-browser-feasibility
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies and branded Chrome support
pip install -r requirements.txt
python -m playwright install chrome

# 3. Run the test
python spike.py --mode persistent_chrome

# 4. Locate the result
type output\persistent_chrome\result.json
```

Or run `.\run_windows.ps1` from this directory to do all four steps in one
command.

## macOS / Linux

```bash
cd spikes/yuyutei-browser-feasibility
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chrome
python3 spike.py --mode persistent_chrome
cat output/persistent_chrome/result.json
```

Or run `./run_macos_linux.sh` (`chmod +x run_macos_linux.sh` first if needed).

## Output

Written to `output/persistent_chrome/` (gitignored):

- `00_homepage.png` / `.html`
- `01_category.png` / `.html`
- `02_product.png` / `.html`
- `trace.zip` - open with `playwright show-trace trace.zip`
- `result.json` - status/title/URL/classification per step, plus
  `extracted_product` if the product page rendered normally
