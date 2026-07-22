"use client";

import Link from "next/link";
import { useState } from "react";

import { EmptyState } from "@/components/StateBlocks";
import { TableScrollContainer } from "@/components/ui/DataTableShell";
import { createCollectorNote, type GradingAnalyticsSubmission } from "@/lib/api";
import { cardDisplayName, formatDate, formatJPY, formatNumber, formatPercent } from "@/lib/format";

export type SubmissionColumn =
  | "company"
  | "status"
  | "final_grade"
  | "total_cost"
  | "raw_cost_basis"
  | "graded_value"
  | "roi"
  | "roi_pct"
  | "submitted_at"
  | "expected_return_date"
  | "received_at"
  | "days_in_grading"
  | "tracking_number"
  | "overdue"
  | "notes";

const COLUMN_LABELS: Record<SubmissionColumn, string> = {
  company: "Company",
  status: "Status",
  final_grade: "Grade",
  total_cost: "Total cost",
  raw_cost_basis: "Raw cost basis",
  graded_value: "Graded value",
  roi: "ROI",
  roi_pct: "ROI %",
  submitted_at: "Submitted",
  expected_return_date: "Expected return",
  received_at: "Received",
  days_in_grading: "Days in grading",
  tracking_number: "Tracking #",
  overdue: "Overdue",
  notes: "Notes",
};

function renderCell(s: GradingAnalyticsSubmission, column: SubmissionColumn) {
  switch (column) {
    case "company":
      return <span className="text-neutral-300">{s.grading_company}</span>;
    case "status":
      return <span className="capitalize text-neutral-300">{s.submission_status.replace("_", " ")}</span>;
    case "final_grade":
      return s.final_grade ?? "not available";
    case "total_cost":
      return formatJPY(s.total_cost_jpy);
    case "raw_cost_basis":
      return formatJPY(s.raw_cost_basis_jpy);
    case "graded_value":
      return formatJPY(s.graded_value_jpy);
    case "roi":
      return s.roi_jpy === null ? (
        "not available"
      ) : (
        <span className={s.roi_jpy >= 0 ? "text-emerald-400" : "text-rose-400"}>{formatJPY(s.roi_jpy)}</span>
      );
    case "roi_pct":
      return formatPercent(s.roi_pct);
    case "submitted_at":
      return formatDate(s.submitted_at);
    case "expected_return_date":
      return formatDate(s.expected_return_date);
    case "received_at":
      return formatDate(s.received_at);
    case "days_in_grading":
      return s.days_in_grading === null ? "not available" : `${formatNumber(s.days_in_grading)}d`;
    case "tracking_number":
      return s.tracking_number ?? "not available";
    case "overdue":
      return (
        <span className={s.flags.overdue ? "text-amber-400" : "text-neutral-600"}>
          {s.flags.overdue ? "Overdue" : "—"}
        </span>
      );
    case "notes":
      return s.notes ?? "not available";
    default:
      return null;
  }
}

function NoteForm({
  submission,
  onDone,
}: {
  submission: GradingAnalyticsSubmission;
  onDone: () => void;
}) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!text.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await createCollectorNote({
        note_type: "grading",
        body: text.trim(),
        card_id: submission.card_id,
        title: `Grading note: ${submission.card_code}`,
      });
      setText("");
      onDone();
    } catch {
      setError("Failed to save note.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-1 flex items-center gap-1">
      <input
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Add a note…"
        className="w-40 rounded border border-neutral-700 bg-neutral-950 px-1.5 py-0.5 text-[11px] text-neutral-200 placeholder:text-neutral-600"
      />
      <button
        type="button"
        onClick={submit}
        disabled={saving || !text.trim()}
        className="rounded border border-neutral-700 px-1.5 py-0.5 text-[11px] text-neutral-300 hover:text-neutral-100 disabled:opacity-50"
      >
        Save
      </button>
      {error && <span className="text-[11px] text-rose-400">{error}</span>}
    </div>
  );
}

/** Dense per-submission table shared across the grading analytics page's ROI
 * sub-sections, pending sub-sections, and full submissions table - columns
 * shown differ per section (see `columns`); `actions` (Card/Grading links
 * plus a note form) is only turned on for the main submissions table. */
export function GradingSubmissionTable({
  submissions,
  columns,
  actions = false,
  onSubmissionUpdated,
}: {
  submissions: GradingAnalyticsSubmission[];
  columns: SubmissionColumn[];
  actions?: boolean;
  onSubmissionUpdated?: () => void;
}) {
  const [notingId, setNotingId] = useState<number | null>(null);

  if (submissions.length === 0) {
    return <EmptyState variant="inline">No data available.</EmptyState>;
  }

  return (
    <TableScrollContainer showScrollHint={false}>
      <table className="w-full min-w-[900px] border-collapse text-xs">
        <thead className="sticky-thead">
          <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
            <th className="sticky-col-first px-3 py-2 font-medium">Card</th>
            {columns.map((column) => (
              <th key={column} className="px-3 py-2 font-medium">
                {COLUMN_LABELS[column]}
              </th>
            ))}
            <th className="px-3 py-2 font-medium">Links</th>
          </tr>
        </thead>
        <tbody>
          {submissions.map((s) => (
            <tr key={s.grading_submission_id} className="border-b border-neutral-900 align-top last:border-0">
              <td className="sticky-col-first px-3 py-2 text-neutral-200">
                <Link href={`/cards/${s.card_id}`} className="text-sky-400 hover:text-sky-300">
                  {s.card_code}
                </Link>
                <div className="text-neutral-400">{cardDisplayName(s)}</div>
              </td>
              {columns.map((column) => (
                <td key={column} className="px-3 py-2 text-neutral-300">
                  {renderCell(s, column)}
                </td>
              ))}
              <td className="px-3 py-2">
                <div className="flex flex-col gap-1">
                  <div className="flex flex-wrap gap-2">
                    <Link href={`/cards/${s.card_id}`} className="text-sky-400 hover:text-sky-300">
                      Card
                    </Link>
                    <Link href="/grading" className="text-sky-400 hover:text-sky-300">
                      Grading
                    </Link>
                  </div>
                  {actions && (
                    <>
                      <button
                        type="button"
                        onClick={() =>
                          setNotingId(notingId === s.grading_submission_id ? null : s.grading_submission_id)
                        }
                        className="w-fit rounded border border-neutral-700 px-1.5 py-0.5 text-[11px] text-neutral-300 hover:text-neutral-100"
                      >
                        + Note
                      </button>
                      {notingId === s.grading_submission_id && (
                        <NoteForm
                          submission={s}
                          onDone={() => {
                            setNotingId(null);
                            onSubmissionUpdated?.();
                          }}
                        />
                      )}
                    </>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScrollContainer>
  );
}
