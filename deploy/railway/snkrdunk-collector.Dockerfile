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

FROM mcr.microsoft.com/playwright/python:v1.61.0-jammy

WORKDIR /app

COPY services/snkrdunk_collector/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/snkrdunk_collector/. .

ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

# Every collector log line is one print()'d JSON object (see
# snkrdunk_collector/browser.py's log_event) - without this, Python
# block-buffers stdout/stderr whenever they're not a TTY (always true under
# Railway), so a run's log lines only surface once the buffer fills or the
# process exits.
ENV PYTHONUNBUFFERED=1

CMD ["python", "-c", "print('snkrdunk-collector image ready; invoke via python -m snkrdunk_collector.collect --mapping-id <id>')"]
