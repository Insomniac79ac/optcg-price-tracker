# Codespaces development

The devcontainer pins Microsoft's `universal:5.1.5-noble` image, matching the
existing Ubuntu 24.04 / Python 3.12 / Node 24 environment. Its published
[contents](https://github.com/devcontainers/images/blob/main/src/universal/history/5.1.5.md)
include git, gh, Docker CLI, curl, and bash; bootstrap checks these without
installing replacements. No custom image or extra language runtimes are added.

`postCreateCommand` runs `scripts/codespaces/bootstrap.sh` after creation or a
rebuild, and the editor waits for it to finish. It installs:

- All four service requirement files and `packages/opcg_source_identity` in one
  Python 3.12 environment at `~/.venvs/cardpirate`. This is user-writable and
  outside `/workspaces`, so a full rebuild recreates it. Editor/Codex processes
  and Bash terminals select it automatically.
- Frontend dependencies with `npm ci` from `apps/web/package-lock.json`, replacing
  any surviving `node_modules` rather than relying on its previous contents.
- The declared Python Playwright **1.61.0**, Chromium's headless shell and system
  dependencies, and branded Google Chrome. Default headless workflows use the
  shell; **native Preview validation uses Chrome** (`channel="chrome"` or
  `/usr/bin/google-chrome`), as existing evidence scripts require. This follows
  [Playwright's host installation mechanism](https://playwright.dev/python/docs/browsers).
  Firefox, WebKit, a duplicate full Chromium browser, and the Playwright Docker
  image are not installed.
- Railway CLI **5.62.1** via the official
  [npm installation method](https://docs.railway.com/cli#npm-macos-linux-windows),
  using `~/.local` as its user-writable prefix. Authentication is a later
  operator/session/plugin action.
- Codex CLI via the official [`@openai/codex` npm package](https://developers.openai.com/codex/cli).
  If `codex` is missing or `codex --version` fails, bootstrap installs it globally
  with npm using the user-writable `~/.local` prefix. A usable existing install is
  retained; bootstrap always verifies `codex --version`. It does not authenticate
  Codex or request or store API keys. Authentication remains an operator/runtime
  concern, and credentials must not be stored in repository files.

The image and Railway CLI are versioned, frontend dependencies are locked, and Python
packages follow the repository's declared constraints (some are unpinned).
New Codex CLI installs use the current npm release rather than a pinned version.
Playwright manages its matching browser revision; branded Chrome follows its
stable channel. Rerunning bootstrap is safe, but is an install, not a health-only
command. No application build, database startup, migration, restore, collector,
R2 request, or Docker application-image pull runs during bootstrap.

## Persistence and recovery

A [full Codespaces rebuild](https://docs.github.com/en/codespaces/developing-in-a-codespace/rebuilding-the-container-in-a-codespace)
preserves `/workspaces`, including untracked/ignored evidence, local configuration,
and the repository. Manually installed tools and packages elsewhere are recreated
by bootstrap. Docker containers, images, and volumes are ephemeral across a full
rebuild; do not treat local database volumes as persistent evidence.

The 2026-09-26 emergency manifest for all 31 preserved PostgreSQL volumes is:

```text
/workspaces/.codespaces-rebuild/docker-volume-backup-2026-09-26.json
```

It records private R2 object keys, hashes, and successful GET-back verification.
Those remote archives are **recovery-only** and are never restored automatically.
Create local service state only when explicitly needed after the rebuild.

GitHub Codespaces injects `EVIDENCE_R2_ACCOUNT_ID`, `EVIDENCE_R2_ACCESS_KEY_ID`,
`EVIDENCE_R2_SECRET_ACCESS_KEY`, and `EVIDENCE_R2_BUCKET_NAME` from Codespaces
secrets. They are optional for ordinary development. Bootstrap does not read,
print, or require them, and no credentials belong in devcontainer configuration.

## Rerun and verify

From the repository root, rerun installation with:

```bash
bash scripts/codespaces/bootstrap.sh
```

The script itself resolves the repository root regardless of its initial working
directory. After a rebuild, wait for the final `[codespaces] Ready` message and
open a terminal. These checks perform no installs or external-site launches:

```bash
python --version
python -c 'import fastapi, sqlalchemy, playwright, boto3, opcg_source_identity'
python -m pip check
node --version
npm --version
apps/web/node_modules/.bin/tsc --version
apps/web/node_modules/.bin/vitest --version
python -m playwright install --list
google-chrome --version
railway --version
codex --version
```

Run real bootstrap validation only after the authorized full rebuild; the old
Codespace's remaining disk space is insufficient for a fresh installation.
Environment setup does not resume Public UX 1B, which remains paused separately.
