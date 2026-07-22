import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
}));

const fetchCacheStatus = vi.fn();
const clearCache = vi.fn();
const getAdminToken = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchCacheStatus: (...args: unknown[]) => fetchCacheStatus(...args),
    clearCache: (...args: unknown[]) => clearCache(...args),
    getAdminToken: (...args: unknown[]) => getAdminToken(...args),
  };
});

import CachePage from "./page";

const SAMPLE_STATUS = {
  enabled: true,
  backend: "redis",
  stats: { keys: 3, hits: 10, misses: 2 },
  ttl: { dashboard: 60, market: 120, collection: 60 },
};

describe("CachePage", () => {
  beforeEach(() => {
    fetchCacheStatus.mockReset();
    clearCache.mockReset();
    getAdminToken.mockReset();
    getAdminToken.mockReturnValue("test-token");
  });

  it("renders status summary cards from the API", async () => {
    fetchCacheStatus.mockResolvedValue(SAMPLE_STATUS);
    render(<CachePage />);

    await waitFor(() => expect(screen.getByText("redis")).toBeInTheDocument());
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("does not crash and shows a loading state when stats are empty/pending", () => {
    fetchCacheStatus.mockResolvedValue(new Promise(() => {}));
    render(<CachePage />);

    expect(screen.getByText("Loading cache status…")).toBeInTheDocument();
  });

  it("does not call clearCache until CLEAR is typed to confirm", async () => {
    fetchCacheStatus.mockResolvedValue(SAMPLE_STATUS);
    render(<CachePage />);

    await waitFor(() => expect(screen.getByText("redis")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Clear cache" }));
    expect(clearCache).not.toHaveBeenCalled();
    expect(screen.getByText("Type CLEAR to confirm.")).toBeInTheDocument();

    const confirmInput = screen.getByRole("textbox", { name: /type clear to confirm/i });
    fireEvent.change(confirmInput, { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Clear cache" }));
    expect(clearCache).not.toHaveBeenCalled();

    clearCache.mockResolvedValue({ success: true, prefix: null, deleted_count: 5 });
    fireEvent.change(confirmInput, { target: { value: "CLEAR" } });
    fireEvent.click(screen.getByRole("button", { name: "Clear cache" }));

    await waitFor(() =>
      expect(clearCache).toHaveBeenCalledWith({ prefix: null, confirm: "CLEAR" }),
    );
    await waitFor(() =>
      expect(screen.getByText(/Cleared all cache keys/)).toBeInTheDocument(),
    );
  });

  it("passes the typed prefix through to clearCache", async () => {
    fetchCacheStatus.mockResolvedValue(SAMPLE_STATUS);
    clearCache.mockResolvedValue({ success: true, prefix: "dashboard", deleted_count: 1 });
    render(<CachePage />);

    await waitFor(() => expect(screen.getByText("redis")).toBeInTheDocument());

    const prefixInput = screen.getByPlaceholderText("e.g. dashboard");
    fireEvent.change(prefixInput, { target: { value: "dashboard" } });

    const confirmInput = screen.getByRole("textbox", { name: /type clear to confirm/i });
    fireEvent.change(confirmInput, { target: { value: "CLEAR" } });
    fireEvent.click(screen.getByRole("button", { name: "Clear cache" }));

    await waitFor(() =>
      expect(clearCache).toHaveBeenCalledWith({ prefix: "dashboard", confirm: "CLEAR" }),
    );
  });
});
