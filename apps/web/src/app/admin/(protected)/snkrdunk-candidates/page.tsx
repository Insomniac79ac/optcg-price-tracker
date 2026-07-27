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
  type Card,
  type CandidateMatches,
  type RematchAllResult,
  type SnkrdunkCandidate,
  approveCandidateMatch,
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
    fetchCandidateMatches(candidate.id)
      .then((data) => setDetailData(data))
      .catch((err) => {
        if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
        else setDetailError("Failed to load match candidates.");
      })
      .finally(() => setDetailLoading(false));
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
    setPendingAction(candidateId);
    setActionError(null);
    try {
      const updated = await approveCandidateMatch(
        candidateId,
        cardId,
        reviewNotes.trim() || undefined,
      );
      updateCandidateInList(updated);
      closeDetail();
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
      else setActionError("Failed to approve match.");
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
                              {candidate.best_match_card_id !== null && (
                                <ActionButton
                                  variant="primary"
                                  onClick={() =>
                                    handleApprove(
                                      candidate.id,
                                      candidate.best_match_card_id!,
                                    )
                                  }
                                  disabled={pendingAction === candidate.id}
                                >
                                  Approve best
                                </ActionButton>
                              )}
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
                              disabled={pendingAction === detailCandidateId}
                            >
                              Approve
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
