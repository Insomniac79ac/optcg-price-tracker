"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AtlasArtworkStage, AtlasSectionIntro } from "./AtlasPrimitives";
import styles from "./HomeMovers.module.css";
import { SkeletonBlock } from "@/components/ui/SkeletonBlock";
import { resolveCardImageUrl } from "@/lib/cardImage";
import { fetchIndexMovers, formatIndexDay, formatRawPct, type IndexMovers } from "@/lib/cardPirateIndex";
import { fetchPrint } from "@/lib/prints";
import { formatJpy } from "@/lib/format";

type Status = { kind: "loading" } | { kind: "error" } | { kind: "ready"; data: IndexMovers };
const HOME_MOVERS_LIMIT = 4;

/** Four movers in server order, with bounded, optional exact-print context. */
export function HomeMovers() {
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  const [releases, setReleases] = useState<Record<number, string>>({});
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    fetchIndexMovers().then((data) => {
      if (cancelled) return;
      setStatus({ kind: "ready", data });
      // Each enrichment fails independently. Never delay the mover itself.
      data.movers.slice(0, HOME_MOVERS_LIMIT).forEach((mover) => {
        fetchPrint(mover.card_print_id).then((detail) => {
          if (cancelled) return;
          const label = detail.release_code || (detail.release_product_id ? "Special product" : null);
          if (label) setReleases((current) => ({ ...current, [mover.card_print_id]: label }));
        }).catch(() => {});
      });
    }).catch(() => { if (!cancelled) setStatus({ kind: "error" }); });
    return () => { cancelled = true; };
  }, [attempt]);

  return (
    <section aria-labelledby="home-movers" className={styles.section}>
      <div className={styles.intro} data-atlas-chapter>
        <AtlasSectionIntro id="home-movers" number="01" title="Cards on the move" description={<>
          Cards behind the latest published index move.
          {status.kind === "ready" && <span className={styles.date}>{formatIndexDay(status.data.as_of)}</span>}
        </>} />
      </div>
      <div className={styles.content}>
        {status.kind === "loading" && <div role="status" aria-label="Loading cards on the move" className="grid grid-cols-2 gap-3 sm:grid-cols-4 sm:gap-4">
          {Array.from({ length: HOME_MOVERS_LIMIT }, (_, i) => <SkeletonBlock key={i} className="aspect-[63/88] rounded-panel" />)}
        </div>}
        {status.kind === "error" && <p role="status" className="text-sm text-text-secondary">We can&rsquo;t show the cards on the move right now. <button type="button" onClick={() => { setStatus({ kind: "loading" }); setAttempt((n) => n + 1); }} className="min-h-11 underline">Retry movers</button></p>}
        {status.kind === "ready" && (status.data.prior_point_date === null
          ? <p className="text-sm text-text-secondary">The latest index update has no previous point to compare.</p>
          : status.data.movers.length === 0
            ? <p className="text-sm text-text-secondary">No cards moved on this published day.</p>
            : <ul className={`${styles.grid} ${status.data.movers.length === 1 ? styles.single : status.data.movers.length === 2 ? styles.pair : ""}`}>
              {status.data.movers.slice(0, HOME_MOVERS_LIMIT).map((mover) => (
                <li key={mover.card_print_id} className="min-w-0">
                  <Link href={`/prints/${mover.card_print_id}`} prefetch={false} className={`${styles.print} focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-teal`}>
                    <AtlasArtworkStage image={{ imageUrl: resolveCardImageUrl(mover.display_image_url), alt: mover.name ?? mover.card_code ?? "Card artwork", cardCode: mover.card_code ?? "—", rarity: mover.rarity }} />
                    <div className={styles.caption}>
                      <p className="break-words text-sm font-semibold text-text-primary">{mover.name ?? mover.card_code ?? "Unknown card"}</p>
                      <p className={styles.metadata}>{[mover.card_code, mover.treatment, mover.language?.toUpperCase()].filter(Boolean).join(" · ")}</p>
                      {releases[mover.card_print_id] && <p className={styles.metadata}>Found in {releases[mover.card_print_id]}</p>}
                      <p className={styles.move} data-direction={mover.raw_pct === 0 ? "neutral" : mover.direction}>
                        <span aria-hidden="true">{mover.raw_pct === 0 ? "→" : mover.direction === "up" ? "↑" : "↓"}</span>{" "}
                        <span>{mover.raw_pct === 0 ? "Unchanged" : mover.direction === "up" ? "Up" : "Down"}</span>{" "}
                        <span>{formatRawPct(mover.raw_pct)}</span>
                      </p>
                      <p className={styles.prices}>Market Index {formatJpy(mover.current_value_jpy)}</p>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>)}
      </div>
      <Link href="/analytics#latest-moves" prefetch={false} className="mt-3 inline-flex min-h-11 items-center py-2 text-sm font-medium text-accent-teal hover:text-accent-teal-hover focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-teal">See what moved</Link>
    </section>
  );
}
