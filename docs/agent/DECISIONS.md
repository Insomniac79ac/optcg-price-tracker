# Durable Card Pirate decisions

Dates below are adoption/reaffirmation dates for this contract, not invented dates
of original implementation. Live rollout status belongs in
[CURRENT_STATE.yaml](CURRENT_STATE.yaml); authority belongs in
[AUTONOMY_POLICY.md](AUTONOMY_POLICY.md). Add a dated superseding decision when a
human authorizes a product/invariant change; retain the original rationale.

| Date (UTC) | Decision | Rationale |
| --- | --- | --- |
| 2026-10-04 | Staging-first, mission-level autonomous development. Agents decompose, implement, test, deliver and observe without step approvals. | Outcome boundaries and evidence provide control without prompt-by-prompt supervision. |
| 2026-10-04 | Production remains explicitly human-gated. | Staging authority must not silently expand to customer-facing production or shared resources. |
| 2026-10-04 | Fix forward bounded defects; quarantine isolated bad records. | Recoverable failures should not strand the whole mission; integrity hazards still stop affected execution. |
| 2026-10-04 | Apply GREEN/AMBER/RED by impact, using the highest applicable level. AMBER preflight is autonomous. | Overlapping descriptions must not allow a risky change to evade safeguards or create unnecessary human gates. |
| 2026-10-04 | Exact physical CardPrint identity and authoritative `release_product_id` govern mapping and price lineage. | Card-code prefixes and fuzzy similarity cannot distinguish release membership or physical print variants reliably. |
| 2026-10-04 | Ambiguous identity is never auto-approved; manual mappings and existing source identity guards remain authoritative. | Additional coverage cannot justify prices attached to the wrong physical card. |
| 2026-10-04 | Yuyu promotional prices remain internal provenance only; exclude public prices/history, Market Index and Market Value. Never substitute struck former prices. | Promotional evidence does not establish an eligible current regular price. |
| 2026-10-04 | Shared standard freshness target: 24 hours, dispatch due at 23 hours. Failure does not refresh success; no-listing does not refresh an old price. | Source-independent semantics distinguish successful availability checks from actual price evidence and capacity shortfalls. |
| 2026-10-04 | Market Value forward publication requires genuine completion receipts. | Publication must prove the intended snapshot completed, not infer completion from time or partial rows. |
| 2026-10-04 | No interpolation or fabricated history; September 27–28, 2026 remain intentional gaps. | Honest missing evidence preserves the meaning and auditability of published history. |
| 2026-10-04 | Source capacity must be measured from bounded natural operation, not assumed from configuration or synthetic tests. | Request cost, latency, denial rates and actual deadlines determine safe throughput. |
| 2026-10-04 | Mapping existence alone does not equal healthy operational coverage. | Admission, identity eligibility, actual collection, availability and timely evidence must be checked separately. |
| 2026-10-04 | Verify changing CLI/API behavior against current official documentation and installed interfaces. | Historical commands can target the wrong environment or have changed side effects. |
| 2026-10-04 | Keep this initial contract PR open for review; no application deployment or production access. | The operating model itself receives one initial review before future missions adopt it. |
