import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The bundle is served through the existing `/static` mount (app/main.py:11) --
// no second mount, no new route. `outDir` sits outside the Vite root, so
// `emptyOutDir` must be explicit (Vite refuses to guess for an external dir).
// `manifest: true` writes .vite/manifest.json, which render_react_page() reads
// to resolve hashed asset filenames -- MANIFEST-SHAPE.md records its real shape.
// `rollupOptions.input` uses the named-object form (not a bare array) so each
// later page (Phase 23, Phase 24) adds one key without reshaping this config.
//
// Dev server: forwards every non-Vite-served request path to a locally
// running uvicorn (`uv run uvicorn app.main:app --port 8000`), so the dev
// origin (this server) is the document origin an operator browses while
// developing. The entries below are enumerated from app/main.py's route
// table -- the seven APIRouters (health, webhook, runs, dashboard, demo,
// pump, ops) plus the static mount -- rather than a catch-all: a catch-all
// here would be the dev-side mirror of the catch-all route this phase's
// other guards exist to forbid, and it would make it impossible to tell
// which paths Vite itself is serving. `/` gets its own exact-match entry (a
// regex key -- Vite treats any key whose first character is `^` as a
// RegExp tested against the full URL, string keys otherwise match by
// prefix) because the dashboard's landing route is the bare root path; a
// plain string entry for "/" would prefix-match every request and become
// exactly the catch-all being avoided.
//
// No `hostRewrite`/`autoRewrite`/`protocolRewrite` is set on any entry --
// those are the only proxy options that rewrite a proxied response's
// `Location` header. Leaving them unset is what lets a 303 redirect the app
// emits (always a relative path, e.g. `/runs/{run_id}`) resolve naturally
// against the dev origin rather than against uvicorn's origin.
const BACKEND_TARGET = "http://localhost:8000";
const proxyToBackend = { target: BACKEND_TARGET, changeOrigin: false };

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
  server: {
    proxy: {
      "^/$": proxyToBackend,
      "/webhook": proxyToBackend,
      "/health": proxyToBackend,
      "/runs": proxyToBackend,
      "/demo": proxyToBackend,
      "/internal": proxyToBackend,
      "/ops": proxyToBackend,
      "/eval": proxyToBackend,
      "/static": proxyToBackend,
    },
  },
});
