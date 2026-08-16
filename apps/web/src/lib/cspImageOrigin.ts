/** Deriving the CSP `img-src` allowlist entry for our own asset origin.
 *
 * Card artwork we mirror ourselves is served from an object-storage bucket
 * behind a public base URL - `R2_PUBLIC_BASE_URL`, the same setting the API
 * uses to build every `display_image.url` it serves (see
 * services/api/app/services/object_storage.py's `normalize_public_base_url`).
 * The browser therefore requests those images from whatever host that
 * setting names, and CSP has to permit exactly that host or the request is
 * blocked before it is ever sent.
 *
 * Deliberately derived from configuration rather than hardcoded: staging's
 * bucket is served from a `*.r2.dev` origin today and production will move to
 * a custom asset domain, and neither should require a code change. Equally
 * deliberately, no wildcard is ever emitted - one configured value maps to
 * one exact origin.
 *
 * `R2_PUBLIC_BASE_URL` is a build-time, server-side setting and is *not*
 * exposed as `NEXT_PUBLIC_*`: nothing in the client bundle needs it, because
 * the API already returns fully-formed absolute image URLs. Its only job here
 * is to name an origin in a response header.
 */

/** A configured asset base URL that cannot safely become a CSP origin.
 *
 * Thrown while the Next.js config module is being evaluated, so a bad value
 * fails the build loudly instead of silently dropping the origin and leaving
 * every mirrored image blocked at runtime. Messages name the *setting* and
 * never echo the configured value. */
export class ImageOriginConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ImageOriginConfigError";
  }
}

const SETTING = "R2_PUBLIC_BASE_URL";

/** The CSP origin for our own asset host, or `null` when none is configured.
 *
 * Unset or blank is a valid, supported state - local checkouts, tests and any
 * deployment that has not adopted mirrored assets keep the pre-existing
 * policy untouched. A non-empty value must be a plain https URL: anything
 * else is a configuration mistake, and a mistake that silently omitted the
 * origin would look exactly like the bug this exists to fix.
 *
 * Only the origin survives - scheme, host and any explicit port. Path, query
 * and fragment are dropped, because CSP matches source expressions by origin
 * and a path fragment in the allowlist would narrow it in ways the object
 * keys under that base would not satisfy. `https://assets.example.com/cards/`
 * therefore contributes `https://assets.example.com`. */
export function ownedAssetImageOrigin(raw: string | undefined | null): string | null {
  if (raw == null) return null;
  const value = raw.trim();
  if (value === "") return null;

  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new ImageOriginConfigError(`${SETTING} is not a valid absolute URL.`);
  }

  if (parsed.protocol !== "https:") {
    throw new ImageOriginConfigError(
      `${SETTING} must use https, so that mirrored card images are not served over an ` +
        "insecure origin.",
    );
  }
  // A base URL is a public delivery address; embedded credentials mean the
  // value is either wrong or a secret that must not reach a response header.
  if (parsed.username !== "" || parsed.password !== "") {
    throw new ImageOriginConfigError(`${SETTING} must not contain credentials.`);
  }
  if (parsed.hostname === "") {
    throw new ImageOriginConfigError(`${SETTING} must include a hostname.`);
  }

  return parsed.origin;
}

/** The full `img-src` host list: the always-approved hotlinked hosts, plus our
 * own asset origin when one is configured.
 *
 * Order is stable and the result is de-duplicated, so configuring a base URL
 * that happens to sit on an already-approved host is a no-op rather than a
 * repeated token. */
export function buildImageSrcHosts(
  approvedHosts: readonly string[],
  ownedAssetBaseUrl: string | undefined | null,
): string[] {
  const hosts = new Set<string>(approvedHosts);
  const origin = ownedAssetImageOrigin(ownedAssetBaseUrl);
  if (origin) hosts.add(origin);
  return Array.from(hosts);
}
