# D9 F1 rule: yuyutei collector rollout

PR #171 (the Yuyu-Tei unique listing-kind rule) carried `hold-for-owner` and was merged by hand on
2026-10-18 at 14:36Z, after the owner allowed the yuyutei redeploy. A hand merge only runs
`Verify staging merge`; the collector rollout runs only inside `staging-automerge`. So staging
moved to the new resolver for the API while the nine yuyutei shards kept the PR #103 images
(a504e476), and verification failed with "Yuyu deployed source/schedule changed".

The rule is inert in that state: the shards keep writing the same ambiguous proposals and the API
only reads proposals or revalidates an approval, which fails closed on any digest mismatch.

This follow-up carries the same mission scope without the hold, so the normal delivery path
releases the nine yuyutei shards one at a time (never 02:00-06:00 UTC), restores any failed shard
to its recovery deployment, and re-verifies staging. snkrdunk is not redeployed.

For later held PRs that need a collector rollout: the owner removes `hold-for-owner` before the PR
is marked ready, or the rollout needs a separate unheld delivery like this one.
