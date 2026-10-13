import { NextRequest, NextResponse } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { requireAdminOrResponse, proxyAdminJson } = vi.hoisted(() => ({
  requireAdminOrResponse: vi.fn(),
  proxyAdminJson: vi.fn(),
}));
vi.mock("@/lib/adminProxy", () => ({ requireAdminOrResponse, proxyAdminJson }));

import { GET } from "./route";

const url = (target: string) => new NextRequest(`https://x.app/api/admin/observability/sentry-test?target=${target}`);

beforeEach(() => {
  requireAdminOrResponse.mockReset();
  proxyAdminJson.mockReset();
});

describe("GET /api/admin/observability/sentry-test", () => {
  it("refuses a caller without an admin session and throws nothing", async () => {
    requireAdminOrResponse.mockResolvedValue({ response: NextResponse.json({ error: "Admin session required." }, { status: 401 }) });
    const response = await GET(url("web"));
    expect(response.status).toBe(401);
  });

  it("throws the deliberate web test error for an admin", async () => {
    requireAdminOrResponse.mockResolvedValue({ identity: { id: "a", email: "admin@example.invalid" } });
    await expect(GET(url("web"))).rejects.toThrow("Deliberate Sentry test error (web)");
  });

  it("delegates the API test to the authenticated admin proxy", async () => {
    proxyAdminJson.mockResolvedValue(NextResponse.json({ detail: "Internal Server Error" }, { status: 500 }));
    const response = await GET(url("api"));
    expect(proxyAdminJson).toHaveBeenCalledWith(expect.anything(), "/admin/observability/sentry-test", { logLabel: "sentry-test" });
    expect(requireAdminOrResponse).not.toHaveBeenCalled();
    expect(response.status).toBe(500);
  });
});
