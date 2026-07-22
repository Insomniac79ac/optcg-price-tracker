"use client";

import Link from "next/link";
import { useState } from "react";

import { FileJobTracker } from "@/components/FileJobTracker";
import { FormField } from "@/components/FormField";
import { ActionButton } from "@/components/ui/ActionButton";
import { TableScrollContainer } from "@/components/ui/DataTableShell";
import {
  COLLECTION_IMPORT_MODES,
  type CollectionImportMode,
  type CollectionImportResponse,
  createCollectionExportJob,
  downloadCollectionCsv,
  importCollectionCsv,
  importCollectionCsvBackground,
} from "@/lib/api";

/** Collection page's CSV export/import section - split out of
 * app/collection/page.tsx purely to shrink an otherwise very large single
 * component. Fully self-contained (owns its own file/mode/dry-run/result/
 * background-job state) except for `onImported`, which the parent uses to
 * refresh the item list/summary/valuation after a real (non-dry-run)
 * import (direct or background). */
export function CollectionImportExport({ onImported }: { onImported: () => void }) {
  const [exportPending, setExportPending] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportJobId, setExportJobId] = useState<number | null>(null);
  const [exportJobPending, setExportJobPending] = useState(false);
  const [exportJobError, setExportJobError] = useState<string | null>(null);

  const [importFile, setImportFile] = useState<File | null>(null);
  const [importMode, setImportMode] = useState<CollectionImportMode>("upsert");
  const [importDryRun, setImportDryRun] = useState(true);
  const [importBackground, setImportBackground] = useState(false);
  const [importPending, setImportPending] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<CollectionImportResponse | null>(null);
  const [importJobId, setImportJobId] = useState<number | null>(null);

  async function handleExportCsv() {
    setExportError(null);
    setExportPending(true);
    try {
      await downloadCollectionCsv();
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Failed to export collection CSV.");
    } finally {
      setExportPending(false);
    }
  }

  async function handlePrepareExportJob() {
    setExportJobError(null);
    setExportJobPending(true);
    try {
      const { file_job_id } = await createCollectionExportJob();
      setExportJobId(file_job_id);
    } catch (err) {
      setExportJobError(err instanceof Error ? err.message : "Failed to prepare export.");
    } finally {
      setExportJobPending(false);
    }
  }

  function handleImportFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    setImportFile(e.target.files?.[0] ?? null);
    setImportResult(null);
    setImportError(null);
    setImportJobId(null);
  }

  async function runImport(dryRun: boolean) {
    if (!importFile) {
      setImportError("Choose a CSV file first.");
      return;
    }
    setImportError(null);
    setImportPending(true);
    try {
      if (importBackground) {
        const { file_job_id } = await importCollectionCsvBackground(importFile, {
          dryRun,
          mode: importMode,
        });
        setImportJobId(file_job_id);
      } else {
        const result = await importCollectionCsv(importFile, { dryRun, mode: importMode });
        setImportResult(result);
        if (!dryRun) onImported();
      }
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Failed to import collection CSV.");
    } finally {
      setImportPending(false);
    }
  }

  return (
    <section className="mb-6 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <h2 className="mb-3 text-sm font-semibold text-neutral-200">Collection import/export</h2>

      <div className="flex flex-wrap items-center gap-3 border-b border-neutral-800 pb-3">
        <ActionButton variant="primary" onClick={handleExportCsv} disabled={exportPending}>
          {exportPending ? "Exporting…" : "Export collection CSV"}
        </ActionButton>
        <span className="text-xs text-neutral-600">Downloads /collection/export.csv</span>

        <button
          type="button"
          onClick={handlePrepareExportJob}
          disabled={exportJobPending}
          className="rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-200 hover:text-neutral-100 disabled:opacity-50"
        >
          {exportJobPending ? "Preparing…" : "Prepare collection export"}
        </button>
        <span className="text-xs text-neutral-600">Generates in the background - useful for a large collection</span>
        <Link
          href="/admin/file-jobs"
          className="ml-auto text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
        >
          File jobs
        </Link>
      </div>

      {exportError && (
        <div className="mt-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {exportError}
        </div>
      )}
      {exportJobError && (
        <div className="mt-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {exportJobError}
        </div>
      )}
      {exportJobId !== null && <FileJobTracker fileJobId={exportJobId} />}

      <div className="mt-3 flex flex-wrap items-end gap-3">
        <FormField label="CSV file">
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={handleImportFileChange}
            className="block w-full text-xs text-neutral-300 file:mr-2 file:rounded file:border-0 file:bg-neutral-800 file:px-2 file:py-1 file:text-xs file:font-medium file:text-neutral-200 hover:file:bg-neutral-700"
          />
        </FormField>

        <FormField label="Mode">
          <select
            value={importMode}
            onChange={(e) => setImportMode(e.target.value as CollectionImportMode)}
            className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
          >
            {COLLECTION_IMPORT_MODES.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </FormField>

        <label className="flex items-center gap-1.5 rounded border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-xs text-neutral-400">
          <input
            type="checkbox"
            checked={importDryRun}
            onChange={(e) => setImportDryRun(e.target.checked)}
            className="rounded border-neutral-700 bg-neutral-950"
          />
          Dry run
        </label>

        <label className="flex items-center gap-1.5 rounded border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-xs text-neutral-400">
          <input
            type="checkbox"
            checked={importBackground}
            onChange={(e) => setImportBackground(e.target.checked)}
            className="rounded border-neutral-700 bg-neutral-950"
          />
          Run import in background
        </label>

        <button
          type="button"
          onClick={() => runImport(true)}
          disabled={importPending || !importFile}
          className="rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-200 hover:text-neutral-100 disabled:opacity-50"
        >
          {importPending ? "Working…" : "Preview import"}
        </button>

        {!importDryRun && (
          <button
            type="button"
            onClick={() => runImport(false)}
            disabled={importPending || !importFile}
            className="rounded bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-500 disabled:opacity-50"
          >
            {importPending ? "Working…" : "Import for real"}
          </button>
        )}
      </div>

      {!importDryRun && (
        <div className="mt-3 rounded border border-amber-900/50 bg-amber-950/30 px-3 py-2 text-xs text-amber-300">
          This will write changes to your collection.
        </div>
      )}

      {importError && (
        <div className="mt-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {importError}
        </div>
      )}

      {importJobId !== null && (
        <FileJobTracker
          fileJobId={importJobId}
          onSuccess={(job) => {
            if (!job.dry_run) onImported();
          }}
        />
      )}

      {importResult && (
        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap gap-2 text-xs">
            <ImportStat label="Total rows" value={importResult.summary.total_rows} />
            <ImportStat label="Valid" value={importResult.summary.valid_rows} />
            <ImportStat label="Errors" value={importResult.summary.error_rows} />
            <ImportStat label="Created" value={importResult.summary.created} />
            <ImportStat label="Updated" value={importResult.summary.updated} />
            <ImportStat label="Skipped" value={importResult.summary.skipped} />
          </div>

          {importResult.errors.length > 0 && (
            <TableScrollContainer showScrollHint={false} className="border-signal-red/40">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Row</th>
                    <th>Card code</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {importResult.errors.map((e, idx) => (
                    <tr key={`${e.row_number}-${idx}`}>
                      <td>{e.row_number}</td>
                      <td className="mono">{e.card_code ?? "—"}</td>
                      <td className="text-signal-red">{e.error}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScrollContainer>
          )}

          {importResult.preview.length > 0 && (
            <TableScrollContainer showScrollHint={false}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Row</th>
                    <th>Card code</th>
                    <th>Action</th>
                    <th>Qty</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {importResult.preview.map((p, idx) => (
                    <tr key={`${p.row_number}-${idx}`}>
                      <td>{p.row_number}</td>
                      <td className="mono">{p.card_code}</td>
                      <td>{p.action}</td>
                      <td className="mono tabular">{p.quantity}</td>
                      <td>{p.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScrollContainer>
          )}
        </div>
      )}
    </section>
  );
}

function ImportStat({ label, value }: { label: string; value: number }) {
  return (
    <span className="rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-neutral-300">
      <span className="text-neutral-500">{label}:</span> {value}
    </span>
  );
}
