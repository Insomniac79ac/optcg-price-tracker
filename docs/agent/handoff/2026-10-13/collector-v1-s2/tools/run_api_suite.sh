#!/bin/bash
# usage: run_api_suite.sh <repo> <out-prefix>
# Fresh disposable Postgres 18 on 127.0.0.1:5544 (tests hardcode 5544), full
# API suite with -rs and JUnit XML. The password comes from the environment.
set -u
: "${LOCAL_TEST_PG_PASSWORD:?set LOCAL_TEST_PG_PASSWORD for the disposable local test Postgres}"
REPO=$1 OUT=$2 NAME=s2-api-pg-5544
docker rm -f $NAME >/dev/null 2>&1
docker run -d --name $NAME -e POSTGRES_USER=opcg -e POSTGRES_PASSWORD="$LOCAL_TEST_PG_PASSWORD" -e POSTGRES_DB=opcg_test -p 127.0.0.1:5544:5432 postgres:18 >/dev/null
for i in $(seq 30); do docker exec $NAME pg_isready -U opcg >/dev/null 2>&1 && break; sleep 2; done; sleep 5
cd "$REPO/services/api"
{ echo "commit: $(git rev-parse --short HEAD)"; echo "postgres: 18 (localhost:5544), TEST_POSTGRES_URL set"; } > "$OUT.txt"
TEST_POSTGRES_URL="postgresql+psycopg://opcg:$LOCAL_TEST_PG_PASSWORD@localhost:5544/opcg_test" \
TEST_POSTGRES_HOST=localhost TEST_POSTGRES_PORT=5544 TEST_POSTGRES_USER=opcg TEST_POSTGRES_PASSWORD="$LOCAL_TEST_PG_PASSWORD" \
PYTHONPATH=$REPO/packages/opcg_source_identity/src \
  ~/.venvs/cardpirate/bin/python -m pytest -q -rs -p no:cacheprovider --junitxml="$OUT.xml" tests > "$OUT.log" 2>&1
echo "exit=$?" >> "$OUT.txt"
grep -E "passed|failed" "$OUT.log" | tail -1 >> "$OUT.txt"
grep -E "^(SKIPPED|FAILED|ERROR)" "$OUT.log" >> "$OUT.txt"
docker rm -f $NAME >/dev/null
