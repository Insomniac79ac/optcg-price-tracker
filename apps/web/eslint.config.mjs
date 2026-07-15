import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Standalone CommonJS Node scripts (run directly via `node`, outside
    // Next.js's own module system) - not app source, so the React/TS
    // ruleset (e.g. no-require-imports) doesn't apply. See scripts/check-env.js.
    "scripts/**",
  ]),
]);

export default eslintConfig;
