"""Bounded execution outcomes shared by pipeline producers and queue consumers.

The result deliberately contains no exception object or free-form diagnostic text. Provider
exceptions can carry prompts, responses, email content, or names, so classification reduces
them to a fixed stage/reason vocabulary before they cross the pipeline boundary.
"""
from __future__ import annotations

import dataclasses
import enum
from datetime import datetime, timedelta

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from pydantic import ValidationError
from resend.exceptions import ResendError


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
    DELIVERY_TIMEOUT = "delivery_timeout"
    DELIVERY_CONNECTION_FAILURE = "delivery_connection_failure"
    DELIVERY_RATE_LIMIT = "delivery_rate_limit"
    DELIVERY_SERVER_FAILURE = "delivery_server_failure"
    DELIVERY_IDEMPOTENCY_PAYLOAD_MISMATCH = "delivery_idempotency_payload_mismatch"
    DELIVERY_QUOTA_EXHAUSTED = "delivery_quota_exhausted"
    DELIVERY_VALIDATION_FAILURE = "delivery_validation_failure"
    DELIVERY_AUTHENTICATION_FAILURE = "delivery_authentication_failure"
    DELIVERY_AUTHORIZATION_FAILURE = "delivery_authorization_failure"
    DELIVERY_CONFIGURATION_FAILURE = "delivery_configuration_failure"
    DELIVERY_PROVIDER_FAILURE = "delivery_provider_failure"
    DELIVERY_RECORD_ONLY = "delivery_record_only"
    DELIVERY_AUTHORIZATION_EXPIRED = "delivery_authorization_expired"


@dataclasses.dataclass(frozen=True)
class DeliverySendBudget:
    """The immutable provider-I/O budget reserved inside a handoff deadline."""

    timeout_seconds: int
    safety_margin: timedelta


DELIVERY_SEND_BUDGET = DeliverySendBudget(
    timeout_seconds=10,
    safety_margin=timedelta(seconds=5),
)


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

    if stage is PipelineStage.DELIVERY:
        return classify_delivery_exception(exc)

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


_DELIVERY_REPLAY_OFFSETS = (
    timedelta(),
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=3),
    timedelta(hours=8),
    timedelta(hours=16),
)
_DELIVERY_REPLAY_WINDOW = timedelta(hours=20)


def classify_delivery_exception(exc: Exception) -> PipelineResult:
    """Reduce a Resend send failure to its bounded replay policy outcome."""

    retryable_reason: PipelineReason | None = None
    if isinstance(exc, (TimeoutError, httpx.TimeoutException, APITimeoutError)):
        retryable_reason = PipelineReason.DELIVERY_TIMEOUT
    elif isinstance(exc, (ConnectionError, httpx.ConnectError, APIConnectionError)):
        retryable_reason = PipelineReason.DELIVERY_CONNECTION_FAILURE
    elif isinstance(exc, RateLimitError):
        retryable_reason = PipelineReason.DELIVERY_RATE_LIMIT
    elif isinstance(exc, APIStatusError) and exc.status_code >= 500:
        retryable_reason = PipelineReason.DELIVERY_SERVER_FAILURE

    if retryable_reason is not None:
        return PipelineResult(
            outcome=PipelineOutcome.RETRYABLE,
            stage=PipelineStage.DELIVERY,
            reason=retryable_reason,
        )

    if isinstance(exc, ResendError):
        error_type = str(exc.error_type).lower()
        try:
            status_code = int(exc.code)
        except (TypeError, ValueError):
            status_code = None

        if error_type == "rate_limit_exceeded" and status_code == 429:
            return _delivery_retryable(PipelineReason.DELIVERY_RATE_LIMIT)
        if error_type in {"daily_quota_exceeded", "monthly_quota_exceeded"}:
            return _delivery_terminal(PipelineReason.DELIVERY_QUOTA_EXHAUSTED)
        if status_code is not None and 500 <= status_code < 600:
            return _delivery_retryable(PipelineReason.DELIVERY_SERVER_FAILURE)
        if status_code == 409 and error_type == "invalid_idempotent_request":
            return _delivery_terminal(PipelineReason.DELIVERY_IDEMPOTENCY_PAYLOAD_MISMATCH)
        if error_type in {"validation_error", "missing_required_fields"} or status_code in {
            400,
            422,
        }:
            return _delivery_terminal(PipelineReason.DELIVERY_VALIDATION_FAILURE)
        if error_type == "missing_api_key":
            return _delivery_terminal(PipelineReason.DELIVERY_CONFIGURATION_FAILURE)
        if status_code == 401:
            return _delivery_terminal(PipelineReason.DELIVERY_AUTHENTICATION_FAILURE)
        if status_code == 403:
            return _delivery_terminal(PipelineReason.DELIVERY_AUTHORIZATION_FAILURE)

    return _delivery_terminal(PipelineReason.DELIVERY_PROVIDER_FAILURE)


def _delivery_retryable(reason: PipelineReason) -> PipelineResult:
    return PipelineResult(
        outcome=PipelineOutcome.RETRYABLE,
        stage=PipelineStage.DELIVERY,
        reason=reason,
    )


def _delivery_terminal(reason: PipelineReason) -> PipelineResult:
    return PipelineResult(stage=PipelineStage.DELIVERY, reason=reason)


def delivery_replay_allowed(reserved_at: datetime, now: datetime) -> bool:
    """Return whether a claimed reservation is still inside the fixed replay window."""

    return now < reserved_at + _DELIVERY_REPLAY_WINDOW


def next_delivery_attempt_at(
    reserved_at: datetime, *, completed_attempts: int
) -> datetime | None:
    """Return the next fixed reservation-time slot, or ``None`` when replay must stop."""

    if completed_attempts < 0:
        raise ValueError("completed_attempts must be non-negative")
    if completed_attempts >= len(_DELIVERY_REPLAY_OFFSETS):
        return None
    scheduled_at = reserved_at + _DELIVERY_REPLAY_OFFSETS[completed_attempts]
    if not delivery_replay_allowed(reserved_at, scheduled_at):
        return None
    return scheduled_at


def normalize_pipeline_result(value: PipelineResult) -> PipelineResult:
    """Validate the exact producer contract at dynamic forwarding boundaries.

    Static typing closes normal application call sites. This runtime check keeps dynamic
    handler lookup, injected providers, and test doubles from silently treating ``None``
    or any other unsound value as successful execution.
    """

    if not isinstance(value, PipelineResult):
        raise TypeError(f"expected PipelineResult, got {type(value).__name__}")
    return value
