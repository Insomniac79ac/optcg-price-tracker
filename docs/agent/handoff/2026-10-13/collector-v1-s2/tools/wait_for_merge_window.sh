#!/bin/bash
# Read-only watcher for the S2 (#114) merge preconditions. Checks every 15 minutes,
# for at most 18 hours; triggers nothing. Exit 0 = all conditions met, 3 = timeout.
# Conditions: fonts PR #117 merged and its CI/delivery run completed green; capacity
# session-12 handoff (#118) merged; no CI run in progress or queued; no other non-draft
# open PR to staging with auto-merge armed; 06:00-23:00 UTC and not 19:30-20:30 UTC.
REPO=Insomniac79ac/optcg-price-tracker
deadline=$(( $(date +%s) + 18*3600 ))
check() {
  local now hm f117 f118 run117 busy armed
  hm=$(date -u +%H%M)
  f117=$(gh pr view 117 -R $REPO --json state,mergeCommit --jq '"\(.state) \(.mergeCommit.oid)"')
  f118=$(gh pr view 118 -R $REPO --json state --jq .state)
  run117=$(gh run list -R $REPO --branch fix/self-host-fonts --workflow CI --limit 1 --json status,conclusion --jq '.[0]|"\(.status) \(.conclusion)"')
  busy=$(gh run list -R $REPO --limit 30 --json status --jq '[.[]|select(.status!="completed")]|length')
  armed=$(gh pr list -R $REPO --base staging --state open --json number,isDraft,autoMergeRequest --jq '[.[]|select(.isDraft==false and .autoMergeRequest!=null and .number!=114)]|length')
  echo "$(date -u +%FT%TZ) pr117=[$f117] run117=[$run117] pr118=$f118 runs_active=$busy armed_prs=$armed hhmm=$hm"
  [[ $f117 == MERGED* ]] && [[ $run117 == "completed success" ]] && [[ $f118 == MERGED ]] \
    && [[ $busy == 0 ]] && [[ $armed == 0 ]] \
    && (( 10#$hm >= 600 && 10#$hm < 2300 )) && ! (( 10#$hm >= 1930 && 10#$hm < 2030 ))
}
while :; do
  if check; then echo READY; exit 0; fi
  (( $(date +%s) + 900 > deadline )) && { echo TIMEOUT; exit 3; }
  sleep 900
done
