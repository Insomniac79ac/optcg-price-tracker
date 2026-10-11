# Self-hosted official card images (R2)

Owner decision, 2026-10-11: Card Pirate stores and serves the official Bandai
card list images itself, unmodified, instead of re-serving them from
`www.onepiece-cardgame.com` on every request. The aims are resilience if
Bandai's URLs or embedding rules change, and fewer requests to Bandai as
traffic grows. The images remain their owners' property. The site shows an
image credit in the footer and under the card on every card page
(`brand.imageCredit`).

Scope: only the official images that `card_prints.image_url` points at.
Yuyu-Tei and SNKRDUNK images are out of scope and unchanged.

## How it works

- **Package `services/api/app/official_images/`.** No collector imports it
  (checked against `scripts/collector_runtime_inputs.py`), so changing it is
  not a collector release.
- **Table `card_print_image_assets`** (migration `6c2242f6f439`, additive).
  - One insert-only row per print and exact `source_url`, including Bandai's
    `?version` suffix.
  - Each row records the R2 object key, SHA-256, byte length, dimensions,
    content type, cache policy and `mirrored_at`.
  - A new Bandai version is a new URL and gets a new row beside the old one.
  - Rows are never updated or deleted.
- **Objects** are content-addressed (`display-images/sha256/<ab>/<sha256>.<ext>`,
  the shared rule in `app/services/display_image_object_key.py`).
  - Uploaded with `Cache-Control: public, max-age=31536000, immutable`.
  - Never overwritten or deleted. An object already at the key (for example,
    one of the 20 earlier identity-evidence copies) is reused.
- **Verification per print, before any row is written:**
  - the source bytes' SHA-256 must equal `card_prints.artwork_key`, the
    first-party digest recorded at import;
  - the authenticated R2 GET must return the same digest;
  - the public GET over `R2_PUBLIC_BASE_URL` must return the same digest and
    the same decoded size.
  - Bytes are never re-encoded, resized, cropped or watermarked.
- **Politeness.**
  - One Bandai request at a time, at least 1 s apart (the floor cannot be
    lowered).
  - Exponential backoff that honours `Retry-After`.
  - Five consecutive transient failures stop the run.
- **Read path** (`app/services/display_image.py`).
  - The canonical Bandai image is served from R2 when a verified row exists
    for the print's *current* `image_url` and its digest equals
    `artwork_key`.
  - Otherwise the original URL is returned and the web app re-serves it
    through `/api/card-image`, which keeps its exact host allowlist.
  - Verified marketplace display images keep their existing priority and
    origin.
  - The read path makes no network call.

## Commands

Run from `services/api` with the staging `DATABASE_URL` and the `R2_*`
settings in the environment:

```console
python -m app.mirror_official_images --dry-run          # pending count; no requests
python -m app.mirror_official_images --write --limit 25 # bounded batch
python -m app.mirror_official_images --write --quiet    # everything pending (resume-safe)
python -m app.check_official_images                     # silent when healthy, exit 1 otherwise
python -m app.check_official_images --verify-objects    # also HEAD every object
```

**After a catalogue import** that adds prints or changes an `image_url`, run
`mirror_official_images --write`.
- The importer itself stays frozen-input and never fetches from Bandai.
- Until the mirror runs, the new prints are served through the proxy fallback.
- `check_official_images` reports them as `missing_copy`.

## Rollback

- Revert the PR. The read path then serves every canonical image through the
  proxy again.
- Rows and objects stay where they are (insert-only and immutable).
- The table can be dropped with `alembic downgrade f9e5b4a8c012` only by a
  separate decision. That would be a destructive migration.

## Constraints

- **`r2.dev` is a development endpoint.** Cloudflare: "Public access through
  `r2.dev` subdomains is rate-limited and should only be used for development
  purposes", and caching is unavailable on it
  (https://developers.cloudflare.com/r2/buckets/public-buckets/).
  - Staging uses it today.
  - Before public traffic, connect a custom domain to the bucket and point
    `R2_PUBLIC_BASE_URL` (API and Vercel) at it. No stored data changes,
    because URLs are built from configuration at read time.
- **Partner/data API responses must not include R2 image URLs or image
  bytes.** Partners get card identifiers and prices only.
