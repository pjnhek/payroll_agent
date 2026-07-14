# Stack Research

**Domain:** LLM-driven email-to-payroll automation pipeline (FastAPI + Supabase + OpenAI-compatible LLMs, free-tier, ephemeral FS, HITL state)
**Researched:** 2026-06-20
**Confidence:** HIGH for versions/hosting/DB/LLM-client mechanics (verified against PyPI + official docs, June 2026); MEDIUM-with-flags for the exact LLM model IDs and the IRS Pub 15-T 2026 numeric tables (must be confirmed against consoles / the live PDF — see flags below).

> This is a **prescriptive deepening** of an already-LOCKED stack. It does not relitigate decisions. For each locked component it pins a current version, the idiomatic usage pattern for *this* use case, and the known gotchas. Where a value cannot be safely hardcoded (model IDs, 2026 tax constants), it is flagged "confirm against source" rather than invented.

---

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

---

## Installation

```bash
# Core (requirements.txt)
pip install \
  "fastapi==0.138.0" \
  "uvicorn[standard]==0.49.0" \
  "pydantic==2.13.4" \
  "pydantic-settings==2.14.2" \
  "openai==2.43.0" \
  "psycopg[binary,pool]==3.3.4" \
  "reportlab==5.0.0" \
  "jinja2==3.1.6" \
  "python-multipart"

# Dev / eval only (not in the runtime image)
pip install pytest ruff python-taxes
```

---

## Prescriptive Usage Patterns (the load-bearing part)

### 1. FastAPI + Pydantic v2 — webhook + structured output

**Webhook pattern.** Define the inbound payload as a Pydantic v2 model and take it as the handler argument; FastAPI validates and 422s on malformed input automatically. This is also exactly how fixture-first development works — POST the same JSON shape whether it comes from a fixture file or the real gateway.

```python
from fastapi import FastAPI
from pydantic import BaseModel, Field

class InboundEmail(BaseModel):
    message_id: str = Field(alias="Message-ID")
    in_reply_to: str | None = Field(default=None, alias="In-Reply-To")
    references: str | None = Field(default=None, alias="References")
    from_addr: str
    to_addr: str
    subject: str
    body_text: str
    model_config = {"populate_by_name": True}   # accept either alias or field name

app = FastAPI()

@app.post("/webhook/inbound")
async def inbound(email: InboundEmail):
    # 1. store row in email_messages, 2. route by header, 3. kick the pipeline
    ...
```

**Gotcha (Pydantic v2):** it's `model_config = {...}` / `ConfigDict`, `model_validate_json()`, `model_dump()` — not the v1 `class Config` / `.parse_raw()` / `.dict()`. The build plan's "Pydantic schema" everywhere means v2 idioms. Field aliases with `populate_by_name=True` let one model accept both the RFC header casing (`Message-ID`) and snake_case fixture keys.

**Pipeline kickoff:** the webhook should persist state and return fast (Render's free tier sleeps and cold-starts; long synchronous LLM chains risk gateway timeouts). Run the pipeline in a `BackgroundTask` or as an awaited call that the gateway tolerates — but **the state machine lives in Postgres**, so even if the process is killed mid-run, status is recoverable. (Note: Render free has no background workers, and only inbound HTTP keeps it awake — so a true async worker queue is out of scope; an in-request `BackgroundTasks` that finishes within the request window is the pragmatic fit.)

### 2. OpenAI-compatible client against Kimi + DeepSeek — JSON mode + retry

**One client, swapped per tier.** Instantiate `OpenAI(base_url=..., api_key=...)` from env config per task. openai `2.43.0` fully supports custom `base_url` + arbitrary `model` strings.

```python
from openai import OpenAI
client = OpenAI(base_url=settings.extract_base_url, api_key=settings.extract_api_key)
```

**CRITICAL gotcha — do NOT use `client.chat.completions.parse()` here.** The `.parse()` helper (and passing a Pydantic class as `response_format`) sends a **strict `json_schema`** response format. **DeepSeek does not support `json_schema`** — its API only documents `response_format` types `text` and `json_object` (verified, DeepSeek API docs, Jun 2026). Moonshot/Kimi *does* document `json_schema`, but to keep ONE provider-agnostic code path you must target the lowest common denominator.

**The portable, prescriptive pattern** (matches the locked "JSON mode + Pydantic + retry once"):

```python
import json
from pydantic import BaseModel, ValidationError

def call_structured(client, model: str, system: str, user: str, schema: type[BaseModel]):
    messages = [
        # DeepSeek REQUIRES the literal word "json" in the prompt AND an example
        # of the desired shape, or it will not honor json_object mode.
        {"role": "system", "content": system + "\nReturn a single JSON object."},
        {"role": "user", "content": user},
    ]
    for attempt in range(2):  # original + one retry
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=2048,  # set generously; truncated JSON is a known failure mode
        )
        content = resp.choices[0].message.content
        try:
            return schema.model_validate_json(content)
        except (ValidationError, json.JSONDecodeError) as e:
            if attempt == 0:
                messages.append({"role": "assistant", "content": content or ""})
                messages.append({"role": "user",
                    "content": f"That did not match the schema ({e}). Re-emit valid JSON only."})
                continue
            raise
```

Gotchas, all verified against current provider docs (Jun 2026):
- **DeepSeek `json_object` requires the word "json" in the prompt + an example shape**, or it silently won't enter JSON mode. It can also occasionally return empty content — the retry loop covers this.
- **`json_object` guarantees valid JSON syntax, NOT your schema.** Field-level correctness comes from `model_validate_json()` on *your* Pydantic model. This is by design and is exactly why the project pairs JSON mode with a Pydantic schema.
- **`temperature=0`** for extraction/decision (deterministic, eval-stable). The drafting tier (cheap model, email text) can run warmer.
- Keep `max_tokens` high enough that the JSON object can't be cut off mid-stream.

**Model families — CONFIRM against the consoles (do NOT hardcode from this doc).** The model landscape moved *past* the build plan's "DeepSeek V3 / Kimi K2" since those names were written:

| Provider | Base URL (verified Jun 2026) | Non-reasoning chat family to target | Flag |
|----------|------------------------------|-------------------------------------|------|
| **DeepSeek** | `https://api.deepseek.com` | `deepseek-v4-flash` run in its **non-thinking** mode is the current non-reasoning chat path. The legacy IDs **`deepseek-chat` / `deepseek-reasoner` are deprecated 2026/07/24** — do not build on them. `deepseek-v4-pro` is a reasoning model — **avoid** (locked: non-reasoning only). | ⚠️ CONFIRM exact ID + how non-thinking mode is selected, against the DeepSeek console/pricing page. |
| **Moonshot / Kimi** | `https://api.moonshot.ai/v1` (note: `platform.moonshot.ai` now redirects to `platform.kimi.ai` for docs) | `moonshot-v1-8k` / `-32k` / `-128k` / `-auto` are the **plain non-reasoning chat** models. The newer `kimi-k2.5 / k2.6 / k2.7*` families are **reasoning-capable** (thinking parameter) — **avoid** for the locked non-reasoning constraint, or explicitly disable thinking. | ⚠️ CONFIRM exact IDs against the Kimi/Moonshot console. The "Kimi K2" in the build plan has since iterated to k2.5+. |

This is precisely why the project's **config-driven, `.env.example`-placeholder** approach is correct: the builder pastes the real, current IDs from each console into env vars; the code never bakes them in. Map them to tiers via env: `EXTRACT_MODEL` (stronger), `RECONCILE_MODEL` (strong/mid), `DECIDE_MODEL` (mid), `DRAFT_MODEL` (cheap), each with its own `*_BASE_URL` and `*_API_KEY`.

### 3. Supabase Postgres from Python — `psycopg` (NOT `supabase-py`) + `schema.sql`

**Driver choice: use `psycopg` (psycopg3) directly.** The locked premise is "Postgres holds ALL state and IS the HITL checkpoint." That means: atomic status transitions (`received → … → awaiting_approval → approved → sent`), `SELECT ... FOR UPDATE` so two requests can't double-approve a run, multi-row writes (a run + its `paystub_line_items`) in one transaction, and the reconciliation check reading a consistent snapshot. `supabase-py` is a thin wrapper over PostgREST — it speaks HTTP/REST, gives you no real transactions, no row locking, and no `RETURNING` semantics across statements. For a transactional state machine it is the wrong layer. `psycopg3` gives genuine `with conn.transaction():` blocks and a connection pool.

```python
from psycopg_pool import ConnectionPool
pool = ConnectionPool(settings.database_url, min_size=1, max_size=5, open=True)

def approve_run(run_id: str) -> bool:
    with pool.connection() as conn, conn.transaction():
        row = conn.execute(
            "SELECT status FROM payroll_runs WHERE id = %s FOR UPDATE", (run_id,)
        ).fetchone()
        if row is None or row[0] != "awaiting_approval":
            return False                      # idempotent gate; no double-send
        conn.execute("UPDATE payroll_runs SET status='approved', updated_at=now() "
                     "WHERE id=%s", (run_id,))
    return True
```

**CRITICAL connection gotcha (Render → Supabase free tier).** Render's outbound networking is **IPv4-only**, but the **direct** Supabase host `db.<ref>.supabase.co` is **IPv6-only** on the free plan. You MUST connect through the **Supavisor pooler** host (`<...>.pooler.supabase.com`), which is IPv4-reachable. For this short-lived, webhook-driven app use **transaction mode on port 6543** (pooler shares connections per-query — ideal when the service sleeps/cold-starts and connections churn). Use session mode (5432) only if you need session-level features you won't have here. Put the full pooler connection string in `DATABASE_URL`. *(Note: Supavisor deprecated session mode on 6543 back in Feb 2025 — 6543 is transaction-only now, which is what you want.)*

**Migrations: a single `schema.sql` is right for this project — not a migration tool.** The build plan already places `app/db/schema.sql` in the repo. For a greenfield demo with one author and a fixed schema, an idempotent `schema.sql` (run once against Supabase, kept in version control as the source of truth) is the minimal correct choice. A migration framework (Alembic, Supabase CLI migrations) is appropriate when a schema evolves across environments with rollbacks — that's over-engineering here. Keep `schema.sql` authoritative; seed businesses/employees with a small `seed.sql`. (If the schema later churns a lot, graduate to Supabase CLI migrations — but not for v1.)

> `supabase-py` (`supabase==2.31.0`) is still worth installing **only if** you want its auth/storage helpers — but the project explicitly has **no storage bucket and no dashboard auth**, so it earns its keep nowhere. Skip it; one driver is simpler.

### 4. PDF generation — `reportlab` (on-demand, in-memory)

**Use `reportlab` 5.0.0.** Verified BSD-licensed open-source Toolkit, **pure Python, no native/system dependencies** — it drops cleanly into a `python:3.12-slim` image with no extra `apt-get`. Generate each paystub to a `BytesIO` and stream it from the FastAPI route; nothing touches Render's ephemeral disk.

```python
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from fastapi.responses import StreamingResponse

@app.get("/runs/{run_id}/paystub/{line_item_id}.pdf")
def paystub_pdf(run_id: str, line_item_id: str):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    # ... draw gross/FICA/federal/net from the line-item row ...
    c.showPage(); c.save()
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf")
```

**Why not the alternatives** (this matters for the slim image):
- **WeasyPrint** `69.0` renders HTML/CSS to PDF beautifully **but pulls heavy native deps** (Pango, cairo, GDK-PixBuf, harfbuzz via system libraries). On a slim Docker image that means a long `apt-get` layer and a fatter image and slower cold starts — directly at odds with Render free constraints. Only choose it if you must reuse HTML/CSS layout, which you don't.
- **fpdf2** `2.8.7` is also pure-Python and lighter than reportlab — a legitimate fallback if you want the smallest dependency. reportlab wins on table/layout maturity for a tabular paystub and is the more battle-tested default; pick fpdf2 only if you specifically want minimal footprint over layout features.

### 5. FICA constants — look up at runtime, don't hardcode a stale year

**2026 figures (verified against SSA COLA materials + multiple payroll sources, Jun 2026):**
- **Social Security (OASDI) wage base = $184,500** (up from $176,100 in 2025). SS rate **6.2%**, employee max = **$11,439**.
- **Medicare = 1.45%, no wage cap.** Additional Medicare **0.9%** on wages over **$200,000** (single) / **$250,000** (MFJ) / **$125,000** (MFS). *(The 0.9% surtax is likely out of scope for the demo's wage levels but the threshold is documented if needed.)*

**Authoritative runtime source of truth:** SSA's Contribution and Benefit Base page — **`https://www.ssa.gov/oact/cola/cbb.html`** (this is THE canonical wage-base table by year). IRS **Topic 751** (`https://www.irs.gov/taxtopics/tc751`) is the canonical rate source.

**Prescriptive approach:** store the wage base and rates in a small **config table or a versioned constants module keyed by tax year**, not as a magic number inline. Set `TAX_YEAR` in env. Document in the README where each value comes from and the year it's valid for. (A literal HTTP scrape of SSA at runtime is fragile — SSA returns 403 to non-browser fetchers, confirmed — so prefer a year-keyed constant you update annually, with the SSA/IRS URLs cited in a comment.) Confidence on the $184,500 figure: **HIGH** (SSA + Mercer + Paycor + OnPay agree).

### 6. IRS Pub 15-T percentage method — the highest-bug-risk unit

**What the calculation actually requires (Worksheet 1A, Percentage Method for Automated Payroll Systems — verified against IRS Pub 15-T 2026):**

1. **Annualize** the period gross taxable wages: `wage × pay_periods_per_year` (Worksheet 1A, Step 1).
2. **Apply the 2020+ W-4 fields** to get the **Adjusted Annual Wage Amount**:
   - add **Step 4(a)** other income,
   - add a **fixed standard-deduction-style amount** that depends on filing status (a constant baked into the *worksheet*, e.g. a larger figure for MFJ vs others — **the exact 2026 figures must be read from the 2026 PDF**, they change yearly and the 2026 edition includes **OBBBA** changes),
   - add **Step 4(b)** deductions,
   - subtract that total → Adjusted Annual Wage Amount.
3. **Pick the rate schedule by filing status × the Step 2 checkbox:**
   - Three filing statuses: **Married Filing Jointly**, **Single or Married Filing Separately**, **Head of Household**.
   - Two schedule sets: **STANDARD** (Step 2 box unchecked / pre-2020 W-4) vs **Form W-4 Step 2 Checkbox** (higher-withholding) tables. You need **both** sets to be correct.
4. **Compute tentative annual withholding** from the bracket: `base_tax + rate × (adjusted_wage − bracket_floor)` (Step 2).
5. **Apply Step 3 credits** (dependents/credits), annual, then **de-annualize**: divide by pay periods.
6. **Add Step 4(c)** per-period extra withholding → final per-period federal withholding.
7. There is a **separate pre-2020 W-4 path** (withholding allowances × a fixed per-allowance amount) — the data model's `filing_status` implies 2020+ W-4 only, so you can scope to the 2020+ path and document that assumption.

**Existing implementations to lean on:**
- **`python-taxes` (PyPI 0.7.0, MIT)** — implements this exact §1 percentage method in Pydantic for 2023–2025. **Best Python reference**, but does not yet ship 2026 tables — use its *structure* and port the 2026 bracket/constant tables yourself from the IRS PDF.
- **IRS-Public/tax-withholding-estimator** (official, open-sourced Feb 2026) — authoritative correctness oracle.

**Prescriptive guidance for THIS project:**
- Build the engine as an **isolated, pure-function module** keyed by `tax_year`, with the bracket tables and the per-status worksheet constants for 2026 **transcribed directly from `https://www.irs.gov/pub/irs-pdf/p15t.pdf` (2026 edition) and unit-tested against the IRS's own worked examples** in that PDF, per filing status, both the standard and the Step-2-checkbox schedules.
- ⚠️ **Do NOT hardcode the 2026 bracket numbers from this research doc — transcribe them from the live 2026 Pub 15-T PDF.** The 2026 edition incorporates OBBBA changes; any number remembered from training data is stale. Flag: **confirm all 2026 bracket rows + the Step-1 standard amounts against the official 2026 PDF.**
- This unit is the one explicitly guarded by the run's **reconciliation check** (net + taxes + deductions ties to the run total) — keep that check as the runtime backstop. Confidence on the *method/structure*: HIGH. Confidence on any specific 2026 *numbers*: **LOW until transcribed from the PDF.**

### 7. Dashboard — FastAPI + Jinja2, no SPA

**Use `Jinja2Templates` + server-rendered HTML + minimal vanilla JS (or htmx if you want partial updates without writing fetch by hand).** Four routes total: runs list, run detail (the operator gate, with Approve/Reject POST forms), eval view (one chart), and the "Send test email" POST button. No React/Vue/build pipeline — that would be pure overhead for a 4-page internal demo with no auth.

```python
from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory="app/dashboard/templates")

@app.get("/runs/{run_id}")
def run_detail(request: Request, run_id: str):
    # fetch run + line items + decision object
    return templates.TemplateResponse("run_detail.html", {"request": request, ...})
```

For the **eval chart**, render it server-side or with a tiny client lib loaded from CDN (e.g. a single `<canvas>` + Chart.js from CDN, or pre-render an SVG). Avoid a JS bundler. The chart is "the proof," so make it legible and static rather than interactive.

### 8. Render free web service — Docker specifics

**Verified Render free-tier behavior (Jun 2026):**
- **Spin-down after 15 minutes** with no inbound traffic; **cold start ≈ under 1 minute** (Render shows a loading page while waking).
- **Only inbound HTTP/WebSocket traffic keeps it awake** — outbound cron or internal loops do NOT. This is exactly why the project is webhook-driven, not polling, and why the **GitHub Actions keep-alive must ping an HTTP endpoint** (the Render service URL and/or Supabase), not rely on the app pinging itself.
- **750 free instance-hours / month** per workspace; over that, free services suspend until next month. A single demo service is well within this.
- **Ephemeral filesystem** — confirmed; nothing on disk survives a restart/spin-down. This is why PDFs are generated in-memory on demand and all state is in Supabase.

**Dockerfile expectations (prescriptive):**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Render injects $PORT (default 10000). MUST bind 0.0.0.0 and read $PORT.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
```
- **Bind to `0.0.0.0` and the `$PORT` env var** (default `10000`). Binding to `127.0.0.1` or a hardcoded port = failed deploy / 502. This is the #1 Render Docker gotcha.
- `reportlab`/`psycopg[binary]` need **no `apt-get`** layer — keeps the image slim and cold starts fast. (If you ever swap to WeasyPrint you'd need a heavy system-deps layer — another reason not to.)
- Keep-alive workflow: GitHub Actions `schedule:` cron a couple times/week issuing a cheap `GET` to the Render URL (wakes the service) and a trivial query to Supabase (keeps the free Postgres project from pausing). Eval workflow: `on: push`.

---

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

**If the email gateway is n8n vs a hosted inbound-parse service (e.g. a webhook-posting parser):**
- Either way, the app only sees `POST /webhook/inbound` with the JSON shape in pattern #1. Keep one `EmailGateway` interface (`parse_inbound`, `send_outbound`) so the provider is wired last and swappable — exactly the locked, fixture-first design.

**If you later need state withholding (currently out of scope):**
- The `state_withholding` column is already nullable; add a flat-rate or per-state strategy behind the same calc module. Don't build it now.

**If cold-start latency hurts the demo:**
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

---
*Stack research for: LLM-driven email-to-payroll automation pipeline (free-tier, ephemeral FS, structured LLM output, Postgres-as-HITL-state)*
*Researched: 2026-06-20*
