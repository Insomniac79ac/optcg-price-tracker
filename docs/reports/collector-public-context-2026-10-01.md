# Card Pirate public frontend product review

This review repositions the existing staging frontend around the cards collectors own or want. It covers public pages, search and sharing, with no changes to pricing, source collection or backend contracts. Baseline: staging `9f9c1c6`. Collection and wishlist remain private; account availability depends on the existing sign-in configuration.

## Information audit before implementation

| Route or surface | User question | Current answer | Information gap | Recommended change |
| --- | --- | --- | --- | --- |
| `/` | What are my cards worth, and what is moving? | “Find your next card”, random featured artwork, Recent finds, releases, movers | Discovery dominates; no clear value proposition or collection entry point | Collector headline, price search, Market and collection links; retain truthful recently added label |
| `/cards` and search/filter queries | What price belongs to the printing I own or want? | Exact-print tiles, source coverage, search, release/rarity/treatment filters | “THE CARD ATLAS”; data and links only appear after hydration | Card Prices; seed first page from existing public API; normal pagination links for crawlers |
| `/prints/:id` | What is this exact printing worth now? | Full art, canonical identity, archived index headline before current sources, history, sibling versions | Current price secondary to archive; “Updated” conflates meaning; no per-print metadata/SSR | Current Market Value first, observed time, sources, then dated archive/history; seed canonical data; distinct metadata and share art |
| `/cards/code/:cardCode` | Which physical version matches my card? | Canonical printing chooser; no merged family price | Client-only identity; generic metadata; blocked by `/cards/` robots rule | Keep chooser and avoid duplicate indexed family pages; make exact prints discoverable through SSR catalogue and sitemap |
| `/cards/:id` | Where is a legacy card link taking me? | Compatibility chooser and session-gated personal tools | Legacy ID is not exact physical identity | Preserve behavior; noindex compatibility surface, link exact prints |
| `/analytics` | Is the wider One Piece market up or down? | Published movement, partial tracked value, coverage, date, movers, valuable prints, release comparison | Technical chart language; first HTML lacks data; publication timestamp is not source freshness | Question-led heading, SSR headline with coverage, plain-language definitions, scoped share preview |
| `/cards?release_product_id=:id` | What are cards from this release worth? | Filtered exact-print catalogue and chronological navigation | No release-specific title, description, canonical or share preview | Use authoritative release ID and name in server metadata and page context; link release Market |
| `/analytics?release_product_id=:id` | How is this release moving? | Scoped published basket, coverage, chart, movers | Generic metadata; partial basket easily mistaken for whole release | Release-specific metadata and share card; explicit coverage adjacent to value |
| Market comparison and release table | Which releases are stronger or weaker? | Server-provided comparable series and release movements with missing states | “Performance”/rebasing language; constituent movement unavailable for sparse windows | Keep server eligibility/nulls; explain comparisons as price movement, retain gaps |
| `/market/movers` | Which cards moved? | Existing redirect to sorted Cards | Destination is current-price ordering, not a full mover history | Preserve redirect; homepage and Market mover panels remain the accurate movement destinations |
| `/collection`, `/collection/vault`, `/wishlist` | What do I own, what did I pay, what am I watching? | Authenticated legacy-card collection and wish list; summaries and acquisition inputs | Not public; exact-print ownership and reliable collection history cannot be assumed | Keep privacy and existing calculations; collector wording and noindex; document exact-print integration gap |
| `/analytics/*`, dashboard, grading, activity, search, market signals/reports | What is happening in my account? | Protected account/operational surfaces | Not public market evidence | Preserve authentication and crawler exclusions; no private share payloads |
| Navigation, sign-in, loading, error and empty states | Where do I go next? | Discover/Cards/Market; Atlas language; existing retry and missing states | Discovery framing; errors sometimes assert collection safety without evidence | Home/Card Prices/Market; task-specific recovery; unavailable is never zero |
| Metadata and social | What exactly did someone share? | Shared brand title and logo-only image across dynamic pages | Duplicate physical print titles; no contextual images | Canonical print/release metadata, 1200×630 contextual artwork/value previews |
| Crawlers | Can this page be read and cited without running JS? | Static three-route sitemap, wildcard robots, client-loaded dynamic evidence | Dynamic links/identity absent from HTML; no structured data | SSR public API reads, release sitemap entries, paginated catalogue links, truthful JSON-LD |

## Data boundaries

Current exact-print value is the existing `market_index.index_value_jpy`, presented as Market Value without changing its calculation. Market tracked value and coverage-neutral movement remain the existing, separate `market-value` contract. Neither is a guaranteed sale price. An archive/publication date never becomes a source observation or successful-check time.

## Missing information and backend follow-up

| User need | Missing field or data | Likely backend dependency | Priority |
| --- | --- | --- | --- |
| Know whether every current-price category was checked recently | Per-source/category last successful check, capture time, availability and freshness verdict, unknown reasons | Expose shared freshness contract on public exact-print/current-price APIs, including auxiliary categories; freshness adapters alone do not establish a public contract | P0 |
| Understand age of overall/release market inputs | Source freshness distribution for basket; oldest contributing observation and check coverage | Public market-value summary derived from source freshness contract; `as_of` remains publication context | P0 |
| Track the exact printing owned or wanted | Canonical exact-print collection/watch membership and actions | Existing collector contracts use legacy card identity; canonical ownership migration/API required | P1 |
| See reliable collection change and biggest contributors | Comparable historical collection values tied to exact-print holdings and quantity changes | Canonical holdings plus valuation snapshots and attribution; do not substitute market basket movement | P1 |
| See more reliable release/card movement | Sufficient published comparable observations | Existing pipeline must accumulate eligible history; frontend must keep unavailable states | P1 |
| Share a collection safely | Explicit share permission, public share identifier and field allowlist | Authenticated opt-in share contract; acquisition costs private by default | P2 |
| Cite all source offers and purchase links | Exact-print offer URL, availability/check time and seller identity in a stable public contract | Source offer contract; do not synthesize Offer/AggregateOffer from market reference values | P2 |

Implementation inventory, crawlability findings and validation evidence follow below as the change is completed.

## Copy and information hierarchy inventory

| Surface | Before | After |
| --- | --- | --- |
| Home headline | Find your next card. | Know what your cards are actually worth. |
| Home support | No collector-value explanation | Follow the cards you own, watch the ones you want and see where the One Piece market is moving. |
| Home actions | Search; Browse all cards | Find a card; See card prices; View the market; Track my collection (existing account gate) |
| Home sections | Recent finds; Discover a different selection each day; Explore the Atlas | Recently added cards, explicitly catalogue activity rather than movement; Prices by release |
| Navigation | Cards; inherited Discover vocabulary | Card Prices; Home; Market |
| Cards | THE CARD ATLAS; print taxonomy first | Card Prices; find the exact printing you own or want and compare its prices |
| Exact print | Archived Market Index before current prices | Current Market Value and source evidence first; clearly dated Recorded Market Value below |
| Exact-print freshness | Updated date | Latest price observation in UTC; each source has separate observation, check-time and freshness labels |
| Auxiliary source evidence | API supplies reference prices, but current-price panels omit them | Other source prices, explicitly not used in Market Value; category-independent freshness presentation |
| Print metadata | Atlas entry | About this printing |
| Market | One Piece Market; Performance; Explore a market; Data through | How is the One Piece market doing?; Price movement; Choose a release; Published |
| Release | Generic Cards title and filtered tiles | Authoritative release name, card-price context and a link to its scoped Market; distinct metadata and social image |
| Collection | Collection; Your trove, kept together. | What is your collection worth today?; cards owned, estimated value and what you paid |
| Wishlist | Cards you are still chasing | Not ready to buy yet? Watch the cards you want and keep your target prices in view. |
| Global error | Something went wrong charting that; asserts collection safety | This page couldn’t be loaded; retry or return Home |
| Sign-in | Catalogue/Market Index; Back to Discover | Card prices/Market without an account; Back to Home |

Existing calculation names remain in technical contracts and some historical chart legends. The report and page explanation explicitly connect the new current-price label to the existing exact-print Market Index calculation. No new market metric is computed. Comparison data, constituent rankings and unavailable movement retain server-provided eligibility and null semantics.

## Search and crawlability

- Public data is fetched on the server from the existing public API, with a five-minute cache and six-second timeout. No session, private data or authorization header is forwarded. Exact-print identity/current sources, the first catalogue page, release navigation and Market headline/coverage render into HTML. Client filters, pagination restoration, independent retries and chart controls remain.
- Exact prints have canonical IDs in titles and URLs. Release catalogue and Market URLs retain the existing `release_product_id` query format. Refinements/search/pagination are noindex with a canonical base or release destination; their ordinary links remain followable.
- `robots.txt` retains the wildcard allow policy and all private exclusions. A specific allow for the existing artwork proxy lets crawlers fetch canonical card images without opening other API routes. Public exact prints remain allowed; compatibility/family card routes remain excluded and receive noindex metadata. Private collection/account pages receive noindex metadata too.
- The stable sitemap includes both release destinations from the canonical release list. Exact-print sitemap shards each read at most 100 public catalogue records; robots advertises the shard URLs. Catalogue pagination emits ordinary links, so discovery does not depend on infinite scrolling. No ingestion, recalculation or arbitrary request timestamp is emitted as `lastmod`.
- Metadata is delivered in the initial head for all readers through Next's `htmlLimitedBots` setting. This avoids relying on a maintained list of user agents or JavaScript metadata insertion. Public content and descriptions use semantic headings; exact-print artwork has identity alt text, while linked decorative art retains accessible link names.
- OAI-SearchBot is allowed by the existing wildcard policy. GPTBot receives an explicit rule preserving its exact former wildcard allow/disallow behavior, including the API exclusion; the new artwork-proxy exception does not expand its access. No model-training opt-in decision was changed. OpenAI documents the two settings as independent: [official crawler documentation](https://developers.openai.com/api/docs/bots). No speculative bot tokens were added. Other browsing agents receive the same public HTML and wildcard policy.
- No repository WAF rule was found that singles out search agents. Hosted Vercel protection, firewall rules, third-party image access and actual crawler ingestion cannot be established by local tests. They were not modified or verified against production. The configured `NEXT_PUBLIC_SITE_URL` is authoritative, retaining the existing staging fallback; deployment owners must set their intended public origin when they publish.
- `llms.txt` was not added: there is no concrete use here beyond the canonical, server-rendered pages, plain-language definitions and standard sitemaps. It is not treated as a ranking mechanism.

The rendering implementation follows [Next metadata guidance](https://nextjs.org/docs/app/api-reference/functions/generate-metadata) and [Next image metadata guidance](https://nextjs.org/docs/app/getting-started/metadata-and-og-images). Public metadata does not establish authorization: existing account and API guards remain unchanged.

## Structured data inventory

| Surface | Schema | Truth boundary |
| --- | --- | --- |
| Site | WebSite and Organization | Card Pirate is an independent tool, with configured canonical origin; no invented affiliation, ratings or social accounts |
| Cards and release catalogue | BreadcrumbList | Existing route and exact canonical release ID |
| Exact print | Product and BreadcrumbList | Canonical card code, print ID, canonical card ID, release ID, language/printing description and actual artwork |
| Prices | No Offer or AggregateOffer | Market references combine different evidence types and do not establish a currently purchasable third-party offer; Card Pirate is never represented as seller |
| Private collections | None | No collection, acquisition cost or private share payload is published |

All monetary displays and share values stay in JPY. Since no truthful live Offer is available, no Offer `priceCurrency` field is invented. JSON-LD escapes `<` to prevent canonical text from terminating its script element; tests cover hostile names and distinct physical print identities.

## Freshness dependency

`CurrentPriceFreshness` separates observation, successful check, availability and freshness for any current-price category, including auxiliary/reference values. Its presentation fields are deliberately not additions to an API response type. The current adapter supplies only existing `observed_at` and positive stale evidence. A false legacy stale flag is not proof of freshness under the new contract.

The future public adapter must map category identity, `last_valid_price_observed_at`, `last_successfully_checked_at`, `availability` (`unknown`, `listed`, `no_listing`) and the shared freshness verdict/reason. Source capture lineage and derived contributing-input freshness must come from the shared backend contract, not a client TTL. The existing aggregate 48-hour display warning is retained; it is not the new shared freshness verdict. `calculated_at`, series `as_of`, page retrieval and publication dates never populate successful-check or observation fields. Successful check and observation can legitimately differ when no listing is found or a value is unchanged. No listing and unknown availability must remain distinct.

## Visual review examples

All values in the examples are mock fixtures, not a live price report. The full Zoro image is an unchanged, previously mirrored staging artwork asset; no card pixels were cropped or edited. Screenshot fixtures intentionally exercise partial coverage, old observations, unavailable sources/history and missing supporting panels.

| Page | Before desktop | After desktop | After mobile |
| --- | --- | --- | --- |
| Home | [Before](../ui/evidence/2026-10-01-collector-public/before-home-desktop.png) | [After](../ui/evidence/2026-10-01-collector-public/after-home-desktop.png) | [390px](../ui/evidence/2026-10-01-collector-public/after-home-mobile.png) |
| Exact print | [Before](../ui/evidence/2026-10-01-collector-public/before-card-desktop.png) | [After](../ui/evidence/2026-10-01-collector-public/after-card-desktop.png) | [390px](../ui/evidence/2026-10-01-collector-public/after-card-mobile.png) |
| Market | [Before](../ui/evidence/2026-10-01-collector-public/before-market-desktop.png) | [After](../ui/evidence/2026-10-01-collector-public/after-market-desktop.png) | [390px](../ui/evidence/2026-10-01-collector-public/after-market-mobile.png) |
| Release | [Before](../ui/evidence/2026-10-01-collector-public/before-release-desktop.png) | [After](../ui/evidence/2026-10-01-collector-public/after-release-desktop.png) | [390px](../ui/evidence/2026-10-01-collector-public/after-release-mobile.png) |

| Share type | Before | After |
| --- | --- | --- |
| Exact print | [Shared generic logo card](../ui/evidence/2026-10-01-collector-public/before-social.png) | [Full artwork, exact identity, Market Value and observation](../ui/evidence/2026-10-01-collector-public/after-social-print.png) |
| Market | Same generic logo card | [Movement, partial tracked value and coverage](../ui/evidence/2026-10-01-collector-public/after-social-market.png) |
| Release | Same generic logo card | [Release identity, movement, coverage and representative release artwork](../ui/evidence/2026-10-01-collector-public/after-social-release.png) |
| Home | Same generic logo card | [Collector proposition](../ui/evidence/2026-10-01-collector-public/after-social-home.png) |

Social routes accept only supported kinds and canonical identifiers, never a private collection ID or arbitrary image URL. Artwork is taken from the public canonical response and fetched only from existing approved origins, with redirects disabled, bounded time/size and image decoding limits. WebP/JPEG are decoded losslessly to PNG for the image renderer; no crop, resize or enhancement is applied to the artwork asset. `object-fit: contain` preserves its full canvas and aspect ratio. Sharp was already resolved transitively through Next and is now declared directly at that same version. Missing artwork falls back to text; unavailable movement never becomes zero. Social images are 1200×630 and cached for five minutes, with dates stated as observation or publication context. Release artwork denotes release membership, not market-basket contribution. Collection sharing remains unavailable until an explicit privacy contract exists.


## Validation and release boundary

- `npm run build`: passed, including TypeScript compilation. Built locally against existing mock fixtures, with no production access or deployment.
- Full `npm test -- --maxWorkers=2`: 1,590 passed and four failed across 125 files. The same four failures reproduce on untouched staging (1,583 passed): two pre-existing unavailable-price wording assertions in the family chooser, and two admin navigation assertions. The final auxiliary-price and crawler additions were subsequently checked in a focused run: **90 tests passed across four files**, including canonical/JSON-LD safety, zero versus unavailable movement, source check separation and unchanged GPTBot permissions.
- `npm run lint`: 52 errors and 20 warnings, exactly matching unchanged staging. A comparison by file, severity and rule found no new findings. Existing React effect/state issues are outside this public presentation tranche.
- Browser checks at 1440px and 390px: no horizontal overflow or page exceptions on the four representative pages before or after. Additional 320px checks verify one h1, no overflow, loaded contained artwork, and canonical/title metadata in the initial head. JavaScript-disabled checks read the proposition, exact-print prices, catalogue links, release identity and market coverage directly from HTML.
- All four social types render valid 1200×630 PNGs. Robots, release sitemap and exact-print shard output were fetched locally. JSON-LD on each representative route parses successfully. Invalid release metadata is noindex. No guarantee of search ranking or external social-platform cache refresh is implied.
- [Browser and metadata results](../ui/evidence/2026-10-01-collector-public/browser-summary.json), [320px acceptance checks](../ui/evidence/2026-10-01-collector-public/acceptance-summary.json), [validation summary](../ui/evidence/2026-10-01-collector-public/validation-summary.json).
- `apps/web/vercel.json` sets only `git.deploymentEnabled["feature/collector-public-context"] = false`, preserving all existing exclusions. This exclusion is committed before the first push. GitHub workflow inspection found build/test jobs, not a deployment job. No service configuration, database, worker, source, schedule, collector or pricing methodology changed.
- Feature branch targets staging and remains open for product review. Do not merge or deploy as part of this tranche.
