import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { brand } from "@/lib/brand";

// Reads the root layout's source rather than importing the module directly
// - app/layout.tsx pulls in next/font/google (real font loading, not mocked
// in this project's vitest setup) and "server-only", neither of which are
// meant to execute inside a jsdom test. Asserting the *source* wires
// metadata from the centralized `brand` config (not a hardcoded string) is
// what this test actually needs to guard against regressing.
const layoutSource = readFileSync(path.resolve(__dirname, "./layout.tsx"), "utf-8");

describe("root layout metadata", () => {
  it("derives the default title from the centralized brand config, not a hardcoded string", () => {
    expect(layoutSource).toMatch(/title:\s*{\s*default:\s*brand\.metadataTitleDefault/);
    expect(layoutSource).not.toMatch(/OPTCG Price Tracker/);
  });

  it("derives the description from the centralized brand config", () => {
    expect(layoutSource).toMatch(/description:\s*brand\.metadataDescription/);
  });

  it("wires Open Graph metadata", () => {
    expect(layoutSource).toMatch(/openGraph:/);
  });

  it("brand's default metadata title contains the current product name", () => {
    expect(brand.metadataTitleDefault).toContain(brand.productName);
  });
});
