# Railway-specific build for the api service. Functionally identical to
# services/api/Dockerfile, but written to be built from the REPO ROOT as
# build context (Root Directory: / in Railway's service settings), not from
# services/api itself - see "Railway build failure" note in
# docs/railway_staging.md for the historical context mismatch. Railway's "Root
# Directory" setting controls both where it looks for this Dockerfile *and*
# the build context passed to `docker build` - pointing it at a
# subdirectory while wanting a repo-root context (or vice versa) silently
# breaks the COPY paths below. This Dockerfile sidesteps that ambiguity
# entirely by always assuming repo-root context, with every COPY spelled out
# relative to the repo root explicitly.
#
# Local verification: docker build -f deploy/railway/api.Dockerfile -t opcg-api-railway-test .
# (run from the repo root - NOT from services/api).
#
# Canonical identity foundation: local Compose now also uses root context
# with services/api/Dockerfile, to install the same shared package. Railway
# root-directory settings are unchanged.

FROM python:3.12-slim

WORKDIR /app

COPY services/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY packages/opcg_source_identity /opt/opcg_source_identity
RUN python -m pip install --no-cache-dir --no-deps /opt/opcg_source_identity
COPY services/api/. .
RUN python -c "from app.services.canonical_listing_identity import canonical_source_listing_identity as derive; from opcg_source_identity.vectors import verify_contract; verify_contract(derive)"

# Release/build metadata - see app/core/version.py (GET /version, GET
# /health, GET /admin/release-status). Same convention as
# services/api/Dockerfile - set these as Railway build args if you want
# GET /version to report a real git commit/build time instead of "unknown".
ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown
ARG APP_VERSION=0.1.0
ENV GIT_COMMIT=${GIT_COMMIT}
ENV BUILD_TIME=${BUILD_TIME}
ENV APP_VERSION=${APP_VERSION}

# Railway injects PORT at runtime (its own convention - the app must bind to
# whatever value it provides, not a hardcoded port). Default 8000 only
# matters for a manual `docker run` without -e PORT=... set (e.g. local
# verification - see docs/railway_staging.md).
ENV PORT=8000
EXPOSE 8000

# sh -c form (not exec-array form) so ${PORT} is expanded by the shell at
# container start - Railway sets PORT as a runtime env var, not a build arg,
# so it isn't known at image build time and can't be baked into an exec-array
# CMD the way services/api/Dockerfile hardcodes "8000".
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
