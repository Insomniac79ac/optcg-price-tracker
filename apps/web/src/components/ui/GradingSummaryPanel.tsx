import Link from "next/link";

import { GradingStatusBadge } from "@/components/GradingStatusBadge";
import { EmptyState } from "@/components/StateBlocks";
import type { GradingSubmission } from "@/lib/api";
import { formatDate, formatJpy } from "@/lib/format";

/** Display-only ROI ratio (not a new analytics formula - the same
 * graded_value-minus-cost-over-cost ratio /analytics/grading already
 * computes server-side for its own listing) - only computed here when both
 * inputs are present, otherwise left as "not available". */
function roiPct(gradedValueJpy: number | null, totalCostJpy: number | null): number | null {
  if (gradedValueJpy === null || totalCostJpy === null || totalCostJpy === 0) return null;
  return ((gradedValueJpy - totalCostJpy) / totalCostJpy) * 100;
}

/** Card-detail grading panel - takes the grading submissions already
 * embedded on this card's collection items (CollectionItem.grading_
 * submissions), so no extra fetch is needed. */
export function GradingSummaryPanel({ submissions }: { submissions: GradingSubmission[] }) {
  return (
    <div className="panel p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-text-primary">Grading</h2>
        <Link href="/grading" className="text-xs text-sky-400 hover:text-sky-300">
          View grading →
        </Link>
      </div>

      {submissions.length === 0 ? (
        <EmptyState variant="inline">No grading submissions.</EmptyState>
      ) : (
        <div className="space-y-3">
          {submissions.map((s) => {
            const roi = roiPct(s.graded_value_jpy, s.total_cost_jpy);
            return (
              <div key={s.id} className="rounded-control border border-border-default bg-bg-page p-3">
                <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium text-text-primary">{s.grading_company}</span>
                  <GradingStatusBadge status={s.submission_status} />
                  {s.final_grade && (
                    <span className="badge bg-violet-500/15 text-violet-300 ring-1 ring-inset ring-violet-500/30">
                      grade {s.final_grade}
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-text-secondary">
                      Graded value
                    </div>
                    <div className="mono tabular text-sm text-text-primary">
                      {formatJpy(s.graded_value_jpy)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-text-secondary">
                      Total cost
                    </div>
                    <div className="mono tabular text-sm text-text-primary">
                      {formatJpy(s.total_cost_jpy)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-text-secondary">ROI</div>
                    <div
                      className={`mono tabular text-sm ${
                        roi === null
                          ? "text-text-faint"
                          : roi >= 0
                            ? "price-positive"
                            : "price-negative"
                      }`}
                    >
                      {roi === null ? "not available" : `${roi >= 0 ? "+" : ""}${roi.toFixed(1)}%`}
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-text-secondary">
                      Cert number
                    </div>
                    <div className="mono text-sm text-text-secondary">{s.cert_number ?? "not available"}</div>
                  </div>
                </div>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-text-muted">
                  <span>Submitted: {formatDate(s.submitted_at)}</span>
                  <span>Expected return: {formatDate(s.expected_return_date)}</span>
                  <span>Received: {formatDate(s.received_at)}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
