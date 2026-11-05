import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("next-auth/react", () => ({
  useSession: vi.fn(() => ({ data: null, status: "loading", update: async () => null })),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/prints/2615",
  useSearchParams: () => new URLSearchParams("callbackUrl=https://evil.example&next=https://evil.example"),
  useParams: () => ({ id: "2615" }),
}));

const { authMock, readPrint } = vi.hoisted(() => ({
  authMock: vi.fn(async (): Promise<{ sessionKind?: string; user?: { email?: string } } | null> => null),
  readPrint: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ auth: () => authMock() }));
vi.mock("@/lib/publicServer", () => ({ readPrint: (id: string) => readPrint(id) }));

import type { PrintDetail, PrintMarketIndexSourceValue } from "@/lib/prints";

import PrintPage from "./page";

function sourceValue(overrides: Partial<PrintMarketIndexSourceValue> & { source: string }): PrintMarketIndexSourceValue {
  return {
    reference_type: "retail_sell",
    evidence_type: "listing",
    value_jpy: null,
    observed_at: "2026-11-05T00:00:00Z",
    sample_size: null,
    stale: false,
    eligible: true,
    fallback_used: false,
    ineligible_reason: null,
    ...overrides,
  };
}

/** Enough of GET /prints/2615 for the first HTML. Prices are the point of the assertion. */
function sanji(): PrintDetail {
  return {
    card_print_id: 2615,
    canonical_card_id: 9,
    card_code: "OP06-119",
    name_en: "Sanji",
    name_jp: "サンジ",
    rarity: "SEC",
    canonical_rarity: "SEC",
    card_type: "Character",
    colors: ["Yellow"],
    language: "jp",
    treatment: null,
    release_product_code: "OP-06",
    original_set_code: "OP-06",
    official_asset_variant: "base",
    artwork_key: "abc",
    image_url: null,
    display_image: null,
    verification_status: "verified",
    siblings: [],
    market_index: {
      card_print_id: 2615,
      index_version: 1,
      index_value_jpy: 148000,
      calculation_method: "median_of_sources",
      source_count: 1,
      coverage_status: "limited",
      confidence: "medium",
      source_values: [
        sourceValue({ source: "yuyutei", value_jpy: 148000 }),
        sourceValue({ source: "snkrdunk", value_jpy: null, observed_at: null }),
      ],
      auxiliary_values: [],
      freshest_observation_at: "2026-11-05T00:00:00Z",
      stalest_eligible_source_at: "2026-11-05T00:00:00Z",
      stale_sources: [],
      calculated_at: "2026-11-05T00:00:00Z",
    },
  };
}

const EVIL_PROPS = {
  searchParams: Promise.resolve({
    callbackUrl: "https://evil.example",
    next: "https://evil.example/phish",
  }),
  headers: {
    host: "evil.example",
    "x-forwarded-host": "evil.example",
    "x-forwarded-proto": "https",
    "x-forwarded-uri": "https://evil.example/prints/1",
  },
};

async function htmlFor(id: string, extra: Record<string, unknown> = {}) {
  const element = await PrintPage({ params: Promise.resolve({ id }), ...extra } as never);
  return renderToStaticMarkup(element);
}

beforeEach(() => {
  authMock.mockReset();
  authMock.mockResolvedValue(null);
  readPrint.mockReset();
  readPrint.mockImplementation(async (id: string) => (id === "2615" ? sanji() : null));
});

describe("print page signed-out first HTML", () => {
  it("includes the sign-in link built from the route id while the session is still loading", async () => {
    const html = await htmlFor("2615", EVIL_PROPS);
    expect(html).toContain("Sign in to add it");
    expect(html).toContain('href="/sign-in?callbackUrl=%2Fprints%2F2615"');
    expect(html).not.toContain("evil.example");
    expect(html).toContain("￥148,000");
    expect(authMock).toHaveBeenCalled();
  });

  it("keeps that link out of a collector's first HTML and leaves the price", async () => {
    authMock.mockResolvedValue({ user: { email: "c@example.test" }, sessionKind: "collector" });
    const html = await htmlFor("2615", EVIL_PROPS);
    expect(html).not.toContain("Sign in to add it");
    expect(html).not.toContain("callbackUrl");
    expect(html).not.toContain("evil.example");
    expect(html).toContain("￥148,000");
  });

  it("still shows the link when the session cannot be read", async () => {
    authMock.mockRejectedValue(new Error("session unreadable"));
    const html = await htmlFor("2615");
    expect(html).toContain('href="/sign-in?callbackUrl=%2Fprints%2F2615"');
    expect(html).toContain("￥148,000");
  });

  it("does not build a callback from a route id that is not this page's own number", async () => {
    const html = await htmlFor("2615?callbackUrl=https://evil.example", EVIL_PROPS);
    expect(html).not.toContain("Sign in to add it");
    expect(html).not.toContain("evil.example");
    expect(html).not.toContain("callbackUrl");
  });
});
