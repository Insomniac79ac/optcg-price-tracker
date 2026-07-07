# apps/web

Next.js dashboard for the OPTCG price tracker. Fetches directly from the API in the browser
using `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`).

## Development

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) — it redirects to `/dashboard`.

## Pages

- `/` — redirects to `/dashboard`.
- `/dashboard` — table of cards from `GET /cards`.
- `/cards/[id]` — card detail, price chart, and price observations from `GET /cards/{id}` and
  `GET /cards/{id}/prices`.
