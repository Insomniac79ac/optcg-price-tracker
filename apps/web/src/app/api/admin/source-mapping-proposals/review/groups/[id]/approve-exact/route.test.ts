// @vitest-environment node
import { NextRequest } from "next/server";
import { jwtVerify } from "jose";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

const { getAdminIdentityForRouteHandler } = vi.hoisted(() => ({
  getAdminIdentityForRouteHandler: vi.fn(),
}));
vi.mock("@/lib/adminSession", () => ({ getAdminIdentityForRouteHandler }));

import { deriveAdminActorKey } from "@/lib/adminActorAssertion";
import { POST } from "./route";

const ADMIN = { id: "authjs-admin-7", email: "reviewer@example.com" };
const ADMIN_TOKEN = "server-only-admin-token";
const BODY = '{"selected_alternative_id":7,"expected_evidence_digest":"' +
  "a".repeat(64) +
  '","expected_resolver_version":"source-mapping-proposals/1.0","expected_updated_at":"2026-09-22T00:00:00Z"}';

function request(headers: Record<string, string> = {}): NextRequest {
  return new NextRequest(
    "http://localhost/api/admin/source-mapping-proposals/review/groups/42/approve-exact",
    { method: "POST", body: BODY, headers: { "content-type": "application/json", ...headers } },
  );
}

describe("POST approve-exact proxy", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    process.env.ADMIN_TOKEN = ADMIN_TOKEN;
    getAdminIdentityForRouteHandler.mockReset();
    getAdminIdentityForRouteHandler.mockResolvedValue(ADMIN);
    global.fetch = vi.fn().mockResolvedValue(
      new Response('{"review_status":"approved"}', { status: 201 }),
    );
  });

  afterEach(() => {
    global.fetch = originalFetch;
    delete process.env.ADMIN_TOKEN;
    vi.restoreAllMocks();
  });

  it("rejects a non-admin before contacting the backend", async () => {
    getAdminIdentityForRouteHandler.mockResolvedValueOnce(null);
    const response = await POST(request(), { params: Promise.resolve({ id: "42" }) });
    expect(response.status).toBe(401);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("forwards exact bytes with only server-generated credentials and identity", async () => {
    const response = await POST(
      request({
        "x-admin-token": "caller-token",
        "x-admin-actor-assertion": "caller-assertion",
      }),
      { params: Promise.resolve({ id: "42" }) },
    );
    expect(response.status).toBe(201);
    await expect(response.json()).resolves.toEqual({ review_status: "approved" });

    const [url, init] = vi.mocked(global.fetch).mock.calls[0];
    expect(url).toBe(
      "http://api:8000/admin/source-mapping-proposals/review/groups/42/approve-exact",
    );
    expect(init?.method).toBe("POST");
    expect(init?.cache).toBe("no-store");
    expect(Buffer.from(init?.body as Uint8Array).toString()).toBe(BODY);
    const headers = init?.headers as Record<string, string>;
    expect(headers["X-Admin-Token"]).toBe(ADMIN_TOKEN);
    expect(headers["X-Admin-Actor-Assertion"]).not.toBe("caller-assertion");

    const verified = await jwtVerify(
      headers["X-Admin-Actor-Assertion"],
      deriveAdminActorKey(ADMIN_TOKEN),
      {
        algorithms: ["HS256"],
        issuer: "opcg-web-admin-proxy",
        audience: "opcg-proposal-decision",
      },
    );
    expect(verified.payload).toMatchObject({
      sub: ADMIN.id,
      email: ADMIN.email,
      method: "POST",
      path: "/admin/source-mapping-proposals/review/groups/42/approve-exact",
      purpose: "approve_exact_proposal",
    });
    expect(verified.payload.exp! - verified.payload.iat!).toBeLessThanOrEqual(60);
  });

  it("preserves backend error status and JSON", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response('{"detail":{"code":"proposal_updated"}}', { status: 409 }),
    );
    const response = await POST(request(), { params: Promise.resolve({ id: "42" }) });
    expect(response.status).toBe(409);
    await expect(response.json()).resolves.toEqual({ detail: { code: "proposal_updated" } });
  });

  it("fails closed when ADMIN_TOKEN is absent", async () => {
    delete process.env.ADMIN_TOKEN;
    const response = await POST(request(), { params: Promise.resolve({ id: "42" }) });
    expect(response.status).toBe(500);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("does not return or log either credential on upstream failure", async () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
    global.fetch = vi.fn().mockRejectedValue(new Error("connection refused"));
    const response = await POST(request(), { params: Promise.resolve({ id: "42" }) });
    const text = await response.text();
    expect(response.status).toBe(502);
    expect(text).not.toContain(ADMIN_TOKEN);
    const logged = JSON.stringify(log.mock.calls);
    expect(logged).not.toContain(ADMIN_TOKEN);
    expect(logged).not.toContain("eyJ");
  });
});
