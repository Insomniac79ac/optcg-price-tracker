/** Public browsing surfaces only. Private analytics leaves and account/admin
 * tools deliberately retain their existing shell; this is not an auth guard. */
export function isPublicShellRoute(pathname: string): boolean {
  return pathname === "/" || pathname === "/analytics" ||
    pathname === "/cards" || pathname.startsWith("/cards/") ||
    pathname.startsWith("/prints/");
}

/** An exact print belongs to Cards in both public navigation surfaces. */
export function publicSectionActive(pathname: string, href: string): boolean {
  if (href === "/cards") {
    return pathname === "/cards" || pathname.startsWith("/cards/") || pathname.startsWith("/prints/");
  }
  return pathname === href;
}
