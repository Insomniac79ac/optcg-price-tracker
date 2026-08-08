# Railway build for the permanent Yuyu-Tei collector service. Same
# repo-root-build-context convention as deploy/railway/api.Dockerfile and
# deploy/railway/worker.Dockerfile - see those files' header comments.
#
# Local verification: docker build -f deploy/railway/yuyutei-collector.Dockerfile -t opcg-yuyutei-collector-test .
# (run from the repo root - NOT from services/yuyutei_collector).
#
# Base image pins the exact browser build that matches
# services/yuyutei_collector/requirements.txt's `playwright==1.61.0` (same
# pin, same base image family already validated in
# spikes/yuyutei-browser-feasibility/Dockerfile.railway), so no browser
# download happens at container start - only `pip install` at build time.
#
# No public HTTP server - this image runs one bounded collection and exits;
# it never binds a port, so do not enable public networking for this
# service in Railway. No Redis requirement - the collector only talks to
# Postgres and to Yuyu-Tei. No browser profile is persisted (a fresh
# BrowserContext per run, never launch_persistent_context). No application
# admin credentials are read or required.
#
# The default CMD below deliberately does NOT run a live collection - it
# only prints readiness so an automatic deploy from a git push never
# triggers a Yuyu-Tei request on its own. Real collection runs are invoked
# explicitly:
#   python -m yuyutei_collector.collect --mapping-id <id>
# Railway Cron is not configured yet (see the tranche this was built for).

FROM mcr.microsoft.com/playwright/python:v1.61.0-jammy

WORKDIR /app

COPY services/yuyutei_collector/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/yuyutei_collector/. .

ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

CMD ["python", "-c", "print('yuyutei-collector image ready; invoke via python -m yuyutei_collector.collect --mapping-id <id>')"]
