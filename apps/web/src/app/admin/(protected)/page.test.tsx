import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
vi.mock("@/lib/adminSession", () => ({ requireAdminSession: vi.fn(async () => ({ id: "test", email: "admin@example.com" })) }));
vi.mock("@/components/AppHeader", () => ({ AppHeader: () => null }));
import AdminIndexPage from "./page";

it("renders the four operational groups without fetching live metrics", async () => {
  const network = vi.spyOn(globalThis, "fetch");
  try {
    render(await AdminIndexPage());
    expect(screen.getByRole("heading", { name: "Admin overview" })).toBeInTheDocument();
    for (const name of ["Catalogue", "Sources & Pricing", "Operations", "System"]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: /Proposal Review/ })).toHaveAttribute("href", "/admin/source-mapping-proposals");
    expect(screen.queryByText(/Pick a section above/)).not.toBeInTheDocument();
    expect(network).not.toHaveBeenCalled();
  } finally { network.mockRestore(); }
});
