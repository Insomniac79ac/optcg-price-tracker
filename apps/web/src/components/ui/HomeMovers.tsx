"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CardImageFrame } from "@/components/ui/CardImageFrame";
import { SkeletonBlock } from "@/components/ui/SkeletonBlock";
import { resolveCardImageUrl } from "@/lib/cardImage";
import { fetchIndexMovers, formatIndexDay, formatRawPct, type IndexMovers } from "@/lib/cardPirateIndex";
import { formatJpy } from "@/lib/format";

type Status = { kind: "loading" } | { kind: "error" } | { kind: "ready"; data: IndexMovers };
const HOME_MOVERS_LIMIT = 4;

/** A small view of the existing payload, in server order. No print lookups,
 * price arithmetic, or index contribution calculations belong here. */
export function HomeMovers() {
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  useEffect(() => {
    let cancelled = false;
    fetchIndexMovers().then((data) => {
      if (!cancelled) setStatus({ kind: "ready", data });
    }).catch(() => { if (!cancelled) setStatus({ kind: "error" }); });
    return () => { cancelled = true; };
  }, []);

  return (
    <section aria-labelledby="home-movers" className="mt-6 sm:mt-8">
      <h2 id="home-movers" className="font-display text-xl font-semibold text-text-primary">Cards on the move</h2>
      <p className="mt-1 text-sm text-text-muted">Cards behind the latest published index move.</p>
      {status.kind === "ready" && <p className="mt-1 text-xs text-text-muted">{formatIndexDay(status.data.as_of)}</p>}
      <div className="mt-4">
        {status.kind === "loading" && <div role="status" aria-label="Loading cards on the move" className="grid grid-cols-2 gap-3 sm:grid-cols-4 sm:gap-4">
          {Array.from({ length: HOME_MOVERS_LIMIT }, (_, i) => <SkeletonBlock key={i} className="aspect-[63/88] rounded-panel" />)}
        </div>}
        {status.kind === "error" && <p role="status" className="text-sm text-text-secondary">We can&rsquo;t show the cards on the move right now.</p>}
        {status.kind === "ready" && (status.data.prior_point_date === null
          ? <p className="text-sm text-text-secondary">The latest index update has no previous point to compare.</p>
          : status.data.movers.length === 0
            ? <p className="text-sm text-text-secondary">No cards moved on this published day.</p>
            : <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4 sm:gap-4">
              {status.data.movers.slice(0, HOME_MOVERS_LIMIT).map((mover) => (
                <li key={mover.card_print_id} className="min-w-0">
                  <Link href={`/prints/${mover.card_print_id}`} prefetch={false} className="block h-full rounded-panel border border-border-muted bg-bg-surface p-2 transition-colors hover:border-accent-teal active:bg-bg-card focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-teal">
                    <CardImageFrame imageUrl={resolveCardImageUrl(mover.display_image_url)} alt={mover.name ?? mover.card_code ?? "Card artwork"} cardCode={mover.card_code ?? "—"} rarity={mover.rarity} size="full" padded />
                    <div className="px-1 pb-1 pt-3">
                      <p className="break-words text-sm font-semibold text-text-primary">{mover.name ?? mover.card_code ?? "Unknown card"}</p>
                      <p className="mt-1 text-xs text-text-muted">{[mover.card_code, mover.treatment, mover.language?.toUpperCase()].filter(Boolean).join(" · ")}</p>
                      <p className={`mt-2 text-sm font-semibold ${mover.direction === "up" ? "text-accent-teal" : "text-text-primary"}`}><span className="sr-only">Price move: </span>{formatRawPct(mover.raw_pct)}</p>
                      <p className="mt-1 text-xs text-text-secondary">{formatJpy(mover.prior_value_jpy)} → {formatJpy(mover.current_value_jpy)}</p>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>)}
      </div>
      <Link href="/analytics#latest-moves" prefetch={false} className="mt-3 inline-flex py-2 text-sm font-medium text-accent-teal hover:text-accent-teal-hover focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-teal">See what moved</Link>
    </section>
  );
}
