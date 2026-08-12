"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { RarityBadge } from "@/components/RarityBadge";
import { ErrorState, LoadingState } from "@/components/StateBlocks";
import { CardImageFrame } from "@/components/ui/CardImageFrame";
import { MarketIndexValue } from "@/components/ui/MarketIndexValue";
import { formatDate, formatJpy } from "@/lib/format";
import { fetchPrint, type PrintDetail, type PrintUiModel, toPrintUiModel } from "@/lib/prints";

/** Minimal print detail landing page.
 *
 * Deliberately unstyled beyond the shared primitives: this tranche is
 * catalogue + search, and this route exists only so a catalogue tile has a
 * print-scoped destination instead of linking to the legacy card_id-keyed
 * /cards/[id], which merges sibling prints. The full print-detail UX is the
 * next tranche - do not expand this page here.
 */
export default function PrintDetailPage() {
  const params = useParams<{ id: string }>();
  const printId = params?.id;

  const [print, setPrint] = useState<PrintUiModel | null>(null);
  const [detail, setDetail] = useState<PrintDetail | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");

  useEffect(() => {
    if (!printId) return;
    let cancelled = false;
    setStatus("loading");
    fetchPrint(printId)
      .then((result) => {
        if (cancelled) return;
        setDetail(result);
        setPrint(toPrintUiModel(result));
        setStatus("ready");
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [printId]);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-4xl px-4 py-6">
        <Link
          href="/cards"
          className="text-xs font-medium text-text-muted hover:text-text-secondary"
        >
          ← Back to cards
        </Link>

        {status === "loading" && <LoadingState>Loading print…</LoadingState>}
        {status === "error" && <ErrorState>Failed to load this print.</ErrorState>}

        {status === "ready" && print && detail && (
          <div className="mt-4 flex flex-col gap-6 sm:flex-row sm:items-start">
            <div className="w-full max-w-[280px] shrink-0 self-center sm:self-start">
              <CardImageFrame
                imageUrl={print.imageUrl}
                alt={`${print.displayName} (${print.cardCode})`}
                cardCode={print.cardCode}
                rarity={print.rarity}
                setCode={print.releaseCode}
                size="full"
                padded
              />
            </div>

            <div className="flex min-w-0 flex-1 flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center gap-2">
                  <h1 className="text-xl font-semibold text-text-primary">
                    {print.displayName}
                  </h1>
                  {print.rarity && <RarityBadge rarity={print.rarity} />}
                </div>
                {print.nameJp && print.nameJp !== print.displayName && (
                  <div className="text-sm text-text-secondary">{print.nameJp}</div>
                )}
                <div className="mono flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-text-muted">
                  <span>{print.cardCode}</span>
                  {print.releaseCode && (
                    <>
                      <span aria-hidden="true">·</span>
                      <span>{print.releaseCode}</span>
                    </>
                  )}
                  <span aria-hidden="true">·</span>
                  <span className="normal-case text-accent-gold">{print.treatment}</span>
                  <span aria-hidden="true">·</span>
                  <span>{print.cardType}</span>
                </div>
              </div>

              <div>
                <MarketIndexValue
                  index={print.marketIndex}
                  size="lg"
                  sourceNames={print.contributingSources}
                />
                {print.latestObservationAt && (
                  <div className="mt-1 text-[11px] text-text-faint">
                    Updated {formatDate(print.latestObservationAt)}
                  </div>
                )}
              </div>

              <dl className="flex flex-col gap-1 text-sm">
                {print.yuyuteiJpy !== null && (
                  <div className="flex items-center justify-between gap-4">
                    <dt className="text-text-muted">Yuyu-Tei</dt>
                    <dd className="mono tabular text-text-secondary">
                      {formatJpy(print.yuyuteiJpy)}
                    </dd>
                  </div>
                )}
                {print.snkrdunkJpy !== null && (
                  <div className="flex items-center justify-between gap-4">
                    <dt className="text-text-muted">SNKRDUNK floor</dt>
                    <dd className="mono tabular text-text-secondary">
                      {formatJpy(print.snkrdunkJpy)}
                    </dd>
                  </div>
                )}
              </dl>

              {detail.siblings.length > 0 && (
                <div className="flex flex-col gap-1.5">
                  <div className="text-xs font-medium uppercase tracking-wide text-text-muted">
                    Other printings
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {detail.siblings.map((sibling) => (
                      <Link
                        key={sibling.card_print_id}
                        href={`/prints/${sibling.card_print_id}`}
                        className="rounded-control border border-border-default px-2.5 py-1 text-xs text-text-secondary hover:text-text-primary"
                      >
                        {sibling.treatment}
                      </Link>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
