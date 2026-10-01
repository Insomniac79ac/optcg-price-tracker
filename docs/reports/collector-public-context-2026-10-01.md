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

Current exact-print value is the existing `market_index.index_value_jpy`, presented as Market Value without changing its calculation. Market tracked value and coverage-neutral movement remain the existing, separate `market-value` contract. Neither is a guaranteed buying or selling price or a live marketplace offer. An archive/publication date never becomes a source observation or successful-check time.

## Missing information and backend follow-up

| User need | Missing field or data | Likely backend dependency | Priority |
| --- | --- | --- | --- |
| Know the age of the last valid price by source/category | `last_valid_price_observed_at` for every source/category, including auxiliary prices | Expose the shared observation contract on public exact-print/current-price APIs; existing observation fields are not a complete shared contract | P0 |
| Know when each source/category was successfully checked | `last_successfully_checked_at`, separately from observation/capture/publication time | Expose the shared successful-check contract; freshness adapters alone do not establish a public contract | P0 |
| Distinguish no listing from unknown availability | Shared `availability` with explicit `no_listing`, `listed` and `unknown` states | Public exact-print/current-price availability by source/category | P0 |
| Understand the freshness decision | Shared freshness verdict and reason, including unknown reasons | Expose the backend verdict/reason; do not infer it from a false stale flag or frontend TTL | P0 |
| Understand age of overall/release market inputs | Freshness and coverage of inputs contributing to overall/release Market Value; source freshness distribution, oldest contributing observation and successful-check coverage | Public market-value summary derived from source freshness contract; `as_of` remains publication context | P0 |
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
| Home support | No collector-value explanation | See what your cards are worth, compare prices for the ones you want and see where the One Piece market is moving. |
| Home actions | Search; Browse all cards | See prices; See card prices; View the market; My collection (existing account gate). Search guidance: name/code → choose exact printing → price context |
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
- Exact prints retain canonical IDs in URLs, descriptions, social-image identity and JSON-LD; titles use brief card/artwork labels. Release catalogue and Market URLs retain the existing `release_product_id` query format. Refinements/search/pagination are noindex with a canonical base or release destination; their ordinary links remain followable.
- `robots.txt` retains the wildcard allow policy and all private exclusions. A specific allow for the existing artwork proxy lets crawlers fetch canonical card images without opening other API routes. Public exact prints remain allowed; compatibility/family card routes remain excluded and receive noindex metadata. Private collection/account pages receive noindex metadata too.
- The stable sitemap includes both release destinations from the canonical release list. Exact-print sitemap shards each read at most 100 public catalogue records; robots advertises the shard URLs. Catalogue pagination emits ordinary links, so discovery does not depend on infinite scrolling. No ingestion, recalculation or arbitrary request timestamp is emitted as `lastmod`.
- Metadata is delivered in the initial head for Next’s built-in HTML-limited agents plus documented OAI-SearchBot and ChatGPT-User agents. Ordinary browser requests retain metadata streaming; see the refinement decision below. Public content and descriptions use semantic headings; exact-print artwork has identity alt text, while linked decorative art retains accessible link names.
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


## PR #33 focused refinement (2026-10-01)

This section supersedes the initial screenshots and validation counts where the focused refinement changes copy or metadata. Backend, collectors, APIs, pricing methodology and deployment remain outside this pass.

### Copy and value meaning

- Homepage submit is **See prices**. Placeholder examples remain; nearby guidance explains entering a name/code and choosing the exact printing for price context. The existing search destination remains `/cards?q=…` rather than guessing a physical printing.
- Homepage, brand metadata and home social copy now describe seeing values and comparing cards owned or wanted. “Follow the cards you own” and related tracking claims are removed. The collection link is **My collection**; it retains the existing destination and account gate.
- Exact-print copy: “Card Pirate Market Value estimates this exact printing’s worth from tracked Japanese market data. Actual buying and selling prices may differ.” Source asking prices, buy quotes and completed sales stay separate below; auxiliary references still explicitly do not contribute to Market Value.
- Exact-print social images label the figure **Market Value estimate**, with contributing-source count and observation context. The page's current/archive hierarchy and source calculations are unchanged.

### Exact-print title audit

| Case | Previous title | Refined title |
| --- | --- | --- |
| Zoro base, no sibling disambiguation needed | Roronoa Zoro OP01-001 Price · OP-01 — Romance Dawn · Original artwork · JP · Print 1 — Card Pirate | Roronoa Zoro OP01-001 Price — Card Pirate |
| Zoro base with alternate siblings | Same full identity title | Roronoa Zoro OP01-001 Original Art Price — Card Pirate |
| Zoro single alternate artwork | Roronoa Zoro OP01-001 Price · OP-01 — Romance Dawn · Alternate artwork · JP · Print 2 — Card Pirate | Roronoa Zoro OP01-001 Alt Art Price — Card Pirate |
| Multiple alternate artworks | Same generic artwork label plus print ID | Roronoa Zoro OP01-001 Art 2 Price — Card Pirate / Roronoa Zoro OP01-001 Art 3 Price — Card Pirate |
| Reprint in PRB-01 / PRB-02 | Full release, reprint, language and print ID in each title | Roronoa Zoro OP01-001 Reprint Price — Card Pirate |
| Franky anniversary printing (uncoded product) | Franky ST01-010 Price · Premium Card Collection — 25th Anniversary Edition · Alternate artwork · JP · Print 6823 — Card Pirate | Franky ST01-010 Alt Art Price — Card Pirate |

Mock cases cover duplicate card codes, original/alternate artwork, two alternate art ordinals, reprints from different releases, an unknown variant, a special print, and the existing Franky original/uncoded anniversary identity shape. Only authoritative asset variants and published special-print labels supply descriptors. Missing/unknown variants never become “Original Art.” The existing art ordinal is used only when sibling alternate-art labels collide. No extra API request or legacy-card lookup is introduced.

Short titles are not identity keys and need not be globally unique: two reprints sharing the same known descriptor deliberately share a short title. Their release, language and stable print ID remain distinct in descriptions, the visible printing information, social image and Product JSON-LD; each retains its own canonical URL and SKU. We do not infer a treatment, invent a reprint ordinal, or merge prices to force title uniqueness. Full physical details remain available to search and readers.

### htmlLimitedBots decision in Next.js 16.2.10

Verified against installed `next/dist/server/lib/streaming-metadata.js`, `next/dist/shared/lib/router/utils/html-bots.js` and the [Next htmlLimitedBots documentation](https://nextjs.org/docs/app/api-reference/config/next-config-js/htmlLimitedBots). For requests with a nonempty User-Agent, Next tests the configured regex and returns `serveStreamingMetadata = false` on a match. Thus `/.*/` blocks metadata for ordinary desktop/mobile visitors too, not just crawlers. Missing/empty User-Agent is an implementation exception: this predicate still allows streaming. Static metadata resolved at build time is unaffected.

Blocking awaits dynamic metadata before sending the initial render so metadata can be in the head. This can increase TTFB and delay visible content on routes where metadata awaits public API reads (currently up to the existing six-second timeout). Our page data can independently delay rendering too; this change is not a claim of a measured production speedup. See [Next's streaming metadata explanation](https://nextjs.org/docs/app/api-reference/functions/generate-metadata#streaming-metadata).

Decision: replace the wildcard with the complete default regex exported by the pinned Next version, extended only with **OAI-SearchBot** and **ChatGPT-User**, both listed in the [official OpenAI crawler documentation](https://developers.openai.com/api/docs/bots). Search and user-initiated browsing metadata stays head-readable, as do Next's existing social/search defaults. Normal browsers and Google's JavaScript-capable main Googlebot retain streaming. An override replaces defaults rather than adding to them, so an AI-only regex would regress social previews. Importing the default prevents a copied list from drifting; the small internal-import dependency is covered by tests of the installed framework and should be reviewed on Next upgrades.

This is rendering policy, not crawler authorization. OAI-SearchBot remains accessible under the existing wildcard robots policy; GPTBot's separate training-access rules are untouched. No speculative agent names or llms.txt were introduced. Server-rendered public evidence, semantic headings, sitemap discovery, exact-print canonicals and truthful structured data remain. No Offer/AggregateOffer schema was added.

### Remaining product/data dependencies

All five requested freshness/coverage items are explicitly P0 in the retained inventory above. Exact-print ownership/watch membership and reliable collection history remain P1. We added no backend placeholder, invented check time, availability state, or freshness value. Unknown source checks/availability stay unknown. Local validation cannot establish hosted firewall behavior or actual crawler ingestion.


### Refinement validation and evidence

- **Production build:** `npm run build` passed on Next.js **16.2.10**, including TypeScript. The local build used mock API/canonical origins, not hosted environments. [Build output](../ui/evidence/2026-10-01-collector-refinement/build.txt).
- **Targeted tests:** **274 passed across 11 files**: Home, exact-print page and analytics, Cards, Market, public SEO/title/identity/social content, installed-framework metadata bot behavior, robots, metadata images, brand, and current-price freshness. [Test output](../ui/evidence/2026-10-01-collector-refinement/targeted-tests.txt). An existing exact-print analytics fixture omitted the required `auxiliary_values` array; the fixture now supplies an empty array. Visible identity assertions include the newly displayed Print ID. No runtime fallback was introduced.
- **Changed-file ESLint:** passed without findings. `git diff --check` passed. The earlier full-suite/lint baseline above is historical; this focused pass did not rerun or fix unrelated baseline failures.
- **Production-server metadata/canonicals:** **60 checks** (eight representative print cases × seven browser/crawler agents, plus Cards/Market and release destinations). All crawler cases expose title/canonical/description in the initial head; title, Open Graph and Twitter text agree. Distinct print URLs, SKUs, release descriptions and visible IDs remain; no Offer/seller assertion is emitted. The print sitemap contains all eight mock identities. [Detailed results](../ui/evidence/2026-10-01-collector-refinement/checks.json), [sitemap](../ui/evidence/2026-10-01-collector-refinement/prints-sitemap.xml).
- **Browser:** Home and exact print at **1440, 390 and 320px**, one h1, no horizontal overflow, artwork loaded/contained, and no uncaught page errors. The search button reaches `/cards?q=OP01-001` with exact-print links at every width. No-JavaScript Franky identity and Market Value explanation remain readable. Browser account state is a mock signed-out session; no private behavior was changed or validated.
- **Social cards:** Home, exact-print Zoro, long-identity Franky anniversary, overall Market and release, all **1200×630**. Checked full contained art, estimate/source count, unchanged observation/check distinction, partial market coverage and legible identity. Images and prices in this new evidence are entirely local mock fixtures, including a clearly marked neutral card image; they are not source artwork or current market reports.
- **Scope:** no backend/API/collector/pricing/deployment changes. Existing Vercel branch deployment suppression is untouched. PR #33 remains for product review; do not merge.

| Surface | Desktop | Mobile | Narrow mobile |
| --- | --- | --- | --- |
| Home | [1440px](../ui/evidence/2026-10-01-collector-refinement/home-1440.png) | [390px](../ui/evidence/2026-10-01-collector-refinement/home-390.png) | [320px](../ui/evidence/2026-10-01-collector-refinement/home-320.png) |
| Exact print | [1440px](../ui/evidence/2026-10-01-collector-refinement/print-1440.png) | [390px](../ui/evidence/2026-10-01-collector-refinement/print-390.png) | [320px](../ui/evidence/2026-10-01-collector-refinement/print-320.png) |

Social examples: [Home](../ui/evidence/2026-10-01-collector-refinement/social-home-site.png), [Zoro](../ui/evidence/2026-10-01-collector-refinement/social-print-1.png), [Franky anniversary](../ui/evidence/2026-10-01-collector-refinement/social-print-6823.png), [Market](../ui/evidence/2026-10-01-collector-refinement/social-market-overall.png), [release](../ui/evidence/2026-10-01-collector-refinement/social-release-181.png).
