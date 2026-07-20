"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { PaginationControls } from "@/components/PaginationControls";
import {
  AdminAuthRequiredError,
  type BulkMappingAction,
  type Card,
  type MappingQualityItem,
  type MappingQualitySummary,
  type RecheckQualityResult,
  type SuggestedCardsForMapping,
  bulkUpdateMappings,
  fetchCards,
  fetchMappingQuality,
  fetchSuggestedCardsForMapping,
  recheckMappingQuality,
  replaceMappingCard,
} from "@/lib/api";
import { cardDisplayName, formatDateTime } from "@/lib/format";

const RISK_FILTERS = [
  { value: "", label: "All" },
  { value: "critical", label: "Critical" },
  { value: "warning", label: "Warning" },
  { value: "review", label: "Review" },
  { value: "ok", label: "OK" },
];

const REVIEW_STATUS_OPTIONS = ["", "approved", "needs_review", "rejected"];
const CONFIDENCE_LABEL_OPTIONS = ["", "exact", "high", "medium", "low", "very_low", "unknown"];
const ISSUE_TYPE_OPTIONS = [
  "",
  "low_confidence",
  "card_code_mismatch",
  "set_code_mismatch",
  "variant_mismatch",
  "duplicate_source_url",
  "inactive_with_recent_price",
  "active_without_recent_price",
  "stale_mapping",
  "unverified_mapping",
  "missing_source_url",
  "missing_card_reference",
];

const RISK_STYLES: Record<string, string> = {
  ok: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  review: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  warning: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  critical: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
};

const LIMIT_OPTIONS = [50, 100, 200, 500] as const;

const DESTRUCTIVE_ACTIONS: BulkMappingAction[] = ["reject", "deactivate"];

const BULK_ACTIONS: { action: BulkMappingAction; label: string; className: string }[] = [
  { action: "approve", label: "Approve", className: "bg-emerald-800/60 text-emerald-200 hover:bg-emerald-700/60" },
  { action: "reject", label: "Reject", className: "bg-rose-950/60 text-rose-300 hover:bg-rose-900/60" },
  { action: "deactivate", label: "Deactivate", className: "bg-rose-950/60 text-rose-300 hover:bg-rose-900/60" },
  { action: "activate", label: "Activate", className: "bg-neutral-800 text-neutral-200 hover:bg-neutral-700" },
  { action: "mark_verified", label: "Mark verified", className: "bg-neutral-800 text-neutral-200 hover:bg-neutral-700" },
  { action: "mark_pending", label: "Mark pending", className: "bg-neutral-800 text-neutral-200 hover:bg-neutral-700" },
];

function RiskBadge({ level }: { level: string }) {
  const style = RISK_STYLES[level] ?? "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}>
      {level}
    </span>
  );
}

export default function SourceMappingQualityPage() {
  const [unauthorized, setUnauthorized] = useState(false);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [items, setItems] = useState<MappingQualityItem[]>([]);
  const [summary, setSummary] = useState<MappingQualitySummary | null>(null);
  const [total, setTotal] = useState(0);

  const [source, setSource] = useState("");
  const [reviewStatus, setReviewStatus] = useState("");
  const [isActive, setIsActive] = useState("");
  const [manualVerified, setManualVerified] = useState("");
  const [confidenceLabel, setConfidenceLabel] = useState("");
  const [riskLevel, setRiskLevel] = useState("");
  const [issueType, setIssueType] = useState("");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);

  const [recheckLimit, setRecheckLimit] = useState(100);
  const [recheckResult, setRecheckResult] = useState<RecheckQualityResult | null>(null);
  const [bulkToolsOpen, setBulkToolsOpen] = useState(false);
  const [bulkResults, setBulkResults] = useState<
    { action: string; results: { mapping_id: number; ok: boolean; error: string | null }[] } | null
  >(null);

  const [cards, setCards] = useState<Card[]>([]);
  const [detailMapping, setDetailMapping] = useState<MappingQualityItem | null>(null);
  const [detailData, setDetailData] = useState<SuggestedCardsForMapping | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [selectedCardId, setSelectedCardId] = useState<number | null>(null);
  const [cardQuery, setCardQuery] = useState("");
  const [reviewNotes, setReviewNotes] = useState("");

  useEffect(() => {
    setOffset(0);
  }, [source, reviewStatus, isActive, manualVerified, confidenceLabel, riskLevel, issueType, q, limit]);

  function load() {
    let cancelled = false;
    fetchMappingQuality({
      source: source || undefined,
      review_status: reviewStatus || undefined,
      is_active: isActive === "" ? undefined : isActive === "true",
      manual_verified: manualVerified === "" ? undefined : manualVerified === "true",
      confidence_label: confidenceLabel || undefined,
      risk_level: riskLevel || undefined,
      issue_type: issueType || undefined,
      q: q || undefined,
      limit,
      offset,
    })
      .then((data) => {
        if (cancelled) return;
        setItems(data.items);
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
  }, [source, reviewStatus, isActive, manualVerified, confidenceLabel, riskLevel, issueType, q, limit, offset]);

  useEffect(() => {
    fetchCards()
      .then(setCards)
      .catch(() => setCards([]));
  }, []);

  const filteredCards = useMemo(() => {
    const query = cardQuery.trim().toLowerCase();
    if (!query) return cards.slice(0, 25);
    return cards
      .filter((card) =>
        [card.card_code, card.name_en, card.name_jp].filter(Boolean).some((f) => f!.toLowerCase().includes(query)),
      )
      .slice(0, 25);
  }, [cards, cardQuery]);

  function updateItem(updated: MappingQualityItem) {
    setItems((prev) => prev.map((i) => (i.mapping_id === updated.mapping_id ? updated : i)));
  }

  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAllOnPage() {
    setSelected((prev) => {
      const allSelected = items.length > 0 && items.every((i) => prev.has(i.mapping_id));
      if (allSelected) return new Set();
      return new Set(items.map((i) => i.mapping_id));
    });
  }

  async function runBulkAction(action: BulkMappingAction) {
    if (selected.size === 0) return;
    if (DESTRUCTIVE_ACTIONS.includes(action)) {
      const confirmed = window.confirm(
        `${action === "reject" ? "Reject" : "Deactivate"} ${selected.size} selected mapping(s)?`,
      );
      if (!confirmed) return;
    }
    setPendingAction(action);
    setActionError(null);
    try {
      const result = await bulkUpdateMappings(Array.from(selected), action, undefined);
      setBulkResults(result);
      load();
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
      else setActionError(`Failed to apply bulk action: ${action}.`);
    } finally {
      setPendingAction(null);
    }
  }

  async function runRecheck(dryRun: boolean) {
    setPendingAction(dryRun ? "recheck-dry" : "recheck-real");
    setActionError(null);
    try {
      const result = await recheckMappingQuality({
        source: source || undefined,
        review_status: reviewStatus || undefined,
        is_active: isActive === "" ? undefined : isActive === "true",
        manual_verified: manualVerified === "" ? undefined : manualVerified === "true",
        limit: recheckLimit,
        dry_run: dryRun,
      });
      setRecheckResult(result);
      if (!dryRun) load();
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
      else setActionError("Failed to recheck mapping quality.");
    } finally {
      setPendingAction(null);
    }
  }

  function openSuggested(item: MappingQualityItem) {
    setDetailMapping(item);
    setDetailData(null);
    setDetailError(null);
    setDetailLoading(true);
    setSelectedCardId(item.card_id);
    setCardQuery("");
    setReviewNotes("");
    fetchSuggestedCardsForMapping(item.mapping_id)
      .then(setDetailData)
      .catch((err) => {
        if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
        else setDetailError("Failed to load suggested cards.");
      })
      .finally(() => setDetailLoading(false));
  }

  function closeDetail() {
    setDetailMapping(null);
    setDetailData(null);
    setDetailError(null);
  }

  async function handleReplace(cardId: number, approve: boolean) {
    if (!detailMapping) return;
    setPendingAction(`replace-${detailMapping.mapping_id}`);
    setActionError(null);
    try {
      const updated = await replaceMappingCard(
        detailMapping.mapping_id,
        cardId,
        reviewNotes.trim() || undefined,
        approve,
      );
      updateItem(updated);
      closeDetail();
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
      else setActionError("Failed to replace mapped card.");
    } finally {
      setPendingAction(null);
    }
  }

  async function quickAction(mappingId: number, action: BulkMappingAction) {
    if (DESTRUCTIVE_ACTIONS.includes(action)) {
      const confirmed = window.confirm(`${action === "reject" ? "Reject" : "Deactivate"} this mapping?`);
      if (!confirmed) return;
    }
    setPendingAction(`row-${mappingId}`);
    setActionError(null);
    try {
      await bulkUpdateMappings([mappingId], action, undefined);
      load();
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
      else setActionError("Failed to apply action.");
    } finally {
      setPendingAction(null);
    }
  }

  const allOnPageSelected = items.length > 0 && items.every((i) => selected.has(i.mapping_id));

  const summaryCards: { label: string; value: number | undefined }[] = summary
    ? [
        { label: "Total mappings", value: summary.total_mappings },
        { label: "OK", value: summary.ok_count },
        { label: "Review", value: summary.review_count },
        { label: "Warning", value: summary.warning_count },
        { label: "Critical", value: summary.critical_count },
        { label: "Low confidence", value: summary.low_confidence_count },
        { label: "Duplicate URLs", value: summary.duplicate_source_url_count },
        { label: "Stale mappings", value: summary.stale_mapping_count },
        { label: "Unverified", value: summary.unverified_count },
        { label: "Inactive w/ recent price", value: summary.inactive_with_recent_price_count },
        { label: "Active w/o recent price", value: summary.active_without_recent_price_count },
      ]
    : [];

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-1 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">Source Mapping Quality</h1>
          <AdminLogoutButton />
        </div>
        <p className="mb-4 text-sm text-neutral-500">
          Review mapping confidence, mismatches, stale mappings, and duplicate source URLs.
        </p>

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
              <select value={source} onChange={(e) => setSource(e.target.value)} className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100">
                <option value="">Any source</option>
                <option value="yuyutei">yuyutei</option>
                <option value="snkrdunk">snkrdunk</option>
              </select>
              <select value={reviewStatus} onChange={(e) => setReviewStatus(e.target.value)} className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100">
                {REVIEW_STATUS_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {v || "Any review status"}
                  </option>
                ))}
              </select>
              <select value={isActive} onChange={(e) => setIsActive(e.target.value)} className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100">
                <option value="">Active: any</option>
                <option value="true">Active only</option>
                <option value="false">Inactive only</option>
              </select>
              <select value={manualVerified} onChange={(e) => setManualVerified(e.target.value)} className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100">
                <option value="">Verified: any</option>
                <option value="true">Verified only</option>
                <option value="false">Unverified only</option>
              </select>
              <select value={confidenceLabel} onChange={(e) => setConfidenceLabel(e.target.value)} className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100">
                {CONFIDENCE_LABEL_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {v || "Any confidence"}
                  </option>
                ))}
              </select>
              <select value={issueType} onChange={(e) => setIssueType(e.target.value)} className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100">
                {ISSUE_TYPE_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {v || "Any issue type"}
                  </option>
                ))}
              </select>
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search URL / source id / card code…"
                className="w-56 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
              />
            </div>

            <div className="mb-4 flex gap-1">
              {RISK_FILTERS.map((f) => (
                <button
                  key={f.value}
                  onClick={() => setRiskLevel(f.value)}
                  className={`rounded px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                    riskLevel === f.value
                      ? "bg-neutral-100 text-neutral-900 ring-neutral-100"
                      : "bg-neutral-900 text-neutral-400 ring-neutral-800 hover:text-neutral-100"
                  }`}
                >
                  {f.label}
                </button>
              ))}
              <button
                onClick={() => setBulkToolsOpen((v) => !v)}
                className="ml-auto rounded bg-neutral-800 px-2.5 py-1 text-xs font-medium text-neutral-200 hover:bg-neutral-700"
              >
                {bulkToolsOpen ? "Hide bulk tools" : "Bulk tools…"}
              </button>
            </div>

            {bulkToolsOpen && (
              <div className="mb-4 rounded-lg border border-neutral-800 bg-neutral-900 p-3">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <span className="text-xs text-neutral-500">Recheck quality (uses current source/review/active/verified filters):</span>
                  <input
                    type="number"
                    value={recheckLimit}
                    onChange={(e) => setRecheckLimit(Number(e.target.value) || 100)}
                    className="w-24 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                  />
                  <button
                    onClick={() => runRecheck(true)}
                    disabled={pendingAction === "recheck-dry"}
                    className="rounded bg-neutral-800 px-2.5 py-1 text-xs font-medium text-neutral-200 hover:bg-neutral-700 disabled:opacity-50"
                  >
                    Dry run
                  </button>
                  <button
                    onClick={() => runRecheck(false)}
                    disabled={pendingAction === "recheck-real"}
                    className="rounded bg-emerald-800/60 px-2.5 py-1 text-xs font-medium text-emerald-200 hover:bg-emerald-700/60 disabled:opacity-50"
                  >
                    Apply real run
                  </button>
                </div>
                {recheckResult && (
                  <div className="mb-3 flex flex-wrap gap-4 text-xs text-neutral-400">
                    <span>dry_run: {String(recheckResult.dry_run)}</span>
                    <span>selected: {recheckResult.summary.selected}</span>
                    <span>would_update: {recheckResult.summary.would_update}</span>
                    <span>updated: {recheckResult.summary.updated}</span>
                    <span>ok: {recheckResult.summary.ok}</span>
                    <span>review: {recheckResult.summary.review}</span>
                    <span>warning: {recheckResult.summary.warning}</span>
                    <span>critical: {recheckResult.summary.critical}</span>
                  </div>
                )}

                <div className="mb-2 text-xs text-neutral-500">
                  Bulk actions apply to {selected.size} selected mapping{selected.size === 1 ? "" : "s"}:
                </div>
                <div className="flex flex-wrap gap-2">
                  {BULK_ACTIONS.map((a) => (
                    <button
                      key={a.action}
                      onClick={() => runBulkAction(a.action)}
                      disabled={selected.size === 0 || pendingAction === a.action}
                      className={`rounded px-2.5 py-1 text-xs font-medium disabled:opacity-50 ${a.className}`}
                    >
                      {a.label}
                    </button>
                  ))}
                </div>
                {bulkResults && (
                  <div className="mt-3 text-xs text-neutral-400">
                    {bulkResults.action}: {bulkResults.results.filter((r) => r.ok).length}/{bulkResults.results.length} succeeded
                    {bulkResults.results.some((r) => !r.ok) && (
                      <span className="text-rose-400">
                        {" "}
                        (failed: {bulkResults.results.filter((r) => !r.ok).map((r) => r.mapping_id).join(", ")})
                      </span>
                    )}
                  </div>
                )}
              </div>
            )}

            {actionError && (
              <div className="mb-4 rounded-lg border border-rose-900/50 bg-rose-950/30 p-3 text-sm text-rose-300">{actionError}</div>
            )}

            {status === "loading" && (
              <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">Loading mappings…</div>
            )}
            {status === "error" && (
              <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
                Failed to load source mappings from the API. Is the backend running?
              </div>
            )}
            {status === "ready" && items.length === 0 && (
              <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">No mappings found.</div>
            )}

            {status === "ready" && items.length > 0 && (
              <div className="overflow-x-auto rounded-lg border border-neutral-800">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wide text-neutral-500">
                      <th className="px-3 py-2">
                        <input type="checkbox" checked={allOnPageSelected} onChange={toggleSelectAllOnPage} />
                      </th>
                      <th className="px-3 py-2 font-medium">Risk</th>
                      <th className="px-3 py-2 font-medium">Issues</th>
                      <th className="px-3 py-2 font-medium">Source</th>
                      <th className="px-3 py-2 font-medium">Mapped card</th>
                      <th className="px-3 py-2 font-medium">URL</th>
                      <th className="px-3 py-2 font-medium">Active</th>
                      <th className="px-3 py-2 font-medium">Verified</th>
                      <th className="px-3 py-2 font-medium">Review</th>
                      <th className="px-3 py-2 font-medium text-right">Score</th>
                      <th className="px-3 py-2 font-medium">Confidence</th>
                      <th className="px-3 py-2 font-medium">Latest price</th>
                      <th className="px-3 py-2 font-medium">Last checked</th>
                      <th className="px-3 py-2 font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <tr key={item.mapping_id} className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60">
                        <td className="px-3 py-2">
                          <input type="checkbox" checked={selected.has(item.mapping_id)} onChange={() => toggleSelect(item.mapping_id)} />
                        </td>
                        <td className="px-3 py-2">
                          <RiskBadge level={item.risk_level} />
                        </td>
                        <td className="px-3 py-2 max-w-[12rem]">
                          <div className="flex flex-wrap gap-1">
                            {item.issue_types.map((t) => (
                              <span key={t} className="rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-400">
                                {t}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="px-3 py-2 text-neutral-400">{item.source_name ?? "—"}</td>
                        <td className="px-3 py-2 text-neutral-300">
                          {item.card_id ? (
                            <Link href={`/cards/${item.card_id}`} className="text-sky-400 hover:underline">
                              {item.card_code ?? item.card_id}
                            </Link>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="px-3 py-2 max-w-[10rem] truncate">
                          {item.source_url ? (
                            <a href={item.source_url} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline">
                              link
                            </a>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="px-3 py-2 text-neutral-400">{item.is_active ? "yes" : "no"}</td>
                        <td className="px-3 py-2 text-neutral-400">{item.manual_verified ? "yes" : "no"}</td>
                        <td className="px-3 py-2 text-neutral-400">{item.review_status}</td>
                        <td className="px-3 py-2 text-right text-neutral-400">{item.match_confidence ?? "—"}</td>
                        <td className="px-3 py-2 text-neutral-400">{item.match_confidence_label}</td>
                        <td className="px-3 py-2 text-xs text-neutral-500">{formatDateTime(item.latest_price_observed_at)}</td>
                        <td className="px-3 py-2 text-xs text-neutral-500">{formatDateTime(item.last_match_checked_at)}</td>
                        <td className="px-3 py-2">
                          <div className="flex flex-wrap gap-1.5">
                            <button
                              onClick={() => openSuggested(item)}
                              className="rounded bg-neutral-800 px-2 py-1 text-xs font-medium text-neutral-200 hover:bg-neutral-700"
                            >
                              Suggested cards
                            </button>
                            <button
                              onClick={() => quickAction(item.mapping_id, "approve")}
                              disabled={pendingAction === `row-${item.mapping_id}`}
                              className="rounded bg-emerald-800/60 px-2 py-1 text-xs font-medium text-emerald-200 hover:bg-emerald-700/60 disabled:opacity-50"
                            >
                              Approve
                            </button>
                            <button
                              onClick={() => quickAction(item.mapping_id, "reject")}
                              disabled={pendingAction === `row-${item.mapping_id}`}
                              className="rounded bg-rose-950/60 px-2 py-1 text-xs font-medium text-rose-300 hover:bg-rose-900/60 disabled:opacity-50"
                            >
                              Reject
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
          </>
        )}

        {detailMapping && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
            <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-lg border border-neutral-800 bg-neutral-950 p-5">
              <div className="mb-3 flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-base font-semibold text-neutral-100">Suggested cards</h2>
                  <div className="text-xs text-neutral-500">
                    Mapping {detailMapping.mapping_id} — {detailMapping.source_card_id}
                  </div>
                  {detailMapping.source_url && (
                    <a href={detailMapping.source_url} target="_blank" rel="noreferrer" className="text-xs text-sky-400 hover:underline">
                      {detailMapping.source_url}
                    </a>
                  )}
                </div>
                <button onClick={closeDetail} className="rounded px-2 py-1 text-xs font-medium text-neutral-400 hover:text-neutral-100">
                  Close
                </button>
              </div>

              {detailLoading && <div className="p-6 text-center text-sm text-neutral-500">Loading suggested cards…</div>}
              {detailError && <div className="rounded border border-rose-900/50 bg-rose-950/30 p-3 text-sm text-rose-300">{detailError}</div>}

              {!detailLoading && detailData && (
                <>
                  {detailData.matches.length === 0 && (
                    <div className="mb-3 rounded border border-neutral-800 bg-neutral-900 p-3 text-sm text-neutral-500">
                      No candidate cards above the scoring threshold.
                    </div>
                  )}
                  <div className="mb-4 space-y-2">
                    {detailData.matches.map((match) => (
                      <div key={match.card_id} className="rounded border border-neutral-800 bg-neutral-900 p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="text-sm font-medium text-neutral-100">
                            {match.card_code} — {match.name_en ?? match.name_jp}
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-neutral-400">
                              score {match.score} ({match.confidence_label})
                            </span>
                            <button
                              onClick={() => handleReplace(match.card_id, false)}
                              disabled={pendingAction === `replace-${detailMapping.mapping_id}`}
                              className="rounded bg-neutral-800 px-2 py-1 text-xs font-medium text-neutral-200 hover:bg-neutral-700 disabled:opacity-50"
                            >
                              Replace
                            </button>
                            <button
                              onClick={() => handleReplace(match.card_id, true)}
                              disabled={pendingAction === `replace-${detailMapping.mapping_id}`}
                              className="rounded bg-emerald-800/60 px-2 py-1 text-xs font-medium text-emerald-200 hover:bg-emerald-700/60 disabled:opacity-50"
                            >
                              Replace &amp; approve
                            </button>
                          </div>
                        </div>
                        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                          {match.explanation.positive.map((p) => (
                            <span key={p} className="text-emerald-400">
                              + {p}
                            </span>
                          ))}
                          {match.explanation.negative.map((n) => (
                            <span key={n} className="text-rose-400">
                              − {n}
                            </span>
                          ))}
                          {match.explanation.caps_applied.map((c) => (
                            <span key={c} className="text-amber-400">
                              cap: {c}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="mb-3 rounded border border-neutral-800 bg-neutral-900 p-3">
                    <div className="mb-2 text-xs font-medium text-neutral-400">Replace with a different card</div>
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        value={cardQuery}
                        onChange={(e) => setCardQuery(e.target.value)}
                        placeholder="Search by card code or name…"
                        className="w-56 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
                      />
                      <select
                        value={selectedCardId ?? ""}
                        onChange={(e) => setSelectedCardId(e.target.value ? Number(e.target.value) : null)}
                        className="w-64 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                      >
                        <option value="">Select a card…</option>
                        {filteredCards.map((card) => (
                          <option key={card.id} value={card.id}>
                            {card.card_code} — {cardDisplayName(card)}
                          </option>
                        ))}
                      </select>
                      <input
                        value={reviewNotes}
                        onChange={(e) => setReviewNotes(e.target.value)}
                        placeholder="Review notes (optional)…"
                        className="w-56 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
                      />
                      <button
                        onClick={() => selectedCardId !== null && handleReplace(selectedCardId, false)}
                        disabled={selectedCardId === null || pendingAction === `replace-${detailMapping.mapping_id}`}
                        className="rounded bg-neutral-800 px-2.5 py-1 text-xs font-medium text-neutral-200 hover:bg-neutral-700 disabled:opacity-50"
                      >
                        Replace
                      </button>
                      <button
                        onClick={() => selectedCardId !== null && handleReplace(selectedCardId, true)}
                        disabled={selectedCardId === null || pendingAction === `replace-${detailMapping.mapping_id}`}
                        className="rounded bg-emerald-800/60 px-2.5 py-1 text-xs font-medium text-emerald-200 hover:bg-emerald-700/60 disabled:opacity-50"
                      >
                        Replace &amp; approve
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
