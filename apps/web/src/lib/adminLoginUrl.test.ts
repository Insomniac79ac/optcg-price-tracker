import { describe, expect, it } from "vitest";
import { adminLoginHref, safeAdminCallbackUrl } from "./adminLoginUrl";

describe("admin callbacks", () => {
  it("preserves the exact admin path and encoded query", () => {
    const path = "/admin/source-mapping-proposals/1128?returnTo=%2Fadmin%2Fsource-mapping-proposals%3Fpage%3D4&note=a%20b";
    expect(safeAdminCallbackUrl(path)).toBe(path);
    const login = new URL(adminLoginHref(path, true), "https://atlas.example");
    expect(login.pathname).toBe("/admin/login");
    expect(login.searchParams.get("callbackUrl")).toBe(path);
    expect(login.searchParams.get("reason")).toBe("session-expired");
  });
  it.each([undefined, "", "https://evil.example/admin", "//evil.example", "/\\evil.example", "/admin/../../evil", "/admin/%2e%2e/evil", "/admin/%2f%2fevil", "/admin/\\evil", "/admin/%ZZ", "/admin\n", "/admin/login", "/admin/login/nested", "/administrator", "javascript:alert(1)"])("rejects unsafe or looping callback %s", (candidate) => {
    expect(safeAdminCallbackUrl(candidate)).toBe("/admin");
  });
});
