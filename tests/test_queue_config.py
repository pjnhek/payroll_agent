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


class TestProofMarkerRegistered:
    def test_proof_registered_in_pyproject(self) -> None:
        """An unregistered marker still *works* (pytest only warns), so this
        registration check is the only thing that would catch a typo'd
        marker string — and PROOF-05's selection-layer completeness checker
        (scripts/check_proof_inventory.py) selects on this exact string.
        """
        toml_src = _PYPROJECT_TOML.read_text()
        assert "proof:" in toml_src, (
            "pyproject.toml's [tool.pytest.ini_options] markers list does not "
            "register `proof`"
        )

    def test_proof_marker_description_records_keyword_id_rationale(self) -> None:
        """The keyword-`id` spelling is load-bearing, not stylistic: pytest's
        `-m` marker-expression syntax only supports selecting on keyword
        marker arguments, never positional ones. A future edit that drops
        this rationale from the registered description must red here.
        """
        toml_src = _PYPROJECT_TOML.read_text()
        assert "keyword argument `id`" in toml_src, (
            "pyproject.toml's `proof` marker description no longer records "
            "the keyword-`id` requirement"
        )


def _workflow_steps() -> list[dict]:
    parsed = yaml.safe_load(_WORKFLOW_YML.read_text())
    return list(parsed["jobs"].values())[0]["steps"]


def _proof_running_steps(steps: list[dict]) -> list[dict]:
    """Steps whose `run` block invokes pytest or the completeness checker.

    Deliberately excludes non-proof `run:` steps (checkout's `uses:`-only
    step, `uv sync`, schema bootstrap) so a future deletion of one of the
    three durability-proof-running steps is caught without also tripping on
    unrelated setup-step edits.
    """
    return [
        s
        for s in steps
        if "run" in s and ("pytest" in s["run"] or "check_proof_inventory" in s["run"])
    ]


class TestD02CollectGateStep:
    """The third CI step wiring scripts/check_proof_inventory.py.

    Asserts structurally over parsed YAML: the step exists and invokes the
    checker, it runs strictly after the queueproof step (so it verifies
    against the same live selection CI just executed), and the job's total
    count of proof-running steps is exactly three — so a future edit that
    silently deletes one of the three is caught here rather than by a CI
    log that just got shorter.
    """

    def test_completeness_gate_step_exists_and_invokes_the_checker(self) -> None:
        steps = _workflow_steps()
        gate_steps = [
            s for s in steps if "run" in s and "check_proof_inventory" in s["run"]
        ]
        assert len(gate_steps) == 1, (
            "expected exactly one step invoking scripts/check_proof_inventory.py, "
            f"found {len(gate_steps)}"
        )

    def test_completeness_gate_step_runs_after_the_queueproof_step(self) -> None:
        steps = _workflow_steps()
        queueproof_idx = next(
            i
            for i, s in enumerate(steps)
            if "queue durability proofs" in s.get("name", "")
        )
        gate_idx = next(
            i
            for i, s in enumerate(steps)
            if "run" in s and "check_proof_inventory" in s["run"]
        )
        assert gate_idx > queueproof_idx, (
            "the completeness gate step must run AFTER the queueproof step: "
            "it verifies the selection that step just executed, not a "
            "hypothetical future one"
        )

    def test_exactly_three_proof_running_steps(self) -> None:
        proof_steps = _proof_running_steps(_workflow_steps())
        names = [s.get("name") for s in proof_steps]
        assert len(proof_steps) == 3, (
            "expected exactly 3 proof-running steps (real-Postgres invariant "
            f"proofs, queue durability proofs, completeness gate), found "
            f"{len(proof_steps)}: {names}"
        )

    def test_no_false_positive_d14_widening_guard_still_passes(self) -> None:
        """No-false-positive half: the pre-existing widening guard must still
        pass unmodified after this step's addition — a new step that
        accidentally satisfied the forbidden whole-suite pattern would
        otherwise slip through unnoticed.
        """
        TestD14NoWideningGuard().test_existing_gate_still_names_its_two_files()
        TestD14NoWideningGuard().test_whole_suite_integration_collection_absent()


class TestPreExistingStepFingerprints:
    """Structural fingerprint pinning both pre-existing proof-running steps.

    `TestD14NoWideningGuard` checks one command substring and one absence —
    it would not catch a dropped `set -o pipefail`, a changed `shell:`, an
    altered `env:` block, or a removed skip/pass log guard on either
    pre-existing step. Since this plan's whole premise is that those two
    steps stay untouched, that premise is enforced here rather than merely
    believed: `name`, `shell`, the presence of `set -o pipefail`, the
    selection arguments, the job-level `env` keys, and both log guards
    (the `skipped`-reds check and the `passed`-required check) are pinned
    for each step.

    Deliberately NOT a hash of either step's `run` block: a hash reds on a
    harmless comment reflow and gets deleted for being annoying, which is
    how a guard dies. Pinning named, load-bearing fields survives
    formatting changes and still catches every semantic change this class
    enumerates.
    """

    def test_integration_step_fingerprint(self) -> None:
        steps = _workflow_steps()
        matches = [
            s for s in steps if "real-Postgres invariant proofs" in s.get("name", "")
        ]
        assert len(matches) == 1
        step = matches[0]

        assert step["name"] == "Run the real-Postgres invariant proofs"
        assert step["shell"] == "bash"
        run = step["run"]
        assert "set -o pipefail" in run
        assert (
            "tests/test_concurrency_proof.py "
            "tests/test_email_epoch_arbiter_integration.py -m integration"
            in run
        )
        assert "grep -qE '[0-9]+ skipped'" in run, "skip-reds log guard missing"
        assert "grep -qE '[0-9]+ passed'" in run, "pass-required log guard missing"
        assert "exit 1" in run

    def test_queueproof_step_fingerprint(self) -> None:
        steps = _workflow_steps()
        matches = [
            s for s in steps if "queue durability proofs" in s.get("name", "")
        ]
        assert len(matches) == 1
        step = matches[0]

        assert step["name"] == "Run the queue durability proofs (real Postgres)"
        assert step["shell"] == "bash"
        run = step["run"]
        assert "set -o pipefail" in run
        assert "uv run pytest tests/ -m queueproof" in run
        assert "grep -qE '[0-9]+ skipped'" in run, "skip-reds log guard missing"
        assert "grep -qE '[0-9]+ passed'" in run, "pass-required log guard missing"
        assert "exit 1" in run

    def test_job_level_env_keys_unchanged(self) -> None:
        parsed = yaml.safe_load(_WORKFLOW_YML.read_text())
        job = list(parsed["jobs"].values())[0]
        assert set(job["env"].keys()) == {
            "DATABASE_URL",
            "ALLOW_DB_RESET",
            "ALLOW_UNSIGNED_FIXTURES",
        }, (
            "the job-level env block changed — the pre-existing steps are "
            "additive-only territory and a change here means the new step "
            "was not additive after all"
        )
