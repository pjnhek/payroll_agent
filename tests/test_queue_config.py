"""Config-contract guard for the v4 job queue's four env-driven knobs.

Hermetic — no DB, no `integration`/`queueproof` marker. Pins:
- the four defaults (WORKER_COUNT=2, LEASE_SECONDS=900, MAX_ATTEMPTS=5,
  QUEUE_POLL_SECONDS=20);
- WORKER_COUNT overrides cleanly through the environment (mirrors mock_llm's
  get_settings.cache_clear() discipline in tests/conftest.py);
- render.yaml carries all four keys — a knob that exists in Settings but not
  in render.yaml is a knob production silently runs on the default of;
- LEASE_SECONDS' derivation is WRITTEN DOWN in app/config.py's source (not
  just a bare number) — a positive assertion that fails if a future edit
  strips the derivation comment down to a magic number;
- the no-widening guard: the pre-existing concurrency-proof.yml gate stays
  byte-identical (still names its two files, never widens to whole-suite
  `-m integration` collection) — a future contributor who "simplifies" the
  gate back to whole-suite collection must hit a red test that says why, not
  discover it in a flaky live-DB CI run;
- `queueproof` is registered in pyproject.toml's markers list — an
  unregistered marker still *works* (pytest only warns), so nothing else
  would catch a typo'd registration, and the CI gate selects on this exact
  string.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from app.config import Settings, get_settings

_REPO_ROOT = pathlib.Path(__file__).parent.parent
_CONFIG_PY = _REPO_ROOT / "app" / "config.py"
_RENDER_YAML = _REPO_ROOT / "render.yaml"
_PYPROJECT_TOML = _REPO_ROOT / "pyproject.toml"
_WORKFLOW_YML = _REPO_ROOT / ".github" / "workflows" / "concurrency-proof.yml"


class TestQueueKnobDefaults:
    def test_four_defaults_exact(self, monkeypatch: pytest.MonkeyPatch) -> None:
        get_settings.cache_clear()
        monkeypatch.setenv("DATABASE_URL", "postgresql://queue-config-test/stub")
        # tests/conftest.py hard-pins WORKER_COUNT=0 in the real process
        # environment for the whole suite (so a TestClient's lifespan can
        # never spawn a real worker); unset it here so this test observes
        # the field's OWN default rather than that suite-wide pin.
        monkeypatch.delenv("WORKER_COUNT", raising=False)
        s = Settings()
        assert (
            s.worker_count,
            s.lease_seconds,
            s.max_attempts,
            s.queue_poll_seconds,
        ) == (2, 900, 5, 20)
        get_settings.cache_clear()

    def test_worker_count_zero_overrides_cleanly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        get_settings.cache_clear()
        monkeypatch.setenv("DATABASE_URL", "postgresql://queue-config-test/stub")
        monkeypatch.setenv("WORKER_COUNT", "0")
        s = Settings()
        assert s.worker_count == 0
        get_settings.cache_clear()


class TestRenderYamlDriftGuard:
    def test_render_yaml_carries_all_four_keys(self) -> None:
        d = yaml.safe_load(_RENDER_YAML.read_text())
        keys = {
            e["key"] for svc in d["services"] for e in svc.get("envVars", [])
        }
        missing = {
            "WORKER_COUNT",
            "LEASE_SECONDS",
            "MAX_ATTEMPTS",
            "QUEUE_POLL_SECONDS",
        } - keys
        assert not missing, (
            f"render.yaml is missing queue knob(s): {missing}. A knob that "
            "exists in Settings but not in render.yaml is a knob production "
            "silently runs on the Settings default of."
        )


class TestDerivationIsWrittenDown:
    def test_lease_seconds_cites_stale_threshold_and_210(self) -> None:
        """LEASE_SECONDS' derivation must be WRITTEN DOWN, not a bare number.

        Positive assertion — fails if a future edit strips the derivation
        comment down to `lease_seconds: int = 900` with no rationale.
        """
        src = _CONFIG_PY.read_text()
        section_start = src.index("# ── Durable job queue")
        section = src[section_start:]
        assert "STALE_THRESHOLD" in section, (
            "app/config.py's queue-config section must cross-reference "
            "STALE_THRESHOLD (app/routes/runs.py) — one derivation, not two "
            "independent copies of the same arithmetic."
        )
        assert "210" in section, (
            "app/config.py's queue-config section must cite the 210s "
            "worst-case pipeline gap that LEASE_SECONDS=900 is derived from."
        )


class TestD14NoWideningGuard:
    def test_existing_gate_still_names_its_two_files(self) -> None:
        sql = _WORKFLOW_YML.read_text()
        assert (
            "tests/test_concurrency_proof.py "
            "tests/test_email_epoch_arbiter_integration.py -m integration"
            in sql
        ), (
            "the pre-existing 'Run the real-Postgres invariant proofs' step "
            "no longer names its two files with -m integration — this is the "
            "byte-identical gate this test requires."
        )

    def test_whole_suite_integration_collection_absent(self) -> None:
        """Whole-suite `-m integration` collection is FORBIDDEN.

        12 files under tests/ already carry an `integration` marker; only 2
        run in CI today. Generalizing collection would wake 10 dormant
        live-DB modules at once against a shared Postgres, each hitting the
        destructive module-scope reset in tests/conftest.py — a large,
        unbudgeted, unrelated change with no place here.
        """
        sql = _WORKFLOW_YML.read_text()
        assert "uv run pytest tests/ -m integration" not in sql, (
            "concurrency-proof.yml was widened to whole-suite `-m integration` "
            "collection — FORBIDDEN. See the workflow's own comment for why: "
            "it would wake 10 dormant live-DB modules against a shared "
            "Postgres."
        )


class TestQueueproofMarkerRegistered:
    def test_queueproof_registered_in_pyproject(self) -> None:
        """An unregistered marker still *works* (pytest only warns), so this
        registration check is the only thing that would catch a typo'd
        marker string — and the CI gate selects on this exact string.
        """
        toml_src = _PYPROJECT_TOML.read_text()
        assert "queueproof:" in toml_src, (
            "pyproject.toml's [tool.pytest.ini_options] markers list does not "
            "register `queueproof`"
        )
