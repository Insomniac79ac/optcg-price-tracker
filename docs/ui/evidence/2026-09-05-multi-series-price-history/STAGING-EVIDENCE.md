# Canonical staging identity, and the "20 prints" correction

## What the harness was pointed at

| | |
|---|---|
| Frontend under test | local production build (`next build` + `next start`, :3100) of this working tree |
| Deployed frontend | `https://optcg-price-tracker-staging.vercel.app` |
| API base | `https://optcg-price-tracker-staging.up.railway.app`, via a local CORS-injecting **read-only GET** proxy on :8001 |
| `/health` | `{"status":"ok","app_env":"staging","database_connected":true,"redis_connected":true,"version":"0.1.0","git_commit":"unknown"}` |
| Database | validated by `scripts/staging_db_read_check.py` |

`staging_db_read_check.py` result:

```
  [PASS] session is read-only: transaction_read_only='on'
  [PASS] fingerprint A - required tables: all present
  [PASS] fingerprint B - named indexes/constraints: all present
  [PASS] fingerprint C - print-lineage columns: all present
  [PASS] fingerprint D - alembic revision: found=['b8e3f1a70d95'] expected=['b8e3f1a70d95']
  [PASS] fingerprint E - non-empty invariants: canonical_cards=2710, card_prints=4316, sources=3
  RESULT: PASS - this connection is the Atlas staging database.
```

`GET /prints?limit=1` reports `total = 4316`, matching `card_prints = 4316`
from the fingerprinted database. The API and the DB agree, so the harness was
reading canonical staging all along.

## The four disputed IDs

| id | `GET /prints/{id}` | identity returned | `GET /prints/{id}/series` | frontend `/prints/{id}` |
|---|---|---|---|---|
| 3580 | 200 | OP17-040 Edward.Newgate, jp, R | 200, no available series | 200 |
| 4671 | 200 | OP10-025 Enel, jp, R | 200, no available series | 200 |
| 5687 | 200 | OP01-078 Boa Hancock, jp, SPカード | 200, Market Index + SNKRDUNK, 10 pts, 3 breaks | 200 |
| 6806 | 200 | OP01-013 Sanji, jp, R | 200, Market Index + SNKRDUNK, 10 pts, 5 constrained | 200 |

The frontend returns 200 for every `/prints/{id}` including invalid ones,
because the print page is a client-rendered route: the HTML shell is always
served and the print is fetched in the browser. That is existing behaviour,
not a regression.

## Root cause of the "20 prints" claim: B — an incorrect inference

Not a wrong backend, not a stale fixture, not a route or data regression.

Print IDs are **sparse**. I scanned the contiguous range 1..120, found data
only in 1..20, spot-checked 21/25/60/100/300 (all genuinely 404), and
generalised that to "staging holds only 20 prints". The real catalogue lives
at much higher ids - the first row `GET /prints` returns is `card_print_id:
3342` - so a low contiguous scan says nothing about the total.

The claim was wrong in a way that mattered: it was used to justify deleting
three scenarios as "not reproducible". All three exist.

## Actual coverage across all 4,316 prints

Counted from `source_coverage` over the full paginated catalogue:

| coverage | prints |
|---|---|
| no source at all | 4,026 |
| Yuyu-Tei only | 247 |
| SNKRDUNK only | 26 |
| both | 17 |

And from `/series` over the 290 priced prints: 223 carry an index-version
break, 224 have the index sitting exactly on a single source's value, 14 carry
a constrained ¥1,000 SNKRDUNK reading, 1 carries a missing-day gap, and
**0 carry a source instrument / reference-type break**.
