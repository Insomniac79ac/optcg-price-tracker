/** Public browsing surfaces only. Private analytics leaves and account/admin
 * tools deliberately retain their existing shell; this is not an auth guard. */
export function isPublicShellRoute(pathname: string): boolean {
  return pathname === "/" || pathname === "/analytics" ||
    pathname === "/cards" || pathname.startsWith("/cards/") ||
    pathname.startsWith("/prints/") ||
    // Sign-in, the collector's account (Collector v1 S6), collection (S7)
    // and watchlist (S8) share the homepage's chrome: same compact mark,
    // header and bottom navigation.
    pathname === "/sign-in" || pathname === "/account" || pathname === "/collection" || pathname === "/watchlist";
}

/** An exact print belongs to Cards in both public navigation surfaces. */
export function publicSectionActive(pathname: string, href: string): boolean {
  if (href === "/cards") {
    return pathname === "/cards" || pathname.startsWith("/cards/") || pathname.startsWith("/prints/");
  }
  return pathname === href;
}
