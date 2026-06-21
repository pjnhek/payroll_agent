<!-- GSD:project-start source:PROJECT.md -->
## Project

**Payroll Agent**

An email-driven system that automates the weekly payroll intake the builder used to do by hand as a tax analyst. A client business emails its employees' hours; an LLM-driven pipeline reads the email, reconciles the submitted names against the business's roster, decides whether it can process the run or must ask the client a clarifying question, computes the payroll (gross, FICA, real IRS Pub 15-T federal withholding), and routes the result to a single human operator for one approval before the confirmation goes back to the client. Built end-to-end on a free stack so it runs and demos cleanly.

The narrative for the writeup: the manual payroll process from the builder's accounting days, rebuilt as an agentic pipeline — the LLM does the reading, name matching, and decisioning; a human approves only the final payroll before it reaches the client. **Primary audience: hiring managers / recruiters.** Optimize for *visibly works end to end* > *clean 60–90s demo* > *a real, legible eval chart*.

**Core Value:** A messy real-world payroll email goes in; a correct, human-approved payroll comes out — and every judgment call (name match, process-vs-clarify) is made by the LLM but **gated by code so a low-confidence match can never reach a real payroll calculation.** If that gated decision flow works, everything else is plumbing.

### Constraints

- **Tech stack**: FastAPI in Docker on a Render free web service; Supabase Postgres for all state — chosen to run end-to-end on a free tier and demo cleanly.
- **Models**: Kimi and DeepSeek via OpenAI-compatible clients, non-reasoning chat variants — latency, and the task isn't multi-step reasoning. Model IDs are **config-driven** (env vars + `.env.example` placeholders); real strings pasted from the consoles later. (Open decision #5, resolved.)
- **Email**: a gateway catches inbound mail and posts to the app and sends outbound; threading is anchored on the RFC `Message-ID` header. Written gateway-agnostic behind one small interface.
- **Orchestration**: plain Python workflow, fixed path, state in Postgres — deliberately not an autonomous agent and not LangGraph.
- **Human-in-the-loop**: exactly one gate (operator approves computed payroll before send). Everything before it is automated.
- **Structured LLM calls**: JSON mode + Pydantic schema, one retry on parse failure.
- **Confidence threshold**: name-reconciliation auto-clarify starts at **0.8**, tuned against the eval. (Open decision #6, resolved.)
- **Audience**: hiring-manager / recruiter facing — bias effort toward a rock-solid end-to-end happy-path-plus-name-mismatch flow and a real, legible eval chart over eval exotica.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Recommended Stack
### Core Technologies
| Technology | Version (Jun 2026) | Purpose | Why Recommended (for THIS use case) |
|------------|--------------------|---------|-------------------------------------|
| **Python** | 3.12 (pin in Docker) | Runtime | 3.12 is the sweet spot: every library below supports it; avoids the 3.13/3.14 wheel-availability edge cases for native deps. Pin via `python:3.12-slim` base image. |
| **FastAPI** | `0.138.0` | Webhook server + dashboard routes | Async webhook + Pydantic-native request validation in one framework. The whole app is "receive JSON, validate, run pipeline, render a few pages" — FastAPI does exactly that with no extra glue. `requires_python >=3.10`. |
| **Pydantic** | `2.13.4` (v2) | LLM JSON schemas, webhook payload validation, settings | v2 is the validation layer for *both* the inbound webhook payloads and the LLM structured outputs. `model_validate_json()` is the retry-on-parse-failure primitive (see LLM section). |
| **pydantic-settings** | `2.14.2` | Env-var config (model IDs, base URLs, keys, DB URL) | The model-routing config is env-driven by design. `BaseSettings` loads `.env` and validates it at startup, so a missing key fails fast instead of mid-pipeline. |
| **uvicorn** (standard) | `0.49.0` | ASGI server | `uvicorn[standard]` (uvloop + httptools). Render runs it as the container CMD bound to `0.0.0.0:$PORT`. |
| **openai** (openai-python) | `2.43.0` | The ONE OpenAI-compatible client for Kimi + DeepSeek | One client class, `base_url`/`api_key`/`model` swapped per task tier. `requires_python >=3.9`. **See the v2 + JSON-mode gotchas below — they change how you should call it.** |
| **psycopg** (psycopg3) | `3.3.4` | Direct Postgres driver for transactional state + HITL checkpoint | Real transactions, `RETURNING`, row locking, and a connection pool. This is the correct tool for a system whose entire premise is "Postgres IS the state machine and the HITL pause." See DB section for why this beats `supabase-py` here. |
### Supporting Libraries
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **psycopg[binary,pool]** | `3.3.4` | Pooled DB access | Use the `[binary]` extra so no local libpq build is needed in the slim image; `[pool]` for `ConnectionPool`. One pool created at app startup, reused across requests. |
| **reportlab** | `5.0.0` | On-demand paystub PDF generation | Pure-Python, **BSD-licensed** (verified — the open-source Toolkit, not the commercial PLUS product), **zero system/native dependencies**. Generates a PDF to an in-memory `BytesIO` and streams it back — perfect for Render's ephemeral FS where nothing is written to disk. Supports Python 3.10–3.14. |
| **Jinja2** | `3.1.6` | Server-rendered dashboard templates | FastAPI's `Jinja2Templates`. The dashboard is ~4 pages (runs list, run detail, eval view, demo button) — Jinja2 + a sprinkle of vanilla JS (or htmx) is the right weight. No SPA, no build step. |
| **httpx** | `0.28.1` | (transitive via openai) + any direct gateway calls | Already pulled in by `openai`. Use it directly only for the outbound email-gateway POST if the gateway is a plain HTTP endpoint. |
| **python-multipart** | latest | Form POSTs from the dashboard | Needed for the Approve/Reject form actions and the "Send test email" button if they POST as HTML forms. |
### Development / Reference Libraries (NOT runtime dependencies)
| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| **python-taxes** | `0.7.0` (PyPI, MIT) | **Reference implementation** of Pub 15-T §1 Percentage Method + FICA | Implements the same Worksheet 1A percentage method this project needs, in Pydantic, depends only on pydantic. **Covers tax years 2023–2025 only (2025 partial)** — so it is NOT a drop-in for a 2026 calculation, but it is the single best Python cross-check for your own implementation. Mine it for structure and unit-test expectations; do not depend on it for the 2026 numbers. |
| **IRS-Public/tax-withholding-estimator** | GitHub (official, Feb 2026) | Official IRS open-source withholding logic | Authoritative reference for *how* the IRS models withholding. Heavy and disclaimer-laden; use as a correctness oracle, not a dependency. |
| **pytest** | latest | The Pub 15-T engine MUST be the most-tested unit in the repo | The calculation is the highest-bug-risk component and is explicitly guarded by the reconciliation check. Table-driven tests with IRS-published example figures per filing status. |
| **ruff** | latest | Lint + format | One tool, fast, no config debate. |
## Installation

**Environment + dependencies are managed with [uv](https://docs.astral.sh/uv/).** Source of truth: `pyproject.toml` (`[project.dependencies]` for runtime, `[dependency-groups].dev` for pytest/ruff) + the committed `uv.lock`. Python is pinned to 3.12 via `.python-version` (matches the `python:3.12-slim` Docker target). There is no `requirements.txt`.

```bash
uv sync            # create/refresh .venv (3.12), install runtime + dev, honor uv.lock
uv sync --no-dev   # runtime deps only (what the Docker image installs)
uv run pytest -q   # run the suite inside the managed venv
uv add <pkg>       # add a runtime dep (updates pyproject + uv.lock)
uv add --dev <pkg> # add a dev/eval-only dep
```

**Docker (Phase 6):** export a pinned, hash-free requirements file from the lock at build time — `uv export --no-dev --no-emit-project --no-hashes -o requirements.txt` — or use uv directly in the Dockerfile. Do NOT hand-maintain a requirements.txt; the lock is authoritative.
## Prescriptive Usage Patterns (the load-bearing part)
### 1. FastAPI + Pydantic v2 — webhook + structured output
### 2. OpenAI-compatible client against Kimi + DeepSeek — JSON mode + retry
- **DeepSeek `json_object` requires the word "json" in the prompt + an example shape**, or it silently won't enter JSON mode. It can also occasionally return empty content — the retry loop covers this.
- **`json_object` guarantees valid JSON syntax, NOT your schema.** Field-level correctness comes from `model_validate_json()` on *your* Pydantic model. This is by design and is exactly why the project pairs JSON mode with a Pydantic schema.
- **`temperature=0`** for extraction/decision (deterministic, eval-stable). The drafting tier (cheap model, email text) can run warmer.
- Keep `max_tokens` high enough that the JSON object can't be cut off mid-stream.
| Provider | Base URL (verified Jun 2026) | Non-reasoning chat family to target | Flag |
|----------|------------------------------|-------------------------------------|------|
| **DeepSeek** | `https://api.deepseek.com` | `deepseek-v4-flash` run in its **non-thinking** mode is the current non-reasoning chat path. The legacy IDs **`deepseek-chat` / `deepseek-reasoner` are deprecated 2026/07/24** — do not build on them. `deepseek-v4-pro` is a reasoning model — **avoid** (locked: non-reasoning only). | ⚠️ CONFIRM exact ID + how non-thinking mode is selected, against the DeepSeek console/pricing page. |
| **Moonshot / Kimi** | `https://api.moonshot.ai/v1` (note: `platform.moonshot.ai` now redirects to `platform.kimi.ai` for docs) | `moonshot-v1-8k` / `-32k` / `-128k` / `-auto` are the **plain non-reasoning chat** models. The newer `kimi-k2.5 / k2.6 / k2.7*` families are **reasoning-capable** (thinking parameter) — **avoid** for the locked non-reasoning constraint, or explicitly disable thinking. | ⚠️ CONFIRM exact IDs against the Kimi/Moonshot console. The "Kimi K2" in the build plan has since iterated to k2.5+. |
### 3. Supabase Postgres from Python — `psycopg` (NOT `supabase-py`) + `schema.sql`
### 4. PDF generation — `reportlab` (on-demand, in-memory)
- **WeasyPrint** `69.0` renders HTML/CSS to PDF beautifully **but pulls heavy native deps** (Pango, cairo, GDK-PixBuf, harfbuzz via system libraries). On a slim Docker image that means a long `apt-get` layer and a fatter image and slower cold starts — directly at odds with Render free constraints. Only choose it if you must reuse HTML/CSS layout, which you don't.
- **fpdf2** `2.8.7` is also pure-Python and lighter than reportlab — a legitimate fallback if you want the smallest dependency. reportlab wins on table/layout maturity for a tabular paystub and is the more battle-tested default; pick fpdf2 only if you specifically want minimal footprint over layout features.
### 5. FICA constants — look up at runtime, don't hardcode a stale year
- **Social Security (OASDI) wage base = $184,500** (up from $176,100 in 2025). SS rate **6.2%**, employee max = **$11,439**.
- **Medicare = 1.45%, no wage cap.** Additional Medicare **0.9%** on wages over **$200,000** (single) / **$250,000** (MFJ) / **$125,000** (MFS). *(The 0.9% surtax is likely out of scope for the demo's wage levels but the threshold is documented if needed.)*
### 6. IRS Pub 15-T percentage method — the highest-bug-risk unit
- **`python-taxes` (PyPI 0.7.0, MIT)** — implements this exact §1 percentage method in Pydantic for 2023–2025. **Best Python reference**, but does not yet ship 2026 tables — use its *structure* and port the 2026 bracket/constant tables yourself from the IRS PDF.
- **IRS-Public/tax-withholding-estimator** (official, open-sourced Feb 2026) — authoritative correctness oracle.
- Build the engine as an **isolated, pure-function module** keyed by `tax_year`, with the bracket tables and the per-status worksheet constants for 2026 **transcribed directly from `https://www.irs.gov/pub/irs-pdf/p15t.pdf` (2026 edition) and unit-tested against the IRS's own worked examples** in that PDF, per filing status, both the standard and the Step-2-checkbox schedules.
- ⚠️ **Do NOT hardcode the 2026 bracket numbers from this research doc — transcribe them from the live 2026 Pub 15-T PDF.** The 2026 edition incorporates OBBBA changes; any number remembered from training data is stale. Flag: **confirm all 2026 bracket rows + the Step-1 standard amounts against the official 2026 PDF.**
- This unit is the one explicitly guarded by the run's **reconciliation check** (net + taxes + deductions ties to the run total) — keep that check as the runtime backstop. Confidence on the *method/structure*: HIGH. Confidence on any specific 2026 *numbers*: **LOW until transcribed from the PDF.**
### 7. Dashboard — FastAPI + Jinja2, no SPA
### 8. Render free web service — Docker specifics
- **Spin-down after 15 minutes** with no inbound traffic; **cold start ≈ under 1 minute** (Render shows a loading page while waking).
- **Only inbound HTTP/WebSocket traffic keeps it awake** — outbound cron or internal loops do NOT. This is exactly why the project is webhook-driven, not polling, and why the **GitHub Actions keep-alive must ping an HTTP endpoint** (the Render service URL and/or Supabase), not rely on the app pinging itself.
- **750 free instance-hours / month** per workspace; over that, free services suspend until next month. A single demo service is well within this.
- **Ephemeral filesystem** — confirmed; nothing on disk survives a restart/spin-down. This is why PDFs are generated in-memory on demand and all state is in Supabase.
# Render injects $PORT (default 10000). MUST bind 0.0.0.0 and read $PORT.
- **Bind to `0.0.0.0` and the `$PORT` env var** (default `10000`). Binding to `127.0.0.1` or a hardcoded port = failed deploy / 502. This is the #1 Render Docker gotcha.
- `reportlab`/`psycopg[binary]` need **no `apt-get`** layer — keeps the image slim and cold starts fast. (If you ever swap to WeasyPrint you'd need a heavy system-deps layer — another reason not to.)
- Keep-alive workflow: GitHub Actions `schedule:` cron a couple times/week issuing a cheap `GET` to the Render URL (wakes the service) and a trivial query to Supabase (keeps the free Postgres project from pausing). Eval workflow: `on: push`.
## Alternatives Considered
| Recommended | Alternative | When the alternative would win |
|-------------|-------------|--------------------------------|
| `psycopg` (psycopg3) | `asyncpg` (`0.31.0`) | If the app were heavily async-DB-bound and never needed psycopg's sync ergonomics. For a low-traffic webhook app with transactional gates, psycopg3's clearer transaction API + binary wheel is the better fit. Both are correct; psycopg3 is the more general default. |
| `psycopg` (direct SQL) | `supabase-py` (`2.31.0`) | If you needed Supabase Auth/Storage/Realtime helpers. This project uses none of them (no bucket, no auth), and PostgREST gives no real transactions — so direct SQL wins for the HITL state machine. |
| `reportlab` | `fpdf2` (`2.8.7`) | If you want the absolute smallest pure-Python footprint over table-layout maturity. Both are dependency-light; pick fpdf2 only to shave the image further. |
| `reportlab` | `WeasyPrint` (`69.0`) | Only if you must author paystubs as HTML/CSS. Costs heavy native system deps + a fatter slim image + slower cold start — bad trade on Render free. |
| `schema.sql` | Supabase CLI migrations / Alembic | If the schema starts churning across multiple environments with rollback needs. Over-engineering for a single-author greenfield demo. |
| Jinja2 + vanilla JS/htmx | Any SPA (React/Vue/Svelte) | If the dashboard became a rich interactive product. For 4 no-auth demo pages, an SPA + build step is pure overhead. |
| `response_format={"type":"json_object"}` + manual `model_validate_json` | `client.chat.completions.parse()` (strict `json_schema`) | `.parse()` is *nicer* but requires server-side `json_schema` support. **DeepSeek lacks it**, so the strict helper breaks the "one provider-agnostic client" goal. Only use `.parse()` if you pin to a provider that guarantees strict structured outputs. |
## What NOT to Use
| Avoid | Why (specific to this project) | Use Instead |
|-------|--------------------------------|-------------|
| `client.chat.completions.parse()` / Pydantic-as-`response_format` | Sends strict `json_schema`; **DeepSeek only supports `json_object`** — strict helper fails against half your providers. | `response_format={"type":"json_object"}` + `Model.model_validate_json()` + 1 retry. |
| Legacy DeepSeek IDs `deepseek-chat` / `deepseek-reasoner` | **Deprecated 2026/07/24.** Building on them is a time bomb. | Confirm the current `deepseek-v4-flash` (non-thinking) ID from the console; keep it in env. |
| Reasoning model variants (`deepseek-v4-pro`, `kimi-k2.x` thinking) | Locked constraint: non-reasoning only — they add latency for a non-multi-step task. | `deepseek-v4-flash` non-thinking / `moonshot-v1-*`. Confirm IDs. |
| Direct Supabase host `db.<ref>.supabase.co` | **IPv6-only on free tier; Render is IPv4-only** → connection failures. | Supavisor **pooler** host `...pooler.supabase.com`, transaction mode port **6543**. |
| `supabase-py` for app state | No real transactions / row locks; it's a REST wrapper. The whole app is a transactional state machine. | `psycopg` with `conn.transaction()` + `FOR UPDATE`. |
| WeasyPrint on a slim image | Heavy native deps (Pango/cairo/etc.) bloat the image + slow Render cold starts. | `reportlab` (pure Python, BSD, zero system deps). |
| Hardcoding the SS wage base / Pub 15-T brackets from memory | 2026 figures changed (wage base $176,100 → $184,500; Pub 15-T includes OBBBA). Stale numbers = silently wrong paystubs. | Year-keyed constants transcribed from SSA/IRS, with `TAX_YEAR` env + cited source URLs. |
| LangGraph / autonomous agent loop | Locked out: the path is fixed and code-gated; Postgres is the checkpoint. An agent framework hides the very control flow this project is showcasing. | Plain Python functions per stage, status column drives the state machine. |
| A Supabase Storage bucket for PDFs | Locked out: nothing to persist; Render FS is ephemeral. | Generate PDFs in-memory on demand (`BytesIO` → `StreamingResponse`). |
| A polling loop to drive the pipeline | Render free only stays awake on inbound HTTP; a loop sleeps with the service. | Webhook-driven kickoff + GitHub Actions cron keep-alive. |
## Stack Patterns by Variant
- Either way, the app only sees `POST /webhook/inbound` with the JSON shape in pattern #1. Keep one `EmailGateway` interface (`parse_inbound`, `send_outbound`) so the provider is wired last and swappable — exactly the locked, fixture-first design.
- The `state_withholding` column is already nullable; add a flat-rate or per-state strategy behind the same calc module. Don't build it now.
- Hit the Render URL ~30–60s before recording to pre-warm; the GitHub Actions keep-alive reduces (not eliminates) cold starts. Don't add a paid plan for a demo.
## Version Compatibility
| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `fastapi 0.138.0` | `pydantic 2.13.4` | FastAPI is Pydantic-v2-native; this is the intended pairing. |
| `pydantic 2.13.4` | `python-taxes 0.7.0` (`pydantic >=2.11.3,<3`) | The reference lib is compatible with your Pydantic v2 pin. |
| `openai 2.43.0` | `httpx 0.28.1` | openai v2 bundles httpx as a transitive dep; don't pin httpx against it. |
| `psycopg[binary] 3.3.4` | `python:3.12-slim` | Binary wheel avoids needing libpq/build tools in the image. |
| `reportlab 5.0.0` | Python 3.10–3.14 | BSD Toolkit; no native deps. Use 3.12 for broadest wheel coverage. |
| Render `$PORT` (10000) | `uvicorn --host 0.0.0.0 --port $PORT` | Must read `$PORT`; binding elsewhere fails the deploy. |
| Supabase pooler 6543 (transaction) | `psycopg` pool | IPv4-reachable from Render; transaction mode suits churny short-lived connections. |
## Confidence Summary & Flags to Confirm
| Item | Confidence | Action |
|------|------------|--------|
| Library versions (FastAPI/Pydantic/openai/psycopg/reportlab/etc.) | HIGH | Verified against PyPI JSON API, Jun 20 2026. |
| openai v2 JSON-mode pattern + DeepSeek lacking `json_schema` | HIGH | Verified against DeepSeek + Moonshot official docs. |
| Render free behavior (15-min sleep, $PORT, IPv4, ephemeral FS, 750 hrs) | HIGH | Verified against Render docs. |
| Supabase pooler (IPv4) + transaction mode 6543 requirement | HIGH | Verified against Supabase docs; the IPv4/IPv6 mismatch is the key gotcha. |
| 2026 SS wage base = **$184,500**, Medicare 1.45% | HIGH | SSA COLA + multiple payroll sources agree. **Re-confirm against ssa.gov/oact/cola/cbb.html before shipping.** |
| **Exact LLM model IDs per tier** | ⚠️ MEDIUM / CONFIRM | Families verified (DeepSeek v4-flash non-thinking; moonshot-v1-*); **exact IDs + how to force non-thinking mode must be pasted from the DeepSeek & Kimi consoles.** Legacy `deepseek-chat` deprecates 2026/07/24. |
| **Pub 15-T 2026 bracket tables + Step-1 constants** | ⚠️ LOW / CONFIRM | Method/structure HIGH; the actual 2026 numbers (OBBBA-affected) **must be transcribed from irs.gov/pub/irs-pdf/p15t.pdf and unit-tested** — never from memory. |
## Sources
- PyPI JSON API (`pypi.org/pypi/<pkg>/json`) — fastapi 0.138.0, pydantic 2.13.4, openai 2.43.0, supabase 2.31.0, psycopg 3.3.4, asyncpg 0.31.0, reportlab 5.0.0 (BSD), fpdf2 2.8.7, jinja2 3.1.6, uvicorn 0.49.0, pydantic-settings 2.14.2, python-taxes 0.7.0 (MIT). Verified Jun 20 2026. **HIGH.**
- DeepSeek API docs — `api-docs.deepseek.com/guides/json_mode` (json_object only; needs "json" + example; can return empty content) and pricing/models (deepseek-v4-flash non-thinking; deepseek-v4-pro reasoning; deepseek-chat/-reasoner deprecate 2026/07/24). **HIGH.**
- Moonshot/Kimi API docs — `platform.kimi.ai/docs/api/chat` (base_url `https://api.moonshot.ai/v1`; moonshot-v1-* non-reasoning; kimi-k2.5/2.6/2.7 reasoning-capable; json_object + json_schema). **HIGH.**
- openai-python — `github.com/openai/openai-python` README + helpers.md (`.parse()` sends strict json_schema; custom base_url support). **HIGH.**
- IRS Pub 15-T (2026) — `irs.gov/publications/p15t` + `irs.gov/pub/irs-pdf/p15t.pdf` (Worksheet 1A percentage method, standard vs Step-2-checkbox schedules, 3 filing statuses, 2020+ W-4 fields). PayrollOrg note: 2026 edition includes OBBBA. **Method HIGH; 2026 numbers must be transcribed.**
- IRS Topic 751 — `irs.gov/taxtopics/tc751` (FICA rates). **HIGH.**
- SSA COLA 2026 factsheet + Contribution & Benefit Base — `ssa.gov/news/en/cola/factsheets/2026.html`, `ssa.gov/oact/cola/cbb.html` (wage base $184,500; cbb.html returns 403 to non-browser fetch — cite, don't scrape at runtime). Corroborated by Mercer, Paycor, OnPay. **HIGH.**
- Render docs — `render.com/docs/free`, `/docs/web-services`, `/docs/environment-variables` ($PORT=10000, 0.0.0.0 bind, 15-min sleep, ~1-min cold start, 750 hrs, ephemeral FS, inbound-only keep-awake). **HIGH.**
- Supabase docs — Supavisor/connection terminology + connecting-to-postgres (transaction mode 6543, session 5432, pooler host for IPv4, session-on-6543 deprecated Feb 2025). **HIGH.**
- Reference impls — `pypi.org/project/python-taxes` (Pub 15-T §1, 2023–2025, MIT), `github.com/IRS-Public/tax-withholding-estimator` (official, Feb 2026). **HIGH as references.**
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
