#!/bin/bash
# usage: run_suite.sh <repo> <port> <out-prefix> [delay]
REPO=$1 PORT=$2 OUT=$3 DELAY=${4:-0}
for i in $(seq 30); do docker exec s3-api-pg-$PORT pg_isready -U opcg >/dev/null 2>&1 && break; sleep 2; done
sleep 5
cd "$REPO/services/api"
{ echo "commit: $(git rev-parse --short HEAD)"; echo "postgres: 18 (localhost:$PORT), TEST_POSTGRES_URL set; DELAY_AFTER_COLLECTION=$DELAY"; } > "$OUT.txt"
PLUG=(); [ "$DELAY" != 0 ] && PLUG=(-p delay_after_collection)
TEST_POSTGRES_URL="postgresql+psycopg://opcg:${TEST_POSTGRES_PASSWORD:?TEST_POSTGRES_PASSWORD is required}@localhost:$PORT/opcg_test" DELAY_AFTER_COLLECTION=$DELAY \
PYTHONPATH=$REPO/packages/opcg_source_identity/src$([ "$DELAY" != 0 ] && echo :/workspaces/cp-cv1-s3/.s3-work/plugins) \
  python -m pytest -q -rs -p no:cacheprovider "${PLUG[@]}" --junitxml="$OUT.xml" tests >> "$OUT.log" 2>&1
echo "exit=$?" >> "$OUT.txt"
grep -E "passed|failed" "$OUT.log" | tail -1 >> "$OUT.txt"
grep -E "^(SKIPPED|FAILED|ERROR)" "$OUT.log" >> "$OUT.txt"
