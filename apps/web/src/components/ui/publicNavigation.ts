/** Public browsing surfaces only. Private analytics leaves and account/admin
 * tools deliberately retain their existing shell; this is not an auth guard. */
export function isPublicShellRoute(pathname: string): boolean {
  return pathname === "/" || pathname === "/analytics" ||
    pathname === "/cards" || pathname.startsWith("/cards/") ||
    pathname.startsWith("/prints/") ||
    // Sign-in and the collector's account share the homepage's chrome
    // (Collector v1 S6): same compact mark, header and bottom navigation.
    pathname === "/sign-in" || pathname === "/account";
}

/** An exact print belongs to Cards in both public navigation surfaces. */
export function publicSectionActive(pathname: string, href: string): boolean {
  if (href === "/cards") {
    return pathname === "/cards" || pathname.startsWith("/cards/") || pathname.startsWith("/prints/");
  }
  return pathname === href;
}
