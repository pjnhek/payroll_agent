# Phase 6: Real Integration & Ship - Research

**Researched:** 2026-06-23
**Domain:** Email provider integration (Resend), Docker/Render deploy, Supabase Postgres pooler, GitHub Actions keep-alive, recruiter-facing README + demo
**Confidence:** HIGH (all critical findings verified against live SDKs, PyPI, and official docs)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- D-01: Provider = Resend (free tier, same provider in/out). Postmark inbound is Pro-locked (~$16.50/mo).
- D-01a: Resend inbound is TWO-STEP — webhook payload is metadata-only; body retrieved via `resend.EmailsReceiving.get(email_id)`. `parse_inbound` owns BOTH steps.
- D-01b: Own the References chain. Resend does not synthesize threading.
- D-03: RFC header chain as sole resume anchor. No subject-token fallback unless D-09b verify fails.
- D-04: Demo recorded via `/demo/send-test` DASH-05 button. Transport proven once (D-09b), recording on controllable path.
- D-06: Beat sequence: (1) clean→approve→deliver, (2) "David Reyez"→clarify+suggestion, (3) alias learned→re-run resolves. +5-10s eval closing shot.
- D-07: Demo-reset script MUST exist before recording (Beat 3 persists alias to prod).
- D-08: Thin deploy FIRST (hello-world container → Supabase via pooler) before wiring Resend.
- D-08a: Local pooler pre-check before Render deploy (isolates failure classes).
- D-09: Render deploy = BLOCKING human checkpoint (`autonomous:false`).
- D-09a: Supabase stood up this phase (fresh project, schema/seed via session pooler 5432).
- D-09b: Email round-trip = BLOCKING human checkpoint (headers-intact verify).
- D-10: Locked order: local pooler pre-check → Supabase up → thin Render deploy → wire Resend → dedup+threading → email verify gate → record demo.
- D-11: Two-tier README (punchy recruiter top + engineer section). Disclaimers prominent near top. Live link = "bonus, may take ~30s."
- D-11a: Mermaid source in README + exported SVG + PNG (commit both).
- D-13: Inbound dedup on provider Message-ID as FIRST action before pipeline — highest-value fix.
- D-14: Durable threading from persisted Postgres row. Rebuild In-Reply-To/References on every send.
- D-15: `prepare_threshold=None` already set. Run schema/seed over session pooler (port 5432), NOT 6543.
- D-16: Keep-alive = one GitHub Actions cron hitting a Render HTTP health route that runs a real SELECT.
- D-17: Webhook signature verification as FIRST action (before dedup even). Raw body bytes + Svix headers.
- D-18: All provider specifics stay inside `gateway.py`. No provider blob downstream.
- D-19: Docker = uv-in-image, multi-stage, `uv sync --frozen --no-dev`.
- D-20: Health endpoint split — liveness (no DB hit) + readiness (SELECT, cron target).
- D-21: eval/chart.svg is a BAKED-IN static asset served from the committed file.

### Claude's Discretion
- Exact storage spot for dedup key + durable References chain (dedicated table vs reuse `email_messages.message_id` UNIQUE).
- Dockerfile layer details (base tag pin, exact multi-stage layout, caching).
- `render.yaml` vs dashboard-only config, exact env-var names, `sync:false` secret handling.
- Health route paths, exact SELECT, keep-alive cron cadence.
- README prose, section ordering, demo embed format (GIF vs linked video).
- Mermaid diagram exact node set.
- Demo-reset script form (SQL script vs `python -m` helper vs fresh-shorthand-per-take).

### Deferred Ideas (OUT OF SCOPE)
- Subject-token threading fallback (built only if D-09b verify fails).
- Postmark Pro paid escape hatch.
- Full per-week biweekly OT, larger eval corpus, synthetic generator, state withholding.
- Continuous-take unedited recording.
- Agent-driven Render deploy.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OPS-01 | FastAPI app containerized in one Dockerfile (binds `0.0.0.0:$PORT`), deployed as single Render free web service | D-19 multi-stage Dockerfile pattern verified; D-20 health route split; Render `$PORT` + `0.0.0.0` bind confirmed; `render.yaml` schema verified |
| OPS-02 | Real email gateway provider wired behind existing `parse_inbound`/`send` interface; fixture path unchanged | Resend SDK 2.32.2 verified; two-step inbound shape confirmed; `resend.Webhooks.verify()` implementation inspected from source; `resend.EmailsReceiving.get()` signature confirmed |
| OPS-03 | GitHub Actions keep-alive workflow pings Supabase so free project does not pause | Cron syntax confirmed; 60-day auto-disable caveat documented; concrete YAML shape provided |
| OPS-04 | README with disclaimer (OBBBA exclusion + Additional Medicare unmodeled), architecture diagram, 60-90s demo recording | Existing README stub found; disclaimer text already drafted; Mermaid native GitHub rendering confirmed; mmdc tooling not available locally |
</phase_requirements>

---

## Summary

Phase 6 wires a working 422-test slice onto the public free stack. All decisions from the discussion (D-01..D-21) are locked; this research fills the implementation gaps the discussion flagged.

**The single most important finding:** `resend.Webhooks.verify()` is implemented INSIDE the `resend` package itself (HMAC-SHA256, manual verification without needing the `svix` PyPI package). The signature is the signed content `{svix-id}.{svix-timestamp}.{raw-body}`. The method takes a `VerifyWebhookOptions` TypedDict with `payload` (str), `headers` (WebhookHeaders with `id`, `timestamp`, `signature` keys), and `webhook_secret`. This was verified by inspecting the live SDK source code at `resend 2.32.2`. The `svix` PyPI package is NOT a required dependency for signature verification.

**Inbound two-step shape (D-01a confirmed):** The `email.received` webhook payload contains `data.email_id`, `from`, `to`, `subject`, `message_id`, `attachments` (metadata only) — no body, no threading headers. Full body + headers (including `in_reply_to` and `references`) are in the `headers: Dict[str, str]` field of the `ReceivedEmail` object returned by `resend.EmailsReceiving.get(email_id)`. Threading headers (`In-Reply-To`, `References`) are NOT top-level typed fields on `ReceivedEmail` — they are keys in the `headers` dict and must be extracted by key name (case-insensitive).

**Dedup storage (D-13):** The `email_messages` table already has `CONSTRAINT uq_message_id UNIQUE (message_id)` [VERIFIED: schema.sql:153]. The current webhook handler ALREADY dedups on message_id via `repo.insert_inbound_email` with `ON CONFLICT (message_id) DO NOTHING` [VERIFIED: main.py:170-187]. However, this dedup runs AFTER `gateway.parse_inbound` — for the real Resend provider, `parse_inbound` becomes a two-step operation. The dedup must happen AFTER the two-step fetch (to have the real Message-ID), but BEFORE `decide.py`. The existing schema constraint is sufficient; no new dedup table needed.

**Threading (D-14):** The existing schema stores `in_reply_to` and `references_header` on `email_messages` rows. The outbound `send_outbound` already accepts `in_reply_to` and `references_header` parameters. What's missing: the Resend live provider must read the PERSISTED outbound `message_id` from the `email_messages` row (via `repo.get_outbound_message_id`) and build the References chain by APPENDING to the stored chain — not by re-reading the last webhook. This is the "durable" part.

**Docker:** The official Astral uv-in-image pattern (verified from astral-sh/uv-docker-example) uses `ghcr.io/astral-sh/uv:0.11.23` (latest stable as of 2026-06-19). WORKDIR must be `/app` so that relative paths `app/templates`, `app/static`, and `eval/chart.svg` resolve correctly at runtime. The `eval/chart.svg` route uses `Path("eval/chart.svg")` — a relative path that only works if uvicorn is launched from `/app`. This is a Docker WORKDIR constraint the planner must enforce.

**Primary recommendation:** Wire Resend strictly inside `gateway.py` touching no other file. The `resend` package (not `svix`) provides the verify method. Two new Settings fields: `RESEND_API_KEY` and `WEBHOOK_SIGNING_SECRET`. The existing dedup constraint is sufficient — no new table. Threading: persist the chain in `email_messages.references_header` on the outbound row and rebuild it on every send by loading that row.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Inbound webhook receive + signature verify | API / Backend (`/webhook/inbound`) | Gateway seam (`gateway.py`) | Verify must happen at route layer with raw body bytes before JSON parse; gateway owns provider specifics |
| Inbound dedup (idempotency) | API / Backend (repo layer) | DB (UNIQUE constraint) | `insert_inbound_email` ON CONFLICT is already the dedup gate; DB constraint is the backstop |
| Inbound body fetch (two-step) | Gateway seam (`gateway.py`) | Resend API | `parse_inbound` owns both webhook parse AND the follow-up `resend.EmailsReceiving.get()` call |
| Threading state (References chain) | Database / Storage (`email_messages`) | Gateway seam (rebuild on send) | Persisted per outbound row; `send_outbound` reads and appends on each send |
| Outbound send (real) | Gateway seam (`gateway.py`) | Resend API | `send_outbound` activates D-13c reserved→sent ordering against real Resend send API |
| Docker containerization | CDN / Static (image build) | API / Backend (runtime) | WORKDIR `/app`, `uv sync --frozen --no-dev`, CMD `uv run uvicorn` |
| Render deploy + $PORT binding | CDN / Static (deploy config) | API / Backend (uvicorn) | `render.yaml` + `0.0.0.0:$PORT` binding |
| Supabase pooler (runtime) | Database / Storage | — | Transaction mode 6543 for app runtime; session mode 5432 for schema/seed only |
| Health endpoints (liveness/readiness) | API / Backend (`app/main.py`) | Database / Storage | D-20 split: liveness = no DB (Render deploy health check), readiness = SELECT (cron target) |
| Keep-alive | CDN / Static (GitHub Actions cron) | API / Backend + DB | Cron hits Render HTTP endpoint that runs SELECT — one ping, two problems |
| README + diagram | Static docs | — | Mermaid source in README + SVG + PNG committed |
| Demo-reset script | Developer tooling (`scripts/`) | Database / Storage | Clears learned aliases + run rows; existing `reset_stuck_runs.py` covers run/email purge but NOT alias reset |
| Eval chart static serve (D-21) | API / Backend (`/eval/chart.svg` FileResponse) | CDN / Static (committed file) | Already implemented via `FileResponse(Path("eval/chart.svg"))`; relative path requires WORKDIR=/app |

---

## Standard Stack

### Core (existing — no change)

| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| `fastapi` | `0.138.0` | Webhook server + dashboard | Already in `pyproject.toml` |
| `uvicorn[standard]` | `0.49.0` | ASGI server | Already in `pyproject.toml` |
| `pydantic` | `2.13.4` | Contracts + settings | Already in `pyproject.toml` |
| `pydantic-settings` | `2.14.2` | Env-var config | Already in `pyproject.toml` |
| `psycopg[binary,pool]` | `3.3.4` | DB pool + pooler | Already in `pyproject.toml` |
| `openai` | `2.43.0` | LLM client | Already in `pyproject.toml` |
| `reportlab` | `5.0.0` | PDF generation | Already in `pyproject.toml` |
| `jinja2` | `3.1.6` | Dashboard templates | Already in `pyproject.toml` |

### New (Phase 6 additions)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `resend` | `2.32.2` | Resend inbound/outbound email SDK + webhook verify | Official SDK (resendlabs org); 2.6M weekly downloads; `resend.Webhooks.verify()` implements HMAC-SHA256 without external svix dep; `resend.EmailsReceiving.get()` retrieves inbound body + headers |

`svix` (PyPI) is NOT needed. `resend 2.32.2` implements webhook verification internally (HMAC-SHA256 from scratch). The `svix` npm package (1.96.0 on npm) is a separate product used by the resend JS SDK; the Python SDK has no svix dependency. [VERIFIED: SDK source inspection, 2026-06-23]

**Installation:**

```bash
uv add resend==2.32.2
```

### Version Verification

```
resend 2.32.2 — published 2026-06-17 (PyPI JSON API, 2026-06-23)
svix 1.96.0   — NOT needed; resend SDK does not depend on it
```

---

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `resend` | PyPI | 4+ years, 58 releases | 2,628,539/wk | github.com/resendlabs/resend-python | UNAVAILABLE — manual verified | Approved (high legitimacy) |

**Packages removed due to [SLOP] verdict:** none

**Packages flagged as suspicious [SUS]:** none

**slopcheck availability:** Not installed on this machine. Manual verification performed:
- `resend`: 58 PyPI versions since ~2022, 2.6M weekly downloads, 9.2M monthly, source at official `resendlabs` GitHub org, 216 npm counterpart releases from the same company. All indicators point to a legitimate, high-traffic package.
- `svix`: NOT recommended as a dependency (resend does not need it in Python).

*All packages above are tagged [VERIFIED: PyPI JSON API + SDK source inspection] based on confirmed official org ownership and download volume.*

---

## Architecture Patterns

### System Architecture Diagram

```
Client email
     |
     v
[Resend inbound webhook POST /webhook/inbound]
     |
     |-- Step 0a: resend.Webhooks.verify() [raw body + svix headers] → 400 on fail
     |
     |-- Step 0b: gateway.parse_inbound(raw_webhook_payload)
     |            |
     |            +-- Extract email_id from webhook data
     |            +-- resend.EmailsReceiving.get(email_id)  ← TWO-STEP FETCH
     |            +-- Extract headers dict for in_reply_to, references
     |            +-- Return InboundEmail (normalized, no provider blob)
     |
     |-- Dedup: repo.insert_inbound_email ON CONFLICT (message_id) DO NOTHING
     |          → duplicate? return 200 immediately, NO pipeline
     |
     |-- Reply routing: if in_reply_to/references → _route_reply() → resume
     |
     |-- Sender auth: find_business_by_sender → unknown? log + 200
     |
     |-- repo.create_run() + BackgroundTasks.add_task(run_pipeline)
     |
     v
[run_pipeline: extract → reconcile → validate → decide]
     |                                              |
     |                               request_clarification → _clarify()
     |                                              |
     |                                        gateway.send_outbound(
     |                                            in_reply_to=inbound.message_id,
     |                                            references_header=build_chain(...)
     |                                        )
     |                                             |
     |                                       DB: insert email_messages(
     |                                           message_id=<resend-outbound-id>,
     |                                           references_header=chain
     |                                       )
     |                                             |
     |                                        status=awaiting_reply ──────┐
     |                                                                    │
     |                                                           [client reply]
     |                                                                    │
     |                                                    ←──── _route_reply
     |                               process →
     v
[_compute_line_items → status=awaiting_approval]
     |
     v (operator approves in dashboard)
[_deliver: D-13c reserved→sent + gateway.send_outbound(confirmation + PDFs)]
     |
     v
status=reconciled


Keep-alive (GitHub Actions cron, 2x/week):
  GET https://<render-url>/health/ready → FastAPI SELECT 1 → 200
  → Render stays warm, Supabase stays un-paused
```

### Recommended Project Structure (Phase 6 additions)

```
.
├── Dockerfile               # new: multi-stage, uv-in-image
├── .dockerignore            # new
├── render.yaml              # new: Render blueprint
├── .env.example             # update: add RESEND_API_KEY, WEBHOOK_SIGNING_SECRET
├── app/
│   ├── config.py            # update: add resend_api_key, webhook_signing_secret fields
│   ├── email/
│   │   └── gateway.py       # update: Resend two-step parse_inbound + real send_outbound
│   └── main.py              # update: D-17 verify step zero + D-20 /health/live + /health/ready
├── scripts/
│   └── reset_demo.py        # new: D-07 demo-reset (extends reset_stuck_runs.py with alias reset)
├── .github/workflows/
│   ├── eval.yml             # existing (unchanged)
│   └── keepalive.yml        # new: D-16 cron keep-alive
└── README.md                # update: full recruiter README, diagram, demo embed, disclaimers
```

---

## Research Findings by Focus Area

### 1. Resend Inbound Two-Step Shape (D-01a / D-18)

[VERIFIED: SDK source inspection via `uv run --with resend python3`, 2026-06-23]

**Webhook payload (`email.received` event):**
```json
{
  "type": "email.received",
  "created_at": "...",
  "data": {
    "email_id": "37e4414c-5e25-4dbc-a071-43552a4bd53b",
    "from": "hr@metrodeli.example",
    "to": ["agent@payroll-agent.com"],
    "subject": "Payroll hours...",
    "message_id": "<original-client-message-id>",
    "attachments": [...]
  }
}
```

Body text, threading headers (`In-Reply-To`, `References`), and full headers are NOT in the webhook payload. They are retrieved via:

```python
import resend

email_obj: resend.ReceivedEmail = resend.EmailsReceiving.get(
    email_id=event_data["email_id"]
)
# email_obj.text        → plain text body (str | None)
# email_obj.html        → HTML body (str | None)
# email_obj.message_id  → the RFC Message-ID (str)
# email_obj.headers     → Dict[str, str] — contains "In-Reply-To", "References", etc.
```

**Critical normalization step:** `email_obj.headers` is a flat `Dict[str, str]`. Threading headers are extracted as:
```python
in_reply_to = email_obj.headers.get("In-Reply-To") or email_obj.headers.get("in-reply-to")
references = email_obj.headers.get("References") or email_obj.headers.get("references")
```

Header key casing from real providers is NOT guaranteed to be consistent. Use a case-insensitive lookup:
```python
headers_lower = {k.lower(): v for k, v in email_obj.headers.items()}
in_reply_to = headers_lower.get("in-reply-to")
references = headers_lower.get("references")
```

The `gateway.parse_inbound` function in Phase 6 must:
1. Accept a raw webhook payload dict (not a canonical InboundEmail)
2. Extract `email_id` from `data.email_id`
3. Call `resend.EmailsReceiving.get(email_id)` to fetch body + headers
4. Normalize headers case-insensitively for threading fields
5. Build and return a canonical `InboundEmail` object

**Implication for the route handler:** The route must receive the raw webhook body (not FastAPI-parsed `email: InboundEmail`) to enable (a) signature verification with raw bytes and (b) extracting `email_id` from the Resend event shape. The function signature must change from `def inbound(email: InboundEmail, ...)` to `async def inbound(request: Request, ...)`.

### 2. Webhook Signature Verification (D-17)

[VERIFIED: SDK source inspection, `resend.Webhooks.verify()`, 2026-06-23]

**The verify method is in `resend.Webhooks.verify()` — no external `svix` package needed.**

Implementation details (from SDK source):
- Algorithm: HMAC-SHA256 manual implementation
- Signed content: `"{svix-id}.{svix-timestamp}.{raw-body-as-string}"`
- Secret decoding: strip `whsec_` prefix, base64-decode remainder
- Timestamp tolerance: 5 minutes (DEFAULT_WEBHOOK_TOLERANCE_SECONDS)
- Returns `None` on success, raises `ValueError` on failure

**Exact call:**
```python
from fastapi import Request
import resend

async def inbound(request: Request, ...):
    raw_body: bytes = await request.body()
    resend.Webhooks.verify({
        "payload": raw_body.decode("utf-8"),
        "headers": {
            "id": request.headers["svix-id"],
            "timestamp": request.headers["svix-timestamp"],
            "signature": request.headers["svix-signature"],
        },
        "webhook_secret": settings.webhook_signing_secret,
    })
    # verify() raises ValueError on failure; let it propagate as HTTP 400
```

**IMPORTANT: Raw body bytes must be captured BEFORE any JSON parsing.** In FastAPI, this means using `request: Request` and `await request.body()` rather than Pydantic body model injection. FastAPI body model injection consumes the body stream.

**Route signature change required:** The `/webhook/inbound` route must change from a Pydantic-typed body to a raw `Request` object for Phase 6. The gateway seam then handles all parsing:
```python
@app.post("/webhook/inbound")
async def inbound(request: Request, background_tasks: BackgroundTasks):
    raw_body = await request.body()
    # Step 0a: signature verify
    # Step 0b: gateway.parse_inbound(raw_body, raw_headers)
    ...
```

### 3. Inbound Idempotency (D-13)

[VERIFIED: schema.sql:153, main.py:170-187, 2026-06-23]

**Current state (stub world):** The `CONSTRAINT uq_message_id UNIQUE (message_id)` exists on `email_messages`. The webhook handler already calls `repo.insert_inbound_email(..., ON CONFLICT (message_id) DO NOTHING)` and returns 200 immediately on a duplicate (no second run). This is `main.py:170-187`.

**Real provider difference:** With the stub, `parse_inbound` returns immediately. With Resend, `parse_inbound` makes a network call to `resend.EmailsReceiving.get()`. The dedup must happen AFTER this fetch (to get the real provider `message_id` from `email_obj.message_id`).

**Recommended storage:** Reuse the existing `email_messages.message_id` UNIQUE constraint. No new dedup table needed. The flow becomes:
1. Signature verify (step 0a)
2. Extract `email_id` from webhook payload (cheap, no fetch needed for dedup)
3. ⚠ Check if `email_id` is in a seen-ids set? — NO, the provider `email_id` is different from the RFC `message_id`. Dedup must be on the RFC Message-ID (from the full fetch).
4. Fetch full email: `resend.EmailsReceiving.get(email_id)` → get RFC `message_id`
5. Dedup on RFC `message_id` via the existing UNIQUE constraint
6. Continue to pipeline

**Alternative optimization (not required):** A lightweight pre-dedup on `email_id` (Resend's own ID) in a separate set could avoid the full fetch on retries. This is an optimization; the UNIQUE constraint on `message_id` is the correctness backstop.

**⚠ CONFIRM:** Does Resend always provide a distinct RFC `message_id` in the webhook event's `data.message_id` field (separate from the Resend `email_id`)? The API reference shows `message_id` as a field on the ReceivedEmail object (the full fetch response). The webhook payload's `data` object also shows `message_id`. If the webhook payload includes the RFC `message_id` top-level, the pre-dedup can avoid the full fetch on retries. Confirm the exact webhook payload shape against the live Resend dashboard when standing up the account.

### 4. Durable Threading (D-14)

[VERIFIED: schema.sql, gateway.py, main.py, repo.py, 2026-06-23]

**Current threading state:**
- `email_messages.in_reply_to` and `email_messages.references_header` columns exist on both inbound and outbound rows.
- `send_outbound` already accepts `in_reply_to` and `references_header` parameters and persists them.
- `repo.get_outbound_message_id(run_id, purpose='clarification')` retrieves the stored outbound Message-ID.
- The `simulate_reply` route (main.py:661) builds synthetic threading from the stored outbound `message_id`.

**What's missing for durable threading (D-14):**
The live `send_outbound` must build the References chain by:
1. Reading the INBOUND email's `message_id` (from `email_messages` for this run's source email)
2. Reading any previously-sent outbound `references_header` (from `email_messages` for prior outbound rows on this run)
3. Constructing `In-Reply-To: <inbound-message-id>` and `References: <prior-chain> <inbound-message-id>`
4. Persisting this chain in `email_messages.references_header` on the new outbound row

**Critical: the chain must survive dropped/duplicated deliveries.** Building it from "the last webhook I saw" is fragile. Building it from the persisted `email_messages` rows is durable.

**Implementation:** `send_outbound` in `gateway.py` should accept the inbound `message_id` it is replying to and load the prior chain from the DB. The signature already has `in_reply_to` and `references_header` parameters — the caller (orchestrator) must load and pass these values from the persisted DB state, not from ephemeral in-memory state.

**Resend threading API:** Resend accepts `reply_to`, `headers` custom fields. The outbound send call will need:
```python
resend.Emails.send({
    "from": from_addr,
    "to": to_addr,
    "subject": subject,
    "text": body,
    "headers": {
        "In-Reply-To": in_reply_to,
        "References": references_header,
        "Message-ID": minted_message_id,  # or let Resend mint it
    }
})
```
**⚠ CONFIRM:** Whether Resend allows setting a custom `Message-ID` header on outbound sends (needed to control the chain). If not, the minted ID must be the Resend-assigned ID retrieved from the send response and stored back to `email_messages`.

### 5. Docker (D-19, uv-in-image, multi-stage)

[VERIFIED: docs.astral.sh/uv/guides/integration/docker, github.com/astral-sh/uv-docker-example, 2026-06-23]

**Recommended pattern (Astral official, uv-docker-example/multistage.Dockerfile):**

```dockerfile
FROM python:3.12-slim AS builder

# Install uv (pin to specific version)
COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /uvx /bin/

# Configure uv for Docker
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Layer 1: install deps (cached until pyproject.toml / uv.lock changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Layer 2: copy source + install project
COPY . .
RUN uv sync --frozen --no-dev

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "${PORT:-10000}"]
```

**WORKDIR=/app is required** because the application uses relative paths:
- `app/templates` (Jinja2Templates)
- `app/static` (StaticFiles)
- `eval/chart.svg` (FileResponse via `Path("eval/chart.svg")`)

All three resolve against the working directory. Running uvicorn from `/app` makes these work correctly.

**psycopg[binary] in slim:** `psycopg[binary]` uses a pre-compiled wheel, so NO `apt-get install libpq-dev` is needed in the slim image. Zero system deps needed for psycopg, reportlab, resend. [VERIFIED: psycopg[binary] = bundled shared library; confirmed in CLAUDE.md]

**uv version to pin:** `0.11.23` (released 2026-06-19, latest at research time). [VERIFIED: GitHub API]

**.dockerignore** should exclude: `.venv`, `.git`, `tests/`, `eval/fixtures/*_extraction.json`, `.env`, `__pycache__`, `*.pyc`, `.planning/`, `scripts/`. Include: `eval/chart.svg`, `eval/summary.json`, `fixtures/` (demo fixtures), `app/templates/`, `app/static/`.

**CMD environment variable:** `$PORT` is injected by Render at runtime. The Dockerfile `CMD` must expand it. Use shell form (`CMD ["sh", "-c", "uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]`) or set `ENV PORT=10000` as a default and use exec form. The exec form `CMD ["uv", "run", "uvicorn", ..., "--port", "${PORT:-10000}"]` does NOT expand env vars — use shell form for the port substitution.

### 6. Render Free Service Specifics (OPS-01)

[VERIFIED: CLAUDE.md §8 + render.com/docs references, confirmed HIGH from prior phase research]

| Parameter | Value | Confidence |
|-----------|-------|------------|
| $PORT default | 10000 | HIGH [VERIFIED: CLAUDE.md] |
| Bind address | 0.0.0.0 | HIGH [VERIFIED: CLAUDE.md] |
| Spin-down | After 15 min no inbound HTTP | HIGH [VERIFIED: CLAUDE.md] |
| Cold start | ~30-60s | HIGH [VERIFIED: CLAUDE.md] |
| Instance hours/mo | 750 (free tier) | HIGH [VERIFIED: CLAUDE.md] |
| Filesystem | Ephemeral (survives nothing across restart/spin-down) | HIGH [VERIFIED: CLAUDE.md] |
| IPv4 | Yes (Render is IPv4-only; Supabase direct host is IPv6) | HIGH [VERIFIED: CLAUDE.md] |

**`render.yaml` schema (verified):**
```yaml
services:
  - name: payroll-agent
    type: web
    runtime: docker
    healthCheckPath: /health/live
    envVars:
      - key: DATABASE_URL
        sync: false        # secret — user sets in Render dashboard
      - key: RESEND_API_KEY
        sync: false
      - key: WEBHOOK_SIGNING_SECRET
        sync: false
      - key: EXTRACTION_API_KEY
        sync: false
      - key: DRAFT_API_KEY
        sync: false
      - key: EXTRACTION_MODEL
        value: deepseek-v4-flash
      - key: DRAFT_MODEL
        value: moonshot-v1-8k
      - key: EXTRACTION_BASE_URL
        value: https://api.deepseek.com
      - key: DRAFT_BASE_URL
        value: https://api.moonshot.ai/v1
      - key: TAX_YEAR
        value: "2026"
      - key: ALLOW_LIVE_LLM
        value: "true"      # prod runs live LLM
```

`sync: false` means Render will prompt the user to set the value once during initial Blueprint creation; the value is never committed to git. [VERIFIED: render.com/docs/blueprint-spec]

**Deploy health check:** Render uses `healthCheckPath` to verify the container started. This path must return 2xx with NO database required (a Supabase blip must not fail the deploy). This is the D-20 liveness route.

### 7. Supabase Pooler Standup (D-09a / D-15)

[VERIFIED: supabase.com/docs/guides/database/connecting-to-postgres, confirmed matches CLAUDE.md]

**Connection string formats:**

| Use | Host | Port | Who uses it |
|-----|------|------|-------------|
| App runtime (transactions) | `aws-<region>.pooler.supabase.com` | **6543** | FastAPI/psycopg pool |
| Schema/seed/migrations | `aws-<region>.pooler.supabase.com` | **5432** (session mode) | `python -m app.db.bootstrap` |
| NEVER for Render | `db.<ref>.supabase.co` | 5432 | IPv6-only, Render is IPv4 |

**Why 5432 for migrations, not 6543:** Transaction mode (6543) multiplexes connections. DDL statements that cannot be pipelined across session boundaries (e.g., `CREATE EXTENSION`, some `ALTER TABLE` patterns) can misbehave under transaction-mode pooling. Use session mode (5432 on the same pooler host) for schema/seed operations. [VERIFIED: Supabase docs + D-15]

**D-08a local pre-check sequence:**
1. Set `DATABASE_URL` to `postgresql://postgres.{ref}:{password}@aws-{region}.pooler.supabase.com:6543/postgres?sslmode=require`
2. `uv run python -m app.db.bootstrap` (applies schema via 5432 session URL — bootstrap must use the session URL)
3. `uv run python -m app.db.seed`
4. `uv run pytest -m integration -x` (live DB round-trip tests — currently skip-guarded)

**Bootstrap URL:** `app/db/bootstrap.py` uses `settings.database_url` directly. For the schema/seed step, the user should temporarily set `DATABASE_URL` to the **5432 session mode URL** (same pooler host, port 5432 instead of 6543), or bootstrap should accept an optional override. [ASSUMED — confirm bootstrap behavior when URL uses 6543 vs 5432; the D-15 note says to run schema over 5432 but the bootstrap code uses whatever DATABASE_URL says]

### 8. GitHub Actions Keep-Alive (OPS-03 / D-16)

[VERIFIED: docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule, 2026-06-23]

**Known caveats:**
- Minimum reliable interval: 5 minutes (per docs). Sub-5-min is unsupported.
- Scheduled workflows auto-disable after **60 days of no repository activity** on public repos. [VERIFIED: GitHub docs]
- High-load delays: the start of every hour is high-load; a ping at `:00` may be delayed.
- Supabase pause threshold: 7 days of no DB activity (not documented in research but consistent with free tier behavior). A 2x/week cron is sufficient.

**Concrete workflow YAML:**
```yaml
name: keepalive

on:
  schedule:
    # 10:17 UTC Monday and Thursday — avoids the :00 high-load window
    - cron: "17 10 * * 1,4"
  workflow_dispatch:  # manual trigger to re-enable after auto-disable

jobs:
  ping:
    runs-on: ubuntu-latest
    steps:
      - name: Ping Render health (wakes service + touches Supabase via SELECT)
        run: |
          curl -sf --max-time 90 "$RENDER_URL/health/ready" || \
            echo "Ping failed — service may still be starting"
        env:
          RENDER_URL: ${{ secrets.RENDER_URL }}
```

**Why `workflow_dispatch`:** When auto-disabled after 60 days of repo inactivity, the user can manually re-enable via the GitHub Actions UI or by triggering the workflow. [CITED: GitHub Actions docs]

**The `/health/ready` route** (D-20 readiness) must run a real `SELECT` (e.g., `SELECT 1 FROM businesses LIMIT 1`) so the Supabase free project registers actual DB activity and does not pause. A `SELECT 1` without a real table may not count as "use" in Supabase's pause detection. [ASSUMED — confirm against Supabase pause detection behavior]

**`RENDER_URL` as a secret:** Set in Render + propagate to Actions secret. The URL is not sensitive (public) but putting it in a secret avoids committing it to the repo and allows updating without a code change.

### 9. README + Architecture Diagram (OPS-04 / D-11 / D-11a)

[VERIFIED: GitHub Markdown docs + existing README.md, 2026-06-23]

**Mermaid in GitHub:** GitHub renders Mermaid natively in markdown files using fenced code blocks:
````
```mermaid
graph TD
    ...
```
````
No plugin or CDN needed. [ASSUMED — confirmed by widespread community usage; GitHub official docs page was not fetched but this is widely verified behavior]

**SVG embedding inconsistency:** SVG `<img>` embedding in GitHub READMEs can be blocked if the SVG has JavaScript or external references. PNG embedding is always reliable. Commit both: the Mermaid fenced block (for GitHub native render), an exported SVG (for embedding in non-GitHub contexts), and a PNG (fallback always works in GitHub `<img>` tags). [CITED: CONTEXT.md D-11a]

**mermaid-cli (mmdc):** Not installed locally (`mmdc` not found in PATH). The planner should include a Wave 0 task to export the diagram. Options:
- `npm install -g @mermaid-js/mermaid-cli` then `mmdc -i diagram.mmd -o diagram.png`
- Use a GitHub Action or online Mermaid live editor to export
- Or accept Mermaid fenced block only (GitHub renders it; PNG add-on is polish)

**Existing README.md:** A stub exists at `/payroll_agent/README.md` with correct disclaimer text for Additional Medicare and a "full README added in hosting/demo phase" note. The OBBBA disclaimer content is in `REQUIREMENTS.md` Out-of-Scope table and Phase 3 CONTEXT.md. The Additional Medicare disclaimer text is already in the current README.md:27-35. [VERIFIED: README.md, 2026-06-23]

**Locked disclaimer text to include verbatim** (from REQUIREMENTS.md + existing README.md):
- Educational-only / not-tax-compliant
- OBBBA exclusion: "OBBBA provisions (qualified-tips/overtime above-the-line deductions, expanded 15-line W-4) are explicitly disclaimed... standard percentage method only"
- Additional Medicare: "Additional Medicare Tax 0.9% over $200k YTD is NOT modeled... engine sets `additional_medicare_not_modeled=True` as a known-limitation flag"

### 10. Demo-Reset Script (D-07)

[VERIFIED: scripts/reset_stuck_runs.py, app/db/seed.py, app/pipeline/orchestrator.py, 2026-06-23]

**What Beat 3 writes to prod that must be cleared between takes:**

Beat 3 scenario: "David Reyez" → system clarifies → operator approves resolved run → alias "David Reyez" (or the submitted token) is learned and written to `employees.known_aliases` for David Reyes (employee ID `e0000003-0000-0000-0000-000000000003`).

On a second take, "David Reyez" now resolves via the stored alias → NO clarification → Beat 2 vanishes from the demo.

**Existing script:** `scripts/reset_stuck_runs.py` with `--purge-all` deletes all `payroll_runs` and `email_messages` rows. This covers run state but does NOT reset `employees.known_aliases`.

**What the demo-reset script needs to do:**
1. Delete all payroll runs + email messages (existing `--purge-all` does this)
2. Reset `employees.known_aliases` for the demo employees to their seed values:
   - David Reyes (`e0000003`): reset to `["D. Reyes"]` (the seed value)
   - Daniel Reyes (`e0000007`): reset to `["D. Reyes"]` (the seed value)
   - Any other employees that might have picked up aliases during demo runs

**SQL for alias reset:**
```sql
-- Reset to seed values (idempotent)
UPDATE employees SET known_aliases = ARRAY['D. Reyes']
WHERE id IN (
    'e0000003-0000-0000-0000-000000000003',  -- David Reyes
    'e0000007-0000-0000-0000-000000000007'   -- Daniel Reyes
);
-- Reset any other employee that has aliases beyond their seed values
-- (approach: re-run seed.py with ON CONFLICT DO UPDATE known_aliases = EXCLUDED.known_aliases)
```

**Recommended form:** Extend `scripts/reset_stuck_runs.py` with a `--reset-demo` mode that combines the purge-all with the alias reset, or create a new `scripts/demo_reset.py`. A Python script (not raw SQL) is preferable because it reuses `repo._conn_ctx` and the project's "never f-string SQL" discipline.

**Simpler alternative:** Add `--reset-aliases` to the existing script. The most reliable approach is to re-run `uv run python -m app.db.seed` after the purge, since seed uses `ON CONFLICT DO UPDATE` and will reset all aliases to seed values.

## Validation Architecture

[REQUIRED: nyquist_validation=true in .planning/config.json]

#### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (already configured in pyproject.toml) |
| Config file | `[tool.pytest.ini_options]` in pyproject.toml |
| Quick run command | `uv run pytest -q -m "not integration and not live_llm"` |
| Full suite command | `uv run pytest -q` (422 tests collected as of Phase 5) |

#### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OPS-02 | Inbound signature reject (forged POST → 400) | unit | `uv run pytest tests/test_gateway.py -k "verify" -x` | ❌ Wave 0 |
| OPS-02 | Inbound dedup (duplicate delivery → 200, no second run) | unit | `uv run pytest tests/test_ingest.py -k "dedup" -x` | ✅ existing (test_ingest.py covers dedup via UNIQUE constraint) |
| OPS-02 | Two-step parse (metadata-only webhook → fetch → InboundEmail) | unit (mock API call) | `uv run pytest tests/test_gateway.py -k "two_step" -x` | ❌ Wave 0 |
| OPS-02 | No-op swap invariant (existing 422 tests green after real gateway) | full suite | `uv run pytest -q` | ✅ existing suite |
| OPS-02 | Durable threading (send rebuilds References from persisted state) | unit | `uv run pytest tests/test_gateway.py -k "threading" -x` | ❌ Wave 0 |
| OPS-01 | Health liveness returns 200 (no DB) | unit | `uv run pytest tests/test_dashboard.py -k "health" -x` | ❌ Wave 0 |
| OPS-01 | Health readiness returns 200 (with DB SELECT) | integration | `uv run pytest tests/test_dashboard.py -k "ready" -m integration -x` | ❌ Wave 0 |
| OPS-03 | Keep-alive hits readiness route (verified in workflow YAML) | manual | inspect `.github/workflows/keepalive.yml` | ❌ Wave 0 |
| OPS-04 | Disclaimer text present in README.md | unit | `uv run pytest tests/test_readme.py -x` OR grep check | ❌ Wave 0 (optional) |

#### Key Behaviors Not Automatable Without Live Network

The following behaviors require a live Resend account and cannot be tested without real credentials:
- Actual webhook delivery from Resend infrastructure
- Real SMTP round-trip with threading headers surviving provider handling (the D-09b gate — BLOCKING human checkpoint, not automatable)
- Real Render cold-start behavior

#### Test Seams for Gateway (no live network needed)

```python
# Mock resend.EmailsReceiving.get — test the two-step parse without hitting Resend API
# Mock resend.Webhooks.verify — test the signature-reject path without a real signing secret
# Mock resend.Emails.send — test the outbound send path without sending real email
```

All three can be mocked at the module level in `tests/test_gateway.py` using `unittest.mock.patch` or `pytest-mock`. The `gateway.py` seam makes this clean.

#### Sampling Rate
- Per task commit: `uv run pytest -q -m "not integration and not live_llm"` (mocked, fast)
- Per wave merge: `uv run pytest -q` (full suite including integration if DB available)
- Phase gate: Full suite green before `/gsd-verify-work`

#### Wave 0 Gaps

- [ ] `tests/test_gateway.py` — add tests: two-step parse (mock `resend.EmailsReceiving.get`), signature-reject (mock `resend.Webhooks.verify` raising ValueError → HTTP 400), durable threading assertion (verify References chain built from DB state)
- [ ] Health route tests in `tests/test_dashboard.py` — liveness (no DB, always 200) and readiness (DB SELECT, returns 200 with pool)
- [ ] `uv add resend==2.32.2` — adds the package to `pyproject.toml`

*(The existing 422-test mocked suite must remain green as the no-op-swap invariant guard throughout.)*

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Webhook HMAC signature verification | Custom HMAC implementation | `resend.Webhooks.verify()` | Already implemented correctly in resend 2.32.2 with timing-safe comparison and timestamp tolerance |
| Inbound body retrieval | Raw HTTP GET to Resend API | `resend.EmailsReceiving.get(email_id)` | SDK handles auth headers, error handling, response parsing |
| Outbound send | Raw HTTP POST to Resend API | `resend.Emails.send(...)` | SDK handles retry semantics, response parsing, attachment encoding |
| Thread ID generation | UUID or hash scheme | RFC Message-ID from Resend response | Resend assigns a real Message-ID to outbound; use it as the chain anchor |

---

## Common Pitfalls

### Pitfall 1: Pydantic-typed route body breaks raw-body capture

**What goes wrong:** If the route keeps `email: InboundEmail` as the FastAPI body parameter, FastAPI's JSON parsing consumes the request body stream before `request.body()` can read it. The signature verification call gets an empty or re-encoded body that doesn't match the original.

**Why it happens:** FastAPI body model injection reads and closes the body stream.

**How to avoid:** Change the webhook route to `async def inbound(request: Request, ...)` and call `raw_body = await request.body()` as the FIRST line. Then pass `raw_body` to both `resend.Webhooks.verify()` and `gateway.parse_inbound()`.

**Warning signs:** `resend.Webhooks.verify()` raises ValueError even with a correct signing secret.

### Pitfall 2: Relative paths fail if uvicorn is not run from /app

**What goes wrong:** `app/templates`, `app/static`, and `eval/chart.svg` are relative paths. If uvicorn is started from a different working directory (e.g., `/`), all three 404.

**Why it happens:** `Path("eval/chart.svg").exists()` resolves relative to the process cwd.

**How to avoid:** Set `WORKDIR /app` in the Dockerfile and start uvicorn with the CMD that uses this as the working directory. Verify in the build that `eval/chart.svg` is COPIED into `/app/eval/chart.svg` (not just the app/ subdirectory).

**Warning signs:** Dashboard loads but the eval chart route returns 404; templates 500 on startup.

### Pitfall 3: $PORT not expanded in Dockerfile exec-form CMD

**What goes wrong:** `CMD ["uvicorn", "app.main:app", "--port", "$PORT"]` does NOT expand environment variables in Docker exec form. Uvicorn starts on the literal string `$PORT`, which fails.

**Why it happens:** Docker exec form does not invoke a shell; no variable substitution occurs.

**How to avoid:** Use shell form: `CMD ["sh", "-c", "uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]`.

**Warning signs:** Render shows the container starting but the health check fails; logs show uvicorn trying to bind to `$PORT`.

### Pitfall 4: Threading headers in headers dict are case-inconsistent

**What goes wrong:** Some providers send `In-Reply-To`, others send `in-reply-to`. Direct key lookup `headers["In-Reply-To"]` fails silently (returns None) when the provider uses lowercase.

**How to avoid:** Always normalize the `ReceivedEmail.headers` dict to lowercase keys before extracting threading fields.

### Pitfall 5: Supabase free project pauses silently

**What goes wrong:** After 7 days of no DB activity, the Supabase free project pauses. The next Render request causes a ~30s DB connection timeout rather than a clean error, stranding in-flight runs.

**How to avoid:** The `/health/ready` route must run a real `SELECT` against an actual table (not just `SELECT 1`). The keep-alive cron must target this route, not a static ping.

### Pitfall 6: GitHub Actions keep-alive auto-disables after 60 days

**What goes wrong:** On a portfolio repo with no pushes for 60 days, the scheduled workflow auto-disables silently. Supabase pauses. The demo fails cold.

**How to avoid:** Add `workflow_dispatch:` trigger to the keepalive.yml so the user can manually re-enable it. Document this in the README's "For engineers" section.

### Pitfall 7: Demo reset omits alias reset

**What goes wrong:** `scripts/reset_stuck_runs.py --purge-all` deletes all runs but leaves learned aliases on `employees.known_aliases`. Beat 2 of the second demo take resolves immediately without clarifying.

**How to avoid:** The demo-reset script must reset `employees.known_aliases` to seed values in addition to deleting runs. The cleanest approach: purge runs + email_messages, then re-run `uv run python -m app.db.seed` (which upserts with `ON CONFLICT DO UPDATE known_aliases = EXCLUDED.known_aliases`).

### Pitfall 8: Bootstrap runs over 6543 (transaction mode) instead of 5432

**What goes wrong:** Some DDL statements (extensions, complex `ALTER TABLE`) can behave incorrectly under Supavisor transaction mode (6543). The bootstrap works locally but fails on fresh Supabase.

**How to avoid:** For schema/seed, temporarily use the session-mode URL (same pooler host, port 5432). Document the two-URL setup in the deployment checklist.

---

## Runtime State Inventory

> This section is relevant because Phase 6 deploys to prod Supabase (a new state environment).

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Fresh Supabase project — no prod data yet (schema/seed not yet applied) | Apply schema.sql + seed.py via session pooler (5432) during D-09a |
| Live service config | No Render service exists yet | Human creates and configures during D-09 checkpoint |
| OS-registered state | None — no cron jobs, pm2, or Task Scheduler involved | None |
| Secrets/env vars | 5 secrets needed: DATABASE_URL, RESEND_API_KEY, WEBHOOK_SIGNING_SECRET, EXTRACTION_API_KEY, DRAFT_API_KEY | Set in Render dashboard during D-09 checkpoint; add RESEND_API_KEY + WEBHOOK_SIGNING_SECRET to .env.example |
| Build artifacts | `payroll_agent.egg-info/` at repo root (stale from editable install) | Not relevant for Docker (clean image build) |

**Demo data state between takes:** After Beat 3, `employees.known_aliases` has learned aliases in prod Supabase. The demo-reset script (D-07) must run between takes.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker | OPS-01 container build | ✓ | 28.4.0 (desktop-linux) | — |
| uv | CLAUDE.md tooling rule | ✓ | 0.9.9 (local) | Latest: 0.11.23 for Docker pin |
| Resend account | OPS-02 inbound email | ✗ | — | Stub path unchanged (fixture tests still pass) |
| Supabase project | OPS-01 prod DB | ✗ | — | Local Postgres (dev only) |
| Render account | OPS-01 deploy | ✗ | — | Local Docker run for smoke testing |
| mmdc (mermaid-cli) | OPS-04 SVG/PNG export | ✗ | — | Mermaid fenced block only (GitHub renders natively); npm install -g @mermaid-js/mermaid-cli |

**Missing dependencies blocking execution (require human):**
- Resend account (D-09b gate): human creates and configures inbound domain + webhook secret
- Supabase project (D-09a gate): human creates project, provides DATABASE_URL
- Render account (D-09 gate): human creates service, injects secrets

**Missing dependencies with fallback:**
- `mmdc`: The README can ship Mermaid fenced block only; PNG export is polish not gating.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Svix Python library for Resend webhook verify | `resend.Webhooks.verify()` (built into SDK, no svix dep) | resend SDK v2.x | No extra package needed; SDK is self-contained |
| `ghcr.io/astral-sh/uv:latest` in Dockerfile | Pin to `ghcr.io/astral-sh/uv:0.11.23` | uv best-practice guidance | Reproducible builds; `latest` can break on uv updates |
| `uv sync --locked` | `uv sync --frozen` | uv workspace docs | `--frozen` is stricter: fails if lockfile would change; correct for Docker CI |
| DeepSeek legacy IDs `deepseek-chat` / `deepseek-reasoner` | `deepseek-v4-flash` (non-thinking mode) | Deprecation 2026-07-24 | Legacy IDs break after deprecation date |

**Deprecated/outdated:**
- `deepseek-chat` / `deepseek-reasoner`: Deprecated 2026-07-24 per CLAUDE.md. The project's `config.py` already uses `deepseek-v4-flash` as the default. [VERIFIED: config.py:31]
- `client.chat.completions.parse()`: Not used (DeepSeek only supports `json_object`). Already avoided. [VERIFIED: config.py, extract.py pattern]

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `ReceivedEmail.headers` dict contains `In-Reply-To` and `References` keys (from the email provider's original headers) — not just Resend-specific headers | Research Finding #1 | Threading would fail; need to parse raw email from `email_obj.raw.download_url` as fallback |
| A2 | Supabase free project pause is triggered by 7 days of no DB activity (not wall-clock or traffic-only) | Research Finding #8 | Keep-alive cron might not prevent pause if threshold is different |
| A3 | GitHub Mermaid rendering works for fenced code blocks in README.md (no plugin needed) | Finding #9 | Would need to embed PNG only |
| A4 | Bootstrap running over 6543 (transaction mode) fails for some DDL — needs 5432 | Finding #7 | Bootstrap might work fine on 6543 (psycopg autocommit DDL may not need session mode) — ⚠ CONFIRM against Supabase docs or test |
| A5 | Resend assigns a usable RFC Message-ID to outbound emails (accessible from the send response) that can be stored and used as the References chain anchor | Finding #4 (threading) | Would need to mint a synthetic Message-ID pre-send and force it via custom headers |
| A6 | The `data.message_id` field in the Resend webhook payload IS the RFC Message-ID (not the Resend internal `email_id`) | Finding #3 (dedup) | Dedup pre-fetch would need to use `email_id` instead |
| A7 | `SELECT 1 FROM businesses LIMIT 1` qualifies as "database use" for Supabase free-tier pause prevention | Finding #8 | A bare `SELECT 1` might also work; or Supabase may measure differently |

**If this table is empty for non-assumed items:** All other claims in this research were verified or cited against official sources.

---

## Open Questions

1. **Custom Message-ID on Resend outbound sends**
   - What we know: Resend accepts custom `headers` on outbound email sends; threading requires controlling `Message-ID`
   - What's unclear: Whether Resend allows overriding `Message-ID` in the `headers` dict or always mints its own
   - Recommendation: Test during D-09b verify gate; if Resend mints its own, store the Resend-assigned ID from the send response

2. **Bootstrap DDL over 6543 vs 5432**
   - What we know: D-15 says run schema/seed over session mode (5432); psycopg `prepare_threshold=None` is already set
   - What's unclear: Whether the current bootstrap code actually fails on 6543 (it uses `psycopg.connect()` directly, not the pool, so there may be no issue)
   - Recommendation: Test `uv run python -m app.db.bootstrap` against the Supabase 6543 URL during D-08a; if it fails, use 5432 URL for bootstrap only

3. **Webhook payload `data.message_id` vs `data.email_id`**
   - What we know: Both `email_id` (Resend internal) and `message_id` (RFC) appear in the ReceivedEmail object from the full fetch
   - What's unclear: Whether `message_id` is also in the lightweight webhook payload (before the full fetch) — this would enable pre-fetch dedup
   - Recommendation: Log the raw webhook payload during the D-09b verify round-trip to see the exact shape

---

## Security Domain

> security_enforcement: true, asvs_level: 1

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No (no user auth — noted as out-of-scope demo) | — |
| V3 Session Management | No | — |
| V4 Access Control | Partial (webhook signature = access control for inbound endpoint) | `resend.Webhooks.verify()` — step zero before any processing |
| V5 Input Validation | Yes | Pydantic v2 `InboundEmail` contract with `extra="forbid"`; signature verify rejects unauthenticated inputs |
| V6 Cryptography | Yes | HMAC-SHA256 (implemented in resend SDK); timing-safe comparison via `hmac.compare_digest` |

### Known Threat Patterns for this Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Forged inbound payroll email | Tampering / Spoofing | `resend.Webhooks.verify()` as step zero — rejects unsigned POSTs |
| Duplicate delivery re-runs `decide.py` | Tampering (false-process) | Dedup on RFC Message-ID via UNIQUE constraint — returns 200 immediately before pipeline |
| Replay attack (old webhook replayed) | Repudiation | 5-minute timestamp tolerance in `resend.Webhooks.verify()` |
| Spoofed clarification reply | Spoofing | FIX-5 sender re-validation already in `_route_reply` (main.py:253) |
| SQL injection via email body | Tampering | psycopg parameterized queries throughout; project rule "never f-string SQL" |
| SSRF via demo fixture path | Elevation | Allowlist in `_DEMO_FIXTURES` dict; server resolves path, never accepts client path |

---

## Sources

### Primary (HIGH confidence)

- **resend SDK 2.32.2 source** — `uv run --with resend python3` live inspection, 2026-06-23: `resend.Webhooks.verify()` signature + implementation, `resend.EmailsReceiving.get()` signature, `resend.ReceivedEmail` schema, `resend.VerifyWebhookOptions` + `resend.WebhookHeaders` TypedDicts
- **PyPI JSON API** — `pypi.org/pypi/resend/json` (2026-06-23): resend 2.32.2, published 2026-06-17; 58 versions; github.com/resendlabs/resend-python
- **pypistats.org** — resend: 2,628,539/wk, 9,217,905/month (2026-06-23)
- **GitHub API** — `api.github.com/repos/astral-sh/uv/releases/latest`: uv 0.11.23, published 2026-06-19
- **resend.com/docs/dashboard/receiving/introduction** — metadata-only webhook payload; `email.received` event shape; body via follow-up API call
- **resend.com/docs/api-reference/emails/retrieve-received-email** (WebFetch) — `GET /emails/receiving/{id}` endpoint; `resend.EmailsReceiving.get(email_id)` returns `text`, `html`, `headers`, `message_id`
- **svix.com/guides/receiving/receive-webhooks-with-python-fastapi** — `Webhook(secret).verify(payload, headers)` FastAPI pattern; raw body required
- **supabase.com/docs/guides/database/connecting-to-postgres** — pooler host format; 6543 (transaction) vs 5432 (session); direct host IPv6-only
- **render.com/docs/blueprint-spec** — `render.yaml` schema for Docker web service; `sync: false` for secrets
- **docs.github.com/en/actions/…/events-that-trigger-workflows#schedule** — cron syntax; 5-min minimum; 60-day auto-disable on inactive public repos
- **astral-sh/uv-docker-example/multistage.Dockerfile** — official Astral multi-stage Dockerfile pattern with uv; `UV_COMPILE_BYTECODE`, `UV_LINK_MODE=copy`, two-stage sync
- **VERIFIED codebase files** (2026-06-23): `app/email/gateway.py`, `app/main.py`, `app/config.py`, `app/db/schema.sql`, `app/db/supabase.py:46`, `app/db/bootstrap.py:96`, `app/models/contracts.py`, `app/db/seed.py`, `scripts/reset_stuck_runs.py`, `pyproject.toml`, `.env.example`, `.github/workflows/eval.yml`, `eval/chart.svg` (confirmed exists), `eval/summary.json` (confirmed exists)

### Secondary (MEDIUM confidence)

- **resend.com/blog/inbound-emails** — webhook payload `data` object fields (from, to, subject, email_id, message_id, attachments — no body)
- **resend.com/docs/dashboard/webhooks/verify-webhooks-requests** — Svix-based signing; raw body required; three required headers

### Tertiary (LOW confidence / flagged)

- **Supabase free-tier pause threshold (7 days)** — widely cited in community, not fetched from official docs directly [ASSUMED — A2]

---

## Metadata

**Confidence breakdown:**
- Standard stack (resend SDK): HIGH — SDK source inspected directly
- Architecture (two-step parse, threading, dedup): HIGH — verified against codebase + SDK
- Docker pattern: HIGH — official Astral example verified
- Render/Supabase configuration: HIGH — carried from prior phase research + verified against CLAUDE.md locked decisions
- Pitfalls: HIGH — verified against SDK source and codebase
- Assumptions (A1-A7): LOW — flagged for confirmation during D-08a / D-09b human gates

**Research date:** 2026-06-23
**Valid until:** 2026-07-23 (stable ecosystem; resend SDK version should be re-verified if planning extends beyond this date)
