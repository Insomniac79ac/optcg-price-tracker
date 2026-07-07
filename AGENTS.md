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
