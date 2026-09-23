"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { CommandPalette } from "./CommandPalette";
import { KeyboardShortcutsModal } from "./KeyboardShortcutsModal";
import { SidebarNav } from "./SidebarNav";
import { TopBar } from "./TopBar";
import { PublicBottomNav } from "./PublicBottomNav";
import { isPublicShellRoute } from "./publicNavigation";
import { AdminNavigation, AdminNavigationDrawer } from "@/components/admin/AdminNavigation";
import { useAdminSurface } from "@/components/admin/AdminSurfaceProvider";
import adminStyles from "@/components/admin/AdminShell.module.css";

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

/** Shared top bar, route-appropriate navigation and keyboard commands.
 * Admin pages have a grouped operational rail and native modal drawer.
 * Collector pages keep their existing header, drawer and public bottom nav.
 */
export function AppShell() {
  const pathname = usePathname();
  const router = useRouter();
  // Route-based, not role-based, on purpose: the rail belongs to the admin
  // *surface*, not to the person. An admin browsing /cards is a collector at
  // that moment and gets the same header-led chrome as everybody else.
  const isAdminRoute = pathname === "/admin" || (pathname?.startsWith("/admin/") ?? false);
  // The protected server layout is the authorization boundary. A delayed or
  // failed client session fetch must not strip chrome from authorized content.
  const adminSurface = useAdminSurface();
  const showAdminNavigation = isAdminRoute && adminSurface?.authorized === true;
  const [mobileNavigation, setMobileNavigation] = useState({ pathname, open: false });
  const mobileNavOpen = mobileNavigation.pathname === pathname && mobileNavigation.open;
  const setMobileNavOpen = (open: boolean) => setMobileNavigation({ pathname, open });
  // Reset during navigation, before rendering the new page's drawer.
  if (mobileNavigation.pathname !== pathname) setMobileNavigation({ pathname, open: false });
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const gotoPendingRef = useRef(false);
  const gotoTimerRef = useRef<number | undefined>(undefined);

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
        onToggleMobileNav={() => setMobileNavOpen(!mobileNavOpen)}
        onOpenPalette={() => setPaletteOpen(true)}
        onOpenShortcuts={() => setShortcutsOpen(true)}
        mobileNavOpen={mobileNavOpen}
      />

      {isPublicShellRoute(pathname ?? "") && <PublicBottomNav />}

      {/* Fixed admin rail; body clearance follows data-app-rail in globals.css. */}
      {showAdminNavigation && (
        <aside
          data-app-rail=""
          className={adminStyles.rail}
        >
          <AdminNavigation />
        </aside>
      )}

      {/* Admin drawer through tablet widths; collector drawer below `lg`. */}
      {mobileNavOpen && showAdminNavigation && <AdminNavigationDrawer onClose={() => setMobileNavOpen(false)} />}
      {mobileNavOpen && !isAdminRoute && (
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
