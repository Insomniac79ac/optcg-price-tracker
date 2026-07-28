"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut, useSession } from "next-auth/react";

import { AtlasCompactMark } from "@/components/brand/AtlasLogo";

export function TopBar({
  onToggleMobileNav,
  onOpenPalette,
  onOpenShortcuts,
}: {
  onToggleMobileNav?: () => void;
  onOpenPalette?: () => void;
  onOpenShortcuts?: () => void;
}) {
  return (
    <header className="sticky top-0 z-30 h-12 border-b border-border-default bg-bg-page/95 backdrop-blur">
      <div className="flex h-full items-center gap-2 px-3 sm:gap-3 md:px-4">
        <button
          type="button"
          onClick={onToggleMobileNav}
          aria-label="Toggle navigation"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded border border-border-default text-sm text-text-secondary hover:text-text-primary lg:hidden"
        >
          ☰
        </button>

        {/* AtlasCompactMark carries the full "CardPirate Atlas" name for
            assistive tech even though only the short "Atlas" wordmark shows
            here - see components/brand/AtlasLogo.tsx. */}
        <Link href="/" className="shrink-0">
          <AtlasCompactMark />
        </Link>

        {/* Full search bar from sm+ */}
        <button
          type="button"
          onClick={onOpenPalette}
          title="Search (Ctrl/Cmd+K)"
          className="hidden flex-1 items-center justify-between rounded-control border border-border-default bg-bg-surface px-3 py-1.5 text-xs text-text-muted hover:border-border-default hover:text-text-secondary sm:flex sm:max-w-sm"
        >
          <span>Search cards, collection, wishlist…</span>
          <span className="mono rounded border border-border-default px-1 py-0.5 text-[10px] text-text-faint">
            ⌘K
          </span>
        </button>

        {/* Icon-only command palette trigger below sm, where the full search
            bar has no room - command palette must stay reachable on mobile. */}
        <button
          type="button"
          onClick={onOpenPalette}
          title="Search (Ctrl/Cmd+K)"
          aria-label="Open command palette"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control border border-border-default text-text-muted hover:text-text-secondary sm:hidden"
        >
          ⌕
        </button>

        <div className="flex-1" />

        <button
          type="button"
          onClick={onOpenShortcuts}
          title="Keyboard shortcuts (?)"
          aria-label="Keyboard shortcuts"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control border border-border-default text-xs text-text-faint hover:text-text-secondary"
        >
          ?
        </button>

        <AuthControl />
      </div>
    </header>
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
        className="rounded-control bg-accent-gold px-2.5 py-1 text-xs font-medium text-black/80 hover:bg-accent-gold-hover"
      >
        <span className="sm:hidden">Sign in</span>
        <span className="hidden sm:inline">Sign in</span>
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
        className="rounded-control border border-border-default px-2 py-1 font-medium text-text-secondary hover:text-text-primary"
      >
        Sign out
      </button>
    </div>
  );
}
