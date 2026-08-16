"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { CommandPalette } from "./CommandPalette";
import { KeyboardShortcutsModal } from "./KeyboardShortcutsModal";
import { SidebarNav } from "./SidebarNav";
import { TopBar } from "./TopBar";

// "g then <key>" goto-shortcut targets (design brief - "Workflow
// shortcuts"). Kept in sync with KeyboardShortcutsModal's reference list and
// with SidebarNav/commandRegistry's approved route set - shortcuts to
// Dashboard, Buy/Sell Decisions, Portfolio Risk and Admin Catalog Ops were
// removed here for the same reason those were removed from navigation and
// the command palette (collector-blueprint.pdf Phase 3/4); their routes
// still exist, just no longer surfaced from this shell.
const GOTO_ROUTES: Record<string, string> = {
  c: "/collection",
  v: "/collection/vault",
  w: "/wishlist",
};

const GOTO_RESET_MS = 600;

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

/** Drop-in replacement for the old flat AppHeader nav bar. Renders a sticky
 * topbar (full width, in document flow, so growing it to `--header-h` pushes
 * every page's content down without any page needing new top padding), and -
 * on the admin surface only - a fixed-position navigation rail below it.
 *
 * The rail used to be permanent on every page at `lg`+. It isn't any more:
 * a persistent left nav made the *public* product read as an internal
 * dashboard, so collector-facing pages now navigate from the header
 * (TopBar's PublicNav) and get the full viewport width. The rail survives
 * for /admin, where a dense operational route list genuinely needs one, and
 * SidebarNav itself is untouched and still shared by both the rail and the
 * mobile drawer.
 *
 * The rail is `position: fixed`, so it doesn't require any page to
 * restructure its wrapper - the matching body padding is applied by
 * globals.css off the `data-app-rail` attribute, only when a rail exists.
 *
 * Also owns the global command palette / keyboard-shortcuts modal mount
 * point and keyboard listener, so every page gets Cmd/Ctrl+K, "?", "/", and
 * the "g then <key>" goto-sequences with zero per-page wiring. */
export function AppShell() {
  const pathname = usePathname();
  const router = useRouter();
  // Route-based, not role-based, on purpose: the rail belongs to the admin
  // *surface*, not to the person. An admin browsing /cards is a collector at
  // that moment and gets the same header-led chrome as everybody else.
  const isAdminRoute = pathname === "/admin" || (pathname?.startsWith("/admin/") ?? false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const gotoPendingRef = useRef(false);
  const gotoTimerRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname]);

  useEffect(() => {
    function resetGoto() {
      gotoPendingRef.current = false;
      window.clearTimeout(gotoTimerRef.current);
    }

    function handleKeyDown(e: KeyboardEvent) {
      const anyModalOpen = paletteOpen || shortcutsOpen;

      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        resetGoto();
        setPaletteOpen((v) => !v);
        return;
      }

      if (e.key === "Escape") {
        if (paletteOpen) setPaletteOpen(false);
        if (shortcutsOpen) setShortcutsOpen(false);
        return;
      }

      if (anyModalOpen || isTypingTarget(e.target)) {
        return;
      }

      if (e.key === "/") {
        e.preventDefault();
        setPaletteOpen(true);
        return;
      }

      if (e.key === "?") {
        e.preventDefault();
        setShortcutsOpen(true);
        return;
      }

      if (gotoPendingRef.current) {
        resetGoto();
        const route = GOTO_ROUTES[e.key.toLowerCase()];
        if (route) {
          e.preventDefault();
          router.push(route);
        }
        return;
      }

      if (e.key.toLowerCase() === "g") {
        gotoPendingRef.current = true;
        gotoTimerRef.current = window.setTimeout(resetGoto, GOTO_RESET_MS);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.clearTimeout(gotoTimerRef.current);
    };
  }, [paletteOpen, shortcutsOpen, router]);

  return (
    <>
      <TopBar
        onToggleMobileNav={() => setMobileNavOpen((v) => !v)}
        onOpenPalette={() => setPaletteOpen(true)}
        onOpenShortcuts={() => setShortcutsOpen(true)}
      />

      {/* Admin-only navigation rail - fixed, clears the topbar via
          --header-h (the one place that height is defined - globals.css),
          own scroll region. Still only at `lg` (1024px)+: tablet keeps the
          drawer so a 768px-wide screen isn't left with a squeezed <600px
          content column next to a permanently-open 224px rail.

          data-app-rail is what globals.css keys the body padding and the
          header's negative margin off, so the attribute and the element have
          to stay together. */}
      {isAdminRoute && (
        <aside
          data-app-rail=""
          className="fixed left-0 top-[var(--header-h)] z-20 hidden h-[calc(100vh-var(--header-h))] w-56 border-r border-border-default bg-bg-surface lg:block"
        >
          <SidebarNav className="h-full" />
        </aside>
      )}

      {/* Mobile/tablet nav - toggled overlay, covers everything below `lg` */}
      {mobileNavOpen && (
        <div className="fixed inset-0 top-[var(--header-h)] z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => setMobileNavOpen(false)}
            className="absolute inset-0 bg-black/60"
          />
          <div className="relative h-full w-64 max-w-[80vw] border-r border-border-default bg-bg-surface shadow-xl">
            <SidebarNav className="h-full" />
          </div>
        </div>
      )}

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <KeyboardShortcutsModal open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
    </>
  );
}

export { SidebarNav } from "./SidebarNav";
export { TopBar } from "./TopBar";
