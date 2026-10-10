import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

const { getAdminIdentityForRouteHandler } = vi.hoisted(() => ({
  getAdminIdentityForRouteHandler: vi.fn(),
}));
vi.mock("@/lib/adminSession", () => ({ getAdminIdentityForRouteHandler }));

import { GET as digestLatest } from "./analytics/digest/latest/route";
import { GET as digestReports } from "./analytics/digest/reports/route";
import { GET as digestReport } from "./analytics/digest/reports/[id]/route";
import { GET as opportunities } from "./market/opportunities/route";
import { GET as reportLatest } from "./market/report/latest/route";
import { GET as reports } from "./market/reports/route";
import { GET as report } from "./market/reports/[id]/route";
import { GET as signalEvents } from "./market/signal-events/route";
import { GET as signals } from "./market/signals/route";

// Market intelligence and stored analytics digests are market-wide and carry
// ownership/portfolio figures summed across every collection, so their
// read proxies are admin-only, like the backend routes behind them.

const ADMIN_IDENTITY = { id: "staging-admin", email: "admin@example.com" };
const params = { params: Promise.resolve({ id: "7" }) };

type Handler = (request: NextRequest, context: typeof params) => Promise<Response>;

const READS: { name: string; handler: Handler; query: string; path: string }[] = [
  { name: "signals", handler: signals, query: "?limit=5", path: "/market/signals?limit=5" },
  { name: "signal-events", handler: signalEvents, query: "?status=open", path: "/market/signal-events?status=open" },
  { name: "opportunities", handler: opportunities, query: "?owned=true", path: "/market/opportunities?owned=true" },
  { name: "report/latest", handler: reportLatest, query: "", path: "/market/report/latest" },
  { name: "reports", handler: reports, query: "?limit=30", path: "/market/reports?limit=30" },
  { name: "reports/[id]", handler: report, query: "", path: "/market/reports/7" },
  {
    name: "digest/latest",
    handler: digestLatest,
    query: "?valuation_mode=raw_market",
    path: "/analytics/digest/latest?valuation_mode=raw_market",
  },
  { name: "digest/reports", handler: digestReports, query: "?limit=30", path: "/analytics/digest/reports?limit=30" },
  { name: "digest/reports/[id]", handler: digestReport, query: "", path: "/analytics/digest/reports/7" },
];

function req(query: string, headers?: Record<string, string>): NextRequest {
  return new NextRequest(new Request(`http://localhost/api/private${query}`, { headers }));
}

describe("private read proxies are admin-only", () => {
  const originalFetch = global.fetch;
  const originalToken = process.env.ADMIN_TOKEN;

  beforeEach(() => {
    getAdminIdentityForRouteHandler.mockReset();
    process.env.ADMIN_TOKEN = "server-side-secret";
  });

  afterEach(() => {
    global.fetch = originalFetch;
    process.env.ADMIN_TOKEN = originalToken;
  });

  it.each(READS)("$name returns 401 and never calls the backend without an admin session", async (r) => {
    getAdminIdentityForRouteHandler.mockResolvedValueOnce(null);
    const fetchSpy = vi.fn();
    global.fetch = fetchSpy;

    const response = await r.handler(req(r.query, { "X-Admin-Token": "caller-supplied" }), params);

    expect(response.status).toBe(401);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it.each(READS)("$name forwards to the backend with the server-side admin token", async (r) => {
    getAdminIdentityForRouteHandler.mockResolvedValueOnce(ADMIN_IDENTITY);
    const fetchSpy = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    global.fetch = fetchSpy;

    const response = await r.handler(req(r.query), params);

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url).endsWith(r.path)).toBe(true);
    expect(init.method).toBe("GET");
    expect(init.cache).toBe("no-store");
    expect(init.headers["X-Admin-Token"]).toBe("server-side-secret");
  });
});
