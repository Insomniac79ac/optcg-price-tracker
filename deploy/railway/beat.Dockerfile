# Railway-specific build for the beat service (Celery beat/scheduler). Same
# image contents as deploy/railway/worker.Dockerfile (both come from
# services/worker - beat is just a different process from the same
# codebase, same as docker-compose.yml/docker-compose.prod.yml, which both
# build worker and beat from services/worker with only the `command:`
# differing), just with a different default CMD so this service runs the
# scheduler instead of the worker if Railway's start command override is
# ever left unset. See deploy/railway/api.Dockerfile's header comment for
# why this is built from repo-root context.
#
# Local verification: docker build -f deploy/railway/beat.Dockerfile -t opcg-beat-railway-test .
# (run from the repo root - NOT from services/worker).
#
# Does not change docker-compose.yml/docker-compose.prod.yml or
# services/worker/Dockerfile - local Docker Compose still uses those
# unchanged. No public port - beat only schedules Celery tasks, it never
# serves HTTP or consumes tasks directly (do not enable public networking
# for this service in Railway).
#
# --schedule=/data/celerybeat-schedule points celery.beat.PersistentScheduler
# (the default scheduler class - no --scheduler override) at a Railway
# volume mounted at /data, so the shelve-backed schedule state (next-run
# bookkeeping for each entry) survives a redeploy/restart instead of resetting
# with the container's writable layer. /data is created here so the mount
# point exists in the image even before a volume is attached; Railway
# overlays the actual volume at runtime.

FROM python:3.12-slim

WORKDIR /app

COPY services/worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/worker/. .

RUN mkdir -p /data

ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown
ARG APP_VERSION=0.1.0
ENV GIT_COMMIT=${GIT_COMMIT}
ENV BUILD_TIME=${BUILD_TIME}
ENV APP_VERSION=${APP_VERSION}

CMD ["celery", "-A", "worker.celery_app", "beat", "--loglevel=info", "--schedule=/data/celerybeat-schedule"]
