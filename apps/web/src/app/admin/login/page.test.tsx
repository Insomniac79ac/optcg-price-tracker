import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { auth, enabled, signIn, push, refresh, redirect } = vi.hoisted(() => ({
  auth: vi.fn(), enabled: vi.fn(), signIn: vi.fn(), push: vi.fn(), refresh: vi.fn(),
  redirect: vi.fn((path: string) => { throw new Error(`REDIRECT:${path}`); }),
}));
vi.mock("@/lib/auth", () => ({ auth, isAdminLoginEnabled: enabled }));
vi.mock("next-auth/react", () => ({ signIn }));
vi.mock("next/navigation", () => ({ redirect, useRouter: () => ({ push, refresh }) }));
vi.mock("@/components/AppHeader", () => ({ AppHeader: () => <header>Atlas</header> }));
import AdminLoginPage from "./page";

beforeEach(() => {
  vi.clearAllMocks();
  enabled.mockResolvedValue(true);
  auth.mockResolvedValue({ user: { email: "admin@example.com" }, sessionKind: "admin", adminSessionExpired: true });
  signIn.mockResolvedValue({ ok: true });
});

describe("admin reauthentication", () => {
  it("explains expiry and returns a successful login to the exact proposal URL", async () => {
    const callbackUrl = "/admin/source-mapping-proposals/1128?returnTo=%2Fadmin%2Fsource-mapping-proposals%3Fpage%3D4";
    render(await AdminLoginPage({ searchParams: Promise.resolve({ callbackUrl, reason: "session-expired" }) }));
    expect(screen.getByRole("status")).toHaveTextContent("Your administrator session expired. Sign in again to continue.");
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "admin@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "test-only-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith(callbackUrl));
    expect(signIn).toHaveBeenCalledWith("admin-credentials", { email: "admin@example.com", password: "test-only-password", redirect: false });
    expect(refresh).toHaveBeenCalled();
  });
  it("keeps failed reauthentication on the login page", async () => {
    signIn.mockResolvedValue({ error: "CredentialsSignin" });
    render(await AdminLoginPage({ searchParams: Promise.resolve({}) }));
    fireEvent.submit(screen.getByRole("button", { name: "Sign in" }).closest("form")!);
    expect(await screen.findByText("Invalid email or password.")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
  it.each([undefined, "https://evil.example/admin", "/admin/login"])("uses overview for missing or rejected callback %s", async (callbackUrl) => {
    render(await AdminLoginPage({ searchParams: Promise.resolve({ callbackUrl }) }));
    fireEvent.submit(screen.getByRole("button", { name: "Sign in" }).closest("form")!);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin"));
    expect(screen.queryByText(/session expired/)).not.toBeInTheDocument();
  });
  it("redirects an already active administrator to the requested proposal", async () => {
    auth.mockResolvedValue({ user: { role: "admin" } });
    await expect(AdminLoginPage({ searchParams: Promise.resolve({ callbackUrl: "/admin/source-mapping-proposals/1129" }) })).rejects.toThrow("REDIRECT:/admin/source-mapping-proposals/1129");
  });
});
