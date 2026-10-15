# Collector v1 S5: owner steps (staging only)

Written 2026-10-15. Everything here is on **staging**. Do not touch anything
named "production". Capacity session 13 has reported, so the rotations are
unblocked.

Staging website: <https://optcg-price-tracker-staging.vercel.app>

Order: **1** re-test sign-in, **2** rotate the four secrets, **3** delete the
test account. The test account is deleted last because step 2's checks sign
in again, which would recreate it.

Before you start: no staging delivery should be running. On GitHub, open the
repository, click **Actions**, and check that nothing has a yellow
"in progress" dot. Avoid 19:30-20:30 UTC (the nightly market run).

## How to make a new secret value

Use your password manager's generator: **64 characters, letters and digits
only** (no symbols, so nothing breaks when pasted). Make a new value for each
secret. Paste it straight into the field; do not save it in notes, chat or
email. Nobody, including Claude, needs to see it.

## 1. Re-test sign-in

1. Open the staging website in a private/incognito window.
2. Click **Sign in** (top right), then **Sign in with Google**. Pick the test
   Google account and allow access.
3. Open <https://optcg-price-tracker-staging.vercel.app/account>.
   - Pass: you see **Your account**, a **Profile** section with your name,
     email and "Member since" date.
   - Fail: "Your account details could not be loaded". Stop and tell Claude.
4. Also open
   <https://optcg-price-tracker-staging.vercel.app/api/collector-token-check>.
   - Pass: the page shows `{"status":"ok"}` (the API accepts the website's
     pass, so the two copies of `API_JWT_SECRET` match).
   - `mismatch`: the copies differ; do rotation 2d now.
   - A 404 page: the check is not deployed yet; skip this line.
5. Back on **/account**, scroll to the bottom and click **Sign out**. You
   should land back on the site signed out.

## 2. Rotate the secrets (this order)

General rules:

- **Railway**: open the project, click the service, then the **Variables**
  tab. Click the variable, paste the new value, save. Railway then shows a
  banner to deploy the change: click **Deploy**. Wait for the service to show
  **Active** (green). Only touch the services named in each step; **never
  change a collector service** (names containing `snkrdunk` or `yuyutei`). If
  a variable is a **Shared Variable** (project Settings → Shared Variables),
  change it there once instead.
- **Vercel**: open the project **optcg-price-tracker-staging** (not any other
  project). **Settings → Environment Variables**, find the variable, click
  **⋯ → Edit**, paste the new value, save. A new value only takes effect
  after a redeploy: go to **Deployments**, open the newest deployment marked
  **Production** (on this project that is the staging site), click
  **⋯ → Redeploy**, confirm, and wait for **Ready**.
- **GitHub secrets**: repository **Settings → Secrets and variables →
  Actions**. Click the pencil next to a secret, paste, **Update secret**. The
  CI delivery secrets live under **Settings → Environments →
  staging-delivery**. None of the four secrets below is used by this
  repository's CI workflows (checked in `.github/workflows/` on 2026-10-15),
  so normally there is nothing to update on GitHub; see 2a.

### 2a. Vercel protection-bypass secret

What it is: the key that lets automated tools open protected Vercel preview
deployments.

1. Vercel → **optcg-price-tracker-staging** → **Settings → Deployment
   Protection** → **Protection Bypass for Automation**.
2. Click **Regenerate** (or delete the old one and **Add** a new one). Copy
   the new value once.
3. GitHub: open **Settings → Secrets and variables → Actions** (and
   **Environments → staging-delivery**). If a secret there holds this value
   (a name like `VERCEL_AUTOMATION_BYPASS_SECRET` or `...BYPASS...`), update
   it with the new value. If none exists, nothing else uses it; done. (Claude
   could not list secret names from here.)

Breaks in between: only tools that open protected preview links. The staging
site itself and visitors are unaffected.

Verify: open the staging website; it loads as normal. On GitHub, open the
latest **CI** run under **Actions** and click **Re-run all jobs**; it should
go green as before.

### 2b. ADMIN_TOKEN

What it is: the shared key the website uses to call the API's admin endpoints.
Both sides must hold the same value, and it must be at least 32 characters.

1. Railway: set the new value on **api**, then on **worker** and **beat** if
   they have an `ADMIN_TOKEN` variable. Deploy each.
2. Vercel: set the same value on `ADMIN_TOKEN`, then Redeploy.

Breaks in between: admin pages (e.g. /admin/system-check) show errors or
"unauthorized" until both sides match. Collectors and public pages are not
affected.

Verify: sign in at <https://optcg-price-tracker-staging.vercel.app/admin/login>
with your admin login, open **/admin/system-check**. Pass: the page shows its
checks, not an authorization error. Sign out.

### 2c. AUTH_SECRET

What it is: the website's own key for sign-in cookies. Vercel only.

1. Vercel: set a new value on `AUTH_SECRET`, then Redeploy.

Breaks in between: every signed-in person (Google and admin) is signed out
once. That is expected. A sign-in started during the redeploy may fail; just
try again after it shows **Ready**.

Verify: in a private window, **Sign in with Google**, open **/account**: the
Profile shows. Admin login at **/admin/login** also works. Sign out.

### 2d. API_JWT_SECRET

What it is: the shared key for collector requests. The website signs a short
pass with it and the API checks it. **Both copies must be identical**; on
2026-10-15 they differed and /account broke.

1. Make one new value. Copy it once.
2. Railway: set it on **api** only. Deploy, wait for **Active**.
3. Vercel: set the same value on `API_JWT_SECRET`, then Redeploy, wait for
   **Ready**.

Breaks in between (between steps 2 and 3 finishing): /account shows "could
not be loaded" and collection pages fail for signed-in collectors. Do steps 2
and 3 back to back.

Verify:

1. Open
   <https://optcg-price-tracker-staging.vercel.app/api/collector-token-check>.
   Pass: `{"status":"ok"}`. `mismatch` means the two values differ: paste the
   value again on both sides, redeploy both.
2. Sign in with Google and open **/account**: the Profile shows.
3. CI: the staging delivery check now requires this to be `ok`. On GitHub,
   **Actions → CI**, open the latest run whose title starts with the most
   recently merged staging PR, and **Re-run** the `staging-automerge` job. A
   green run confirms it.
4. Sign out.

## 3. Delete the test account

1. Sign in with Google (test account), open **/account**.
2. Scroll to **Delete my account**. In the box, type `delete my account`.
3. Click **Delete my account** and wait. You should be signed out.
4. Optional check: sign in again with the same Google account and open
   /account: "Member since" shows today, which means the old account and its
   data were removed and a fresh empty one was made. If you do this, delete it
   again the same way.

## When done

Tell Claude in the project which steps passed. If any check failed, say which
step and what the page showed (never paste a secret value).
