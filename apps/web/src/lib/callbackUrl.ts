// Validates a caller-supplied `callbackUrl` query value before it's ever
// used to redirect a browser. Only same-origin, root-relative paths are
// allowed - everything else (absolute URLs, protocol-relative URLs,
// backslash tricks, embedded control characters) is an open-redirect vector
// and falls back to "/".

const SAFE_DEFAULT = "/";

// Deliberately matches C0 control characters, space, and DEL.
const UNSAFE_CHARS = /[\x00-\x20\x7F]/;

export function sanitizeCallbackUrl(candidate: string | null | undefined): string {
  if (!candidate) return SAFE_DEFAULT;

  // Must be root-relative - rejects absolute URLs ("https://evil.example",
  // "javascript:alert(1)") and anything not starting with a single "/".
  if (!candidate.startsWith("/")) return SAFE_DEFAULT;

  // Protocol-relative URLs ("//evil.example") resolve to a different origin
  // in a browser even though they start with "/".
  if (candidate.startsWith("//")) return SAFE_DEFAULT;

  // Some browsers normalize a leading "/\" to "//", making it an equivalent
  // protocol-relative bypass of the check above.
  if (candidate.startsWith("/\\")) return SAFE_DEFAULT;

  // Whitespace/control characters (including plain spaces) have no place in
  // a path+query and are a common way to smuggle a scheme past naive checks.
  if (UNSAFE_CHARS.test(candidate)) return SAFE_DEFAULT;

  return candidate;
}
