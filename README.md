# optcg-price-tracker

Tracks One Piece Card Game (OPTCG) price changes across **Yuyu-Tei** and **SNKRDUNK**, so that
price trends and drops can be monitored over time.

## Planned stack

- **Web**: Next.js
- **API**: FastAPI
- **Database**: Postgres
- **Cache / queue**: Redis
- **Worker**: Python

## Development approach

Development starts with mock data. Live scraping of Yuyu-Tei and SNKRDUNK is added only after
the core data model, API, and worker pipeline work end-to-end against mock data.

## Status

This repository currently contains only the project skeleton (directory layout and config
placeholders). No application code has been written yet.
