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

# Base: Playwright 1.61.0 on Ubuntu 24.04 (Python 3.12), pinned by the multi-arch
# index digest read 2026-11-18 so a re-pointed tag cannot change the build.
FROM mcr.microsoft.com/playwright/python:v1.61.0-noble@sha256:a9731514f24121d1dcd25d58d0a38146646d290a5998fd80d3e533e7b5e21c69

# OS security update (read 2026-11-18): bring libbrotli1 to the fixed version
# from the Ubuntu security notice; the version installed is printed in the build log.
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade libbrotli1 \
    && dpkg-query -W -f='libbrotli1 installed version: ${Version}\n' libbrotli1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/yuyutei_collector/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Same service package used by API and both opt-in adapters; no scheduler copy.
COPY packages/opcg_source_identity /tmp/opcg_source_identity
COPY services/api /tmp/opcg_collection_services
RUN pip install --no-cache-dir /tmp/opcg_source_identity /tmp/opcg_collection_services

COPY services/yuyutei_collector/. .
RUN python -c "from yuyutei_collector.due import run_due"

ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

# Every collector log line is one print()'d JSON object (see
# yuyutei_collector/browser.py's log_event) - without this, Python
# block-buffers stdout/stderr whenever they're not a TTY (always true under
# Railway), so a batch run's log lines only surface once the buffer fills or
# the process exits, defeating live log tailing during a scheduled cron run.
# Global, not per-print(flush=True) - covers every current and future
# print() call in this service with one setting.
ENV PYTHONUNBUFFERED=1

CMD ["python", "-c", "print('yuyutei-collector image ready; invoke via python -m yuyutei_collector.collect --mapping-id <id>')"]
