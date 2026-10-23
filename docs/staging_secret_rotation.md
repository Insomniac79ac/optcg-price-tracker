# Staging secret rotation runbook

Rotate every staging secret after a provider incident (Railway disclosed one on 2026-10-21) or a
suspected leak. Written from the 2026-10-22/23 rotation; the "Pitfalls" section lists what went wrong
then. Staging only: production is a separate, owner-only decision.

The owner does every step in a dashboard. A coding session never sees a value: it only dispatches
the read-only checks named below and reads their summaries. Never paste a secret into a chat, a task,
a PR or a log.

## Rules

- **One source of truth.** In Railway, a variable that repeats a password must be a reference
  (`${{...}}`), never a typed copy. Create references by typing `${{` and picking from the dropdown,
  so the names are exact; a wrong name resolves to an empty value without any error. After saving,
  the eye icon must show a full value, not a blank.
- **Variables reach a service only on a new deployment.** A restart or a cron run keeps the old
  values. Deploy with the banner at the top of the canvas, or select the service and use
  **Ctrl+K → Deploy Latest Commit**.
- **Never deploy a collector from Railway.** Before clicking the banner's Deploy, read its list. If it
  names `snkrdunk-collector` or a `yuyutei-collector-shard-*`, do not deploy collectors from there:
  "Deploy latest commit" builds them from the branch and loses their verified, pinned build. To give
  collectors new variables, run the `collector-redeploy` ops-write runbook
  ([agent/OPS_RUNBOOKS.md](agent/OPS_RUNBOOKS.md)): dry run, owner approval, then apply with the dry
  run's `plan_sha256`, owner approval again. It redeploys each collector on its fleet-pinned image.
- **New values**: 64 characters for app secrets, 32 for database passwords; letters and numbers only,
  from a password manager's generator. Select all and delete before pasting, so no stray space or
  line break is kept.
- **Order**: Railway token first (the checks need it), then the most powerful secrets. Check after
  each one before moving on.

## Inventory and steps

| # | Secret | Lives in | Read by |
|---|---|---|---|
| 1 | Railway project token | GitHub, Environment `Staging-delivery`, secret `STAGING_RAILWAY_TOKEN` | Every CI delivery, Verify and ops runbook |
| 2 | Postgres password | Railway `Postgres`: `POSTGRES_PASSWORD` | api, worker, beat, market-index-snapshot, official-images-mirror, collectors, ops runbooks |
| 3 | Redis password | Railway `Redis`: `REDIS_PASSWORD` | api, worker (job queue), beat |
| 4 | `API_JWT_SECRET` | Railway `optcg-price-tracker` and Vercel staging project (identical) | api and website (signed passes) |
| 5 | `AUTH_SECRET` | Vercel staging project | website sessions |
| 6 | `ADMIN_TOKEN` | Railway `optcg-price-tracker` and Vercel staging project (identical) | api admin routes; website server side |
| 7 | R2 keys `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Railway `optcg-price-tracker` (`official-images-mirror` references them) | card image storage |
| 8 | `TELEGRAM_BOT_TOKEN` | Railway app services, only if a bot is set | alerts |
| 9 | Sentry DSN | Vercel / Railway | error reports (lowest risk) |

### 1. Railway project token

1. Railway → Card Pirate project → **Settings** (project level) → **Tokens** → create a token for the
   **staging** environment. Copy it once.
2. GitHub → repository → **Settings** → **Secrets and variables** → **Actions** → under
   **Environment secrets**, `STAGING_RAILWAY_TOKEN` (environment `Staging-delivery`) → pencil →
   paste → **Update secret**.
3. Delete every older token in Railway → Settings → Tokens.
4. Check: `ops-readonly staging-state`. Railway reads pass (a database failure here is item 2).

### 2. Postgres password

1. Railway → `Postgres` → **Database** tab → **Config** → regenerate the password. This changes the
   database and `POSTGRES_PASSWORD`, nothing else.
2. `Postgres` → **Variables**: these must be references, not copies:
   - `PGPASSWORD` = `${{POSTGRES_PASSWORD}}`
   - `DATABASE_URL` = `postgresql://${{PGUSER}}:${{POSTGRES_PASSWORD}}@${{RAILWAY_PRIVATE_DOMAIN}}:5432/${{PGDATABASE}}`
   - `DATABASE_PUBLIC_URL` = `postgresql://${{PGUSER}}:${{POSTGRES_PASSWORD}}@${{RAILWAY_TCP_PROXY_DOMAIN}}:${{RAILWAY_TCP_PROXY_PORT}}/${{PGDATABASE}}`
3. Deploy the banner (app services only) and wait for green.
4. Collectors: `collector-redeploy` runbook (see Rules).
5. Check: `ops-readonly staging-state` and `db-diagnostic` succeed; an `auth` class in the failure
   means a service still has the old password.

### 3. Redis password

1. Railway → `Redis` → **Variables**:
   - `REDIS_PASSWORD` = the new password
   - `REDISPASSWORD` (if present) = `${{REDIS_PASSWORD}}`
   - `REDIS_URL` = `redis://${{REDISUSER}}:${{REDIS_PASSWORD}}@${{REDISHOST}}:${{REDISPORT}}`
   - `REDIS_PUBLIC_URL` (if present) = `redis://${{REDISUSER}}:${{REDIS_PASSWORD}}@${{RAILWAY_TCP_PROXY_DOMAIN}}:${{RAILWAY_TCP_PROXY_PORT}}`
   - Keep `REDISUSER` = `default` (the built-in user the password protects).
2. Eye icon on `REDIS_URL`: a full `redis://...` value, not blank.
3. `optcg-price-tracker`, worker and beat: `REDIS_URL` = `${{Redis.REDIS_URL}}` (via the dropdown),
   eye icon not blank.
4. **Restart Redis**: `Redis` → **Deployments** → ⋮ on ACTIVE → **Redeploy**. Its start command reads
   `REDIS_PASSWORD` only at start (`--requirepass $REDIS_PASSWORD`).
5. Redeploy `optcg-price-tracker`, worker and beat (Ctrl+K → Deploy Latest Commit).
6. Check: `https://optcg-price-tracker-staging.up.railway.app/health` shows `"redis_connected":true`.

### 4 to 6. `API_JWT_SECRET`, `AUTH_SECRET`, `ADMIN_TOKEN`

Everyone is signed out of staging afterwards. That is expected.

1. Three new values in the password manager.
2. Railway `optcg-price-tracker` → Variables: `API_JWT_SECRET` and `ADMIN_TOKEN`. Also on worker and
   beat if those names exist there. Deploy the banner (app services only).
3. Vercel → staging project → **Settings** → **Environment Variables**: `API_JWT_SECRET` (same value
   as Railway), `AUTH_SECRET`, `ADMIN_TOKEN` (same value as Railway). Update every row of a name
   (Production and Preview). Then **Deployments** → top entry → ⋮ → **Redeploy**.
4. Check: `https://optcg-price-tracker-staging.vercel.app/api/collector-token-check` shows
   `{"status":"ok"}` (the two `API_JWT_SECRET` copies match), and `ops-readonly web-smoke` passes.

### 7. R2 keys

1. Cloudflare → **R2 Object Storage** → **Manage API tokens** → create a token with **Object Read &
   Write**, applied to the staging bucket only. Copy the Access Key ID and Secret Access Key once.
2. Railway `optcg-price-tracker` → Variables: `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`. Deploy;
   also redeploy `official-images-mirror` (Ctrl+K → Deploy Latest Commit; it is not a collector).
3. Delete the old token in Cloudflare.
4. Check: `ops-readonly official-images-status` healthy, then the mirror's next scheduled run
   succeeds (the first write with the new key).

### 8. Telegram bot token (only if set)

Telegram → @BotFather → `/mybots` → the bot → **API Token** → **Revoke current token**. Paste the new
token into `TELEGRAM_BOT_TOKEN` on every app service that has it, then deploy. Revoking kills the old
token at once. `TELEGRAM_CHAT_ID` is not a secret.

### 9. Sentry DSN

Sentry → the project → **Settings** → **Client Keys (DSN)** → create a new key, put it where the old
DSN was, deploy, then disable the old key. It only allows sending events, so it is last.

## Afterwards

- A **Verify staging merge** re-run on the same commit fails with "Unexpected API build for a change
  outside its watch paths". The rotation redeployed the api on a commit whose merge Railway had
  skipped, and Verify refuses that by design. It clears on the next merge to staging; do not change
  the verifier for it.
- `collector-redeploy` replaces each collector's deployment, so Verify's SNKR check needs one natural
  SNKRDUNK run (at :27 and :57) before it passes.

## Pitfalls seen on 2026-10-22/23

- Postgres regenerate changed only `POSTGRES_PASSWORD`; `PGPASSWORD`, `DATABASE_URL` and
  `DATABASE_PUBLIC_URL` were typed copies of the old password, so every service and check got "auth"
  failures while Railway's Data tab still worked.
- Restarting crashed collector cron runs kept the old password; only a new deployment carries new
  variables.
- "Deploy latest commit" on collectors (from the banner and by hand) started branch builds that
  failed and left them off their pinned builds until `collector-redeploy` put them back.
- `collector-redeploy` first used the committed rollout receipts and put SNKRDUNK on an older image;
  it now uses the fleet pins in `docs/agent/STAGING_FLEET.json`.
- Redis `REDIS_URL` was rebuilt by hand with a wrong name inside `${{ }}` and resolved to an empty
  value; the api's next deploy then failed its health check ("REDIS_URL must not be empty"). Use the
  dropdown and check the eye icon.
- `ADMIN_TOKEN` also lives in Vercel (the website's server adds it to admin calls); an old note in
  `.env.staging.example` said otherwise and was corrected.
