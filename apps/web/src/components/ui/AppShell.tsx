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
 * topbar (full width, in document flow - unchanged height/position from the
 * old AppHeader, so no page needs new top padding) plus a fixed-position
 * sidebar below it. The sidebar is `position: fixed`, not part of layout
 * flow, so it doesn't require any page to restructure its own wrapper - the
 * one bit of matching padding it needs (`md:pl-56`) lives once on
 * <body> in app/layout.tsx rather than on every page.
 *
 * Also owns the global command palette / keyboard-shortcuts modal mount
 * point and keyboard listener, so every page gets Cmd/Ctrl+K, "?", "/", and
 * the "g then <key>" goto-sequences with zero per-page wiring. */
export function AppShell() {
  const pathname = usePathname();
  const router = useRouter();
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

      {/* Desktop sidebar - fixed, clears the topbar via top-12, own scroll
          region. Only shown at `lg` (1024px)+ - tablet (down to 768px) keeps
          the drawer below so a 768px-wide screen isn't left with a squeezed
          <600px content column next to a permanently-open 224px rail. */}
      <aside className="fixed left-0 top-12 z-20 hidden h-[calc(100vh-3rem)] w-56 border-r border-border-default bg-bg-surface lg:block">
        <SidebarNav className="h-full" />
      </aside>

      {/* Mobile/tablet nav - toggled overlay, covers everything below `lg` */}
      {mobileNavOpen && (
        <div className="fixed inset-0 top-12 z-40 lg:hidden">
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
