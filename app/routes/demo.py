"""Demo affordances — POST /demo/bind, /demo/compose, /demo/send-test.

Also owns the demo allowlist constants (DEMO_FIXTURES, DEMO_FIXTURE_DEFAULT_KEY,
DEMO_OPERATOR_EMAIL, SEED_CONTACTS, SEED_BUSINESS_IDS); they are public names
because runs.py and dashboard.py import them.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form
from fastapi.responses import RedirectResponse

from app.db import repo
from app.email import gateway
from app.email.clean import clean_body
from app.routes import pipeline_glue

logger = logging.getLogger("payroll_agent.webhook")

router = APIRouter()

# Curated allowlist of demo fixtures mapped to their seeded business. Only fixtures
# whose from_addr resolves via repo.find_business_by_sender belong here — unknown
# senders are rejected by the webhook (INGEST-03).
# The server validates the posted fixture_key against this dict and falls back to the
# default key on a miss. Resolving a client-supplied path instead would let any caller
# name an arbitrary file for the server to open and replay.
DEMO_FIXTURES: dict[str, dict[str, str]] = {
    "coastal_exact": {
        "label": "Coastal Cleaning Co. — exact match",
        "path": "eval/fixtures/01_exact_match_coastal.json",
        "business_name": "Coastal Cleaning Co.",
    },
    "metro_alias": {
        "label": "Metro Deli — stored alias",
        "path": "eval/fixtures/02_stored_alias_metro.json",
        "business_name": "Metro Deli Group",
    },
    "summit_exact": {
        "label": "Summit Tech — exact match",
        "path": "eval/fixtures/12_exact_process_summit.json",
        "business_name": "Summit Tech Solutions",
    },
    "coastal_multi": {
        "label": "Coastal Cleaning Co. — multi-employee",
        "path": "eval/fixtures/10_multi_employee_coastal.json",
        "business_name": "Coastal Cleaning Co.",
    },
    "unknown_shorthand_metro": {
        "label": "Metro Deli — unknown shorthand 'Dave Reyes' (clarify + suggest)",
        "path": "eval/fixtures/04_unknown_shorthand_metro.json",
        "business_name": "Metro Deli Group",
    },
}
DEMO_FIXTURE_DEFAULT_KEY = "coastal_exact"

# ---------------------------------------------------------------------------
# Demo routing constants
# ---------------------------------------------------------------------------

# Hardcoded operator email for Path-2 demo binding. bind_demo_business writes
# demo_sender_bindings for Path-2 routing; the address is never user-supplied.
DEMO_OPERATOR_EMAIL = "pjnhek@gmail.com"

# Stable seed .example contacts. /demo/bind must NEVER mutate them: the fixtures and
# every routing path below key off these exact addresses, so rewriting a business's
# contact_email would silently re-point demo runs at the wrong business.
# Source: app/db/seed.py _BUSINESSES list — these match the seeded contact_email values.
SEED_CONTACTS: dict[str, str] = {
    "Coastal Cleaning Co.": "payroll@coastalcleaning.example",
    "Metro Deli Group": "hr@metrodeli.example",
    "Summit Tech Solutions": "finance@summittech.example",
}

# Stable seed UUIDs; /demo/compose uses these directly rather than going through
# find_business_by_sender, so the composer cannot be re-pointed by binding state.
# Source: app/db/seed.py _BUSINESSES list (fixed literals).
SEED_BUSINESS_IDS: dict[str, uuid.UUID] = {
    "Coastal Cleaning Co.": uuid.UUID("b0000001-0000-0000-0000-000000000001"),
    "Metro Deli Group": uuid.UUID("b0000002-0000-0000-0000-000000000002"),
    "Summit Tech Solutions": uuid.UUID("b0000003-0000-0000-0000-000000000003"),
}


# ---------------------------------------------------------------------------
# POST /demo/bind — unlinked operator route (NOT on landing page)
# ---------------------------------------------------------------------------


@router.post("/demo/bind")
def demo_bind(
    business_name: str = Form(...),
) -> RedirectResponse:
    """Operator-only: bind an operator email to a business for Path-2 real-email routing.

    Writes to demo_sender_bindings ONLY — businesses.contact_email is NEVER mutated.
    Seed .example contacts remain permanently stable.

    SECURITY: business_name is validated against the SEED_CONTACTS allowlist and
    operator_email is the hardcoded DEMO_OPERATOR_EMAIL constant — accepting either
    from the form would let any caller bind an arbitrary address to a business and
    receive that business's payroll mail.
    """
    if business_name not in SEED_CONTACTS:
        return RedirectResponse(url="/", status_code=303)

    success = repo.bind_demo_business(business_name, DEMO_OPERATOR_EMAIL, SEED_BUSINESS_IDS)
    if success:
        return RedirectResponse(url="/?bound=1", status_code=303)
    return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# POST /demo/compose — in-app recruiter composer (Path-1, no real email)
# ---------------------------------------------------------------------------


@router.post("/demo/compose")
def demo_compose(
    background_tasks: BackgroundTasks,
    business_name: str = Form(...),
    subject: str = Form(default="Payroll submission"),
    body: str = Form(default=""),
) -> RedirectResponse:
    """Recruiter in-app composer: fires the REAL pipeline for the selected business.

    Routes by stable seed business_id directly, with no find_business_by_sender call.
    Sets record_only=True on create_run, so the pipeline writes outbound rows WITHOUT
    calling Resend — the thread view and simulate-reply still work, but a recruiter
    clicking around the demo can never send real mail to a .example address.

    SECURITY:
    - business_name validated against the SEED_CONTACTS allowlist
    - body capped at 4000 chars, subject at 200 chars before any DB/LLM touch — an
      unbounded body would be persisted and then billed straight into the LLM call
    - from_addr is allowlist-resolved from SEED_CONTACTS, never taken from the form:
      a caller-supplied sender would let the composer impersonate another business
    - body goes to body_text only — no file open, no subprocess, no URL fetch
    - Jinja2 autoescape handles XSS on subsequent rendering
    """
    # Step 1: Validate business_name against allowlist.
    if business_name not in SEED_CONTACTS:
        return RedirectResponse(url="/", status_code=303)

    # Step 2: Length validation (server-side, before DB or LLM touch).
    if len(body) > 4000 or len(subject) > 200:
        return RedirectResponse(url="/", status_code=303)

    # Step 3: Resolve business_id from the stable seed constant — no
    # find_business_by_sender call, so binding state cannot re-point the composer.
    business_id = SEED_BUSINESS_IDS[business_name]

    # Step 4: from_addr is the seed .example contact (stable; never the operator email).
    # The thread view and simulate-reply's sender-revalidation spoof guard both compare
    # against it, so a drifting from_addr would break reply resumption.
    from_addr = SEED_CONTACTS[business_name]

    # Step 5: Build InboundEmail payload (mirrors demo_send_test construction).
    fresh_message_id = f"<{uuid.uuid4()}@demo.payroll-agent.local>"
    inbound_payload = {
        "id": str(uuid.uuid4()),
        "message_id": fresh_message_id,
        "in_reply_to": None,
        "references_header": None,
        "subject": subject or "Payroll submission",
        "from_addr": from_addr,
        "to_addr": "agent@payroll-agent.local",
        "body_text": body,
        "created_at": datetime.now(tz=UTC).isoformat(),
    }

    try:
        # Step 6: Parse, clean, insert inbound email row.
        email = gateway.parse_inbound(inbound_payload)
        cleaned = clean_body(email.body_text)

        email_id, inserted = repo.insert_inbound_email(
            message_id=email.message_id,
            in_reply_to=email.in_reply_to,
            references_header=email.references_header,
            subject=email.subject,
            from_addr=email.from_addr,
            to_addr=email.to_addr,
            body_text=cleaned,
            run_id=None,
        )
        if not inserted:
            # Shouldn't happen (fresh uuid4 message_id per click), but handle gracefully.
            logger.warning("demo_compose: duplicate message_id — redirecting to /runs")
            return RedirectResponse(url="/runs", status_code=303)

        # Step 7: Create the run with record_only=True — no provider send.
        run_id = repo.create_run(
            business_id=business_id,
            source_email_id=email_id,
            record_only=True,
        )

        # Step 8: Schedule pipeline in background; redirect to run detail.
        background_tasks.add_task(pipeline_glue.run_pipeline_bg, run_id)
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

    except Exception:
        logger.exception("demo_compose: failed to create compose run")
        return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# DASH-05: POST /demo/send-test — fire demo fixture with FRESH Message-ID per click
# ---------------------------------------------------------------------------


@router.post("/demo/send-test")
def demo_send_test(
    background_tasks: BackgroundTasks,
    fixture_key: str = Form(default=DEMO_FIXTURE_DEFAULT_KEY),
) -> RedirectResponse:
    """DASH-05: Fire a curated demo fixture through the pipeline with a fresh Message-ID.

    Accepts an optional fixture_key form field selecting among the DEMO_FIXTURES
    allowlist; any unknown / missing key falls back to the default (Coastal Cleaning
    exact match). The client NEVER supplies a file path — the server resolves the path
    from the allowlist, so a caller cannot name a file for the server to read.

    The fixture's original Message-ID is OVERRIDDEN with a fresh uuid4-based synthetic
    ID per click. Reusing the fixture's baked-in ID would collide with the uq_message_id
    UNIQUE constraint on email_messages, and the second click would be silently swallowed
    as a duplicate — the demo button would appear to do nothing. Each click must create a
    distinct run visible in the runs list.
    """
    # Server-side allowlist validation — never trust a client-supplied path.
    if fixture_key not in DEMO_FIXTURES:
        fixture_key = DEMO_FIXTURE_DEFAULT_KEY
    fixture_meta = DEMO_FIXTURES[fixture_key]
    fixture_path = Path(fixture_meta["path"])

    if fixture_path.exists():
        fixture_data = json.loads(fixture_path.read_text())
    else:
        # Fallback: build a minimal fixture from the seed business contact_email
        fixture_data = {
            "message_id": "",  # will be overridden below
            "in_reply_to": None,
            "references_header": None,
            "subject": "Demo payroll run",
            "from_addr": "payroll@coastalcleaning.example",
            "to_addr": "agent@payroll-agent.local",
            "body_text": "Maria Chen 40 regular hours. Thanks!",
        }

    # Mint a fresh synthetic Message-ID per click so the uq_message_id UNIQUE
    # constraint cannot silently drop a repeat click as a duplicate.
    fresh_message_id = f"<{uuid.uuid4()}@demo.payroll-agent.local>"
    fixture_data["message_id"] = fresh_message_id

    # Resolve from_addr from THIS fixture's business's seed contact via SEED_CONTACTS.
    # The seed .example contacts are permanently stable (nothing mutates
    # businesses.contact_email), so each fixture routes to its own business with zero DB
    # coupling and independent of demo_sender_bindings state — otherwise an armed
    # binding would drag every fixture to whichever business was bound last.
    business_name = fixture_meta.get("business_name")
    from_addr = SEED_CONTACTS.get(business_name) if business_name else None
    if from_addr is None:
        # Fallback for misconfigured fixture or tests: use the fixture file's from_addr
        from_addr = fixture_data.get("from_addr", "payroll@coastalcleaning.example")

    # Build the InboundEmail payload from the fixture, stripping non-model keys.
    # InboundEmail requires: id, message_id, in_reply_to, references_header,
    # subject, from_addr, to_addr, body_text, created_at.
    inbound_payload = {
        "id": fixture_data.get("id") or str(uuid.uuid4()),
        "message_id": fixture_data["message_id"],
        "in_reply_to": fixture_data.get("in_reply_to"),
        "references_header": fixture_data.get("references_header"),
        "subject": fixture_data.get("subject") or "Demo payroll run",
        "from_addr": from_addr,
        "to_addr": fixture_data.get("to_addr", "agent@payroll-agent.local"),
        "body_text": fixture_data.get("body_text", ""),
        "created_at": fixture_data.get("created_at") or datetime.now(tz=UTC).isoformat(),
    }
    inbound_email = gateway.parse_inbound(inbound_payload)

    cleaned = clean_body(inbound_email.body_text)

    try:
        email_id, inserted = repo.insert_inbound_email(
            message_id=inbound_email.message_id,
            in_reply_to=inbound_email.in_reply_to,
            references_header=inbound_email.references_header,
            subject=inbound_email.subject,
            from_addr=inbound_email.from_addr,
            to_addr=inbound_email.to_addr,
            body_text=cleaned,
            run_id=None,
        )

        if not inserted:
            # Collision is extremely unlikely (uuid4 IDs) but if it happens, redirect anyway.
            logger.warning("demo send-test: unexpected duplicate message_id %s", fresh_message_id)
            return RedirectResponse(url="/runs", status_code=303)

        business_id = repo.find_business_by_sender(inbound_email.from_addr)
        if business_id is None:
            logger.warning("demo send-test: unknown sender %s", inbound_email.from_addr)
            return RedirectResponse(url="/runs", status_code=303)

        run_id = repo.create_run(business_id=business_id, source_email_id=email_id)
        background_tasks.add_task(pipeline_glue.run_pipeline_bg, run_id)
        # Redirect to the /runs queue so the operator can watch the new run appear
        # and advance through statuses. Each click still creates a distinct run
        # (fresh Message-ID per click).
        return RedirectResponse(url="/runs", status_code=303)
    except Exception:
        # DB unavailable: still redirect to /runs rather than returning 500.
        # The run will not be created but the operator can see the (empty) list.
        logger.debug("demo send-test: DB unavailable — redirecting without creating run")

    # Fallback (duplicate Message-ID, unknown sender, or DB error): no specific run
    # to show — land on the triage queue.
    return RedirectResponse(url="/runs", status_code=303)
