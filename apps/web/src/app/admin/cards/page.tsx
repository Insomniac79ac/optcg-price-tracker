"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { FormField } from "@/components/FormField";
import { PaginationControls } from "@/components/PaginationControls";
import { RarityBadge } from "@/components/RarityBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { ActionButton } from "@/components/ui/ActionButton";
import { ConfirmActionModal } from "@/components/ui/ConfirmActionModal";
import { TableScrollContainer } from "@/components/ui/DataTableShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { SavedViewBar } from "@/components/ui/SavedViewBar";
import { StatCard as SharedStatCard, StatGrid } from "@/components/ui/StatCard";
import {
  AdminAuthRequiredError,
  type AdminCard,
  type AdminCardListResponse,
  type CardCatalogImportResponse,
  downloadCardsCsv,
  fetchAdminCards,
  getAdminToken,
  importCardsCsv,
} from "@/lib/api";
import { formatDateTime, formatNullable, formatNumber } from "@/lib/format";

type PageStatus = "loading" | "ready" | "unauthorized" | "error";

const LIMIT_OPTIONS = [25, 50, 100, 200] as const;
const MISSING_METADATA_OPTIONS = [
  { value: "", label: "Any" },
  { value: "true", label: "Missing metadata" },
  { value: "false", label: "Has metadata" },
] as const;

const IMPORT_CONFIRM_PHRASE = "IMPORT";

export default function AdminCardsPage() {
  const [unauthorized, setUnauthorized] = useState(false);
  const [status, setStatus] = useState<PageStatus>("loading");
  const [data, setData] = useState<AdminCardListResponse | null>(null);

  const [q, setQ] = useState("");
  const [setCode, setSetCode] = useState("");
  const [rarity, setRarity] = useState("");
  const [variant, setVariant] = useState("");
  const [language, setLanguage] = useState("");
  const [missingMetadata, setMissingMetadata] = useState("");
  const [limit, setLimit] = useState<number>(100);
  const [offset, setOffset] = useState(0);

  const load = useCallback(() => {
    setStatus("loading");
    fetchAdminCards({
      q: q.trim() || undefined,
      set_code: setCode || undefined,
      rarity: rarity || undefined,
      variant: variant || undefined,
      language: language || undefined,
      missing_metadata: missingMetadata === "" ? undefined : missingMetadata === "true",
      limit,
      offset,
    })
      .then((res) => {
        setData(res);
        setStatus("ready");
      })
      .catch((err) => {
        if (err instanceof AdminAuthRequiredError) {
          setUnauthorized(true);
        } else {
          setStatus("error");
        }
      });
  }, [q, setCode, rarity, variant, language, missingMetadata, limit, offset]);

  useEffect(() => {
    setUnauthorized(!getAdminToken());
  }, []);

  useEffect(() => {
    if (unauthorized) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unauthorized, load]);

  // Any filter change other than pagination itself resets back to page 1.
  useEffect(() => {
    setOffset(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, setCode, rarity, variant, language, missingMetadata, limit]);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <PageHeader
          title="Card catalog"
          description="Browse, search, and bulk import/export the canonical cards table."
          actions={<AdminLogoutButton />}
        />
        <div className="mb-6 flex flex-wrap gap-3">
          <Link
            href="/admin/card-audit"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Card audit →
          </Link>
          <Link
            href="/admin/catalog-coverage"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Catalog coverage →
          </Link>
          <Link
            href="/admin/card-duplicates"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Card duplicates →
          </Link>
          <Link
            href="/admin/import-validation"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Import validation →
          </Link>
          <Link
            href="/admin/catalog-ops"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Catalog operations →
          </Link>
        </div>

        {unauthorized && (
          <AdminAuthGate
            onTokenSaved={() => {
              setUnauthorized(false);
            }}
          />
        )}

        {!unauthorized && (
          <>
            <ImportExportSection onImported={load} />

            <SearchFilters
              q={q}
              onQChange={setQ}
              setCode={setCode}
              onSetCodeChange={setSetCode}
              rarity={rarity}
              onRarityChange={setRarity}
              variant={variant}
              onVariantChange={setVariant}
              language={language}
              onLanguageChange={setLanguage}
              missingMetadata={missingMetadata}
              onMissingMetadataChange={setMissingMetadata}
            />

            <SavedViewBar
              routePath="/admin/cards"
              viewType="cards"
              scope="admin"
              currentFilters={{ q, setCode, rarity, variant, language, missingMetadata }}
              onApply={(filters) => {
                if (typeof filters.q === "string") setQ(filters.q);
                if (typeof filters.setCode === "string") setSetCode(filters.setCode);
                if (typeof filters.rarity === "string") setRarity(filters.rarity);
                if (typeof filters.variant === "string") setVariant(filters.variant);
                if (typeof filters.language === "string") setLanguage(filters.language);
                if (typeof filters.missingMetadata === "string") {
                  setMissingMetadata(filters.missingMetadata);
                }
                setOffset(0);
              }}
            />

            {status === "loading" && <LoadingState>Loading cards…</LoadingState>}

            {status === "error" && (
              <ErrorState>Failed to load the card catalog from the API.</ErrorState>
            )}

            {status === "ready" && data && (
              <>
                <SummaryCards data={data} />

                {data.cards.length === 0 ? (
                  <EmptyState>No cards match the current filters.</EmptyState>
                ) : (
                  <>
                    <CardsTable cards={data.cards} />
                    <div className="mt-3">
                      <PaginationControls
                        offset={offset}
                        limit={limit}
                        total={data.pagination.total}
                        onOffsetChange={setOffset}
                        limitOptions={LIMIT_OPTIONS}
                        onLimitChange={setLimit}
                      />
                    </div>
                  </>
                )}
              </>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function SummaryCards({ data }: { data: AdminCardListResponse }) {
  const topSets = Object.entries(data.summary.by_set)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([k, v]) => `${k} (${v})`)
    .join(", ");
  const topRarities = Object.entries(data.summary.by_rarity)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([k, v]) => `${k} (${v})`)
    .join(", ");

  return (
    <div className="mb-6">
      <StatGrid>
        <SharedStatCard label="Total cards" value={formatNumber(data.summary.total_cards)} />
        <SharedStatCard
          label="Missing metadata"
          value={formatNumber(data.summary.missing_metadata_count)}
          tone={data.summary.missing_metadata_count > 0 ? "bad" : "neutral"}
        />
        <SharedStatCard label="Top sets" value={topSets || "not available"} />
        <SharedStatCard label="Top rarities" value={topRarities || "not available"} />
      </StatGrid>
    </div>
  );
}

function SearchFilters({
  q,
  onQChange,
  setCode,
  onSetCodeChange,
  rarity,
  onRarityChange,
  variant,
  onVariantChange,
  language,
  onLanguageChange,
  missingMetadata,
  onMissingMetadataChange,
}: {
  q: string;
  onQChange: (v: string) => void;
  setCode: string;
  onSetCodeChange: (v: string) => void;
  rarity: string;
  onRarityChange: (v: string) => void;
  variant: string;
  onVariantChange: (v: string) => void;
  language: string;
  onLanguageChange: (v: string) => void;
  missingMetadata: string;
  onMissingMetadataChange: (v: string) => void;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end gap-3">
      <FormField label="Search">
        <input
          type="text"
          value={q}
          onChange={(e) => onQChange(e.target.value)}
          placeholder="card code or name"
          className="w-48 rounded border border-border-default bg-bg-surface px-2 py-1 text-xs text-text-primary placeholder:text-text-faint"
        />
      </FormField>
      <FormField label="Set code">
        <input
          type="text"
          value={setCode}
          onChange={(e) => onSetCodeChange(e.target.value)}
          placeholder="OP01"
          className="w-24 rounded border border-border-default bg-bg-surface px-2 py-1 text-xs text-text-primary placeholder:text-text-faint"
        />
      </FormField>
      <FormField label="Rarity">
        <input
          type="text"
          value={rarity}
          onChange={(e) => onRarityChange(e.target.value)}
          placeholder="L"
          className="w-20 rounded border border-border-default bg-bg-surface px-2 py-1 text-xs text-text-primary placeholder:text-text-faint"
        />
      </FormField>
      <FormField label="Variant">
        <input
          type="text"
          value={variant}
          onChange={(e) => onVariantChange(e.target.value)}
          placeholder="parallel"
          className="w-28 rounded border border-border-default bg-bg-surface px-2 py-1 text-xs text-text-primary placeholder:text-text-faint"
        />
      </FormField>
      <FormField label="Language">
        <select
          value={language}
          onChange={(e) => onLanguageChange(e.target.value)}
          className="rounded border border-border-default bg-bg-surface px-2 py-1 text-xs text-text-primary"
        >
          <option value="">Any</option>
          <option value="jp">jp</option>
          <option value="en">en</option>
        </select>
      </FormField>
      <FormField label="Metadata">
        <select
          value={missingMetadata}
          onChange={(e) => onMissingMetadataChange(e.target.value)}
          className="rounded border border-border-default bg-bg-surface px-2 py-1 text-xs text-text-primary"
        >
          {MISSING_METADATA_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </FormField>
    </div>
  );
}

function CardsTable({ cards }: { cards: AdminCard[] }) {
  return (
    <TableScrollContainer minWidth={960}>
      <table className="w-full border-collapse text-sm">
        <thead className="sticky-thead">
          <tr className="border-b border-border-default bg-bg-surface text-left text-xs uppercase tracking-wide text-text-muted">
            <th className="px-3 py-2 font-medium">Card code</th>
            <th className="px-3 py-2 font-medium">Name</th>
            <th className="px-3 py-2 font-medium">Set</th>
            <th className="px-3 py-2 font-medium">Rarity</th>
            <th className="px-3 py-2 font-medium">Variant</th>
            <th className="px-3 py-2 font-medium">Language</th>
            <th className="px-3 py-2 font-medium">Artist</th>
            <th className="px-3 py-2 font-medium">Updated</th>
          </tr>
        </thead>
        <tbody>
          {cards.map((card) => (
            <tr key={card.id} className="border-b border-border-muted last:border-0 hover:bg-bg-elevated/60">
              <td className="px-3 py-2 font-mono text-xs text-text-secondary">
                <Link href={`/cards/${card.id}`} className="hover:text-sky-400">
                  {card.card_code}
                </Link>
              </td>
              <td className="max-w-xs px-3 py-2 text-text-secondary" title={card.name_en ?? undefined}>
                {formatNullable(card.name_en, (v) => v)}
              </td>
              <td className="px-3 py-2 text-text-secondary">{card.set_code}</td>
              <td className="px-3 py-2">
                <RarityBadge rarity={card.rarity} />
              </td>
              <td className="px-3 py-2 text-text-secondary">{formatNullable(card.variant, (v) => v)}</td>
              <td className="px-3 py-2 text-text-secondary">{card.language}</td>
              <td className="px-3 py-2 text-text-secondary">{formatNullable(card.artist, (v) => v)}</td>
              <td className="px-3 py-2 text-xs text-text-muted">{formatDateTime(card.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScrollContainer>
  );
}

function ImportExportSection({ onImported }: { onImported: () => void }) {
  const [exportPending, setExportPending] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const [importFile, setImportFile] = useState<File | null>(null);
  const [importDryRun, setImportDryRun] = useState(true);
  const [importOverwrite, setImportOverwrite] = useState(false);
  const [importPending, setImportPending] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<CardCatalogImportResponse | null>(null);
  const [confirmingRealImport, setConfirmingRealImport] = useState(false);

  async function handleExportCsv() {
    setExportError(null);
    setExportPending(true);
    try {
      await downloadCardsCsv();
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Failed to export card catalog CSV.");
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
      const result = await importCardsCsv(importFile, { dryRun, overwrite: importOverwrite });
      setImportResult(result);
      if (!dryRun) onImported();
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Failed to import card catalog CSV.");
    } finally {
      setImportPending(false);
    }
  }

  return (
    <section className="mb-6 rounded-panel border border-border-default bg-bg-surface p-4">
      <h2 className="mb-3 text-sm font-semibold text-text-primary">Import / export</h2>

      <div className="flex flex-wrap items-center gap-3 border-b border-border-default pb-3">
        <ActionButton variant="primary" onClick={handleExportCsv} disabled={exportPending}>
          {exportPending ? "Exporting…" : "Export cards CSV"}
        </ActionButton>
        <span className="text-xs text-text-faint">Downloads /admin/cards/export.csv</span>
      </div>

      {exportError && (
        <div className="mt-3 rounded border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
          {exportError}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-end gap-3">
        <FormField label="CSV file">
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={handleImportFileChange}
            className="block w-full text-xs text-text-secondary file:mr-2 file:rounded file:border-0 file:bg-bg-card file:px-2 file:py-1 file:text-xs file:font-medium file:text-text-primary hover:file:bg-bg-elevated"
          />
        </FormField>

        <label className="flex items-center gap-1.5 rounded border border-border-default bg-bg-page px-2 py-1.5 text-xs text-text-secondary">
          <input
            type="checkbox"
            checked={importDryRun}
            onChange={(e) => setImportDryRun(e.target.checked)}
            className="rounded border-border-default bg-bg-page"
          />
          Dry run
        </label>

        <label className="flex items-center gap-1.5 rounded border border-border-default bg-bg-page px-2 py-1.5 text-xs text-text-secondary">
          <input
            type="checkbox"
            checked={importOverwrite}
            onChange={(e) => setImportOverwrite(e.target.checked)}
            className="rounded border-border-default bg-bg-page"
          />
          Overwrite existing fields
        </label>

        <ActionButton variant="dry-run" onClick={() => runImport(true)} disabled={importPending || !importFile}>
          {importPending ? "Working…" : "Preview import"}
        </ActionButton>

        {!importDryRun && (
          <ActionButton
            variant="danger"
            onClick={() => setConfirmingRealImport(true)}
            disabled={importPending || !importFile}
          >
            {importPending ? "Working…" : "Import for real"}
          </ActionButton>
        )}
      </div>

      {!importDryRun && (
        <div className="mt-3 rounded border border-signal-warning/40 bg-signal-warning/10 px-3 py-2 text-xs text-signal-warning">
          This will write changes to the card catalog.
        </div>
      )}

      {importError && (
        <div className="mt-3 rounded border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
          {importError}
        </div>
      )}

      <ConfirmActionModal
        open={confirmingRealImport}
        title="Import card catalog for real"
        description={
          importOverwrite
            ? "This overwrites existing fields on matched cards and writes new rows for the rest - it cannot be previewed away once run."
            : "This creates/updates card catalog rows from the CSV. Run \"Preview import\" first if you haven't already."
        }
        confirmPhrase={IMPORT_CONFIRM_PHRASE}
        confirmLabel="Import for real"
        pending={importPending}
        error={importError}
        onConfirm={() => {
          setConfirmingRealImport(false);
          runImport(false);
        }}
        onCancel={() => setConfirmingRealImport(false)}
      />

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
            <TableScrollContainer showScrollHint={false}>
              <table className="w-full border-collapse text-xs">
                <thead className="sticky-thead">
                  <tr className="border-b border-signal-red/40 bg-signal-red/10 text-left text-[11px] uppercase tracking-wide text-signal-red">
                    <th className="px-2 py-1.5 font-medium">Row</th>
                    <th className="px-2 py-1.5 font-medium">Card code</th>
                    <th className="px-2 py-1.5 font-medium">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {importResult.errors.map((e, idx) => (
                    <tr key={`${e.row_number}-${idx}`} className="border-b border-border-muted last:border-0">
                      <td className="px-2 py-1.5 text-text-secondary">{e.row_number}</td>
                      <td className="px-2 py-1.5 font-mono text-text-secondary">
                        {e.card_code ?? "not available"}
                      </td>
                      <td className="px-2 py-1.5 text-signal-red">{e.error}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScrollContainer>
          )}

          {importResult.preview.length > 0 && (
            <TableScrollContainer showScrollHint={false}>
              <table className="w-full border-collapse text-xs">
                <thead className="sticky-thead">
                  <tr className="border-b border-border-default bg-bg-page text-left text-[11px] uppercase tracking-wide text-text-muted">
                    <th className="px-2 py-1.5 font-medium">Row</th>
                    <th className="px-2 py-1.5 font-medium">Card code</th>
                    <th className="px-2 py-1.5 font-medium">Action</th>
                    <th className="px-2 py-1.5 font-medium">Changed fields</th>
                  </tr>
                </thead>
                <tbody>
                  {importResult.preview.map((p, idx) => (
                    <tr key={`${p.row_number}-${idx}`} className="border-b border-border-muted last:border-0">
                      <td className="px-2 py-1.5 text-text-secondary">{p.row_number}</td>
                      <td className="px-2 py-1.5 font-mono text-text-secondary">{p.card_code}</td>
                      <td className="px-2 py-1.5 text-text-primary">{p.action}</td>
                      <td className="px-2 py-1.5 text-text-secondary">
                        {Object.keys(p.changes).length === 0
                          ? "none"
                          : Object.keys(p.changes).join(", ")}
                      </td>
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
    <span className="rounded border border-border-default bg-bg-page px-2 py-1 text-text-secondary">
      <span className="text-text-muted">{label}:</span> {value}
    </span>
  );
}
