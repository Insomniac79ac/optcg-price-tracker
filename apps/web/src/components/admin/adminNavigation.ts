export const ADMIN_NAVIGATION = [
  {
    label: "Catalogue",
    description: "Maintain card identity, imports and catalogue coverage.",
    routes: [
      ["/admin", "Overview"], ["/admin/catalog-ops", "Catalog Ops"],
      ["/admin/cards", "Cards"], ["/admin/import-validation", "Import Validation"],
      ["/admin/card-audit", "Card Audit"], ["/admin/card-duplicates", "Duplicates"],
      ["/admin/catalog-coverage", "Catalog Coverage"],
    ],
  },
  {
    label: "Sources & Pricing",
    description: "Review source evidence, exact printings and price coverage.",
    routes: [
      ["/admin/source-mapping-proposals", "Proposal Review"],
      ["/admin/source-mapping-quality", "Source Mapping Quality"],
      ["/admin/snkrdunk-candidates", "SNKRDUNK Candidates"],
      ["/admin/price-source-health", "Price Source Health"],
      ["/admin/collection-attempts", "Collection Attempts"],
    ],
  },
  {
    label: "Operations",
    description: "Inspect workflow history, file jobs and operational alerts.",
    routes: [
      ["/admin/actions", "Actions"], ["/admin/market-workflow-runs", "Workflow Runs"],
      ["/admin/refresh-runs", "Refresh Runs"], ["/admin/file-jobs", "File Jobs"],
      ["/admin/alerts", "Alerts"],
    ],
  },
  {
    label: "System",
    description: "Inspect service health, diagnostics and maintenance tools.",
    routes: [
      ["/admin/system-check", "System Check"], ["/admin/performance", "Performance"],
      ["/admin/logs", "Logs"], ["/admin/cache", "Cache"],
      ["/admin/job-locks", "Job Locks"], ["/admin/data-retention", "Data Retention"],
      ["/admin/backup", "Backup"], ["/admin/release-status", "Release Status"],
    ],
  },
] as const;

export function adminRouteActive(pathname: string, href: string): boolean {
  return pathname === href || (href !== "/admin" && pathname.startsWith(`${href}/`));
}
