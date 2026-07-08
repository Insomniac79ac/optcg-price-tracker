"use client";

import { Fragment, useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { MatchStatusBadge } from "@/components/MatchStatusBadge";
import {
  type Card,
  type SnkrdunkCandidate,
  fetchCards,
  fetchSnkrdunkCandidates,
  matchSnkrdunkCandidate,
  rejectSnkrdunkCandidate,
} from "@/lib/api";
import { cardDisplayName, formatDateTime, formatJpy } from "@/lib/format";

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "needs_review", label: "Needs review" },
  { value: "auto_matched", label: "Auto matched" },
  { value: "rejected", label: "Rejected" },
];

export default function SnkrdunkCandidatesPage() {
  const [candidates, setCandidates] = useState<SnkrdunkCandidate[]>([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [status, setStatus] = useState<"loading" | "error" | "ready">(
    "loading",
  );
  const [cards, setCards] = useState<Card[]>([]);
  const [matchingId, setMatchingId] = useState<number | null>(null);
  const [cardQuery, setCardQuery] = useState("");
  const [selectedCardId, setSelectedCardId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    fetchSnkrdunkCandidates({ status: statusFilter || undefined, limit: 200 })
      .then((data) => {
        if (cancelled) return;
        setCandidates(data.items);
        setTotal(data.total);
        setStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, [statusFilter]);

  useEffect(() => {
    fetchCards()
      .then(setCards)
      .catch(() => setCards([]));
  }, []);

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

  function openMatch(candidate: SnkrdunkCandidate) {
    setMatchingId(candidate.id);
    setCardQuery("");
    setSelectedCardId(candidate.matched_card_id);
    setActionError(null);
  }

  function closeMatch() {
    setMatchingId(null);
    setSelectedCardId(null);
    setCardQuery("");
  }

  async function submitMatch(candidateId: number) {
    if (selectedCardId === null) return;
    setPendingAction(candidateId);
    setActionError(null);
    try {
      const updated = await matchSnkrdunkCandidate(candidateId, selectedCardId);
      setCandidates((prev) =>
        prev.map((c) => (c.id === candidateId ? updated : c)),
      );
      closeMatch();
    } catch {
      setActionError("Failed to match candidate.");
    } finally {
      setPendingAction(null);
    }
  }

  async function reject(candidateId: number) {
    setPendingAction(candidateId);
    setActionError(null);
    try {
      const updated = await rejectSnkrdunkCandidate(candidateId);
      setCandidates((prev) =>
        prev.map((c) => (c.id === candidateId ? updated : c)),
      );
    } catch {
      setActionError("Failed to reject candidate.");
    } finally {
      setPendingAction(null);
    }
  }

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-4 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">
            SNKRDUNK candidates
          </h1>
          {status === "ready" && (
            <span className="text-sm text-neutral-500">
              {total} candidate{total === 1 ? "" : "s"}
            </span>
          )}
        </div>

        <div className="mb-4 flex gap-1">
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

        {status === "ready" && candidates.length === 0 && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            No candidates found.
          </div>
        )}

        {status === "ready" && candidates.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-neutral-800">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wide text-neutral-500">
                  <th className="px-3 py-2 font-medium">Title</th>
                  <th className="px-3 py-2 font-medium text-right">Price</th>
                  <th className="px-3 py-2 font-medium">Condition</th>
                  <th className="px-3 py-2 font-medium">Source</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium text-right">
                    Confidence
                  </th>
                  <th className="px-3 py-2 font-medium">Matched card</th>
                  <th className="px-3 py-2 font-medium">Updated</th>
                  <th className="px-3 py-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((candidate) => (
                  <Fragment key={candidate.id}>
                    <tr className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60">
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
                      <td className="px-3 py-2 text-neutral-400">
                        {candidate.condition_label ?? "—"}
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
                      <td className="px-3 py-2 text-right text-neutral-400">
                        {candidate.match_confidence !== null
                          ? candidate.match_confidence.toFixed(2)
                          : "—"}
                      </td>
                      <td className="px-3 py-2 text-neutral-400">
                        {candidate.matched_card
                          ? `${cardDisplayName(candidate.matched_card)} (${candidate.matched_card.card_code})`
                          : "—"}
                      </td>
                      <td className="px-3 py-2 text-xs text-neutral-500">
                        {formatDateTime(candidate.updated_at)}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex gap-2">
                          <button
                            onClick={() => openMatch(candidate)}
                            disabled={pendingAction === candidate.id}
                            className="rounded bg-neutral-800 px-2 py-1 text-xs font-medium text-neutral-200 hover:bg-neutral-700 disabled:opacity-50"
                          >
                            Match
                          </button>
                          <button
                            onClick={() => reject(candidate.id)}
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
                    {matchingId === candidate.id && (
                      <tr className="border-b border-neutral-900 bg-neutral-900/40">
                        <td colSpan={9} className="px-3 py-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <input
                              autoFocus
                              value={cardQuery}
                              onChange={(e) => setCardQuery(e.target.value)}
                              placeholder="Search by card code or name…"
                              className="w-64 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
                            />
                            <select
                              value={selectedCardId ?? ""}
                              onChange={(e) =>
                                setSelectedCardId(
                                  e.target.value
                                    ? Number(e.target.value)
                                    : null,
                                )
                              }
                              className="w-72 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                            >
                              <option value="">Select a card…</option>
                              {filteredCards.map((card) => (
                                <option key={card.id} value={card.id}>
                                  {card.card_code} — {cardDisplayName(card)}
                                </option>
                              ))}
                            </select>
                            <button
                              onClick={() => submitMatch(candidate.id)}
                              disabled={
                                selectedCardId === null ||
                                pendingAction === candidate.id
                              }
                              className="rounded bg-emerald-800/60 px-2.5 py-1 text-xs font-medium text-emerald-200 hover:bg-emerald-700/60 disabled:opacity-50"
                            >
                              Confirm match
                            </button>
                            <button
                              onClick={closeMatch}
                              className="rounded px-2.5 py-1 text-xs font-medium text-neutral-400 hover:text-neutral-100"
                            >
                              Cancel
                            </button>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}
