import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ usePathname: () => "/admin/source-mapping-proposals" }));

import { AdminSubNav } from "./AdminSubNav";

describe("AdminSubNav proposal review entry", () => {
  it("links the protected proposal workspace beside the related mapping tools", () => {
    render(<AdminSubNav />);
    const links = screen.getAllByRole("link");
    const labels = links.map((link) => link.textContent);
    const proposalIndex = labels.indexOf("Proposal Review");
    expect(links[proposalIndex]).toHaveAttribute("href", "/admin/source-mapping-proposals");
    expect(labels[proposalIndex - 1]).toBe("SNKRDUNK Candidates");
    expect(labels[proposalIndex + 1]).toBe("Source Mapping Quality");
  });
});
