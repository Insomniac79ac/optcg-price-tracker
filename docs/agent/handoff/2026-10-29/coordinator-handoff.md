# Coordinator handoff, 2026-10-29 (staging)

From the Claude coordinator session of 2026-10-27 to 2026-10-29 to the next one. Read this,
then [ROADMAP.md](../../ROADMAP.md) (sections 1 and 6), [OPS_RUNBOOKS.md](../../OPS_RUNBOOKS.md),
[IDENTITY_REVIEWS.md](../../IDENTITY_REVIEWS.md) and [AUTONOMY_POLICY.md](../../AUTONOMY_POLICY.md)
before acting. Numbers here are MEASURED at the run ids given and go stale.

Historical context (owner instruction): when the reasoning behind a decision, a rejected option or
an earlier finding is not in the repo, check the previous coordinator chat before asking the owner
or re-deriving it. It is the Claude chat "Card Pirate" coordinator session of 2026-10-27 to
2026-10-29 (https://claude.ai/code/session_014AJNwYXaDit6nqBbKqhy1x). Use the past-chat search
tools if this session has them (search terms such as "frozen membership", "identity proof
binding", "SNKRDUNK not_seen", "every card priced"); otherwise ask the owner to paste the part you
need. The repo stays the source of truth: anything the chat decided that matters is in
ROADMAP.md, DECISIONS.md or a mission file, and the chat never overrides them.

## Owner and standing rules

- Owner: Insomniac (Malaysia, UTC+8, "not a dev"). Terse, plain English, no em-dashes.
- Plan and build are separate steps: no build before the owner approves the plan. Offer
  perfectionist vs pragmatist when it matters. Verify before reporting done. Fix root causes.
- UI asks: click-by-click with exact links. Prompts for other sessions: pasted in full.
- Never print or paste secrets. Staging only (production is RED). PSA10 is off.
- Agents never approve ops-write runs and never remove `hold-for-owner`.
- The coordinator may merge owner-approved PRs that touch neither `.github/**` nor `.claude/**`
  and are not collector releases. `.github` changes get `hold-for-owner`; the owner merges them.
  Collector releases go only through the `staging-automerge` job: open as draft, the owner
  marks it ready.
- Windows (UTC): forward collector rollouts 06:00 to 22:59 only; never merge 19:30 to 20:30
  (the 20:00Z market-index-snapshot run); collector-affecting ops writes blocked 02:00 to 06:00.
- Sources: honest User-Agent, respect robots.txt, stop on 403/429/challenge, never escalate.
- Never use Railway "Deploy Latest Commit" or the Deploy banner on collectors. Tell the owner
  never to click GitHub "Update branch" on a mission PR (it stales the mission digest).

## State at handoff (2026-10-29 07:30Z)

- staging head 9ec8b329 (#239 merged 06:33Z). #239's collector release deployed all ten
  collectors successfully; its delivery verify was still running at handoff. Check run
  40828346968 (`staging-automerge` job) first.
- staging-state 40762982528 (2026-10-28 20:25Z): blockers freshness-deadline-deficit,
  snkrdunk-identity-quarantine, quarantined-refresh-work (355). Yuyu HEALTHY, SNKRDUNK DEGRADED.
- Market Value: fixed (plan A, #235). Published 2026-10-26..28 under
  `card-print-release-coded-v2:cddb7dac...` (183 points, 61 scopes); v1 history intact (64 dates).
  db-diagnostic market-value-membership 40762476093. The owner's screenshots show the 7D view live
  (+0.31%, published Oct 28). 30D and ALL read "Unavailable" by design (`market_value_read._movement`
  needs every day present and every step publishable; the archive has a gap around 2026-09-28 and
  coverage jumps 2026-10-03..06). 30D returns once early October leaves the window (about
  2026-11-05).
- Coverage (yuyu-coverage-gap 40713172523, 2026-10-28): 3569 of 4528 verified prints fresh.
  Gap: 61 EB-05 (not released yet), 483 ambiguous, 327 code listed only in another category,
  34 capture-intent (captured, unreviewed), 54 d_est (all listings mapped to siblings).

## Open work, in order

### 1. Yuyu-Tei identity reviews (owner: "every card priced", perfectionist; task "Phase 2")

#239 made reviews bind to listing identity, not price, and added Claude as a reviewer
(`claude_visual_review_of_unique_full_physical_artwork`, actor `claude:<name>`). Pipeline and
validator rules: [IDENTITY_REVIEWS.md](../../IDENTITY_REVIEWS.md).

Next steps:
1. Confirm the #239 delivery verify passed. If it failed, read the job log first.
2. Fleet pin PR: `docs/agent/STAGING_FLEET.json` `yuyu_reader_component` and `snkr_component` to
   the #239 merge (9ec8b329bdb348860b5f7f6d782fc099a15fae72), precedent `docs/agent/missions/claude-pin-fleet-2adc07f.json`.
   Without it, the next PR's verify compares collectors to an old pin.
3. Review the 14 captures below. Image hosts `card.yuyu-tei.jp` and `www.onepiece-cardgame.com`
   were allowlisted by the owner on 2026-10-29 for new sessions (the old session's proxy refused
   them). Per row: fetch the shop photo `https://card.yuyu-tei.jp/opc/front/{slug}/{pid}.jpg` and
   each official image `https://www.onepiece-cardgame.com/images/cardlist/card/{CODE}.png`
   (`{CODE}_{variant}.png` for p1, p2, ...), once each with an honest User-Agent, no retries;
   sha256 each and require the 12-hex prefix to match; view; pick the one print whose full
   artwork it shows; skip on any doubt or same-art twins.
4. Proof PR: one entry per reviewed row in
   `services/api/app/services/evidence/positive_physical_artwork.json`. Fields the validator
   checks (`physical_artwork_proof.validate`): `capture_scope` =
   `yuyu-identity:{cand}:sha256:{digest}`, `source_candidate_id`, `source_url` =
   `https://yuyu-tei.jp/sell/opc/card/{slug}/{pid}`, `baseline_evidence_digest` = digest,
   `release_product_id` = rp, `language` jp, `review_method`, `actor`, `reviewed_at` (UTC),
   `selected_card_print_id`, `considered_print_ids` (sorted, all siblings),
   `positive_physical_basis`, `excluded_sibling_basis` (every other sibling, keys as strings),
   `work_id`, `source_product_snapshot_id` = psnap, `source_product_content_hash` = phash,
   `source_image_snapshot_id` = isnap, `source_image_url`, `source_body_sha256` (full),
   `official_images` [{card_print_id, raw_snapshot_id, official_asset_variant, body_sha256}].
   The registry is a collector runtime input: the PR is a collector release (all ten, mission
   modelled on `docs/agent/missions/claude-identity-proof-binding.json`), draft, owner marks
   ready. Group many reviews per PR (each release is about 40 min to 2.5 h).
5. After release, the next Yuyu discovery turn per category re-resolves the listings to exact.
   Then `approve-f1-batch` dry run (it now also approves `physical_review` proposals; summary
   `rules`), owner approves, apply.
6. Captures for the rest: `capture-batch-preview` 40718332493 found 164 eligible. Then
   `enqueue-capture-batch` dry run (count up to 100), owner approves. The 90-day storage fit fails
   even with no batch (planning 33.6 MB/day vs 2,470 MB room); the owner's 2026-10-18 decision
   allows one-off captures; flag the owner below 45 days of runway (73 days at handoff).

Review pack (db-diagnostic identity-capture-work, statement `review_pack`, run of 2026-10-29
06:41Z; columns: cand | work | listing | code | rp | digest | psnap | phash | isnap | isha |
official = print:snapshot:variant:prefix):

```
157|3736|op13/10152|OP13-118|182|20dd050fc04d9d731742593e017bc965d79ed950faaf63307fd47da4dd20a40b|64566|8600dfb1307f478f9e1866f279d230718b657f50bce69529dcfe45fee4b96553|64567|1dbb789edfc5|4307:64568:base:b2c627ffcc41 4308:64569:p1:eeece4740cd5 4309:64570:p2:1216da9ca90b 4310:64571:p3:2c54bb54e5cc 4311:64572:p4:28b0007d7b24
160|3737|op13/10156|OP13-119|182|41068c95b52130211e674eb20a31bb2431fe170da8123549e2622902eeec6a03|64574|f5aec5bcdce4897f0141e8f27856bbe4e27088080c3050bd5e6d58ce3cc4c270|64575|d565818b6d00|4312:64576:base:02dcf38a81c4 4313:64577:p1:337738ca73f6 4314:64578:p2:cb1d5a5c0b5f 4315:64579:p3:3615907a31c6 4316:64580:p4:f8e12bb0d0b3
163|3738|op13/10160|OP13-120|182|b24cd575d2d57c84416eadb097212bce6f504e30c28d9f75433752c7746080f3|64582|5bd7a4f38c53edfaa1f62b08654569d57b96443b50ba3e2f2f6c289709e99b0b|64583|d7b8c2fe7233|4317:64584:base:7b282fa611b0 4318:64585:p1:32d77613c0db 4319:64586:p2:0ddbb13c9a64 4320:64587:p3:a3637f5111b8 4321:64588:p4:b4efa8f14afa
194|3754|op13/10098|OP13-080|182|2f511e4a17d493d05e03108b8217ad4eefb14666ed19738626e5a81fc044c3a9|64679|5bef336e4c54e4ff7b3a7872419024f98a5e41b73c9db6b0c41bae86d46e5263|64680|893d4095b275|4253:64681:base:b65f1b70836e 4254:64682:p1:c1fbf331b795 4255:64683:p2:61b3307eba2b
196|3755|op13/10104|OP13-083|182|38934f72ee7f71ae78c4398969e36b464fe9b01350bd72a76d128e370822ab84|64685|0ba604df97193796dbfe32f1849d2482c6d562882c7db421e6d7fe919ab0d686|64686|b8d798262eb5|4259:64687:base:f8f3b2a6abda 4260:64688:p1:e62234ef5845 4261:64689:p2:f315ec67ed41
198|3756|op13/10107|OP13-084|182|aad8e16e071e96c1200c5f358c893a5dfb0504df4c5adc9976b4cd19acba8971|64691|7c4729baa5701eae68c72339f045e294d0c7fca4e965881a4970bd7bc6b4ddc1|64692|03e82330d1d1|4262:64693:base:8f82bc28fa7c 4263:64694:p1:52823397fd00 4264:64695:p2:c32d44523622
200|3757|op13/10114|OP13-089|182|8fdc7e447b701d4bf362630bc556cd2dbf317ed701129d43e0e68f360fde1bbf|64697|03a6e136b9d3a83dc0a0133438fb7e5bd9cf142c5c9772686c50d5314f6726bd|64698|6d4cb88bcbdd|4269:64699:base:0e464f99e2ce 4270:64700:p1:5d5ec29e478b 4271:64701:p2:3c5b8bf4bfe1
202|3758|op13/10118|OP13-091|182|7dadf81c87eaf4e4e385dafd1280850bc3e51cd18c87a9eb3caf8a2465734fad|64703|1e11b8ab2e0b5da2b3f1d167c07a0649cd57699af0e6788cef3a21b8420ed989|64704|a904ccf5443c|4273:64705:base:c1f79693e9fb 4274:64706:p1:9ac8a9beec98 4275:64707:p2:50d01acda373
329|3767|op13/10175|OP09-004|182|798dd5ba9dbbab63a0805e104a6b70fe006df1b97b9bc54937136f29fb9191b0|64772|e15b07f5256093f13d76eb5edfb638b47ce3672273335cf4d38ae8a7761f6d0a|64773|2c262fa9f0f2|4325:64774:p5:e961fef04da8 4326:64775:p6:4f565a5adada
564|3709|op12/10143|OP12-118|181|b08bbde71251b98b31276d00ccd2485662cfcef654cf03452968fceecf42aae5|54140|a41dfd7cca82d5eef72edd087fedce62bb60a58a994b4b6c837ded3edeadfd80|54141|c4d888b9c7ad|4472:54144:base:636f48236139 4473:54145:p1:c9a65b5a2abb 4474:54147:p2:77a7faa6bb7c
716|3735|op12/10154|OP09-093|181|5eeac3b55eb5c97e09093fa1391f25a8e3123e7c3b394b84ea86064e6ad2a8ec|64561|a392319e19ab39124e5dac68961e633e9339b8442da7f977d21e2d4ede973987|64562|5878e618fdb1|4480:64563:p4:f912d5c14858 4481:64564:p5:c0fff5a18282
719|3768|op14/10145|OP14-119|183|5705e1c3e2f3aa53099d6b575d8bfd8a2a21596cf2c8c38fa600dd6df43e1003|64783|3800576b53ef360d1101901dcc5886768c17deb57a952adc545c4b63cd198a2e|64784|1229fece5a80|4144:64785:base:d1b2e4a70d3f 4145:64786:p1:09d4d0c46781 4146:64787:p2:e81df2726dac
2731|3681|op11/10144|OP11-118|180|64f8ac2dfe829da8187e63d1a3b7d3a70de49fb9d07016863b07fe9a8b7db34a|53998|ea786aaaa4b73fe71fa4747044a544dc813a7e0c02bb97ca14278440bfc24198|53999|24e875d80da5|4627:54000:base:ccd0bf54d60b 4628:54001:p1:c4f41bf32fb3 4629:54002:p2:d3386b772474
2884|3708|op11/10155|OP05-119|180|8906e332e80671958ab76e8ac51c0abd97ba9c7bdfbbac80f7e6ff7a7399362d|54129|40656e3d1a90f35b7b6a9f8c8334a319da6e5f240d751e5f45e852543662acc7|54130|0fa1b0df4fb1|4633:54131:p6:b218c05dacea 4634:54133:p7:37ce0a4eb8f3
```

12 of the 14 show a moved proposal digest since capture (price or stock); #239 keeps them bindable.
Re-run the pack before writing proofs: rows leave it once their listing is no longer ambiguous.

### 2. SNKRDUNK price wait (ROADMAP item 24, owner option A then fix)

- Work 196 (mapping 230) still fails: last attempt 2026-10-29 06:00:14Z,
  `no_extraction_attempted:classification=prices_not_loaded;condition_prices...` (freshness-not-met
  run of 2026-10-29 06:2xZ). Six transient failures in 24 h. The size-chips response is never seen
  within 15 s.
- The #237 network trace is in that attempt's `product_result` log line. Railway shows the
  collector's JSON log lines with an EMPTY message (`browser.log_event` prints JSON without a
  `message` key; the fields become hidden attributes), so a text search for `product_result`
  finds nothing. Owner steps: snkrdunk-collector, Deployments, Active, View logs, click the line
  at 06:00:17Z (14:00:17 MYT), Raw Data; or filter `@event:product_result`. #239 redeployed the
  collector, so the old run's logs are under the previous deployment (40e53e7f).
- Next: read the trace, plan the price-wait fix (owner approves), and ship it with: a `message`
  key in `log_event` (readable Railway logs), security L1 `hide_parameters=True` in
  `services/api/app/db.py`. Then canary, the owner-approved "rest" requeue of the 283
  (`snkr-parser-requeue`, windows in `snkr_parser_requeue.WINDOWS`), and a fleet pin.
- Open owner decisions: audit the possibly false SNKRDUNK no-listing facts since 2026-10-26;
  re-enabling no-listing for chip-less products later.

### 3. Smaller open items

- EB-05 (61 prints, Heroines vol.2) goes on sale in Japan 2026-10-31. Discovery adds Yuyu-Tei's new
  category by itself (`due_discovery.persist_enumeration` plans advertised scopes). Check on
  2026-11-01 with db-diagnostic yuyu-coverage-gap-samples (statement `releases`, row EB-05).
- Comparable performance chart stops drawing at its first non-publishable step
  (`market_value_read._series` sets `continuous = False` for good), so the 30D chart is empty
  after 2026-10-01. Offered to the owner as a plan (re-anchor after a break); no decision yet.
- Coverage phases 3 (327 prints listed only in another category: needs a rule and owner examples)
  and 4 (second sources, `plan/new-sources` N1 to N16) not started.
- 58 exact pending Yuyu proposals: their prints are already priced; no coverage gain; ignore.
- Official image mirror: 212 unmirrored; needs the owner's official-images-mirror deploy logs.
- Auto-merge on an already-clean PR is refused by GitHub (#224, #233). Workaround: draft, then
  ready. The ci.yml fix is a `.github` change (owner merge).
- Catalogue Phase 2 batches, then step D (ROADMAP item 25).

## Working notes

- `gh` works over REST only; GraphQL is blocked. Draft and ready, review threads and auto-merge go
  through the `/ccr/` REST routes the error message lists.
- ops-readonly results: `docs/agent/handoff/2026-10-29/ops_result.py` (dispatch, wait, rebuild the
  summary from `ops-summary i/n` annotations, skip the preflight 1/1). Dispatch one run at a time.
  Artifacts cannot be downloaded from the workspace (blob storage blocked).
- db-diagnostic inline budget is 18,000 characters (`scripts/ops/diagnostic.py INLINE_CHARS`);
  statements past it are listed in `rows_omitted`. A new diagnostic FILE needs a choice in
  `ops-readonly.yml` (`.github`, owner merge); a new statement in an existing file does not.
- Mission flow: commit the change, then `python scripts/staging_mission.py digest --base
  origin/staging` (JSON; take `diff_sha256`), write it into the mission, commit, then
  `python scripts/staging_policy.py --base origin/staging --head HEAD`. Missions never set the fleet
  `revision`. `.github` paths floor the class to AMBER.
- A change to `services/api/app/services/*` that a collector imports is a collector runtime input
  for EVERY collector that imports it (the component verify checks the import graph): release
  those collectors too, even if their behaviour is unchanged.
- The staging API and website are not reachable from the workspace shell or WebFetch. Use the
  owner's built-in browser (desktop app, chat linked to the computer) or screenshots.
- Local tests: API Postgres suites need the local cluster; run start, schema reset and pytest in one
  `setsid -w` script (the cluster dies between tool calls otherwise). CI `backend-tests` is the
  authoritative full suite (about 18 min).
- Never `pkill -f` with a pattern your own shell matches.
