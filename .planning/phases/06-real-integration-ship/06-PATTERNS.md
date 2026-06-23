# Phase 6: Real Integration & Ship - Pattern Map

**Mapped:** 2026-06-23
**Files analyzed:** 10 new/modified files
**Analogs found:** 9 / 10

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `app/email/gateway.py` | service / gateway | request-response + event-driven | self (current stub shape) | exact |
| `app/main.py` | controller | request-response | self (existing routes) | exact |
| `app/config.py` | config | — | self (existing Settings) | exact |
| `app/models/contracts.py` | model | — | self (existing InboundEmail) | exact |
| `pyproject.toml` | config | — | self (existing deps block) | exact |
| `Dockerfile` | config | — | none in-repo; RESEARCH.md Astral pattern | no analog |
| `render.yaml` | config | — | none in-repo; RESEARCH.md verified schema | no analog |
| `.github/workflows/keepalive.yml` | config / CI | — | `.github/workflows/eval.yml` | role-match |
| `scripts/demo_reset.py` | utility | CRUD | `scripts/reset_stuck_runs.py` + `app/db/seed.py` | role-match |
| `tests/test_gateway.py` (extend) + `tests/test_ingest.py` / `tests/test_dashboard.py` (extend) | test | — | `tests/test_gateway.py` + `tests/conftest.py` | exact |

---

## Pattern Assignments

### `app/email/gateway.py` (service/gateway, request-response)

**Analog:** same file — current stub is the shape to extend, not replace.

**Current imports block** (`app/email/gateway.py` lines 16-21):
```python
from __future__ import annotations

import uuid

from app.db import repo
from app.models.contracts import InboundEmail
```

**Phase 6 additions to imports:**
```python
import resend                          # uv add resend==2.32.2
from app.config import get_settings    # for resend_api_key
```

**Current `parse_inbound` stub** (lines 27-37 — the shape to replace):
```python
def parse_inbound(raw: dict | str | bytes) -> InboundEmail:
    if isinstance(raw, (str, bytes)):
        return InboundEmail.model_validate_json(raw)
    return InboundEmail.model_validate(raw)
```

**Real Resend two-step shape to implement** (from RESEARCH.md §1 — D-01a/D-18):
```python
def parse_inbound(raw: dict | str | bytes) -> InboundEmail:
    """Two-step Resend parse: webhook metadata → resend.EmailsReceiving.get() fetch.

    Step 1: extract email_id from the webhook data dict.
    Step 2: fetch full body + headers via resend.EmailsReceiving.get(email_id).
    Step 3: normalize headers case-insensitively for threading fields.
    Step 4: return canonical InboundEmail (no provider blob downstream — D-18).
    """
    # Accept raw bytes/str from route (after signature verify consumed the body)
    if isinstance(raw, (str, bytes)):
        import json
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    else:
        data = raw
    email_id = data["data"]["email_id"]
    # Two-step fetch — resend.EmailsReceiving.get() returns body + headers
    email_obj: resend.ReceivedEmail = resend.EmailsReceiving.get(email_id=email_id)
    headers_lower = {k.lower(): v for k, v in (email_obj.headers or {}).items()}
    return InboundEmail(
        id=uuid.uuid4(),
        message_id=email_obj.message_id or data["data"].get("message_id", ""),
        in_reply_to=headers_lower.get("in-reply-to"),
        references_header=headers_lower.get("references"),
        subject=data["data"].get("subject", ""),
        from_addr=data["data"].get("from", ""),
        to_addr=(data["data"].get("to") or [""])[0],
        body_text=email_obj.text or "",
        created_at=...,
    )
```

**Current `send_outbound` stub** (lines 40-87 — shape to extend for D-13c / D-14):
```python
def send_outbound(
    *,
    run_id: uuid.UUID,
    to_addr: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
    references_header: str | None = None,
    from_addr: str | None = None,
    attachments: list[tuple[str, bytes]] | None = None,
    purpose: str | None = None,
    send_state: str = "sent",
    conn=None,
) -> str:
    # D-13c Phase-6-forward: send_state='reserved' before provider call, 'sent' after
    message_id = f"<{uuid.uuid4()}@{_OUTBOUND_DOMAIN}>"
    repo.insert_email_message(
        run_id=run_id,
        direction="outbound",
        message_id=message_id,
        in_reply_to=in_reply_to,
        references_header=references_header,
        subject=subject,
        ...
        send_state=send_state,
        conn=conn,
    )
    return message_id
```

**D-13c crash-safe ordering to activate — SCHEMA-SAFE VERSION (HIGH-1 WAIVE, 06-04):**

IMPORTANT: email_messages has NO `provider_message_id` column and NO `updated_at` column.
The Resend-returned provider id (`response["id"]`) is LOGGED ONLY — it is NOT written to the DB.
The flip-to-sent UPDATE sets ONLY `send_state`, keyed by the synthetic `message_id`.
The function returns the SYNTHETIC message_id (the RFC anchor), NOT Resend's provider id.

```python
# 1. Write intent row FIRST (send_state='reserved') — the irreversible record
#    synthetic_message_id is the RFC anchor; the DB dedup UNIQUE is keyed on it.
repo.insert_email_message(..., send_state="reserved", conn=conn)
# 2. Make the provider call — the side-effect that can fail
response = resend.Emails.send({...})
provider_id = response["id"]   # Resend-internal id — logged only, NOT persisted
logger.info("send_outbound provider_id=%s synthetic_id=%s", provider_id, synthetic_message_id)
# 3. Flip to 'sent' — UPDATE sets ONLY send_state, WHERE clause uses synthetic_message_id
#    DO NOT write provider_id to the DB (column does not exist — would raise ProgrammingError)
repo.update_email_message_state(synthetic_message_id, "sent", conn=conn)
return synthetic_message_id   # RFC anchor — callers use this to thread replies
```

**Verify method placement** (D-17 — stays in gateway.py per D-18):
```python
def verify(raw_body: bytes, headers: dict[str, str], signing_secret: str) -> None:
    """Verify Resend webhook signature. Raises ValueError on failure.

    Called from the route handler BEFORE parse_inbound. Kept in gateway.py so
    the route stays provider-agnostic — it passes raw bytes + raw headers here.
    """
    resend.Webhooks.verify({
        "payload": raw_body.decode("utf-8"),
        "headers": {
            "id": headers["svix-id"],
            "timestamp": headers["svix-timestamp"],
            "signature": headers["svix-signature"],
        },
        "webhook_secret": signing_secret,
    })
    # Returns None on success; raises ValueError on failure (resend SDK behavior)
```

---

### `app/main.py` (controller, request-response)

**Analog:** self — existing `/webhook/inbound` route at line 158, `/eval/chart.svg` at line 598.

**Current route signature** (line 158-159 — must change):
```python
@app.post("/webhook/inbound")
def inbound(email: InboundEmail, background_tasks: BackgroundTasks) -> JSONResponse:
```

**New route signature** (D-17 raw body + D-13 dedup as step zero):
```python
@app.post("/webhook/inbound")
async def inbound(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    """Step 0a: signature verify; Step 0b: parse; then existing dedup/pipeline flow."""
    raw_body: bytes = await request.body()
    # Step 0a — signature verify (D-17). Raises ValueError → caught as 400.
    try:
        gateway.verify(raw_body, dict(request.headers), settings.webhook_signing_secret)
    except ValueError as exc:
        logger.warning("webhook signature verification failed: %s", exc)
        raise HTTPException(status_code=400, detail="invalid webhook signature")
    # Step 0b — provider parse (D-01a two-step, D-18 normalized)
    email = gateway.parse_inbound(raw_body)
    # ... rest of existing flow unchanged (dedup, reply routing, sender auth, etc.)
```

**Existing dedup pattern** (lines 170-187 — unchanged, already correct):
```python
email_id, inserted = repo.insert_inbound_email(
    message_id=email.message_id,
    ...
)
if not inserted:
    logger.info("duplicate inbound message_id=%s — no second run", email.message_id)
    return JSONResponse(
        status_code=200,
        content={"status": "duplicate", "message_id": email.message_id},
    )
```

**New health routes to add** (D-20 — no analog yet, mimic existing route style):
```python
@app.get("/health/live")
def health_live() -> JSONResponse:
    """Liveness probe — no DB hit. Render deploy health check target (D-20).

    A Supabase blip must not fail the deploy, so this route does NO DB work.
    """
    return JSONResponse({"status": "ok"})


@app.get("/health/ready")
def health_ready() -> JSONResponse:
    """Readiness probe — runs a real SELECT. GitHub Actions keep-alive target (D-16/D-20).

    Touches a real table so Supabase free project registers DB activity and
    does not pause. A SELECT 1 without a real table may not count as 'use'.
    """
    try:
        from app.db.supabase import get_connection
        with get_connection() as conn:
            conn.execute("SELECT 1 FROM businesses LIMIT 1")
        return JSONResponse({"status": "ready"})
    except Exception as exc:
        logger.error("readiness probe failed: %s", exc)
        raise HTTPException(status_code=503, detail="database not ready")
```

**Existing `/eval/chart.svg` pattern** (lines 598-604 — confirm D-21, no change needed):
```python
@app.get("/eval/chart.svg")
def eval_chart():
    """Serve the committed eval/chart.svg as image/svg+xml."""
    chart_path = Path("eval/chart.svg")
    if not chart_path.exists():
        raise HTTPException(status_code=404, detail="eval/chart.svg not found")
    return FileResponse(str(chart_path), media_type="image/svg+xml")
```
Note: `Path("eval/chart.svg")` is a relative path — WORKDIR=/app in Dockerfile is required (D-19, RESEARCH Pitfall 2).

---

### `app/config.py` (config)

**Analog:** self — existing `Settings` class (lines 16-52).

**Existing pattern to extend** (lines 16-52):
```python
class Settings(BaseSettings):
    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str  # no default — fails fast if unset

    # ── Extraction tier ───────────────────────────────────────────────────────
    extraction_model: str = "deepseek-v4-flash"
    extraction_base_url: str = "https://api.deepseek.com"
    extraction_api_key: str = ""

    # ── Drafting tier ─────────────────────────────────────────────────────────
    draft_model: str = "moonshot-v1-8k"
    draft_base_url: str = "https://api.moonshot.ai/v1"
    draft_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
```

**Phase 6 additions** (follow same comment-header pattern, no default = fails fast):
```python
    # ── Email provider (Resend, Phase 6) ──────────────────────────────────────
    # No defaults — missing keys fail fast at startup, not mid-pipeline (D-17).
    resend_api_key: str = ""           # RESEND_API_KEY env var
    webhook_signing_secret: str = ""   # WEBHOOK_SIGNING_SECRET env var
```

---

### `app/models/contracts.py` — `InboundEmail` (model)

**Analog:** self — existing `InboundEmail` at lines 35-53.

**Current shape** (lines 35-53 — already has the required typed threading fields):
```python
class InboundEmail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    message_id: str
    in_reply_to: str | None
    references_header: str | None
    subject: str
    from_addr: str
    to_addr: str
    body_text: str
    created_at: datetime
```

**Assessment:** The `InboundEmail` contract already has `message_id`, `in_reply_to`, `references_header`, and `body_text` as typed fields (D-18 normalization target is already satisfied). No modifications needed to this model — the gateway's real `parse_inbound` must populate these from the Resend `ReceivedEmail` object, not pass a raw provider blob through.

---

### `pyproject.toml` (config)

**Analog:** self — existing `[project.dependencies]` block (lines 7-17).

**Existing pattern** (lines 7-17):
```toml
[project]
dependencies = [
    "fastapi==0.138.0",
    "uvicorn[standard]==0.49.0",
    "pydantic==2.13.4",
    ...
]
```

**Phase 6 addition** — run `uv add resend==2.32.2`. The lockfile is authoritative; never edit `pyproject.toml` by hand for deps. The line added will follow the pinned-version pattern:
```toml
    "resend==2.32.2",
```

---

### `Dockerfile` (config — no in-repo analog)

**Analog:** none in-repo. Use the official Astral uv-docker-example/multistage.Dockerfile pattern from RESEARCH.md §5.

**Pattern from RESEARCH.md** (verified against astral-sh/uv-docker-example):
```dockerfile
FROM python:3.12-slim AS builder

# Pin uv version for reproducible builds (uv latest at research time: 0.11.23)
COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# WORKDIR=/app is REQUIRED — app uses relative paths for templates, static, eval/chart.svg
WORKDIR /app

# Layer 1: install deps (cached until pyproject.toml / uv.lock changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Layer 2: copy source + install project
COPY . .
RUN uv sync --frozen --no-dev

# Runtime stage
FROM python:3.12-slim AS runtime

WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"

# Shell form required — Docker exec form does NOT expand $PORT (RESEARCH Pitfall 3)
# HIGH-1 (Round 1): run uvicorn directly from the venv — uv is NOT copied into the
# runtime stage, so `uv run` would fail at container start. PATH includes /app/.venv/bin.
CMD ["sh", "-c", ".venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
```

**Critical constraints:**
- WORKDIR must be `/app` — `eval/chart.svg`, `app/templates`, `app/static` are relative paths
- Shell form CMD for `$PORT` expansion — exec form silently uses literal `"$PORT"`
- `uv sync --frozen --no-dev` — `--frozen` fails if lockfile would change (stricter than `--locked`)
- No `apt-get` needed — `psycopg[binary]`, `reportlab`, `resend` are all pure-Python or have bundled wheels

**.dockerignore pattern** (include only what the runtime needs):
```
.venv/
.git/
tests/
.env
__pycache__/
*.pyc
.planning/
payroll_agent.egg-info/
# keep: app/, eval/chart.svg, eval/summary.json, eval/fixtures/, fixtures/
```

---

### `render.yaml` (config — no in-repo analog)

**Analog:** none in-repo. Verified schema from RESEARCH.md §6.

**Pattern from RESEARCH.md** (verified against render.com/docs/blueprint-spec):
```yaml
services:
  - name: payroll-agent
    type: web
    runtime: docker
    healthCheckPath: /health/live      # D-20 liveness — no DB, survives Supabase blip
    envVars:
      - key: DATABASE_URL
        sync: false                    # secret — user sets in Render dashboard; never committed
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
        value: "true"
```

`sync: false` means Render prompts for the value once at Blueprint creation — the value is never committed to git (D-09).

---

### `.github/workflows/keepalive.yml` (CI config)

**Analog:** `.github/workflows/eval.yml` — copy its structure (checkout, uv setup, run command), adapt for a cron schedule targeting the health route.

**Existing eval.yml structure** (lines 1-65 — the template):
```yaml
name: eval

on:
  push:
    branches: ["master"]
  workflow_dispatch:
    inputs:
      live_record:
        ...

jobs:
  check:
    name: "..."
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Set up uv + Python 3.12
        uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.12"
      - name: Install deps (all groups)
        run: uv sync
      - name: Run eval regression gate
        run: uv run python eval/run_eval.py --check
        env:
          DATABASE_URL: "placeholder"
```

**New keepalive.yml pattern** (derived from eval.yml style, adapted to cron + HTTP ping):
```yaml
name: keepalive

on:
  schedule:
    # 10:17 UTC Monday and Thursday — avoids :00 high-load window (RESEARCH §8)
    - cron: "17 10 * * 1,4"
  workflow_dispatch:    # manual re-enable after 60-day auto-disable (RESEARCH Pitfall 6)

jobs:
  ping:
    name: "Ping Render + Supabase (keep-alive)"
    runs-on: ubuntu-latest
    steps:
      - name: Ping Render health (wakes service + touches Supabase via SELECT)
        # --max-time 90: Render cold start can take up to 60s; give headroom
        # || echo: non-fatal — log failure but don't fail the workflow
        run: |
          curl -sf --max-time 90 "$RENDER_URL/health/ready" || \
            echo "Ping failed — service may still be starting (cold start)"
        env:
          RENDER_URL: ${{ secrets.RENDER_URL }}
```

**Key differences from eval.yml:**
- Trigger: `schedule:` cron + `workflow_dispatch:` (NOT `push:`)
- No `checkout` or `uv setup` needed — just a `curl` HTTP ping
- `workflow_dispatch:` is required so the user can manually re-enable after the 60-day auto-disable (RESEARCH Pitfall 6)
- `RENDER_URL` is a repo secret (not committed); the `/health/ready` route runs a real `SELECT` so Supabase registers DB activity (D-16)

---

### `scripts/demo_reset.py` (utility, CRUD)

**Analog 1:** `scripts/reset_stuck_runs.py` — CLI entrypoint style, `repo._conn_ctx`, `--mode` pattern, parameterized SQL discipline.
**Analog 2:** `app/db/seed.py` — the `ON CONFLICT DO UPDATE known_aliases = EXCLUDED.known_aliases` upsert that resets aliases to seed values.

**reset_stuck_runs.py key patterns** (lines 1-80):
```python
# CLI entrypoint pattern
from app.db import repo

def main() -> None:
    args = sys.argv[1:]
    mode = args[0] if args else "--list"

    with repo._conn_ctx(None) as (c, _owns):
        if mode == "--purge-all":
            # DESTRUCTIVE: asks for confirmation
            print("DESTRUCTIVE: ... Type 'PURGE' to confirm: ", end="")
            try:
                confirm = input().strip()
            except EOFError:
                confirm = "PURGE" if "--yes" in args else ""
            if confirm != "PURGE":
                print("Aborted.")
                return
            # Break circular FK first, then delete
            c.execute("UPDATE payroll_runs SET source_email_id = NULL")
            c.execute("DELETE FROM email_messages")
            c.execute("DELETE FROM payroll_runs")

if __name__ == "__main__":
    main()
```

**seed.py alias reset pattern** (lines 346-399 — the idempotent upsert to replicate):
```python
# ON CONFLICT ON CONSTRAINT uq_employee_business_name DO UPDATE
# resets known_aliases to the seed values (idempotent, safe to re-run)
conn.execute(
    """
    INSERT INTO employees (..., known_aliases, ...)
    VALUES (...)
    ON CONFLICT ON CONSTRAINT uq_employee_business_name DO UPDATE
      SET known_aliases = EXCLUDED.known_aliases,
          ...
          updated_at    = now()
    """,
    (..., emp.known_aliases, ...),
)
```

**New demo_reset.py shape to implement** (combines both patterns):
```python
"""Demo-DB reset helper (Phase 6, D-07).

Clears all payroll runs + email_messages AND resets employee known_aliases to
seed values so the demo's Beat 2 (unknown shorthand → clarify) works on every
take. Beat 3 persists a learned alias to prod — this script undoes that.

Two modes:
  --confirm        purge all runs + email_messages + reset aliases (DESTRUCTIVE; requires this flag)
  --reset-aliases  alias reset only (no run/email purge; no --confirm required)

Run: uv run python scripts/demo_reset.py --confirm
"""
import sys
from app.db import repo

def main() -> None:
    args = sys.argv[1:]
    mode = args[0] if args else ""

    if mode == "--confirm":
        with repo._conn_ctx(None) as (c, _owns):
            # Step 1: break circular FK
            c.execute("UPDATE payroll_runs SET source_email_id = NULL")
            # Step 2: delete child rows in FK-safe order
            # (NO alias_audit table in schema.sql — only paystub_line_items → email_messages → payroll_runs)
            c.execute("DELETE FROM paystub_line_items")
            c.execute("DELETE FROM email_messages")
            c.execute("DELETE FROM payroll_runs")
            # Step 3: reset known_aliases via seed() upsert
            from app.db.seed import seed
            seed()
            # Step 4: re-apply demo contact_email so find_business_by_sender still matches
            import os
            demo_email = os.environ.get("DEMO_CONTACT_EMAIL", "")
            demo_biz   = os.environ.get("DEMO_BUSINESS_NAME", "")
            if demo_email and demo_biz:
                c.execute(
                    "UPDATE businesses SET contact_email = %s WHERE name = %s",
                    (demo_email, demo_biz),
                )
            else:
                print("WARNING: DEMO_CONTACT_EMAIL or DEMO_BUSINESS_NAME not set — demo identity not restored")
    elif mode == "--reset-aliases":
        from app.db.seed import seed
        seed()
        import os
        demo_email = os.environ.get("DEMO_CONTACT_EMAIL", "")
        demo_biz   = os.environ.get("DEMO_BUSINESS_NAME", "")
        if demo_email and demo_biz:
            with repo._conn_ctx(None) as (c, _owns):
                c.execute(
                    "UPDATE businesses SET contact_email = %s WHERE name = %s",
                    (demo_email, demo_biz),
                )
    else:
        print("Usage: uv run python scripts/demo_reset.py --confirm | --reset-aliases")
        print("  --confirm       DESTRUCTIVE: purge all runs + emails + reset aliases")
        print("  --reset-aliases Alias reset only (non-destructive)")
```

---

### `tests/test_gateway.py` (extend) + `tests/test_ingest.py` / `tests/test_dashboard.py` (extend) (test)

**Analog:** `tests/test_gateway.py` (existing) + `tests/conftest.py` — the `FakeConnection`, `fake_conn` fixture, `monkeypatch`, `@pytest.mark.integration` pattern.

**FakeConnection pattern** (`tests/conftest.py` lines 37-123 — use as-is, no change):
```python
class FakeConnection:
    """In-memory psycopg.Connection stand-in. Records (sql, params) per execute()."""
    def __init__(self) -> None:
        self.executed: list[tuple] = []
        self._fetchone_q: list = []
    def script_fetchone(self, row) -> None: ...
    def execute(self, sql, params=None): self.executed.append((sql, params)); return self
    def last(self) -> tuple: return self.executed[-1]
    def all_sql(self) -> str: return "\n".join(str(sql) for sql, _ in self.executed)

@pytest.fixture
def fake_conn() -> FakeConnection:
    return FakeConnection()
```

**Existing mock pattern for external calls** (`tests/conftest.py` lines 488-498):
```python
@pytest.fixture
def mock_llm(monkeypatch):
    MockOpenAI.script = []
    MockOpenAI.calls = []
    monkeypatch.setattr("app.llm.client.OpenAI", MockOpenAI)
    return MockOpenAI
```

**New gateway tests to add** (copy style from existing `test_gateway.py` + mock the resend SDK):
```python
# tests/test_gateway.py additions — mock resend SDK calls, no network

def test_verify_raises_on_bad_signature(monkeypatch):
    """D-17: gateway.verify() must raise ValueError on invalid signature."""
    import resend
    monkeypatch.setattr(resend.Webhooks, "verify", lambda opts: (_ for _ in ()).throw(ValueError("bad sig")))
    with pytest.raises(ValueError):
        gateway.verify(b"payload", {"svix-id": "x", "svix-timestamp": "y", "svix-signature": "z"}, "secret")


def test_parse_inbound_two_step_fetch(monkeypatch):
    """D-01a: parse_inbound makes a follow-up resend.EmailsReceiving.get() call."""
    import resend

    class _FakeReceivedEmail:
        message_id = "<abc@resend.com>"
        text = "Maria 40 hours"
        html = None
        headers = {"In-Reply-To": "<prev@x.test>", "References": "<prev@x.test>"}

    monkeypatch.setattr(resend.EmailsReceiving, "get", lambda email_id: _FakeReceivedEmail())
    raw = {"data": {"email_id": "re_123", "from": "hr@acme.test", "to": ["agent@x.test"],
                    "subject": "hours", "message_id": "<abc@resend.com>"}}
    email = gateway.parse_inbound(raw)
    assert email.message_id == "<abc@resend.com>"
    assert email.in_reply_to == "<prev@x.test>"
    assert email.body_text == "Maria 40 hours"


def test_parse_inbound_normalizes_headers_case_insensitively(monkeypatch):
    """D-18 / RESEARCH Pitfall 4: lowercase header keys must be extracted."""
    import resend

    class _FakeEmail:
        message_id = "<x@resend.com>"
        text = "body"
        html = None
        headers = {"in-reply-to": "<prev@x.test>"}  # lowercase variant

    monkeypatch.setattr(resend.EmailsReceiving, "get", lambda email_id: _FakeEmail())
    raw = {"data": {"email_id": "re_456", "from": "hr@acme.test", "to": ["a@x.test"],
                    "subject": "s", "message_id": "<x@resend.com>"}}
    email = gateway.parse_inbound(raw)
    assert email.in_reply_to == "<prev@x.test>"


def test_send_outbound_reserved_before_sent_ordering(fake_conn, monkeypatch):
    """D-13c: send_state='reserved' written to DB BEFORE provider call."""
    import resend
    monkeypatch.setattr(resend.Emails, "send", lambda params: {"id": "<out@resend.com>"})
    gateway.send_outbound(run_id=uuid.uuid4(), to_addr="x@test.com",
                          subject="s", body="b", conn=fake_conn)
    # First SQL executed must be the 'reserved' insert, not 'sent'
    first_sql, first_params = fake_conn.executed[0]
    assert "reserved" in str(first_params), "send_state='reserved' must be written before the provider call"
```

**New health route tests to add to `tests/test_dashboard.py`** (copy existing client + TestClient pattern):
```python
def test_health_live_returns_200_no_db():
    """D-20 liveness: /health/live must return 200 with no DB connection."""
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.integration
def test_health_ready_returns_200_with_db(seeded_db):
    """D-20 readiness: /health/ready must SELECT and return 200 when DB is available."""
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
```

**Marker pattern** (`pyproject.toml` lines 39-42 — already registered, use as-is):
```toml
[tool.pytest.ini_options]
markers = [
    "integration: marks tests as requiring a live database",
    "live_llm: marks tests as hitting real DeepSeek/Kimi APIs",
]
```

Run fast suite (mocked, no network): `uv run pytest -q -m "not integration and not live_llm"`

---

## Shared Patterns

### uv Toolchain (applies to ALL new files and workflows)
**Source:** `pyproject.toml` + CLAUDE.md Tooling Rule
```bash
uv add resend==2.32.2           # adds to pyproject.toml + uv.lock
uv sync --frozen --no-dev       # Docker runtime install (lockfile authoritative)
uv run pytest -q -m "not integration and not live_llm"   # fast test run
```
Never use `pip`, never hand-edit `uv.lock`, never create a standalone `requirements.txt`.

### Parameterized SQL Discipline (applies to all DB-touching code)
**Source:** `scripts/reset_stuck_runs.py` lines 43-51, `app/db/seed.py` lines 321-399
```python
# CORRECT — parameterized (the project's locked rule)
c.execute(
    "UPDATE employees SET known_aliases = %s WHERE id = ANY(%s::uuid[])",
    (new_aliases, [str(eid) for eid in employee_ids]),
)
# WRONG — never f-string SQL
c.execute(f"UPDATE employees SET known_aliases = '{alias}' WHERE id = '{eid}'")
```

### psycopg3 Connection Context (applies to all scripts touching the DB)
**Source:** `scripts/reset_stuck_runs.py` line 34, `app/db/supabase.py` lines 54-65
```python
# Script pattern (reset_stuck_runs.py style)
with repo._conn_ctx(None) as (c, _owns):
    c.execute(...)

# App pattern (supabase.py style)
from app.db.supabase import get_connection
with get_connection() as conn:
    with conn.transaction():
        conn.execute(...)
```

### prepare_threshold=None — Already Set, Do Not Regress
**Source:** `app/db/supabase.py` line 46 — `kwargs={"prepare_threshold": None}`
This is already correct for Supavisor transaction mode (port 6543). D-15 adds one nuance: run `schema.sql` + seed over the **session pooler (port 5432)** during D-09a to avoid DDL issues under transaction-mode pooling.

### Crash-Safe Intent-Before-Side-Effect (D-13c — SCHEMA-SAFE VERSION, HIGH-1 WAIVE)
**Source:** `app/email/gateway.py` lines 63-70 (stub comment), Phase 5 D-13c decision, 06-04 HIGH-1 WAIVE

CRITICAL: email_messages has NO `provider_message_id` or `updated_at` columns.
The repo helpers set ONLY `send_state` in UPDATE SQL. The provider id is logged, not persisted.
The function returns the SYNTHETIC message_id (the RFC anchor), not Resend's internal id.

```python
# WRITE durable record BEFORE irreversible external call (D-13c pattern)
repo.insert_email_message(..., send_state="reserved", conn=conn)   # intent row first
response = resend.Emails.send({...})                                # provider call second
provider_id = response["id"]                                        # logged only, NOT persisted
logger.info("send provider_id=%s", provider_id)
# Flip to 'sent' — UPDATE email_messages SET send_state='sent' WHERE message_id=synthetic_id
# DO NOT write provider_id (column does not exist — ProgrammingError at runtime)
repo.update_email_message_state(synthetic_message_id, "sent", conn=conn)
return synthetic_message_id   # RFC anchor — NOT the provider id
```

### Error Handling (applies to route handlers)
**Source:** `app/main.py` lines 184-187, 201-207 — return `JSONResponse(status_code=200)` for non-error duplicate/unknown-sender cases; raise `HTTPException` only for actual errors.
```python
# Soft stop (not an error — duplicate, unknown sender): return 200 with status key
return JSONResponse(status_code=200, content={"status": "duplicate", ...})

# Hard stop (configuration error, auth failure): raise HTTPException
raise HTTPException(status_code=400, detail="invalid webhook signature")
raise HTTPException(status_code=503, detail="database not ready")
```

### FakeConnection Mock Pattern (applies to all new gateway tests)
**Source:** `tests/conftest.py` lines 37-123 + `tests/test_gateway.py` lines 63-88
```python
def test_new_gateway_behavior(fake_conn):   # fake_conn fixture from conftest.py
    result = gateway.send_outbound(run_id=..., conn=fake_conn)
    sql, params = fake_conn.last()
    assert "expected_table" in str(sql)
    assert "expected_value" in str(params)
```
For external SDK calls (resend.EmailsReceiving.get, resend.Emails.send, resend.Webhooks.verify) use `monkeypatch.setattr` on the resend module, not FakeConnection.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `Dockerfile` | config | — | No Docker artifacts exist in the repo; use Astral uv-docker-example pattern from RESEARCH.md §5 |
| `render.yaml` | config | — | No Render config exists in the repo; use RESEARCH.md §6 verified schema |

---

## Metadata

**Analog search scope:** `app/`, `scripts/`, `tests/`, `.github/workflows/`, root config files
**Files read:** `app/email/gateway.py`, `app/main.py`, `app/config.py`, `app/models/contracts.py`, `app/db/supabase.py`, `app/db/seed.py`, `scripts/reset_stuck_runs.py`, `tests/test_gateway.py`, `tests/test_ingest.py`, `tests/test_dashboard.py`, `tests/conftest.py`, `.github/workflows/eval.yml`, `pyproject.toml`, `.env.example`
**Files scanned total:** 14
**Pattern extraction date:** 2026-06-23
**MEDIUM-3 fix (Round-4):** Stale `provider_message_id`/`updated_at` send-pattern removed from D-13c blocks (both the gateway section and Shared Patterns). The SCHEMA-SAFE VERSION is the authoritative pattern: provider id logged only, NOT persisted; UPDATE sets ONLY send_state WHERE synthetic_message_id; return value is the synthetic message_id (RFC anchor).
