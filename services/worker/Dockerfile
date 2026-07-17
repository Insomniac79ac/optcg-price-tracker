FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Release/build metadata, for correlating worker/beat logs with a specific
# release - see services/api/Dockerfile's identical block and the Makefile's
# prod-build target for how these get computed and passed in.
ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown
ARG APP_VERSION=0.1.0
ENV GIT_COMMIT=${GIT_COMMIT}
ENV BUILD_TIME=${BUILD_TIME}
ENV APP_VERSION=${APP_VERSION}

# Default to a long-running Celery worker process, not a one-off job - both
# docker-compose.yml and docker-compose.prod.yml override this explicitly
# per service anyway (`celery -A worker.celery_app worker --loglevel=info`
# for worker, `... beat --loglevel=info` for beat, since this one Dockerfile
# backs both), but a container started without an explicit command (e.g. a
# PaaS that doesn't let you override CMD) should come up as a production
# worker, not run refresh_prices once and exit.
CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=info"]
