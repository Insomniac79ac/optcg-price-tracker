"use client";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { ActionButton } from "@/components/ui/ActionButton";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { PageHeader } from "@/components/ui/PageHeader";
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
        <PageHeader
          title="Import Validation"
          description="Validate catalog, mapping, candidate, collection, and wishlist CSVs before writing data."
          actions={<AdminLogoutButton />}
        />

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
              <Link
                href="/admin/catalog-ops"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Catalog operations
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
    <section className="rounded-panel border border-border-default bg-bg-surface p-4">
      <h2 className="mb-3 text-sm font-semibold text-text-primary">{title}</h2>
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
        <div className="mb-3 rounded border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
          {error}
        </div>
      )}

      {!templates && !error && <p className="text-xs text-text-muted">Loading templates…</p>}

      {templates && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {templates.map((template) => (
            <div
              key={template.template_type}
              className="flex flex-col justify-between rounded border border-border-default bg-bg-page p-3"
            >
              <div>
                <div className="text-sm font-medium text-text-primary">
                  {IMPORT_TYPE_LABELS[template.template_type] ?? template.template_type}
                </div>
                <p className="mt-1 text-xs text-text-muted">{template.description}</p>

                <div className="mt-2 text-[11px] text-text-muted">
                  <span className="font-medium text-text-secondary">Required:</span>{" "}
                  {template.required_columns.join(", ")}
                </div>

                {template.optional_columns.length > 0 && (
                  <details className="mt-1 text-[11px] text-text-muted">
                    <summary className="cursor-pointer select-none hover:text-text-secondary">
                      Optional columns ({template.optional_columns.length})
                    </summary>
                    <p className="mt-1">{template.optional_columns.join(", ")}</p>
                  </details>
                )}
              </div>

              <ActionButton
                onClick={() => handleDownload(template.template_type)}
                disabled={downloadingType === template.template_type}
                className="mt-3"
              >
                {downloadingType === template.template_type ? "Downloading…" : "Download CSV"}
              </ActionButton>
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
          <label className="text-xs text-text-muted">
            Import type
            <select
              value={importType}
              onChange={(e) => {
                setImportType(e.target.value as ImportType);
                setResult(null);
              }}
              className="ml-2 rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary"
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
            className="block text-xs text-text-secondary file:mr-2 file:rounded file:border-0 file:bg-bg-elevated file:px-2 file:py-1 file:text-xs file:font-medium file:text-text-primary hover:file:bg-bg-card"
          />

          <label className="flex items-center gap-1.5 rounded border border-border-default bg-bg-page px-2 py-1.5 text-xs text-text-secondary">
            <input
              type="checkbox"
              checked={strict}
              onChange={(e) => setStrict(e.target.checked)}
              className="rounded border-border-default bg-bg-page"
            />
            Strict mode
          </label>

          <label className="text-xs text-text-muted">
            Max preview rows
            <input
              type="number"
              min={1}
              max={1000}
              value={maxPreviewRows}
              onChange={(e) => setMaxPreviewRows(Number(e.target.value) || 100)}
              className="ml-2 w-20 rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary"
            />
          </label>

          <label className="text-xs text-text-muted">
            User ID (collection/wishlist)
            <input
              type="number"
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              placeholder="optional"
              className="ml-2 w-24 rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary placeholder:text-text-faint"
            />
          </label>

          <ActionButton variant="primary" onClick={handleValidate} disabled={pending || !file}>
            {pending ? "Validating…" : "Validate"}
          </ActionButton>
        </div>

        {error && (
          <div className="mt-3 rounded border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
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
          <div className="mb-3 rounded border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
            {reportsError}
          </div>
        )}

        {!reports && !reportsError && <p className="text-xs text-text-muted">Loading report history…</p>}

        {reports && (
          <DataTableShell isEmpty={reports.length === 0} emptyLabel="No import validation reports yet.">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Created</th>
                  <th>Type</th>
                  <th>Filename</th>
                  <th>Valid</th>
                  <th>Total</th>
                  <th>Errors</th>
                  <th>Warnings</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {reports.map((report) => (
                  <Fragment key={report.id}>
                    <tr>
                      <td className="mono tabular text-text-secondary">{report.created_at}</td>
                      <td className="text-text-secondary">{report.import_type}</td>
                      <td className="text-text-secondary">{report.filename ?? "—"}</td>
                      <td>
                        <StatusBadge valid={report.valid} />
                      </td>
                      <td className="mono tabular text-text-secondary">{report.total_rows}</td>
                      <td className="mono tabular text-text-secondary">{report.error_rows}</td>
                      <td className="mono tabular text-text-secondary">{report.warning_rows}</td>
                      <td>
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
                      <tr key={`${report.id}-detail`}>
                        <td colSpan={8} className="bg-bg-page/60">
                          {expandedReportError && (
                            <div className="rounded border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
                              {expandedReportError}
                            </div>
                          )}
                          {!expandedReport && !expandedReportError && (
                            <p className="text-xs text-text-muted">Loading report…</p>
                          )}
                          {expandedReport && <ValidationResultView result={expandedReport} />}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </DataTableShell>
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
        <span className="text-xs text-text-muted">import_type: {result.import_type}</span>
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
      ? "border-signal-red/40 bg-rose-950/20 text-signal-red"
      : tone === "amber"
        ? "border-signal-warning/40 bg-signal-warning/10 text-signal-warning"
        : "border-border-default bg-bg-page text-text-secondary";
  return (
    <div>
      <div className="mb-1 text-[11px] uppercase tracking-wide text-text-muted">{label}</div>
      {items.length === 0 ? (
        <span className="text-text-faint">—</span>
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
  const headerToneClass = tone === "rose" ? "text-signal-red" : "text-signal-warning";
  return (
    <div>
      <div className={`mb-1 text-[11px] uppercase tracking-wide ${headerToneClass}`}>
        {label} ({issues.length})
      </div>
      <DataTableShell>
        <table className="data-table">
          <thead>
            <tr>
              <th>Row</th>
              <th>Field</th>
              <th>Value</th>
              <th>Code</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody>
            {issues.map((issue, idx) => (
              <tr key={idx}>
                <td className="mono tabular text-text-secondary">{issue.row_number}</td>
                <td className="mono text-text-secondary">{issue.field ?? "—"}</td>
                <td className="mono text-text-secondary">
                  {issue.value === null || issue.value === undefined ? "—" : String(issue.value)}
                </td>
                <td className="mono text-text-secondary">{issue.code}</td>
                <td className="text-text-secondary">{issue.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataTableShell>
    </div>
  );
}

const PREVIEW_ACTION_TONE: Record<string, string> = {
  would_create: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  would_update: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  would_skip: "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30",
  invalid: "bg-rose-500/15 text-signal-red ring-rose-500/30",
};

function PreviewTable({ rows }: { rows: ImportPreviewRow[] }) {
  if (rows.length === 0) return null;
  return (
    <div>
      <div className="mb-1 text-[11px] uppercase tracking-wide text-text-muted">
        Preview ({rows.length})
      </div>
      <DataTableShell>
        <table className="data-table">
          <thead>
            <tr>
              <th>Row</th>
              <th>Action</th>
              <th>Normalized values</th>
              <th>Warnings</th>
              <th>Errors</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.row_number}>
                <td className="mono tabular text-text-secondary">{row.row_number}</td>
                <td>
                  <span
                    className={`badge ring-1 ring-inset ${
                      PREVIEW_ACTION_TONE[row.action] ?? PREVIEW_ACTION_TONE.would_skip
                    }`}
                  >
                    {row.action}
                  </span>
                </td>
                <td className="mono max-w-xs text-text-secondary">
                  {Object.keys(row.normalized_values).length === 0
                    ? "—"
                    : JSON.stringify(row.normalized_values)}
                </td>
                <td className="max-w-xs text-signal-warning">
                  {row.warnings.length === 0 ? "—" : row.warnings.join("; ")}
                </td>
                <td className="max-w-xs text-signal-red">
                  {row.errors.length === 0 ? "—" : row.errors.join("; ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataTableShell>
    </div>
  );
}

function StatusBadge({ valid }: { valid: boolean }) {
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${
        valid
          ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30"
          : "bg-rose-500/15 text-signal-red ring-rose-500/30"
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
      ? "text-signal-red"
      : tone === "amber"
        ? "text-signal-warning"
        : tone === "emerald"
          ? "text-emerald-300"
          : tone === "sky"
            ? "text-sky-300"
            : "text-text-secondary";
  return (
    <span className="rounded border border-border-default bg-bg-page px-2 py-1">
      <span className="text-text-muted">{label}:</span>{" "}
      <span className={`font-medium ${toneClass}`}>{value}</span>
    </span>
  );
}
