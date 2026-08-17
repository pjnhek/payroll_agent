import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The bundle is served through the existing `/static` mount (app/main.py:11) --
// no second mount, no new route. `outDir` sits outside the Vite root, so
// `emptyOutDir` must be explicit (Vite refuses to guess for an external dir).
// `manifest: true` writes .vite/manifest.json, which render_react_page() reads
// to resolve hashed asset filenames -- MANIFEST-SHAPE.md records its real shape.
// `rollupOptions.input` uses the named-object form (not a bare array) so each
// later page (Phase 23, Phase 24) adds one key without reshaping this config.
export default defineConfig({
  plugins: [react()],
  base: "/static/dist/",
  build: {
    outDir: "../app/static/dist",
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: {
        runs: "src/entries/runs.tsx",
      },
    },
  },
});
