---
id: 260623-02
created: 2026-06-23
source: Phase 05 UAT discussion
resolves_phase:
priority: low
---

# Frontend progressive enhancement (NO build step) — post-demo polish

Considered during Phase 05 UAT and explicitly deferred. The dashboard is server-rendered
Jinja2 + vanilla JS by locked decision (CLAUDE.md "What NOT to Use" → no SPA/React/Vue;
the deploy story is a slim Docker image on Render free with fast cold start, so a Node/TS
build step is a deliberate non-goal).

If the dashboard ever needs to feel more "live" after the demo ships, the right move is
**progressive enhancement**, not a framework:

- **Live run status (replaces the `<meta http-equiv="refresh">` from UAT #3):** a ~30-line
  vanilla-JS `fetch('/runs/{id}/status')` poll that swaps the status badge in place while a
  run is in-flight, stopping on a terminal status. Much smoother than a full-page meta-refresh;
  still zero build step. Add a tiny `GET /runs/{id}/status` JSON endpoint.
- **Optional:** htmx or Alpine.js via CDN `<script>` (no bundler) if more interactivity is
  wanted — still honors the no-build constraint.

Do NOT introduce TypeScript / a bundler / an SPA: it adds a build artifact and cold-start cost
to the one phase (P6) whose job is to ship on a free tier, and the project's value story is the
deterministic payroll pipeline, not the UI. CSS styling (UI-SPEC tokens) carries the "looks
professional" bar; framework adds little here.

Trigger to revisit: only if the meta-refresh auto-reload feels janky in the live demo, do the
vanilla-JS status poll for that one interaction.
