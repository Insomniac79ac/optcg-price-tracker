# Bounded Yuyu admission for staging capacity work

The nine Yuyu consumers share the source budget row lock. Their natural 72-hour peak was four active executions. Claim admission now allows at most four live Yuyu product claims across every work kind and claimant. Expired claims settle conservatively before counting; completed or failed claims release their slot. The source budget, reservations, pacing, modulo-nine routing, exact identity and 23h/24h targets are unchanged.

The ordinary 30-minute cadence remains installed during this release. The component verifier can recognise an explicitly declared ten-minute profile (`shard,shard+10,...,shard+50`) only across all nine shards, while keeping max16 and every identity/denial/ownership check. Schedule recognition is not capacity proof or activation.

See `evidence/yuyu-bounded-admission-preflight-20261007.json` for measured before state, impact, forecast limits and rollback. No expanded volume is admitted by this code release. A later staging-only cron change requires a fresh guarded preflight and natural peak evidence. Restore original cron before removing the claim cap. Keep the existing dictionary readers and e8 dependency protections during rollback.
