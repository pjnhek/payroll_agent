---
schema_version: 1
open_count: 1
waived_count: 0
fixed_count: 0
total_count: 1
last_updated: 2026-08-17T23:45:08.596Z
---

# Broken Windows Ledger

> Cross-phase defect register. With `workflow.windows_enforce` enabled, `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 22 | unrun-verify | frontend/src/pages/RunsPage.tsx |  | LIST-04 real 375/374/376px narrow-viewport overflow measurement not performed -- no browser reachable from this worktree/sandbox and no Playwright/Puppeteer installed; left open per plan 22-06 instruction rather than claimed | open |  | 2026-08-17T23:45:08.596Z |  |

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
  }
]
````
