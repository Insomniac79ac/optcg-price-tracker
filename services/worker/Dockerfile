FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default to a long-running Celery worker process, not a one-off job - both
# docker-compose.yml and docker-compose.prod.yml override this explicitly
# per service anyway (`celery -A worker.celery_app worker --loglevel=info`
# for worker, `... beat --loglevel=info` for beat, since this one Dockerfile
# backs both), but a container started without an explicit command (e.g. a
# PaaS that doesn't let you override CMD) should come up as a production
# worker, not run refresh_prices once and exit.
CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=info"]
