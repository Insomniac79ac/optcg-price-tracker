"use client";

import { useState } from "react";

import { FormField } from "@/components/FormField";
import {
  COLLECTION_IMPORT_MODES,
  type CollectionImportMode,
  type CollectionImportResponse,
  downloadCollectionCsv,
  importCollectionCsv,
} from "@/lib/api";

/** Collection page's CSV export/import section - split out of
 * app/collection/page.tsx purely to shrink an otherwise very large single
 * component. Fully self-contained (owns its own file/mode/dry-run/result
 * state) except for `onImported`, which the parent uses to refresh the
 * item list/summary/valuation after a real (non-dry-run) import. */
export function CollectionImportExport({ onImported }: { onImported: () => void }) {
  const [exportPending, setExportPending] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const [importFile, setImportFile] = useState<File | null>(null);
  const [importMode, setImportMode] = useState<CollectionImportMode>("upsert");
  const [importDryRun, setImportDryRun] = useState(true);
  const [importPending, setImportPending] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<CollectionImportResponse | null>(null);

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

  function handleImportFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    setImportFile(e.target.files?.[0] ?? null);
    setImportResult(null);
    setImportError(null);
  }

  async function runImport(dryRun: boolean) {
    if (!importFile) {
      setImportError("Choose a CSV file first.");
      return;
    }
    setImportError(null);
    setImportPending(true);
    try {
      const result = await importCollectionCsv(importFile, { dryRun, mode: importMode });
      setImportResult(result);
      if (!dryRun) onImported();
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
        <button
          type="button"
          onClick={handleExportCsv}
          disabled={exportPending}
          className="rounded bg-neutral-100 px-3 py-1.5 text-xs font-medium text-neutral-900 hover:bg-white disabled:opacity-50"
        >
          {exportPending ? "Exporting…" : "Export collection CSV"}
        </button>
        <span className="text-xs text-neutral-600">Downloads /collection/export.csv</span>
      </div>

      {exportError && (
        <div className="mt-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {exportError}
        </div>
      )}

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
            <div className="overflow-x-auto rounded border border-rose-900/50">
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="border-b border-rose-900/50 bg-rose-950/30 text-left text-[11px] uppercase tracking-wide text-rose-300">
                    <th className="px-2 py-1.5 font-medium">Row</th>
                    <th className="px-2 py-1.5 font-medium">Card code</th>
                    <th className="px-2 py-1.5 font-medium">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {importResult.errors.map((e, idx) => (
                    <tr key={`${e.row_number}-${idx}`} className="border-b border-neutral-900 last:border-0">
                      <td className="px-2 py-1.5 text-neutral-400">{e.row_number}</td>
                      <td className="px-2 py-1.5 font-mono text-neutral-400">
                        {e.card_code ?? "—"}
                      </td>
                      <td className="px-2 py-1.5 text-rose-300">{e.error}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {importResult.preview.length > 0 && (
            <div className="overflow-x-auto rounded border border-neutral-800">
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="border-b border-neutral-800 bg-neutral-950 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                    <th className="px-2 py-1.5 font-medium">Row</th>
                    <th className="px-2 py-1.5 font-medium">Card code</th>
                    <th className="px-2 py-1.5 font-medium">Action</th>
                    <th className="px-2 py-1.5 font-medium">Qty</th>
                    <th className="px-2 py-1.5 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {importResult.preview.map((p, idx) => (
                    <tr key={`${p.row_number}-${idx}`} className="border-b border-neutral-900 last:border-0">
                      <td className="px-2 py-1.5 text-neutral-400">{p.row_number}</td>
                      <td className="px-2 py-1.5 font-mono text-neutral-300">{p.card_code}</td>
                      <td className="px-2 py-1.5 text-neutral-200">{p.action}</td>
                      <td className="px-2 py-1.5 text-neutral-300">{p.quantity}</td>
                      <td className="px-2 py-1.5 text-neutral-300">{p.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
