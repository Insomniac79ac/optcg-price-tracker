# Railway build for the permanent SNKRDUNK collector service. Same
# repo-root-build-context convention as deploy/railway/yuyutei-collector.Dockerfile
# - see that file's header comment for the full reasoning (base image
# pinning, no browser download at container start, no public server, no
# Redis, no persisted browser profile).
#
# Local verification: docker build -f deploy/railway/snkrdunk-collector.Dockerfile -t opcg-snkrdunk-collector-test .
# (run from the repo root - NOT from services/snkrdunk_collector).
#
# This service is for exactly one already-approved, exact-print-linked
# SNKRDUNK mapping at a time (see snkrdunk_collector/collect.py's
# --mapping-id). No batch mode yet - that comes when SNKRDUNK is scaled
# beyond the one verified print this tranche productionizes.
#
# The default CMD below deliberately does NOT run a live collection - it
# only prints readiness so an automatic deploy from a git push never
# triggers a SNKRDUNK request on its own. Real collection runs are invoked
# explicitly:
#   python -m snkrdunk_collector.collect --mapping-id <id>
# Railway Cron is not configured for this service yet.

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

COPY services/snkrdunk_collector/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Same service package used by API and both opt-in adapters; no scheduler copy.
COPY packages/opcg_source_identity /tmp/opcg_source_identity
COPY services/api /tmp/opcg_collection_services
RUN pip install --no-cache-dir /tmp/opcg_source_identity /tmp/opcg_collection_services

COPY services/snkrdunk_collector/. .
RUN python -c "from snkrdunk_collector.due import run_due"

ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

# Every collector log line is one print()'d JSON object (see
# snkrdunk_collector/browser.py's log_event) - without this, Python
# block-buffers stdout/stderr whenever they're not a TTY (always true under
# Railway), so a run's log lines only surface once the buffer fills or the
# process exits.
ENV PYTHONUNBUFFERED=1

CMD ["python", "-c", "print('snkrdunk-collector image ready; invoke via python -m snkrdunk_collector.collect --mapping-id <id>')"]
