// Recent-workflow tracking for the command palette. localStorage-only by
// design (see docs/interface_design_system.md "Command palette" and
// docs/operations.md "Workflow shortcuts") - this is ephemeral, single-
// browser UX convenience, not data that needs to survive a device change or
// appear in backups, so it doesn't warrant a fifth new database table.
// The shape mirrors what a backend table would look like, so this could
// migrate later with no data-shape change.

export type RecentWorkflowType = "route" | "saved_view" | "card" | "admin_action";

export interface RecentWorkflowEntry {
  item_type: RecentWorkflowType;
  label: string;
  route_path: string;
  payload_json: Record<string, unknown> | null;
  last_used_at: string;
  usage_count: number;
}

const STORAGE_KEY = "optcg.recentWorkflows.v1";
const MAX_ENTRIES = 20;

function readAll(): RecentWorkflowEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed;
  } catch {
    return [];
  }
}

function writeAll(entries: RecentWorkflowEntry[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // localStorage unavailable (private mode, quota) - recent workflows are
    // a convenience feature, so silently skip rather than surface an error.
  }
}

export function getRecentWorkflows(limit = 8): RecentWorkflowEntry[] {
  return readAll()
    .sort((a, b) => (a.last_used_at < b.last_used_at ? 1 : -1))
    .slice(0, limit);
}

export function recordRecentWorkflow(entry: {
  item_type: RecentWorkflowType;
  label: string;
  route_path: string;
  payload_json?: Record<string, unknown> | null;
}) {
  const all = readAll();
  const existingIdx = all.findIndex(
    (e) =>
      e.item_type === entry.item_type &&
      e.route_path === entry.route_path &&
      e.label === entry.label,
  );

  const now = new Date().toISOString();

  if (existingIdx >= 0) {
    const existing = all[existingIdx];
    all[existingIdx] = {
      ...existing,
      payload_json: entry.payload_json ?? existing.payload_json ?? null,
      last_used_at: now,
      usage_count: existing.usage_count + 1,
    };
  } else {
    all.push({
      item_type: entry.item_type,
      label: entry.label,
      route_path: entry.route_path,
      payload_json: entry.payload_json ?? null,
      last_used_at: now,
      usage_count: 1,
    });
  }

  const trimmed = all
    .sort((a, b) => (a.last_used_at < b.last_used_at ? 1 : -1))
    .slice(0, MAX_ENTRIES);

  writeAll(trimmed);
}

export function clearRecentWorkflows() {
  writeAll([]);
}
