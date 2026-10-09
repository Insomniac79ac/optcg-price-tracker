import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// Static guard: every Route Handler under src/app/api that exports a
// state-changing method must authenticate the caller before forwarding,
// through one of the shared helpers below (or an Auth.js session that
// supplies a bearer token). A new unauthenticated write route fails here.

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
