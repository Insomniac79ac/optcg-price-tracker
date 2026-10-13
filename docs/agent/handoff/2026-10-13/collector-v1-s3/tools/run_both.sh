#!/bin/bash
S=/tmp/claude-1000/-workspaces-optcg-price-tracker/9188a7cc-e516-4c6f-99f3-be48efb6f257/scratchpad
run() { # repo out delay
  docker rm -f s3-api-pg-5544 >/dev/null 2>&1
  docker run -d --name s3-api-pg-5544 -e POSTGRES_USER=opcg -e POSTGRES_PASSWORD=opcg -e POSTGRES_DB=opcg_test -p 127.0.0.1:5544:5432 postgres:18 >/dev/null
  TEST_POSTGRES_HOST=localhost TEST_POSTGRES_PORT=5544 TEST_POSTGRES_USER=opcg TEST_POSTGRES_PASSWORD=opcg $S/run_suite.sh "$1" 5544 "$2" "$3"
}
run /workspaces/cp-cv1-s3 $S/suite-s3 65
run $S/staging-base $S/suite-staging 0
docker rm -f s3-api-pg-5544 >/dev/null
