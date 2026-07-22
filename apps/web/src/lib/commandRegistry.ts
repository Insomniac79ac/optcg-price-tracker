// Static command list for the global Cmd/Ctrl+K palette (see
// docs/interface_design_system.md "Command palette"). Every `route_path`
// here has been confirmed against the actual App Router tree / SidebarNav -
// routes the design brief named that don't exist (e.g. a standalone
// "/admin/source-mappings") are omitted rather than linked as dead ends.

export type CommandGroup =
  | "Navigate"
  | "Cards"
  | "Collection"
  | "Wishlist"
  | "Grading"
  | "Market"
  | "Analytics"
  | "Admin";

export type CommandScope = "collector" | "admin" | "analytics" | "market";

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
  // --- Navigate --------------------------------------------------------
  cmd({
    id: "nav-dashboard",
    label: "Dashboard",
    description: "Portfolio overview, pinned views, vault highlights",
    group: "Navigate",
    route_path: "/dashboard",
    keywords: ["home", "overview"],
    scope: "collector",
  }),
  cmd({
    id: "nav-search",
    label: "Cards / Search",
    description: "Search cards, collection, signals and more",
    group: "Navigate",
    route_path: "/search",
    keywords: ["find", "lookup"],
    scope: "collector",
  }),
  cmd({
    id: "nav-collection-table",
    label: "Collection (Table)",
    description: "Owned cards in table view",
    group: "Collection",
    route_path: "/collection",
    keywords: ["owned", "table"],
    scope: "collector",
  }),
  cmd({
    id: "nav-collection-vault",
    label: "Collection (Vault)",
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
  cmd({
    id: "nav-market-opportunities",
    label: "Market Opportunities",
    description: "Buy/sell opportunity scoring",
    group: "Market",
    route_path: "/market/opportunities",
    keywords: ["deals", "score"],
    scope: "market",
  }),
  cmd({
    id: "nav-market-signals",
    label: "Market Signals",
    description: "Price movement signals",
    group: "Market",
    route_path: "/market/signals",
    keywords: ["signal", "alert"],
    scope: "market",
  }),
  cmd({
    id: "nav-market-signal-events",
    label: "Market Signal Events",
    description: "Signal event history",
    group: "Market",
    route_path: "/market/signal-events",
    keywords: ["signal", "events"],
    scope: "market",
  }),

  // --- Analytics ---------------------------------------------------------
  cmd({
    id: "analytics-digest",
    label: "Analytics Digest",
    description: "Rolled-up analytics summary",
    group: "Analytics",
    route_path: "/analytics/digest",
    keywords: ["summary", "digest"],
    scope: "analytics",
  }),
  cmd({
    id: "analytics-collection",
    label: "Collection Analytics",
    description: "Value and composition of your collection",
    group: "Analytics",
    route_path: "/analytics/collection",
    keywords: ["value", "composition"],
    scope: "analytics",
  }),
  cmd({
    id: "analytics-wishlist",
    label: "Wishlist Analytics",
    description: "Wishlist cost and priority breakdown",
    group: "Analytics",
    route_path: "/analytics/wishlist",
    keywords: ["wishlist", "cost"],
    scope: "analytics",
  }),
  cmd({
    id: "analytics-buy-decisions",
    label: "Buy Decisions",
    description: "Recommended buy candidates",
    group: "Analytics",
    route_path: "/analytics/buy-decisions",
    keywords: ["buy", "recommend"],
    scope: "analytics",
  }),
  cmd({
    id: "analytics-sell-decisions",
    label: "Sell Decisions",
    description: "Recommended sell candidates",
    group: "Analytics",
    route_path: "/analytics/sell-decisions",
    keywords: ["sell", "recommend"],
    scope: "analytics",
  }),
  cmd({
    id: "analytics-grading-roi",
    label: "Grading ROI",
    description: "Grading analytics and return on investment",
    group: "Analytics",
    route_path: "/analytics/grading",
    keywords: ["grading", "roi"],
    scope: "analytics",
  }),
  cmd({
    id: "analytics-portfolio-risk",
    label: "Portfolio Risk",
    description: "Concentration and risk exposure",
    group: "Analytics",
    route_path: "/analytics/portfolio-risk",
    keywords: ["risk", "exposure"],
    scope: "analytics",
  }),

  // --- Admin ---------------------------------------------------------
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

const NORMALIZE = (s: string) => s.toLowerCase().trim();

export function searchCommands(query: string): Command[] {
  const q = NORMALIZE(query);
  if (!q) return COMMAND_REGISTRY;
  return COMMAND_REGISTRY.filter((c) => {
    const haystack = `${c.label} ${c.description} ${c.keywords.join(" ")}`.toLowerCase();
    return haystack.includes(q);
  });
}
