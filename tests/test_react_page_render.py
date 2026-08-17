"""GET /runs -- the React-rendered page shell (tracer plan 22-04).

`TestClient` never executes JavaScript, so nothing here can assert on the
React-rendered DOM. What these tests CAN see, and do assert on, is the Jinja
shell and the embedded `__INITIAL_DATA__` JSON data island: its presence, its
exact parsed shape, its row order, its resilience to a hostile business name,
its behavior at zero rows, its determinism across identical repeat renders,
and its absence of the seven internal/PII fields the old denylist let
through.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.templating import INITIAL_DATA_ELEMENT_ID, ManifestMissingError

client = TestClient(app, raise_server_exceptions=False)

_ISLAND_PATTERN = re.compile(
    r'<script id="' + re.escape(INITIAL_DATA_ELEMENT_ID) + r'" type="application/json">'
    r"(.*?)</script>",
    re.DOTALL,
)


def _parse_island(response_text: str) -> dict[str, Any]:
    """Extract and parse the embedded __INITIAL_DATA__ island from a rendered
    page's response text -- the one helper every test below routes through
    rather than each writing its own ad hoc string search."""
    match = _ISLAND_PATTERN.search(response_text)
    assert match is not None, "no __INITIAL_DATA__ island found in response text"
    return json.loads(match.group(1))  # type: ignore[no-any-return]


@pytest.fixture(autouse=True)
def _default_dashboard_queue_projection(monkeypatch):
    """Keep GET /runs DB-free of the queue projection unless a test opts in."""
    from app.db import repo

    monkeypatch.setattr(repo, "get_run_queue_label", lambda rid, conn=None: None)


def test_island_present_and_matches_expected_model_dump(fake_repo):
    business_id = next(iter(fake_repo.contact_to_business.values()))
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)

    response = client.get("/runs")
    assert response.status_code == 200
    island = _parse_island(response.text)

    assert island["in_flight_statuses"]
    assert len(island["runs"]) == 1
    row = island["runs"][0]
    assert row["id"] == str(run_id)
    assert row["status"] == "received"
    assert row["badge_label"] == "Received"
    assert row["badge_class"] == "neutral"
    assert row["has_open_job"] is False
    assert row["queue_label"] is None
    assert row["failure"] == {
        "secondary_label": None,
        "stage": None,
        "reason": None,
        "attempts": None,
    }


def test_island_row_order_matches_repository_order(fake_repo):
    business_id = next(iter(fake_repo.contact_to_business.values()))
    run_ids = [
        fake_repo.create_run(business_id=business_id, source_email_id=None)
        for _ in range(3)
    ]

    response = client.get("/runs")
    assert response.status_code == 200
    island = _parse_island(response.text)

    assert [row["id"] for row in island["runs"]] == [str(rid) for rid in run_ids]


def test_zero_runs_emits_valid_empty_island(fake_repo):
    fake_repo.runs.clear()

    response = client.get("/runs")
    assert response.status_code == 200
    island = _parse_island(response.text)

    assert island["runs"] == []
    assert isinstance(island["in_flight_statuses"], list)
    # The demo form (Jinja-owned chrome) still renders with zero runs.
    assert 'action="/demo/send-test"' in response.text


def test_hostile_business_name_does_not_terminate_island_early(monkeypatch):
    from app.db import repo as _repo

    run_id = uuid.uuid4()
    hostile_name = '</script><script>alert(1)</script>&"<img src=x>'
    monkeypatch.setattr(
        _repo,
        "load_all_runs",
        lambda: [
            {
                "id": run_id,
                "business_id": uuid.uuid4(),
                "status": "received",
                "created_at": None,
                "updated_at": None,
                "business_name": hostile_name,
                "summary_gate_reason": None,
                "employee_count": 0,
            }
        ],
    )

    response = client.get("/runs")
    assert response.status_code == 200
    # The hostile substring must never appear un-escaped in the raw response --
    # if it terminated the island early, "<script>alert(1)</script>" would
    # appear verbatim in the markup.
    assert "<script>alert(1)</script>" not in response.text
    island = _parse_island(response.text)
    assert island["runs"][0]["business_name"] == hostile_name


def test_markup_order_notice_heading_mount_form(fake_repo):
    business_id = next(iter(fake_repo.contact_to_business.values()))
    fake_repo.create_run(business_id=business_id, source_email_id=None)

    response = client.get("/runs", params={"notice": "demo_queue_error"})
    assert response.status_code == 200
    text = response.text

    notice_idx = text.index('class="callout callout-error"')
    heading_idx = text.index("<h1>Payroll Runs</h1>")
    mount_idx = text.index('id="react-root"')
    form_idx = text.index('action="/demo/send-test"')

    assert notice_idx < heading_idx < mount_idx < form_idx


def test_two_renders_of_unchanged_snapshot_are_byte_identical(fake_repo):
    business_id = next(iter(fake_repo.contact_to_business.values()))
    fake_repo.create_run(business_id=business_id, source_email_id=None)

    first = client.get("/runs")
    second = client.get("/runs")
    assert first.status_code == second.status_code == 200
    first_body, second_body = first.text, second.text
    assert first_body == second_body


def test_two_renders_over_different_snapshots_differ(fake_repo):
    business_id = next(iter(fake_repo.contact_to_business.values()))

    before = client.get("/runs")
    fake_repo.create_run(business_id=business_id, source_email_id=None)
    after = client.get("/runs")

    before_body, after_body = before.text, after.text
    assert before_body != after_body


def test_payload_excludes_internal_and_pii_fields(fake_repo):
    """The seven internal/PII keys that survive the old denylist must
    be absent from the embedded payload. fake_repo's create_run seeds most of
    them (source_email_id, extracted_data, decision, reconciliation,
    reply_epoch) directly; alias_candidates is set explicitly here since
    create_run does not seed it by default."""
    from app.db import repo as _repo

    business_id = next(iter(fake_repo.contact_to_business.values()))
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)
    _repo.set_alias_candidates(run_id, {"maria": ["Maria Chen"]})

    response = client.get("/runs")
    assert response.status_code == 200
    island = _parse_island(response.text)

    row = island["runs"][0]
    forbidden = (
        "business_id",
        "source_email_id",
        "reply_epoch",
        "alias_candidates",
        "extracted_data",
        "reconciliation",
        "decision",
    )
    for key in forbidden:
        assert key not in row, f"{key!r} must never reach the /runs data island"


def test_missing_manifest_raises_manifest_missing_error(monkeypatch, fake_repo, tmp_path):
    from app.routes import templating

    business_id = next(iter(fake_repo.contact_to_business.values()))
    fake_repo.create_run(business_id=business_id, source_email_id=None)

    monkeypatch.setattr(templating, "MANIFEST_PATH", tmp_path / "does-not-exist.json")
    templating.load_manifest.cache_clear()

    strict_client = TestClient(app, raise_server_exceptions=True)
    with pytest.raises(ManifestMissingError):
        strict_client.get("/runs")

    templating.load_manifest.cache_clear()
