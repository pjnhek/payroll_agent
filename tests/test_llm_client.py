"""Mocked-LLM tests for app/llm/client.py — the one OpenAI-compatible wrapper.

No network is touched: a FakeOpenAI is injected over the `OpenAI` constructor the
client imports, recording construction kwargs + create() calls and replaying a
scripted sequence of responses. These tests prove the wrapper mechanics
(LLM-01/LLM-02): per-tier routing, temperature=0 + json_object, the DeepSeek
non-thinking toggle, the single reflective retry, raise-on-double-failure, and the
free-text drafting path. Real-model accuracy is the eval's job (Phase 4), not here.

Run with the default CI selection (no markers): these always run, free, offline.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.llm.client import call_structured, call_text


# ---------------------------------------------------------------------------
# A small response_model used purely to exercise the generic structured path.
# The real contracts (ExtractionPayload/Decision) live in app/models and are
# wired by the stage code in Plan 02/03 — the client itself is contract-agnostic
# and only needs *a* BaseModel with model_validate_json.
# ---------------------------------------------------------------------------


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    score: Decimal = Field(ge=0, le=1)


# ---------------------------------------------------------------------------
# Fake OpenAI client — records construction + create() calls, replays a script.
# ---------------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, parent):
        self._parent = parent

    def create(self, **kwargs):
        self._parent.create_calls.append(kwargs)
        # Pop the next scripted content (str or None) for this client instance.
        content = self._parent.script.pop(0)
        return _FakeResponse(content)


class _FakeChat:
    def __init__(self, parent):
        self.completions = _FakeCompletions(parent)


class _FakeOpenAI:
    """Stands in for openai.OpenAI; one instance per call_structured invocation."""

    # Class-level recorders so the test can inspect across the (possibly single)
    # instance the wrapper constructs.
    instances: list["_FakeOpenAI"] = []

    def __init__(self, *, base_url=None, api_key=None, **_):
        self.base_url = base_url
        self.api_key = api_key
        self.create_calls: list[dict] = []
        # Each instance pulls its scripted responses from the class-level queue.
        self.script: list = list(_FakeOpenAI.next_script)
        self.chat = _FakeChat(self)
        _FakeOpenAI.instances.append(self)

    # Per-test scripted responses (list of message.content values, consumed FIFO).
    next_script: list = []


@pytest.fixture(autouse=True)
def _patch_openai(monkeypatch):
    """Inject FakeOpenAI over the `OpenAI` symbol the client module imports."""
    _FakeOpenAI.instances = []
    _FakeOpenAI.next_script = []
    monkeypatch.setattr("app.llm.client.OpenAI", _FakeOpenAI)
    yield


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """get_settings() is lru_cached; clear it so per-test env edits take effect."""
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_tier_env(monkeypatch, *, prefix, model, base_url="https://example.test", key="sk-test"):
    monkeypatch.setenv(f"{prefix}_MODEL", model)
    monkeypatch.setenv(f"{prefix}_BASE_URL", base_url)
    monkeypatch.setenv(f"{prefix}_API_KEY", key)


# ---------------------------------------------------------------------------
# Per-tier routing + valid JSON returns a validated object
# ---------------------------------------------------------------------------


def test_structured_returns_validated_object_and_routes_per_tier(monkeypatch):
    _set_tier_env(
        monkeypatch,
        prefix="EXTRACTION",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.test",
        key="sk-deepseek",
    )
    _FakeOpenAI.next_script = ['{"name": "Ann", "score": "0.9"}']

    out = call_structured(
        tier="extraction",
        messages=[{"role": "user", "content": "return json {\"name\":..., \"score\":...}"}],
        response_model=_Payload,
    )

    assert isinstance(out, _Payload)
    assert out.name == "Ann"
    assert out.score == Decimal("0.9")
    # The OpenAI client was constructed from the EXTRACTION tier config.
    assert len(_FakeOpenAI.instances) == 1
    inst = _FakeOpenAI.instances[0]
    assert inst.base_url == "https://api.deepseek.test"
    assert inst.api_key == "sk-deepseek"
    assert inst.create_calls[0]["model"] == "deepseek-v4-flash"


def test_decision_tier_routes_to_decision_config(monkeypatch):
    _set_tier_env(
        monkeypatch,
        prefix="DECISION",
        model="moonshot-v1-8k",
        base_url="https://api.moonshot.test/v1",
        key="sk-moon",
    )
    _FakeOpenAI.next_script = ['{"name": "Bo", "score": "0.5"}']

    call_structured(
        tier="decision",
        messages=[{"role": "user", "content": "json"}],
        response_model=_Payload,
    )
    inst = _FakeOpenAI.instances[0]
    assert inst.base_url == "https://api.moonshot.test/v1"
    assert inst.create_calls[0]["model"] == "moonshot-v1-8k"


# ---------------------------------------------------------------------------
# DeepSeek non-thinking toggle is sent only for deepseek-model tiers
# ---------------------------------------------------------------------------


def test_deepseek_tier_sends_non_thinking_toggle(monkeypatch):
    _set_tier_env(monkeypatch, prefix="EXTRACTION", model="deepseek-v4-flash")
    _FakeOpenAI.next_script = ['{"name": "Cy", "score": "0.7"}']

    call_structured(
        tier="extraction",
        messages=[{"role": "user", "content": "json"}],
        response_model=_Payload,
    )
    kwargs = _FakeOpenAI.instances[0].create_calls[0]
    assert "extra_body" in kwargs, "deepseek tier must send the non-thinking toggle"
    # The toggle disables thinking (exact param confirmed from the console later).
    assert kwargs["extra_body"]["thinking"]["type"] == "disabled"


def test_non_deepseek_tier_omits_non_thinking_toggle(monkeypatch):
    _set_tier_env(monkeypatch, prefix="DECISION", model="moonshot-v1-8k")
    _FakeOpenAI.next_script = ['{"name": "Di", "score": "0.7"}']

    call_structured(
        tier="decision",
        messages=[{"role": "user", "content": "json"}],
        response_model=_Payload,
    )
    kwargs = _FakeOpenAI.instances[0].create_calls[0]
    assert "extra_body" not in kwargs, "non-deepseek tier must NOT send extra_body"


# ---------------------------------------------------------------------------
# Every structured call sets temperature=0 and response_format json_object
# ---------------------------------------------------------------------------


def test_structured_call_sets_temp0_and_json_object(monkeypatch):
    _set_tier_env(monkeypatch, prefix="EXTRACTION", model="deepseek-v4-flash")
    _FakeOpenAI.next_script = ['{"name": "Ed", "score": "0.7"}']

    call_structured(
        tier="extraction",
        messages=[{"role": "user", "content": "json"}],
        response_model=_Payload,
    )
    kwargs = _FakeOpenAI.instances[0].create_calls[0]
    assert kwargs["temperature"] == 0
    assert kwargs["response_format"] == {"type": "json_object"}


# ---------------------------------------------------------------------------
# Reflective retry: invalid/empty first, valid second → exactly 2 create() calls
# ---------------------------------------------------------------------------


def test_invalid_then_valid_retries_exactly_once(monkeypatch):
    _set_tier_env(monkeypatch, prefix="EXTRACTION", model="deepseek-v4-flash")
    # First response fails schema (score out of range), second succeeds.
    _FakeOpenAI.next_script = [
        '{"name": "Fay", "score": "9.0"}',
        '{"name": "Fay", "score": "0.6"}',
    ]

    out = call_structured(
        tier="extraction",
        messages=[{"role": "user", "content": "json"}],
        response_model=_Payload,
    )
    assert out.score == Decimal("0.6")
    inst = _FakeOpenAI.instances[0]
    assert len(inst.create_calls) == 2, "must retry exactly once on first failure"
    # The retry must feed the validation error back into the messages.
    retry_messages = inst.create_calls[1]["messages"]
    assert len(retry_messages) > len(inst.create_calls[0]["messages"])
    assert "valid JSON" in retry_messages[-1]["content"]


def test_empty_content_is_treated_as_failure_and_retried(monkeypatch):
    _set_tier_env(monkeypatch, prefix="EXTRACTION", model="deepseek-v4-flash")
    _FakeOpenAI.next_script = [None, '{"name": "Gus", "score": "0.6"}']

    out = call_structured(
        tier="extraction",
        messages=[{"role": "user", "content": "json"}],
        response_model=_Payload,
    )
    assert out.name == "Gus"
    assert len(_FakeOpenAI.instances[0].create_calls) == 2


# ---------------------------------------------------------------------------
# Both attempts fail → wrapper raises (propagates to orchestrator → ERROR)
# ---------------------------------------------------------------------------


def test_double_failure_raises(monkeypatch):
    _set_tier_env(monkeypatch, prefix="EXTRACTION", model="deepseek-v4-flash")
    _FakeOpenAI.next_script = [
        '{"name": "Hal", "score": "9.0"}',
        '{"not": "valid"}',
    ]

    with pytest.raises(ValidationError):
        call_structured(
            tier="extraction",
            messages=[{"role": "user", "content": "json"}],
            response_model=_Payload,
        )
    assert len(_FakeOpenAI.instances[0].create_calls) == 2


# ---------------------------------------------------------------------------
# Free-text drafting path: raw string, no json_object, None on empty (no raise)
# ---------------------------------------------------------------------------


def test_call_text_returns_raw_string_without_json_mode(monkeypatch):
    _set_tier_env(monkeypatch, prefix="DRAFT", model="moonshot-v1-8k")
    _FakeOpenAI.next_script = ["Dear client, please confirm hours."]

    out = call_text(
        tier="draft",
        messages=[{"role": "user", "content": "Draft a clarification email."}],
    )
    assert out == "Dear client, please confirm hours."
    kwargs = _FakeOpenAI.instances[0].create_calls[0]
    assert "response_format" not in kwargs, "drafting path must not set json_object"


def test_call_text_returns_none_on_empty_without_raising(monkeypatch):
    _set_tier_env(monkeypatch, prefix="DRAFT", model="moonshot-v1-8k")
    _FakeOpenAI.next_script = [None]

    out = call_text(
        tier="draft",
        messages=[{"role": "user", "content": "Draft a clarification email."}],
    )
    assert out is None, "empty drafting content falls back to None so the caller templates"
