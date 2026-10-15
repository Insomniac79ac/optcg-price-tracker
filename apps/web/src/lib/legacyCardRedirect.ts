import "server-only";

/** What GET /cards/{card_id}/print-destination answers (services/api
 * app/api/cards.py): the one print a legacy card reaches through active,
 * approved mappings, or none. */
export interface LegacyCardDestination {
  card_id: number;
  card_code: string;
  card_print_id: number | null;
  resolution: "exact" | "multiple_prints" | "no_print";
}

export type LegacyCardLookup =
  | { kind: "found"; destination: LegacyCardDestination }
  | { kind: "not_found" }
  | { kind: "unavailable" };

const LEGACY_CARD_ID = /^[1-9]\d{0,9}$/;

/** Where the retired /cards/{id} page sends a visitor (Collector v1 S6,
 * PLAN E1 and B2), or null for "no such card" (404).
 *
 * - /prints/{id} only when the API says the legacy card reaches exactly one
 *   active print (resolution "exact" with a positive print id). Nothing here
 *   picks a print from a card code.
 * - otherwise the card code's version chooser, /cards/code/{code}, so the
 *   visitor chooses the exact version themselves;
 * - null when there is not even a card code to fall back to.
 *
 * Both answers are permanent (308) redirects, so this is deliberately strict
 * about what it accepts. */
export function legacyCardRedirectPath(destination: LegacyCardDestination): string | null {
  const printId = destination.card_print_id;
  if (destination.resolution === "exact" && Number.isSafeInteger(printId) && printId !== null && printId > 0) {
    return `/prints/${printId}`;
  }
  const code = typeof destination.card_code === "string" ? destination.card_code.trim() : "";
  return code ? `/cards/code/${encodeURIComponent(code)}` : null;
}

export function isLegacyCardId(id: string): boolean {
  return LEGACY_CARD_ID.test(id);
}

/** Reads the destination server-side. No cookie or token is sent: this is a
 * public, read-only lookup. A failure is reported as "unavailable", never
 * guessed into a redirect, because a 308 is cached by the browser. */
export async function readLegacyCardDestination(id: string): Promise<LegacyCardLookup> {
  if (!isLegacyCardId(id)) return { kind: "not_found" };
  try {
    // The same public API origin as every other public server read
    // (src/lib/publicServer.ts).
    const origin = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
    const response = await fetch(`${origin}/cards/${id}/print-destination`, {
      cache: "no-store",
      signal: AbortSignal.timeout(6_000),
    });
    if (response.status === 404) return { kind: "not_found" };
    if (!response.ok) {
      console.error(`[legacy card redirect] lookup failed status=${response.status}`);
      return { kind: "unavailable" };
    }
    const body = (await response.json()) as Partial<LegacyCardDestination>;
    if (String(body.card_id) !== id || typeof body.card_code !== "string" || !body.resolution) {
      console.error("[legacy card redirect] lookup answered an unexpected shape");
      return { kind: "unavailable" };
    }
    return { kind: "found", destination: body as LegacyCardDestination };
  } catch (error) {
    console.error(`[legacy card redirect] lookup failed error=${error instanceof Error ? error.name : "unknown"}`);
    return { kind: "unavailable" };
  }
}
