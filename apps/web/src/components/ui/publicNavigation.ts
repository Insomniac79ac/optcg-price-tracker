export interface NavItem {
  href: string;
  label: string;
}

// The three public destinations, shared by the desktop header nav (TopBar),
// the mobile bottom nav (PublicBottomNav) and the mobile drawer (SidebarNav)
// so the surfaces cannot drift apart or quietly gain an admin entry.
//
// "Market Index" is not a destination: /market/movers became a re-sorted copy
// of /cards and redirects there (tranche 1A, 2026-08-19); the metric stays on
// every tile and print page. "Market" points at /analytics, the public market
// landscape (Analytics 1A-B, 2026-09-06), whose endpoints are deliberately
// unauthenticated. The legacy /analytics/* leaf pages (collection, wishlist,
// grading, ...) describe one collector's holdings, are gated in proxyGuard and
// get no entry here.
export const PUBLIC_NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Home" },
  { href: "/cards", label: "Card Prices" },
  { href: "/analytics", label: "Market" },
];

/** Public browsing surfaces only. Private analytics leaves and account/admin
 * tools deliberately retain their existing shell; this is not an auth guard. */
export function isPublicShellRoute(pathname: string): boolean {
  return pathname === "/" || pathname === "/analytics" ||
    pathname === "/cards" || pathname.startsWith("/cards/") ||
    pathname.startsWith("/prints/") ||
    // Sign-in, the collector's account (Collector v1 S6), collection (S7)
    // and watchlist (S8) share the homepage's chrome: same compact mark,
    // header and bottom navigation.
    pathname === "/sign-in" || pathname === "/account" || pathname === "/collection" || pathname === "/watchlist" ||
    // The long-form info pages (design cleanup c).
    pathname === "/about" || pathname === "/methodology" || pathname === "/privacy" || pathname === "/terms";
}

/** An exact print belongs to Cards in both public navigation surfaces. */
export function publicSectionActive(pathname: string, href: string): boolean {
  if (href === "/cards") {
    return pathname === "/cards" || pathname.startsWith("/cards/") || pathname.startsWith("/prints/");
  }
  return pathname === href;
}
