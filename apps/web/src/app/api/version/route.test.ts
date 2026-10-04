import { readFileSync } from "node:fs";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildVersion, buildCommit } from "@/generated/buildVersion";

beforeEach(() => {
  vi.resetModules();
  for (const key of ["APP_VERSION", "GIT_COMMIT", "VERCEL_GIT_COMMIT_SHA", "BUILD_TIME"]) {
    vi.stubEnv(key, "");
  }
  vi.stubEnv("API_INTERNAL_URL", "http://backend.invalid");
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

async function get() {
  return (await import("./route")).GET();
}

describe("GET /api/version", () => {
  it("uses the generated authoritative root VERSION and adds immutable build identity", async () => {
    expect(buildVersion).toBe(readFileSync(path.resolve(__dirname, "../../../../../../VERSION"), "utf8").trim());
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ version: "backend-version", git_commit: "backend-sha", extra: "ignored" }));
    const response = await get();
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      web: { version: buildVersion, git_commit: "unknown", build_time: "unknown", source_commit: buildCommit },
      api: { version: "backend-version", git_commit: "backend-sha" },
    });
    expect(fetch).toHaveBeenCalledExactlyOnceWith("http://backend.invalid/version", { cache: "no-store", signal: expect.any(AbortSignal) });
  });

  it("preserves APP_VERSION, GIT_COMMIT and BUILD_TIME overrides", async () => {
    vi.stubEnv("APP_VERSION", "7.8.9");
    vi.stubEnv("GIT_COMMIT", "explicit-sha");
    vi.stubEnv("VERCEL_GIT_COMMIT_SHA", "vercel-sha");
    vi.stubEnv("BUILD_TIME", "2026-09-28T12:00:00Z");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 503 }));
    expect(await (await get()).json()).toEqual({ web: { version: "7.8.9", git_commit: "explicit-sha", build_time: "2026-09-28T12:00:00Z", source_commit: buildCommit }, api: null });
  });

  it("uses the Vercel commit only when GIT_COMMIT is absent", async () => {
    vi.stubEnv("VERCEL_GIT_COMMIT_SHA", "vercel-sha");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 503 }));
    expect((await (await get()).json()).web.git_commit).toBe("vercel-sha");
  });

  it("retains the default backend URL", async () => {
    vi.stubEnv("API_INTERNAL_URL", "");
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 503 }));
    await get();
    expect(fetch).toHaveBeenCalledWith("http://api:8000/version", expect.objectContaining({ cache: "no-store" }));
  });

  it.each(["network", "invalid-json", "non-success"])("returns web metadata with api=null on %s failure", async (kind) => {
    const fetch = vi.spyOn(globalThis, "fetch");
    if (kind === "network") fetch.mockRejectedValue(new Error("unavailable"));
    else fetch.mockResolvedValue(new Response("invalid JSON", { status: kind === "non-success" ? 503 : 200 }));
    expect(await (await get()).json()).toEqual({ web: { version: buildVersion, git_commit: "unknown", build_time: "unknown", source_commit: buildCommit }, api: null });
  });

  it("aborts a stalled backend after exactly five seconds and clears the timer", async () => {
    const { GET } = await import("./route");
    vi.useFakeTimers();
    let signal: AbortSignal | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      signal = init?.signal as AbortSignal;
      signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));
    const pending = GET();
    await vi.advanceTimersByTimeAsync(4999);
    expect(signal?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(signal?.aborted).toBe(true);
    expect((await (await pending).json()).api).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("clears the timeout after a successful backend response", async () => {
    const { GET } = await import("./route");
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ version: "1", git_commit: "sha" }));
    await GET();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not import runtime filesystem tooling or scan the working directory", () => {
    const source = readFileSync(path.join(__dirname, "route.ts"), "utf8");
    expect(source).not.toMatch(/(?:node:)?(?:fs|path)["']|process\.cwd|readFileSync/);
  });
});
