import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
    // scripts/*.test.js is a separate suite that runs on Node's built-in
    // test runner (require("node:test")), not Vitest - only src/**/*.test.*
    // (React/Vitest) belongs here. proxy.test.ts is the one exception: it
    // tests apps/web/proxy.ts, which Next.js requires to live at the app
    // root (not under src/), so its test is co-located there too.
    include: ["src/**/*.{test,spec}.{ts,tsx}", "proxy.test.ts"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
