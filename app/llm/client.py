"""The ONE OpenAI-compatible client wrapper (LLM-01 / LLM-02).

A single call surface that every judgment stage imports. It routes per tier by
swapping `base_url`/`model`/`api_key` from `Settings` (config-driven, so
re-pointing a tier is a one-line env change), enters JSON mode, validates the
untrusted model output against a Pydantic contract, and does ONE reflective
retry on a `ValidationError`/empty content before raising.

Design locks — do not "simplify" any of these away:
- `response_format={"type": "json_object"}` + `model_validate_json`, NOT the strict
  structured-output helper. DeepSeek does not support strict `json_schema`, so the
  strict helper would fail against half the providers and break the goal of one
  provider-agnostic client.
- `temperature=0` on every structured call: deterministic, eval-stable extraction.
  There is no confidence gate to fall back on — the decision is pure code.
- DeepSeek's thinking vs non-thinking is a per-REQUEST body toggle, not a model name,
  so the wrapper must explicitly select non-thinking for any deepseek-* tier or the
  tier silently runs as a reasoning model.
- EXACTLY ONE reflective retry: on failure the validation error is fed back into the
  prompt ("your last output failed: <error>, return valid JSON"), then a second
  attempt. A second failure raises, the orchestrator catches it, and the run is
  persisted to ERROR — a failed extraction must never silently become a payroll.

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

# The two model tiers: extraction + draft. The decision is pure code and calls NO
# model, so there is deliberately no decision/mid tier.
Tier = Literal["extraction", "draft"]

# High enough that a structured JSON object can't be cut off mid-stream. A truncated
# response is invalid JSON, which burns the single retry on a purely mechanical failure.
_MAX_TOKENS = 2048

# The structured-call timeout, and why max_retries=0 travels with it.
#
# Left implicit, the OpenAI client inherits the library's raw 10-minute HTTP timeout AND
# its own `max_retries=2` default — and that library retry layer sits BENEATH the app's
# single reflective retry-on-parse-failure loop (`for attempt in (1, 2):` below), so the
# two COMPOUND. Worst-case single-stage latency would be
# `timeout x 3 library-attempts x 2 app-attempts` = SIX times the timeout, not the 2x a
# reader would assume from the app's retry loop alone. `max_retries=0` makes the app's
# single reflective retry the ONLY retry layer, collapsing the ceiling to exactly
# `_STRUCTURED_TIMEOUT_S x 2 app-attempts`. Keep both pinned together.
#
# This function is the call surface for BOTH extract() (app/pipeline/extract.py) AND
# suggest_employees() (app/pipeline/suggest.py), so this one constant plus the one
# client-construction change bounds both call sites at once.
#
# The resume path's round-2 branch (app/pipeline/orchestrator.py) calls extract() TWICE
# back-to-back before its next DB write, so the real worst-case gap on THAT path is
# `_STRUCTURED_TIMEOUT_S x 2 app-attempts x 2 extractions`. That figure is what the
# stale-run sweep threshold (runs.py's STALE_THRESHOLD) is derived against — raising this
# timeout without revisiting that threshold would let the sweep kill live runs.
#
# 45s is scaled up from compose_confirmation's timeout_s=3.0 (a much lighter free-text
# call) to a bound generous enough for a full structured-JSON extraction round-trip of a
# real payroll email, while keeping the sweep threshold short and useful.
_STRUCTURED_TIMEOUT_S = 45.0

# ⚠️ CONFIRM the exact param + placement against the DeepSeek console.
# DeepSeek selects non-thinking via a per-request body toggle; it is sent through the
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
    surfaces clearly even when no DATABASE_URL is set in the environment — otherwise a
    typo'd tier name would surface as a confusing settings-validation failure instead.
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

    `response_model` MUST be a single Pydantic `BaseModel` (never a bare `list[...]`)
    because the wrapper validates via `model_validate_json`. The extraction tier
    validates an `ExtractionPayload` (which has no `run_id`) — never `Extracted`
    directly — because `Extracted.run_id` is code-owned, not model output. Letting the
    model supply a run_id would let it address a payroll to a different run; the stage
    stamps the run_id itself after this returns.

    On a `ValidationError` or empty content the wrapper retries EXACTLY once with the
    error fed back into the prompt; a second failure raises.
    """
    cfg = _resolve_tier(tier)
    # Explicit bounded timeout= AND max_retries=0 — see _STRUCTURED_TIMEOUT_S's comment
    # above for the compounding-retry rationale. Both must stay.
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

    `timeout_s`: optional hard timeout in seconds passed to the OpenAI client.
    compose_confirmation passes `timeout_s=3.0` to bound cold-dyno latency; a
    TimeoutError propagates to the caller's except-all clause, which falls through to
    the deterministic template floor — so a slow provider degrades the email's prose,
    never the run. Fake-LLM stubs in tests must accept **kwargs, or passing timeout_s=
    raises TypeError.

    `max_retries=0` is set UNCONDITIONALLY below — not gated on whether `timeout_s` was
    passed. Unlike `call_structured`, `call_text` has NO app-level reflective retry
    loop, so the openai library's own `max_retries=2` default would be the ONLY retry
    layer here: even with `timeout_s` set, the real worst case would be `timeout_s x 3`
    (1 original + 2 library retries), not `timeout_s x 1`. Suppressing the library
    retries collapses every caller's worst case to `timeout_s x 1` (or the raw library
    default x 1 when no timeout was passed — still no compounding). Re-enabling library
    retries here would silently triple every drafting call's latency ceiling.
    """
    cfg = _resolve_tier(tier)
    # Pass the hard timeout to the OpenAI client when the caller supplied one, and
    # suppress the library's own retry layer for every call_text caller.
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
