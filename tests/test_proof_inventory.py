"""Hermetic tests for `scripts/check_proof_inventory.py`'s pure decision core.

Exercises `evaluate_inventory` and the exported node-id pattern only — no subprocess,
no live repo scan. The live-repo assertion (wiring `collect_inventory` + `main()`
against the real test tree) belongs to plan 21-09, after the four PROOF-0N proofs are
actually tagged.

Every failure-shape test builds a synthetic, isolated scenario (fabricated node-id
strings as literal dicts/lists) so each assertion is checking exactly one thing, and
asserts on the *content* of the violation string it produces — not merely that the
violation list is non-empty. A violation list that reds for the wrong reason is the
same class of defect as a proof that reds for the wrong reason.
"""

from __future__ import annotations

from scripts.check_proof_inventory import EXPECTED_PROOF_IDS, NODE_ID_PATTERN, evaluate_inventory


def _node(proof_id: str) -> str:
    return f"tests/test_proof_fixture.py::test_{proof_id.lower().replace('-', '_')}"


class TestConformingInventory:
    def test_no_violations_when_everything_lines_up(self) -> None:
        per_id = {proof_id: [_node(proof_id)] for proof_id in EXPECTED_PROOF_IDS}
        all_marked = [_node(proof_id) for proof_id in EXPECTED_PROOF_IDS]
        queueproof_marked = list(all_marked)

        violations = evaluate_inventory(per_id, all_marked, queueproof_marked, EXPECTED_PROOF_IDS)

        assert violations == []


class TestMissingId:
    def test_missing_id_names_the_offending_id(self) -> None:
        missing = EXPECTED_PROOF_IDS[0]
        present_ids = EXPECTED_PROOF_IDS[1:]
        per_id = {missing: [], **{proof_id: [_node(proof_id)] for proof_id in present_ids}}
        # The missing id's test does not exist at all: it appears in neither the bare
        # `proof` collection nor the `queueproof` collection.
        all_marked = [_node(proof_id) for proof_id in present_ids]
        queueproof_marked = list(all_marked)

        violations = evaluate_inventory(per_id, all_marked, queueproof_marked, EXPECTED_PROOF_IDS)

        assert len(violations) == 1
        assert missing in violations[0]


class TestDuplicateId:
    def test_duplicate_id_names_the_id_and_both_node_ids(self) -> None:
        dup_id = EXPECTED_PROOF_IDS[1]
        node_a = f"{_node(dup_id)}_a"
        node_b = f"{_node(dup_id)}_b"
        other_ids = [proof_id for proof_id in EXPECTED_PROOF_IDS if proof_id != dup_id]
        per_id = {
            dup_id: [node_a, node_b],
            **{proof_id: [_node(proof_id)] for proof_id in other_ids},
        }
        all_marked = [node_a, node_b] + [_node(proof_id) for proof_id in other_ids]
        queueproof_marked = list(all_marked)

        violations = evaluate_inventory(per_id, all_marked, queueproof_marked, EXPECTED_PROOF_IDS)

        assert len(violations) == 1
        assert dup_id in violations[0]
        assert node_a in violations[0]
        assert node_b in violations[0]


class TestStrayId:
    def test_stray_id_names_the_offending_node_id(self) -> None:
        # Simulates id="PROOF-3" (a typo'd id): the test carries BOTH markers
        # correctly (proof + queueproof), but its id string matches none of the
        # four expected ids, so it never shows up under any per-id intersection
        # selection even though it is fully selectable and fully tagged.
        stray_node = "tests/test_proof_fixture.py::test_typod_id"
        per_id = {proof_id: [_node(proof_id)] for proof_id in EXPECTED_PROOF_IDS}
        all_marked = [_node(proof_id) for proof_id in EXPECTED_PROOF_IDS] + [stray_node]
        queueproof_marked = list(all_marked)

        violations = evaluate_inventory(per_id, all_marked, queueproof_marked, EXPECTED_PROOF_IDS)

        assert len(violations) == 1
        assert stray_node in violations[0]


class TestMissingQueueproofMarker:
    def test_absent_from_queueproof_selection_names_queueproof_and_node_id(self) -> None:
        # A proof that carries a fully valid `proof(id=...)` yet is not selected by
        # the marker CI actually runs (`queueproof`) — it would pass an id-only
        # inventory gate and simply never execute in CI.
        unselected_id = EXPECTED_PROOF_IDS[2]
        unselected_node = _node(unselected_id)
        other_ids = [proof_id for proof_id in EXPECTED_PROOF_IDS if proof_id != unselected_id]
        # The intersection selection (`queueproof and proof(id=...)`) necessarily
        # excludes this node too, since it lacks `queueproof` — so its own per-id
        # slot is empty, exactly like the real collector would report.
        per_id = {
            unselected_id: [],
            **{proof_id: [_node(proof_id)] for proof_id in other_ids},
        }
        all_marked = [unselected_node] + [_node(proof_id) for proof_id in other_ids]
        queueproof_marked = [_node(proof_id) for proof_id in other_ids]  # excludes unselected_node

        violations = evaluate_inventory(per_id, all_marked, queueproof_marked, EXPECTED_PROOF_IDS)

        queueproof_violations = [v for v in violations if "queueproof" in v]
        assert len(queueproof_violations) == 1
        assert unselected_node in queueproof_violations[0]


class TestAllFourShapesSimultaneously:
    def test_all_four_shapes_reported_at_once(self) -> None:
        proof_01, proof_02, proof_03, proof_04 = EXPECTED_PROOF_IDS

        node_01 = _node(proof_01)
        # proof_02 has NO test at all -> missing.
        node_03_a = f"{_node(proof_03)}_a"
        node_03_b = f"{_node(proof_03)}_b"  # -> duplicate for proof_03
        node_04 = _node(proof_04)  # carries proof(id=...) but not queueproof
        typo_node = "tests/test_proof_fixture.py::test_typod_id"  # -> stray

        per_id = {
            proof_01: [node_01],
            proof_02: [],
            proof_03: [node_03_a, node_03_b],
            proof_04: [],
        }
        all_marked = [node_01, node_03_a, node_03_b, node_04, typo_node]
        queueproof_marked = [node_01, node_03_a, node_03_b, typo_node]  # excludes node_04

        violations = evaluate_inventory(per_id, all_marked, queueproof_marked, EXPECTED_PROOF_IDS)
        violation_text = "\n".join(violations)

        assert any(proof_02 in v for v in violations), (
            f"expected a missing-id violation for {proof_02}, got:\n{violation_text}"
        )
        assert any(
            proof_03 in v and node_03_a in v and node_03_b in v for v in violations
        ), f"expected a duplicate-id violation for {proof_03}, got:\n{violation_text}"
        assert any(
            typo_node in v and "queueproof" not in v for v in violations
        ), f"expected a stray-id violation for {typo_node}, got:\n{violation_text}"
        assert any(
            node_04 in v and "queueproof" in v for v in violations
        ), f"expected a missing-queueproof violation for {node_04}, got:\n{violation_text}"


class TestNodeIdPattern:
    def test_matches_plain_and_parametrized_node_ids(self) -> None:
        assert NODE_ID_PATTERN.match("tests/x.py::test_y")
        assert NODE_ID_PATTERN.match("tests/x.py::test_y[case-1]")
        assert NODE_ID_PATTERN.match(
            "tests/test_queue_config.py::TestQueueKnobDefaults::test_four_defaults_exact"
        )

    def test_rejects_trailing_summary_and_bare_directory(self) -> None:
        assert NODE_ID_PATTERN.match("11 tests collected in 0.04s") is None
        assert NODE_ID_PATTERN.match("63/1289 tests collected (1226 deselected) in 0.74s") is None
        assert NODE_ID_PATTERN.match("tests/") is None
