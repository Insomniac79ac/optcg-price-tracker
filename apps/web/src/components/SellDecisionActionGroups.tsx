import Link from "next/link";

import type { SellDecisionAction, SellDecisionCandidate } from "@/lib/api";
import { cardDisplayName, formatNumber } from "@/lib/format";

const GROUPS: { action: SellDecisionAction; label: string }[] = [
  { action: "review_sell", label: "Review Sell" },
  { action: "grade_first", label: "Grade First" },
  { action: "missing_data", label: "Missing Data" },
  { action: "monitor", label: "Monitor" },
  { action: "hold", label: "Hold" },
];

/** Compact per-action summary shown above the full candidate table - count
 * plus the top 3 cards (candidates already arrive score-sorted from the
 * API, so `.slice(0, 3)` is "top 3 by score" with no extra sorting here). */
export function SellDecisionActionGroups({ candidates }: { candidates: SellDecisionCandidate[] }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
      {GROUPS.map(({ action, label }) => {
        const matches = candidates.filter((c) => c.recommended_action === action);
        const top3 = matches.slice(0, 3);
        return (
          <div key={action} className="rounded-lg border border-neutral-800 bg-neutral-900 p-3">
            <div className="mb-2 flex items-baseline justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-neutral-400">{label}</span>
              <span className="text-sm font-semibold text-neutral-200">{formatNumber(matches.length)}</span>
            </div>
            {top3.length === 0 ? (
              <p className="text-[11px] text-neutral-600">None</p>
            ) : (
              <ul className="space-y-1">
                {top3.map((c) => (
                  <li key={c.collection_item_id} className="truncate text-[11px] text-neutral-400">
                    <Link href={`/cards/${c.card_id}`} className="text-sky-400 hover:text-sky-300">
                      {c.card_code}
                    </Link>{" "}
                    {cardDisplayName(c)}
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}
