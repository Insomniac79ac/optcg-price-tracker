import { readFileSync } from "node:fs";
import path from "node:path";

import { render, screen, within } from "@testing-library/react";
import type { Metadata } from "next";
import { describe, expect, it, vi } from "vitest";

// Page metadata is built at import; these assertions describe the launch
// behaviour (SITE_SEARCH_INDEXING=on). Off, every page is noindex
// (publicSeo.test.ts).
vi.hoisted(() => {
  process.env.SITE_SEARCH_INDEXING = "on";
});

vi.mock("@/components/AppHeader", () => ({ AppHeader: () => <header data-testid="app-header" /> }));

import { FOOTER_LINKS, Footer } from "@/components/Footer";

import AboutPage, { metadata as aboutMetadata } from "./about/page";
import MethodologyPage, { metadata as methodologyMetadata } from "./methodology/page";
import PrivacyPage, { metadata as privacyMetadata } from "./privacy/page";
import TermsPage, { metadata as termsMetadata } from "./terms/page";

const PAGES = [
  { path: "/about", Page: AboutPage, metadata: aboutMetadata, h1: "About Card Pirate", draft: false },
  { path: "/methodology", Page: MethodologyPage, metadata: methodologyMetadata, h1: "How we price cards", draft: false },
  { path: "/privacy", Page: PrivacyPage, metadata: privacyMetadata, h1: "Privacy policy", draft: true },
  { path: "/terms", Page: TermsPage, metadata: termsMetadata, h1: "Terms of use", draft: true },
] as const;

function robots(metadata: Metadata) {
  return metadata.robots as { index?: boolean; follow?: boolean };
}

describe.each(PAGES)("$path", ({ path: route, Page, metadata, h1, draft }) => {
  it("renders the shared shell and its heading", () => {
    render(<Page />);
    expect(screen.getByTestId("app-header")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: h1 })).toBeInTheDocument();
  });

  it(draft ? "is a noindex draft with a visible banner" : "is indexable with no draft banner", () => {
    const { container } = render(<Page />);
    const banner = container.querySelector("[data-draft-banner]");
    expect(robots(metadata).index).toBe(!draft);
    if (draft) {
      expect(banner).not.toBeNull();
      expect(banner).toHaveTextContent("Draft – under review");
      expect(String(metadata.title && (metadata.title as { absolute: string }).absolute)).toContain("(draft)");
    } else {
      expect(banner).toBeNull();
    }
  });

  it("sets a canonical URL on its own path", () => {
    expect(String(metadata.alternates?.canonical)).toMatch(new RegExp(`${route}$`));
  });

  it("uses collection language, names the operator only as Card Pirate and leaks no address", () => {
    const { container } = render(<Page />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/portfolio/i);
    // No real email address: only the [CONTACT EMAIL] placeholder.
    expect(text).not.toMatch(/[\w.+-]+@[\w-]+\.[\w.]+/);
  });

  it("links every in-page contents entry to a section that exists", () => {
    const { container } = render(<Page />);
    const nav = container.querySelector('nav[aria-label="On this page"]');
    for (const anchor of nav ? Array.from(nav.querySelectorAll("a")) : []) {
      const id = anchor.getAttribute("href")!.slice(1);
      expect(container.querySelector(`section#${id}`), id).not.toBeNull();
    }
  });
});

describe("draft legal pages (owner decision Q8)", () => {
  it.each([PrivacyPage, TermsPage])("carry the contact placeholder", (Page) => {
    const { container } = render(<Page />);
    expect(container.textContent).toContain("[CONTACT EMAIL]");
    expect(container.textContent).toContain("operated by Card Pirate");
  });

  it("terms carry the governing-law placeholder", () => {
    const { container } = render(<TermsPage />);
    expect(container.textContent).toContain("[GOVERNING LAW]");
  });

  it("privacy discloses every provider the owner listed", () => {
    const { container } = render(<PrivacyPage />);
    const providers = within(container.querySelector("section#providers") as HTMLElement);
    for (const name of ["Vercel", "Railway", "Cloudflare R2", "Google", "Sentry"]) {
      expect(providers.getByText(name)).toBeInTheDocument();
    }
    expect(container.textContent).toContain("Vercel Web Analytics");
    expect(container.textContent).toMatch(/does not use cookies/);
  });
});

describe("methodology stays inside the documented method", () => {
  const text = () => render(<MethodologyPage />).container.textContent ?? "";

  it("states the rules docs/market_value.md and docs/market_index.md define", () => {
    const body = text();
    for (const rule of [
      "at least 3 sales in the last 30 days",
      "the median of their values",
      "never shown as 0%",
      "at least 80% of the priced value",
      "at least 300 compared versions",
      "27 and 28 September 2026",
      "is never part of the Market Index",
    ]) {
      expect(body.replace(/\s+/g, " ")).toContain(rule);
    }
  });

  it("names only the two approved sources", () => {
    expect(text()).not.toMatch(/Cardrush|Mercari|Cardmarket|eBay/i);
  });

  it("carries the no-new-claims source note for future editors", () => {
    const source = readFileSync(path.join(__dirname, "methodology/page.tsx"), "utf8");
    expect(source).toContain("docs/market_value.md");
  });
});

describe("Footer", () => {
  it("links all four info pages", () => {
    render(<Footer />);
    const nav = screen.getByRole("navigation", { name: "Site information" });
    expect(FOOTER_LINKS.map((link) => link.href)).toEqual(["/about", "/methodology", "/privacy", "/terms"]);
    for (const link of FOOTER_LINKS) {
      expect(within(nav).getByRole("link", { name: link.label })).toHaveAttribute("href", link.href);
    }
  });
});
