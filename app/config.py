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

    D-04: database_url has no default — a missing env var raises a ValidationError
    at import time so the problem is visible immediately, not buried in a later
    connection attempt.
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
    # The mid/decision tier was removed in Phase 2.1 (D-21-05): the decision is pure
    # code with no model call, so there are TWO tiers — extraction + drafting (the
    # cheap tier also serves the optional clarification-suggestion call in Wave 4).
    draft_model: str = "moonshot-v1-8k"
    draft_base_url: str = "https://api.moonshot.ai/v1"
    draft_api_key: str = ""

    # ── Tax year ──────────────────────────────────────────────────────────────
    # Drives the bracket tables in the Pub 15-T engine. Default 2026.
    tax_year: int = 2026

    # ── Live-LLM opt-in (D-A2-01) ─────────────────────────────────────────────
    # Two-factor guard mirroring the live-DB ALLOW_DB_RESET pattern: the live_llm
    # test suite hits the REAL DeepSeek/Kimi APIs only when this flag is truthy
    # AND the per-tier API keys are present. Default False so CI stays green/free.
    allow_live_llm: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (reads env / .env once)."""
    return Settings()
