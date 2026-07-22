"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { signIn, signOut, useSession } from "next-auth/react";

export function TopBar({
  onToggleMobileNav,
}: {
  onToggleMobileNav?: () => void;
}) {
  const router = useRouter();

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        router.push("/search");
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [router]);

  return (
    <header className="sticky top-0 z-30 h-12 border-b border-border-default bg-bg-page/95 backdrop-blur">
      <div className="flex h-full items-center gap-3 px-3 md:px-4">
        <button
          type="button"
          onClick={onToggleMobileNav}
          aria-label="Toggle navigation"
          className="rounded border border-border-default px-2 py-1 text-xs text-text-secondary hover:text-text-primary md:hidden"
        >
          ☰
        </button>

        <Link
          href="/dashboard"
          className="shrink-0 text-sm font-semibold tracking-tight text-text-primary"
        >
          <span className="text-accent-gold">OPTCG</span> Vault
        </Link>

        <Link
          href="/search"
          title="Search (Ctrl/Cmd+K)"
          className="hidden flex-1 items-center justify-between rounded-control border border-border-default bg-bg-surface px-3 py-1.5 text-xs text-text-muted hover:border-border-default hover:text-text-secondary sm:flex sm:max-w-sm"
        >
          <span>Search cards, collection, signals…</span>
          <span className="mono rounded border border-border-default px-1 py-0.5 text-[10px] text-text-faint">
            ⌘K
          </span>
        </Link>

        <div className="flex-1" />

        <AuthControl />
      </div>
    </header>
  );
}

function AuthControl() {
  const { data: session, status } = useSession();

  if (status === "loading") {
    return <span className="text-xs text-text-faint">…</span>;
  }

  if (!session) {
    return (
      <button
        type="button"
        onClick={() => signIn("google", { callbackUrl: "/dashboard" })}
        className="rounded-control bg-accent-gold px-2.5 py-1 text-xs font-medium text-black/80 hover:bg-accent-gold-hover"
      >
        Sign in with Google
      </button>
    );
  }

  return (
    <div className="flex items-center gap-2 text-xs text-text-secondary">
      <span className="max-w-[10rem] truncate" title={session.user?.email ?? undefined}>
        {session.user?.name || session.user?.email}
      </span>
      <button
        type="button"
        onClick={() => signOut({ callbackUrl: "/dashboard" })}
        className="rounded-control border border-border-default px-2 py-1 font-medium text-text-secondary hover:text-text-primary"
      >
        Sign out
      </button>
    </div>
  );
}
