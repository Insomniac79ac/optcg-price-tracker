import "server-only";

import { logAccountUpstreamFailure } from "@/lib/accountServer";
import {
  COLLECTION_WINDOWS,
  type CollectionResponse,
  type CollectionValue,
  type CollectionWindow,
} from "@/lib/collection";
import { API_INTERNAL_URL, type CollectorIdentity, mintApiToken } from "@/lib/collectorApi";

export type CollectionPage =
  | {
      state: "ok";
      collection: CollectionResponse;
      /** One response per window; null when that window's read failed (its
       * chip then says so instead of guessing). */
      values: Record<CollectionWindow, CollectionValue | null>;
    }
  // COLLECTOR_ACCOUNTS_ENABLED is off on the API: every /me route is 404.
  | { state: "disabled" }
  | { state: "error" };

class UpstreamStatus extends Error {
  constructor(public readonly status: number) {
    super(`upstream ${status}`);
    this.name = "UpstreamStatus";
  }
}

async function getMe<T>(path: string, step: string, token: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_INTERNAL_URL}/me/${path}`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
  } catch (error) {
    logAccountUpstreamFailure(step, { error });
    throw error;
  }
  if (!response.ok) {
    // 404 is the accounts-disabled state, not a failure.
    if (response.status !== 404) logAccountUpstreamFailure(step, { status: response.status });
    throw new UpstreamStatus(response.status);
  }
  try {
    return (await response.json()) as T;
  } catch (error) {
    logAccountUpstreamFailure(`${step} body`, { status: response.status, error });
    throw error;
  }
}

/** The collection and its value for every window, read server-side with one
 * short-lived token (the browser never holds it). Never throws: the page
 * renders a plain state instead. Failures are logged by status and error
 * class only (logAccountUpstreamFailure). */
export async function loadCollectionPage(identity: CollectorIdentity): Promise<CollectionPage> {
  let token: string;
  try {
    token = await mintApiToken(identity);
  } catch (error) {
    logAccountUpstreamFailure("mint API token", { error });
    return { state: "error" };
  }

  const values = Promise.all(
    COLLECTION_WINDOWS.map((window) =>
      getMe<CollectionValue>(`collection/value?window=${window}`, `GET /me/collection/value ${window}`, token).catch(
        () => null,
      ),
    ),
  );
  try {
    const collection = await getMe<CollectionResponse>("collection", "GET /me/collection", token);
    const [week, month, all] = await values;
    return { state: "ok", collection, values: { "7d": week, "30d": month, all } };
  } catch (error) {
    await values;
    if (error instanceof UpstreamStatus && error.status === 404) return { state: "disabled" };
    return { state: "error" };
  }
}
