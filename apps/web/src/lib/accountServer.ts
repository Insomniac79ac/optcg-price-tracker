import "server-only";

import { API_INTERNAL_URL, type CollectorIdentity, mintApiToken } from "@/lib/collectorApi";

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
  | { state: "ok"; profile: AccountProfile; preferences: AccountPreferences }
  // COLLECTOR_ACCOUNTS_ENABLED is off on the API: every /me route is 404.
  | { state: "disabled" }
  | { state: "error" };

const ACCOUNT_PATHS = ["profile", "preferences"] as const;
type AccountPath = (typeof ACCOUNT_PATHS)[number];

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

async function getMe<T>(path: AccountPath, token: string): Promise<{ status: number; body?: T }> {
  let response: Response;
  try {
    response = await fetch(`${API_INTERNAL_URL}/me/${path}`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
  } catch (error) {
    logAccountUpstreamFailure(`GET /me/${path}`, { error });
    throw error;
  }
  // 404 is the accounts-disabled state, not a failure.
  if (!response.ok) {
    if (response.status !== 404) logAccountUpstreamFailure(`GET /me/${path}`, { status: response.status });
    return { status: response.status };
  }
  try {
    return { status: response.status, body: (await response.json()) as T };
  } catch (error) {
    logAccountUpstreamFailure(`GET /me/${path} body`, { status: response.status, error });
    throw error;
  }
}

/** Profile and preferences for /account, read server-side with one
 * short-lived token. Never throws: the page renders a plain state instead. */
export async function loadAccountOverview(identity: CollectorIdentity): Promise<AccountOverview> {
  let token: string;
  try {
    token = await mintApiToken(identity);
  } catch (error) {
    logAccountUpstreamFailure("mint API token", { error });
    return { state: "error" };
  }
  try {
    const [profile, preferences] = await Promise.all([
      getMe<AccountProfile>("profile", token),
      getMe<AccountPreferences>("preferences", token),
    ]);
    if (profile.status === 404 || preferences.status === 404) return { state: "disabled" };
    if (!profile.body || !preferences.body) return { state: "error" };
    return { state: "ok", profile: profile.body, preferences: preferences.body };
  } catch {
    // Already logged by getMe with its status or error class.
    return { state: "error" };
  }
}
