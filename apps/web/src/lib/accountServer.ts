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

async function getMe<T>(path: string, token: string): Promise<{ status: number; body?: T }> {
  const response = await fetch(`${API_INTERNAL_URL}/me/${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) return { status: response.status };
  return { status: response.status, body: (await response.json()) as T };
}

/** Profile and preferences for /account, read server-side with one
 * short-lived token. Never throws: the page renders a plain state instead. */
export async function loadAccountOverview(identity: CollectorIdentity): Promise<AccountOverview> {
  try {
    const token = await mintApiToken(identity);
    const [profile, preferences] = await Promise.all([
      getMe<AccountProfile>("profile", token),
      getMe<AccountPreferences>("preferences", token),
    ]);
    if (profile.status === 404 || preferences.status === 404) return { state: "disabled" };
    if (!profile.body || !preferences.body) return { state: "error" };
    return { state: "ok", profile: profile.body, preferences: preferences.body };
  } catch {
    return { state: "error" };
  }
}
