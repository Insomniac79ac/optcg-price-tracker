# Railway-specific build for the worker service (Celery worker). Same
# repo-root-build-context reasoning as deploy/railway/api.Dockerfile - see
# that file's header comment and "Railway build failure" in
# docs/railway_staging.md.
#
# Local verification: docker build -f deploy/railway/worker.Dockerfile -t opcg-worker-railway-test .
# (run from the repo root - NOT from services/worker).
#
# Does not change docker-compose.yml/docker-compose.prod.yml or
# services/worker/Dockerfile - local Docker Compose still uses those
# unchanged. No public port - worker only consumes Celery tasks over Redis,
# it never serves HTTP (do not enable public networking for this service in
# Railway).
#
# Celery's --concurrency defaults to the HOST's CPU count (multiprocessing.
# cpu_count()), not the container's actual resource allocation - on Railway
# this showed up as "concurrency: 48 (prefork)" and the container crash-
# looped (OOM-killed forking that many worker processes on a small
# instance, no Python traceback since the kill is external to the
# process). WORKER_CONCURRENCY lets Railway set a safe value via a service
# variable without rebuilding the image; defaults to 2 if unset - see
# docs/railway_staging.md.

FROM python:3.12-slim

WORKDIR /app

COPY services/worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/worker/. .

ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown
ARG APP_VERSION=0.1.0
ENV GIT_COMMIT=${GIT_COMMIT}
ENV BUILD_TIME=${BUILD_TIME}
ENV APP_VERSION=${APP_VERSION}

CMD ["sh", "-c", "celery -A worker.celery_app worker --loglevel=info --concurrency=${WORKER_CONCURRENCY:-2}"]
