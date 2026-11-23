# Railway-specific build for the worker service (Celery worker). Same
# repo-root-build-context reasoning as deploy/railway/api.Dockerfile - see
# that file's header comment and "Railway build failure" in
# docs/railway_staging.md.
#
# Local verification: docker build -f deploy/railway/worker.Dockerfile -t opcg-worker-railway-test .
# (run from the repo root - NOT from services/worker).
#
# Local Compose now also uses root context for the shared identity package.
# No public port - worker only consumes Celery tasks over Redis,
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

# Base pinned by multi-arch index digest (read 2026-11-23 14:35 MYT from Docker Hub);
# refreshed by a reviewed PR, never floating.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

WORKDIR /app

COPY services/worker/requirements.txt .
# Upgrade the base image's bundled pip (and its vendored CA bundle) before
# any dependency install.
RUN python -m pip install --no-cache-dir "pip==26.2.2"
RUN pip install --no-cache-dir -r requirements.txt

COPY packages/opcg_source_identity /opt/opcg_source_identity
RUN python -m pip install --no-cache-dir --no-deps /opt/opcg_source_identity
COPY services/worker/. .
RUN python -c "from worker.matching.listing_identity import canonical_source_listing_identity as derive; from opcg_source_identity.vectors import verify_contract; verify_contract(derive)"

ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown
ARG APP_VERSION=0.1.0
ENV GIT_COMMIT=${GIT_COMMIT}
ENV BUILD_TIME=${BUILD_TIME}
ENV APP_VERSION=${APP_VERSION}

CMD ["sh", "-c", "celery -A worker.celery_app worker --loglevel=info --concurrency=${WORKER_CONCURRENCY:-2}"]
