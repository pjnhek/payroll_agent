"""Bounded execution outcomes shared by pipeline producers and queue consumers.

The result deliberately contains no exception object or free-form diagnostic text. Provider
exceptions can carry prompts, responses, email content, or names, so classification reduces
them to a fixed stage/reason vocabulary before they cross the pipeline boundary.
"""
from __future__ import annotations

import dataclasses
import enum

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from pydantic import ValidationError


class PipelineOutcome(enum.StrEnum):
    """Coarse transport outcome; business actions remain outside this vocabulary."""

    OK = "ok"
    RETRYABLE = "retryable"
    TERMINAL = "terminal"


class PipelineStage(enum.StrEnum):
    """Bounded stage active when pipeline execution stopped."""

    UNKNOWN = "unknown"
    LOAD = "load"
    EXTRACT = "extract"
    PERSIST = "persist"
    CLARIFICATION = "clarification"
    COMPUTE = "compute"
    DELIVERY = "delivery"


class PipelineReason(enum.StrEnum):
    """PII-safe reason codes that callers may persist or render."""

    UNCLASSIFIED = "unclassified"
    PROVIDER_CONNECTION_FAILURE = "provider_connection_failure"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_RATE_LIMIT = "provider_rate_limit"
    PROVIDER_SERVER_FAILURE = "provider_server_failure"
    SCHEMA_OR_PARSE_FAILURE = "schema_or_parse_failure"
    CLIENT_REQUEST_FAILURE = "client_request_failure"
    AMBIGUOUS_SEND_FAILURE = "ambiguous_send_failure"
    INVALID_OPERATOR_OVERRIDE_CONTEXT = "invalid_operator_override_context"


@dataclasses.dataclass(frozen=True)
class PipelineResult:
    """A safe-default result containing bounded values only."""

    outcome: PipelineOutcome = PipelineOutcome.TERMINAL
    stage: PipelineStage = PipelineStage.UNKNOWN
    reason: PipelineReason = PipelineReason.UNCLASSIFIED

    @property
    def diagnostic_code(self) -> str:
        """Return a stable code derived only from the bounded stage and reason."""

        return f"{self.stage.value}:{self.reason.value}"


def classify_pipeline_exception(stage: PipelineStage, exc: Exception) -> PipelineResult:
    """Classify ``exc`` without retaining or formatting its potentially sensitive content.

    Only extraction has replay-safe provider failures in this phase. A clarification or
    delivery timeout can occur after provider acceptance, so every provider failure at those
    send stages remains terminal until idempotent replay exists.
    """

    if isinstance(exc, ValidationError):
        return PipelineResult(
            stage=stage,
            reason=PipelineReason.SCHEMA_OR_PARSE_FAILURE,
        )

    if stage in (PipelineStage.CLARIFICATION, PipelineStage.DELIVERY) and isinstance(
        exc, (APIConnectionError, APIStatusError)
    ):
        return PipelineResult(
            stage=stage,
            reason=PipelineReason.AMBIGUOUS_SEND_FAILURE,
        )

    if stage is PipelineStage.EXTRACT:
        if isinstance(exc, APITimeoutError):
            return PipelineResult(
                outcome=PipelineOutcome.RETRYABLE,
                stage=stage,
                reason=PipelineReason.PROVIDER_TIMEOUT,
            )
        if isinstance(exc, APIConnectionError):
            return PipelineResult(
                outcome=PipelineOutcome.RETRYABLE,
                stage=stage,
                reason=PipelineReason.PROVIDER_CONNECTION_FAILURE,
            )
        if isinstance(exc, RateLimitError):
            return PipelineResult(
                outcome=PipelineOutcome.RETRYABLE,
                stage=stage,
                reason=PipelineReason.PROVIDER_RATE_LIMIT,
            )
        if isinstance(exc, APIStatusError):
            if exc.status_code >= 500:
                return PipelineResult(
                    outcome=PipelineOutcome.RETRYABLE,
                    stage=stage,
                    reason=PipelineReason.PROVIDER_SERVER_FAILURE,
                )
            return PipelineResult(
                stage=stage,
                reason=PipelineReason.CLIENT_REQUEST_FAILURE,
            )

    return PipelineResult(stage=stage)


def normalize_pipeline_result(value: PipelineResult) -> PipelineResult:
    """Validate the exact producer contract at dynamic forwarding boundaries.

    Static typing closes normal application call sites. This runtime check keeps dynamic
    handler lookup, injected providers, and test doubles from silently treating ``None``
    or any other unsound value as successful execution.
    """

    if not isinstance(value, PipelineResult):
        raise TypeError(f"expected PipelineResult, got {type(value).__name__}")
    return value
