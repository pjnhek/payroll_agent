"""Calc + persistence round-trip tests (LLM-08, D-A3-05; FIX 2).

Section 1 (always run, DB-free): the full-fidelity gross+FICA+federal calc (Phase 3) —
federal is real (not zero), SS honors the wage-base cap.

NOTE: PRE_FEDERAL_NET_LABEL was removed in Phase 3 (Plan 03-03) — the net is now real.
The Phase 2 tests that asserted federal_withholding == 0 and tested PRE_FEDERAL_NET_LABEL
have been updated to reflect Phase 3 behavior. (Rule 1 auto-fix — Phase 3 retired the
label and replaced the Decimal("0") federal stub with real Pub 15-T withholding.)

Section 2 (live-DB, two-factor guard): a clean run persisted to payroll_runs
round-trips BOTH decision AND reconciliation — mirrors tests/test_seed_roundtrip.py
§2.
"""
from __future__ import annotations

import os
import unicodedata
import uuid
from decimal import Decimal

import pytest

from app.models.contracts import Decision, Extracted, ExtractedEmployee, PaystubLineItem
from app.models.roster import Employee, NameMatchResult, Roster
from app.pipeline.calculate import calculate

_HAS_DB = bool(os.environ.get("DATABASE_URL"))
_HAS_RESET = os.environ.get("ALLOW_DB_RESET") == "1"

_SKIP_LIVE_DB = pytest.mark.skipif(
    not (_HAS_DB and _HAS_RESET),
    reason="Live-DB tests require DATABASE_URL and ALLOW_DB_RESET=1 (two-factor guard)",
)


# ===========================================================================
# Section 1 — thin calc (always run, DB-free)
# ===========================================================================


def _hourly_employee(ytd_ss="12000.00", rate="18.50", pct="0.00") -> Employee:
    return Employee(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        full_name="Maria Chen",
        known_aliases=[],
        pay_type="hourly",
        hourly_rate=Decimal(rate),
        annual_salary=None,
        retirement_contribution_pct=Decimal(pct),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal(ytd_ss),
        pay_periods_per_year=52,
    )


def test_calc_federal_is_real_in_phase3():
    """Phase 3: federal_withholding is real (non-zero) for a typical earning employee.

    Phase 2 asserted federal_withholding == Decimal("0") (thin calc, no federal).
    Phase 3 (Plan 03-03) replaces that stub with real IRS Pub 15-T withholding.
    This test is updated to reflect Phase 3 behavior (Rule 1 auto-fix).
    """
    item = calculate({"hours_regular": Decimal("40")}, _hourly_employee())
    assert isinstance(item, PaystubLineItem)
    # Phase 3: federal_withholding is real for a typical employee (non-zero)
    assert item.federal_withholding > Decimal("0"), "Phase 3 calc has REAL federal withholding"


def test_no_net_pay_label_field_on_paystub():
    """FIX 2 (updated for Phase 3): PaystubLineItem must NOT gain a label field.

    The Phase 2 'pre-federal' label constant has been retired in Phase 3 (Plan 03-03).
    This test retains the critical invariant: no net_pay_label field on PaystubLineItem
    (which is extra='forbid' — such a field would break existing callers).
    """
    assert "net_pay_label" not in PaystubLineItem.model_fields, (
        "PaystubLineItem must NOT gain a label field (FIX 2)"
    )


def test_calc_gross_and_net_hourly():
    """Phase 3 update: net_pay now includes real federal withholding (Rule 1 auto-fix).

    Phase 2 asserted net_pay == 683.39 (gross - FICA, no federal).
    Phase 3 adds real Pub 15-T withholding, so net_pay = gross - FICA - federal.
    The gross and FICA assertions remain unchanged; net_pay is now computed from the item.
    """
    item = calculate({"hours_regular": Decimal("40")}, _hourly_employee(rate="18.50"))
    assert item.gross_pay == Decimal("740.00")  # 40 * 18.50
    # FICA: SS 6.2% (under cap) + Medicare 1.45%; no 401k
    assert item.fica_ss == Decimal("45.88")  # 740 * 0.062
    assert item.fica_medicare == Decimal("10.73")  # 740 * 0.0145
    # Phase 3: net_pay = gross - fica_ss - fica_medicare - federal_withholding (real)
    expected_net = (item.gross_pay - item.fica_ss - item.fica_medicare - item.federal_withholding).quantize(Decimal("0.01"))
    assert item.net_pay == expected_net  # net is now real (includes federal withholding)


def test_ss_honors_wage_base_cap_straddle():
    """Mirror the seed straddle case (Thomas Bergmann): ytd_ss_wages 183,900,
    remaining cap 600 < per-period gross → only $600 is SS-taxable."""
    emp = Employee(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        full_name="Thomas Bergmann",
        known_aliases=[],
        pay_type="salary",
        hourly_rate=None,
        annual_salary=Decimal("240000.00"),
        retirement_contribution_pct=Decimal("0.00"),
        filing_status="married_jointly",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("183900.00"),
        pay_periods_per_year=26,
    )
    item = calculate({}, emp)
    # Only the remaining $600 of wage base is SS-taxable: 600 * 0.062 = 37.20.
    assert item.fica_ss == Decimal("37.20"), "SS must honor the remaining wage-base cap"


def test_absent_hours_treated_as_zero_in_calc():
    item = calculate({"hours_regular": None}, _hourly_employee())
    assert item.gross_pay == Decimal("0.00")


# ===========================================================================
# Section 1b — record_run_error must not clobber a terminal run (WR-04, DB-free)
# ===========================================================================


def test_record_run_error_skips_terminal_run(fake_conn):
    """WR-04 guard, WR-03 CAS — record_run_error must NOT clobber a terminal run.

    Phase-8 review WR-03: the guard is an atomic CAS folded into the UPDATE's
    WHERE clause (`status <> ALL(terminal)` + RETURNING, the claim_status idiom),
    NOT a SELECT-then-UPDATE — a check-then-act pair lets a concurrent
    transaction commit `sent`/`reconciled` between the read and the write under
    READ COMMITTED, and the unconditional UPDATE then clobbers the terminal run.

    A terminal run matches no row, so RETURNING yields None (scripted here) and
    set_status(ERROR) must never run. The genuinely terminal statuses are:
    sent, reconciled, rejected, error ('approved' stays claimable — D-13b).
    """
    from app.db import repo

    fake_conn.script_fetchone(None)  # CAS matched no row — the run is terminal
    repo.record_run_error(uuid.uuid4(), "boom: a late resume hit an exception", conn=fake_conn)

    sql = fake_conn.all_sql()
    # The guard is INSIDE the write: no separate status read, and the UPDATE
    # carries the terminal-status predicate + RETURNING (atomic claim).
    assert "SELECT status" not in sql, (
        "the terminal guard must be a CAS in the UPDATE WHERE clause, not a "
        "separate check-then-act SELECT (WR-03)"
    )
    assert "status <> ALL(%s)" in sql and "RETURNING" in sql, (
        "the UPDATE must carry the terminal-status predicate and RETURNING "
        "so the claim is atomic (WR-03 CAS)"
    )
    # The terminal set is parameterized from _TERMINAL_STATUSES (single source
    # of truth) — never inlined literals.
    _, params = fake_conn.executed[0]
    assert sorted(repo._TERMINAL_STATUSES) in list(params), (
        "the terminal statuses must be passed as a SQL array param sourced "
        "from _TERMINAL_STATUSES"
    )
    assert "SET status" not in sql, "a terminal run must NOT be flipped to ERROR (WR-04)"


def test_record_run_error_processes_approved_run(fake_conn):
    """D-13b — record_run_error MUST write error_reason for an 'approved' run.

    'approved' was removed from _TERMINAL_STATUSES in Phase 5 Plan 03 so that a
    delivery failure after approval can advance the run to ERROR — making it
    retriggerable. With the WR-03 CAS, 'approved' is claimable because it is not
    in the parameterized terminal set (test_approved_not_in_terminal_statuses
    pins that), so the CAS UPDATE matches and RETURNING yields the row id.
    """
    from app.db import repo

    run_id = uuid.uuid4()
    fake_conn.script_fetchone((str(run_id),))  # CAS RETURNING id — claim succeeded
    repo.record_run_error(run_id, "delivery crashed after approval", conn=fake_conn)

    sql = fake_conn.all_sql()
    assert "SET error_reason" in sql, (
        "an approved run with a delivery failure must write error_reason "
        "(D-13b: approved is non-terminal, delivery failures must be recoverable)"
    )
    assert "SET status" in sql, (
        "an approved run with a delivery failure must advance to ERROR "
        "(D-13b: so the operator can retrigger)"
    )


def test_record_run_error_writes_for_non_terminal_run(fake_conn):
    """WR-04 — a NON-terminal run still records the error and advances to ERROR (the
    original behavior is preserved for in-flight runs)."""
    from app.db import repo

    run_id = uuid.uuid4()
    fake_conn.script_fetchone((str(run_id),))  # CAS claim succeeds (run in-flight)
    repo.record_run_error(run_id, "boom: a real stage failure", conn=fake_conn)

    sql = fake_conn.all_sql()
    assert "SET error_reason" in sql, "a non-terminal run must persist the error_reason"
    assert "SET status" in sql, "a non-terminal run must advance to ERROR via set_status"


def test_record_run_error_two_arg_call_overwrites_detail_with_null(fake_conn):
    """WR-05 (phase-8 review) — the documented overwrite contract: a legacy
    two-arg call (no detail_exc/stage) writes error_detail = NULL, ERASING any
    previously-persisted detail. Deliberate: error_reason and error_detail must
    always describe the SAME (latest) error — a stale detail next to a fresh
    reason would mislead the operator. This test pins the contract so the
    docstring and the SQL cannot drift apart again.
    """
    from app.db import repo

    run_id = uuid.uuid4()
    fake_conn.script_fetchone((str(run_id),))  # CAS claim succeeds
    repo.record_run_error(run_id, "SomeLaterError", conn=fake_conn)

    sql, params = fake_conn.executed[0]
    assert "error_detail" in sql, (
        "the UPDATE must always include error_detail in its SET clause "
        "(always-overwrite contract, WR-05)"
    )
    assert params[0] == "SomeLaterError"
    assert params[1] is None, (
        "omitting detail_exc/stage must overwrite error_detail with NULL — "
        "never silently preserve a stale prior detail (WR-05)"
    )


# ===========================================================================
# Section 1c — PII scrub / _build_error_detail (OPS2-01, D-8-01/D-8-01b/D-8-02)
# ===========================================================================


def _employee(full_name: str, aliases: list[str] | None = None) -> Employee:
    """Minimal valid hourly Employee for scrub-test rosters (fields unused by
    the scrubber are filled with harmless defaults)."""
    return Employee(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        full_name=full_name,
        known_aliases=aliases or [],
        pay_type="hourly",
        hourly_rate=Decimal("20.00"),
        annual_salary=None,
        retirement_contribution_pct=Decimal("0.00"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("0.00"),
        pay_periods_per_year=52,
    )


def test_record_run_error_scrubs_pii_from_error_detail(fake_conn, roster_from_seed):
    """D-8-04 — error_detail excludes both a roster employee's full_name AND an
    email address, but retains the surviving non-PII text plus a [REDACTED] marker.
    """
    from app.db import repo

    employee = roster_from_seed.employees[0]
    exc = ValueError(
        f"failed to process {employee.full_name} <maria.gonzalez@acme.test>: bad row"
    )
    fake_conn.script_fetchone(("extracting",))
    repo.record_run_error(
        uuid.uuid4(),
        "ValueError",
        conn=fake_conn,
        detail_exc=exc,
        stage="extract",
        roster=roster_from_seed,
    )

    sql, params = fake_conn.executed[-2]
    assert "error_detail" in sql
    detail = params[1]
    assert detail is not None
    assert "[REDACTED]" in detail
    assert employee.full_name not in detail
    assert "maria.gonzalez@acme.test" not in detail
    assert "bad row" in detail


def test_record_run_error_scrubs_before_truncate_boundary(fake_conn, roster_from_seed):
    """D-8-04a — scrub runs on the FULL message BEFORE the 200-char truncate, so a
    sensitive email straddling the boundary is never left as a partial fragment."""
    from app.db import repo

    padding = "x" * 185
    email = "straddle.boundary@acme.test"
    message = f"{padding} {email} more trailing text that gets cut off after this"
    exc = ValueError(message)

    fake_conn.script_fetchone(("extracting",))
    repo.record_run_error(
        uuid.uuid4(),
        "ValueError",
        conn=fake_conn,
        detail_exc=exc,
        stage="extract",
        roster=roster_from_seed,
    )

    sql, params = fake_conn.executed[-2]
    detail = params[1]
    assert detail is not None
    assert email not in detail
    # No fragment of the email survives (neither the full string nor a partial
    # remnant like the local-part or domain-part alone).
    assert "straddle.boundary" not in detail
    assert "acme.test" not in detail


def test_record_run_error_fails_open_when_scrub_raises(fake_conn, roster_from_seed, monkeypatch):
    """D-8-04b — if the scrub step itself raises, record_run_error still writes the
    pre-existing error_reason and advances to ERROR; error_detail falls back to None.
    """
    from app.db import repo

    def _boom(message, roster=None):
        raise RuntimeError("scrub exploded")

    monkeypatch.setattr(repo, "_scrub", _boom)

    fake_conn.script_fetchone(("extracting",))
    repo.record_run_error(
        uuid.uuid4(),
        "ValueError",
        conn=fake_conn,
        detail_exc=ValueError("boom"),
        stage="extract",
        roster=roster_from_seed,
    )

    sql = fake_conn.all_sql()
    assert "SET error_reason" in sql
    assert "SET status" in sql
    sql_last, params = fake_conn.executed[-2]
    assert params[0] == "ValueError"
    assert params[1] is None


def test_record_run_error_fails_open_when_no_roster(fake_conn):
    """D-8-04b — with roster=None, record_run_error does not raise; error_detail is
    still populated via the regex-only (email) scrub, with no roster-name redaction
    attempted and no additional DB/roster-loading SQL beyond the terminal-status read.
    """
    from app.db import repo

    exc = ValueError("contact ops@acme.test about this run")
    fake_conn.script_fetchone(("extracting",))
    repo.record_run_error(
        uuid.uuid4(),
        "ValueError",
        conn=fake_conn,
        detail_exc=exc,
        stage="extract",
        roster=None,
    )

    sql, params = fake_conn.executed[-2]
    detail = params[1]
    assert detail is not None
    assert "[REDACTED]" in detail
    assert "ops@acme.test" not in detail
    # Exactly the CAS UPDATE plus set_status's UPDATE (WR-03: the terminal guard
    # is inside the UPDATE's WHERE, no separate status SELECT) — and no extra
    # roster-loading SELECT appears.
    assert "SELECT" not in fake_conn.all_sql().upper(), (
        "record_run_error must issue no SELECT (no status read, no roster load)"
    )
    assert len(fake_conn.executed) == 2, (
        "expected exactly the CAS UPDATE + set_status UPDATE, got "
        f"{len(fake_conn.executed)} statements"
    )


def test_scrub_case_and_unicode_form_insensitive_longest_first(roster_from_seed):
    """R2-1 (constructed, non-skippable) — the scrubber matches roster names
    case-insensitively and Unicode-form-insensitively across precomposed, NFD-
    decomposed, AND bare-unaccented renderings, for BOTH a with-alias name and a
    no-covering-alias name. This test builds its OWN roster (not roster_from_seed)
    so it never depends on what the seed data happens to contain.
    """
    from app.db import repo

    jose = _employee("José García", aliases=["Jose"])
    ana = _employee("Ana Núñez", aliases=[])
    roster = Roster(business_id=uuid.uuid4(), employees=[jose, ana])

    variants = []
    for name in ("José García", "Ana Núñez"):
        precomposed = name
        decomposed = unicodedata.normalize("NFD", name)
        upper_precomposed = name.upper()
        bare_unaccented = (
            unicodedata.normalize("NFKD", name)
            .encode("ascii", "ignore")
            .decode("ascii")
            .upper()
        )
        variants.extend([precomposed, decomposed, upper_precomposed, bare_unaccented])

    message = "Payroll note: " + " | ".join(variants) + " — please review."
    scrubbed = repo._scrub(message, roster=roster)

    assert scrubbed.count("[REDACTED]") >= 8

    # No stray combining mark survives adjacent to a redacted span or anywhere.
    for i, ch in enumerate(scrubbed):
        if unicodedata.combining(ch) != 0:
            raise AssertionError(f"stray combining mark {ch!r} at index {i} in {scrubbed!r}")

    # No raw literal occurrence of any constructed variant survives.
    for variant in variants:
        assert variant not in scrubbed.replace("[REDACTED]", ""), (
            f"raw variant {variant!r} leaked into scrubbed output: {scrubbed!r}"
        )

    # The individual surname fragments must not leak either — the exact
    # fixture-coincidence gap the original test design left open.
    assert "GARCIA" not in scrubbed
    assert "NUNEZ" not in scrubbed


def test_scrub_umlaut_and_grave_names_redacted_in_all_renderings():
    """WR-02 (phase-8 review) — the accent class map must cover the full Latin-1
    accented range, not just acute vowels + n-tilde + c-cedilla. For stored
    "Björn Müller" the pre-fix map left the bare ASCII-ified rendering
    "Bjorn Muller" (the single most common real-input form) completely
    unredacted. Same for grave/circumflex names.
    """
    from app.db import repo

    bjorn = _employee("Björn Müller", aliases=[])
    amelie = _employee("Amélie Lefèvre", aliases=[])
    roster = Roster(business_id=uuid.uuid4(), employees=[bjorn, amelie])

    cases = [
        ("bare umlaut", "failed for Bjorn Muller at row 2"),
        ("precomposed umlaut", "failed for Björn Müller at row 2"),
        ("nfd umlaut", "failed for " + unicodedata.normalize("NFD", "Björn Müller") + " at row 2"),
        ("bare grave/acute", "failed for Amelie Lefevre at row 2"),
        ("precomposed grave/acute", "failed for Amélie Lefèvre at row 2"),
    ]
    for label, message in cases:
        scrubbed = repo._scrub(message, roster=roster)
        assert scrubbed == "failed for [REDACTED] at row 2", (
            f"{label} rendering must be fully redacted with surrounding text "
            f"byte-identical; got {scrubbed!r}"
        )


def test_accent_class_map_covers_latin1_and_keeps_original_entries():
    """WR-02 — the generated map still contains every original hand-transcribed
    entry (acute vowels, n-tilde, c-cedilla) AND the previously-missing common
    diacritics (umlaut/grave/circumflex vowels). Letters with no canonical
    base+mark decomposition stay absent (they fall through to literal escaping).
    """
    from app.db.repo import _ACCENT_CLASS_MAP

    for ch in "áéíóúñç" + "äëïöü" + "àèìòù" + "âêîôû":
        assert ch in _ACCENT_CLASS_MAP, f"map must cover {ch!r} (WR-02)"
    for ch in "øæßð":  # no canonical two-part decomposition — literal escape path
        assert ch not in _ACCENT_CLASS_MAP, (
            f"{ch!r} has no base+mark decomposition and must not be in the map"
        )


def test_scrub_nfd_stored_candidate_still_redacts_all_renderings():
    """WR-01 (phase-8 review) — the STORED candidate itself is NFD-decomposed
    (e.g. an alias learned from an NFD-encoded client email), and every message
    rendering — NFC, NFD, and bare-unaccented — must still be redacted.

    The pre-fix scrubber built the pattern from the raw candidate string, and
    _ACCENT_CLASS_MAP is keyed by PRECOMPOSED characters only — so an NFD-stored
    candidate bypassed the map and matched only its own NFD rendering: both the
    NFC and bare renderings of the full name leaked unredacted (total redaction
    failure for that name). The existing R2-1 test only varies the MESSAGE, never
    the stored candidate — this test closes that gap.
    """
    from app.db import repo

    nfd_name = unicodedata.normalize("NFD", "José García")
    assert nfd_name != "José García"  # sanity: genuinely decomposed
    jose = _employee(nfd_name, aliases=[])
    roster = Roster(business_id=uuid.uuid4(), employees=[jose])

    renderings = {
        "nfc": "failed for José García at row 3",
        "nfd": "failed for " + nfd_name + " at row 3",
        "bare": "failed for Jose Garcia at row 3",
    }
    for label, message in renderings.items():
        scrubbed = repo._scrub(message, roster=roster)
        assert "[REDACTED]" in scrubbed, (
            f"{label} rendering of an NFD-stored candidate must be redacted; "
            f"got {scrubbed!r}"
        )
        assert "Garc" not in scrubbed and "GARC" not in scrubbed, (
            f"name fragment leaked for {label} rendering: {scrubbed!r}"
        )
        assert scrubbed == "failed for [REDACTED] at row 3", (
            f"non-PII text must survive byte-identical for {label}: {scrubbed!r}"
        )


def test_scrub_mark_aware_boundary_trailing_accent_nfd(roster_from_seed):
    """R3-1 — a name ending in an accented character (no trailing consonant) must
    still fully consume an NFD-decomposed trailing combining mark; no character in
    the scrubbed output anywhere may have unicodedata.combining(ch) != 0.
    """
    from app.db import repo

    rene = _employee("René", aliases=[])
    roster = Roster(business_id=uuid.uuid4(), employees=[rene])

    decomposed = unicodedata.normalize("NFD", "René")
    message = "Contact " + decomposed + " about the run."
    scrubbed = repo._scrub(message, roster=roster)

    assert "[REDACTED]" in scrubbed
    for ch in scrubbed:
        assert unicodedata.combining(ch) == 0, (
            f"stray combining mark survived in scrubbed output: {scrubbed!r}"
        )
    assert (decomposed) not in scrubbed


def test_scrub_longest_first_no_offset_drift(roster_from_seed):
    """R2-1 continued — a short alias contained inside a longer full_name (e.g.
    "Dave" vs "Dave Reyes") redacts as ONE span, and surrounding text is byte-
    identical to the input outside the redacted span."""
    from app.db import repo

    dave = _employee("Dave Reyes", aliases=["Dave"])
    roster = Roster(business_id=uuid.uuid4(), employees=[dave])

    message = "Please confirm Dave Reyes submitted hours correctly."
    scrubbed = repo._scrub(message, roster=roster)

    assert scrubbed.count("[REDACTED]") == 1
    assert scrubbed == "Please confirm [REDACTED] submitted hours correctly."


def test_scrub_mark_aware_lookaround_no_over_redaction(roster_from_seed):
    """R2-3 — a short alias ("Tom") never matches as a prefix inside an unrelated
    word ("Tomorrow"); lookarounds are strictly stronger than \\b for plain ASCII."""
    from app.db import repo

    tom = _employee("Thomas Bergmann", aliases=["Tom Bergmann", "Tom"])
    roster = Roster(business_id=uuid.uuid4(), employees=[tom])

    message = "Tom submitted hours late. Tomorrow the batch reruns."
    scrubbed = repo._scrub(message, roster=roster)

    assert "[REDACTED]" in scrubbed
    assert "Tomorrow" in scrubbed


# ===========================================================================
# Section 2 — live-DB decision + reconciliation round-trip (two-factor guard)
# ===========================================================================


# `seeded_db` is provided by tests/conftest.py (shared two-factor-guarded fixture).


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_decision_roundtrip(seeded_db):
    """A clean run round-trips BOTH decision AND reconciliation from payroll_runs
    (LLM-08, D-A3-05)."""
    from app.db import repo
    from app.db.seed import seed as _seed

    result = _seed(dry_run=True)
    business_id = result.businesses[0]["id"]

    msg_id = f"<{uuid.uuid4()}@coastalcleaning.example>"
    email_id, _ = repo.insert_inbound_email(
        message_id=msg_id,
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="payroll@coastalcleaning.example",
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen 40 regular.",
        run_id=None,
    )
    run_id = repo.create_run(business_id=business_id, source_email_id=email_id)

    maria = next(e for e in result.employees if e.full_name == "Maria Chen")
    matches = [
        NameMatchResult(
            submitted_name="Maria Chen",
            matched_employee_id=maria.id,
            source="exact",
            resolved=True,
            reason="exact match",
        )
    ]
    extracted = Extracted(
        run_id=run_id,
        employees=[ExtractedEmployee(submitted_name="Maria Chen", hours_regular=Decimal("40"))],
        pay_period_start="2026-06-15",
    )
    decision = Decision(
        final_action="process",
        gate_reasons=[],
        unresolved_names=[],
        missing_fields=[],
        resolutions=matches,
    )

    repo.persist_extracted(run_id, extracted)
    repo.persist_decision(run_id, decision)
    repo.persist_reconciliation(run_id, matches)

    run = repo.load_run(run_id)
    assert run["decision"] is not None
    assert run["decision"]["final_action"] == "process"
    assert run["reconciliation"] is not None, "reconciliation must NOT be NULL (D-A3-05)"
    assert run["reconciliation"][0]["submitted_name"] == "Maria Chen"
    # The deterministic resolution carries source/resolved, NOT a confidence score.
    assert run["reconciliation"][0]["source"] == "exact"
    assert run["reconciliation"][0]["resolved"] is True
    assert "confidence" not in run["reconciliation"][0], (
        "the deterministic reconciliation JSONB must be confidence-free (D-21-01)"
    )
