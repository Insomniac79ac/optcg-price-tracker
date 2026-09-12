"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut, useSession } from "next-auth/react";

import { AtlasLogoImage, AtlasMarkImage } from "@/components/brand/AtlasBrandAssets";
import styles from "./PublicShell.module.css";
import { isPublicShellRoute, publicSectionActive } from "./publicNavigation";
import { brand } from "@/lib/brand";
import { PUBLIC_NAV_ITEMS } from "./SidebarNav";

/** Shared header mechanics for public browsing and private tools.
 * PublicShell supplies the canonical compact compass, blue-black foundation,
 * underline navigation and >=44px targets. Private routes retain their existing
 * logo assets, token values and control sizing.
 *
 * Public sections share one destination list with the mobile bottom bar. Below
 * md the desktop links are hidden; the drawer also keeps signed-in collector
 * tools reachable. The admin rail remains owned by AppShell.
 */
// Private tools retain compact desktop icons; PublicShell increases their
// effective target to 44px on public routes without enlarging the glyphs.
const ICON_BUTTON_CLASS =
  "flex h-11 w-11 shrink-0 items-center justify-center border border-border-default text-text-secondary transition-colors hover:text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 md:h-9 md:w-9";

function SearchIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      aria-hidden="true"
      className="h-[18px] w-[18px]"
    >
      <circle cx="8.75" cy="8.75" r="5.25" />
      <path d="M12.6 12.6 16.5 16.5" />
    </svg>
  );
}

export function TopBar({
  onToggleMobileNav,
  onOpenPalette,
  onOpenShortcuts,
}: {
  onToggleMobileNav?: () => void;
  onOpenPalette?: () => void;
  onOpenShortcuts?: () => void;
}) {
  const publicShell = isPublicShellRoute(usePathname() ?? "");
  const { status } = useSession();
  const authenticated = status === "authenticated";

  return (
    // No negative margin any more: <body> carries no sidebar padding on the
    // public surface, so the header is full-bleed by default. On /admin,
    // where a rail does exist, globals.css re-applies both the body padding
    // and the matching negative margin here off `data-app-header`.
    <header
      data-app-header=""
      data-public-shell={publicShell ? "" : undefined}
      className={`sticky top-0 z-30 h-[var(--header-h)] border-b border-border-default bg-bg-page/95 backdrop-blur ${publicShell ? styles.header : ""}`}
    >
      <div className="flex h-full items-center gap-2.5 px-3 sm:gap-3 md:gap-5 md:px-6">
        <button
          type="button"
          onClick={onToggleMobileNav}
          aria-label="Toggle navigation"
          className={`${ICON_BUTTON_CLASS} rounded text-base ${
            authenticated ? "" : "md:hidden"
          }`}
        >
          ☰
        </button>

        {/* Single explicit aria-label on the link itself - both brand images
            are decorative (alt="") so the link's accessible name is exactly
            this one string, never a concatenation with the artwork's alt.
            `pr-1` on mobile keeps the 44px mark from sitting flush against
            the utilities when the bar is at its tightest. */}
        <Link
          href="/"
          className="flex shrink-0 items-center pr-1 md:pr-0"
          aria-label={`${brand.productName} — Home`}
        >
          {publicShell ? <PublicLogo /> : <>
            <AtlasMarkImage className="h-11 w-11 md:hidden" />
            <AtlasLogoImage className="hidden h-16 w-auto md:block" />
          </>}
        </Link>

        <PublicNav />

        <div className="flex-1" />

        {/* Full search bar only from `lg`. Between `md` and `lg` the logo
            lockup plus three nav links plus the auth control already fill the
            bar - keeping a 320px search box there overflowed the viewport at
            768px. */}
        <button
          type="button"
          onClick={onOpenPalette}
          title="Search (Ctrl/Cmd+K)"
          className="hidden items-center justify-between gap-6 rounded-control border border-border-default bg-bg-surface px-3 py-2 text-xs text-text-muted transition-colors hover:border-accent-teal/60 hover:text-text-secondary lg:flex lg:w-72"
        >
          <span>Search cards…</span>
          <span className="mono rounded border border-border-default px-1 py-0.5 text-[10px] text-text-faint">
            ⌘K
          </span>
        </button>

        {/* Icon-only command palette trigger below `lg`, where the full
            search bar has no room - the palette must stay reachable on every
            viewport. A drawn glyph rather than the "⌕" character, which most
            of the shipped font stack renders a few pixels tall and which read
            as an unlabelled speck beside the 44px brand mark at 390px. */}
        <button
          type="button"
          onClick={onOpenPalette}
          title="Search (Ctrl/Cmd+K)"
          aria-label="Search cards"
          className={`${ICON_BUTTON_CLASS} rounded-control lg:hidden`}
        >
          <SearchIcon />
        </button>

        {/* `lg`+ only. This opens a reference for keyboard shortcuts, so it
            is meaningless on the touch viewports where the header is also at
            its tightest - and dropping it there is what buys the remaining
            controls their full 44px targets at 390px. The "?" key still opens
            the same modal wherever a keyboard exists. */}
        <button
          type="button"
          onClick={onOpenShortcuts}
          title="Keyboard shortcuts (?)"
          aria-label="Keyboard shortcuts"
          className={`${ICON_BUTTON_CLASS} hidden rounded-control text-xs text-text-faint lg:flex`}
        >
          ?
        </button>

        <AuthControl />
      </div>
    </header>
  );
}

function PublicNav() {
  const pathname = usePathname() ?? "";

  return (
    <nav aria-label="Public sections" className="hidden items-center gap-1 md:flex">
      {PUBLIC_NAV_ITEMS.map((item) => {
        const active = isPublicShellRoute(pathname)
          ? publicSectionActive(pathname, item.href)
          : pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`rounded-control px-3 py-1.5 text-sm font-medium whitespace-nowrap transition-colors ${
              active
                ? "bg-accent-teal/12 text-accent-teal-hover"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

function AuthControl() {
  const { data: session, status } = useSession();
  // Deliberately pathname-only (no query string) - useSearchParams() would
  // require every page that renders <AppHeader /> (nearly all of them) to
  // add its own Suspense boundary to stay statically-optimizable, which is
  // out of scope for this task. The redirect flow that actually needs full
  // pathname+query preservation (proxy.ts -> /sign-in for a protected
  // route) already has it - see src/lib/proxyGuard.ts.
  const pathname = usePathname() ?? "/";
  const currentPath = pathname;

  if (status === "loading") {
    return <span className="text-xs text-text-faint">…</span>;
  }

  if (!session) {
    // Routes to /sign-in rather than calling next-auth's signIn() directly -
    // that page is the single place that checks whether Google OAuth is
    // actually configured (it isn't, in this staging build) before showing
    // a working sign-in action, so this button never promises an auth flow
    // that doesn't work yet. callbackUrl is validated there too (see
    // src/lib/callbackUrl.ts) before ever being used.
    const signInHref = `/sign-in?callbackUrl=${encodeURIComponent(currentPath)}`;
    return (
      <Link
        href={signInHref}
        // Sized to the same 44px touch target as the icon buttons beside it
        // up to `md`, then back to the compact desktop pill.
        className="flex h-11 shrink-0 items-center rounded-control bg-accent-gold px-3.5 text-xs font-semibold text-black/80 transition-colors hover:bg-accent-gold-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-gold/60 md:h-8 md:px-3"
      >
        Sign in
      </Link>
    );
  }

  return (
    <div className="flex items-center gap-2 text-xs text-text-secondary">
      <span
        className="hidden max-w-[10rem] truncate sm:inline"
        title={session.user?.email ?? undefined}
      >
        {session.user?.name || session.user?.email}
      </span>
      <button
        type="button"
        onClick={() => signOut({ callbackUrl: "/" })}
        title={session.user?.name || session.user?.email || undefined}
        className="flex h-11 shrink-0 items-center rounded-control border border-border-default px-2.5 font-medium text-text-secondary transition-colors hover:text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 md:h-8 md:px-2"
      >
        Sign out
      </button>
    </div>
  );
}

/** Canonical public compass and wordmark, decorative inside the labelled Home link.
 * Private tools retain their existing brand assets and styling. */
function PublicLogo() {
  return <span className={styles.logo} aria-hidden="true">
    <svg viewBox="0 0 36 36" fill="none" focusable="false">
      <circle cx="18" cy="18" r="16" stroke="#33565b" />
      <circle cx="18" cy="18" r="12.5" stroke="#6fb5b0" />
      <path d="M18 5 20.5 15.5 31 18 20.5 20.5 18 31 15.5 20.5 5 18 15.5 15.5Z" stroke="#6fb5b0" fill="#12262a" />
      <path d="M18 5 20.5 15.5 18 18 15.5 15.5Z" fill="#d6a84f" />
      <circle cx="18" cy="18" r="1.5" fill="#eef2f2" />
    </svg>
    <span className={styles.wordmark}>CARD<span>PIRATE</span><small>ATLAS</small></span>
  </span>;
}
