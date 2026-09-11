"use client";

import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { fetchSavedViews, type SavedView } from "@/lib/api";
import { COMMAND_REGISTRY, searchCommands, type Command } from "@/lib/commandRegistry";
import {
  MIN_QUERY_LENGTH,
  PUBLIC_CARD_SEARCH_LIMIT,
  searchPublicCardFamilies,
  type PaletteCardResult,
} from "@/lib/publicCardSearch";
import { getRecentWorkflows, recordRecentWorkflow, type RecentWorkflowEntry } from "@/lib/recentWorkflows";

import { CardImageFrame } from "./CardImageFrame";

import { Badge } from "./Badge";
import { ConfirmActionModal } from "./ConfirmActionModal";

type PaletteItem =
  | { kind: "command"; key: string; command: Command }
  | { kind: "saved_view"; key: string; view: SavedView }
  | { kind: "recent"; key: string; entry: RecentWorkflowEntry }
  | { kind: "card"; key: string; result: PaletteCardResult };

/** Card search has three outcomes a visitor must be able to tell apart: a
 * result set (possibly empty), a request still in flight, and a failed
 * request. Collapsing the last two into "No matches" is what made the public
 * palette claim Kaido did not exist. */
type CardSearchStatus = "idle" | "loading" | "ready" | "error";

/** Global Cmd/Ctrl+K command palette (design brief - "Command palette +
 * workflow shortcuts"). Mounted once in AppShell so every page gets it with
 * zero per-page wiring. Navigation-only for admin/dangerous commands - see
 * docs/interface_design_system.md "Command palette" for why a global
 * component can't safely trigger a specific page's dry-run handlers. */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const { data: session, status } = useSession();
  const isAuthenticated = status === "authenticated";
  const isAdmin = session?.user?.role === "admin";
  const [query, setQuery] = useState("");
  const [savedViews, setSavedViews] = useState<SavedView[]>([]);
  const [recent, setRecent] = useState<RecentWorkflowEntry[]>([]);
  const [cardResults, setCardResults] = useState<PaletteCardResult[]>([]);
  const [cardStatus, setCardStatus] = useState<CardSearchStatus>("idle");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [pendingDangerous, setPendingDangerous] = useState<Command | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    // Opening the externally controlled dialog resets its ephemeral input.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setQuery("");
    setSelectedIndex(0);
    setRecent(getRecentWorkflows());
    if (!isAuthenticated) {
      // Saved views are per-collector. Asking for them while signed out only
      // buys a 401 the palette would have to swallow anyway.
      setSavedViews([]);
    } else {
      fetchSavedViews({ limit: 100 })
        .then((res) => setSavedViews(res.items))
        .catch(() => setSavedViews([]));
    }
    const focusTimer = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => window.clearTimeout(focusTimer);
  }, [open, isAuthenticated]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const trimmed = query.trim();
    if (trimmed.length < MIN_QUERY_LENGTH) {
      // Clear suggestions immediately when the query becomes invalid.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCardResults([]);
      setCardStatus("idle");
      return;
    }
    setCardResults([]);
    setCardStatus("loading");
    const debounceTimer = window.setTimeout(() => {
      // ONE card search for everybody, signed in or not: the public canonical
      // catalogue (GET /prints), collapsed to one row per canonical card.
      //
      // The authenticated branch used to call /api/search with types:["cards"],
      // which searches the legacy `cards` table - 25 rows against 2,710
      // canonical cards, 10 of them naming a different character than their own
      // card_code resolves to, and 4 codes present twice with conflicting
      // names. That made a signed-in collector's results both narrower and
      // wrong: searching "Nami" returned a row titled Nami whose page correctly
      // reads "Monkey.D.Luffy". Card lookup is catalogue data, identical for
      // every visitor, so it no longer depends on who is asking.
      //
      // WHAT A SIGNED-IN COLLECTOR LOSES, STATED PLAINLY. /api/search ranked
      // its card results with an ownership bonus and attached
      // metadata.owned_quantity, so a card you own could sort above one you do
      // not. That ranking is NOT reproduced here: it is derived from private
      // collection data, and re-deriving it in the browser would mean fetching
      // the caller's collection just to order a suggestion list. Ownership-aware
      // ranking is deferred, not silently reimplemented - what replaces it is
      // catalogue correctness, which the old path did not have.
      //
      // /api/search itself is untouched and still authenticated - it remains
      // the signed-in command centre over collection, wishlist, grading, notes
      // and activity, which the /search page still uses. Only this palette's
      // CARD SUGGESTIONS changed; saved views and command visibility below
      // still depend on the session exactly as before.
      const search = searchPublicCardFamilies(trimmed, PUBLIC_CARD_SEARCH_LIMIT);

      search
        .then((results) => {
          if (cancelled) return;
          setCardResults(results);
          setCardStatus("ready");
        })
        .catch(() => {
          if (cancelled) return;
          // Never fall through to "No matches" - that would claim a search
          // succeeded and found nothing.
          setCardResults([]);
          setCardStatus("error");
        });
    }, 250);
    return () => {
      window.clearTimeout(debounceTimer);
      cancelled = true;
    };
  }, [open, query]);

  const filteredCommands = useMemo(
    () => searchCommands(query, { isAuthenticated, isAdmin }),
    [query, isAuthenticated, isAdmin],
  );

  const filteredSavedViews = useMemo(() => {
    if (!isAuthenticated) return [];
    const q = query.trim().toLowerCase();
    if (!q) return savedViews.filter((v) => v.pinned || v.is_default).slice(0, 6);
    return savedViews.filter((v) => v.name.toLowerCase().includes(q)).slice(0, 6);
  }, [savedViews, query, isAuthenticated]);

  const items: PaletteItem[] = useMemo(() => {
    const out: PaletteItem[] = cardResults.map((result) => ({ kind: "card", key: result.key, result }));
    if (!query.trim()) {
      for (const entry of recent.filter((entry) => {
        if (entry.route_path.startsWith("/admin") || entry.item_type === "admin_action") return isAuthenticated && isAdmin;
        if (isAuthenticated) return true;
        if (entry.item_type === "card") return /^\/(cards\/(code\/[^/?#]+|\d+)|prints\/\d+)$/.test(entry.route_path);
        return entry.item_type === "route" && COMMAND_REGISTRY.some((command) => command.scope === "public" && command.route_path === entry.route_path && command.label === entry.label);
      })) {
        out.push({ kind: "recent", key: `recent-${entry.item_type}-${entry.route_path}-${entry.label}`, entry });
      }
    }
    for (const view of filteredSavedViews) {
      out.push({ kind: "saved_view", key: `saved-${view.id}`, view });
    }
    for (const command of filteredCommands) {
      out.push({ kind: "command", key: `command-${command.id}`, command });
    }
    return out;
  }, [query, recent, filteredSavedViews, filteredCommands, cardResults, isAuthenticated, isAdmin]);

  useEffect(() => {
    // A new result list starts keyboard selection at its first row.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSelectedIndex(0);
  }, [items.length, query]);

  function activate(item: PaletteItem) {
    if (item.kind === "command") {
      const command = item.command;
      recordRecentWorkflow({
        item_type: "route",
        label: command.label,
        route_path: command.route_path,
      });
      if (command.dangerous) {
        setPendingDangerous(command);
        return;
      }
      onClose();
      router.push(command.route_path);
      return;
    }
    if (item.kind === "saved_view") {
      recordRecentWorkflow({
        item_type: "saved_view",
        label: item.view.name,
        route_path: item.view.route_path,
        payload_json: { saved_view_id: item.view.id },
      });
      onClose();
      router.push(item.view.route_path);
      return;
    }
    if (item.kind === "recent") {
      recordRecentWorkflow({
        item_type: item.entry.item_type,
        label: item.entry.label,
        route_path: item.entry.route_path,
        payload_json: item.entry.payload_json,
      });
      onClose();
      router.push(item.entry.route_path);
      return;
    }
    if (item.kind === "card") {
      recordRecentWorkflow({
        item_type: "card",
        label: item.result.title,
        route_path: item.result.url,
      });
      onClose();
      router.push(item.result.url);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => (items.length === 0 ? 0 : (i + 1) % items.length));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => (items.length === 0 ? 0 : (i - 1 + items.length) % items.length));
      return;
    }
    if (e.key === "Enter" && e.target === inputRef.current) {
      e.preventDefault();
      const item = items[selectedIndex];
      if (item) activate(item);
    }
  }

  useEffect(() => {
    if (open) document.querySelector("[data-palette-active='true']")?.scrollIntoView?.({ block: "nearest" });
  }, [open, selectedIndex]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-2 pt-[4dvh] sm:p-4 sm:pt-[10vh]"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-label="Search cards"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
        className="flex max-h-[85dvh] flex-col sm:max-h-[70vh] w-full max-w-xl overflow-hidden rounded-modal border border-border-default bg-bg-elevated shadow-xl"
      >
        <div className="border-b border-border-default p-3">
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search by name or code"
            placeholder="Search by name or code"
            className="min-h-11 w-full rounded-control border border-border-default bg-bg-surface px-3 py-2 text-base sm:text-sm text-text-primary placeholder:text-text-faint"
          />
        </div>

        <div className="min-h-0 overflow-y-auto overscroll-contain p-2">
          {items.length === 0 && (
            <div className="px-3 py-6 text-center text-xs text-text-muted">
              {cardStatus === "loading"
                ? "Searching…"
                : cardStatus === "error"
                  ? "Search unavailable"
                  : "No matches"}
            </div>
          )}

          {renderGroup("Cards", items, "card", selectedIndex, activate)}
          {renderGroup("Recent", items, "recent", selectedIndex, activate)}
          {renderGroup("Saved Views", items, "saved_view", selectedIndex, activate)}
          {renderGroup("Pages", items, "command", selectedIndex, activate)}
        </div>

        <div className="shrink-0 border-t border-border-default p-2">
          {query.trim().length >= MIN_QUERY_LENGTH && (
            <a href={`/cards?q=${encodeURIComponent(query.trim())}`} onClick={onClose}
              className="flex min-h-11 items-center justify-center rounded-control bg-bg-surface text-sm font-semibold text-text-primary">
              View all results
            </a>
          )}
          <div className="flex items-center justify-between gap-2 text-xs text-text-muted">
            <span className="hidden sm:inline">↑↓ navigate · Enter select · Esc close</span>
            <button type="button" onClick={onClose} className="min-h-11 px-3 sm:min-h-8">Close search</button>
          </div>
        </div>
      </div>

      {pendingDangerous && (
        <ConfirmActionModal
          open
          title={pendingDangerous.label}
          description={pendingDangerous.description}
          confirmPhrase={pendingDangerous.confirm_phrase}
          confirmLabel="Continue"
          onConfirm={() => {
            const command = pendingDangerous;
            setPendingDangerous(null);
            onClose();
            router.push(command.route_path);
          }}
          onCancel={() => setPendingDangerous(null)}
        />
      )}
    </div>
  );
}

function renderGroup(
  title: string,
  items: PaletteItem[],
  kind: PaletteItem["kind"],
  selectedIndex: number,
  onActivate: (item: PaletteItem) => void,
) {
  const groupItems = items
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item.kind === kind);
  if (groupItems.length === 0) return null;

  return (
    <div key={kind} className="mb-2">
      <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-text-faint">
        {title}
      </div>
      {groupItems.map(({ item, index }) => (
        <PaletteRow
          key={item.key}
          item={item}
          active={index === selectedIndex}
          onClick={() => onActivate(item)}
        />
      ))}
    </div>
  );
}

function PaletteRow({
  item,
  active,
  onClick,
}: {
  item: PaletteItem;
  active: boolean;
  onClick: () => void;
}) {
  const rowClass = `flex min-h-11 w-full items-center justify-between gap-3 rounded-control px-3 py-2 text-left text-sm transition-colors ${
    active ? "bg-bg-surface text-text-primary" : "text-text-secondary hover:bg-bg-surface/60"
  }`;

  if (item.kind === "command") {
    const { command } = item;
    return (
      <button type="button" data-palette-active={active} onClick={onClick} className={rowClass}>
        <span className="min-w-0">
          <span className="block truncate">{command.label}</span>
          <span className="block truncate text-[11px] text-text-muted">{command.description}</span>
        </span>
        {command.badge === "admin" && (
          <Badge label="ADMIN" className="shrink-0 bg-accent-gold/10 text-accent-gold ring-1 ring-inset ring-accent-gold/30" />
        )}
        {command.dangerous && (
          <Badge label="CONFIRM" className="shrink-0 bg-signal-red/10 text-signal-red ring-1 ring-inset ring-signal-red/30" />
        )}
      </button>
    );
  }

  if (item.kind === "saved_view") {
    return (
      <button type="button" data-palette-active={active} onClick={onClick} className={rowClass}>
        <span className="min-w-0">
          <span className="block truncate">{item.view.name}</span>
          <span className="block truncate text-[11px] text-text-muted">{item.view.route_path}</span>
        </span>
        <Badge label="VIEW" className="shrink-0" />
      </button>
    );
  }

  if (item.kind === "recent") {
    return (
      <button type="button" data-palette-active={active} onClick={onClick} className={rowClass}>
        <span className="min-w-0">
          <span className="block truncate">{item.entry.label}</span>
          <span className="block truncate text-[11px] text-text-muted">{item.entry.route_path}</span>
        </span>
        <Badge label="RECENT" className="shrink-0" />
      </button>
    );
  }

  return (
    <button type="button" data-palette-active={active} onClick={onClick} className={rowClass}>
      {item.result.preview && (
        <span className="w-14 shrink-0">
          <CardImageFrame imageUrl={item.result.preview.imageUrl} cardCode={item.result.preview.cardCode}
            alt={`${item.result.preview.cardCode} printing preview — ${item.result.preview.context}`} size="full" padded />
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="block truncate">{item.result.title}</span>
        <span className="block truncate text-[11px] text-text-muted">{item.result.subtitle}</span>
        {item.result.preview && <span className="block text-[11px] text-text-muted">Preview: {item.result.preview.context}</span>}
      </span>

    </button>
  );
}
