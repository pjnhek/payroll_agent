---
schema_version: 1
open_count: 2
waived_count: 0
fixed_count: 0
total_count: 2
last_updated: 2026-08-18T01:10:02.919Z
---

# Broken Windows Ledger

> Cross-phase defect register. With `workflow.windows_enforce` enabled, `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 22 | unrun-verify | frontend/src/pages/RunsPage.tsx |  | LIST-04 real 375/374/376px narrow-viewport overflow measurement not performed -- no browser reachable from this worktree/sandbox and no Playwright/Puppeteer installed; left open per plan 22-06 instruction rather than claimed | open |  | 2026-08-17T23:45:08.596Z |  |
| 2 | 22 | deviation | tests/safety_mutation_registry.py |  | SAFETY-03's non-HTML-service-route guarantee could not be pinned: FastAPI 0.138 gives include_router-registered APIRoutes precedence over an interleaved Mount at every position tried, so test_no_html_on_service_routes.py never reds; the registry keeps only the mount-count pin (test_only_mount_is_static). | open |  | 2026-08-18T01:10:02.919Z |  |

````json
[
  {
    "id": 1,
    "kind": "unrun-verify",
    "phase": "22",
    "file": "frontend/src/pages/RunsPage.tsx",
    "line": null,
    "description": "LIST-04 real 375/374/376px narrow-viewport overflow measurement not performed -- no browser reachable from this worktree/sandbox and no Playwright/Puppeteer installed; left open per plan 22-06 instruction rather than claimed",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-17T23:45:08.596Z",
    "resolved_at": null
  },
  {
    "id": 2,
    "kind": "deviation",
    "phase": "22",
    "file": "tests/safety_mutation_registry.py",
    "line": null,
    "description": "SAFETY-03's non-HTML-service-route guarantee could not be pinned: FastAPI 0.138 gives include_router-registered APIRoutes precedence over an interleaved Mount at every position tried, so test_no_html_on_service_routes.py never reds; the registry keeps only the mount-count pin (test_only_mount_is_static).",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-18T01:10:02.919Z",
    "resolved_at": null
  }
]
````
