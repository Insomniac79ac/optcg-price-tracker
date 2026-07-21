"use client";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import {
  AdminAuthRequiredError,
  IMPORT_TYPES,
  type ImportPreviewRow,
  type ImportRowIssue,
  type ImportTemplate,
  type ImportType,
  type ImportValidationReport,
  type ImportValidationResponse,
  downloadImportTemplate,
  fetchImportTemplates,
  fetchImportValidationReport,
  fetchImportValidationReports,
  getAdminToken,
  validateImportCsv,
} from "@/lib/api";

const IMPORT_TYPE_LABELS: Record<ImportType, string> = {
  card_catalog: "Card Catalog",
  source_mappings: "Source Mappings",
  snkrdunk_candidates: "SNKRDUNK Candidates",
  collection: "Collection",
  wishlist: "Wishlist",
};

export default function AdminImportValidationPage() {
  const [unauthorized, setUnauthorized] = useState(false);

  useEffect(() => {
    setUnauthorized(!getAdminToken());
  }, []);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-6xl px-4 py-6">
        <div className="mb-1 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">Import Validation</h1>
          <AdminLogoutButton />
        </div>
        <p className="mb-6 text-xs text-neutral-500">
          Validate catalog, mapping, candidate, collection, and wishlist CSVs before writing data.
        </p>

        {unauthorized && <AdminAuthGate onTokenSaved={() => setUnauthorized(false)} />}

        {!unauthorized && (
          <div className="flex flex-col gap-6">
            <TemplatesSection />
            <ValidatorAndReportsSection />

            <div className="flex flex-wrap gap-3 text-xs">
              <Link
                href="/admin/cards"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Card catalog
              </Link>
              <Link
                href="/admin/card-audit"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Card audit
              </Link>
              <Link
                href="/admin/source-mapping-quality"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Source mapping quality
              </Link>
              <Link
                href="/admin/backup"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Backup
              </Link>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <h2 className="mb-3 text-sm font-semibold text-neutral-200">{title}</h2>
      {children}
    </section>
  );
}

// --- Templates ------------------------------------------------------------

function TemplatesSection() {
  const [templates, setTemplates] = useState<ImportTemplate[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloadingType, setDownloadingType] = useState<string | null>(null);

  useEffect(() => {
    fetchImportTemplates()
      .then((data) => setTemplates(data.templates))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load templates."));
  }, []);

  async function handleDownload(templateType: ImportType) {
    setDownloadingType(templateType);
    setError(null);
    try {
      await downloadImportTemplate(templateType);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download template.");
    } finally {
      setDownloadingType(null);
    }
  }

  return (
    <Section title="Download templates">
      {error && (
        <div className="mb-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {error}
        </div>
      )}

      {!templates && !error && <p className="text-xs text-neutral-500">Loading templates…</p>}

      {templates && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {templates.map((template) => (
            <div
              key={template.template_type}
              className="flex flex-col justify-between rounded border border-neutral-800 bg-neutral-950 p-3"
            >
              <div>
                <div className="text-sm font-medium text-neutral-100">
                  {IMPORT_TYPE_LABELS[template.template_type] ?? template.template_type}
                </div>
                <p className="mt-1 text-xs text-neutral-500">{template.description}</p>

                <div className="mt-2 text-[11px] text-neutral-500">
                  <span className="font-medium text-neutral-400">Required:</span>{" "}
                  {template.required_columns.join(", ")}
                </div>

                {template.optional_columns.length > 0 && (
                  <details className="mt-1 text-[11px] text-neutral-500">
                    <summary className="cursor-pointer select-none hover:text-neutral-300">
                      Optional columns ({template.optional_columns.length})
                    </summary>
                    <p className="mt-1">{template.optional_columns.join(", ")}</p>
                  </details>
                )}
              </div>

              <button
                type="button"
                onClick={() => handleDownload(template.template_type)}
                disabled={downloadingType === template.template_type}
                className="mt-3 rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-200 hover:text-neutral-100 disabled:opacity-50"
              >
                {downloadingType === template.template_type ? "Downloading…" : "Download CSV"}
              </button>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

// --- Validator + report history --------------------------------------------

function ValidatorAndReportsSection() {
  const [importType, setImportType] = useState<ImportType>("card_catalog");
  const [file, setFile] = useState<File | null>(null);
  const [strict, setStrict] = useState(false);
  const [maxPreviewRows, setMaxPreviewRows] = useState(100);
  const [userId, setUserId] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportValidationResponse | null>(null);

  const [reports, setReports] = useState<ImportValidationReport[] | null>(null);
  const [reportsError, setReportsError] = useState<string | null>(null);
  const [expandedReportId, setExpandedReportId] = useState<number | null>(null);
  const [expandedReport, setExpandedReport] = useState<ImportValidationResponse | null>(null);
  const [expandedReportError, setExpandedReportError] = useState<string | null>(null);

  const loadReports = useCallback(() => {
    fetchImportValidationReports({ limit: 25 })
      .then((data) => setReports(data.reports))
      .catch((err) =>
        setReportsError(err instanceof Error ? err.message : "Failed to load report history."),
      );
  }, []);

  useEffect(() => {
    loadReports();
  }, [loadReports]);

  async function handleValidate() {
    if (!file) {
      setError("Choose a CSV file first.");
      return;
    }
    setError(null);
    setPending(true);
    try {
      const parsedUserId = userId.trim() === "" ? undefined : Number(userId);
      const data = await validateImportCsv(importType, file, {
        strict,
        maxPreviewRows,
        userId: parsedUserId,
      });
      setResult(data);
      loadReports();
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) {
        setError("Admin token required.");
      } else {
        setError(err instanceof Error ? err.message : "Failed to validate CSV.");
      }
    } finally {
      setPending(false);
    }
  }

  async function handleExpandReport(id: number) {
    if (expandedReportId === id) {
      setExpandedReportId(null);
      setExpandedReport(null);
      return;
    }
    setExpandedReportId(id);
    setExpandedReport(null);
    setExpandedReportError(null);
    try {
      const detail = await fetchImportValidationReport(id);
      setExpandedReport(detail.report_payload_json);
    } catch (err) {
      setExpandedReportError(
        err instanceof Error ? err.message : "Failed to load report detail.",
      );
    }
  }

  return (
    <>
      <Section title="Validate a CSV upload">
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-neutral-500">
            Import type
            <select
              value={importType}
              onChange={(e) => {
                setImportType(e.target.value as ImportType);
                setResult(null);
              }}
              className="ml-2 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
            >
              {IMPORT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {IMPORT_TYPE_LABELS[t]}
                </option>
              ))}
            </select>
          </label>

          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setResult(null);
              setError(null);
            }}
            className="block text-xs text-neutral-300 file:mr-2 file:rounded file:border-0 file:bg-neutral-800 file:px-2 file:py-1 file:text-xs file:font-medium file:text-neutral-200 hover:file:bg-neutral-700"
          />

          <label className="flex items-center gap-1.5 rounded border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-xs text-neutral-400">
            <input
              type="checkbox"
              checked={strict}
              onChange={(e) => setStrict(e.target.checked)}
              className="rounded border-neutral-700 bg-neutral-950"
            />
            Strict mode
          </label>

          <label className="text-xs text-neutral-500">
            Max preview rows
            <input
              type="number"
              min={1}
              max={1000}
              value={maxPreviewRows}
              onChange={(e) => setMaxPreviewRows(Number(e.target.value) || 100)}
              className="ml-2 w-20 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
            />
          </label>

          <label className="text-xs text-neutral-500">
            User ID (collection/wishlist)
            <input
              type="number"
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              placeholder="optional"
              className="ml-2 w-24 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-700"
            />
          </label>

          <button
            type="button"
            onClick={handleValidate}
            disabled={pending || !file}
            className="rounded bg-neutral-100 px-3 py-1.5 text-xs font-medium text-neutral-900 hover:bg-white disabled:opacity-50"
          >
            {pending ? "Validating…" : "Validate"}
          </button>
        </div>

        {error && (
          <div className="mt-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
            {error}
          </div>
        )}

        {result && (
          <div className="mt-4">
            <ValidationResultView result={result} />
          </div>
        )}
      </Section>

      <Section title="Validation report history">
        {reportsError && (
          <div className="mb-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
            {reportsError}
          </div>
        )}

        {!reports && !reportsError && <p className="text-xs text-neutral-500">Loading report history…</p>}

        {reports && reports.length === 0 && (
          <p className="text-xs text-neutral-500">No import validation reports yet.</p>
        )}

        {reports && reports.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-neutral-800">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wide text-neutral-500">
                  <th className="px-3 py-2 font-medium">Created</th>
                  <th className="px-3 py-2 font-medium">Type</th>
                  <th className="px-3 py-2 font-medium">Filename</th>
                  <th className="px-3 py-2 font-medium">Valid</th>
                  <th className="px-3 py-2 font-medium">Total</th>
                  <th className="px-3 py-2 font-medium">Errors</th>
                  <th className="px-3 py-2 font-medium">Warnings</th>
                  <th className="px-3 py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {reports.map((report) => (
                  <Fragment key={report.id}>
                    <tr
                      className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                    >
                      <td className="px-3 py-2 text-xs text-neutral-400">{report.created_at}</td>
                      <td className="px-3 py-2 text-xs text-neutral-300">{report.import_type}</td>
                      <td className="px-3 py-2 text-xs text-neutral-400">{report.filename ?? "—"}</td>
                      <td className="px-3 py-2">
                        <StatusBadge valid={report.valid} />
                      </td>
                      <td className="px-3 py-2 text-xs text-neutral-300">{report.total_rows}</td>
                      <td className="px-3 py-2 text-xs text-neutral-300">{report.error_rows}</td>
                      <td className="px-3 py-2 text-xs text-neutral-300">{report.warning_rows}</td>
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          onClick={() => handleExpandReport(report.id)}
                          className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
                        >
                          {expandedReportId === report.id ? "Hide" : "Open"}
                        </button>
                      </td>
                    </tr>
                    {expandedReportId === report.id && (
                      <tr key={`${report.id}-detail`} className="border-b border-neutral-900 last:border-0">
                        <td colSpan={8} className="bg-neutral-950/60 px-3 py-3">
                          {expandedReportError && (
                            <div className="rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
                              {expandedReportError}
                            </div>
                          )}
                          {!expandedReport && !expandedReportError && (
                            <p className="text-xs text-neutral-500">Loading report…</p>
                          )}
                          {expandedReport && <ValidationResultView result={expandedReport} />}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </>
  );
}

// --- Shared result renderer (live validation or a fetched report) ---------

function ValidationResultView({ result }: { result: ImportValidationResponse }) {
  const summary = result.summary;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge valid={result.valid} />
        <span className="text-xs text-neutral-500">import_type: {result.import_type}</span>
      </div>

      <div className="flex flex-wrap gap-2 text-xs">
        <StatChip label="Total rows" value={summary.total_rows} />
        <StatChip label="Valid rows" value={summary.valid_rows} />
        <StatChip label="Error rows" value={summary.error_rows} tone="rose" />
        <StatChip label="Warning rows" value={summary.warning_rows} tone="amber" />
        <StatChip label="Duplicate rows" value={summary.duplicate_rows} />
        <StatChip label="Would create" value={summary.would_create} tone="emerald" />
        <StatChip label="Would update" value={summary.would_update} tone="sky" />
        <StatChip label="Would skip" value={summary.would_skip} />
      </div>

      <ColumnsView columns={result.columns} />

      <IssueTable label="Errors" issues={result.errors} tone="rose" />
      <IssueTable label="Warnings" issues={result.warnings} tone="amber" />
      <PreviewTable rows={result.preview} />
    </div>
  );
}

function ColumnsView({ columns }: { columns: ImportValidationResponse["columns"] }) {
  return (
    <div className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
      <ChipList label="Required columns" items={columns.required_columns} />
      <ChipList label="Received columns" items={columns.received_columns} />
      <ChipList label="Missing required columns" items={columns.missing_required_columns} tone="rose" />
      <ChipList label="Unknown columns" items={columns.unknown_columns} tone="amber" />
    </div>
  );
}

function ChipList({
  label,
  items,
  tone,
}: {
  label: string;
  items: string[];
  tone?: "rose" | "amber";
}) {
  const toneClass =
    tone === "rose"
      ? "border-rose-900/50 bg-rose-950/20 text-rose-300"
      : tone === "amber"
        ? "border-amber-900/50 bg-amber-950/20 text-amber-200"
        : "border-neutral-800 bg-neutral-950 text-neutral-300";
  return (
    <div>
      <div className="mb-1 text-[11px] uppercase tracking-wide text-neutral-500">{label}</div>
      {items.length === 0 ? (
        <span className="text-neutral-600">—</span>
      ) : (
        <div className="flex flex-wrap gap-1">
          {items.map((item) => (
            <span key={item} className={`rounded border px-1.5 py-0.5 font-mono ${toneClass}`}>
              {item}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function IssueTable({
  label,
  issues,
  tone,
}: {
  label: string;
  issues: ImportRowIssue[];
  tone: "rose" | "amber";
}) {
  if (issues.length === 0) return null;
  const headerToneClass = tone === "rose" ? "text-rose-300" : "text-amber-200";
  return (
    <div>
      <div className={`mb-1 text-[11px] uppercase tracking-wide ${headerToneClass}`}>
        {label} ({issues.length})
      </div>
      <div className="overflow-x-auto rounded-lg border border-neutral-800">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="border-b border-neutral-800 bg-neutral-900 text-left uppercase tracking-wide text-neutral-500">
              <th className="px-2 py-1.5 font-medium">Row</th>
              <th className="px-2 py-1.5 font-medium">Field</th>
              <th className="px-2 py-1.5 font-medium">Value</th>
              <th className="px-2 py-1.5 font-medium">Code</th>
              <th className="px-2 py-1.5 font-medium">Message</th>
            </tr>
          </thead>
          <tbody>
            {issues.map((issue, idx) => (
              <tr key={idx} className="border-b border-neutral-900 last:border-0">
                <td className="px-2 py-1.5 text-neutral-400">{issue.row_number}</td>
                <td className="px-2 py-1.5 font-mono text-neutral-400">{issue.field ?? "—"}</td>
                <td className="px-2 py-1.5 font-mono text-neutral-400">
                  {issue.value === null || issue.value === undefined ? "—" : String(issue.value)}
                </td>
                <td className="px-2 py-1.5 font-mono text-neutral-300">{issue.code}</td>
                <td className="px-2 py-1.5 text-neutral-300">{issue.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const PREVIEW_ACTION_TONE: Record<string, string> = {
  would_create: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  would_update: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  would_skip: "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30",
  invalid: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
};

function PreviewTable({ rows }: { rows: ImportPreviewRow[] }) {
  if (rows.length === 0) return null;
  return (
    <div>
      <div className="mb-1 text-[11px] uppercase tracking-wide text-neutral-500">
        Preview ({rows.length})
      </div>
      <div className="overflow-x-auto rounded-lg border border-neutral-800">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="border-b border-neutral-800 bg-neutral-900 text-left uppercase tracking-wide text-neutral-500">
              <th className="px-2 py-1.5 font-medium">Row</th>
              <th className="px-2 py-1.5 font-medium">Action</th>
              <th className="px-2 py-1.5 font-medium">Normalized values</th>
              <th className="px-2 py-1.5 font-medium">Warnings</th>
              <th className="px-2 py-1.5 font-medium">Errors</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.row_number} className="border-b border-neutral-900 last:border-0">
                <td className="px-2 py-1.5 text-neutral-400">{row.row_number}</td>
                <td className="px-2 py-1.5">
                  <span
                    className={`inline-flex items-center rounded px-1.5 py-0.5 font-medium ring-1 ring-inset ${
                      PREVIEW_ACTION_TONE[row.action] ?? PREVIEW_ACTION_TONE.would_skip
                    }`}
                  >
                    {row.action}
                  </span>
                </td>
                <td className="max-w-xs px-2 py-1.5 font-mono text-neutral-400">
                  {Object.keys(row.normalized_values).length === 0
                    ? "—"
                    : JSON.stringify(row.normalized_values)}
                </td>
                <td className="max-w-xs px-2 py-1.5 text-amber-200">
                  {row.warnings.length === 0 ? "—" : row.warnings.join("; ")}
                </td>
                <td className="max-w-xs px-2 py-1.5 text-rose-300">
                  {row.errors.length === 0 ? "—" : row.errors.join("; ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatusBadge({ valid }: { valid: boolean }) {
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${
        valid
          ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30"
          : "bg-rose-500/15 text-rose-300 ring-rose-500/30"
      }`}
    >
      {valid ? "Valid" : "Invalid"}
    </span>
  );
}

function StatChip({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "rose" | "amber" | "emerald" | "sky";
}) {
  const toneClass =
    tone === "rose"
      ? "text-rose-300"
      : tone === "amber"
        ? "text-amber-300"
        : tone === "emerald"
          ? "text-emerald-300"
          : tone === "sky"
            ? "text-sky-300"
            : "text-neutral-300";
  return (
    <span className="rounded border border-neutral-800 bg-neutral-950 px-2 py-1">
      <span className="text-neutral-500">{label}:</span>{" "}
      <span className={`font-medium ${toneClass}`}>{value}</span>
    </span>
  );
}
