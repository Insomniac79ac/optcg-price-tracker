"use client";

import Link from "next/link";
import { useState } from "react";

import { RarityBadge } from "@/components/RarityBadge";
import { EmptyState } from "@/components/StateBlocks";
import { TableScrollContainer } from "@/components/ui/DataTableShell";
import { convertWishlistItemToCollection, createCollectorNote, type BuyDecisionCandidate } from "@/lib/api";
import { cardDisplayName, formatJPY, formatNumber, formatPercent } from "@/lib/format";

const ACTION_LABELS: Record<string, string> = {
  review_buy: "Review buy",
  wait: "Wait",
  skip: "Skip",
  missing_data: "Missing data",
  monitor: "Monitor",
};

const ACTION_TONE: Record<string, string> = {
  review_buy: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  wait: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  skip: "bg-neutral-500/15 text-neutral-400 ring-neutral-500/30",
  missing_data: "bg-neutral-500/15 text-neutral-400 ring-neutral-500/30",
  monitor: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
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

function NoteForm({ candidate, onDone }: { candidate: BuyDecisionCandidate; onDone: () => void }) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!text.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await createCollectorNote({
        note_type: "wishlist",
        body: text.trim(),
        card_id: candidate.card_id,
        title: `Buy decision note: ${candidate.card_code}`,
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

/** Dense candidate table for the buy-decision-support page - every column
 * the spec lists is always shown, so the table is wide and meant to scroll
 * horizontally in its own container (same pattern as
 * SellDecisionCandidateTable). */
export function BuyDecisionCandidateTable({
  candidates,
  onCandidateUpdated,
}: {
  candidates: BuyDecisionCandidate[];
  onCandidateUpdated: () => void;
}) {
  const [notingId, setNotingId] = useState<number | null>(null);
  const [convertingId, setConvertingId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  if (candidates.length === 0) {
    return <EmptyState>No buy decision candidates found for the selected filters.</EmptyState>;
  }

  async function convertToCollection(candidate: BuyDecisionCandidate) {
    setConvertingId(candidate.wishlist_item_id);
    setActionError(null);
    try {
      await convertWishlistItemToCollection(candidate.wishlist_item_id, {
        quantity: candidate.remaining_quantity > 0 ? candidate.remaining_quantity : 1,
      });
      onCandidateUpdated();
    } catch {
      setActionError(`Failed to convert wishlist item #${candidate.wishlist_item_id} to collection.`);
    } finally {
      setConvertingId(null);
    }
  }

  return (
    <div>
      {actionError && <p className="mb-2 text-xs text-rose-400">{actionError}</p>}
      <TableScrollContainer>
        <table className="w-full min-w-[2300px] border-collapse text-xs">
          <thead className="sticky-thead">
            <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
              <th className="sticky-col-first px-3 py-2 font-medium">Score</th>
              <th className="px-3 py-2 font-medium">Action</th>
              <th className="px-3 py-2 font-medium">Priority</th>
              <th className="px-3 py-2 font-medium">Card</th>
              <th className="px-3 py-2 font-medium">Set / Rarity</th>
              <th className="px-3 py-2 font-medium">Desired</th>
              <th className="px-3 py-2 font-medium">Owned</th>
              <th className="px-3 py-2 font-medium">Remaining</th>
              <th className="px-3 py-2 font-medium">Target price</th>
              <th className="px-3 py-2 font-medium">Max price</th>
              <th className="px-3 py-2 font-medium">Current price</th>
              <th className="px-3 py-2 font-medium">Price source</th>
              <th className="px-3 py-2 font-medium">Target hit</th>
              <th className="px-3 py-2 font-medium">Gap to target</th>
              <th className="px-3 py-2 font-medium">Gap to max</th>
              <th className="px-3 py-2 font-medium">SNKRDUNK/Yuyu-Tei gap</th>
              <th className="px-3 py-2 font-medium">Yuyu-Tei spread</th>
              <th className="px-3 py-2 font-medium">Tags / groups</th>
              <th className="px-3 py-2 font-medium">Score reasons</th>
              <th className="px-3 py-2 font-medium">Warnings</th>
              <th className="px-3 py-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((c) => (
              <tr key={c.wishlist_item_id} className="border-b border-neutral-900 align-top last:border-0">
                <td className="sticky-col-first px-3 py-2">
                  <ScoreBadge score={c.score} />
                </td>
                <td className="px-3 py-2">
                  <ActionBadge action={c.recommended_action} />
                </td>
                <td className="px-3 py-2 capitalize text-neutral-300">{c.priority}</td>
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
                <td className="px-3 py-2 text-neutral-300">{formatNumber(c.desired_quantity)}</td>
                <td className="px-3 py-2 text-neutral-300">{formatNumber(c.owned_quantity)}</td>
                <td className="px-3 py-2 text-neutral-300">{formatNumber(c.remaining_quantity)}</td>
                <td className="px-3 py-2 text-neutral-300">{formatJPY(c.target_buy_price_jpy)}</td>
                <td className="px-3 py-2 text-neutral-300">{formatJPY(c.max_buy_price_jpy)}</td>
                <td className="px-3 py-2 text-neutral-200">{formatJPY(c.current_price_jpy)}</td>
                <td className="px-3 py-2 text-neutral-500">{c.current_price_source ?? "not available"}</td>
                <td className="px-3 py-2">
                  <span className={c.target_hit ? "text-emerald-400" : "text-neutral-600"}>
                    {c.target_hit ? "Hit" : "—"}
                  </span>
                </td>
                <td className="px-3 py-2 text-neutral-300">
                  {c.gap_to_target_jpy === null ? (
                    "not available"
                  ) : (
                    <span className={c.gap_to_target_jpy <= 0 ? "text-emerald-400" : "text-neutral-300"}>
                      {formatJPY(c.gap_to_target_jpy)}
                      {c.gap_to_target_pct !== null && (
                        <span className="ml-1 text-neutral-500">({formatPercent(c.gap_to_target_pct)})</span>
                      )}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-neutral-300">
                  {c.gap_to_max_jpy === null ? (
                    "not available"
                  ) : (
                    <span className={c.gap_to_max_jpy <= 0 ? "text-emerald-400" : "text-amber-400"}>
                      {formatJPY(c.gap_to_max_jpy)}
                      {c.gap_to_max_pct !== null && (
                        <span className="ml-1 text-neutral-500">({formatPercent(c.gap_to_max_pct)})</span>
                      )}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-neutral-300">
                  {formatPercent(c.market_context.snkrdunk_vs_yuyutei_sell_gap_pct)}
                </td>
                <td className="px-3 py-2 text-neutral-300">
                  {formatPercent(c.market_context.yuyutei_spread_pct)}
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
                      <Link href="/wishlist" className="text-sky-400 hover:text-sky-300">
                        Wishlist
                      </Link>
                      <Link href="/market/opportunities" className="text-sky-400 hover:text-sky-300">
                        Opportunities
                      </Link>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => convertToCollection(c)}
                        disabled={convertingId === c.wishlist_item_id}
                        className="rounded border border-neutral-700 px-1.5 py-0.5 text-[11px] text-neutral-300 hover:text-neutral-100 disabled:opacity-50"
                      >
                        Convert to collection
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          setNotingId(notingId === c.wishlist_item_id ? null : c.wishlist_item_id)
                        }
                        className="rounded border border-neutral-700 px-1.5 py-0.5 text-[11px] text-neutral-300 hover:text-neutral-100"
                      >
                        + Note
                      </button>
                    </div>
                    {notingId === c.wishlist_item_id && (
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
