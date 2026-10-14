// @vitest-environment node
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

// Collector v1 S5 (PLAN §D1): the browser never holds a bearer token. These
// are source-level guards; the built client bundle is scanned separately in
// the delivery evidence.

const SRC = path.resolve(__dirname, "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return sourceFiles(full);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) ? [full] : [];
  });
}

const files = sourceFiles(SRC).map((file) => ({ file: path.relative(SRC, file), text: readFileSync(file, "utf8") }));
const isClientModule = (text: string) => /^\s*["']use client["']/.test(text);

describe("no bearer token reaches the browser", () => {
  it("nothing reads or sets apiToken on the session any more", () => {
    const offenders = files.filter(({ text }) => /session[?!]?\.apiToken|apiToken\s*[:=]/.test(text)).map(({ file }) => file);
    expect(offenders).toEqual([]);
  });

  it("the session type no longer declares apiToken", () => {
    expect(readFileSync(path.join(SRC, "types/next-auth.d.ts"), "utf8")).not.toMatch(/apiToken/);
  });

  it("client modules and the browser API helpers never build an Authorization header", () => {
    const clientSide = files.filter(({ file, text }) => isClientModule(text) || file === "lib/api.ts");
    expect(clientSide.length).toBeGreaterThan(20);
    const offenders = clientSide.filter(({ text }) => /Authorization["']?\s*:|Bearer \$\{|getSession\(/.test(text)).map(({ file }) => file);
    expect(offenders).toEqual([]);
  });

  it("only server-only modules sign JWTs, and only collectorApi signs user API tokens", () => {
    const minters = files.filter(({ text }) => /new SignJWT\(/.test(text));
    expect(minters.length).toBeGreaterThan(0);
    for (const { file, text } of minters) expect(text, file).toMatch(/^import "server-only";/m);
    const userTokenMinters = minters.filter(({ text }) => /API_JWT_SECRET/.test(text)).map(({ file }) => file);
    expect(userTokenMinters).toEqual(["lib/collectorApi.ts"]);
  });
});
