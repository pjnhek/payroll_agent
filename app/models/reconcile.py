"""Layer-2 reconciliation structured-output wrapper (review FIX 6).

`call_structured` validates an untrusted model response via
`response_model.model_validate_json`, which requires a single Pydantic
`BaseModel` — a bare `list[NameMatchResult]` has no `model_validate_json` and so
cannot be the response_model. `NameReconciliationResponse` is that wrapper: the
layer-2 LLM returns a JSON object `{"matches": [...]}`, the wrapper validates it,
and the reconcile stage unwraps `.matches` into the merged `list[NameMatchResult]`.

`extra="forbid"` (the project-wide contract convention) means a stray top-level
key in the model output raises a `ValidationError`, routed through the client's
one reflective retry — an untrusted model can't smuggle extra fields past the
schema (T-03-03).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.roster import NameMatchResult


class NameReconciliationResponse(BaseModel):
    """The layer-2 structured-output schema: a `matches` list wrapper.

    Each `NameMatchResult` classifies one RESIDUAL submitted name (a name that
    failed deterministic layer-1) as `llm_typo` / `llm_nickname` / `unknown` with
    a per-name `confidence` (Decimal 0–1) and a `reason`. The stage unwraps
    `.matches` and merges it with the layer-1 hits (one result per submitted
    name); the 0.8 gate in decide.py keys off each per-name confidence.
    """

    model_config = ConfigDict(extra="forbid")

    matches: list[NameMatchResult]
