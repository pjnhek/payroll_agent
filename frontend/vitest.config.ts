import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// A separate config from vite.config.ts (not merged) so the production build's outDir /
// manifest / rollupOptions never leak into the test run, and vice versa.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    // Explicit imports (describe/it/expect from "vitest") over Jest-style implicit
    // globals -- one fewer ambient-type dependency and a clearer trace to where a
    // test's assertions come from.
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // No .test.tsx files exist yet -- the first component tests are added in later plans.
    // An empty suite is a legitimate pass here, not a failure to paper over.
    passWithNoTests: true,
  },
});
