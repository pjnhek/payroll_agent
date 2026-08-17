# API Coverage — Phase 22

No external API integration: this phase converts one already-existing internal page (`/runs`) to a
React island rendered by the same FastAPI app, adds a build toolchain, two CI jobs and six guards;
the only HTTP surface it touches is the app's own `GET /runs/{run_id}/status`, which gains a
`response_model` declaration and no new behaviour, and no third-party API, SDK or service is called
from any code path this phase creates.

## Detector result at plan time

`node gsd-core/bin/lib/api-coverage.cjs --json` over the Phase 22 ROADMAP section returned
`{"detected": false, "signals": []}` on 2026-08-17. This declaration is recorded anyway so the
`api-coverage.verify-pre` seal gate has an explicit, reasoned artifact rather than re-deriving the
verdict from the finished plan bodies, which discuss endpoints, wiring and consumption in the
internal sense.

## What this phase does talk to

| Surface | External? | Note |
|---|---|---|
| `GET /runs/{run_id}/status` | No | The app's own route; gains an enforced response model (plan 22-07). Its wire body is asserted byte-identical before and after. |
| npm registry | Build-time only | 13 packages installed at pinned versions behind a blocking package-legitimacy checkpoint (plan 22-03, threat `T-22-SC`). Not a runtime API integration. |
| Render / Supabase / Resend / DeepSeek / Kimi | Untouched | The five untouchable directories (`app/pipeline`, `app/queue`, `app/db`, `app/llm`, `app/email`) are fenced by the CI diff-scope gate added in plan 22-05. |
