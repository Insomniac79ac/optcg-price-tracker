import { notFound, permanentRedirect } from "next/navigation";

import { legacyCardRedirectPath, readLegacyCardDestination } from "@/lib/legacyCardRedirect";

export const dynamic = "force-dynamic";

/** /cards/{id}, retired in Collector v1 S6 (PLAN E1).
 *
 * The page that lived here was keyed by a legacy `cards` row and carried the
 * old ownership, wishlist, grading, notes and activity panels. Every card
 * version now has its own page, /prints/{id}, where collection actions live,
 * so this route only forwards old links:
 *
 * - 308 to /prints/{id} when the legacy card reaches exactly one active print
 *   through active, approved mappings (decided by the API, never from a card
 *   code);
 * - otherwise 308 to /cards/code/{cardCode}, where the visitor picks the exact
 *   version;
 * - 404 for an unknown id.
 *
 * If the lookup itself fails, this throws to the error page rather than
 * redirecting: a permanent redirect is cached by the browser, so it is only
 * ever sent for an answer the API actually gave. */
export default async function LegacyCardPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const lookup = await readLegacyCardDestination(id);
  if (lookup.kind === "not_found") notFound();
  if (lookup.kind === "unavailable") throw new Error("Legacy card lookup unavailable");
  const path = legacyCardRedirectPath(lookup.destination);
  if (!path) notFound();
  permanentRedirect(path);
}
