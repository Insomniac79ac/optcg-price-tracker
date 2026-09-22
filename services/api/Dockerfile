FROM python:3.12-slim

WORKDIR /app

COPY services/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY packages/opcg_source_identity /opt/opcg_source_identity
RUN python -m pip install --no-cache-dir --no-deps /opt/opcg_source_identity
COPY services/api/. .
RUN python -c "from app.services.canonical_listing_identity import canonical_source_listing_identity as derive; from opcg_source_identity.vectors import verify_contract; verify_contract(derive)"

# Release/build metadata - see app/core/version.py (GET /version, GET
# /health, GET /admin/release-status) and the Makefile's prod-build target,
# which computes these from `git rev-parse --short HEAD`/a UTC timestamp/the
# repo-root VERSION file and passes them as --build-arg. Defaults here only
# matter for a manual `docker build` without those args (e.g. local testing).
ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown
ARG APP_VERSION=0.1.0
ENV GIT_COMMIT=${GIT_COMMIT}
ENV BUILD_TIME=${BUILD_TIME}
ENV APP_VERSION=${APP_VERSION}

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
