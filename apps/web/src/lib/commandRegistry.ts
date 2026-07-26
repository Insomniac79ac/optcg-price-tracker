// Static command list for the global Cmd/Ctrl+K palette. Every `route_path`
// here has been confirmed against the actual App Router tree / SidebarNav.
//
// Visibility is enforced by `visibleCommands` below, called from
// CommandPalette.tsx with the caller's actual session state - `scope` and
// `requires_admin` are read there, not just advisory metadata (see
// collector-blueprint.pdf Part 9's audit finding that this used to be
// advisory-only). This mirrors SidebarNav.tsx's own public/collector split
// so the two surfaces never drift apart:
//   - scope "public": always visible.
//   - scope "collector": visible only once a session exists.
//   - requires_admin: never visible today - no admin session concept exists
//     yet (see the dedicated admin-login task). Left enforced-but-always-
//     false rather than deleted so that task only has to change the check,
//     not rebuild it.
//
// Trading/internal commands (market opportunities/signals/signal-events,
// the old Analytics group, Dashboard) have been removed from this registry
// entirely, matching their removal from SidebarNav - their routes still
// exist, they're just not linked from either navigation surface pending a
// later product decision (collector-blueprint.pdf Phase 3).

export type CommandGroup = "Navigate" | "Cards" | "Collection" | "Wishlist" | "Grading" | "Market" | "Admin";

export type CommandScope = "public" | "collector" | "admin";

export interface Command {
  id: string;
  label: string;
  description: string;
  group: CommandGroup;
  route_path: string;
  keywords: string[];
  scope: CommandScope;
  icon_key: string;
  badge?: "admin";
  requires_admin?: boolean;
  dangerous?: boolean;
  /** Required typed phrase, only meaningful when `dangerous` is true. */
  confirm_phrase?: string;
}

function cmd(partial: Omit<Command, "scope" | "icon_key"> & { scope: CommandScope; icon_key?: string }): Command {
  return { icon_key: partial.group.toLowerCase(), ...partial };
}

export const COMMAND_REGISTRY: Command[] = [
  // --- Public ------------------------------------------------------------
  cmd({
    id: "nav-discover",
    label: "Discover",
    description: "Public landing page",
    group: "Navigate",
    route_path: "/",
    keywords: ["home", "discover"],
    scope: "public",
  }),
  cmd({
    id: "nav-search",
    label: "Cards",
    description: "Browse and search the card catalogue",
    group: "Cards",
    route_path: "/search",
    keywords: ["find", "lookup", "browse", "catalogue"],
    scope: "public",
  }),
  cmd({
    id: "nav-market-index",
    label: "Market Index",
    description: "Market Index movers across Yuyu-Tei and SNKRDUNK",
    group: "Market",
    route_path: "/market/movers",
    keywords: ["market", "index", "price"],
    scope: "public",
  }),

  // --- Collector -----------------------------------------------------------
  cmd({
    id: "nav-collection-table",
    label: "My Collection (Table)",
    description: "Owned cards in table view",
    group: "Collection",
    route_path: "/collection",
    keywords: ["owned", "table"],
    scope: "collector",
  }),
  cmd({
    id: "nav-collection-vault",
    label: "My Collection (Vault)",
    description: "Owned cards in card-grid vault view",
    group: "Collection",
    route_path: "/collection/vault",
    keywords: ["owned", "grid", "vault"],
    scope: "collector",
  }),
  cmd({
    id: "nav-wishlist",
    label: "Wishlist",
    description: "Cards you want to acquire",
    group: "Wishlist",
    route_path: "/wishlist",
    keywords: ["want", "target"],
    scope: "collector",
  }),
  cmd({
    id: "nav-grading",
    label: "Grading",
    description: "Grading submissions and ROI tracking",
    group: "Grading",
    route_path: "/grading",
    keywords: ["psa", "bgs", "submission"],
    scope: "collector",
  }),
  cmd({
    id: "nav-activity",
    label: "Activity",
    description: "Recent collection and wishlist activity",
    group: "Navigate",
    route_path: "/activity",
    keywords: ["history", "log"],
    scope: "collector",
  }),

  // --- Admin ---------------------------------------------------------
  // Kept as data (not deleted) for the dedicated admin-login task - see the
  // module comment above. `requires_admin: true` is enforced in
  // CommandPalette.tsx and today evaluates to "hidden for everyone."
  cmd({
    id: "admin-catalog-ops",
    label: "Catalog Ops",
    description: "Catalog operations dashboard",
    group: "Admin",
    route_path: "/admin/catalog-ops",
    keywords: ["catalog", "operations"],
    scope: "admin",
    badge: "admin",
    requires_admin: true,
  }),
  cmd({
    id: "admin-cards",
    label: "Cards",
    description: "Card catalog administration",
    group: "Admin",
    route_path: "/admin/cards",
    keywords: ["catalog", "cards"],
    scope: "admin",
    badge: "admin",
    requires_admin: true,
  }),
  cmd({
    id: "admin-import-validation",
    label: "Import Validation",
    description: "Import templates and validation reports",
    group: "Admin",
    route_path: "/admin/import-validation",
    keywords: ["import", "csv", "template"],
    scope: "admin",
    badge: "admin",
    requires_admin: true,
  }),
  cmd({
    id: "admin-card-audit",
    label: "Card Audit",
    description: "Catalog operations audit",
    group: "Admin",
    route_path: "/admin/card-audit",
    keywords: ["audit"],
    scope: "admin",
    badge: "admin",
    requires_admin: true,
  }),
  cmd({
    id: "admin-card-duplicates",
    label: "Card Duplicates",
    description: "Card identity merge and duplicate cleanup",
    group: "Admin",
    route_path: "/admin/card-duplicates",
    keywords: ["duplicate", "merge"],
    scope: "admin",
    badge: "admin",
    requires_admin: true,
  }),
  cmd({
    id: "admin-snkrdunk-candidates",
    label: "SNKRDUNK Candidates",
    description: "SNKRDUNK source candidates",
    group: "Admin",
    route_path: "/admin/snkrdunk-candidates",
    keywords: ["snkrdunk", "candidates"],
    scope: "admin",
    badge: "admin",
    requires_admin: true,
  }),
  cmd({
    id: "admin-source-mapping-quality",
    label: "Source Mapping Quality",
    description: "Price source mapping health",
    group: "Admin",
    route_path: "/admin/source-mapping-quality",
    keywords: ["source", "mapping", "quality"],
    scope: "admin",
    badge: "admin",
    requires_admin: true,
  }),
  cmd({
    id: "admin-catalog-coverage",
    label: "Catalog Coverage",
    description: "Catalog coverage dashboard",
    group: "Admin",
    route_path: "/admin/catalog-coverage",
    keywords: ["coverage"],
    scope: "admin",
    badge: "admin",
    requires_admin: true,
  }),
  cmd({
    id: "admin-price-source-health",
    label: "Price Source Health",
    description: "Price source health audit",
    group: "Admin",
    route_path: "/admin/price-source-health",
    keywords: ["price", "source", "health"],
    scope: "admin",
    badge: "admin",
    requires_admin: true,
  }),
  cmd({
    id: "admin-system-check",
    label: "System Check",
    description: "System health check",
    group: "Admin",
    route_path: "/admin/system-check",
    keywords: ["system", "health"],
    scope: "admin",
    badge: "admin",
    requires_admin: true,
  }),
  cmd({
    id: "admin-actions",
    label: "Admin Actions",
    description: "Admin action log",
    group: "Admin",
    route_path: "/admin/actions",
    keywords: ["actions", "log"],
    scope: "admin",
    badge: "admin",
    requires_admin: true,
  }),
  cmd({
    id: "admin-backup",
    label: "Backup",
    description: "Backup and restore",
    group: "Admin",
    route_path: "/admin/backup",
    keywords: ["backup", "restore"],
    scope: "admin",
    badge: "admin",
    requires_admin: true,
  }),
  cmd({
    id: "admin-logs",
    label: "Logs",
    description: "Application logs",
    group: "Admin",
    route_path: "/admin/logs",
    keywords: ["logs"],
    scope: "admin",
    badge: "admin",
    requires_admin: true,
  }),
  cmd({
    id: "admin-performance",
    label: "Performance",
    description: "Performance metrics",
    group: "Admin",
    route_path: "/admin/performance",
    keywords: ["performance", "metrics"],
    scope: "admin",
    badge: "admin",
    requires_admin: true,
  }),
  cmd({
    id: "admin-cache",
    label: "Cache",
    description: "Cache administration",
    group: "Admin",
    route_path: "/admin/cache",
    keywords: ["cache"],
    scope: "admin",
    badge: "admin",
    requires_admin: true,
  }),
  cmd({
    id: "admin-job-locks",
    label: "Job Locks",
    description: "Background job locks",
    group: "Admin",
    route_path: "/admin/job-locks",
    keywords: ["job", "lock"],
    scope: "admin",
    badge: "admin",
    requires_admin: true,
  }),
  cmd({
    id: "admin-file-jobs",
    label: "File Jobs",
    description: "File processing jobs",
    group: "Admin",
    route_path: "/admin/file-jobs",
    keywords: ["file", "job"],
    scope: "admin",
    badge: "admin",
    requires_admin: true,
  }),
];

export interface CommandVisibilityContext {
  isAuthenticated: boolean;
  isAdmin: boolean;
}

/** The actual enforcement point for `scope`/`requires_admin` - both
 * CommandPalette.tsx and searchCommands() below must go through this rather
 * than reading the registry directly, or the two could drift. */
export function visibleCommands(commands: Command[], ctx: CommandVisibilityContext): Command[] {
  return commands.filter((c) => {
    if (c.requires_admin && !ctx.isAdmin) return false;
    if (c.scope === "collector" && !ctx.isAuthenticated) return false;
    if (c.scope === "admin" && !ctx.isAdmin) return false;
    return true;
  });
}

const NORMALIZE = (s: string) => s.toLowerCase().trim();

export function searchCommands(query: string, ctx: CommandVisibilityContext): Command[] {
  const q = NORMALIZE(query);
  const visible = visibleCommands(COMMAND_REGISTRY, ctx);
  if (!q) return visible;
  return visible.filter((c) => {
    const haystack = `${c.label} ${c.description} ${c.keywords.join(" ")}`.toLowerCase();
    return haystack.includes(q);
  });
}
