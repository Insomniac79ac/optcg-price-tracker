# Daily Market Value pipeline (prepared, inactive)

The opt-in coordinator uses the existing snapshot writer, C1B0 receipt verifier,
Market Value forward publisher, and Card Pirate Index writer. Source collectors
remain separately scheduled. This change does not run the pipeline or change
Railway configuration. The existing 20:00 UTC schedule is the expected baseline
from [operations](operations.md#scheduled-index-jobs-railway-cron), not a newly
verified live setting.

Proposed replacement Railway start command for the existing
`market-index-snapshot` service, when activation is separately approved:

```sh
python -m app.market_index_daily_pipeline
```

The coordinator acquires its own job lock, runs the normal snapshot writer and
closes its session, then checks the committed receipt for the snapshot result's
UTC date in a fresh session. A shared `NOWAIT` lock on the released producer
row keeps a new snapshot from starting through both downstream attempts. A
failed snapshot, held producer, missing or invalid receipt blocks both writers.
An empty snapshot is an explicit no-op with no downstream publication.

After the gate, Market Value runs with the forward publisher's normal all-new
eligible-date selection (`--write` semantics), then CPI runs independently.
Each job retains its own lock, validation, transaction, and idempotency. If one
writer fails, the other is still attempted. Market Value excludes unpublished
receipt-less dates; CPI retains its existing archive semantics. The coordinator
prints one JSON record with each stage's status, dates, inserted count, and
failure reason. Exit 0 means success or an empty/no-op snapshot; exit 1 means
a failed gate or stage; exit 2 means a held job lock. A successful independent
stage remains visible in the report even when the overall exit is nonzero.

## Activation checklist (future operator action)

1. Review and merge the code PR, then confirm the deployed API image contains
   the coordinator and the C1B0 completion migration is already applied.
2. Check the live `market-index-snapshot` service's branch, start command,
   schedule, restart policy, and deployment triggers against the expected
   staging baseline. Ensure separately scheduled collectors still complete
   before the expected 20:00 UTC index run.
3. In a separately authorized Railway configuration change, replace only that
   service's start command with the command above. Observe its first scheduled
   run's JSON report, exit status, receipts, and downstream inserted counts.

Rollback: restore the prior start command shown in
[operations](operations.md#scheduled-index-jobs-railway-cron) in a separately
authorized Railway configuration change. No data rollback or replay is part of
this command rollback; investigate any failed stage using its report before
the next scheduled run. Do not manually trigger the pipeline as part of this
PR.
