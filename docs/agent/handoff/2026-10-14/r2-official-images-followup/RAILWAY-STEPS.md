# Create `official-images-mirror` (owner, Railway dashboard, staging only)

The repository tooling cannot do this. The only supported variable path,
`scripts/collector_variables.py`, accepts collector RAW keys only. A
repository scan test refuses any other tooling that sets Railway variables.
Every value below copies `market-index-snapshot`, read from Railway on
2026-10-14.

Do this after PR #120 is merged and delivered. Do it outside 19:30-20:30 UTC.

1. Open the Card Pirate project in Railway and select the **staging**
   environment in the top bar. Check that it does not say production.
2. Click **+ Create**, then **GitHub Repo**, then
   `Insomniac79ac/optcg-price-tracker`.
3. When the new service appears, click its name and rename it to exactly
   `official-images-mirror`. The state report looks for this name.
4. Go to **Settings**, then **Source**:
   - **Branch:** `staging`.
   - **Root Directory:** `/`.
   - **Watch Paths:** add `services/api/**`, then
     `deploy/railway/api.Dockerfile`.
5. Still in **Settings**, go to **Build**. Set the **Dockerfile Path** to
   `deploy/railway/api.Dockerfile`.
6. Still in **Settings**, go to **Deploy**:
   - **Custom Start Command** (copy exactly):
     `/bin/sh -c "python -m app.mirror_official_images --write --quiet && exec python -m app.check_official_images"`
   - **Cron Schedule:** `15 7 * * *` (07:15 UTC daily).
   - **Restart Policy:** `Never`.
   - Leave the healthcheck path empty.
   - Do **not** add a public domain under Networking.
7. Go to the **Variables** tab, then **Raw Editor**, and paste the block
   below. These are references to the staging API service, so no secret is
   copied by hand:

   ```
   DATABASE_URL=${{optcg-price-tracker.DATABASE_URL}}
   R2_ACCOUNT_ID=${{optcg-price-tracker.R2_ACCOUNT_ID}}
   R2_ACCESS_KEY_ID=${{optcg-price-tracker.R2_ACCESS_KEY_ID}}
   R2_SECRET_ACCESS_KEY=${{optcg-price-tracker.R2_SECRET_ACCESS_KEY}}
   R2_BUCKET_NAME=${{optcg-price-tracker.R2_BUCKET_NAME}}
   R2_PUBLIC_BASE_URL=${{optcg-price-tracker.R2_PUBLIC_BASE_URL}}
   ```

   Add nothing else.
8. Click **Deploy** (or **Apply changes**). The build makes the image. It
   does not run the job; Railway runs a cron only at its schedule.
9. Do not touch any collector service (`snkrdunk-collector`,
   `yuyutei-collector-shard-*`) or its variables.
10. Tell the session the service exists. It will then verify the service
    read-only (name, schedule, start command, restart policy, watch paths,
    variable names, 0 collector deployments) and check the first 07:15 UTC
    run.

**To stop it later:** clear the Cron Schedule, or delete the service. This
leaves rows and R2 objects in place (both are insert-only).
