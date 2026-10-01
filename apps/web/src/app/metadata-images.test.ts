import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

describe("static metadata images", () => {
  it.each([
    ["apple-icon", 180, 180, "919a6718810dbb65a8e729e72a6a02632599cdc1eddd549da332675bac9f27d3"],
  ] as const)("%s preserves the original rendered PNG and dimensions", (name, width, height, sha256) => {
    // Golden hashes of the original Next/ImageResponse output, captured before
    // removing the generators. This detects any visual/content change.
    const png = readFileSync(path.join(__dirname, `${name}.png`));
    expect(png.subarray(0, 8)).toEqual(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
    expect(png.readUInt32BE(16)).toBe(width);
    expect(png.readUInt32BE(20)).toBe(height);
    expect(createHash("sha256").update(png).digest("hex")).toBe(sha256);
    expect(existsSync(path.join(__dirname, `${name}.tsx`))).toBe(false);
  });
});
