"use client";

import { Fragment, useEffect, useMemo, useState } from "react";

import { AdminSessionExpired } from "@/components/AdminSessionExpired";
import { AppHeader } from "@/components/AppHeader";
import { MatchStatusBadge } from "@/components/MatchStatusBadge";
import { PaginationControls } from "@/components/PaginationControls";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { ActionButton } from "@/components/ui/ActionButton";
import { TableScrollContainer } from "@/components/ui/DataTableShell";
import { FILTER_INPUT_CLASS } from "@/components/ui/FilterBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { SavedViewBar } from "@/components/ui/SavedViewBar";
import { StatCard, StatGrid } from "@/components/ui/StatCard";
import {
  AdminAuthRequiredError,
  type ApprovalContext,
  type ApprovalPrintOption,
  type Card,
  type CandidateMatches,
  type RematchAllResult,
  type SnkrdunkCandidate,
  approveCandidateMatch,
  fetchCandidatePrintOptions,
  fetchCandidateMatches,
  fetchCards,
  fetchSnkrdunkCandidates,
  rejectCandidateMatch,
  rematchAllCandidates,
  rematchCandidate,
} from "@/lib/api";
import { cardDisplayName, formatDateTime, formatJpy } from "@/lib/format";

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "unmatched", label: "Unmatched" },
  { value: "suggested", label: "Suggested" },
  { value: "ambiguous", label: "Ambiguous" },
  { value: "matched", label: "Matched" },
  { value: "rejected", label: "Rejected" },
];

const CONFIDENCE_LABELS = ["exact", "high", "medium", "low", "very_low"];

const REMATCH_ALL_STATUS_OPTIONS = [
  { value: "all", label: "All unresolved (unmatched/suggested/ambiguous)" },
  { value: "unmatched", label: "Unmatched only" },
  { value: "suggested", label: "Suggested only" },
  { value: "ambiguous", label: "Ambiguous only" },
];

const LIMIT_OPTIONS = [50, 100, 200, 500] as const;

/** The API's refusal, verbatim where it has one.
 *
 * A refused approval carries the reason and the rival printings it could not
 * distinguish - which is the whole content of the decision. Flattening that
 * to "Failed to approve match" would hide the only thing the operator needs. */
function approvalErrorMessage(err: unknown): string {
  const detail = (err as { body?: { detail?: unknown } })?.body?.detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    const d = detail as { message?: string; alternatives?: number[] };
    const alts = d.alternatives?.length
      ? ` Candidate printings: ${d.alternatives.join(", ")}.`
      : "";
    return `${d.message ?? "Approval refused."}${alts}`;
  }
  return "Failed to approve match.";
}

/** One printing, shown the way a collector would recognise it.
 *
 * The artwork leads, at a size where two alternate arts are actually
 * distinguishable - that is the decision being made. The internal id is
 * present but last and muted: it is what the request sends, not what the
 * operator judges by.
 */
function PrintOptionCard({
  option,
  selected,
  onSelect,
}: {
  option: ApprovalPrintOption;
  selected: boolean;
  onSelect: () => void;
}) {
  const src = option.display_image?.url ?? option.image_url ?? null;
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={!option.approvable}
      aria-pressed={selected}
      className={`flex w-full gap-3 rounded border p-3 text-left transition-colors ${
        selected
          ? "border-accent-teal bg-bg-elevated"
          : "border-border-default bg-bg-surface hover:border-border-strong"
      } ${option.approvable ? "" : "cursor-not-allowed opacity-60"}`}
    >
      {src ? (
        // object-contain, never cover: a cropped card is the wrong card.
        <img
          src={src}
          alt={`${option.name_en ?? option.name_jp ?? option.card_code} (${option.card_code})`}
          className="h-32 w-auto shrink-0 rounded object-contain"
        />
      ) : (
        <div className="flex h-32 w-24 shrink-0 items-center justify-center rounded bg-bg-page text-xs text-text-muted">
          no image
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-text-primary">
          {option.name_en ?? option.name_jp ?? option.card_code}
          {option.art_ordinal !== null && (
            <span className="ml-1.5 text-xs font-normal text-text-muted">
              Art {option.art_ordinal}
            </span>
          )}
        </div>
        {option.name_en && option.name_jp && (
          <div className="text-xs text-text-secondary">{option.name_jp}</div>
        )}
        <div className="mono mt-1 text-xs text-text-muted">{option.card_code}</div>
        <div className="mt-1.5 flex flex-wrap gap-1.5 text-xs">
          {option.found_in_product && (
            <span className="rounded bg-bg-page px-1.5 py-0.5 text-text-secondary">
              Found in {option.found_in_product}
            </span>
          )}
          {option.rarity && (
            <span className="rounded bg-bg-page px-1.5 py-0.5 text-text-secondary">
              {option.rarity}
            </span>
          )}
          {option.special_print && (
            <span className="rounded bg-purple-500/15 px-1.5 py-0.5 text-purple-300">
              {option.special_print}
            </span>
          )}
          {option.printing && (
            <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-sky-300">
              {option.printing}
            </span>
          )}
        </div>
        {!option.approvable && option.refusal_detail && (
          <div className="mt-1.5 text-xs text-amber-400">{option.refusal_detail}</div>
        )}
        <div className="mt-1 text-[10px] text-text-faint">print #{option.card_print_id}</div>
      </div>
    </button>
  );
}

export default function SnkrdunkCandidatesPage() {
  const [unauthorized, setUnauthorized] = useState(false);
  const [candidates, setCandidates] = useState<SnkrdunkCandidate[]>([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [confidenceFilter, setConfidenceFilter] = useState("");
  const [scoreMinFilter, setScoreMinFilter] = useState("");
  const [cardCodeFilter, setCardCodeFilter] = useState("");
  const [limit, setLimit] = useState(200);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState<"loading" | "error" | "ready">(
    "loading",
  );
  const [cards, setCards] = useState<Card[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<number | "bulk" | null>(
    null,
  );

  const [detailCandidateId, setDetailCandidateId] = useState<number | null>(
    null,
  );
  const [detailData, setDetailData] = useState<CandidateMatches | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [reviewNotes, setReviewNotes] = useState("");
  const [cardQuery, setCardQuery] = useState("");
  const [selectedCardId, setSelectedCardId] = useState<number | null>(null);

  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkStatus, setBulkStatus] = useState("all");
  const [bulkLimit, setBulkLimit] = useState(100);
  const [bulkResult, setBulkResult] = useState<RematchAllResult | null>(null);

  // A filter change re-pages to the start - an offset from the old filter's
  // result set is otherwise almost certainly out of range for the new one.
  useEffect(() => {
    setOffset(0);
  }, [statusFilter, limit]);

  function loadCandidates() {
    let cancelled = false;

    fetchSnkrdunkCandidates({ status: statusFilter || undefined, limit, offset })
      .then((data) => {
        if (cancelled) return;
        setCandidates(data.items);
        setTotal(data.total);
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
    return loadCandidates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, limit, offset]);

  useEffect(() => {
    fetchCards()
      .then(setCards)
      .catch(() => setCards([]));
  }, []);

  const filteredCandidates = useMemo(() => {
    const scoreMin = scoreMinFilter.trim() ? Number(scoreMinFilter) : null;
    const codeQuery = cardCodeFilter.trim().toLowerCase();
    return candidates.filter((c) => {
      if (confidenceFilter && c.best_match_confidence_label !== confidenceFilter) {
        return false;
      }
      if (scoreMin !== null && !Number.isNaN(scoreMin)) {
        if (c.best_match_score === null || c.best_match_score < scoreMin) return false;
      }
      if (codeQuery) {
        const haystack = [
          c.detected_card_code,
          c.matched_card?.card_code,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(codeQuery)) return false;
      }
      return true;
    });
  }, [candidates, confidenceFilter, scoreMinFilter, cardCodeFilter]);

  const filteredCards = useMemo(() => {
    const q = cardQuery.trim().toLowerCase();
    if (!q) return cards.slice(0, 25);
    return cards
      .filter((card) =>
        [card.card_code, card.name_en, card.name_jp]
          .filter(Boolean)
          .some((field) => field!.toLowerCase().includes(q)),
      )
      .slice(0, 25);
  }, [cards, cardQuery]);

  // The exact printing the mapping will name. Never defaulted to "the
  // first option": when the evidence leaves several printings standing the
  // API refuses anyway, and pre-selecting one would only invite the operator
  // to rubber-stamp a guess.
  const [printOptions, setPrintOptions] = useState<ApprovalContext | null>(null);
  const [printOptionsError, setPrintOptionsError] = useState<string | null>(null);
  const [selectedPrintId, setSelectedPrintId] = useState<number | null>(null);

  function updateCandidateInList(updated: SnkrdunkCandidate) {
    setCandidates((prev) =>
      prev.map((c) => (c.id === updated.id ? updated : c)),
    );
  }

  function openDetail(candidate: SnkrdunkCandidate) {
    setDetailCandidateId(candidate.id);
    setDetailData(null);
    setDetailError(null);
    setDetailLoading(true);
    setReviewNotes("");
    setCardQuery("");
    setSelectedCardId(candidate.matched_card_id ?? candidate.best_match_card_id);
    setPrintOptions(null);
    setPrintOptionsError(null);
    setSelectedPrintId(null);
    fetchCandidateMatches(candidate.id)
      .then((data) => setDetailData(data))
      .catch((err) => {
        if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
        else setDetailError("Failed to load match candidates.");
      })
      .finally(() => setDetailLoading(false));
    fetchCandidatePrintOptions(candidate.id)
      .then((data) => {
        setPrintOptions(data);
        // Pre-select only when the evidence itself leaves exactly one
        // printing standing.
        setSelectedPrintId(data.resolvable_card_print_id);
      })
      .catch((err) => {
        if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
        else setPrintOptionsError("Failed to load printings for this listing.");
      });
  }

  function closeDetail() {
    setDetailCandidateId(null);
    setDetailData(null);
    setDetailError(null);
  }

  async function handleRematch(candidateId: number) {
    setPendingAction(candidateId);
    setActionError(null);
    try {
      const result = await rematchCandidate(candidateId);
      updateCandidateInList(result.candidate);
      if (detailCandidateId === candidateId) setDetailData(result);
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
      else setActionError("Failed to rematch candidate.");
    } finally {
      setPendingAction(null);
    }
  }

  async function handleApprove(candidateId: number, cardId: number) {
    if (selectedPrintId === null) {
      setActionError("Choose the exact printing this listing is selling first.");
      return;
    }
    setPendingAction(candidateId);
    setActionError(null);
    try {
      const updated = await approveCandidateMatch(
        candidateId,
        cardId,
        selectedPrintId,
        reviewNotes.trim() || undefined,
      );
      updateCandidateInList(updated);
      closeDetail();
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
      // The API's refusal is the useful message here - it says which
      // printings the evidence could not tell apart - so it is surfaced
      // rather than replaced with a generic failure line.
      else setActionError(approvalErrorMessage(err));
    } finally {
      setPendingAction(null);
    }
  }

  async function handleReject(candidateId: number) {
    setPendingAction(candidateId);
    setActionError(null);
    try {
      const updated = await rejectCandidateMatch(
        candidateId,
        reviewNotes.trim() || undefined,
      );
      updateCandidateInList(updated);
      closeDetail();
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
      else setActionError("Failed to reject match.");
    } finally {
      setPendingAction(null);
    }
  }

  async function runBulkRematch(dryRun: boolean) {
    setPendingAction("bulk");
    setActionError(null);
    try {
      const result = await rematchAllCandidates({
        status: bulkStatus,
        limit: bulkLimit,
        dry_run: dryRun,
      });
      setBulkResult(result);
      if (!dryRun) loadCandidates();
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
      else setActionError("Failed to run bulk rematch.");
    } finally {
      setPendingAction(null);
    }
  }

  const detailCandidate = detailData?.candidate;

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <PageHeader
          title="SNKRDUNK candidates"
          description="Review imported SNKRDUNK product candidates and match them to canonical cards."
        />

        {status === "ready" && (
          <div className="mb-4">
            <StatGrid>
              <StatCard label="Candidates" value={total.toLocaleString("en-US")} />
            </StatGrid>
          </div>
        )}

        {unauthorized && (
          <AdminSessionExpired />
        )}

        {!unauthorized && (
          <>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap gap-1">
                {STATUS_FILTERS.map((f) => (
                  <button
                    key={f.value}
                    type="button"
                    onClick={() => setStatusFilter(f.value)}
                    className={`rounded-control px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                      statusFilter === f.value
                        ? "bg-accent-gold text-black/80 ring-accent-gold"
                        : "bg-bg-surface text-text-muted ring-border-default hover:text-text-primary"
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              <ActionButton variant="default" onClick={() => setBulkOpen((v) => !v)}>
                {bulkOpen ? "Hide rematch all" : "Rematch all…"}
              </ActionButton>
            </div>

            {bulkOpen && (
              <div className="mb-4 panel p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    value={bulkStatus}
                    onChange={(e) => setBulkStatus(e.target.value)}
                    className={FILTER_INPUT_CLASS}
                  >
                    {REMATCH_ALL_STATUS_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                  <input
                    type="number"
                    value={bulkLimit}
                    onChange={(e) => setBulkLimit(Number(e.target.value) || 100)}
                    className={`w-24 ${FILTER_INPUT_CLASS}`}
                  />
                  <ActionButton
                    variant="dry-run"
                    onClick={() => runBulkRematch(true)}
                    disabled={pendingAction === "bulk"}
                  >
                    Dry run
                  </ActionButton>
                  <ActionButton
                    variant="real"
                    onClick={() => runBulkRematch(false)}
                    disabled={pendingAction === "bulk"}
                  >
                    Apply
                  </ActionButton>
                </div>
                {bulkResult && (
                  <div className="mt-3 flex flex-wrap gap-4 text-xs text-text-secondary">
                    <span>dry_run: {String(bulkResult.dry_run)}</span>
                    <span>would_update: {bulkResult.would_update}</span>
                    <span>updated: {bulkResult.updated}</span>
                    <span>suggested: {bulkResult.suggested}</span>
                    <span>ambiguous: {bulkResult.ambiguous}</span>
                    <span>unmatched: {bulkResult.unmatched}</span>
                  </div>
                )}
              </div>
            )}

            <div className="mb-4 flex flex-wrap items-center gap-2">
              <select
                value={confidenceFilter}
                onChange={(e) => setConfidenceFilter(e.target.value)}
                className={FILTER_INPUT_CLASS}
              >
                <option value="">Any confidence</option>
                {CONFIDENCE_LABELS.map((label) => (
                  <option key={label} value={label}>
                    {label}
                  </option>
                ))}
              </select>
              <input
                type="number"
                placeholder="Min score"
                value={scoreMinFilter}
                onChange={(e) => setScoreMinFilter(e.target.value)}
                className={`w-28 ${FILTER_INPUT_CLASS}`}
              />
              <input
                placeholder="Card code contains…"
                value={cardCodeFilter}
                onChange={(e) => setCardCodeFilter(e.target.value)}
                className={`w-48 ${FILTER_INPUT_CLASS}`}
              />
            </div>

            <SavedViewBar
              routePath="/admin/snkrdunk-candidates"
              viewType="snkrdunk_candidates"
              scope="admin"
              currentFilters={{ statusFilter, confidenceFilter, scoreMinFilter, cardCodeFilter }}
              onApply={(filters) => {
                if (typeof filters.statusFilter === "string") setStatusFilter(filters.statusFilter);
                if (typeof filters.confidenceFilter === "string") {
                  setConfidenceFilter(filters.confidenceFilter);
                }
                if (typeof filters.scoreMinFilter === "string") setScoreMinFilter(filters.scoreMinFilter);
                if (typeof filters.cardCodeFilter === "string") setCardCodeFilter(filters.cardCodeFilter);
                setOffset(0);
              }}
            />

            {actionError && (
              <div className="mb-4 rounded-panel border border-signal-red/40 bg-signal-red/10 p-3 text-sm text-signal-red">
                {actionError}
              </div>
            )}

            {status === "loading" && <LoadingState>Loading candidates…</LoadingState>}

            {status === "error" && (
              <ErrorState>Failed to load candidates from the API. Is the backend running?</ErrorState>
            )}

            {status === "ready" && filteredCandidates.length === 0 && (
              <EmptyState>No candidates found.</EmptyState>
            )}

            {status === "ready" && filteredCandidates.length > 0 && (
              <TableScrollContainer minWidth={960}>
                <table className="w-full border-collapse text-sm">
                  <thead className="sticky-thead">
                    <tr className="border-b border-border-default bg-bg-surface text-left text-xs uppercase tracking-wide text-text-muted">
                      <th className="px-3 py-2 font-medium">Title</th>
                      <th className="px-3 py-2 font-medium text-right">Price</th>
                      <th className="px-3 py-2 font-medium">Source</th>
                      <th className="px-3 py-2 font-medium">Status</th>
                      <th className="px-3 py-2 font-medium">Best match</th>
                      <th className="px-3 py-2 font-medium text-right">Score</th>
                      <th className="px-3 py-2 font-medium">Confidence</th>
                      <th className="px-3 py-2 font-medium">Updated</th>
                      <th className="px-3 py-2 font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredCandidates.map((candidate) => {
                      const bestMatchCard =
                        candidate.best_match_card_id !== null
                          ? cards.find((c) => c.id === candidate.best_match_card_id)
                          : undefined;
                      return (
                        <tr
                          key={candidate.id}
                          className="border-b border-border-muted last:border-0 hover:bg-bg-elevated/60"
                        >
                          <td className="px-3 py-2 max-w-xs">
                            <div className="truncate font-medium text-text-primary">
                              {candidate.title ?? "—"}
                            </div>
                            {candidate.detected_card_code && (
                              <div className="font-mono text-xs text-text-muted">
                                {candidate.detected_card_code}
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-2 text-right text-text-secondary">
                            {formatJpy(candidate.price_jpy)}
                          </td>
                          <td className="px-3 py-2">
                            <a
                              href={candidate.source_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-sky-400 hover:underline"
                            >
                              link
                            </a>
                          </td>
                          <td className="px-3 py-2">
                            <MatchStatusBadge status={candidate.match_status} />
                          </td>
                          <td className="px-3 py-2 text-text-secondary">
                            {candidate.matched_card
                              ? `${cardDisplayName(candidate.matched_card)} (${candidate.matched_card.card_code})`
                              : bestMatchCard
                                ? `${cardDisplayName(bestMatchCard)} (${bestMatchCard.card_code})`
                                : "—"}
                          </td>
                          <td className="px-3 py-2 text-right text-text-secondary">
                            {candidate.best_match_score ?? "—"}
                          </td>
                          <td className="px-3 py-2 text-text-secondary">
                            {candidate.best_match_confidence_label ?? "—"}
                          </td>
                          <td className="px-3 py-2 text-xs text-text-muted">
                            {formatDateTime(candidate.updated_at)}
                          </td>
                          <td className="px-3 py-2">
                            <div className="flex flex-wrap gap-2">
                              <ActionButton variant="default" onClick={() => openDetail(candidate)}>
                                Matches
                              </ActionButton>
                              <ActionButton
                                variant="default"
                                onClick={() => handleRematch(candidate.id)}
                                disabled={pendingAction === candidate.id}
                              >
                                Rematch
                              </ActionButton>
                              {/* Approval moved into the detail panel: it now
                                  requires choosing the exact printing, which
                                  cannot be done from a row in a list. */}
                              <ActionButton
                                variant="real"
                                onClick={() => handleReject(candidate.id)}
                                disabled={
                                  pendingAction === candidate.id ||
                                  candidate.match_status === "rejected"
                                }
                              >
                                Reject
                              </ActionButton>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </TableScrollContainer>
            )}

            {status === "ready" && (
              <div className="mt-3">
                <PaginationControls
                  offset={offset}
                  limit={limit}
                  total={total}
                  onOffsetChange={setOffset}
                  limitOptions={LIMIT_OPTIONS}
                  onLimitChange={setLimit}
                />
              </div>
            )}
          </>
        )}

        {detailCandidateId !== null && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
            <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-panel border border-border-default bg-bg-page p-5">
              <div className="mb-3 flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-base font-semibold text-text-primary">
                    {detailCandidate?.title ?? "Candidate matches"}
                  </h2>
                  {detailCandidate && (
                    <a
                      href={detailCandidate.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs text-sky-400 hover:underline"
                    >
                      {detailCandidate.source_url}
                    </a>
                  )}
                </div>
                <button
                  onClick={closeDetail}
                  className="rounded px-2 py-1 text-xs font-medium text-text-secondary hover:text-text-primary"
                >
                  Close
                </button>
              </div>

              {detailCandidate?.image_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={detailCandidate.image_url}
                  alt={detailCandidate.title ?? "Candidate listing"}
                  className="mb-3 max-h-48 rounded border border-border-default object-contain"
                />
              )}

              {detailCandidate?.raw_text && (
                <div className="mb-3 rounded border border-border-default bg-bg-surface p-2 text-xs text-text-secondary">
                  {detailCandidate.raw_text}
                </div>
              )}

              {detailLoading && (
                <div className="p-6 text-center text-sm text-text-muted">
                  Loading matches…
                </div>
              )}

              {detailError && (
                <div className="rounded border border-signal-red/40 bg-signal-red/10 p-3 text-sm text-signal-red">
                  {detailError}
                </div>
              )}

              {printOptionsError && (
                <div className="mb-3 rounded border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-300">
                  {printOptionsError}
                </div>
              )}

              {printOptions && (
                <section className="mb-5">
                  {/* SOURCE CANDIDATE - what the listing itself says. */}
                  <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-text-faint">
                    Source listing
                  </h3>
                  <div className="flex gap-3 rounded border border-border-default bg-bg-surface p-3">
                    {printOptions.candidate.source_image_url && (
                      <img
                        src={printOptions.candidate.source_image_url}
                        alt=""
                        className="h-24 w-auto shrink-0 rounded object-contain"
                      />
                    )}
                    <div className="min-w-0 flex-1 text-sm">
                      <div className="font-medium text-text-primary">
                        {printOptions.candidate.title ?? "(no title)"}
                      </div>
                      <a
                        href={printOptions.candidate.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="mono break-all text-xs text-accent-teal hover:underline"
                      >
                        {printOptions.candidate.source_url}
                      </a>
                      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-text-secondary">
                        <span>{printOptions.candidate.source}</span>
                        {printOptions.candidate.detected_card_code && (
                          <span>code {printOptions.candidate.detected_card_code}</span>
                        )}
                        {printOptions.candidate.detected_set_code && (
                          <span>product {printOptions.candidate.detected_set_code}</span>
                        )}
                        {printOptions.candidate.detected_variant && (
                          <span>artwork {printOptions.candidate.detected_variant}</span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* TARGET PRINT - which physical printing is being priced. */}
                  <h3 className="mb-2 mt-4 text-xs font-medium uppercase tracking-wide text-text-faint">
                    Which printing is this listing selling?
                  </h3>
                  {printOptions.ambiguity_reason && (
                    <div className="mb-2 rounded border border-amber-500/40 bg-amber-500/10 p-2.5 text-xs text-amber-300">
                      {printOptions.ambiguity_reason}
                    </div>
                  )}
                  {printOptions.options.length === 0 ? (
                    <div className="rounded border border-border-default bg-bg-surface p-3 text-sm text-text-muted">
                      No active verified printing matches this listing.
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {printOptions.options.map((option) => (
                        <PrintOptionCard
                          key={option.card_print_id}
                          option={option}
                          selected={selectedPrintId === option.card_print_id}
                          onSelect={() => setSelectedPrintId(option.card_print_id)}
                        />
                      ))}
                    </div>
                  )}
                </section>
              )}

              {!detailLoading && detailData && (
                <>
                  {detailData.matches.length === 0 && (
                    <div className="mb-3 rounded border border-border-default bg-bg-surface p-3 text-sm text-text-muted">
                      No candidate matches above the scoring threshold.
                    </div>
                  )}
                  <div className="mb-4 space-y-2">
                    {detailData.matches.map((match) => (
                      <div
                        key={match.card_id}
                        className="rounded border border-border-default bg-bg-surface p-3"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="text-sm font-medium text-text-primary">
                            {match.card_code} — {match.name_en ?? match.name_jp}
                            {match.ambiguous && (
                              <span className="ml-2 inline-flex items-center rounded bg-orange-500/15 px-1.5 py-0.5 text-xs font-medium text-orange-300 ring-1 ring-inset ring-orange-500/30">
                                ambiguous
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-text-secondary">
                              score {match.score} ({match.confidence_label})
                            </span>
                            <ActionButton
                              variant="primary"
                              onClick={() =>
                                detailCandidateId !== null &&
                                handleApprove(detailCandidateId, match.card_id)
                              }
                              disabled={
                                pendingAction === detailCandidateId ||
                                selectedPrintId === null
                              }
                            >
                              {selectedPrintId === null
                                ? "Choose a printing"
                                : "Approve"}
                            </ActionButton>
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

                  <div className="mb-3 rounded border border-border-default bg-bg-surface p-3">
                    <div className="mb-2 text-xs font-medium text-text-secondary">
                      Approve a different card
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        value={cardQuery}
                        onChange={(e) => setCardQuery(e.target.value)}
                        placeholder="Search by card code or name…"
                        className="w-56 rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary placeholder:text-text-faint"
                      />
                      <select
                        value={selectedCardId ?? ""}
                        onChange={(e) =>
                          setSelectedCardId(
                            e.target.value ? Number(e.target.value) : null,
                          )
                        }
                        className="w-64 rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary"
                      >
                        <option value="">Select a card…</option>
                        {filteredCards.map((card) => (
                          <option key={card.id} value={card.id}>
                            {card.card_code} — {cardDisplayName(card)}
                          </option>
                        ))}
                      </select>
                      <ActionButton
                        variant="primary"
                        onClick={() =>
                          selectedCardId !== null &&
                          detailCandidateId !== null &&
                          handleApprove(detailCandidateId, selectedCardId)
                        }
                        disabled={
                          selectedCardId === null ||
                          pendingAction === detailCandidateId
                        }
                      >
                        Approve selected
                      </ActionButton>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      value={reviewNotes}
                      onChange={(e) => setReviewNotes(e.target.value)}
                      placeholder="Review notes (optional)…"
                      className="flex-1 rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary placeholder:text-text-faint"
                    />
                    <ActionButton
                      variant="real"
                      onClick={() =>
                        detailCandidateId !== null &&
                        handleReject(detailCandidateId)
                      }
                      disabled={pendingAction === detailCandidateId}
                    >
                      Reject match
                    </ActionButton>
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
