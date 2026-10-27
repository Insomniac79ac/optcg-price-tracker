"use client";

import { useCallback, useEffect, useState } from "react";

import { useCollectorSession } from "@/hooks/useCollectorSession";

/** What a signed-in collector already has of each exact card version, for the
 * public card pages (Collector v1 S6, PLAN E1): the "In your collection ×2"
 * badges and the add / watch actions on /prints/[id].
 *
 * Reads the v1 accounts API through the same-origin route handler
 * (/api/me/...; src/lib/meProxy.ts), which checks the session cookie and
 * mints the API token on the server. Nothing here holds a token. A visitor who
 * is not a collector makes no request at all. */

export interface HeldVersion {
  entryId: number;
  quantity: number;
  paidJpyPerCard: number | null;
  acquiredOn: string | null;
}

export interface WatchedVersion {
  entryId: number;
  targetJpy: number | null;
}

export type ShelfStatus =
  /** Session still resolving: render nothing that could flicker to a wrong state. */
  | "loading"
  /** Signed out, or an admin session: no collector account behind it. */
  | "visitor"
  /** COLLECTOR_ACCOUNTS_ENABLED is off on the API (every /me route 404s). */
  | "disabled"
  | "error"
  | "ready";

export interface CollectorShelf {
  status: ShelfStatus;
  held: ReadonlyMap<number, HeldVersion>;
  watched: ReadonlyMap<number, WatchedVersion>;
  refresh: () => void;
}

interface CollectionEntryJson {
  id: number;
  card_print_id: number | null;
  resolution: "exact" | "unresolved";
  quantity: number;
  paid_jpy_per_card: number | null;
  acquired_on: string | null;
}

interface WatchlistEntryJson {
  id: number;
  card_print_id: number | null;
  resolution: "exact" | "unresolved";
  target_jpy: number | null;
}

const EMPTY_HELD: ReadonlyMap<number, HeldVersion> = new Map();
const EMPTY_WATCHED: ReadonlyMap<number, WatchedVersion> = new Map();

/** Only exact entries count: an unresolved row ("needs a version") is never
 * shown as owning any particular version. */
export function heldByPrint(entries: readonly CollectionEntryJson[]): Map<number, HeldVersion> {
  const map = new Map<number, HeldVersion>();
  for (const entry of entries) {
    if (entry.resolution !== "exact" || entry.card_print_id === null) continue;
    map.set(entry.card_print_id, {
      entryId: entry.id,
      quantity: entry.quantity,
      paidJpyPerCard: entry.paid_jpy_per_card,
      acquiredOn: entry.acquired_on,
    });
  }
  return map;
}

export function watchedByPrint(entries: readonly WatchlistEntryJson[]): Map<number, WatchedVersion> {
  const map = new Map<number, WatchedVersion>();
  for (const entry of entries) {
    if (entry.resolution !== "exact" || entry.card_print_id === null) continue;
    map.set(entry.card_print_id, { entryId: entry.id, targetJpy: entry.target_jpy });
  }
  return map;
}

export class ShelfRequestError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ShelfRequestError";
  }
}

/** One same-origin request to /api/me/<path>. The browser sends Origin and
 * Sec-Fetch-Site itself, which is what the route handler's CSRF check reads. */
export async function meRequest<T>(method: string, path: string, body?: unknown): Promise<T | null> {
  const response = await fetch(`/api/me/${path}`, {
    method,
    cache: "no-store",
    credentials: "same-origin",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    let detail = "";
    try {
      const json = (await response.json()) as { detail?: unknown; error?: unknown };
      detail = typeof json.detail === "string" ? json.detail : typeof json.error === "string" ? json.error : "";
    } catch {
      // No body to explain it; the status says enough.
    }
    throw new ShelfRequestError(response.status, detail);
  }
  if (response.status === 204) return null;
  return (await response.json()) as T;
}

export function useCollectorShelf(): CollectorShelf {
  const { data: session, status: sessionStatus } = useCollectorSession();
  const isCollector = session?.sessionKind === "collector";
  const [state, setState] = useState<Omit<CollectorShelf, "refresh">>({
    status: "loading",
    held: EMPTY_HELD,
    watched: EMPTY_WATCHED,
  });
  const [generation, setGeneration] = useState(0);
  const refresh = useCallback(() => setGeneration((value) => value + 1), []);

  useEffect(() => {
    if (sessionStatus === "loading" || !isCollector) return;
    let cancelled = false;
    Promise.all([
      meRequest<{ entries: CollectionEntryJson[] }>("GET", "collection"),
      meRequest<{ entries: WatchlistEntryJson[] }>("GET", "watchlist"),
    ])
      .then(([collection, watchlist]) => {
        if (cancelled) return;
        setState({
          status: "ready",
          held: heldByPrint(collection?.entries ?? []),
          watched: watchedByPrint(watchlist?.entries ?? []),
        });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const disabled = error instanceof ShelfRequestError && error.status === 404;
        // 401: the session ended between page load and this request.
        const visitor = error instanceof ShelfRequestError && error.status === 401;
        setState({
          status: disabled ? "disabled" : visitor ? "visitor" : "error",
          held: EMPTY_HELD,
          watched: EMPTY_WATCHED,
        });
      });
    return () => {
      cancelled = true;
    };
  }, [sessionStatus, isCollector, generation]);

  // Derived, not stored: a visitor never had anything to fetch.
  if (sessionStatus === "loading") return { status: "loading", held: EMPTY_HELD, watched: EMPTY_WATCHED, refresh };
  if (!isCollector) return { status: "visitor", held: EMPTY_HELD, watched: EMPTY_WATCHED, refresh };
  return { ...state, refresh };
}
