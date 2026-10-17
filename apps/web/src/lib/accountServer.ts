import "server-only";

import type { CollectionValue } from "@/lib/collection";
import { API_INTERNAL_URL, type CollectorIdentity, mintApiToken } from "@/lib/collectorApi";
import type { WatchlistResponse } from "@/lib/watchlist";

export interface AccountProfile {
  email: string;
  name: string | null;
  member_since: string;
}

export interface AccountPreferences {
  currency: string;
  collection_visibility: string;
}

export type AccountOverview =
  | {
      state: "ok";
      profile: AccountProfile;
      preferences: AccountPreferences;
      /** The 7D collection value and the watchlist behind the overview strip;
       * null when that read failed (its tiles then say so). */
      collection: CollectionValue | null;
      watchlist: WatchlistResponse | null;
    }
  // COLLECTOR_ACCOUNTS_ENABLED is off on the API: every /me route is 404.
  | { state: "disabled" }
  | { state: "error" };

type AccountPath = "profile" | "preferences" | "collection/value?window=7d" | "watchlist";

/** One server log line for a failed upstream step, so a broken /account can
 * be diagnosed from the deployment logs. Carries only the fixed step name,
 * an HTTP status and an error class name: never the token, the user's
 * identity, a response body or an error message (which can echo either). */
export function logAccountUpstreamFailure(step: string, detail: { status?: number; error?: unknown }): void {
  const parts = [`[account] ${step} failed`];
  if (detail.status !== undefined) parts.push(`status=${detail.status}`);
  if (detail.error !== undefined) {
    const name = detail.error instanceof Error ? detail.error.name : typeof detail.error;
    parts.push(`error=${/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(name) ? name : "unknown"}`);
  }
  console.error(parts.join(" "));
}

/** The fixed step name for a log line: the path without its query. */
function step(path: AccountPath): string {
  return path.split("?")[0];
}

async function getMe<T>(path: AccountPath, token: string): Promise<{ status: number; body?: T }> {
  let response: Response;
  try {
    response = await fetch(`${API_INTERNAL_URL}/me/${path}`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
  } catch (error) {
    logAccountUpstreamFailure(`GET /me/${step(path)}`, { error });
    throw error;
  }
  // 404 is the accounts-disabled state, not a failure.
  if (!response.ok) {
    if (response.status !== 404) logAccountUpstreamFailure(`GET /me/${step(path)}`, { status: response.status });
    return { status: response.status };
  }
  try {
    return { status: response.status, body: (await response.json()) as T };
  } catch (error) {
    logAccountUpstreamFailure(`GET /me/${step(path)} body`, { status: response.status, error });
    throw error;
  }
}

/** Profile, preferences and the overview strip's collection value and
 * watchlist for /account, read server-side in parallel with one short-lived
 * token. Never throws: the page renders a plain state instead, and a failed
 * strip read only empties its own tiles. */
export async function loadAccountOverview(identity: CollectorIdentity): Promise<AccountOverview> {
  let token: string;
  try {
    token = await mintApiToken(identity);
  } catch (error) {
    logAccountUpstreamFailure("mint API token", { error });
    return { state: "error" };
  }
  // Strip reads never fail the page; getMe has already logged why.
  const strip = Promise.all([
    getMe<CollectionValue>("collection/value?window=7d", token).then((r) => r.body ?? null, () => null),
    getMe<WatchlistResponse>("watchlist", token).then((r) => r.body ?? null, () => null),
  ]);
  try {
    const [profile, preferences] = await Promise.all([
      getMe<AccountProfile>("profile", token),
      getMe<AccountPreferences>("preferences", token),
    ]);
    const [collection, watchlist] = await strip;
    if (profile.status === 404 || preferences.status === 404) return { state: "disabled" };
    if (!profile.body || !preferences.body) return { state: "error" };
    return { state: "ok", profile: profile.body, preferences: preferences.body, collection, watchlist };
  } catch {
    await strip;
    // Already logged by getMe with its status or error class.
    return { state: "error" };
  }
}
