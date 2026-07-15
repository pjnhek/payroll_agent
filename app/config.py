"""Application configuration via pydantic-settings.

All sensitive values (DATABASE_URL, API keys) are loaded from environment variables
or a .env file. A missing DATABASE_URL fails fast at startup rather than mid-pipeline.

Usage:
    from app.config import get_settings
    settings = get_settings()
    url = settings.database_url
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env-driven config for the payroll agent.

    database_url deliberately has NO default: a missing env var raises a ValidationError
    at import time, so the problem is visible immediately instead of surfacing as a
    confusing failure mid-pipeline on the first connection attempt.
    """

    # ── Database ──────────────────────────────────────────────────────────────
    # Must point to the Supavisor pooler host (transaction mode, port 6543) —
    # NOT the direct db.<ref>.supabase.co host (IPv6-only; Render/local mismatch).
    database_url: str  # no default — fails fast if unset

    # ── Extraction tier (stronger model) ─────────────────────────────────────
    extraction_model: str = "deepseek-v4-flash"
    extraction_base_url: str = "https://api.deepseek.com"
    extraction_api_key: str = ""

    # ── Drafting tier (cheap model) ───────────────────────────────────────────
    # There are exactly TWO tiers — extraction + drafting. There is deliberately no
    # decision tier: the process-vs-clarify decision is pure code with no model call.
    # The cheap tier also serves the optional clarification-suggestion call.
    draft_model: str = "moonshot-v1-8k"
    draft_base_url: str = "https://api.moonshot.ai/v1"
    draft_api_key: str = ""

    # ── Tax year ──────────────────────────────────────────────────────────────
    # Drives the bracket tables in the Pub 15-T engine. Default 2026.
    tax_year: int = 2026

    # ── Live-LLM opt-in ───────────────────────────────────────────────────────
    # Two-factor guard mirroring the live-DB ALLOW_DB_RESET pattern: the live_llm test
    # suite hits the REAL DeepSeek/Kimi APIs only when this flag is truthy AND the
    # per-tier API keys are present. Default False so CI stays green and free — flipping
    # the default would silently bill every CI run against the real providers.
    allow_live_llm: bool = False

    # ── Email provider (Resend) ───────────────────────────────────────────────
    # Empty-string defaults: missing keys log a warning but do not fail startup —
    # the stub fixture path must still work locally without Resend credentials.
    resend_api_key: str = ""            # RESEND_API_KEY env var
    webhook_signing_secret: str = ""    # WEBHOOK_SIGNING_SECRET env var
    resend_from_addr: str = "onboarding@resend.dev"  # shared free-tier sender (no verified domain)

    # False by default, which is the production-safe value. Setting
    # ALLOW_UNSIGNED_FIXTURES=true enables the dev-mode bypass that skips webhook signature
    # verification when the signing secret is absent — i.e. it lets ANY unsigned POST drive
    # the pipeline. MUST NOT appear in render.yaml `value:` entries; a committed `true` here
    # would ship an unauthenticated webhook to production.
    allow_unsigned_fixtures: bool = False

    # REPLY-TO TOPOLOGY (P6): free-tier FROM=onboarding@resend.dev cannot be replied to;
    # set this to the inbound .resend.app address so client replies route to the webhook.
    # Omitted from send when empty.
    resend_reply_to: str = ""           # RESEND_REPLY_TO env var — inbound .resend.app address

    # ── Durable job queue ──────────────────────────────────────────────────────
    # WORKER_COUNT: 2 daemon threads. `0` is the test/dev off switch —
    # tests/conftest.py pins WORKER_COUNT=0 so the suite never spawns real worker
    # threads. The pool-budget guard that hard-fails boot if this value would
    # exceed the psycopg pool's capacity (WORKER_COUNT + 2 <= max_size) lives in
    # app/queue/worker.py's lifespan — NOT here; this field is a bare knob with
    # no validation of its own.
    worker_count: int = 2

    # LEASE_SECONDS: the load-bearing safety parameter behind the queue's crash
    # recovery. Two things this comment carries:
    #
    # (a) THE DERIVATION, by cross-reference — not re-derived here. app/routes/
    #     runs.py:34-68 already computes and documents STALE_THRESHOLD: the
    #     pipeline's worst-case gap between two consecutive DB writes on the
    #     longest real path is 210s (the resume path's back-to-back double
    #     extraction — 45s x 2 app-retries x 2 calls — plus a 30s clarification
    #     draft), and picks 15 minutes (900s) as ~4x that ceiling. LEASE_SECONDS
    #     reuses that already-reviewed number rather than re-deriving it, so this
    #     is the ONE place either value needs to change — maintaining two
    #     independent copies of the "210s x ~4" arithmetic is exactly the drift
    #     risk this cross-reference exists to avoid.
    #
    # (b) WHAT A DOUBLE-RUN ACTUALLY COSTS — the narrowed, true claim (a
    #     double-run is NOT unconditionally harmless):
    #       - It IS harmless for PIPELINE STATE: claim_status's CAS makes every
    #         status advance at-most-once, and replace_line_items is
    #         DELETE-by-run-then-INSERT (idempotent by value).
    #       - It is NOT intrinsically harmless for the CLIENT-FACING SEND.
    #         gateway.send_outbound writes send_state='reserved', calls the
    #         provider, and only THEN flips to 'sent' (gateway.py:271-289 /
    #         339-345 / 355-359) — while both existing duplicate guards
    #         (emails.py:140-171, emails.py:174-218) count ONLY send_state='sent'
    #         rows. A worker killed between provider-acceptance and the
    #         sent-commit leaves NO 'sent' row while the client already has the
    #         email, so a naive re-run would send a SECOND one.
    #       - That window is closed by app/pipeline/send_guard.py's fail-closed
    #         unconfirmed-reservation guard. One authoritative copy of the
    #         mechanism lives in that guard's own docstring; this comment does
    #         not restate it.
    #
    # (c) NO LEASE HEARTBEAT, and why: a heartbeat would burn a pooled connection
    #     per extension against the max_size=5 budget, and introduce a worse
    #     failure mode (heartbeat thread dies silently, work continues unbounded)
    #     than the one it prevents.
    lease_seconds: int = 900

    # MAX_ATTEMPTS: SCOPING CAVEAT. `attempts` is incremented AT CLAIM (not at
    # failure), so today the counter only advances via a genuine crash-reclaim —
    # there is no retryable/terminal backoff classification yet. So
    # MAX_ATTEMPTS=5 here means "a single retrigger survives up to 5
    # worker-crash cycles before dead-lettering", NOT "5 retries of a classified
    # failure". A later reader adding backoff classification must not assume
    # this constant already encodes that policy — it doesn't.
    max_attempts: int = 5

    # PUMP_TOKEN: the shared secret the external cron sends as
    # `Authorization: Bearer $PUMP_TOKEN` to GET /internal/pump. Empty-default-
    # secret convention (mirrors resend_api_key/webhook_signing_secret above);
    # the fail-closed meaning (reject every call when this is unset/empty)
    # lives in the route's _authorized() check, not as validation on this
    # field — matching how ALLOW_UNSIGNED_FIXTURES gates behavior at its call
    # site rather than in Settings itself.
    pump_token: str = ""        # PUMP_TOKEN env var

    # QUEUE_POLL_SECONDS: the SLOW DURABLE FALLBACK, not the latency path. The
    # in-process threading.Event wake (app/queue/wake.py) is what makes
    # Retrigger feel instant for the demo; this poll exists only to cover what
    # an in-process signal cannot reach — expired-lease reclaims (bounded below
    # by LEASE_SECONDS), future-dated backoff retries, and a cold-started
    # instance where the enqueuing process no longer exists. The band is
    # ~15-30s; 20 splits it. LISTEN/NOTIFY and session advisory locks are NOT
    # available here — they fail SILENTLY under Supavisor transaction-mode
    # pooling (app/db/supabase.py:1-18), which is exactly what forces this
    # Event-plus-slow-poll design. Unlike the other three knobs, this field's
    # env name is not otherwise constrained — it carries the QUEUE_ prefix for
    # legibility.
    queue_poll_seconds: int = 20

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (reads env / .env once)."""
    return Settings()
