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

Proceed without asking for confirmation for:

- reading or searching files in this repository;
- editing files inside this repository when the current task authorizes code changes;
- running tests, type checks, linters, builds, and local validation;
- git diff, git status, git log, and other read-only Git inspection;
- read-only database queries when the task authorizes database inspection;
- read-only Railway, GitHub, and Vercel inspection;
- creating disposable local test artifacts outside tracked repository paths.

Ask before:

- accessing or mutating production;
- database writes or migrations against staging or production;
- approving, rejecting, deleting, or changing card/source mappings or candidates;
- changing Railway or Vercel service configuration;
- changing cron schedules or deployment triggers;
- manually triggering collectors, discovery jobs, backfills, or other external jobs;
- committing or pushing unless the current task explicitly authorizes it;
- destructive Git or filesystem operations such as reset, clean, force push, or broad deletion;
- deleting services, databases, volumes, environments, deployments, or other external resources;
- actions that create material external cost or irreversible external state.

If the current task explicitly authorizes one of the actions above, carry it out without asking again unless the live state materially differs from the task's assumptions, a new safety risk is discovered, or the action would affect a broader scope than the user authorized.

Do not ask for confirmation merely to continue ordinary implementation, investigation, testing, or read-only verification already within the stated task scope. Stop and ask only when a decision would materially change product behavior, data semantics, infrastructure state, or the authorized scope.
