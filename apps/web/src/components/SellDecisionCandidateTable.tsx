"use client";

import Link from "next/link";
import { useState } from "react";

import { RarityBadge } from "@/components/RarityBadge";
import { EmptyState } from "@/components/StateBlocks";
import { TableScrollContainer } from "@/components/ui/DataTableShell";
import { createCollectorNote, updateCollectionItem, type SellDecisionCandidate } from "@/lib/api";
import { cardDisplayName, formatJPY, formatNumber, formatPercent, formatSignedJpy } from "@/lib/format";

const ACTION_LABELS: Record<string, string> = {
  review_sell: "Review sell",
  hold: "Hold",
  grade_first: "Grade first",
  missing_data: "Missing data",
  monitor: "Monitor",
};

const ACTION_TONE: Record<string, string> = {
  review_sell: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  hold: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  grade_first: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  missing_data: "bg-neutral-500/15 text-neutral-400 ring-neutral-500/30",
  monitor: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
};

function ActionBadge({ action }: { action: string }) {
  const tone = ACTION_TONE[action] ?? ACTION_TONE.monitor;
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${tone}`}
    >
      {ACTION_LABELS[action] ?? action}
    </span>
  );
}

/** Score is meant to be "clear but not flashy" per the spec - a plain large
 * tabular number colored by tier, no icon/animation. */
function ScoreBadge({ score }: { score: number }) {
  const tone = score >= 70 ? "text-emerald-400" : score >= 35 ? "text-amber-400" : "text-neutral-500";
  return <span className={`text-base font-semibold tabular-nums ${tone}`}>{score}</span>;
}

function NoteForm({ candidate, onDone }: { candidate: SellDecisionCandidate; onDone: () => void }) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!text.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await createCollectorNote({
        note_type: "collection",
        body: text.trim(),
        collection_item_id: candidate.collection_item_id,
        card_id: candidate.card_id,
        title: `Sell decision note: ${candidate.card_code}`,
      });
      setText("");
      onDone();
    } catch {
      setError("Failed to save note.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-1 flex items-center gap-1">
      <input
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Add a note…"
        className="w-40 rounded border border-neutral-700 bg-neutral-950 px-1.5 py-0.5 text-[11px] text-neutral-200 placeholder:text-neutral-600"
      />
      <button
        type="button"
        onClick={submit}
        disabled={saving || !text.trim()}
        className="rounded border border-neutral-700 px-1.5 py-0.5 text-[11px] text-neutral-300 hover:text-neutral-100 disabled:opacity-50"
      >
        Save
      </button>
      {error && <span className="text-[11px] text-rose-400">{error}</span>}
    </div>
  );
}

/** Dense candidate table for the sell-decision-support page - every column
 * the spec lists is always shown (unlike the wishlist analytics table,
 * there's no per-section column subset here), so the table is wide and
 * meant to scroll horizontally in its own container. */
export function SellDecisionCandidateTable({
  candidates,
  onCandidateUpdated,
}: {
  candidates: SellDecisionCandidate[];
  onCandidateUpdated: () => void;
}) {
  const [notingId, setNotingId] = useState<number | null>(null);
  const [markingId, setMarkingId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  if (candidates.length === 0) {
    return <EmptyState>No sell decision candidates found for the selected filters.</EmptyState>;
  }

  async function markForSell(candidate: SellDecisionCandidate) {
    setMarkingId(candidate.collection_item_id);
    setActionError(null);
    try {
      await updateCollectionItem(candidate.collection_item_id, { status: "sell" });
      onCandidateUpdated();
    } catch {
      setActionError(`Failed to update collection item #${candidate.collection_item_id}.`);
    } finally {
      setMarkingId(null);
    }
  }

  return (
    <div>
      {actionError && <p className="mb-2 text-xs text-rose-400">{actionError}</p>}
      <TableScrollContainer>
        <table className="w-full min-w-[2400px] border-collapse text-xs">
          <thead className="sticky-thead">
            <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
              <th className="sticky-col-first px-3 py-2 font-medium">Score</th>
              <th className="px-3 py-2 font-medium">Action</th>
              <th className="px-3 py-2 font-medium">Card</th>
              <th className="px-3 py-2 font-medium">Set / Rarity</th>
              <th className="px-3 py-2 font-medium">Qty</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Condition</th>
              <th className="px-3 py-2 font-medium">Current value</th>
              <th className="px-3 py-2 font-medium">Basis</th>
              <th className="px-3 py-2 font-medium">Cost basis</th>
              <th className="px-3 py-2 font-medium">P/L</th>
              <th className="px-3 py-2 font-medium">Target sell</th>
              <th className="px-3 py-2 font-medium">Above target</th>
              <th className="px-3 py-2 font-medium">Yuyu-Tei spread</th>
              <th className="px-3 py-2 font-medium">SNKRDUNK gap</th>
              <th className="px-3 py-2 font-medium">Grading</th>
              <th className="px-3 py-2 font-medium">Wishlist overlap</th>
              <th className="px-3 py-2 font-medium">Tags / groups</th>
              <th className="px-3 py-2 font-medium">Score reasons</th>
              <th className="px-3 py-2 font-medium">Warnings</th>
              <th className="px-3 py-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((c) => (
              <tr key={c.collection_item_id} className="border-b border-neutral-900 align-top last:border-0">
                <td className="sticky-col-first px-3 py-2">
                  <ScoreBadge score={c.score} />
                </td>
                <td className="px-3 py-2">
                  <ActionBadge action={c.recommended_action} />
                </td>
                <td className="px-3 py-2 text-neutral-200">
                  <Link href={`/cards/${c.card_id}`} className="text-sky-400 hover:text-sky-300">
                    {c.card_code}
                  </Link>
                  <div className="text-neutral-400">{cardDisplayName(c)}</div>
                </td>
                <td className="px-3 py-2">
                  <span className="flex items-center gap-1.5">
                    <span className="text-neutral-300">{c.set_code}</span>
                    <RarityBadge rarity={c.rarity} />
                  </span>
                </td>
                <td className="px-3 py-2 text-neutral-300">{formatNumber(c.quantity)}</td>
                <td className="px-3 py-2 capitalize text-neutral-300">{c.status}</td>
                <td className="px-3 py-2 text-neutral-300">{c.condition_label ?? "not available"}</td>
                <td className="px-3 py-2 text-neutral-200">{formatJPY(c.current_value_jpy)}</td>
                <td className="px-3 py-2 text-neutral-500">{c.current_value_basis ?? "not available"}</td>
                <td className="px-3 py-2 text-neutral-300">{formatJPY(c.cost_basis_jpy)}</td>
                <td className="px-3 py-2">
                  {c.unrealized_pnl_jpy === null ? (
                    "not available"
                  ) : (
                    <span className={c.unrealized_pnl_jpy >= 0 ? "text-emerald-400" : "text-rose-400"}>
                      {formatSignedJpy(c.unrealized_pnl_jpy)}
                      {c.unrealized_pnl_pct !== null && (
                        <span className="ml-1 text-neutral-500">({formatPercent(c.unrealized_pnl_pct)})</span>
                      )}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-neutral-300">{formatJPY(c.target_sell_price_jpy)}</td>
                <td className="px-3 py-2">
                  <span className={c.above_target_sell ? "text-emerald-400" : "text-neutral-600"}>
                    {c.above_target_sell ? "Yes" : "No"}
                  </span>
                </td>
                <td className="px-3 py-2 text-neutral-300">
                  {formatPercent(c.market_context.yuyutei_spread_pct)}
                </td>
                <td className="px-3 py-2 text-neutral-300">
                  {formatPercent(c.market_context.snkrdunk_vs_yuyutei_sell_gap_pct)}
                </td>
                <td className="px-3 py-2 text-neutral-300">
                  {c.grading.latest_status ? (
                    <span className={c.grading.has_active_grading ? "text-violet-300" : "text-neutral-300"}>
                      {c.grading.latest_status}
                    </span>
                  ) : (
                    "not available"
                  )}
                  {c.grading.final_grade && <div className="text-neutral-500">{c.grading.final_grade}</div>}
                </td>
                <td className="px-3 py-2 text-neutral-300">
                  {c.wishlist_overlap.is_on_wishlist
                    ? `${c.wishlist_overlap.priority ?? "not available"} / ${
                        c.wishlist_overlap.status ?? "not available"
                      }`
                    : "not available"}
                </td>
                <td className="px-3 py-2 text-neutral-400">
                  {[...c.tags, ...c.groups].length > 0 ? [...c.tags, ...c.groups].join(", ") : "not available"}
                </td>
                <td className="px-3 py-2 text-neutral-400">
                  {c.score_reasons.length > 0 ? c.score_reasons.join("; ") : "not available"}
                </td>
                <td className="px-3 py-2 text-amber-400">
                  {c.warnings.length > 0 ? c.warnings.join("; ") : "not available"}
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-col gap-1">
                    <div className="flex flex-wrap gap-2">
                      <Link href={`/cards/${c.card_id}`} className="text-sky-400 hover:text-sky-300">
                        Card
                      </Link>
                      <Link href="/collection" className="text-sky-400 hover:text-sky-300">
                        Collection
                      </Link>
                      {c.grading.has_active_grading && (
                        <Link href="/grading" className="text-sky-400 hover:text-sky-300">
                          Grading
                        </Link>
                      )}
                      <Link href="/market/opportunities" className="text-sky-400 hover:text-sky-300">
                        Opportunities
                      </Link>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => markForSell(c)}
                        disabled={c.status === "sell" || markingId === c.collection_item_id}
                        className="rounded border border-neutral-700 px-1.5 py-0.5 text-[11px] text-neutral-300 hover:text-neutral-100 disabled:opacity-50"
                      >
                        {c.status === "sell" ? "Marked for sell" : "Mark for sell"}
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          setNotingId(notingId === c.collection_item_id ? null : c.collection_item_id)
                        }
                        className="rounded border border-neutral-700 px-1.5 py-0.5 text-[11px] text-neutral-300 hover:text-neutral-100"
                      >
                        + Note
                      </button>
                    </div>
                    {notingId === c.collection_item_id && (
                      <NoteForm candidate={c} onDone={() => setNotingId(null)} />
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScrollContainer>
    </div>
  );
}
