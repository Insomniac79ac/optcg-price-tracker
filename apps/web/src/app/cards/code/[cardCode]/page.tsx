"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { ErrorState, LoadingState } from "@/components/StateBlocks";
import { CardPrintingChooser } from "@/components/ui/CardPrintingChooser";
import { CollectorEmptyState } from "@/components/ui/CollectorEmptyState";
import {
  fetchPrintCatalogue,
  resolveCanonicalPrintIdentity,
  toPrintUiModel,
  type CanonicalPrintIdentity,
  type PrintUiModel,
} from "@/lib/prints";

/** The canonical card family route: every printing of one card code.
 *
 * WHY THIS ROUTE EXISTS. `/cards/{id}` is keyed by a legacy `cards` row, and
 * that table holds 25 rows against 2,710 canonical cards - so 99% of the
 * catalogue has no `/cards/{id}` URL at all, and the rows that do exist
 * disagree with the catalogue about which card a code names. A card family is
 * identified by its CARD CODE, which both sides agree on and which the public
 * catalogue can address directly. This is the forward-looking family route;
 * `/cards/{id}` stays as a compatibility surface.
 *
 * PUBLIC BY DESIGN. This is catalogue, not collection: it carries no
 * ownership, wishlist, grading, tags or notes panels and makes no request that
 * needs a session. A signed-in collector's own tools stay on `/cards/{id}`
 * until they are given a canonical key of their own.
 *
 * WHAT IT REFUSES TO DO. It computes no family-level price, states no
 * representative rarity or variant, merges no observations across printings,
 * and never selects a default printing - each printing keeps its own artwork,
 * its own chips and its own print-scoped Market Index, and the collector
 * chooses. Those guarantees live in CardPrintingChooser and PrintCardTile and
 * are not re-implemented here.
 */
type Status = "loading" | "error" | "not_found" | "ambiguous" | "ready";

export default function CardFamilyPage() {
  const params = useParams<{ cardCode: string }>();
  // Next has already percent-decoded the segment; this is the card code as
  // published, compared verbatim against the catalogue's own value.
  const cardCode = params?.cardCode;

  const [prints, setPrints] = useState<PrintUiModel[]>([]);
  const [identity, setIdentity] = useState<CanonicalPrintIdentity | null>(null);
  const [status, setStatus] = useState<Status>("loading");

  useEffect(() => {
    if (!cardCode) return;
    let cancelled = false;
    setStatus("loading");
    setPrints([]);
    setIdentity(null);

    fetchPrintCatalogue({ q: cardCode, limit: 100 })
      .then((result) => {
        if (cancelled) return;
        // `q` is a substring ILIKE across canonical name_en, name_jp AND
        // card_code, so a query can match another card by code prefix or by a
        // name containing the string. The exact-code filter is what turns a
        // search result into an identity match - it is the whole basis of this
        // page's claim to be one card, not decoration.
        const exact = result.items.filter((item) => item.card_code === cardCode);
        if (exact.length === 0) {
          setStatus("not_found");
          return;
        }

        // Fail closed on any disagreement. resolveCanonicalPrintIdentity
        // returns a name only when every record agrees on one canonical card
        // AND one name; it never takes the first row, votes, or normalises a
        // difference away. A page that cannot say which card it is has no
        // business showing that card's printings as if it could.
        const resolved = resolveCanonicalPrintIdentity(exact);
        if (!resolved) {
          setStatus("ambiguous");
          return;
        }

        setIdentity(resolved);
        setPrints(exact.map(toPrintUiModel));
        setStatus("ready");
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, [cardCode]);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Link
          href="/cards"
          className="mb-4 inline-flex items-center gap-1.5 text-xs font-medium text-text-muted transition-colors hover:text-accent-teal"
        >
          <span aria-hidden="true">←</span> Catalogue
        </Link>

        {status === "loading" && <LoadingState>Loading this card…</LoadingState>}

        {status === "error" && (
          <ErrorState tone="collector">This card couldn’t be loaded right now.</ErrorState>
        )}

        {status === "not_found" && (
          <CollectorEmptyState
            title="This card isn’t in the Atlas."
            action={
              <Link
                href="/cards"
                className="text-xs font-medium text-accent-teal hover:text-accent-teal-hover"
              >
                Browse the catalogue →
              </Link>
            }
          >
            No printing carries the card code {cardCode}.
          </CollectorEmptyState>
        )}

        {/* Fail-closed, stated plainly. The printings are deliberately NOT
            shown: they disagree about which card they belong to, and listing
            them under one heading would be the page picking a winner. */}
        {status === "ambiguous" && (
          <CollectorEmptyState
            title="This card code can’t be shown yet."
            action={
              <Link
                href="/cards"
                className="text-xs font-medium text-accent-teal hover:text-accent-teal-hover"
              >
                Browse the catalogue →
              </Link>
            }
          >
            The catalogue records for {cardCode} don’t agree on which card it
            is, so the Atlas won’t guess.
          </CollectorEmptyState>
        )}

        {status === "ready" && identity && (
          <article>
            <header className="mb-5">
              <h1 className="font-display text-[30px] font-semibold leading-[1.05] tracking-tight text-text-primary sm:text-[34px]">
                {identity.name}
              </h1>
              <p className="mono mt-2 text-xs text-text-muted">{cardCode}</p>
            </header>

            <CardPrintingChooser
              status="ready"
              prints={prints}
              cardCode={cardCode ?? ""}
              canonicalName={identity.name}
            />
          </article>
        )}
      </main>
    </div>
  );
}
