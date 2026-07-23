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

CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=info"]
