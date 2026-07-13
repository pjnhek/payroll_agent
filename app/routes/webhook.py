"""POST /webhook/inbound — the thin webhook adapter.

This is a THIN HTTP adapter: no business logic, no LLM, no calc. It does only
the cheap, synchronous, idempotency-critical work, then schedules the LLM-heavy
pipeline as a FastAPI BackgroundTask and returns 200 fast (INGEST-01). Doing the
LLM work inline would blow the provider's webhook timeout and trigger redelivery
of an email that is already being processed.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import repo
from app.email import gateway
from app.email.clean import clean_body
from app.models.status import RunStatus
from app.routes import pipeline_glue

logger = logging.getLogger("payroll_agent.webhook")

router = APIRouter()


@router.post("/webhook/inbound")
async def inbound(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    """Ingest one inbound email, schedule the pipeline, return 200 fast.

    Security ordering — verify BEFORE parse. Every step below is ordered so that no
    untrusted bytes are interpreted until the request is authenticated:

      1. Read raw_body bytes first (HMAC verification is over the raw payload; parsing
         and re-serializing would change the bytes and break the signature check).
      2. Check for svix-* signature headers:
         - Present (Resend-signed webhook): verify BEFORE json.loads. A verify failure
           returns 400 before any JSON parsing happens.
         - Absent AND allow_unsigned_fixtures=False (the production default): return 400
           BEFORE json.loads. An unauthorized body is never parsed.
         - Absent AND allow_unsigned_fixtures=True (dev/test only): proceed to parse.
           Both the Resend-envelope and the canonical shape go through
           gateway.parse_inbound, which detects the shape internally.
      3. parse_inbound(raw_body) — dual-path, shape detection internal to the gateway.
      4. insert_inbound_email — explicit ON CONFLICT DO NOTHING dedup. The pipeline is
         enqueued ONLY when a new row was actually inserted, never for a duplicate.
      5. Reply routing, sender auth, create_run, background task.

    The invariant this ordering protects: in production ANY unsigned POST is rejected —
    both the Resend-envelope shape and the canonical InboundEmail shape. Accepting the
    canonical shape unsigned would be a full bypass of webhook authentication, letting
    anyone inject a payroll email attributed to a real business.
    """
    # Step 1: capture raw body bytes (needed for HMAC verification).
    raw_body: bytes = await request.body()

    settings = get_settings()
    allow_unsigned = settings.allow_unsigned_fixtures

    # Check for svix signature headers (indicates a Resend-signed webhook).
    is_signed = (
        "svix-id" in request.headers
        and "svix-timestamp" in request.headers
        and "svix-signature" in request.headers
    )

    # Step 2: verify before parse — see the ordering contract in the docstring.
    if is_signed:
        # Signed Resend webhook: verify BEFORE json.loads. ValueError → 400.
        try:
            gateway.verify(raw_body, dict(request.headers), settings.webhook_signing_secret)
        except (ValueError, Exception) as exc:
            logger.warning("webhook signature verification failed: %s", type(exc).__name__)
            return JSONResponse(status_code=400, content={"error": "invalid signature"})
        # Signature passed — proceed to parse.
    elif not allow_unsigned:
        # Unsigned request in prod (ALLOW_UNSIGNED_FIXTURES=False): reject BEFORE
        # json.loads. This branch is what closes the canonical-shape bypass — without
        # it, an attacker could skip the svix headers entirely, POST the canonical
        # InboundEmail shape, and have it ingested as a genuine client email.
        logger.warning("unsigned webhook rejected in production (ALLOW_UNSIGNED_FIXTURES=False)")
        return JSONResponse(status_code=400, content={"error": "unsigned webhook not allowed"})
    # else: allow_unsigned=True (dev/test mode) — proceed to parse without verification.

    # Step 3: parse (dual-path: shape detection inside gateway.parse_inbound).
    # Path A (real Resend envelope) does a two-step fetch — resend.EmailsReceiving.get(email_id)
    # — which calls the Resend API and can fail (bad/insufficient RESEND_API_KEY, API error,
    # malformed payload). An unhandled raise here returns a raw 500 to Resend, which then
    # retries the delivery indefinitely and surfaces only as "internal server error" with no
    # diagnostic. Catch it: log the exception type + a hint, and return a clean 502 so the
    # failure is legible and Resend backs off. Signature verification already happened
    # above, so this catch cannot swallow an authentication failure.
    try:
        email = gateway.parse_inbound(raw_body)
    except Exception as exc:  # noqa: BLE001 — webhook boundary: never leak a raw 500 to Resend
        logger.error(
            "inbound parse/fetch failed: %s (likely RESEND_API_KEY invalid or "
            "EmailsReceiving.get error) — returning 502, no run created",
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=502,
            content={"error": "inbound parse failed", "reason": type(exc).__name__},
        )

    # Clean the body BEFORE persisting, so email_messages.body_text holds the cleaned
    # text — it is the single cleaned-body source of truth that extraction reads back.
    cleaned = clean_body(email.body_text)

    # ── The ingest transaction (DATA-02) ────────────────────────────────────────
    # ONE transaction spans dedup-insert + reply-classification + sender-routing +
    # create_run, and it commits BEFORE background_tasks.add_task is ever called.
    #
    # Two invariants live here:
    #   1. No orphan rows. A crash mid-ingest must not leave an email row with no run.
    #   2. A reply can never spuriously create a second run. A header-bearing reply is
    #      classified as a reply-resume candidate INSIDE this same transaction, strictly
    #      BEFORE any code path that could reach create_run. Classify outside the
    #      transaction and a concurrent ingest can interleave between the read and the
    #      create, producing a duplicate run for a single reply. On the
    #      reply_candidate/late_reply/duplicate outcomes create_run is simply not
    #      reachable in the block below.
    #
    # The transaction commits exactly ONE of five outcomes: duplicate /
    # reply_candidate / late_reply / unknown_sender / new_run. All response shaping and
    # background-task scheduling happens strictly AFTER the `with` block exits — never
    # inside it, or a mid-transaction rollback would leave a background task already
    # scheduled against state that no longer exists.
    outcome: str
    email_id: uuid.UUID | None = None
    existing_run_id: uuid.UUID | None = None
    reply_run_id: uuid.UUID | None = None
    late_run_id: uuid.UUID | None = None
    business_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None

    with repo.get_connection() as conn, conn.transaction():
        # Step 1: explicit dedup via ON CONFLICT DO NOTHING RETURNING id.
        email_id, inserted = repo.insert_inbound_email(
            message_id=email.message_id,
            in_reply_to=email.in_reply_to,
            references_header=email.references_header,
            subject=email.subject,
            from_addr=email.from_addr,
            to_addr=email.to_addr,
            body_text=cleaned,
            run_id=None,
            conn=conn,
        )

        if not inserted:
            # Duplicate delivery (ON CONFLICT DO NOTHING → not inserted): the loser
            # attaches to the EXISTING run — report it, never create a second one.
            # insert_inbound_email returns (None, False) on conflict, so message_id
            # (already parsed above) is the only usable key to find the existing run.
            outcome = "duplicate"
            existing_run_id = repo.find_run_by_message_id(
                email.message_id, conn=conn
            )
        elif email.in_reply_to or email.references_header:
            assert email_id is not None
            # Reply classification READS the run INSIDE the transaction, before any
            # code path that could reach create_run — see the invariant above.
            reply_run_id = repo.find_awaiting_reply_for_header(
                in_reply_to=email.in_reply_to,
                references_header=email.references_header,
                conn=conn,
            )
            if reply_run_id is not None:
                outcome = "reply_candidate"
                # Back-fill run_id on the reply row INSIDE this same transaction so
                # real client replies appear in the run-detail thread view
                # (load_thread_messages), like the simulate-reply demo path already
                # does. Safe because inbound rows keep purpose=NULL, so
                # uq_email_run_purpose never conflicts, and every routing query on
                # email_messages.run_id filters direction='outbound' — linking an
                # inbound row cannot perturb reply routing.
                repo.link_email_to_run(email_id, reply_run_id, conn=conn)
            else:
                late_run_id = repo.find_any_run_for_header(
                    in_reply_to=email.in_reply_to,
                    references_header=email.references_header,
                    conn=conn,
                )
                if late_run_id is not None:
                    outcome = "late_reply"
                    # Link late replies too — they are otherwise invisible in any
                    # join-based audit of the run's thread.
                    repo.link_email_to_run(email_id, late_run_id, conn=conn)
                else:
                    # No header match at all — fall through to ordinary
                    # first ingest exactly like a non-reply inbound.
                    business_id = repo.find_business_by_sender(
                        email.from_addr, conn=conn
                    )
                    if business_id is None:
                        outcome = "unknown_sender"
                    else:
                        run_id = repo.create_run(
                            business_id=business_id,
                            source_email_id=email_id,
                            conn=conn,
                        )
                        outcome = "new_run"
        else:
            # Ordinary (non-reply) inbound: sender-route + create_run.
            business_id = repo.find_business_by_sender(
                email.from_addr, conn=conn
            )
            if business_id is None:
                outcome = "unknown_sender"
            else:
                run_id = repo.create_run(
                    business_id=business_id,
                    source_email_id=email_id,
                    conn=conn,
                )
                outcome = "new_run"
    # ── Transaction committed. Everything below is post-commit response shaping
    # + background task scheduling — never inside the `with` block above. ──────

    if outcome == "duplicate":
        logger.info("duplicate inbound message_id=%s — no second run", email.message_id)
        # Redelivery re-schedule: a redelivered webhook carrying a reply is normally
        # just a no-op duplicate — but if the PERSISTED reply row is still unconsumed
        # AND its run is still awaiting_reply, the original resume never happened (dead
        # background task / missed delivery) and this redelivery is the only signal
        # we will ever get. Without this branch the run stalls in awaiting_reply
        # forever and the client's answer is silently dropped.
        #
        # Load the row by message_id — NEVER rebuild the reply from this request's body.
        # The persisted row holds the CLEANED body; re-cleaning the redelivered raw body
        # would produce a different text than the one the first delivery stored.
        #
        # Re-schedule only if both conditions hold. A consumed reply, or a run no longer
        # awaiting_reply, stays a pure no-op (the duplicate response below). The CAS
        # claim inside resume_pipeline (AWAITING_REPLY -> EXTRACTING) makes any
        # double-scheduling safe.
        reply_row = repo.get_inbound_by_message_id(email.message_id)
        if (
            reply_row is not None
            and reply_row.get("consumed_round") is None
            and reply_row.get("run_id") is not None
        ):
            linked_run = repo.load_run(reply_row["run_id"])
            if (
                linked_run is not None
                and linked_run.get("status") == RunStatus.AWAITING_REPLY.value
            ):
                # Re-assert the sender revalidation before dispatching this redelivery
                # re-schedule. A spoofed reply that already failed revalidation on first
                # delivery is left linked+unconsumed — exactly the state this branch
                # resumes from. Without this re-check, redelivering the same message_id
                # would launder the spoofed reply straight into the pipeline.
                if pipeline_glue.reply_sender_ok(reply_row, linked_run):
                    logger.info(
                        "run_id=%s redelivery reschedule", reply_row["run_id"]
                    )
                    background_tasks.add_task(
                        pipeline_glue.resume_pipeline_bg,
                        reply_row["run_id"],
                        pipeline_glue.row_to_inbound(reply_row),
                    )
                else:
                    logger.warning(
                        "run_id=%s redelivery blocked — sender mismatch persists",
                        reply_row["run_id"],
                    )
        return JSONResponse(
            status_code=200,
            content={
                "status": "duplicate",
                "message_id": email.message_id,
                "run_id": str(existing_run_id) if existing_run_id else None,
            },
        )

    if outcome == "reply_candidate":
        # The transaction's classification is authoritative — do NOT re-run
        # find_awaiting_reply_for_header/find_any_run_for_header here. Re-reading the
        # header match post-commit reintroduces the duplicate-run race in a different
        # shape. Re-run ONLY the sender revalidation: a pure read-then-branch, no write.
        assert reply_run_id is not None
        return pipeline_glue.finish_reply_resume(reply_run_id, email, cleaned, background_tasks)

    if outcome == "late_reply":
        logger.info(
            "late reply: header matched run %s not in awaiting_reply — not resumed",
            late_run_id,
        )
        return JSONResponse(
            status_code=200,
            content={"status": "late_reply", "run_id": str(late_run_id)},
        )

    if outcome == "unknown_sender":
        logger.warning("unknown sender from_addr=%s — stopped, no run", email.from_addr)
        return JSONResponse(
            status_code=200,
            content={"status": "unknown_sender", "from_addr": email.from_addr},
        )

    # outcome == "new_run"
    # Schedule the LLM-heavy pipeline AFTER the commit (in prod); SYNCHRONOUS
    # under TestClient so the end-to-end test can assert the pause immediately.
    assert run_id is not None
    background_tasks.add_task(pipeline_glue.run_pipeline_bg, run_id)

    return JSONResponse(
        status_code=200,
        content={"status": "accepted", "run_id": str(run_id)},
    )
