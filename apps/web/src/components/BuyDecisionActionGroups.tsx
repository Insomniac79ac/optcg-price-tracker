import Link from "next/link";

import type { BuyDecisionAction, BuyDecisionCandidate } from "@/lib/api";
import { cardDisplayName, formatNumber } from "@/lib/format";

const GROUPS: { action: BuyDecisionAction; label: string }[] = [
  { action: "review_buy", label: "Review Buy" },
  { action: "wait", label: "Wait" },
  { action: "missing_data", label: "Missing Data" },
  { action: "monitor", label: "Monitor" },
  { action: "skip", label: "Skip" },
];

/** Compact per-action summary shown above the full candidate table - count
 * plus the top 3 cards (candidates already arrive score-sorted from the
 * API, so `.slice(0, 3)` is "top 3 by score" with no extra sorting here). */
export function BuyDecisionActionGroups({ candidates }: { candidates: BuyDecisionCandidate[] }) {
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
                  <li key={c.wishlist_item_id} className="truncate text-[11px] text-neutral-400">
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
