import { sanitizeCallbackUrl } from "./callbackUrl";

// Navigation only. This value never grants authorization.
export const ADMIN_CALLBACK_HEADER = "x-atlas-admin-callback";

export function safeAdminCallbackUrl(candidate?: string | null): string {
  const safe = sanitizeCallbackUrl(candidate);
  try {
    const url = new URL(safe, "https://atlas.invalid");
    const path = decodeURIComponent(safe.split(/[?#]/, 1)[0]);
    if (
      url.origin !== "https://atlas.invalid" ||
      (url.pathname !== "/admin" && !url.pathname.startsWith("/admin/")) ||
      url.pathname === "/admin/login" || url.pathname.startsWith("/admin/login/") ||
      path !== url.pathname || path.includes("\\") || /[\x00-\x20\x7f]/.test(path)
    ) return "/admin";
    return safe;
  } catch {
    return "/admin";
  }
}

export function adminLoginHref(callbackUrl?: string | null, expired = false): string {
  const params = new URLSearchParams({ callbackUrl: safeAdminCallbackUrl(callbackUrl) });
  if (expired) params.set("reason", "session-expired");
  return `/admin/login?${params}`;
}
