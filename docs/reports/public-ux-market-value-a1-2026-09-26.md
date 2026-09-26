# Public UX Market Value A1 — publication and monetary basket contract

**Decision:** One basket unit is one physical `CardPrint`. Current tracked value is its literal eligible JPY sum; historical price movement is a separate, monetary-weighted chain over comparable prints. Release values always disclose priced/physical coverage. The old PR #18 Market is reference material, remains open and unmerged, and is not the implementation target.

**Audit boundary and timing.** Repository and staging reads only. Staging was queried with `BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY`, `transaction_read_only = on` was verified in each connection, and each transaction was rolled back and closed. Alembic was `c4e9a2b7816d`. The live calculation below was at **2026-09-26 16:30:16 UTC** (Market Index 3 / source semantics 2); the two latest complete archive dates were **2026-09-24 and 25**. All counts are active, verified, Japanese physical prints. There was no database write, source request, collector, replay, migration, configuration change, or PR change.

## Complete active coded release census

`Priced/physical` is the coverage count; `%` is that fraction. `Snapshots` counts current active physical prints with at least one archived row, including a null-price row. `Comparable` counts current live priced prints that pass the existing strict per-print comparability guard against the 2026-09-25 archived price: positive prior value, equal index/source-semantic versions, and identical nonempty contributing `(source, reference_type)` sets. This is an **adjacent-calendar-day capability check**, not a published daily point. `First/last` are the first and last *usable non-null* archived values. English names are the existing official Asia-English presentation map; release identity remains the numeric `ReleaseProduct.id`.

| ID | Code | English name | Physical | Priced | JPY sum | Coverage count | Coverage % | Snapshots | Comparable | First usable | Last usable |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 170 | EB-01 | Memorial Collection | 80 | 36 | ¥2,020 | 36/80 | 45.0% | 36 | 36 | 2026-09-01 | 2026-09-25 |
| 171 | EB-02 | Anime 25th collection | 105 | 43 | ¥2,600 | 43/105 | 41.0% | 43 | 43 | 2026-09-13 | 2026-09-25 |
| 172 | EB-03 | ONE PIECE Heroines Edition | 90 | 42 | ¥2,560 | 42/90 | 46.7% | 42 | 42 | 2026-09-13 | 2026-09-25 |
| 173 | EB-04 | EGGHEAD CRISIS | 85 | 39 | ¥3,200 | 39/85 | 45.9% | 39 | 39 | 2026-09-13 | 2026-09-25 |
| 1 | OP-01 | Romance Dawn | 154 | 81 | ¥48,300 | 81/154 | 52.6% | 81 | 81 | 2026-08-21 | 2026-09-25 |
| 2 | OP-02 | Paramount War | 154 | 66 | ¥4,340 | 66/154 | 42.9% | 67 | 66 | 2026-08-21 | 2026-09-25 |
| 3 | OP-03 | Pillars of Strength | 154 | 79 | ¥18,930 | 79/154 | 51.3% | 79 | 79 | 2026-08-21 | 2026-09-25 |
| 4 | OP-04 | Kingdoms of Intrigue | 149 | 60 | ¥126,330 | 60/149 | 40.3% | 60 | 60 | 2026-08-21 | 2026-09-25 |
| 174 | OP-05 | Awakening of the New Era | 154 | 4 | ¥480 | 4/154 | 2.6% | 4 | 4 | 2026-09-24 | 2026-09-25 |
| 175 | OP-06 | Wings of Captain | 150 | 5 | ¥730 | 5/150 | 3.3% | 5 | 5 | 2026-09-24 | 2026-09-25 |
| 176 | OP-07 | 500 Years in the Future | 150 | 4 | ¥400 | 4/150 | 2.7% | 4 | 4 | 2026-09-24 | 2026-09-25 |
| 177 | OP-08 | Two Legends | 150 | 1 | ¥80 | 1/150 | 0.7% | 1 | 1 | 2026-09-24 | 2026-09-25 |
| 178 | OP-09 | Emperors in the New World | 158 | 0 | ¥0 | 0/158 | 0.0% | 0 | 0 | — | — |
| 179 | OP-10 | Royal Blood | 150 | 16 | ¥1,400 | 16/150 | 10.7% | 16 | 16 | 2026-09-04 | 2026-09-25 |
| 180 | OP-11 | A Fist of Divine Speed | 155 | 0 | ¥0 | 0/155 | 0.0% | 0 | 0 | — | — |
| 181 | OP-12 | Legacy of the Master | 154 | 16 | ¥1,570 | 16/154 | 10.4% | 16 | 16 | 2026-09-04 | 2026-09-25 |
| 182 | OP-13 | Carrying on His Will | 174 | 81 | ¥5,580 | 81/174 | 46.6% | 81 | 81 | 2026-09-01 | 2026-09-25 |
| 183 | OP-14 | The Azure Sea’s Seven | 156 | 16 | ¥1,400 | 16/156 | 10.3% | 16 | 16 | 2026-09-04 | 2026-09-25 |
| 184 | OP-15 | Adventure on KAMI’s Island | 152 | 0 | ¥0 | 0/152 | 0.0% | 0 | 0 | — | — |
| 185 | OP-16 | THE TIME OF BATTLE | 153 | 16 | ¥1,440 | 16/153 | 10.5% | 16 | 16 | 2026-09-04 | 2026-09-25 |
| 186 | OP-17 | The World's Strongest Warriors | 169 | 20 | ¥14,780 | 20/169 | 11.8% | 20 | 20 | 2026-09-04 | 2026-09-25 |
| 187 | PRB-01 | ONE PIECE CARD THE BEST | 319 | 0 | ¥0 | 0/319 | 0.0% | 0 | 0 | — | — |
| 188 | PRB-02 | ONE PIECE CARD THE BEST vol.2 | 316 | 0 | ¥0 | 0/316 | 0.0% | 0 | 0 | — | — |
| 189 | ST-01 | Straw Hat Crew | 17 | 4 | ¥400 | 4/17 | 23.5% | 4 | 4 | 2026-09-24 | 2026-09-25 |
| 190 | ST-02 | Worst Generation | 17 | 0 | ¥0 | 0/17 | 0.0% | 0 | 0 | — | — |
| 191 | ST-03 | The Seven Warlords of the Sea | 17 | 0 | ¥0 | 0/17 | 0.0% | 0 | 0 | — | — |
| 192 | ST-04 | Animal Kingdom Pirates | 17 | 1 | ¥3,300 | 1/17 | 5.9% | 2 | 1 | 2026-08-31 | 2026-09-25 |
| 193 | ST-05 | ONE PIECE FILM edition | 17 | 0 | ¥0 | 0/17 | 0.0% | 0 | 0 | — | — |
| 194 | ST-06 | The Navy | 17 | 0 | ¥0 | 0/17 | 0.0% | 0 | 0 | — | — |
| 195 | ST-07 | Big Mom Pirates | 17 | 0 | ¥0 | 0/17 | 0.0% | 0 | 0 | — | — |
| 196 | ST-08 | Side Monkey.D.Luffy | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 197 | ST-09 | Side Yamato | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 198 | ST-10 | The Three Captains | 19 | 0 | ¥0 | 0/19 | 0.0% | 0 | 0 | — | — |
| 199 | ST-11 | Side Uta | 15 | 2 | ¥340 | 2/15 | 13.3% | 2 | 2 | 2026-09-22 | 2026-09-25 |
| 200 | ST-12 | Zoro & Sanji | 17 | 0 | ¥0 | 0/17 | 0.0% | 0 | 0 | — | — |
| 201 | ST-13 | The Three Brothers Bond | 35 | 0 | ¥0 | 0/35 | 0.0% | 0 | 0 | — | — |
| 202 | ST-14 | 3D2Y | 17 | 0 | ¥0 | 0/17 | 0.0% | 0 | 0 | — | — |
| 203 | ST-15 | Red Edward.Newgate | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 204 | ST-16 | Green Uta | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 205 | ST-17 | Blue Donquixote Doflamingo | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 206 | ST-18 | Purple Monkey.D.Luffy | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 207 | ST-19 | Black Smoker | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 208 | ST-20 | Yellow Charlotte Katakuri | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 209 | ST-21 | GEAR5 | 32 | 0 | ¥0 | 0/32 | 0.0% | 0 | 0 | — | — |
| 210 | ST-22 | Ace & Newgate | 31 | 0 | ¥0 | 0/31 | 0.0% | 0 | 0 | — | — |
| 211 | ST-23 | Red Shanks | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 212 | ST-24 | Green Jewelry Bonney | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 213 | ST-25 | Blue Buggy | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 214 | ST-26 | Purple/Black Monkey.D.Luffy | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 215 | ST-27 | Black Marshall.D.Teach | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 216 | ST-28 | Green/Yellow Yamato | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 217 | ST-29 | EGGHEAD | 31 | 0 | ¥0 | 0/31 | 0.0% | 0 | 0 | — | — |
| 218 | ST-30 | Luffy & Ace | 34 | 0 | ¥0 | 0/34 | 0.0% | 0 | 0 | — | — |
| 219 | ST-31 | Red Monkey.D.Luffy | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 220 | ST-32 | Green Roronoa Zoro | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 221 | ST-33 | Blue Kuzan | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 222 | ST-34 | Purple Charlotte Katakuri | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 223 | ST-35 | Red/Black Sabo | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |
| 224 | ST-36 | Yellow Eustass"Captain"Kid | 15 | 0 | ¥0 | 0/15 | 0.0% | 0 | 0 | — | — |

The 59 coded Bandai JP products all contain active verified prints; **21** currently have a usable price. A `¥0` in this **audit table** is the arithmetic sum of an empty priced set, **not a publishable zero-valued release**; the proposed API/UI returns null/— for those rows. The other six of the 65 products are uncoded and are outside this requested table, but must remain addressable by release ID in the future API. Overall across coded releases: **632 priced / 4,281 physical**, ¥240,180; Overall including uncoded products is **639 / 4,316**, ¥262,279. These are one-copy *tracked* sums, not an estimate of every print's value or market capitalization.

### Descriptive coverage distribution

These are audit bins, not publication rules: very sparse `<5%`: **42** releases; sparse `5–<20%`: **7**; moderate `20–<40%`: **1**; strong `40–<70%`: **9**; near-complete `≥70%`: **0**. The nine strong releases are EB-01/02/03/04 and OP-01/02/03/04/13. Most releases have not entered a representative priced cohort. A count gate alone is unsafe: OP-17's **20 / 169 = 11.8%** would qualify at 20 prints, although one print currently holds **86.6%** of its tracked JPY value. Conversely, OP-01 and OP-04 have 50.5% and 49.9% of their tracked value in one print; this is real monetary-basket concentration, to disclose and scrutinize, not silently equalize.

## Publication gates and terminology

**Current value.** If no print has a usable price, return `value_jpy: null` / `no_prices`; never show “¥0”. With any nonzero coverage, the literal sum may appear in the release table or methodology detail as **“Value of N priced printings”** alongside `N / total` and the `as_of` time. A **prominent selected-release figure** requires, for products with at least 30 physical prints, **at least 30 priced prints and ≥40% physical coverage**. For smaller products with **10–29** physical prints, it requires at least `max(10, ceil(0.80 × physical_prints))` priced prints and **≥80%** coverage; products with fewer than 10 physical prints have only the explicitly partial/detail value in v1. Even when prominent, label it **“Current tracked release value”**, with coverage immediately visible. Below that gate, show **“Price coverage in progress”** instead of a prominent yen figure; an explicitly partial sum may remain in the table. OP-05's 4/154 and OP-17's 20/169 cannot be presented as what the whole release is worth.

Never use unqualified **“Market value”** for a one-copy sum while prints remain unpriced. Even at 100% catalogue coverage, a one-copy inventory sum is not real market capitalization, transaction volume, or a portfolio valuation. Use **“Tracked market value”** or **“One-copy tracked value”** permanently, and expose count, fraction, price basis, and time. The publication fraction governs prominence/price-trend publication, not a claim that missing prints have zero value.

**Release movement, v1:** for **every adjacent UTC-day step** used by a displayed window, apply a size-aware two-part gate. For a release with `N ≥ 30` active verified physical prints, require **at least 30 strictly comparable prints and ≥40% of N** at both endpoints. For `10 ≤ N < 30`, require **at least `max(10, ceil(0.80 × N))` comparable prints and ≥80% of N** at both endpoints. `N < 10` has no release movement in v1; those prints can retain individual histories. In every case, comparable prints must account for **≥80% of the already priced JPY sum** at both endpoints. This last guard prevents a panel of cheap stable prints from representing a basket whose valuable print just entered, left, or changed source. The primary two-part gate is count plus physical breadth; value share is a monetary-basket integrity guard. Require exact daily snapshots spanning the full requested 7D/30D UTC window, positive denominator, no hidden version/membership break, and every step to pass. A quiet valid step is `0%`; failed or missing steps are `null` with a reason, never 0%.

Thirty is a useful minimum for larger products, but **cannot be universal**: many complete starter decks contain only 15–19 physical prints. A fully priced small product should eventually become eligible; the ≥80% small-product rule demands near-complete coverage before trusting its narrower panel. CPI's equal-weight rationale does **not** transfer directly to a monetary basket: a single expensive print can still dominate a 30-print return. The large-product 40% rule keeps `30 / 170 = 17.6%` from passing, and 80% comparable-value share bounds drift within the *priced* basket. The audit cannot establish random sampling of the unpriced prints; none of these gates licenses a full-release price claim. Persist and expose the largest-print share and source/contributor coverage for quality review, without clipping a genuine expensive-card change.

### Candidate threshold check on actual staging

The `Current adjacent` column tests the **2026-09-25 archive → 2026-09-26 live** capability; `7D` tests every completed daily step 2026-09-18 → 25; `30D` tests 2026-08-26 → 2026-09-25. For 7D/30D the table also requires the ≥80% comparable-value-share guard. A policy's count and relative fraction must hold **on each step**, not only at its last endpoint. This historical audit uses today's corrected catalogue denominator for prior dates because the archive does not freeze past release/status membership; the production contract below requires a persisted membership basis before publication.

| Candidate | Current adjacent qualifiers | Full 7D | Full 30D | Assessment |
| --- | --- | ---: | ---: | --- |
| A: ≥20 | Nine strong releases **plus OP-17** (10) | 9 | 0 | Incorrectly admits OP-17's sparse **current day** (11.8% of physical prints); its earlier 7D steps still fail. |
| B: ≥30 | Nine strong releases (9) | 9 | 0 | Works on today's distribution, but future 30/170 would qualify at 17.6%. |
| C: ≥30 and ≥25% | Nine strong releases (9) | 9 | 0 | More defensible than count alone; could still leave 75% of a product unpriced. |
| D: ≥30 and ≥40% | EB-01/02/03/04; OP-01/02/03/04/13 (9) | 9 | 0 | Good for larger products, but makes a fully priced 15-print starter deck permanently ineligible. |
| E: ≥30 and ≥50% | OP-01, OP-03 (2) | 2 | 0 | Excludes seven otherwise broad, stable tracked baskets. |
| **F: size-aware ≥30/40% for N≥30; ≥max(10, ceil(80% of N))/80% for 10≤N<30** | **EB-01/02/03/04; OP-01/02/03/04/13 (9)** | **9** | **0** | **Recommended:** retains D's protection for large releases and gives small, nearly complete products a truthful path. |

Today's cohort does not empirically distinguish B/C/D/F—the same nine pass. **F** is a product safety rule chosen for the actual variation in product size, not because the current nine happen to pass. Its fractions are *versioned methodology constants*: changing them later requires a new version and publication review, not silent retroactive recomputation. Under F, the nine release cohorts have 7D minimum comparable counts **36–80**, minimum physical breadth **40.3–51.9%**, and minimum two-sided comparable-value share **97.4%**. The remaining **50** coded releases are unavailable under F: OP-05–12, OP-14–17, PRB-01/02, and ST-01–36. No release has a publishable 30D: early archive role evidence and the 2026-09-02→03 index/source version boundary prevent continuous, proven returns. Do not calculate a 30D release number from only the surviving tail.

**Overall uses a separate tracked-basket gate:** ≥300 comparable prints, ≥10% of active verified Japanese physical prints, and ≥80% of priced JPY value represented at both endpoints, for every step in the window. Thirty prints would be under 1% of this catalogue; a materially larger panel is warranted, although even 10% does not establish representative sampling. The label is **“Price movement of tracked printings”** rather than movement of the entire One Piece market. The latest full 7D has **616–630** comparable prints (14.3–14.6% of 4,316) and minimum two-sided value share **94.5%**, so 7D movement qualifies; the full 30D does not. The current **639/4,316 (14.8%)** supports a substantial tracked-panel movement measurement, but **does not** justify “Total One Piece Market Value” for the ¥262,279 headline. Display “Current tracked value — 639 of 4,316 printings priced” with time and an easy path to methodology.

## Exact monetary basket estimator

For scope `s` (`overall` or one `release_product_id`) and UTC day `d`, define `U(s,d)` as active verified Japanese physical prints assigned to that scope in the **recorded membership revision** for `d`. Assignment is always `CardPrint.release_product_id`: for example, the `EB04-007` `p2` print physically issued in OP-17 belongs to OP-17 despite its card-code prefix. Define `E(s,d) ⊆ U(s,d)` as those with a non-null, positive archived Atlas Market Index JPY value `v(i,d)` from that day's immutable snapshot. A source with no usable value supplies no inferred price. The literal daily tracked sum is

`S(s,d) = Σ[i ∈ E(s,d)] v(i,d)`; `N(s,d) = |U(s,d)|`; `priced(s,d) = |E(s,d)|`.

For adjacent archived days `p = d − 1 UTC day` and `d`, let `C(s,p,d)` be prints in **both** eligible sets whose release assignment is unchanged for that scope, whose `(index_version, source_semantics_version)` matches, and whose nonempty contributing `(source, reference_type)` set matches exactly. Reuse the existing strict per-print `comparability_refusal` rule; a missing provenance role fails closed. Define

`P = Σ[i ∈ C] v(i,p)`, `Q = Σ[i ∈ C] v(i,d)`, `R = Q / P`, `r = R − 1`.

Publish `r` only when `P > 0`, the appropriate count/physical-breadth gate passes at **both** dates, `P / S(s,p) ≥ 0.80`, `Q / S(s,d) ≥ 0.80`, and both days have a single compatible methodology. `R` is a price-weighted one-copy return: a print's contribution to the day's yen change is `ΔJPY(i) = v(i,d) − v(i,p)`; its exact percentage-point contribution is `100 × ΔJPY(i) / P`; the contributions sum to `100r`. No CPI-style per-print cap is applied. Flag suspicious outliers for evidence review and withhold a disputed step rather than change the arithmetic invisibly.

Within a continuous publishable segment, set `F(base) = 1` and `F(d) = F(p) × R`. `F` is **dimensionless performance**, not a historical JPY sum. On a failed gate, missing UTC snapshot, contributor/version break, or invalid denominator, publish no return and mark a segment break; the next positive-sum day can be a new base at 1, but no 7D/30D window crosses that break. Never forward-fill, zero-fill, or bridge a skipped date. A `[Value]` chart could compute `S(s,end) × F(d)/F(end)` within one segment, but every earlier JPY point is a **modeled, endpoint-anchored value** that can restate as the anchor changes; it must be named accordingly. Prefer a percentage `[Performance]` chart first. A0's divisor alternative adds machinery without removing this semantic distinction.

**Today’s live tracked sum and the historical-series endpoint need not match.** The latest archived chart point is 2026-09-25; the live headline was valued on 2026-09-26. Do not connect the live headline to the archived line or report a 1D move until a same-scope, same-as-of, comparability-checked live bridge exists. Even with such a bridge, the literal current sum is separate from past modeled JPY points. The API must carry both times and both semantics explicitly.

### State changes and provenance

| Event | Current literal sum | Movement step |
| --- | --- | --- |
| First usable price | Print enters and raises `S` | Excluded until it has a comparable prior-day price. |
| Price becomes unusable | Print leaves `S` | Excluded; no fake decline. |
| Price re-enters after a gap | Re-enters `S` | First return after re-entry excluded; next adjacent stable pair may qualify. |
| Contributor identity changes | Uses the current resolver's value | Excluded for that transition; may rejoin after one stable adjacent pair. |
| Index/source-semantic methodology changes | Current value uses the new rule | No cross-version return; break/segment rebase, never a fabricated 0%. |
| Release FK corrected | Current sum moves to the corrected release | Historical points retain their as-published membership revision; exclude the reassigned print from the cross-correction release step, record a catalogue break, and test the remaining panel. Overall identity remains the same if eligibility remains valid. |
| Print deactivated, superseded, or verification changes | Current scope excludes it while ineligible | Preserve prior published points; treat entry/exit as coverage, not price movement. |

**Membership provenance rule:** Newly published points freeze the physical-print-to-release assignment and active/verified eligibility used at publication. Store an immutable membership revision or compact append-only membership ledger with effective UTC date, source catalogue version, and digest; a point must reference it. This is needed because `MarketIndexSnapshot` stores print ID but no historical release/status record. For initial replay, the existing archive can be joined to the **current corrected** catalogue, but record that replay-basis revision and its effective assumption. Do not claim it was Atlas's historical membership on those old dates. Later corrections apply forward and start an auditable segment/break; any historical restatement needs an explicit new methodology/data revision, never a silent rewrite.

## Collector-facing read contracts

- **Compare releases:** List all releases in the selector by authoritative ID; an ineligible release says **“Price coverage in progress.”** Chart only releases whose **entire selected window** passes the release movement gate and has a common valid baseline date. Rebase each eligible series to `0%` at that date. OP-05, OP-06, and OP-17 currently get no misleading flat/sparse line. A release can have a table sum while comparison remains unavailable.
- **Market movers:** Initially use the latest published **daily step** in the selected scope. Gainer/loser rank positive/negative exact-print `% change = 100 × (v_d/v_p − 1)` over comparable `C`; impact ranks by `|ΔJPY|` with exact print ID as deterministic tie-breaker. Show both **“Basket change: +¥X”** and **“Impact: +Y percentage points”**; the latter reconciles to the daily basket return before rounding. Do not reuse CPI `approx_index_points` or its capped/equal-weight rankings. Multi-day attribution is a later contract, since daily denominators compound.
- **Most valuable cards:** Exact physical prints with a usable **current** Atlas Market Index value, scoped by Overall or `release_product_id`, sorted `index_value_jpy DESC, card_print_id ASC`; null prices excluded, siblings never collapsed. Return `card_print_id`, card/release/print/artwork identity, JPY value, and calculation time. Default **10**, maximum **50**, stable pagination/tie order. The existing `/prints` filter and `index_desc` sorting are a useful base but the new Market response needs one aligned valuation time.
- **Release market table:** `release_product_id`, official code/English label, `tracked_value_jpy` or null, priced/physical count and fraction, `7d`/`30d` return or null, top daily mover or null, availability reason, `as_of`. Display a low-coverage sum only as an explicitly partial tracked value; a no-price row shows **— / Price coverage in progress**, not ¥0. A movement cell with a failed gate shows **— / Insufficient coverage** or a more exact break/history reason, not 0%. Top mover appears only for a valid published step.
- **FX:** JPY only for the first implementation. No authoritative FX feed exists in the repository. A later approximate current USD reference must carry its rate, provider, and timestamp and must never feed the JPY return. Historical daily USD conversion would introduce exchange-rate movement and needs a separately named view.
- **Watermark:** Every primary Market chart visibly includes **CARDPIRATE ATLAS** and preferably `cardpirateatlas.com` **inside the captured/exported chart frame**, without hover. Place the wordmark and small domain in a reserved lower chart margin, left aligned on desktop/mobile, away from plotted marks and axis labels. Target roughly **12–14px desktop / 11–12px mobile** legible text at **60–75% opacity**; a compass may sit behind at **10–15% opacity**. The current 7%-opacity mark alone is insufficient. Export, if added, must render the same mark without clipping; check screenshots at ~1500px and ~390px.

### Provisional API payload semantics

| Read surface | Minimum fields and failure behavior |
| --- | --- |
| `GET /market/value` | Scope=`overall`; live `tracked_value_jpy`, priced/physical/coverage, `valuation_as_of`, basis=`Atlas Market Index JPY`, prominence/quality state; historical `series_as_of` and published 7D/30D only if their full windows pass. |
| `GET /market/value/releases/{id}` | Same fields for exact `ReleaseProduct.id`; return its identity, official/English label, `release_product_id`, `headline_eligible`, `movement_eligible`, and explicit unavailable reason. Unknown ID is 404, never Overall fallback. |
| `GET /market/releases` | Dated ReleaseProducts with table fields above plus inclusion of uncoded IDs; stable server order, quality state, no fabricated percentage. |
| `GET /market/movers` | Exact scope/date, prior/current snapshot dates, panel `P/Q/C`, signed `ΔJPY`, percentage-point impact, per-print move %, source/version basis, true global ranks and truncation metadata. Unavailable with reason if step unpublished. |
| `GET /market/most-valuable` | Scope, common valuation timestamp, top exact physical prints with deterministic sort and total eligible count; missing prices excluded. |

Shared payload rules: distinguish `null` from genuine zero; use UTC times and integer/decimal JPY; include methodology and membership revisions, snapshot dates, gate inputs, coverage, break reasons, and requested-window availability. Invalid/unknown release IDs never become Overall. Value, ranking and movers must either share a valuation/snapshot token or clearly disclose differing `as_of` times. URLs above are provisional.

## Persistence boundary and PR #18 disposition

Use a new **`MarketValuePoint`** series rather than generalizing `CardPirateIndexPoint`. CPI is dimensionless, equal-weight, based at 1000, capped, and constrained around `index_value`; repurposing it would give one table incompatible meanings. A future migration should create one daily point table for Overall and release scopes, plus the immutable membership revision/ledger required to reproduce release history. Natural identity is `(scope, UTC point_date, monetary_methodology_version)`; `scope` is `overall` or the typed `release_product_id` FK. Implement separate unique constraints for Overall and release rows so a nullable FK cannot admit duplicate Overall dates. Store `raw_tracked_value_jpy` (wide integer/decimal), priced and physical counts, `P/Q/C`, step ratio, chain factor/segment, two-sided priced-value shares, largest-print share, status/break, index/source-semantic versions, membership revision, snapshot/input fingerprint, and creation/calculation times. Do not overwrite archived Market Index snapshots or CPI points. A deterministic read-only replay can be built and checked before any A2 write; **new durable public points require a migration**, none is authorized here.

| PR #18 piece | Classification | New-direction treatment |
| --- | --- | --- |
| Release selector and URL state | **ADAPT** | Reuse ID-based routing and Back/Forward behavior; scope value, movement, movers and rankings together, with explicit unavailable states. |
| English release names | **REUSE** | Keep official Asia-English presentation map; ID remains membership authority. |
| Move % / Index impact control | **ADAPT** | Keep separate move and impact questions; replace CPI impact with exact monetary `ΔJPY` and percentage-point contribution. |
| Market Snapshot | **DISCARD** as primary | Replace with tracked JPY value and movement; retain coverage only as nearby quality context or methodology detail. |
| Cards in this market / Browse these cards | **ADAPT** | Replace arbitrary strip with Most valuable exact prints; scoped browse URL/navigation can be reused. |
| Market structure | **ADAPT** | Move distribution/source coverage to secondary Data & methodology; remove prominence of median, bands and catalogue tiles. |
| Responsive layout and artwork handling | **REUSE** patterns | Revalidate redesigned chart/table on desktop/mobile with real artwork and no overflow. |
| Branch Preview variables and exact-origin CORS | **REUSE** setup | Existing staging Preview plumbing remains useful for the later implementation; no configuration change in A1. |

**Smallest independently testable implementation path:** A1 freezes this methodology and its example fixtures; A2 adds membership provenance and `MarketValuePoint` schema, a pure archive estimator, dry-run replay/verify, and only then authorized forward persistence; A3 exposes Overall current value/quality and published historical movement with snapshot-aligned tests; A4 adds release scopes, 7D/30D gates and release table, including mixed-code and sparse cases; A5 adds monetary movers and exact-print most-valuable ranking; B1 replaces the old Market page with the new headline/chart and unavailable states; B2 adds qualified release comparison; B3 finishes screenshot/export watermark and responsive sharing verification. Each API tranche must prove no source refetch, no historical snapshot rewrite, exact scope identity, and null-vs-zero behavior before the next tranche. PR #18 remains open and unmerged throughout this design tranche.
