"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminSessionExpired } from "@/components/AdminSessionExpired";
import { AppHeader } from "@/components/AppHeader";
import { FileJobTracker } from "@/components/FileJobTracker";
import { ActionButton } from "@/components/ui/ActionButton";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  AdminAuthRequiredError,
  type BackupRestoreMode,
  type BackupRestoreResponse,
  type BackupValidateResponse,
  BACKUP_RESTORE_MODES,
  createBackupExportJob,
  downloadBackup,
  restoreBackup,
  validateBackup,
} from "@/lib/api";

const CONFIRM_PHRASE = "RESTORE";

export default function AdminBackupPage() {
  const [unauthorized, setUnauthorized] = useState(false);

  useEffect(() => {
  }, []);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <PageHeader
          title="Backup & restore"
          description="Export, validate, and restore tracker data (cards, collection, mappings, reports, signals, and workflow history). Never includes tokens, passwords, or other secrets."
        />

        {unauthorized && <AdminSessionExpired />}

        {!unauthorized && (
          <div className="flex flex-col gap-6">
            <ExportSection />
            <ValidateSection />
            <RestoreSection />

            <div className="flex flex-wrap gap-3 text-xs">
              <Link
                href="/admin/actions"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Admin actions
              </Link>
              <Link
                href="/collection"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Collection
              </Link>
              <Link
                href="/admin/file-jobs"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                File jobs
              </Link>
              <Link
                href="/admin/import-validation"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Import validation
              </Link>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="panel p-4">
      <h2 className="mb-3 text-sm font-semibold text-text-primary">{title}</h2>
      {children}
    </section>
  );
}

function ExportSection() {
  const [includePrices, setIncludePrices] = useState(false);
  const [includeRawSnapshots, setIncludeRawSnapshots] = useState(false);
  const [includeRefreshRuns, setIncludeRefreshRuns] = useState(false);
  const [includeLogs, setIncludeLogs] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [jobPending, setJobPending] = useState(false);
  const [jobError, setJobError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);

  async function handleDownload() {
    setError(null);
    setPending(true);
    try {
      await downloadBackup({
        includePrices,
        includeRawSnapshots,
        includeRefreshRuns,
        includeLogs,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export backup.");
    } finally {
      setPending(false);
    }
  }

  async function handlePrepareJob() {
    setJobError(null);
    setJobPending(true);
    try {
      const { file_job_id } = await createBackupExportJob({
        includePrices,
        includeRawSnapshots,
        includeRefreshRuns,
        includeLogs,
      });
      setJobId(file_job_id);
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) {
        setJobError("Admin token required.");
      } else {
        setJobError(err instanceof Error ? err.message : "Failed to prepare backup export.");
      }
    } finally {
      setJobPending(false);
    }
  }

  return (
    <Section title="Export backup">
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          <input
            type="checkbox"
            checked={includePrices}
            onChange={(e) => setIncludePrices(e.target.checked)}
            className="rounded border-border-default bg-bg-page"
          />
          Include prices
        </label>
        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          <input
            type="checkbox"
            checked={includeRawSnapshots}
            onChange={(e) => setIncludeRawSnapshots(e.target.checked)}
            className="rounded border-border-default bg-bg-page"
          />
          Include raw snapshots
        </label>
        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          <input
            type="checkbox"
            checked={includeRefreshRuns}
            onChange={(e) => setIncludeRefreshRuns(e.target.checked)}
            className="rounded border-border-default bg-bg-page"
          />
          Include refresh runs
        </label>
        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          <input
            type="checkbox"
            checked={includeLogs}
            onChange={(e) => setIncludeLogs(e.target.checked)}
            className="rounded border-border-default bg-bg-page"
          />
          Include logs
        </label>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <ActionButton variant="primary" onClick={handleDownload} disabled={pending}>
          {pending ? "Exporting…" : "Download backup JSON"}
        </ActionButton>

        <ActionButton variant="default" onClick={handlePrepareJob} disabled={jobPending}>
          {jobPending ? "Preparing…" : "Prepare backup in background"}
        </ActionButton>
        <span className="text-xs text-text-faint">
          Generates in the background - useful for a large backup
        </span>
      </div>

      {error && (
        <div className="mt-3 rounded-control border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
          {error}
        </div>
      )}
      {jobError && (
        <div className="mt-3 rounded-control border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
          {jobError}
        </div>
      )}
      {jobId !== null && <FileJobTracker fileJobId={jobId} />}
    </Section>
  );
}

function ValidateSection() {
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BackupValidateResponse | null>(null);

  async function handleValidate() {
    if (!file) {
      setError("Choose a backup JSON file first.");
      return;
    }
    setError(null);
    setPending(true);
    try {
      const data = await validateBackup(file);
      setResult(data);
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) {
        setError("Admin token required.");
      } else {
        setError(err instanceof Error ? err.message : "Failed to validate backup.");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <Section title="Validate backup">
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="file"
          accept=".json,application/json"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setResult(null);
            setError(null);
          }}
          className="block text-xs text-text-secondary file:mr-2 file:rounded file:border-0 file:bg-bg-card file:px-2 file:py-1 file:text-xs file:font-medium file:text-text-primary hover:file:bg-bg-elevated"
        />
        <button
          type="button"
          onClick={handleValidate}
          disabled={pending || !file}
          className="rounded border border-border-default px-3 py-1.5 text-xs font-medium text-text-primary hover:text-text-primary disabled:opacity-50"
        >
          {pending ? "Validating…" : "Validate"}
        </button>
      </div>

      {error && (
        <div className="mt-3 rounded border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-4 space-y-3">
          <div className="flex items-center gap-2">
            <StatusBadge valid={result.valid} />
            <span className="text-xs text-text-muted">
              backup_version: {result.backup_version ?? "—"}
            </span>
          </div>

          {Object.keys(result.summary).length > 0 && (
            <div className="flex flex-wrap gap-2 text-xs">
              {Object.entries(result.summary).map(([table, count]) => (
                <span
                  key={table}
                  className="rounded border border-border-default bg-bg-page px-2 py-1 text-text-secondary"
                >
                  <span className="text-text-muted">{table}:</span> {count}
                </span>
              ))}
            </div>
          )}

          <MessageList label="Warnings" items={result.warnings} tone="amber" />
          <MessageList label="Errors" items={result.errors} tone="rose" />
        </div>
      )}
    </Section>
  );
}

function RestoreSection() {
  const [file, setFile] = useState<File | null>(null);
  const [dryRun, setDryRun] = useState(true);
  const [mode, setMode] = useState<BackupRestoreMode>("merge");
  const [confirmText, setConfirmText] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BackupRestoreResponse | null>(null);

  const isRealReplace = mode === "replace" && !dryRun;
  const confirmSatisfied = !isRealReplace || confirmText === CONFIRM_PHRASE;

  async function handleRestore() {
    if (!file) {
      setError("Choose a backup JSON file first.");
      return;
    }
    if (!confirmSatisfied) {
      setError(`Type ${CONFIRM_PHRASE} to confirm a real replace restore.`);
      return;
    }
    setError(null);
    setPending(true);
    try {
      const data = await restoreBackup(file, {
        dryRun,
        mode,
        confirm: isRealReplace ? confirmText : undefined,
      });
      setResult(data);
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) {
        setError("Admin token required.");
      } else {
        setError(err instanceof Error ? err.message : "Failed to restore backup.");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <Section title="Restore backup">
      <div className="flex flex-wrap items-end gap-3">
        <input
          type="file"
          accept=".json,application/json"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setResult(null);
            setError(null);
          }}
          className="block text-xs text-text-secondary file:mr-2 file:rounded file:border-0 file:bg-bg-card file:px-2 file:py-1 file:text-xs file:font-medium file:text-text-primary hover:file:bg-bg-elevated"
        />

        <label className="text-xs text-text-muted">
          Mode
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as BackupRestoreMode)}
            className="ml-2 rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary"
          >
            {BACKUP_RESTORE_MODES.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-1.5 rounded border border-border-default bg-bg-page px-2 py-1.5 text-xs text-text-secondary">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => setDryRun(e.target.checked)}
            className="rounded border-border-default bg-bg-page"
          />
          Dry run
        </label>

        <ActionButton
          variant={isRealReplace ? "danger" : dryRun ? "dry-run" : "real"}
          onClick={handleRestore}
          disabled={pending || !file || !confirmSatisfied}
        >
          {pending ? "Working…" : "Restore"}
        </ActionButton>
      </div>

      {mode === "replace" && (
        <div className="mt-3 space-y-2">
          <div className="rounded border border-signal-warning/40 bg-signal-warning/10 px-3 py-2 text-xs text-signal-warning">
            Replace mode can delete existing tracker data.
          </div>
          {!dryRun && (
            <label className="flex items-center gap-2 text-xs text-text-secondary">
              Type <span className="font-mono text-text-primary">{CONFIRM_PHRASE}</span> to
              confirm:
              <input
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder={CONFIRM_PHRASE}
                className="w-40 rounded border border-border-default bg-bg-page px-2 py-1 text-xs text-text-primary placeholder:text-text-faint"
              />
            </label>
          )}
        </div>
      )}

      {error && (
        <div className="mt-3 rounded border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge valid={result.valid} />
            <span className="text-xs text-text-muted">
              dry_run: {String(result.dry_run)} · mode: {result.mode} · backup_version:{" "}
              {result.backup_version ?? "—"}
            </span>
          </div>

          {result.dry_run && Object.keys(result.preview).length > 0 && (
            <PreviewTable data={result.preview} />
          )}

          {!result.dry_run && (
            <>
              <SummaryTable title="Created" data={result.summary.created} />
              <SummaryTable title="Updated" data={result.summary.updated} />
              <SummaryTable title="Deleted" data={result.summary.deleted} />
              <SummaryTable title="Skipped" data={result.summary.skipped} />
            </>
          )}

          <MessageList label="Warnings" items={result.warnings} tone="amber" />
          <MessageList label="Errors" items={result.errors} tone="rose" />

          <details className="text-xs text-text-muted">
            <summary className="cursor-pointer select-none hover:text-text-secondary">
              Raw JSON
            </summary>
            <pre className="mt-2 max-h-64 overflow-auto rounded bg-bg-page p-3 text-[11px] text-text-secondary">
              {JSON.stringify(result, null, 2)}
            </pre>
          </details>
        </div>
      )}
    </Section>
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

function SummaryTable({ title, data }: { title: string; data: Record<string, number> }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return null;
  return (
    <div>
      <div className="mb-1 text-[11px] uppercase tracking-wide text-text-muted">{title}</div>
      <div className="flex flex-wrap gap-2 text-xs">
        {entries.map(([table, value]) => (
          <span
            key={table}
            className="rounded border border-border-default bg-bg-page px-2 py-1 text-text-secondary"
          >
            <span className="text-text-muted">{table}:</span> {value}
          </span>
        ))}
      </div>
    </div>
  );
}

function PreviewTable({ data }: { data: Record<string, Record<string, number>> }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return null;
  return (
    <div>
      <div className="mb-1 text-[11px] uppercase tracking-wide text-text-muted">Preview</div>
      <div className="flex flex-wrap gap-2 text-xs">
        {entries.map(([table, counts]) => (
          <span
            key={table}
            className="rounded border border-border-default bg-bg-page px-2 py-1 text-text-secondary"
          >
            <span className="text-text-muted">{table}:</span>{" "}
            {Object.entries(counts)
              .map(([action, n]) => `${action}=${n}`)
              .join(", ")}
          </span>
        ))}
      </div>
    </div>
  );
}

function MessageList({
  label,
  items,
  tone,
}: {
  label: string;
  items: string[];
  tone: "amber" | "rose";
}) {
  if (items.length === 0) return null;
  const toneClass =
    tone === "amber"
      ? "border-signal-warning/40 bg-signal-warning/10 text-signal-warning"
      : "border-signal-red/40 bg-signal-red/10 text-signal-red";
  return (
    <div>
      <div className="mb-1 text-[11px] uppercase tracking-wide text-text-muted">{label}</div>
      <ul className={`list-disc space-y-1 rounded border p-3 pl-8 text-xs ${toneClass}`}>
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
