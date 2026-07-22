"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { SidebarNav } from "./SidebarNav";
import { TopBar } from "./TopBar";

/** Drop-in replacement for the old flat AppHeader nav bar. Renders a sticky
 * topbar (full width, in document flow - unchanged height/position from the
 * old AppHeader, so no page needs new top padding) plus a fixed-position
 * sidebar below it. The sidebar is `position: fixed`, not part of layout
 * flow, so it doesn't require any page to restructure its own wrapper - the
 * one bit of matching padding it needs (`md:pl-56`) lives once on
 * <body> in app/layout.tsx rather than on every page. */
export function AppShell() {
  const pathname = usePathname();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname]);

  return (
    <>
      <TopBar onToggleMobileNav={() => setMobileNavOpen((v) => !v)} />

      {/* Desktop sidebar - fixed, clears the topbar via top-12, own scroll region */}
      <aside className="fixed left-0 top-12 z-20 hidden h-[calc(100vh-3rem)] w-56 border-r border-border-default bg-bg-surface md:block">
        <SidebarNav className="h-full" />
      </aside>

      {/* Mobile nav - toggled overlay, since the fixed sidebar is hidden below md */}
      {mobileNavOpen && (
        <div className="fixed inset-0 top-12 z-40 md:hidden">
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
    </>
  );
}

export { SidebarNav } from "./SidebarNav";
export { TopBar } from "./TopBar";
