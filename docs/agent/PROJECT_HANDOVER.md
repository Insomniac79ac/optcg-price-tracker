# Card Pirate: Project Handover

You are taking over development of the Card Pirate project.

This is a MASTER PROJECT HANDOVER, not merely a single-task prompt.

Read this entire document before making changes.

The repository itself and freshly verified live staging state are authoritative.
If any live value in this handover conflicts with CURRENT_STATE.yaml, a newer
handoff, merged repo documentation, or verified staging evidence, use the newer
verified evidence.

Do NOT restart the project from first principles.

==================================================
1. PROJECT
==================================================

Product name:

Card Pirate

Repository:

Insomniac79ac/optcg-price-tracker

Primary purpose:

Card Pirate is a collector-first One Piece Card Game market intelligence and
collection-tracking product focused initially on the Japanese secondary market.

It is NOT primarily a card discovery database.

The target user is already a One Piece player or collector.

They typically want to answer:

1. What are the cards I own worth?
2. How is a card I want to buy moving in price?
3. How is my entire collection performing?
4. How is the overall One Piece card market performing?

The catalogue is infrastructure.

The actual product is market context around cards the user already cares about.

Internal positioning:

Card Pirate helps One Piece collectors understand what their cards are worth,
what the cards they want are doing, and where the wider market is heading.

Current homepage positioning:

Headline:
Know your cards. Know the market.

Supporting copy:
Track card prices, collection value and the One Piece market.

Primary customer paths include:

- card prices
- Market
- collection
- watchlist
- exact card/version pages

Avoid positioning Card Pirate as:

- "discover thousands of cards"
- generic catalogue browsing
- a crypto/trading terminal
- an auto-trading product

==================================================
2. PRODUCT / UX PRINCIPLES
==================================================

Collector-first.

Card artwork should be prominent.

Card lists/grids must preserve complete card artwork:

- no cropping
- preserve physical aspect ratio
- use contain rather than cover

Public language should sound like collector language.

Avoid exposing internal engineering terminology such as:

- CardPrint
- print
- printing

unless technically necessary.

Preferred user-facing language:

- card
- version
- variant
- artwork
- alternate art
- regular art
- other versions

Internal model may continue using CardPrint.

Search is a utility, not the product proposition.

The user usually already knows which card they care about.

==================================================
3. BRAND / VISUAL DIRECTION
==================================================

Card Pirate should feel like a product built specifically for One Piece
collectors.

General frontend direction:

- collector-first
- dark charcoal foundation
- restrained teal / gold accenting where appropriate
- card artwork dominant
- minimal SaaS feel
- not a trading-terminal aesthetic

Social / Open Graph cards should visibly feel related to One Piece rather than
using generic pirate derivatives.

Approved design direction includes:

- canonical One Piece card artwork
- Wanted framing
- manga-panel treatments
- faction/character-specific treatments
- Marine treatment where applicable
- Straw Hat treatment where applicable
- neutral One Piece treatment as fallback

Do NOT substitute generic:

- ropes
- pirate clipart
- random treasure maps
- generic compass art

for actual One Piece visual language.

Card Pirate remains the independent data publisher.

Do not imply affiliation with Bandai, Shueisha or Toei.

==================================================
4. TECH STACK
==================================================

Repository:

Insomniac79ac/optcg-price-tracker

Development environment:

GitHub Codespaces

Frontend:

Next.js / React / TypeScript
Vercel

Backend:

FastAPI
Python
SQLAlchemy / Alembic
Railway

Database:

PostgreSQL

Supporting infrastructure includes:

Redis / worker infrastructure where currently used
Playwright/browser collectors
Railway scheduled services

Primary source collectors:

Yuyu-Tei
SNKRDUNK

==================================================
5. CANONICAL ENVIRONMENTS
==================================================

STAGING IS THE CANONICAL DEVELOPMENT ENVIRONMENT.

Staging frontend:

https://optcg-price-tracker-staging.vercel.app/

Staging API:

https://optcg-price-tracker-staging.up.railway.app

Railway project name:

glistening-peace

Known Railway staging environment ID:

05d1eac2-510d-4bd3-999e-fea9ead766b7

Known Railway project ID used by current tooling:

c613898d-bf03-43a6-8813-761f72e1c00a

Environment status (owner statement, 2026-10-09):

- Railway staging (project glistening-peace, environment
  05d1eac2-510d-4bd3-999e-fea9ead766b7) is THE working environment.
- Vercel has a single environment: the frontend at
  optcg-price-tracker-staging.vercel.app. There is no live Vercel production.
- The Railway production environment is obsolete and will be deprecated
  (owner decision, executed separately).
- The main branch (last updated 2026-07-23) is stale and is not a release
  source.
- A future production, if any, will be provisioned fresh from staging when
  the owner decides.

Production remains RED / human-controlled. See §41.

==================================================
6. AUTHORITATIVE CARD IDENTITY
==================================================

This is one of the most important project invariants.

Authoritative pricing lineage:

CanonicalCard
→ CardPrint
→ SourceCardMapping
→ PriceObservation

Meaning:

CanonicalCard:
rules/card-code level identity

CardPrint:
exact physical card variant/version

SourceCardMapping:
exact source listing/product mapped to one CardPrint

PriceObservation:
source observation linked through the exact mapping

CardPrint.release_product_id is authoritative for release membership.

NEVER infer release from a card-code prefix.

Example:

A card code beginning OP01 does NOT necessarily prove its physical product is
OP-01.

Reprints, alternate artwork and special products make that unsafe.

Legacy card_id relationships may remain for compatibility but are not
authoritative pricing identity.

==================================================
7. EXACT CARD IDENTITY RULES
==================================================

Card identity must preserve physical differences such as:

- base art
- parallel
- alternate artwork
- promotional variants
- reprints
- official asset variants
- release/product membership

Never attach a price to a sibling physical variant merely because:

- card code matches
- character name matches
- artwork looks similar
- market price is similar

Ambiguous identities must NEVER be auto-approved.

Manual/verified exact mappings override fuzzy matching.

Existing identity guards must remain fail-closed.

==================================================
8. SOURCE STRATEGY
==================================================

Primary current sources:

1. Yuyu-Tei
2. SNKRDUNK

Future sources were discussed historically, but do not expand source scope
unless the current roadmap or mission explicitly authorizes it.

The main current engineering objective is:

Every canonical CardPrint should eventually have at least one actively
monitored source where reliable source evidence exists.

Second-source coverage is desirable after first-source coverage.

Track separately:

MAPPED COVERAGE

exact active SourceCardMapping exists

OPERATIONAL COVERAGE

at least one non-paused source has a successful current check

FRESH USABLE PRICE COVERAGE

at least one currently valid eligible regular price exists

Do not conflate these metrics.

==================================================
9. YUYU-TEI PRICE POLICY
==================================================

CRITICAL PRODUCT POLICY.

Yuyu promotional / sale prices are NOT customer-facing prices.

They may be retained internally as source/provenance evidence.

They must NOT:

- appear as the public Yuyu current price
- appear in public Yuyu price history
- contribute to Market Index
- contribute to Market Value

promotion_state=sale may remain stored internally.

NEVER replace a Yuyu sale price with the struck-through former price.

Example historical bug:

page showed:

¥120 struck through
¥80 sale

Incorrect old behavior:

¥80 was public and Market Index eligible.

Correct current behavior:

¥80 retained internally only
public Yuyu price unavailable
Market Index contribution = false
¥120 never substituted

This policy is a HARD invariant.

==================================================
10. RAW SOURCE EVIDENCE
==================================================

Always preserve raw source evidence before parsing/transformation where the
current collector architecture supports it.

Raw snapshots exist so parsing bugs do not destroy provenance.

Do not rewrite history merely because parser logic changes.

Prices are stored in JPY.

Timestamps are UTC.

==================================================
11. MARKET INDEX / MARKET VALUE
==================================================

Card Pirate has:

- source-level prices
- normalized Market Index semantics
- broader Market Value history

Market Value is used for:

- overall One Piece market
- release/set performance
- market history
- movement

Forward Market Value publication is receipt-gated.

A completion receipt proves the intended snapshot completed.

Never fabricate receipts.

==================================================
12. SEP 27–28 2026 MARKET GAP
==================================================

September 27 and September 28, 2026 are intentional historical Market Value
gaps.

Snapshots existed, but valid publication receipts did not.

A later one-off historical repair was attempted, then fully rolled back because
the reconstructed rows were not compatible with the immutable forward
publication chain.

Final decision:

Sep 27 and Sep 28 remain gaps.

Do NOT:

- interpolate them
- create fake receipts
- manufacture Market Value
- rewrite later history

Frontend behavior:

Price Movement chart still displays valid historical Market Value before and
after the gap.

The visual line breaks for missing dates.

7D movement remains unavailable where continuity requirements fail.

Never display unavailable movement as 0%.

==================================================
13. FRESHNESS POLICY
==================================================

Shared current-price freshness policy:

Standard target:

24 hours

Dispatch due:

23 hours

This provides ~1 hour execution headroom.

High-interest policy was designed around:

4 hour target
3 hour dispatch due

Do not silently relax freshness targets because capacity is insufficient.

Capacity shortage must remain visible as deadline misses.

==================================================
14. FRESHNESS SEMANTICS
==================================================

Keep these timestamps/concepts distinct:

- attempt time
- last successful check
- last valid price observation
- historical sale date where applicable
- calculation time
- publication time

NO LISTING:

A confident no-listing result may advance:

last_successfully_checked_at
availability = no_listing

But MUST NOT make an old historical price fresh.

FAILURE:

A transient/parsing/source failure must NOT advance successful-check freshness.

Apply bounded retry/backoff.

Reprocessing or calculation does not make source evidence fresh.

==================================================
15. SHARED DUE-WORK
==================================================

A shared due-work/freshness system has been implemented.

Relevant concepts/tables include:

freshness_work
freshness_price_states
freshness_attempts
source_dispatch_budgets

Due-work is intended to make freshness deadline-driven rather than determined by
legacy fixed rotations.

The system supports:

- claims
- leases
- retries
- source budgets
- category outcomes
- due timestamps
- source/category separation

Do not bypass due-work with manual source runs merely to obtain results.

==================================================
16. YUYU COLLECTOR ARCHITECTURE
==================================================

Yuyu uses 9 Railway shards.

Routing invariant:

mapping_id % 9

Shard count:

9

Current shard architecture must remain unless a mission explicitly changes it.

Shard 4 was historically replaced after a Railway snapshot/build defect.

Current replacement service:

yuyutei-collector-shard-4-v2

Do not resurrect the deleted old shard 4.

The replacement was validated with a successful natural run.

Static outbound networking is in use.

==================================================
17. SNKRDUNK COLLECTOR
==================================================

SNKRDUNK uses bounded collection and singleton protection.

Historically:

BATCH_MAX_MAPPINGS_PER_RUN approximately 70

Do not assume historical settings are still current.

Read CURRENT_STATE / runtime receipts.

Singleton advisory locking must remain.

SNKRDUNK mapping identity requirements are strict.

There has historically been an identity quarantine population, including
artwork/rarity/title mismatches.

Do not bulk-unquarantine.

==================================================
18. PSA10
==================================================

PSA10 support has been designed and partially implemented.

Important semantics:

PSA10 is a distinct category.

It must never be confused with raw floor/current card pricing.

SNKRDUNK architecture was designed so one product capture can eventually yield:

RAW
+
PSA10

without unnecessary duplicate source requests.

PSA10 has intentionally remained OFF during RAW stabilization.

Do not activate PSA10 during the current mission.

==================================================
19. DISCOVERY
==================================================

Discovery exists to find source evidence for cards that currently lack exact
source mappings.

Discovery must:

- persist cursor/checkpoints
- revisit missing/unmapped source identities
- retain candidate evidence
- classify exact/family/unmatched
- feed proposal generation

Discovery NEVER bypasses identity validation.

Ambiguous candidate evidence must not auto-approve.

Current work has also introduced SNKRDUNK published-sitemap discovery.

==================================================
20. FRONTEND / SEARCH / AI DISCOVERABILITY
==================================================

Frontend public pages were repositioned around collector intent.

Homepage:

Know your cards. Know the market.

Supporting copy:

Track card prices, collection value and the One Piece market.

Cards/search:

focused on pricing, not generic discovery.

Market:

shows broader One Piece market performance.

Sets on the Move:

release-level movement, not just release navigation.

AI/search optimization work includes:

- server-rendered public evidence
- canonical exact-card URLs
- sitemap coverage
- semantic headings
- structured metadata
- OAI-SearchBot accessibility
- GPTBot policy kept separate
- structured data where truthful

Do not invent Offer/AggregateOffer semantics when Card Pirate is not the seller.

==================================================
21. SOCIAL / OPEN GRAPH CARDS
==================================================

Dynamic social cards exist for:

- homepage
- exact card
- Market
- release/set

Approved direction:

actual One Piece visual language
full uncropped card art
minimal readable pricing/value context
Card Pirate as independent publisher

Avoid generic SaaS cards.

==================================================
22. COLLECTION / WATCHLIST PRODUCT DIRECTION
==================================================

Long-term user needs include:

Collection:

What is my collection worth today?

Track:

- total collection value
- changes over time
- contributors/movers
- acquisition value where user supplies it

Watchlist:

Users want to monitor cards they are considering buying.

Do not overuse finance language such as "portfolio management" in public copy.

Use collector language.

There have historically been exact-card identity gaps in collection/watch
features.

Do not assume that work is fully complete without checking the current repo.

==================================================
23. ADMIN
==================================================

Admin functionality exists for operational workflows such as:

- source mappings
- refresh runs
- candidate review
- alerts
- card audit

Admin must not be publicly exposed in production.

Staging admin may exist behind authentication.

Do not expose admin tokens to browser code.

==================================================
24. AUTONOMOUS DEVELOPMENT MODEL
==================================================

This project no longer uses prompt-by-prompt staging approvals.

Read:

docs/agent/AUTONOMY_POLICY.md

Authority model:

GREEN

Autonomous.

Examples:

- code
- tests
- fixes
- PRs
- staging deployments
- bounded staging writes
- exact guard-passing mapping approvals
- due-work/discovery operation
- fix-forward debugging

AMBER

Autonomous AFTER:

- impact assessment
- rollback/recovery
- mutation manifest
- verification plan

Examples:

- large mapping approvals
- significant source-volume changes
- migrations
- major schedule/budget changes
- subsystem activation
- service cutovers

RED

Human decision required.

Examples:

- production
- destructive migration
- immutable historical rewrite
- pricing methodology change
- weakening identity validation
- authentication/security policy
- secrets policy
- major brand/product positioning decisions
- meaningful new paid infrastructure
- legal/compliance decisions

==================================================
25. FIX-FORWARD PRINCIPLE
==================================================

An isolated bounded defect is NOT a reason to stop the mission.

Expected behavior:

diagnose
→ regression test
→ fix
→ staging deploy
→ observe
→ continue

Do not return for intermediate approval.

Stop only for:

- RED decision
- wrong CardPrint identity
- DB integrity threat
- uncontrolled duplicate requests
- genuine widespread source blocking
- security issue
- production impact
- invalidated mission assumptions

==================================================
26. AUTONOMOUS DELIVERY
==================================================

Autonomous staging delivery has been fully verified.

Normal path:

PR
→ engineering-gate
→ native GitHub auto-merge
→ serialized staging delivery
→ Vercel/Railway staging verification
→ natural-operation evidence
→ CURRENT_STATE regeneration

Branch:

staging

Production remains manually gated.

Do not manually merge normal autonomous mission PRs.

==================================================
27. MACHINE-READABLE STATE
==================================================

Current project state is generated automatically.

Always read:

docs/agent/CURRENT_STATE.yaml

Regenerate before major external mutation.

State distinguishes:

- verified live
- configured/inferred
- historical
- unknown

Do not substitute old report values as live facts.

==================================================
28. STRUCTURED OPERATIONAL HEALTH
==================================================

Structured RAW health has been implemented.

Health classification:

HEALTHY

normal operation

DEGRADED

bounded issue; fix forward autonomously

BLOCKED

affected path stops because of integrity/source safety issue

Structured health uses existing authoritative evidence rather than a parallel
truth store.

Healthy runs should remain mostly silent.

==================================================
29. IMPORTANT HISTORICAL INCIDENTS / RESOLVED WORK
==================================================

Major historical work that should NOT be restarted casually:

- exact CardPrint architecture established
- authoritative release_product_id model established
- official catalogue expanded to ~4.3k verified variants
- Yuyu sharded into nine collectors
- shard 4 replacement completed
- Market Value receipt-gated publication implemented
- Sep 27–28 historical repair investigated and intentionally rejected
- Yuyu promotion semantics corrected
- shared due-work implemented
- discovery infrastructure implemented
- raw operational health implemented
- autonomous staging delivery implemented
- state generator implemented
- frontend collector-first repositioning completed
- social/OG redesign completed
- Market chart historical-gap rendering fixed
- AI/search metadata work implemented

Do not repeat completed work without evidence it regressed.

==================================================
30. CODESPACES DISK SPACE
==================================================

Codespaces has repeatedly run low on disk space.

Before heavy:

- builds
- browser installs
- Docker builds
- artifact downloads
- large checkouts
- dependency installs

check disk.

Safe cleanup targets include:

- build caches
- package caches
- Playwright caches
- Docker layers/images
- temporary screenshots
- old CI downloads
- stale worktrees
- disposable untracked artifacts

Do NOT delete:

- active worktrees
- unrelated user edits
- handoffs
- rollback evidence
- raw/source evidence
- database data

Aim for ~20% free headroom when practical.

==================================================
31. LIVE STATE: WHERE TO FIND IT
==================================================

This handover holds durable rules only. It deliberately contains no live
numbers (coverage counts, storage GB, latest PR, CI runs).

Live state always comes from, in this order:

1. the newest handoff under docs/agent/handoff/ (and the handoff/<date>
   branches if not yet merged), with its CONTINUATION.json and evidence
2. a freshly regenerated CURRENT_STATE
3. live staging measurement

If a handoff and live measurement disagree, live measurement wins.

==================================================
32. NEVER REPLAY
==================================================

Completed one-off operations must never be re-run:

- SNKRDUNK published-sitemap scheduler intents 3676 and 3677
- RAW recovery 35175
- Yuyu storage canary evidence (lossless encodings and protected rows);
  never overwrite
- completed staging deliveries (do not rerun staging-automerge for an
  already-delivered PR; it redeploys collectors)

Newer handoffs may add to this list. Continue from retained cursors,
checkpoints and evidence.

==================================================
33. SNKRDUNK SITEMAP DISCOVERY
==================================================

PR73 delivered published-sitemap discovery code
(merge 183076f8e1f71b1ed6efec4a81e9146564df123f).

Expansion beyond completed canaries is capacity-guarded: model against
natural RAW recurrence first, never trade RAW freshness for discovery speed.

==================================================
34. STORAGE CAPACITY
==================================================

Storage became the binding constraint in October 2026. Raw page snapshots
dominate database size.

Rules:

- Establish SUSTAINED storage headroom before significantly increasing
  write volume.
- Whole-body dedup was measured as ineffective for recurring captures; the
  planned remedy is the dictionary/compression writer, activated in stages
  with natural verification.
- Writer flags stay OFF until naturally validated.
- Railway volumes cannot be shrunk once enlarged, so a resize fails the
  AMBER rollback requirement and is a human (RED: paid infrastructure)
  decision.
- Never delete immutable/raw evidence to create space.

==================================================
35. YUYU NEW100
==================================================

A prepared Yuyu NEW100 expansion exists. Its current status is in the
newest handoff.

Do not blindly approve it. Approve only when all pass:

- exact CardPrint identity still valid
- no duplicate active Yuyu mapping
- authoritative release_product_id
- safe shard distribution and per-shard capacity
- 23h dispatch / 24h freshness feasibility
- storage headroom
- measured source budget and natural recurrence

If all pass, approval is AMBER and may proceed autonomously.

==================================================
36. CURRENT ACTIVE PRIORITIES
==================================================

Priority 1:

Resolve sustained storage headroom.

Priority 2:

Validate scheduler / admission capacity using natural evidence.

Priority 3:

Complete guarded Yuyu NEW100 if safe.

Priority 4:

Continue SNKRDUNK sitemap discovery from existing checkpoints.

Priority 5:

Complete artwork / exact identity reviews.

Priority 6:

Approve newly exact source mappings within measured capacity.

Priority 7:

Continue operational coverage toward 75%.

==================================================
37. CURRENT CAPACITY PRINCIPLE
==================================================

Do not increase volume merely because configured limits appear large.

Capacity claims require natural-operation evidence.

Coverage growth must not materially worsen freshness.

Continue measuring:

- <=23h
- 23–24h
- >24h
- never checked
- due
- overdue
- backoff
- claims
- source budget utilization

Do NOT relax freshness policy.

==================================================
38. STORAGE MISSION
==================================================

Investigate current storage growth.

Measure:

- DB physical size
- raw snapshot contribution
- observations
- freshness tables
- health/event tables
- indexes
- object storage
- logs/artifacts where relevant

Produce:

current use
daily growth
30-day projection
90-day projection

Prefer safe:

- compression
- deduplication
- archival
- storage representation improvements
- unnecessary duplicate artifact elimination

Do NOT delete immutable/raw evidence merely to create capacity.

==================================================
39. COVERAGE TARGET
==================================================

Target:

3,237 / 4,316 operational variants = 75%

Track separately:

mapped
operational
fresh usable
both sources
zero source

Do not declare success based only on approved mappings.

==================================================
40. PSA10
==================================================

PSA10 remains OFF.

Do NOT activate during the active RAW 75% mission.

At mission end only assess:

PSA10 READY FOR ACTIVATION

or

PSA10 NOT READY

==================================================
41. PRODUCTION
==================================================

PRODUCTION IS RED.

Status (owner statement, 2026-10-09): there is no live production. The Railway
production environment is obsolete and will be deprecated by a separate,
owner-authorized action. The main branch (last updated 2026-07-23) is stale
and is not a release source. A future production, if any, will be provisioned
fresh from staging when the owner decides.

This does not loosen the rule. No agent creates, deploys to, reads or deletes
any production environment, old or new, without explicit owner authorization
for that specific action. Do not delete the main branch, production config
files or production resources as part of any other mission.

Do not:

- deploy
- mutate config
- write production DB
- change aliases
- access production services beyond explicitly authorized read-only metadata
  checks

A prior accidental read-only production metadata inspection is documented.

No production deployment/config/data was changed.

Do not repeat it unnecessarily.

==================================================
42. WORKSPACE SAFETY
==================================================

Preserve unrelated workspace edits.

Several missions have used isolated worktrees.

Before deleting/cleaning worktrees:

verify they are stale and not referenced by a current handoff.

Do not use:

git reset --hard

git clean -fd

or destructive cleanup against unknown user state.

==================================================
43. DEVELOPMENT STYLE
==================================================

The user previously preferred small step-by-step Codex prompts.

That preference has been superseded for autonomous project execution.

CURRENT preference:

MISSION-LEVEL AUTONOMY.

Do not break coherent missions into artificial tiny PRs or human approval
checkpoints.

Keep Git history understandable, but do not create micro-PRs merely for
comfort.

The user should act as product owner, not queue manager.

==================================================
43a. WORKING MODEL
==================================================

The owner is a product owner, not a developer.

Execution runs as autonomous Claude Code sessions in the GitHub Codespace.
A separate Claude chat reviews session reports against the repo and
prepares the next session prompt.

When the next step depends on scheduled natural evidence that has not
arrived, end the session:

1. write HANDOFF.md and CONTINUATION.json under
   docs/agent/handoff/<date>/<name>/ (done, pending, evidence still needed,
   earliest re-check time in UTC and Asia/Kuala_Lumpur, never-replay items)
2. push to a handoff/<date> branch
3. regenerate CURRENT_STATE
4. report, opening with a short plain-English summary for the owner

Do not sleep, poll in a loop, or manually trigger runs to avoid waiting.
Mark every reported number as MEASURED (with source) or CARRIED FORWARD.

==================================================
44. WHEN TO RETURN TO THE USER
==================================================

Do NOT return for:

- bounded bugs
- CI fixture issues
- staging deployment fixes
- ordinary mapping approvals
- routine staging redeploys
- scheduler tuning inside policy
- normal AMBER operations after safeguards pass

Return only for:

- mission success
- genuine verified constraint
- RED product/security/production decision
- integrity/source safety issue that cannot be resolved autonomously

==================================================
45. IMMEDIATE START PROCEDURE
==================================================

When beginning this handover:

1. Read:
   docs/agent/AUTONOMY_POLICY.md
   docs/agent/INVARIANTS.md

2. Locate and read the NEWEST relevant handoff under:
   docs/agent/handoff/

3. Check handoff/<date> branches for handoffs not yet merged to staging.

4. Read its CONTINUATION.json and all referenced evidence.

5. Regenerate CURRENT_STATE.

6. Check Codespaces disk.

7. Verify staging destination.

8. Reconcile any newer work against this handover.

9. Do NOT replay completed intents.

10. Continue the active mission autonomously.

==================================================
46. ACTIVE MISSION SUMMARY
==================================================

Resume:

Card Pirate staging-only RAW capacity / operational coverage mission.

Goal:

resolve storage + scheduler capacity safely,
then move operational coverage toward 3,237 (75%).

Continue:

- Yuyu capacity validation
- NEW100 when safe
- SNKRDUNK sitemap evidence
- exact identity resolution
- source mapping approvals
- natural RAW verification
- storage safeguards
- freshness compliance

Preserve:

- exact CardPrint identity
- Yuyu sale hiding
- Market Value immutability
- source pacing
- autonomous staging delivery
- unrelated edits

Production RED.
PSA10 OFF.

Continue until:

A. 75% operational coverage is safely achieved

or

B. a genuinely verified evidence/capacity/source/integrity constraint prevents
   it.

At completion:

refresh CURRENT_STATE

and provide a concise final mission report covering:

- mapped coverage
- operational coverage
- fresh usable coverage
- dual-source coverage
- zero-source population
- Yuyu capacity/storage
- SNKRDUNK discovery/capacity
- freshness
- storage
- exact remaining constraint if any
- PSA10 readiness
- safety/invariants
- production untouched