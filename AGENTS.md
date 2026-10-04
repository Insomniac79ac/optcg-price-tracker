# Agent / contributor guidelines

Rules to follow when working on this repository.

- **Small, reviewable changes.** Prefer many small PRs/commits over large ones.
- **Mock data before live scraping.** New features are built and validated against mock data
  first; live scraping is added only once the pipeline works end-to-end.
- **Store raw snapshots before parsing.** Always persist the raw scraped/fetched payload before
  extracting or transforming data from it, so parsing bugs don't destroy source data.
- **Never commit secrets.** No API keys, tokens, or credentials in code or config. Use
  `.env` (gitignored) with `.env.example` as the template.
- **Prices are stored in JPY.** Do not convert or store prices in other currencies.
- **Timestamps are stored in UTC.** Convert to local time only at display time.
- **Manual card mappings override fuzzy matching.** When a manual mapping exists for a card,
  it always takes precedence over any fuzzy/automatic match.

## Agent autonomy

Follow the [Card Pirate operating contract](docs/agent/AUTONOMY_POLICY.md) and
[hard invariants](docs/agent/INVARIANTS.md). Define missions with
[MISSION_TEMPLATE.md](docs/agent/MISSION_TEMPLATE.md), consult
[DECISIONS.md](docs/agent/DECISIONS.md), and reverify
[CURRENT_STATE.yaml](docs/agent/CURRENT_STATE.yaml) before external operations.

An authorized staging mission grants GREEN actions and AMBER actions after their
preflight/rollback safeguards pass. Agents decompose, implement, test, deploy,
observe natural operation and fix bounded defects forward without step approvals.
Apply the highest applicable authority level. RED decisions require a human.
Explicit user scope limits prevail; production access and changes remain gated.

Read-only repository/platform inspection, authorized read-only database queries,
local tests and disposable artifacts do not require additional confirmation.
Preserve unrelated working changes. Destructive Git/filesystem operations or
resource deletion outside bounded mission authority still require explicit
permission; a staging mission does not authorize broad deletion or force pushes.

For the initial contract PR, leave it open for review and do not deploy application
changes or access production. No permission in the proposed contract expands
that documentation-only task.
