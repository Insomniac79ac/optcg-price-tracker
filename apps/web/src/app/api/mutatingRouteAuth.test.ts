import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// Static guard: every Route Handler under src/app/api that exports a
// state-changing method must authenticate the caller before forwarding,
// through one of the shared helpers below (or an Auth.js session that
// supplies a bearer token). A new unauthenticated write route fails here.
// The same holds for reads: a GET handler is either authenticated or on an
// explicit, reviewed public list, so a new proxy that returns collection,
// wishlist, portfolio or ownership data cannot ship unauthenticated.

const API_DIR = __dirname;
const MUTATING_EXPORT = /export\s+(?:async\s+)?(?:function|const)\s+(POST|PUT|PATCH|DELETE)\b/;

const AUTH_MARKERS = [
  "proxyAdminJson", // admin session + server-side X-Admin-Token
  "proxyAdminActorJson", // admin session + actor assertion
  "requireAdminOrResponse", // admin session (streaming/multipart routes)
  "proxySavedViews", // user session bearer token
  "session.apiToken", // user session bearer token
];

// Relative paths that are intentionally unauthenticated.
const ALLOWLIST = new Set([
  // Auth.js sign-in/sign-out handlers (CSRF-protected by Auth.js itself).
  "auth/[...nextauth]/route.ts",
]);

const GET_EXPORT = /export\s+(?:async\s+)?(?:function|const)\s+GET\b|export\s+const\s+\{[^}]*\bGET\b/;

// GET handlers that are intentionally unauthenticated. Adding one here is a
// deliberate review that it returns nothing derived from any user's data.
const PUBLIC_READ_ALLOWLIST = new Set([
  "auth/[...nextauth]/route.ts", // Auth.js session/CSRF/provider endpoints
  "backend-health/route.ts", // backend /health passthrough
  "card-image/route.ts", // public card artwork proxy
  "health/route.ts", // web liveness
  "version/route.ts", // build identity
]);

// Market intelligence and stored analytics digests: admin-only reads.
const ADMIN_ONLY_READS = [
  "market/signals/route.ts",
  "market/signal-events/route.ts",
  "market/opportunities/route.ts",
  "market/report/latest/route.ts",
  "market/reports/route.ts",
  "market/reports/[id]/route.ts",
  "analytics/digest/latest/route.ts",
  "analytics/digest/reports/route.ts",
  "analytics/digest/reports/[id]/route.ts",
];

function routeFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return routeFiles(full);
    return entry.name === "route.ts" ? [full] : [];
  });
}

describe("mutating API routes require authentication", () => {
  const files = routeFiles(API_DIR);

  it("finds the route handlers it is meant to guard", () => {
    const relative = files.map((f) => path.relative(API_DIR, f));
    expect(relative).toContain("market/signal-events/[id]/dismiss/route.ts");
    expect(relative).toContain("admin/cache/clear/route.ts");
  });

  it("every POST/PUT/PATCH/DELETE handler uses an auth helper", () => {
    const unauthenticated = files
      .filter((file) => !ALLOWLIST.has(path.relative(API_DIR, file)))
      .filter((file) => {
        const source = fs.readFileSync(file, "utf8");
        return MUTATING_EXPORT.test(source) && !AUTH_MARKERS.some((m) => source.includes(m));
      })
      .map((file) => path.relative(API_DIR, file));

    expect(unauthenticated).toEqual([]);
  });
});

describe("read API routes require authentication unless explicitly public", () => {
  const files = routeFiles(API_DIR);
  const relative = (file: string) => path.relative(API_DIR, file);
  const readFiles = files.filter((file) => GET_EXPORT.test(fs.readFileSync(file, "utf8")));

  it("finds the read handlers it is meant to guard", () => {
    const reads = readFiles.map(relative);
    expect(reads).toContain("market/signal-events/route.ts");
    expect(reads).toContain("auth/[...nextauth]/route.ts");
  });

  it("every GET handler uses an auth helper or is explicitly public", () => {
    const unauthenticated = readFiles
      .filter((file) => !PUBLIC_READ_ALLOWLIST.has(relative(file)))
      .filter((file) => !AUTH_MARKERS.some((m) => fs.readFileSync(file, "utf8").includes(m)))
      .map(relative);

    expect(unauthenticated).toEqual([]);
  });

  it("has no stale public allowlist entries", () => {
    const reads = new Set(readFiles.map(relative));
    expect([...PUBLIC_READ_ALLOWLIST].filter((entry) => !reads.has(entry))).toEqual([]);
  });

  it("market intelligence and stored digest reads require an admin session", () => {
    for (const route of ADMIN_ONLY_READS) {
      const source = fs.readFileSync(path.join(API_DIR, route), "utf8");
      expect(source, route).toContain("proxyAdminJson(");
    }
  });
});
