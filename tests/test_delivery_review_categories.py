"""Table-driven coverage for the delivery-review retry classification (BUG-2 half 1).

Pure data + pure functions -- no HTTP, no DB, no route or template dependency. The
classification is proven here first; app/routes/runs.py's two delivery-review cards
consume it (tests/test_phase20_clarification_review.py covers that half).
"""
from __future__ import annotations

from app.db.repo.job_settlement import all_producer_failure_categories
from app.models.delivery_review import DELIVERY_REVIEW_CATEGORIES


def test_every_category_has_label_uncertainty_and_a_consistent_blocker() -> None:
    assert DELIVERY_REVIEW_CATEGORIES, "DELIVERY_REVIEW_CATEGORIES must not be empty"
    for key, category in DELIVERY_REVIEW_CATEGORIES.items():
        assert category.label.strip(), f"{key}: label must be non-empty"
        assert category.uncertainty.strip(), f"{key}: uncertainty must be non-empty"
        both_ok = category.replay_same_ok and category.fresh_send_ok
        if both_ok:
            assert category.blocker is None, (
                f"{key}: blocker must be None when both replay_same_ok and "
                f"fresh_send_ok are True"
            )
        else:
            assert category.blocker is not None, (
                f"{key}: blocker must be set when either retry path is blocked"
            )
            assert category.blocker.strip()


def test_category_keys_match_the_producer_vocabulary() -> None:
    """Reuses job_settlement's own per-PipelineReason-member derivation -- the
    same single source of truth test_status_drift.py's producer coverage test
    checks against -- rather than re-transcribing the category list.

    final_attempt_lease_expired is the one key `_delivery_failure_category`
    itself never returns (job_settlement.py's final-lease reap path writes
    that literal directly), matching the same "+ one extra key" shape
    test_status_drift.py's schema-CHECK coverage test pins ('+ none')."""
    assert set(DELIVERY_REVIEW_CATEGORIES) == all_producer_failure_categories() | {
        "final_attempt_lease_expired"
    }


def test_live_proven_categories_are_pinned_by_name() -> None:
    """The two live-proven cases from the real Resend API this session:
    validation (403 on a .example recipient) is unretryable either way;
    payload_mismatch (409 invalid_idempotent_request) is retryable only by a
    fresh slot -- a single `retryable: bool` gets this one backwards."""
    validation = DELIVERY_REVIEW_CATEGORIES["validation"]
    assert validation.replay_same_ok is False
    assert validation.fresh_send_ok is False

    payload_mismatch = DELIVERY_REVIEW_CATEGORIES["payload_mismatch"]
    assert payload_mismatch.replay_same_ok is False
    assert payload_mismatch.fresh_send_ok is True


def test_unknown_fails_open_on_both_flags() -> None:
    """unknown is the unclassified DELIVERY_PROVIDER_FAILURE catch-all.
    Suppressing an action that might work is a different failure than
    offering one that cannot, so it fails OPEN, not closed."""
    unknown = DELIVERY_REVIEW_CATEGORIES["unknown"]
    assert unknown.replay_same_ok is True
    assert unknown.fresh_send_ok is True
    assert unknown.blocker is None


def test_no_uncertainty_or_blocker_string_contains_markup() -> None:
    for key, category in DELIVERY_REVIEW_CATEGORIES.items():
        for char in "<>{}":
            assert char not in category.uncertainty, (
                f"{key}: uncertainty contains {char!r}"
            )
            if category.blocker is not None:
                assert char not in category.blocker, f"{key}: blocker contains {char!r}"
