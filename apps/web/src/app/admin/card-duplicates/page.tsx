"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { PaginationControls } from "@/components/PaginationControls";
import { RarityBadge } from "@/components/RarityBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { ActionButton } from "@/components/ui/ActionButton";
import { Badge } from "@/components/ui/Badge";
import { ConfirmActionModal } from "@/components/ui/ConfirmActionModal";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { FILTER_INPUT_CLASS, FilterBar } from "@/components/ui/FilterBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatCard, StatGrid } from "@/components/ui/StatCard";
import { VariantBadge } from "@/components/ui/VariantBadge";
import {
  AdminAuthRequiredError,
  type CardMergeFieldStrategy,
  type CardMergePreview,
  type CardMergeResult,
  type DuplicatePair,
  type DuplicateSummary,
  bulkPreviewCardDuplicates,
  fetchCardDuplicates,
  fetchCardMergePreview,
  mergeCards,
} from "@/lib/api";
import { cardDisplayName } from "@/lib/format";

const CONFIDENCE_LABEL_OPTIONS = [
  "",
  "exact_duplicate",
  "likely_duplicate",
  "possible_duplicate",
  "weak_match",
  "not_duplicate",
];

const FIELD_STRATEGY_OPTIONS: { value: CardMergeFieldStrategy; label: string }[] = [
  { value: "keep_target", label: "Keep target" },
  { value: "fill_missing_target_fields", label: "Fill missing target fields" },
  { value: "overwrite_target_empty_or_shorter_text", label: "Overwrite target if empty/shorter" },
];

const LIMIT_OPTIONS = [50, 100, 200, 500] as const;

const CONFIDENCE_STYLES: Record<string, string> = {
  exact_duplicate: "bg-rose-500/15 text-signal-red ring-rose-500/30",
  likely_duplicate: "bg-amber-500/15 text-signal-warning ring-amber-500/30",
  possible_duplicate: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  weak_match: "bg-neutral-500/15 text-text-secondary ring-neutral-500/30",
  not_duplicate: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
};

const MERGE_CONFIRM_PHRASE = "MERGE";

/** Duplicate-match confidence has its own domain vocabulary (distinct from
 * the app-wide exact/high/medium/low/very_low/unknown ConfidenceBadge) -
 * kept as a local badge on the shared `Badge` shell rather than forced
 * through a mismatched vocabulary. */
function ConfidenceBadge({ label }: { label: string }) {
  const style = CONFIDENCE_STYLES[label] ?? "bg-neutral-500/15 text-text-secondary ring-1 ring-inset ring-neutral-500/30";
  return <Badge label={label} className={`ring-1 ring-inset ${style}`} />;
}

function CardCell({ card }: { card: DuplicatePair["source_card"] }) {
  return (
    <div>
      <div className="flex flex-wrap items-center gap-1.5">
        <Link href={`/cards/${card.id}`} className="mono text-sm text-sky-400 hover:underline">
          {card.card_code}
        </Link>
        <RarityBadge rarity={card.rarity} />
        <VariantBadge variant={card.variant} />
      </div>
      <div className="text-xs text-text-secondary">{cardDisplayName(card)}</div>
      <div className="text-[11px] text-text-muted">
        {card.set_code} · {card.language}
        {!card.is_active && " · inactive"}
      </div>
    </div>
  );
}

export default function CardDuplicatesPage() {
  const [unauthorized, setUnauthorized] = useState(false);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [pairs, setPairs] = useState<DuplicatePair[]>([]);
  const [summary, setSummary] = useState<DuplicateSummary | null>(null);
  const [total, setTotal] = useState(0);

  const [q, setQ] = useState("");
  const [setCode, setSetCode] = useState("");
  const [rarity, setRarity] = useState("");
  const [variant, setVariant] = useState("");
  const [language, setLanguage] = useState("");
  const [confidenceLabel, setConfidenceLabel] = useState("");
  const [minScore, setMinScore] = useState(55);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);

  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);

  const [previewPair, setPreviewPair] = useState<DuplicatePair | null>(null);
  const [preview, setPreview] = useState<CardMergePreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [fieldStrategy, setFieldStrategy] = useState<CardMergeFieldStrategy>("keep_target");
  const [mergeNotes, setMergeNotes] = useState("");
  const [approveLowConfidence, setApproveLowConfidence] = useState(false);
  const [mergeResult, setMergeResult] = useState<CardMergeResult | null>(null);

  const [bulkMinScore, setBulkMinScore] = useState(90);
  const [bulkConfidenceLabel, setBulkConfidenceLabel] = useState("exact_duplicate");
  const [bulkLimit, setBulkLimit] = useState(50);
  const [bulkPreviews, setBulkPreviews] = useState<CardMergePreview[] | null>(null);
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);

  useEffect(() => {
    setOffset(0);
  }, [q, setCode, rarity, variant, language, confidenceLabel, minScore, includeInactive, limit]);

  function load() {
    let cancelled = false;
    fetchCardDuplicates({
      q: q || undefined,
      set_code: setCode || undefined,
      rarity: rarity || undefined,
      variant: variant || undefined,
      language: language || undefined,
      confidence_label: confidenceLabel || undefined,
      min_score: minScore,
      include_inactive: includeInactive,
      limit,
      offset,
    })
      .then((data) => {
        if (cancelled) return;
        setPairs(data.pairs);
        setSummary(data.summary);
        setTotal(data.pagination.total);
        setStatus("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
        else setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }

  useEffect(() => {
    return load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, setCode, rarity, variant, language, confidenceLabel, minScore, includeInactive, limit, offset]);

  function openPreview(pair: DuplicatePair) {
    setPreviewPair(pair);
    setPreview(null);
    setPreviewError(null);
    setPreviewLoading(true);
    setFieldStrategy("keep_target");
    setMergeNotes("");
    setApproveLowConfidence(false);
    setMergeResult(null);
    fetchCardMergePreview(pair.source_card.id, pair.target_card.id)
      .then(setPreview)
      .catch((err) => {
        if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
        else setPreviewError("Failed to load merge preview.");
      })
      .finally(() => setPreviewLoading(false));
  }

  function closePreview() {
    setPreviewPair(null);
    setPreview(null);
    setPreviewError(null);
    setMergeResult(null);
  }

  async function runMerge(dryRun: boolean) {
    if (!previewPair) return;
    setPendingAction(dryRun ? "dry-run" : "execute");
    setActionError(null);
    try {
      const result = await mergeCards({
        source_card_id: previewPair.source_card.id,
        target_card_id: previewPair.target_card.id,
        dry_run: dryRun,
        merge_notes: mergeNotes.trim() || undefined,
        field_strategy: fieldStrategy,
        approve_low_confidence: approveLowConfidence,
      });
      setMergeResult(result);
      if (!dryRun) load();
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
      else setActionError("Failed to merge cards.");
    } finally {
      setPendingAction(null);
    }
  }

  async function runBulkPreview() {
    setBulkLoading(true);
    setBulkError(null);
    try {
      const result = await bulkPreviewCardDuplicates({
        min_score: bulkMinScore,
        confidence_label: bulkConfidenceLabel || null,
        limit: bulkLimit,
      });
      setBulkPreviews(result.previews);
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
      else setBulkError("Failed to load bulk merge previews.");
    } finally {
      setBulkLoading(false);
    }
  }

  const summaryCards: { label: string; value: number | undefined }[] = summary
    ? [
        { label: "Total pairs", value: summary.total_pairs },
        { label: "Exact duplicates", value: summary.exact_duplicate_count },
        { label: "Likely duplicates", value: summary.likely_duplicate_count },
        { label: "Possible duplicates", value: summary.possible_duplicate_count },
        { label: "Weak matches", value: summary.weak_match_count },
        { label: "Inactive merged cards", value: summary.inactive_merged_cards },
      ]
    : [];

  const requiresApproval = preview !== null && preview.duplicate_score < 75;

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <PageHeader
          title="Card Duplicate Review"
          description="Review duplicate canonical cards and merge identities safely."
          actions={<AdminLogoutButton />}
        />
        <div className="mb-4 flex flex-wrap gap-3 text-xs text-text-muted">
          <Link href="/admin/cards" className="text-sky-400 hover:underline">
            Card catalog
          </Link>
          <Link href="/admin/card-audit" className="text-sky-400 hover:underline">
            Card audit
          </Link>
          <Link href="/admin/catalog-coverage" className="text-sky-400 hover:underline">
            Catalog coverage
          </Link>
          <Link href="/admin/system-check" className="text-sky-400 hover:underline">
            System check
          </Link>
          <Link href="/admin/catalog-ops" className="text-sky-400 hover:underline">
            Catalog operations
          </Link>
        </div>

        {unauthorized && <AdminAuthGate onTokenSaved={() => window.location.reload()} />}

        {!unauthorized && (
          <>
            {summary && (
              <StatGrid>
                {summaryCards.map((c) => (
                  <StatCard key={c.label} label={c.label} value={c.value} />
                ))}
              </StatGrid>
            )}

            <FilterBar>
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search card code / name…"
                className={`w-56 ${FILTER_INPUT_CLASS}`}
              />
              <input
                value={setCode}
                onChange={(e) => setSetCode(e.target.value)}
                placeholder="Set code"
                className={`w-28 ${FILTER_INPUT_CLASS}`}
              />
              <input
                value={rarity}
                onChange={(e) => setRarity(e.target.value)}
                placeholder="Rarity"
                className={`w-24 ${FILTER_INPUT_CLASS}`}
              />
              <input
                value={variant}
                onChange={(e) => setVariant(e.target.value)}
                placeholder="Variant"
                className={`w-28 ${FILTER_INPUT_CLASS}`}
              />
              <input
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                placeholder="Language"
                className={`w-24 ${FILTER_INPUT_CLASS}`}
              />
              <select
                value={confidenceLabel}
                onChange={(e) => setConfidenceLabel(e.target.value)}
                className={FILTER_INPUT_CLASS}
              >
                {CONFIDENCE_LABEL_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {v || "Any confidence"}
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-1 text-xs text-text-secondary">
                Min score
                <input
                  type="number"
                  value={minScore}
                  onChange={(e) => setMinScore(Number(e.target.value) || 0)}
                  className={`w-16 ${FILTER_INPUT_CLASS}`}
                />
              </label>
              <label className="flex items-center gap-1 text-xs text-text-secondary">
                <input
                  type="checkbox"
                  checked={includeInactive}
                  onChange={(e) => setIncludeInactive(e.target.checked)}
                />
                Include inactive
              </label>
            </FilterBar>

            {status === "loading" && <LoadingState>Loading duplicate pairs…</LoadingState>}
            {status === "error" && (
              <ErrorState>Failed to load duplicate cards from the API. Is the backend running?</ErrorState>
            )}

            {status === "ready" && (
              <DataTableShell isEmpty={pairs.length === 0} emptyLabel="No duplicate pairs found.">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th className="text-right">Score</th>
                      <th>Confidence</th>
                      <th>Source card</th>
                      <th>Target card</th>
                      <th>Explanation</th>
                      <th>Warnings</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pairs.map((pair) => (
                      <tr key={`${pair.source_card.id}-${pair.target_card.id}`}>
                        <td className="mono tabular text-right text-text-secondary">{pair.score}</td>
                        <td>
                          <ConfidenceBadge label={pair.confidence_label} />
                        </td>
                        <td>
                          <CardCell card={pair.source_card} />
                        </td>
                        <td>
                          <CardCell card={pair.target_card} />
                        </td>
                        <td className="max-w-[14rem]">
                          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
                            {pair.explanation.positive.map((p) => (
                              <span key={p} className="text-emerald-400">
                                + {p}
                              </span>
                            ))}
                            {pair.explanation.negative.map((n) => (
                              <span key={n} className="text-signal-red">
                                − {n}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="max-w-[10rem] text-[11px] text-signal-warning">
                          {pair.warnings.map((w) => (
                            <div key={w}>{w}</div>
                          ))}
                        </td>
                        <td>
                          <ActionButton onClick={() => openPreview(pair)}>Preview merge</ActionButton>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </DataTableShell>
            )}

            {status === "ready" && (
              <div className="mt-3">
                <PaginationControls offset={offset} limit={limit} total={total} onOffsetChange={setOffset} limitOptions={LIMIT_OPTIONS} onLimitChange={setLimit} />
              </div>
            )}

            <div className="panel mt-8 p-3">
              <div className="mb-3 text-sm font-medium text-text-primary">Bulk merge suggestions (preview only)</div>
              <FilterBar>
                <label className="flex items-center gap-1 text-xs text-text-secondary">
                  Min score
                  <input
                    type="number"
                    value={bulkMinScore}
                    onChange={(e) => setBulkMinScore(Number(e.target.value) || 0)}
                    className={`w-20 ${FILTER_INPUT_CLASS}`}
                  />
                </label>
                <select
                  value={bulkConfidenceLabel}
                  onChange={(e) => setBulkConfidenceLabel(e.target.value)}
                  className={FILTER_INPUT_CLASS}
                >
                  {CONFIDENCE_LABEL_OPTIONS.map((v) => (
                    <option key={v} value={v}>
                      {v || "Any confidence"}
                    </option>
                  ))}
                </select>
                <label className="flex items-center gap-1 text-xs text-text-secondary">
                  Limit
                  <input
                    type="number"
                    value={bulkLimit}
                    onChange={(e) => setBulkLimit(Number(e.target.value) || 50)}
                    className={`w-20 ${FILTER_INPUT_CLASS}`}
                  />
                </label>
                <ActionButton variant="preview" onClick={runBulkPreview} disabled={bulkLoading}>
                  {bulkLoading ? "Loading…" : "Bulk preview"}
                </ActionButton>
              </FilterBar>
              {bulkError && <div className="mb-3 text-sm text-signal-red">{bulkError}</div>}
              {bulkPreviews && bulkPreviews.length === 0 && (
                <EmptyState variant="inline">No clear duplicate pairs match these filters.</EmptyState>
              )}
              {bulkPreviews && bulkPreviews.length > 0 && (
                <div className="space-y-2">
                  {bulkPreviews.map((p) => (
                    <div
                      key={`${p.source_card.id}-${p.target_card.id}`}
                      className="rounded-control border border-border-default bg-bg-page p-2 text-xs text-text-secondary"
                    >
                      <span className="mono font-medium text-text-primary">{p.source_card.card_code}</span>
                      {" → "}
                      <span className="mono font-medium text-text-primary">{p.target_card.card_code}</span>
                      {" · score "}
                      {p.duplicate_score} ({p.confidence_label})
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

        <ConfirmActionModal
          open={previewPair !== null}
          title="Merge preview"
          description={
            previewPair
              ? `${previewPair.source_card.card_code} → ${previewPair.target_card.card_code}`
              : undefined
          }
          affectedRecords={
            preview
              ? Object.entries(preview.affected_records).map(([key, value]) => ({
                  label: key,
                  value,
                }))
              : undefined
          }
          confirmPhrase={MERGE_CONFIRM_PHRASE}
          confirmLabel="Execute merge"
          pending={pendingAction === "execute"}
          disableConfirm={requiresApproval && !approveLowConfidence}
          error={actionError}
          onConfirm={() => runMerge(false)}
          onCancel={closePreview}
        >
          {previewLoading && <p className="p-6 text-center text-sm text-text-muted">Loading preview…</p>}
          {previewError && (
            <div className="rounded-control border border-signal-red/40 bg-signal-red/10 p-3 text-sm text-signal-red">
              {previewError}
            </div>
          )}

          {!previewLoading && preview && previewPair && (
            <>
              <div className="mb-3 flex items-center gap-2 text-sm">
                <span className="text-text-secondary">Score {preview.duplicate_score}</span>
                <ConfidenceBadge label={preview.confidence_label} />
              </div>

              <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                {preview.explanation.positive.map((p) => (
                  <span key={p} className="text-emerald-400">
                    + {p}
                  </span>
                ))}
                {preview.explanation.negative.map((n) => (
                  <span key={n} className="text-signal-red">
                    − {n}
                  </span>
                ))}
                {preview.explanation.caps_applied.map((c) => (
                  <span key={c} className="text-signal-warning">
                    cap: {c}
                  </span>
                ))}
              </div>

              {preview.warnings.length > 0 && (
                <div className="mb-3 rounded-control border border-signal-warning/40 bg-signal-warning/10 p-2 text-xs text-signal-warning">
                  {preview.warnings.map((w) => (
                    <div key={w}>{w}</div>
                  ))}
                </div>
              )}

              {Object.keys(preview.field_merge_preview).length > 0 && (
                <div className="mb-3 panel p-3">
                  <div className="mb-2 text-xs font-medium text-text-secondary">Field merge preview</div>
                  <div className="space-y-1 text-xs text-text-secondary">
                    {Object.entries(preview.field_merge_preview).map(([field, change]) => (
                      <div key={field}>
                        <span className="font-medium text-text-primary">{field}</span>: {String(change.source ?? "—")}
                        {" → "}
                        {String(change.result ?? "—")} ({change.action})
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="mb-3 panel p-3">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <select
                    value={fieldStrategy}
                    onChange={(e) => {
                      setFieldStrategy(e.target.value as CardMergeFieldStrategy);
                      fetchCardMergePreview(
                        previewPair.source_card.id,
                        previewPair.target_card.id,
                        e.target.value as CardMergeFieldStrategy,
                      )
                        .then(setPreview)
                        .catch(() => {});
                    }}
                    className={FILTER_INPUT_CLASS}
                  >
                    {FIELD_STRATEGY_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                  <input
                    value={mergeNotes}
                    onChange={(e) => setMergeNotes(e.target.value)}
                    placeholder="Merge notes (optional)…"
                    className={`w-64 ${FILTER_INPUT_CLASS}`}
                  />
                </div>

                {requiresApproval && (
                  <label className="mb-2 flex items-center gap-1 text-xs text-signal-warning">
                    <input
                      type="checkbox"
                      checked={approveLowConfidence}
                      onChange={(e) => setApproveLowConfidence(e.target.checked)}
                    />
                    Approve low-confidence merge (score below 75)
                  </label>
                )}

                <ActionButton
                  variant="dry-run"
                  onClick={() => runMerge(true)}
                  disabled={pendingAction === "dry-run"}
                >
                  Dry-run merge
                </ActionButton>
              </div>

              {mergeResult && (
                <div className="panel p-3 text-xs text-text-secondary">
                  <div>dry_run: {String(mergeResult.dry_run)}</div>
                  <div>merged: {String(mergeResult.merged)}</div>
                  {mergeResult.warnings.map((w) => (
                    <div key={w} className="text-signal-warning">
                      {w}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </ConfirmActionModal>
      </main>
    </div>
  );
}
