"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { PaginationControls } from "@/components/PaginationControls";
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
  exact_duplicate: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  likely_duplicate: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  possible_duplicate: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  weak_match: "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30",
  not_duplicate: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
};

const MERGE_CONFIRM_PHRASE = "MERGE";

function ConfidenceBadge({ label }: { label: string }) {
  const style = CONFIDENCE_STYLES[label] ?? "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}>
      {label}
    </span>
  );
}

function CardCell({ card }: { card: DuplicatePair["source_card"] }) {
  return (
    <div>
      <Link href={`/cards/${card.id}`} className="text-sky-400 hover:underline">
        {card.card_code}
      </Link>
      <div className="text-xs text-neutral-500">{cardDisplayName(card)}</div>
      <div className="text-[10px] text-neutral-600">
        {card.set_code} / {card.rarity} / {card.variant ?? "base"} / {card.language}
        {!card.is_active && " / inactive"}
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
  const [confirmText, setConfirmText] = useState("");

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
    setConfirmText("");
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
  const canExecute = confirmText.trim() === MERGE_CONFIRM_PHRASE && (!requiresApproval || approveLowConfidence);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-1 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">Card Duplicate Review</h1>
          <AdminLogoutButton />
        </div>
        <p className="mb-4 text-sm text-neutral-500">
          Review duplicate canonical cards and merge identities safely.
        </p>
        <div className="mb-4 flex flex-wrap gap-3 text-xs text-neutral-500">
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
        </div>

        {unauthorized && <AdminAuthGate onTokenSaved={() => window.location.reload()} />}

        {!unauthorized && (
          <>
            {summary && (
              <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-6">
                {summaryCards.map((c) => (
                  <div key={c.label} className="rounded-lg border border-neutral-800 bg-neutral-900 p-3">
                    <div className="text-xs text-neutral-500">{c.label}</div>
                    <div className="text-lg font-semibold text-neutral-100">{c.value}</div>
                  </div>
                ))}
              </div>
            )}

            <div className="mb-4 flex flex-wrap items-center gap-2">
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search card code / name…"
                className="w-56 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
              />
              <input
                value={setCode}
                onChange={(e) => setSetCode(e.target.value)}
                placeholder="Set code"
                className="w-28 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
              />
              <input
                value={rarity}
                onChange={(e) => setRarity(e.target.value)}
                placeholder="Rarity"
                className="w-24 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
              />
              <input
                value={variant}
                onChange={(e) => setVariant(e.target.value)}
                placeholder="Variant"
                className="w-28 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
              />
              <input
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                placeholder="Language"
                className="w-24 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
              />
              <select
                value={confidenceLabel}
                onChange={(e) => setConfidenceLabel(e.target.value)}
                className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
              >
                {CONFIDENCE_LABEL_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {v || "Any confidence"}
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-1 text-xs text-neutral-400">
                Min score
                <input
                  type="number"
                  value={minScore}
                  onChange={(e) => setMinScore(Number(e.target.value) || 0)}
                  className="w-16 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
              </label>
              <label className="flex items-center gap-1 text-xs text-neutral-400">
                <input
                  type="checkbox"
                  checked={includeInactive}
                  onChange={(e) => setIncludeInactive(e.target.checked)}
                />
                Include inactive
              </label>
            </div>

            {actionError && (
              <div className="mb-4 rounded-lg border border-rose-900/50 bg-rose-950/30 p-3 text-sm text-rose-300">{actionError}</div>
            )}

            {status === "loading" && (
              <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">Loading duplicate pairs…</div>
            )}
            {status === "error" && (
              <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
                Failed to load duplicate cards from the API. Is the backend running?
              </div>
            )}
            {status === "ready" && pairs.length === 0 && (
              <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">No duplicate pairs found.</div>
            )}

            {status === "ready" && pairs.length > 0 && (
              <div className="overflow-x-auto rounded-lg border border-neutral-800">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wide text-neutral-500">
                      <th className="px-3 py-2 font-medium text-right">Score</th>
                      <th className="px-3 py-2 font-medium">Confidence</th>
                      <th className="px-3 py-2 font-medium">Source card</th>
                      <th className="px-3 py-2 font-medium">Target card</th>
                      <th className="px-3 py-2 font-medium">Explanation</th>
                      <th className="px-3 py-2 font-medium">Warnings</th>
                      <th className="px-3 py-2 font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pairs.map((pair) => (
                      <tr
                        key={`${pair.source_card.id}-${pair.target_card.id}`}
                        className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                      >
                        <td className="px-3 py-2 text-right text-neutral-300">{pair.score}</td>
                        <td className="px-3 py-2">
                          <ConfidenceBadge label={pair.confidence_label} />
                        </td>
                        <td className="px-3 py-2">
                          <CardCell card={pair.source_card} />
                        </td>
                        <td className="px-3 py-2">
                          <CardCell card={pair.target_card} />
                        </td>
                        <td className="px-3 py-2 max-w-[14rem]">
                          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
                            {pair.explanation.positive.map((p) => (
                              <span key={p} className="text-emerald-400">
                                + {p}
                              </span>
                            ))}
                            {pair.explanation.negative.map((n) => (
                              <span key={n} className="text-rose-400">
                                − {n}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="px-3 py-2 max-w-[10rem] text-[11px] text-amber-400">
                          {pair.warnings.map((w) => (
                            <div key={w}>{w}</div>
                          ))}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex flex-wrap gap-1.5">
                            <button
                              onClick={() => openPreview(pair)}
                              className="rounded bg-neutral-800 px-2 py-1 text-xs font-medium text-neutral-200 hover:bg-neutral-700"
                            >
                              Preview merge
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {status === "ready" && (
              <div className="mt-3">
                <PaginationControls offset={offset} limit={limit} total={total} onOffsetChange={setOffset} limitOptions={LIMIT_OPTIONS} onLimitChange={setLimit} />
              </div>
            )}

            <div className="mt-8 rounded-lg border border-neutral-800 bg-neutral-900 p-3">
              <div className="mb-3 text-sm font-medium text-neutral-200">Bulk merge suggestions (preview only)</div>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-1 text-xs text-neutral-400">
                  Min score
                  <input
                    type="number"
                    value={bulkMinScore}
                    onChange={(e) => setBulkMinScore(Number(e.target.value) || 0)}
                    className="w-20 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                  />
                </label>
                <select
                  value={bulkConfidenceLabel}
                  onChange={(e) => setBulkConfidenceLabel(e.target.value)}
                  className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                >
                  {CONFIDENCE_LABEL_OPTIONS.map((v) => (
                    <option key={v} value={v}>
                      {v || "Any confidence"}
                    </option>
                  ))}
                </select>
                <label className="flex items-center gap-1 text-xs text-neutral-400">
                  Limit
                  <input
                    type="number"
                    value={bulkLimit}
                    onChange={(e) => setBulkLimit(Number(e.target.value) || 50)}
                    className="w-20 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                  />
                </label>
                <button
                  onClick={runBulkPreview}
                  disabled={bulkLoading}
                  className="rounded bg-neutral-800 px-2.5 py-1 text-xs font-medium text-neutral-200 hover:bg-neutral-700 disabled:opacity-50"
                >
                  {bulkLoading ? "Loading…" : "Bulk preview"}
                </button>
              </div>
              {bulkError && <div className="mb-3 text-sm text-rose-300">{bulkError}</div>}
              {bulkPreviews && bulkPreviews.length === 0 && (
                <div className="text-sm text-neutral-500">No clear duplicate pairs match these filters.</div>
              )}
              {bulkPreviews && bulkPreviews.length > 0 && (
                <div className="space-y-2">
                  {bulkPreviews.map((p) => (
                    <div
                      key={`${p.source_card.id}-${p.target_card.id}`}
                      className="rounded border border-neutral-800 bg-neutral-950 p-2 text-xs text-neutral-300"
                    >
                      <span className="font-medium text-neutral-100">{p.source_card.card_code}</span>
                      {" → "}
                      <span className="font-medium text-neutral-100">{p.target_card.card_code}</span>
                      {" · score "}
                      {p.duplicate_score} ({p.confidence_label})
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

        {previewPair && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
            <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-lg border border-neutral-800 bg-neutral-950 p-5">
              <div className="mb-3 flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-base font-semibold text-neutral-100">Merge preview</h2>
                  <div className="text-xs text-neutral-500">
                    {previewPair.source_card.card_code} → {previewPair.target_card.card_code}
                  </div>
                </div>
                <button onClick={closePreview} className="rounded px-2 py-1 text-xs font-medium text-neutral-400 hover:text-neutral-100">
                  Close
                </button>
              </div>

              {previewLoading && <div className="p-6 text-center text-sm text-neutral-500">Loading preview…</div>}
              {previewError && <div className="rounded border border-rose-900/50 bg-rose-950/30 p-3 text-sm text-rose-300">{previewError}</div>}

              {!previewLoading && preview && (
                <>
                  <div className="mb-3 flex items-center gap-2 text-sm">
                    <span className="text-neutral-400">Score {preview.duplicate_score}</span>
                    <ConfidenceBadge label={preview.confidence_label} />
                  </div>

                  <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                    {preview.explanation.positive.map((p) => (
                      <span key={p} className="text-emerald-400">
                        + {p}
                      </span>
                    ))}
                    {preview.explanation.negative.map((n) => (
                      <span key={n} className="text-rose-400">
                        − {n}
                      </span>
                    ))}
                    {preview.explanation.caps_applied.map((c) => (
                      <span key={c} className="text-amber-400">
                        cap: {c}
                      </span>
                    ))}
                  </div>

                  {preview.warnings.length > 0 && (
                    <div className="mb-3 rounded border border-amber-900/50 bg-amber-950/20 p-2 text-xs text-amber-300">
                      {preview.warnings.map((w) => (
                        <div key={w}>{w}</div>
                      ))}
                    </div>
                  )}

                  <div className="mb-3 rounded border border-neutral-800 bg-neutral-900 p-3">
                    <div className="mb-2 text-xs font-medium text-neutral-400">Affected records</div>
                    <div className="grid grid-cols-2 gap-1 text-xs text-neutral-300 sm:grid-cols-3">
                      {Object.entries(preview.affected_records).map(([key, value]) => (
                        <div key={key}>
                          {key}: <span className="text-neutral-100">{value}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {Object.keys(preview.field_merge_preview).length > 0 && (
                    <div className="mb-3 rounded border border-neutral-800 bg-neutral-900 p-3">
                      <div className="mb-2 text-xs font-medium text-neutral-400">Field merge preview</div>
                      <div className="space-y-1 text-xs text-neutral-300">
                        {Object.entries(preview.field_merge_preview).map(([field, change]) => (
                          <div key={field}>
                            <span className="font-medium text-neutral-100">{field}</span>: {String(change.source ?? "—")}
                            {" → "}
                            {String(change.result ?? "—")} ({change.action})
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="mb-3 rounded border border-neutral-800 bg-neutral-900 p-3">
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
                        className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
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
                        className="w-64 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
                      />
                    </div>

                    {requiresApproval && (
                      <label className="mb-2 flex items-center gap-1 text-xs text-amber-300">
                        <input
                          type="checkbox"
                          checked={approveLowConfidence}
                          onChange={(e) => setApproveLowConfidence(e.target.checked)}
                        />
                        Approve low-confidence merge (score below 75)
                      </label>
                    )}

                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        onClick={() => runMerge(true)}
                        disabled={pendingAction === "dry-run"}
                        className="rounded bg-neutral-800 px-2.5 py-1 text-xs font-medium text-neutral-200 hover:bg-neutral-700 disabled:opacity-50"
                      >
                        Dry-run merge
                      </button>
                      <input
                        value={confirmText}
                        onChange={(e) => setConfirmText(e.target.value)}
                        placeholder={`Type ${MERGE_CONFIRM_PHRASE} to confirm`}
                        className="w-48 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
                      />
                      <button
                        onClick={() => runMerge(false)}
                        disabled={!canExecute || pendingAction === "execute"}
                        className="rounded bg-rose-950/60 px-2.5 py-1 text-xs font-medium text-rose-300 hover:bg-rose-900/60 disabled:opacity-50"
                      >
                        Execute merge
                      </button>
                    </div>
                  </div>

                  {mergeResult && (
                    <div className="rounded border border-neutral-800 bg-neutral-900 p-3 text-xs text-neutral-300">
                      <div>dry_run: {String(mergeResult.dry_run)}</div>
                      <div>merged: {String(mergeResult.merged)}</div>
                      {mergeResult.warnings.map((w) => (
                        <div key={w} className="text-amber-400">
                          {w}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
