# Owner decision: staging database storage (2026-10-10)

**Decision needed by: 2026-10-29.** The worst-case growth rate reaches the
3 GiB safety reserve on about 2026-11-06; this leaves one week for a resize
and its verification.

**Recommendation: grow the Railway Postgres volume from 10 GB to 20 GB.**
Keep reducing growth in code alongside it. Do not archive RAW evidence to R2
now.

## Where we are

Measured 2026-10-10 08:06Z (`evidence/volume-0810.json`):

- The volume holds 3,633 MB of its 10,000 MB limit (3,636.7 MB at 15:15Z).
- The 3 GiB reserve (3,221 MB) leaves **3,146 MB** of usable room.

| Growth rate | MB/day | Days to reserve | Reserve reached | Basis |
|---|---|---|---|---|
| Worst case | 116.7 | 27 | ≈ 2026-11-06 | MEASURED, session 7, full 24h including vacuum lag |
| Measured now | 47.9 | 66 | ≈ 2026-12-15 | MEASURED, volume 10-09 14:27Z → 10-10 08:06Z |
| After this session's storage fix (a) | ≈ 48 | ≈ 65 | ≈ 2026-12-14 | ESTIMATE, below |
| After fix (a), per-turn browser and proposal-version fix | ≈ 27 | ≈ 116 | ≈ 2027-02-03 | ESTIMATE, below |
| Early reading after fix (a) and the per-turn browser | 11.8 | ≈ 266 | — | MEASURED over a short window, 08:07–15:15Z, 3,633.2 → 3,636.7 MB. Too short to plan on; session 9 measures 24h |

**Why these estimates**
- **Fix (a), encode before insert.** It stops ~167 MB/day of throw-away plaintext
  being written and later vacuumed. It mostly removes the "worst case" swings
  (the 116.7 figure) rather than lowering the long-run floor. That floor is set
  by real new data:
  - new RAW about 28.5 MB/day;
  - indexes and overhead a few MB/day;
  - other tables about 16.6 MB/day;
  - so about 48 MB/day in total.
- **Per-turn browser.** Delivered at 14:31Z on a852244. It cuts the SNKRDUNK
  homepage copies from ~287 to ~48 a day (MEASURED: 1 per turn, 67 KB), about
  −15.7 MB/day (ESTIMATE).
- **Proposal-version fix.** It is about −5.1 MB/day. Its design is ready for
  session 9 and it has not been delivered.
- Every reduction counts only once it is delivered and measured in natural
  operation.

**NEW100 (100 new cards)** is still blocked. On a 90-day basis it needs about
4.3–8.8 GB more headroom (CARRIED FORWARD, session 7).

## Options

| | A. Grow the volume (recommended) | B. Archive old RAW to R2 | C. Growth reduction only |
|---|---|---|---|
| What it is | Raise the limit to 20 GB in Railway | Copy old RAW bodies to R2, verify restore, then remove them from Postgres | Keep shipping code fixes |
| Cost | $0.15/GB-month **for storage used**, not the limit: ≈ $0.55/mo now, ≈ $1.50/mo at 10 GB used | R2 Standard $0.015/GB-month: ≈ $0.04/mo for 2.5 GB, plus engineering time | Engineering time only |
| Effect | +10 GB. Covers NEW100 (+4.3–8.8 GB at 90 days). Runway ≥ 6 months even at the worst rate | Up to ~2.4 GB back, but only after a table rewrite | Later reserve date, ≈ Dec to Feb, if each fix lands |
| Reversible? | **No**: Railway cannot shrink a volume. Little practical downside, because billing follows use | Restore is possible but must be proven. The bodies leave the primary database | Yes |
| Risk | Low: a provider operation on one volume, done outside the busy window with a verified backup | High: evidence leaves the database (an owner policy call). Space comes back only after rewriting `raw_snapshots` (2.6 GB, an ACCESS EXCLUSIVE lock for minutes, blocking collector writes) and a restore drill | Fixes may slip or under-deliver. No room for NEW100 |
| Provenance | Untouched | Kept only if the R2 copy, its SHA and the restore are all verified | Untouched |

## Why A

- It is the only option that makes room for NEW100.
- It costs about a dollar a month, because Railway bills used gigabytes, not
  the limit.
- It touches no evidence.
- Its single drawback is that it cannot be undone. With usage-based billing,
  a larger-than-needed limit costs nothing extra.

B saves cents per month. It needs a risky table rewrite and a policy decision
to move evidence out of the database. Revisit it only if storage reaches tens
of GB. C alone leaves no headroom for NEW100, and its later dates depend on
fixes that have not yet been measured.

**If you approve A**, the agent will prepare an AMBER change:
- a fresh logical backup, verified to restore;
- the resize, outside 02:00–06:00 UTC;
- re-verification of the database fingerprints, volume size and all collectors;
- a recomputed runway.

Production is not affected. This is staging only.

Pricing checked 2026-10-10:
[Railway pricing](https://docs.railway.com/pricing/plans) ($0.15/GB/month, billed for storage in use),
[Railway volumes](https://docs.railway.com/volumes/reference) (no downsizing),
[Cloudflare R2 pricing](https://developers.cloudflare.com/r2/pricing).
