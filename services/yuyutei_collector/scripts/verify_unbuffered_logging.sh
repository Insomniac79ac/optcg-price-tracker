#!/usr/bin/env bash
# Container-level proof that the collector image streams stdout/stderr
# immediately instead of block-buffering until process exit - see
# deploy/railway/yuyutei-collector.Dockerfile's PYTHONUNBUFFERED=1.
#
# Makes no network request of any kind (no yuyu-tei.jp, no database) - every
# check here runs a trivial inline `python -c` script inside the built
# image. Build the image first:
#
#   docker build -f deploy/railway/yuyutei-collector.Dockerfile \
#     -t opcg-yuyutei-collector-test .
#
# then run this script from the repo root:
#
#   services/yuyutei_collector/scripts/verify_unbuffered_logging.sh
#
# Test A proves the image's own default (PYTHONUNBUFFERED=1 baked in via
# ENV) streams a line before a subsequent sleep completes. Test B is a
# negative control - explicitly unsetting PYTHONUNBUFFERED for that one
# container proves the same script WOULD buffer without the fix, so Test A
# passing is evidence of the fix actually doing something, not a
# vacuously-true check. Test C confirms normal (non-zero, argparse) exit
# codes are unaffected by this change.
set -uo pipefail

IMAGE="${IMAGE:-opcg-yuyutei-collector-test}"
FAILED=0

run_and_check() {
  local label="$1"; shift
  local expect_early="$1"; shift
  local cname="unbuf-check-$$-$RANDOM"

  docker run -d --name "$cname" "$@" "$IMAGE" \
    python -c "
import sys, time
print('STDOUT_EARLY_LINE', flush=False)
print('STDERR_EARLY_LINE', file=sys.stderr, flush=False)
time.sleep(4)
print('STDOUT_LATE_LINE')
" >/dev/null

  sleep 1.5
  early_logs=$(docker logs "$cname" 2>&1 || true)
  early_seen="no"
  if echo "$early_logs" | grep -q "STDOUT_EARLY_LINE" && echo "$early_logs" | grep -q "STDERR_EARLY_LINE"; then
    early_seen="yes"
  fi

  docker wait "$cname" >/tmp/verify_unbuffered_exit_"$cname".txt
  exit_code=$(cat /tmp/verify_unbuffered_exit_"$cname".txt)
  final_logs=$(docker logs "$cname" 2>&1 || true)

  echo "=== $label ==="
  echo "  early (t=1.5s) STDOUT+STDERR visible: $early_seen  (expected: $expect_early)"
  echo "  final logs contain STDOUT_LATE_LINE: $(echo "$final_logs" | grep -q STDOUT_LATE_LINE && echo yes || echo no)"
  echo "  exit code: $exit_code (expected: 0)"

  docker rm -f "$cname" >/dev/null 2>&1 || true
  rm -f /tmp/verify_unbuffered_exit_"$cname".txt

  if [ "$early_seen" != "$expect_early" ] || [ "$exit_code" != "0" ]; then
    echo "  !! MISMATCH for $label"
    FAILED=1
  fi
}

echo "--- Test A: image default (PYTHONUNBUFFERED=1 baked in) ---"
run_and_check "image default" "yes"

echo
echo "--- Test B: negative control, explicitly unset PYTHONUNBUFFERED ---"
run_and_check "PYTHONUNBUFFERED unset" "no" -e PYTHONUNBUFFERED=

echo
echo "--- Test C: normal (argparse) exit code is unchanged ---"
cname="unbuf-argtest-$$"
set +e
docker run --rm --name "$cname" "$IMAGE" python -m yuyutei_collector.collect >/tmp/verify_unbuffered_argtest.txt 2>&1
code=$?
set -e
echo "  exit code for missing required args: $code (argparse expected: 2)"
if [ "$code" != "2" ]; then
  echo "  !! MISMATCH: expected argparse exit code 2"
  FAILED=1
fi
rm -f /tmp/verify_unbuffered_argtest.txt

echo
if [ "$FAILED" -ne 0 ]; then
  echo "FAILED - see MISMATCH lines above"
  exit 1
fi
echo "ALL CHECKS PASSED"
