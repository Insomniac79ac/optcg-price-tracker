import { describe, expect, it, vi } from "vitest";

const { notFound } = vi.hoisted(() => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
}));
vi.mock("next/navigation", () => ({ notFound }));

import AdminLayout from "./layout";

describe("AdminLayout (shared server-side boundary for all /admin/* routes)", () => {
  it("calls notFound() before rendering a page's children - e.g. system-check", () => {
    notFound.mockClear();
    expect(() => AdminLayout()).toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalledTimes(1);
  });

  it("calls notFound() regardless of which admin page would have rendered - e.g. backup", () => {
    // The layout takes no route-specific input, which is the point: it is
    // one shared boundary for the whole /admin/* group, not a per-page
    // check that could be forgotten on a new page.
    notFound.mockClear();
    expect(() => AdminLayout()).toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalledTimes(1);
  });

  it("does not gate on any session/role - no admin session concept exists yet", () => {
    // Regression guard: if someone "fixes" this by adding a role check that
    // defaults to allowing access when the field is undefined, this test
    // (which passes no session at all) would start failing to throw.
    notFound.mockClear();
    expect(() => AdminLayout()).toThrow();
  });
});
