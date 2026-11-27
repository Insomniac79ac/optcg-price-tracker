import { NextRequest, NextResponse } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { proxyAdminJson } = vi.hoisted(() => ({ proxyAdminJson: vi.fn() }));
vi.mock("@/lib/adminProxy", () => ({ proxyAdminJson }));

import * as route from "./route";

beforeEach(() => {
  proxyAdminJson.mockReset();
});

describe("GET /api/admin/rate-limit/status", () => {
  it("goes through the admin proxy with the fixed backend path only", async () => {
    proxyAdminJson.mockResolvedValue(NextResponse.json({ enabled: true }, { status: 200 }));
    const request = new NextRequest("https://x.app/api/admin/rate-limit/status?path=/admin/other", {
      headers: { "x-admin-token": "caller-supplied" },
    });
    const response = await route.GET(request);
    expect(proxyAdminJson).toHaveBeenCalledTimes(1);
    expect(proxyAdminJson).toHaveBeenCalledWith(request, "/admin/rate-limit/status", {
      logLabel: "rate-limit-status",
    });
    expect(response.status).toBe(200);
  });

  it("passes a signed-out 401 from the proxy straight through", async () => {
    proxyAdminJson.mockResolvedValue(NextResponse.json({ error: "Admin session required." }, { status: 401 }));
    const response = await route.GET(new NextRequest("https://x.app/api/admin/rate-limit/status"));
    expect(response.status).toBe(401);
  });

  it("is GET only and never statically cached", () => {
    expect(route.dynamic).toBe("force-dynamic");
    expect(Object.keys(route).sort()).toEqual(["GET", "dynamic"]);
  });
});
