"use client";

import { Fragment, useEffect, useMemo, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { MatchStatusBadge } from "@/components/MatchStatusBadge";
import { PaginationControls } from "@/components/PaginationControls";
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
        <div className="mb-4 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">
            SNKRDUNK candidates
          </h1>
          <div className="flex items-center gap-3">
            {status === "ready" && (
              <span className="text-sm text-neutral-500">
                {total} candidate{total === 1 ? "" : "s"}
              </span>
            )}
            <AdminLogoutButton />
          </div>
        </div>

        {unauthorized && (
          <AdminAuthGate onTokenSaved={() => window.location.reload()} />
        )}

        {!unauthorized && (
          <>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap gap-1">
                {STATUS_FILTERS.map((f) => (
                  <button
                    key={f.value}
                    onClick={() => setStatusFilter(f.value)}
                    className={`rounded px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                      statusFilter === f.value
                        ? "bg-neutral-100 text-neutral-900 ring-neutral-100"
                        : "bg-neutral-900 text-neutral-400 ring-neutral-800 hover:text-neutral-100"
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              <button
                onClick={() => setBulkOpen((v) => !v)}
                className="rounded bg-neutral-800 px-2.5 py-1 text-xs font-medium text-neutral-200 hover:bg-neutral-700"
              >
                {bulkOpen ? "Hide rematch all" : "Rematch all…"}
              </button>
            </div>

            {bulkOpen && (
              <div className="mb-4 rounded-lg border border-neutral-800 bg-neutral-900 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    value={bulkStatus}
                    onChange={(e) => setBulkStatus(e.target.value)}
                    className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
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
                    className="w-24 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                  />
                  <button
                    onClick={() => runBulkRematch(true)}
                    disabled={pendingAction === "bulk"}
                    className="rounded bg-neutral-800 px-2.5 py-1 text-xs font-medium text-neutral-200 hover:bg-neutral-700 disabled:opacity-50"
                  >
                    Dry run
                  </button>
                  <button
                    onClick={() => runBulkRematch(false)}
                    disabled={pendingAction === "bulk"}
                    className="rounded bg-emerald-800/60 px-2.5 py-1 text-xs font-medium text-emerald-200 hover:bg-emerald-700/60 disabled:opacity-50"
                  >
                    Apply
                  </button>
                </div>
                {bulkResult && (
                  <div className="mt-3 flex flex-wrap gap-4 text-xs text-neutral-400">
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
                className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
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
                className="w-28 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
              />
              <input
                placeholder="Card code contains…"
                value={cardCodeFilter}
                onChange={(e) => setCardCodeFilter(e.target.value)}
                className="w-48 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
              />
            </div>

            {actionError && (
              <div className="mb-4 rounded-lg border border-rose-900/50 bg-rose-950/30 p-3 text-sm text-rose-300">
                {actionError}
              </div>
            )}

            {status === "loading" && (
              <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
                Loading candidates…
              </div>
            )}

            {status === "error" && (
              <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
                Failed to load candidates from the API. Is the backend running?
              </div>
            )}

            {status === "ready" && filteredCandidates.length === 0 && (
              <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
                No candidates found.
              </div>
            )}

            {status === "ready" && filteredCandidates.length > 0 && (
              <div className="overflow-x-auto rounded-lg border border-neutral-800">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wide text-neutral-500">
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
                          className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                        >
                          <td className="px-3 py-2 max-w-xs">
                            <div className="truncate font-medium text-neutral-100">
                              {candidate.title ?? "—"}
                            </div>
                            {candidate.detected_card_code && (
                              <div className="font-mono text-xs text-neutral-500">
                                {candidate.detected_card_code}
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-2 text-right text-neutral-300">
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
                          <td className="px-3 py-2 text-neutral-400">
                            {candidate.matched_card
                              ? `${cardDisplayName(candidate.matched_card)} (${candidate.matched_card.card_code})`
                              : bestMatchCard
                                ? `${cardDisplayName(bestMatchCard)} (${bestMatchCard.card_code})`
                                : "—"}
                          </td>
                          <td className="px-3 py-2 text-right text-neutral-400">
                            {candidate.best_match_score ?? "—"}
                          </td>
                          <td className="px-3 py-2 text-neutral-400">
                            {candidate.best_match_confidence_label ?? "—"}
                          </td>
                          <td className="px-3 py-2 text-xs text-neutral-500">
                            {formatDateTime(candidate.updated_at)}
                          </td>
                          <td className="px-3 py-2">
                            <div className="flex flex-wrap gap-2">
                              <button
                                onClick={() => openDetail(candidate)}
                                className="rounded bg-neutral-800 px-2 py-1 text-xs font-medium text-neutral-200 hover:bg-neutral-700"
                              >
                                Matches
                              </button>
                              <button
                                onClick={() => handleRematch(candidate.id)}
                                disabled={pendingAction === candidate.id}
                                className="rounded bg-neutral-800 px-2 py-1 text-xs font-medium text-neutral-200 hover:bg-neutral-700 disabled:opacity-50"
                              >
                                Rematch
                              </button>
                              {candidate.best_match_card_id !== null && (
                                <button
                                  onClick={() =>
                                    handleApprove(
                                      candidate.id,
                                      candidate.best_match_card_id!,
                                    )
                                  }
                                  disabled={pendingAction === candidate.id}
                                  className="rounded bg-emerald-800/60 px-2 py-1 text-xs font-medium text-emerald-200 hover:bg-emerald-700/60 disabled:opacity-50"
                                >
                                  Approve best
                                </button>
                              )}
                              <button
                                onClick={() => handleReject(candidate.id)}
                                disabled={
                                  pendingAction === candidate.id ||
                                  candidate.match_status === "rejected"
                                }
                                className="rounded bg-rose-950/60 px-2 py-1 text-xs font-medium text-rose-300 hover:bg-rose-900/60 disabled:opacity-50"
                              >
                                Reject
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
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
            <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-lg border border-neutral-800 bg-neutral-950 p-5">
              <div className="mb-3 flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-base font-semibold text-neutral-100">
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
                  className="rounded px-2 py-1 text-xs font-medium text-neutral-400 hover:text-neutral-100"
                >
                  Close
                </button>
              </div>

              {detailCandidate?.image_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={detailCandidate.image_url}
                  alt={detailCandidate.title ?? "Candidate listing"}
                  className="mb-3 max-h-48 rounded border border-neutral-800 object-contain"
                />
              )}

              {detailCandidate?.raw_text && (
                <div className="mb-3 rounded border border-neutral-800 bg-neutral-900 p-2 text-xs text-neutral-400">
                  {detailCandidate.raw_text}
                </div>
              )}

              {detailLoading && (
                <div className="p-6 text-center text-sm text-neutral-500">
                  Loading matches…
                </div>
              )}

              {detailError && (
                <div className="rounded border border-rose-900/50 bg-rose-950/30 p-3 text-sm text-rose-300">
                  {detailError}
                </div>
              )}

              {!detailLoading && detailData && (
                <>
                  {detailData.matches.length === 0 && (
                    <div className="mb-3 rounded border border-neutral-800 bg-neutral-900 p-3 text-sm text-neutral-500">
                      No candidate matches above the scoring threshold.
                    </div>
                  )}
                  <div className="mb-4 space-y-2">
                    {detailData.matches.map((match) => (
                      <div
                        key={match.card_id}
                        className="rounded border border-neutral-800 bg-neutral-900 p-3"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="text-sm font-medium text-neutral-100">
                            {match.card_code} — {match.name_en ?? match.name_jp}
                            {match.ambiguous && (
                              <span className="ml-2 inline-flex items-center rounded bg-orange-500/15 px-1.5 py-0.5 text-xs font-medium text-orange-300 ring-1 ring-inset ring-orange-500/30">
                                ambiguous
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-neutral-400">
                              score {match.score} ({match.confidence_label})
                            </span>
                            <button
                              onClick={() =>
                                detailCandidateId !== null &&
                                handleApprove(detailCandidateId, match.card_id)
                              }
                              disabled={pendingAction === detailCandidateId}
                              className="rounded bg-emerald-800/60 px-2 py-1 text-xs font-medium text-emerald-200 hover:bg-emerald-700/60 disabled:opacity-50"
                            >
                              Approve
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
                    <div className="mb-2 text-xs font-medium text-neutral-400">
                      Approve a different card
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        value={cardQuery}
                        onChange={(e) => setCardQuery(e.target.value)}
                        placeholder="Search by card code or name…"
                        className="w-56 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
                      />
                      <select
                        value={selectedCardId ?? ""}
                        onChange={(e) =>
                          setSelectedCardId(
                            e.target.value ? Number(e.target.value) : null,
                          )
                        }
                        className="w-64 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                      >
                        <option value="">Select a card…</option>
                        {filteredCards.map((card) => (
                          <option key={card.id} value={card.id}>
                            {card.card_code} — {cardDisplayName(card)}
                          </option>
                        ))}
                      </select>
                      <button
                        onClick={() =>
                          selectedCardId !== null &&
                          detailCandidateId !== null &&
                          handleApprove(detailCandidateId, selectedCardId)
                        }
                        disabled={
                          selectedCardId === null ||
                          pendingAction === detailCandidateId
                        }
                        className="rounded bg-emerald-800/60 px-2.5 py-1 text-xs font-medium text-emerald-200 hover:bg-emerald-700/60 disabled:opacity-50"
                      >
                        Approve selected
                      </button>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      value={reviewNotes}
                      onChange={(e) => setReviewNotes(e.target.value)}
                      placeholder="Review notes (optional)…"
                      className="flex-1 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
                    />
                    <button
                      onClick={() =>
                        detailCandidateId !== null &&
                        handleReject(detailCandidateId)
                      }
                      disabled={pendingAction === detailCandidateId}
                      className="rounded bg-rose-950/60 px-2.5 py-1 text-xs font-medium text-rose-300 hover:bg-rose-900/60 disabled:opacity-50"
                    >
                      Reject match
                    </button>
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
