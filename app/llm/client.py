"""The ONE OpenAI-compatible client wrapper (LLM-01 / LLM-02).

A single call surface that every judgment stage imports. It routes per tier by
swapping `base_url`/`model`/`api_key` from `Settings` (config-driven, so
re-pointing a tier is a one-line env change), enters JSON mode, validates the
untrusted model output against a Pydantic contract, and does ONE reflective
retry on a `ValidationError`/empty content before raising.

Design locks (CLAUDE.md / CONTEXT D-A2-02/03 / RESEARCH §Pattern 2):
- `response_format={"type": "json_object"}` + `model_validate_json` — NOT the
  strict structured-output helper (DeepSeek lacks strict `json_schema`, which
  would break the one-provider-agnostic-client goal).
- `temperature=0` on every structured call — temperature 0 for deterministic,
  eval-stable extraction (no confidence gate exists; the decision is pure code).
- DeepSeek's thinking vs non-thinking is a per-REQUEST toggle in V4, not a model
  name — so the wrapper must explicitly select non-thinking in the request body
  for any deepseek-* tier. The exact field placement is an open console blocker
  (STATE.md provider-IDs item); coded here as the documented best guess.
- EXACTLY ONE reflective retry: on failure the validation error is fed back into
  the prompt ("your last output failed: <error>, return valid JSON"), then a
  second attempt; a second failure raises → the orchestrator catches it and
  persists the run to ERROR (D-A1-03).

The free-text drafting path (`call_text`) is the ONE call that does NOT use JSON
mode and may run warmer than 0; on empty content it returns None so the caller
templates a fallback body and a draft failure never strands the run.
"""
from __future__ import annotations

import copy
from typing import Literal, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.config import get_settings

# The two model tiers (D-21-05): extraction + draft. The decision is pure code and
# calls NO model, so the mid/decision tier was removed in Phase 2.1.
Tier = Literal["extraction", "draft"]

T = TypeVar("T", bound=BaseModel)

# High enough that a structured JSON object can't be cut off mid-stream
# (RESEARCH Pattern 2 non-negotiable; DeepSeek truncation guard).
_MAX_TOKENS = 2048

# ⚠️ CONFIRM exact param + placement from the DeepSeek console (STATE.md blocker).
# DeepSeek V4 selects non-thinking via a per-request body toggle; sent through the
# openai client's `extra_body` passthrough.
_NON_THINKING_EXTRA_BODY = {"thinking": {"type": "disabled"}}


class _TierConfig:
    """Resolved (base_url, model, api_key) for one tier."""

    __slots__ = ("base_url", "model", "api_key")

    def __init__(self, base_url: str, model: str, api_key: str) -> None:
        self.base_url = base_url
        self.model = model
        self.api_key = api_key


def _resolve_tier(tier: Tier) -> _TierConfig:
    """Map a tier name to its Settings triple. Never hardcodes a URL/model/key.

    Tier validity is checked BEFORE get_settings() so an unknown-tier ValueError
    surfaces clearly (D-21-05) even when no DATABASE_URL is set in the environment.
    """
    # Guard first: fail fast on unknown tier before loading settings.
    if tier not in ("extraction", "draft"):
        raise ValueError(f"unknown tier: {tier!r}")
    settings = get_settings()
    if tier == "extraction":
        return _TierConfig(
            settings.extraction_base_url,
            settings.extraction_model,
            settings.extraction_api_key,
        )
    # tier == "draft"
    return _TierConfig(
        settings.draft_base_url,
        settings.draft_model,
        settings.draft_api_key,
    )


def _is_deepseek(model: str) -> bool:
    return "deepseek" in model.lower()


def call_structured(
    tier: Tier,
    messages: list[dict],
    response_model: type[T],
) -> T:
    """Make a JSON-mode structured call for `tier`, validated against `response_model`.

    `response_model` MUST be a single Pydantic `BaseModel` (never a bare
    `list[...]`) because the wrapper validates via `model_validate_json`. The
    extraction tier validates an `ExtractionPayload` (no `run_id`) — never
    `Extracted` directly — because `Extracted.run_id` is code-owned, not an LLM
    output (FIX A; the stage stamps the run_id after this returns).

    On a `ValidationError` or empty content the wrapper retries EXACTLY once with
    the error fed back into the prompt; a second failure raises.
    """
    cfg = _resolve_tier(tier)
    client = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)

    extra: dict = {}
    if _is_deepseek(cfg.model):
        extra["extra_body"] = _NON_THINKING_EXTRA_BODY

    # Copy so feeding the validation error back never mutates the caller's list.
    convo = list(messages)

    last_error: ValidationError | None = None
    for attempt in (1, 2):  # ONE reflective retry (CLAUDE.md locks ONE)
        resp = client.chat.completions.create(
            model=cfg.model,
            messages=convo,
            temperature=0,
            response_format={"type": "json_object"},
            max_tokens=_MAX_TOKENS,
            **extra,
        )
        content = resp.choices[0].message.content
        try:
            if not content:  # DeepSeek can return empty content — treat as failure
                raise ValueError("empty content from model")
            return response_model.model_validate_json(content)
        except (ValidationError, ValueError) as exc:
            if attempt == 2:
                # Second failure → propagate. A ValidationError propagates as-is;
                # an empty-content ValueError is normalized to a ValidationError so
                # the orchestrator has one failure type to catch.
                if isinstance(exc, ValidationError):
                    raise
                if last_error is not None:
                    raise last_error
                raise ValidationError.from_exception_data(
                    response_model.__name__, []
                ) from exc
            if isinstance(exc, ValidationError):
                last_error = exc
            convo = convo + [
                {
                    "role": "user",
                    "content": (
                        f"Your last output failed validation: {exc}. "
                        "Return ONLY valid JSON matching the schema."
                    ),
                }
            ]
    # Unreachable: the loop either returns or raises on attempt 2.
    raise AssertionError("call_structured loop exited without return/raise")  # pragma: no cover


def call_text(
    tier: Tier,
    messages: list[dict],
    temperature: float = 0.7,
    timeout_s: float | None = None,
    **kwargs,
) -> str | None:
    """Free-text (drafting) call — raw string content, NO JSON mode.

    This is the ONLY call that does not enter JSON mode and may run warmer than 0
    (the clarification email is prose, not a schema). On empty content it returns
    None so the caller falls back to a templated body — a draft failure never
    strands the run (no schema retry, no raise).

    `timeout_s` (D-10b): optional hard timeout in seconds passed to the OpenAI
    client. compose_confirmation passes `timeout_s=3.0` to bound cold-dyno latency;
    a TimeoutError propagates to the caller's except-all clause which falls through
    to the deterministic template floor (D-10b, T-05-10). Fake-LLM stubs in tests
    must accept **kwargs so passing timeout_s= does not raise TypeError (MEDIUM fix,
    T-05-11b).
    """
    cfg = _resolve_tier(tier)
    # Pass timeout to the OpenAI client if provided (D-10b hard timeout).
    client_kwargs: dict = {}
    if timeout_s is not None:
        client_kwargs["timeout"] = timeout_s
    client = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key, **client_kwargs)

    extra: dict = {}
    if _is_deepseek(cfg.model):
        extra["extra_body"] = copy.deepcopy(_NON_THINKING_EXTRA_BODY)

    resp = client.chat.completions.create(
        model=cfg.model,
        messages=list(messages),
        temperature=temperature,
        max_tokens=_MAX_TOKENS,
        **extra,
    )
    content = resp.choices[0].message.content
    return content if content else None
