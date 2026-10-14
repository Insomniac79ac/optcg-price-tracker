#!/bin/bash
# usage: run_suite.sh <repo> <out-prefix>; needs TEST_POSTGRES_PASSWORD. Postgres 18 on localhost:5545.
# Excludes test_raw_dictionary_storage_postgres.py: it hardcodes localhost:5544, which another
# session's container (lockpg) holds; running it would write a schema into that database.
REPO=$1 OUT=$2 PORT=5545
cd "$REPO/services/api"
{ echo "commit: $(git rev-parse --short HEAD)"; echo "postgres: $(docker exec cv1-s4-pg18 psql -U opcg -d opcg -tAc 'show server_version') (localhost:$PORT); TEST_POSTGRES_URL/HOST/PORT/USER/PASSWORD set"; echo "ignored: tests/test_raw_dictionary_storage_postgres.py (hardcoded :5544, held by another session)"; } > "$OUT.txt"
TEST_POSTGRES_URL="postgresql+psycopg://opcg:${TEST_POSTGRES_PASSWORD:?required}@localhost:$PORT/opcg_test" \
TEST_POSTGRES_HOST=localhost TEST_POSTGRES_PORT=$PORT TEST_POSTGRES_USER=opcg \
PYTHONPATH=$REPO/packages/opcg_source_identity/src \
  ~/.venvs/cardpirate/bin/python -m pytest -q -rs -p no:cacheprovider -p no:warnings \
  --ignore=tests/test_raw_dictionary_storage_postgres.py --junitxml="$OUT.xml" tests > "$OUT.log" 2>&1
echo "exit=$?" >> "$OUT.txt"
grep -E "passed|failed" "$OUT.log" | tail -1 >> "$OUT.txt"
grep -E "^(SKIPPED|FAILED|ERROR)" "$OUT.log" >> "$OUT.txt"
sed -i "s/${TEST_POSTGRES_PASSWORD}/***/g" "$OUT.txt" "$OUT.log" "$OUT.xml"
