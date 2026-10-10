# Staging Postgres volume 10 → 20 GB. RED, owner-approved, NOT executed in session 9

**Owner approval (recorded in the session-9 prompt):** APPROVED by the owner on 2026-10-10 (MYT).
Grow the Railway **staging** Postgres volume from 10 GB to 20 GB, per the session-8
`OWNER_STORAGE_BRIEF.md`. The approval covers only that one resize in environment
`05d1eac2-510d-4bd3-999e-fea9ead766b7`.

## Why it was not done in session 9

1. **There is no API path.** Read-only introspection of Railway's public GraphQL schema shows
   that `VolumeInstanceUpdateInput` has only `mountPath`, `serviceId` and `state`, with no size
   field. Railway documents the resize as dashboard-only: volume → **Live Resize**
   (https://docs.railway.com/guides/volumes, checked 2026-10-10).
2. **There is no recent backup.**
   - The newest Postgres volume backup is from **2026-09-30T11:38Z**, 10 days old.
   - **No backup schedule** is configured (`evidence/volume-backups-2220.json`).
   - The procedure requires a fresh backup immediately before the resize.
3. **Timing.**
   - The session started at 22:10Z, 50 minutes before the 23:00Z end of the change window.
   - The collector auto-deploy change ran from 22:16 to about 22:35Z, and the procedure forbids a
     resize during a collector change.
   - An irreversible step was not squeezed into what remained of the window.

## Before (MEASURED 2026-10-10 ~22:20Z)

| | Value | Source |
|---|---|---|
| Volume `postgres-volume` | limit 10,000 MB, used 3,641.5 MB (`currentSizeMB` 3,556.1 from the volume API) | `evidence/volume-2220.json`, `volume-backups-2220.json` |
| Volume instance | `60f9c775-1cc0-4fa3-9d33-4cd6149792b4`, state READY | `volume-backups-2220.json` |
| Database size | 2,794,206,911 bytes | `storage-2220.json` |
| raw_snapshots | 44,947 rows | db query 22:20:15Z |
| price_observations | 35,005 | same |
| market_value_points | 2,940 | same |
| completion receipts (`market_index_snapshot_completions`) | 12, last 2026-10-10 completed 20:04:06Z; 0 rows on 09-27/28 | same |
| Previous resize precedent | backup "Online resize to 10000MB", 2026-09-16 | `volume-backups-2220.json` |

## Railway behaviour (docs, checked 2026-10-10)

- "Railway performs volume resizing live without any downtime… Your application maintains
  read/write access throughout." There is one exception: at 100% full Railway does an offline
  resize, which restarts the service. Usage is now 36%, so a **live** resize, no restart, is
  expected (https://docs.railway.com/guides/volumes).
- "Down-sizing a volume is not currently supported." The resize is **irreversible**.
- Pro plan default maximum: 50 GB (https://docs.railway.com/reference/volumes).
- Backups: `volumeInstanceBackupCreate(volumeInstanceId, name)` creates a manual,
  copy-on-write, incremental backup. Restore stages a new volume and redeploys.
  "Manual backups are limited to 50% of the volume's total size."
  (https://docs.railway.com/reference/backups)

## Procedure for session 10

Run it inside 06:00-23:00Z, not in 02:00-06:00Z, and with no collector release or post-release
observation in progress.

1. Re-read the live state. All 10 collectors must be on a852244 with daily-v1 and no GitHub
   trigger.
2. Record the before values above again.
3. Create a manual backup: `volumeInstanceBackupCreate(volumeInstanceId:"60f9c775-…",
   name:"pre-resize-20GB-<UTC>")`. Wait until `volumeInstanceBackupList` shows it with
   `createdAt` after step 2. Restore verification: the backup is listed with non-zero
   `referencedMB`. A full restore drill would create a second database service and is optional
   (`volumeInstancePITRRestore` creates a new service and leaves the source untouched).
4. The **owner**, or the agent through the dashboard if a browser session is authorised, opens the
   Postgres volume and runs **Live Resize** to 20,000 MB. It must be the staging environment only.
   Confirm the environment selector reads `staging` and the volume instance id matches.
5. After the resize:
   - `sizeMB == 20000`;
   - identical row counts, apart from natural collector inserts;
   - Postgres SUCCESS with no restart, or one brief restart;
   - API `/health` OK;
   - `verify_staging_delivery.py` green, or the next delivery receipt green;
   - all 10 collectors unchanged (`tools/live_now.py`);
   - the next natural turn of each collector completes.
6. If anything is unhealthy, stop and report at the top. Make no further infrastructure changes.
