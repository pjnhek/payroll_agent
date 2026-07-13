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
from typing import Literal

from openai import NOT_GIVEN, OpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ValidationError

from app.config import get_settings

# The two model tiers (D-21-05): extraction + draft. The decision is pure code and
# calls NO model, so the mid/decision tier was removed in Phase 2.1.
Tier = Literal["extraction", "draft"]

# High enough that a structured JSON object can't be cut off mid-stream
# (RESEARCH Pattern 2 non-negotiable; DeepSeek truncation guard).
_MAX_TOKENS = 2048

# 09-04 (Codex HIGH-3, closing RESEARCH.md Assumption A1): call_structured's
# OpenAI(...) client construction previously passed NO explicit `timeout=`, so it
# inherited the openai library's raw 10-minute HTTP timeout — AND the library's own
# `max_retries=2` default applies BENEATH (independent of) the app's own single
# reflective retry-on-parse-failure loop (`for attempt in (1, 2):` below). Without
# an explicit `max_retries=0` override, the true worst-case single-stage latency was
# `timeout x 3 library-attempts x 2 app-attempts` = 6x the timeout, not the 2x a
# reader would assume from the app's own retry loop alone. Setting `max_retries=0`
# makes the app's single reflective retry the ONLY retry layer for this call,
# collapsing the ceiling to exactly `_STRUCTURED_TIMEOUT_S x 2 app-attempts`.
#
# This same function is the call surface for BOTH extract() (app/pipeline/extract.py)
# AND suggest_employees() (app/pipeline/suggest.py:81, `llm.call_structured("draft",
# messages, NameSuggestionResponse)`) — so this one constant + one client-construction
# change bounds both call sites at once (Codex HIGH-3).
#
# resume_pipeline's Round-2 branch (app/pipeline/orchestrator.py:377,380) calls
# extract() TWICE back-to-back (raw_reply_extracted, then raw_extracted) before its
# next DB write — the real worst-case gap on THAT path is
# `_STRUCTURED_TIMEOUT_S x 2 app-attempts x 2 extractions`, not a single-call figure.
# 45s is scaled up from compose_confirmation's timeout_s=3.0 (a much lighter
# free-text call) to a bound generous enough for a full structured-JSON extraction
# round-trip of a real payroll email, while still keeping the sweep threshold
# (app/main.py's STALE_THRESHOLD_SECONDS) short and useful (RESEARCH.md Pitfall 1
# recommendation #1).
_STRUCTURED_TIMEOUT_S = 45.0

# ⚠️ CONFIRM exact param + placement from the DeepSeek console (STATE.md blocker).
# DeepSeek V4 selects non-thinking via a per-request body toggle; sent through the
# openai client's `extra_body` passthrough.
_NON_THINKING_EXTRA_BODY: dict[str, dict[str, str]] = {
    "thinking": {"type": "disabled"}
}


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


def _scrubbed_validation_summary(exc: ValidationError | ValueError) -> str:
    """Describe a validation failure WITHOUT echoing the model's own output.

    A ValidationError stringifies with the offending input embedded
    (`input_value='...'`), and the retry prompt goes back out to the provider — so
    interpolating it verbatim would return untrusted model output to a third party.
    `include_input=False` keeps the actionable half (where it failed, what the schema
    wanted: `msg` is pydantic's generic description, e.g. "Input should be a valid
    number") and drops the value itself. The empty-content ValueError carries no model
    output, so it passes through as-is.
    """
    if not isinstance(exc, ValidationError):
        return str(exc)
    parts = [
        f"{'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['type']} — {err['msg']}"
        for err in exc.errors(include_url=False, include_input=False)
    ]
    return "; ".join(parts) if parts else "output did not match the schema"


def call_structured[T: BaseModel](
    tier: Tier,
    messages: list[ChatCompletionMessageParam],
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
    # 09-04: explicit bounded timeout= AND max_retries=0 — see _STRUCTURED_TIMEOUT_S's
    # comment above for the full compounding-retry rationale (Codex HIGH-3).
    client = OpenAI(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        timeout=_STRUCTURED_TIMEOUT_S,
        max_retries=0,
    )

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
            # extra_body=None is the SDK default (nothing sent on the wire):
            # only DeepSeek tiers get the non-thinking toggle.
            extra_body=_NON_THINKING_EXTRA_BODY if _is_deepseek(cfg.model) else None,
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
                    raise last_error from exc
                raise ValidationError.from_exception_data(
                    response_model.__name__, []
                ) from exc
            if isinstance(exc, ValidationError):
                last_error = exc
            convo = convo + [
                {
                    "role": "user",
                    "content": (
                        "Your last output failed validation: "
                        f"{_scrubbed_validation_summary(exc)}. "
                        "Return ONLY valid JSON matching the schema."
                    ),
                }
            ]
    # Unreachable: the loop either returns or raises on attempt 2.
    raise AssertionError("call_structured loop exited without return/raise")  # pragma: no cover


def call_text(
    tier: Tier,
    messages: list[ChatCompletionMessageParam],
    temperature: float = 0.7,
    timeout_s: float | None = None,
    **kwargs: object,
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

    09-04 (Codex round-2, STILL-OPEN HIGH — closed here): `call_text` has NO
    app-level reflective retry loop (unlike `call_structured`'s `for attempt in
    (1, 2):`), so the openai library's own `max_retries=2` default was the ONLY
    retry layer on this call path — meaning even with `timeout_s` set, the true
    worst case was `timeout_s x 3` (1 original + 2 library retries), not
    `timeout_s x 1`. `max_retries=0` is therefore set UNCONDITIONALLY below
    (independent of whether `timeout_s` was passed — a caller may want
    retry-suppression even without a custom timeout), collapsing every
    `call_text` caller's worst case to `timeout_s x 1` when a timeout is set (or
    to the raw library default x 1 when it is not — still no retry compounding).
    This benefits ALL callers automatically, including compose_confirmation's
    existing `timeout_s=3.0` (now `3.0 x 1`, not `3.0 x 3`, as a welcome side
    effect of the fix rather than a scope change to that call site).
    """
    cfg = _resolve_tier(tier)
    # Pass timeout to the OpenAI client if provided (D-10b hard timeout).
    # Unconditional (not gated on timeout_s is not None): suppress the library's
    # own retry layer for every call_text caller (09-04, Codex round-2).
    client = OpenAI(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        # NOT_GIVEN == the kwarg omitted: the library's own default timeout
        # applies when no timeout_s was passed (identical to the old branch).
        timeout=timeout_s if timeout_s is not None else NOT_GIVEN,
        max_retries=0,
    )

    resp = client.chat.completions.create(
        model=cfg.model,
        messages=list(messages),
        temperature=temperature,
        max_tokens=_MAX_TOKENS,
        # extra_body=None is the SDK default (nothing sent on the wire):
        # only DeepSeek tiers get the non-thinking toggle.
        extra_body=copy.deepcopy(_NON_THINKING_EXTRA_BODY)
        if _is_deepseek(cfg.model)
        else None,
    )
    content = resp.choices[0].message.content
    return content if content else None
