-- Payroll Agent — DDL source of truth
-- Apply with: python -m app.db.bootstrap
-- Reset with: python -m app.db.bootstrap --reset
--
-- Table creation order matters for FK dependencies:
--   businesses → employees → payroll_runs → paystub_line_items → email_messages → eval_results
--   Circular FK (payroll_runs.source_email_id → email_messages.id) is deferred to an
--   ALTER TABLE block at the bottom so both tables exist before the FK is added.

-- ── Extension (idempotent) ────────────────────────────────────────────────────
-- gen_random_uuid() is provided by pgcrypto on local Postgres.
-- Supabase already has it; IF NOT EXISTS makes this a no-op there.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── 1. businesses ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS businesses (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT        NOT NULL,
    contact_email   TEXT        NOT NULL UNIQUE,
    -- D-8-09: verify, don't duplicate — the UNIQUE constraint above already
    -- creates an implicit btree index that serves find_business_by_sender's
    -- plain-equality lookup (repo.py). No separate CREATE INDEX is added.
    pay_period      TEXT        NOT NULL CHECK (pay_period IN ('weekly','biweekly','semi_monthly','monthly')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 2. employees ─────────────────────────────────────────────────────────────
-- Finding #1: updated_at column + UNIQUE(business_id, full_name) required by
-- Plan 03's ON CONFLICT (business_id, full_name) DO UPDATE upsert.
CREATE TABLE IF NOT EXISTS employees (
    id                          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id                 UUID        NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    full_name                   TEXT        NOT NULL,
    known_aliases               TEXT[]      NOT NULL DEFAULT '{}',
    pay_type                    TEXT        NOT NULL CHECK (pay_type IN ('hourly','salary')),
    hourly_rate                 NUMERIC(12,4),
    annual_salary               NUMERIC(14,2),
    retirement_contribution_pct NUMERIC(5,4)  NOT NULL DEFAULT 0,
    filing_status               TEXT        NOT NULL CHECK (filing_status IN ('single','married_jointly','married_separately')),
    step_2_checkbox             BOOLEAN     NOT NULL DEFAULT FALSE,
    -- WR-08: ge=0 in the Employee model is mirrored here as a runtime backstop
    -- (project "reconciliation check as backstop" philosophy). A negative W-4
    -- dollar amount or YTD wage silently corrupts the Pub 15-T worksheet / SS cap.
    step_3_dependents           NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (step_3_dependents >= 0),
    step_4a_other_income        NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (step_4a_other_income >= 0),
    step_4b_deductions          NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (step_4b_deductions >= 0),
    ytd_ss_wages                NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (ytd_ss_wages >= 0),
    pay_periods_per_year        INTEGER     NOT NULL CHECK (pay_periods_per_year IN (12,24,26,52)),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_employee_business_name UNIQUE (business_id, full_name)
);

-- ── 3. payroll_runs ───────────────────────────────────────────────────────────
-- Finding #2: source_email_id is declared as plain UUID with NO inline REFERENCES
-- email_messages — that FK is added in the deferred block below to avoid a
-- circular dependency DDL error (email_messages references payroll_runs.id, and
-- payroll_runs.source_email_id references email_messages.id).
--
-- D-02/D-03: status is TEXT + CHECK (not a native ENUM) so adding a value is a
-- one-line CHECK edit that can run inside a transaction. The 11 values mirror
-- RunStatus in app/models/status.py exactly — a CI test asserts set-equality.
CREATE TABLE IF NOT EXISTS payroll_runs (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id     UUID        NOT NULL REFERENCES businesses(id),
    source_email_id UUID,       -- FK to email_messages added below (circular ref)
    status          TEXT        NOT NULL DEFAULT 'received'
                                CHECK (status IN (
                                    'received',
                                    'extracting',
                                    'awaiting_reply',
                                    'computed',
                                    'awaiting_approval',
                                    'approved',
                                    'sent',
                                    'reconciled',
                                    'rejected',
                                    'error',
                                    'needs_operator'
                                )),
    extracted_data  JSONB,      -- D-06: persisted from Extracted.model_dump(mode="json")
    decision        JSONB,      -- D-06: persisted from Decision.model_dump(mode="json")
    -- D-A3-05 / D-21-06: the per-name resolutions (submitted_name, matched_employee_id,
    -- source, resolved, reason) live HERE as list[NameMatchResult].model_dump(mode="json").
    -- This JSONB is the SINGLE source of truth for reconciliation — the relational
    -- name_matches table is intentionally ABSENT (dropped in Phase 2.1 via bootstrap;
    -- CREATE IF NOT EXISTS cannot drop a live table, so the DROP runs in bootstrap.py).
    -- The deterministic shape carries no confidence score (D-21-01).
    reconciliation  JSONB,
    -- D-04: separate JSONB column for alias candidates so persist_reconciliation can
    -- never overwrite it on resume. Written by repo.set_alias_candidates in Wave 4.
    alias_candidates JSONB,
    pre_clarify_extracted JSONB,    -- D-19 MONEY-03: snapshot at awaiting_reply (IS NULL write-once guard)
    clarified_fields      JSONB,    -- D-13 MONEY-03: {employee_id: {field: outcome}} field-regression outcomes
    -- Phase 11 (D-11-01): counts clarification/clarification_field_regression sends
    -- for this run. Drives the round-aware send guard + the D-11-07 cap-to-
    -- needs_operator escalation. NOT NULL DEFAULT 0 — every run starts at round 0
    -- and old code never writes it, so the default is always correct for pre-Phase-11 rows.
    clarification_round  INT     NOT NULL DEFAULT 0,
    -- Phase 11 gap-closure (GAP-2/GAP-3, 11-06): bumped by clear_reply_context
    -- on every retrigger (D-11-04 extension) — scopes every round-machine
    -- email_messages read/write to the CURRENT conversation without deleting
    -- or mutating the append-only audit log's historical rows. NOT NULL
    -- DEFAULT 0 so every pre-existing run (which never retriggered) stays at
    -- epoch 0 forever, behavior-identical to pre-fix.
    reply_epoch     INT     NOT NULL DEFAULT 0,
    error_reason    TEXT,       -- D-A1-03 / FIX 7: orchestrator's persisted ERROR reason
    pay_period_start DATE,
    pay_period_end   DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Idempotent column adds for payroll_runs (Plan 02-01 / Plan 05-03) ───────────
-- CREATE TABLE IF NOT EXISTS above is a no-op on an existing (Phase 1) table, so
-- these ALTER ... ADD COLUMN IF NOT EXISTS blocks are what actually add the new
-- columns when re-applying schema.sql via the non-destructive bootstrap path.
-- All are no-ops on a fresh CREATE (the columns are already declared inline) and
-- on re-runs (IF NOT EXISTS). A new JSONB/TEXT column is invisible to the
-- status-drift guard, which parses only CHECK (col IN (...)) value sets.
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS reconciliation    JSONB;  -- D-A3-05
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS error_reason      TEXT;   -- D-A1-03
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS alias_candidates  JSONB;  -- D-04 (Plan 05-03)
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS record_only       BOOLEAN NOT NULL DEFAULT FALSE;  -- 06-08 HIGH-1: compose-created runs skip real Resend send
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS pre_clarify_extracted JSONB;  -- D-19 MONEY-03
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS clarified_fields      JSONB;  -- D-13 MONEY-03
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS error_detail          TEXT;   -- D-8-01/D-8-02: PII-scrubbed, stage-prefixed, truncated exception detail
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS clarification_round   INT NOT NULL DEFAULT 0;  -- D-11-01 (Phase 11 round machine)
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS reply_epoch            INT NOT NULL DEFAULT 0;  -- GAP-2/GAP-3 (Plan 11-06 epoch mechanism)

-- ── OPS2-02 hot-path indexes for payroll_runs ─────────────────────────────────
-- Serve load_all_runs's ORDER BY created_at DESC and find_awaiting_reply_for_header's
-- pr.status = 'awaiting_reply' filter (repo.py, confirmed in 08-RESEARCH.md).
CREATE INDEX IF NOT EXISTS idx_payroll_runs_created_at
    ON payroll_runs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_payroll_runs_status
    ON payroll_runs (status);

-- Folded todo 260623-06: idempotent DROP + RE-ADD of the payroll_runs status CHECK
-- constraint, removing the dead needs-clarification value. Mirrors the D-7.5-03a
-- atomic DROP+ADD pattern used above for email_messages_purpose_check — the DROP
-- and re-ADD happen inside one DO $$ ... END $$; block so a failed ADD rolls back
-- the DROP too (no half-migrated table).
-- WR-06 (phase-8 review): the DROP is anchored on the constraint's actual COLUMN
-- SET (conkey -> pg_attribute), never a name-substring match. The previous
-- `conname LIKE '%status%'` lookup (no STRICT) took ONE arbitrary matching row
-- and would have silently dropped-and-never-restored any unrelated future
-- constraint whose NAME merely contained 'status' (e.g. a send_status CHECK).
-- Matching conkey = {status} selects exactly the CHECK constraints that
-- constrain the status column and nothing else, however they are named. The
-- loop drops ALL of them, so the named re-ADD below can never collide and the
-- block stays idempotent on every bootstrap re-apply.
-- NOTE: this DO-block only fixes an EXISTING table (bootstrap re-apply path); the
-- inline CHECK edit above already gives a fresh bootstrap the correct 11-value set.
DO $$
DECLARE
    _con RECORD;
BEGIN
    FOR _con IN
        SELECT c.conname
        FROM pg_constraint c
        WHERE c.contype = 'c'
          AND c.conrelid = 'payroll_runs'::regclass
          AND (SELECT array_agg(a.attname::text)
               FROM pg_attribute a
               WHERE a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
              ) = ARRAY['status']
    LOOP
        EXECUTE 'ALTER TABLE payroll_runs DROP CONSTRAINT ' || quote_ident(_con.conname);
    END LOOP;
    ALTER TABLE payroll_runs ADD CONSTRAINT payroll_runs_status_check
        CHECK (status IN (
            'received',
            'extracting',
            'awaiting_reply',
            'computed',
            'awaiting_approval',
            'approved',
            'sent',
            'reconciled',
            'rejected',
            'error',
            'needs_operator'
        ));
END;
$$;

-- ── 4. paystub_line_items ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS paystub_line_items (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID        NOT NULL REFERENCES payroll_runs(id) ON DELETE CASCADE,
    employee_id         UUID        REFERENCES employees(id),
    submitted_name      TEXT        NOT NULL,
    hours_regular       NUMERIC(6,2)  NOT NULL DEFAULT 0,
    hours_overtime      NUMERIC(6,2)  NOT NULL DEFAULT 0,
    hours_vacation      NUMERIC(6,2)  NOT NULL DEFAULT 0,
    hours_sick          NUMERIC(6,2)  NOT NULL DEFAULT 0,
    hours_holiday       NUMERIC(6,2)  NOT NULL DEFAULT 0,
    gross_pay           NUMERIC(12,2) NOT NULL DEFAULT 0,
    pretax_401k         NUMERIC(12,2) NOT NULL DEFAULT 0,
    fica_ss             NUMERIC(12,2) NOT NULL DEFAULT 0,
    fica_medicare       NUMERIC(12,2) NOT NULL DEFAULT 0,
    federal_withholding NUMERIC(12,2) NOT NULL DEFAULT 0,
    state_withholding   NUMERIC(12,2),
    net_pay             NUMERIC(12,2) NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 5. email_messages ─────────────────────────────────────────────────────────
-- FOUND-02: UNIQUE on message_id makes duplicate webhook deliveries idempotent.
-- run_id references payroll_runs (exists at this point in the file).
CREATE TABLE IF NOT EXISTS email_messages (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id           UUID        REFERENCES payroll_runs(id),
    direction        TEXT        NOT NULL CHECK (direction IN ('inbound','outbound')),
    message_id       TEXT        NOT NULL,
    in_reply_to      TEXT,
    references_header TEXT,
    subject          TEXT,
    from_addr        TEXT,
    to_addr          TEXT,
    body_text        TEXT,
    -- Plan 05-03: D-13c sharpening (finding #1 + #3, Codex review):
    -- purpose distinguishes clarification from confirmation; inbound rows keep NULL.
    -- N4 MONEY-03: 'clarification_field_regression' added for field-regression runs.
    purpose          TEXT        CHECK (purpose IN ('clarification','confirmation','clarification_field_regression')),
    -- send_state is NULLABLE (NOT NOT NULL DEFAULT 'sent'): inbound rows have no send
    -- lifecycle and must keep NULL — giving them 'sent' would weaken audit semantics
    -- (R2-MEDIUM/HIGH finding). Outbound rows: 'reserved' before provider call,
    -- 'sent' on success, 'failed' on error (Phase 6). Phase 5 stub writes 'sent'.
    send_state       TEXT        CHECK (send_state IN ('reserved','sent','failed')),
    -- Phase 11 (D-11-01): NOT NULL DEFAULT 0 — a nullable round would let Postgres
    -- treat every confirmation row as distinct under the widened UNIQUE below,
    -- silently disabling the one-confirmation-per-run dedup guard (Pitfall #2).
    round            INT         NOT NULL DEFAULT 0,
    -- Phase 11 (D-11-02): NULL = unconsumed (the D-11-13 resume-read/redelivery
    -- signal). Set once, write-once, by repo.mark_reply_consumed.
    consumed_round   INT,
    -- Phase 11 gap-closure (GAP-2/GAP-3, 11-06): stamped at write time from the
    -- OWNING RUN's reply_epoch at the moment the row is created/linked
    -- (outbound send, or inbound reply linkage) — NEVER read back and mutated
    -- afterward. A row's epoch is a permanent, point-in-time fact about which
    -- conversation it belonged to. NOT NULL DEFAULT 0 so every pre-existing row
    -- (created before any run ever retriggered) is correctly epoch 0.
    epoch            INT         NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_message_id UNIQUE (message_id),
    -- uq_email_run_purpose_round (widened from uq_email_run_purpose, D-11-01):
    -- each run has at most one clarification (per round) and one confirmation
    -- outbound row. Postgres NULL != NULL so inbound rows (purpose=NULL) never conflict.
    CONSTRAINT uq_email_run_purpose_round UNIQUE (run_id, purpose, round)
);

-- ── Idempotent column adds for email_messages (Plan 05-03) ───────────────────
-- CREATE TABLE IF NOT EXISTS above is a no-op on an existing table, so these
-- ALTER ... ADD COLUMN IF NOT EXISTS blocks apply the new columns on a running DB.
-- Both columns are nullable (no DEFAULT) so existing rows are unaffected.
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS purpose
    TEXT CHECK (purpose IN ('clarification','confirmation','clarification_field_regression'));  -- finding #1, D-13c sharpening; N4 MONEY-03 adds clarification_field_regression
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS send_state
    TEXT CHECK (send_state IN ('reserved','sent','failed'));   -- finding #3, R2-HIGH fix; NULLABLE
-- Phase 11 (D-11-01/D-11-02): round/consumed_round idempotent adds for a running DB.
-- round is NOT NULL DEFAULT 0 (Pitfall #2 — see the inline CREATE TABLE comment);
-- consumed_round stays nullable (NULL = unconsumed).
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS round INT NOT NULL DEFAULT 0;
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS consumed_round INT;
-- GAP-2/GAP-3 (Plan 11-06): epoch idempotent add for a running DB. NOT NULL
-- DEFAULT 0 — every existing row predates the epoch mechanism and belongs to
-- epoch 0, matching every existing run's reply_epoch default.
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS epoch INT NOT NULL DEFAULT 0;

-- N4 MONEY-03: Idempotent DROP + RE-ADD of email_messages purpose CHECK constraint
-- (D-7.5-03a atomic DROP+ADD in one transaction). The new CHECK includes
-- 'clarification_field_regression'.
-- WR-06 (phase-8 review): same column-anchored matcher as the payroll_runs status
-- block above — the DROP selects CHECK constraints by their actual column set
-- (conkey = {purpose}), never by name substring. The previous
-- `conname LIKE '%purpose%'` would also have matched any future check whose name
-- contained 'purpose'; conkey-anchoring cannot. (uq_email_run_purpose is a UNIQUE
-- constraint, contype='u', so the contype='c' filter already excludes it.)
DO $$
DECLARE
    _con RECORD;
BEGIN
    FOR _con IN
        SELECT c.conname
        FROM pg_constraint c
        WHERE c.contype = 'c'
          AND c.conrelid = 'email_messages'::regclass
          AND (SELECT array_agg(a.attname::text)
               FROM pg_attribute a
               WHERE a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
              ) = ARRAY['purpose']
    LOOP
        EXECUTE 'ALTER TABLE email_messages DROP CONSTRAINT ' || quote_ident(_con.conname);
    END LOOP;
    ALTER TABLE email_messages ADD CONSTRAINT email_messages_purpose_check
        CHECK (purpose IN ('clarification','confirmation','clarification_field_regression'));
END;
$$;

-- Phase 11 (D-11-01): widen uq_email_run_purpose -> uq_email_run_purpose_round.
-- NOTE: Postgres does NOT support ADD CONSTRAINT IF NOT EXISTS — the DO $$ pg_constraint
-- guard is the ONLY correct idempotent pattern for adding a named constraint on an existing
-- table (mirror of the fk_payroll_runs_source_email DO $$ block above).
-- Per the D-7.5-03a comment: the DROP of the old 2-column constraint and the ADD of
-- the new 3-column constraint live in ONE atomic DO-block — a failed ADD rolls back
-- the DROP too, so a live migration can never end up with neither constraint present
-- (Pitfall #1: insert_email_message's ON CONFLICT arbiter must always have a match).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_email_run_purpose'
          AND conrelid = 'email_messages'::regclass
    ) THEN
        ALTER TABLE email_messages DROP CONSTRAINT uq_email_run_purpose;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_email_run_purpose_round'
          AND conrelid = 'email_messages'::regclass
    ) THEN
        ALTER TABLE email_messages
            ADD CONSTRAINT uq_email_run_purpose_round UNIQUE (run_id, purpose, round);
    END IF;
END;
$$;

-- Phase 11 (D-11-01) one-shot backfill: live payroll_runs rows that already sent
-- clarification(s) before this migration predate clarification_round entirely.
-- Deterministic and idempotent (re-running recomputes the same count from the
-- immutable sent-row history — RESEARCH Open Question #3): clarification_round
-- becomes the count of this run's SENT outbound clarification-purpose rows.
UPDATE payroll_runs pr
SET clarification_round = sub.sent_count
FROM (
    SELECT run_id, count(*) AS sent_count
    FROM email_messages
    WHERE direction = 'outbound'
      AND purpose IN ('clarification', 'clarification_field_regression')
      AND send_state = 'sent'
    GROUP BY run_id
) sub
WHERE pr.id = sub.run_id
  AND pr.clarification_round <> sub.sent_count;

-- Phase 11 (Pitfall #6) one-shot alias_candidates shape migration: live rows carry
-- the old flat shape ({token: null} or {token: "uuid-str"}); D-11-14 needs the
-- nested {token: {"suggested": id|null, "bound": id|null}} shape. Idempotent:
-- entries whose jsonb_typeof is already 'object' are left untouched, so re-running
-- this block on an already-migrated (or fresh) DB is a no-op.
DO $$
DECLARE
    _run RECORD;
    _migrated JSONB;
BEGIN
    FOR _run IN
        SELECT id, alias_candidates
        FROM payroll_runs
        WHERE alias_candidates IS NOT NULL
    LOOP
        SELECT jsonb_object_agg(
                   key,
                   CASE
                       WHEN jsonb_typeof(value) = 'object' THEN value
                       WHEN jsonb_typeof(value) = 'null' THEN
                           jsonb_build_object('suggested', NULL, 'bound', NULL)
                       ELSE
                           jsonb_build_object('suggested', NULL, 'bound', value)
                   END
               )
        INTO _migrated
        FROM jsonb_each(_run.alias_candidates);

        IF _migrated IS NOT NULL AND _migrated IS DISTINCT FROM _run.alias_candidates THEN
            UPDATE payroll_runs SET alias_candidates = _migrated WHERE id = _run.id;
        END IF;
    END LOOP;
END;
$$;

-- ── OPS2-02 hot-path index for email_messages ─────────────────────────────────
-- D-8-09: column order (run_id, direction, send_state) traced against live query
-- predicates in repo.py (08-RESEARCH.md Pattern 3), not copied from the audit's
-- guess. businesses.contact_email is deliberately excluded from any new index
-- here — it is already covered by its own NOT NULL UNIQUE constraint's implicit
-- index (see the comment on that column declaration above).
CREATE INDEX IF NOT EXISTS idx_email_messages_run_direction_state
    ON email_messages (run_id, direction, send_state);

-- ── 6. eval_results ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS eval_results (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    suite_run_id UUID        NOT NULL,
    fixture_id   TEXT        NOT NULL,
    metric_name  TEXT        NOT NULL,
    value        NUMERIC(8,4)  NOT NULL,
    details      JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── demo_sender_bindings: operator email → business mapping for Path-2 demo routing ────
-- demo_sender_bindings: operator email → business mapping for Path-2 demo routing
-- (HIGH-2 fix; never modifies businesses.contact_email).
-- POST /demo/bind UPSERTs here; find_business_by_sender gains an additive fallback
-- that checks this table when the primary contact_email match returns None.
-- One row maximum in practice (one operator), enforced by the PRIMARY KEY.
CREATE TABLE IF NOT EXISTS demo_sender_bindings (
    operator_email  TEXT        PRIMARY KEY,
    business_id     UUID        NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    bound_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Deferred FK: payroll_runs.source_email_id → email_messages.id ─────────────
-- Finding #2: resolves the circular FK between payroll_runs and email_messages.
-- email_messages already exists at this point so the FK is valid.
-- The DO block is idempotent — checks pg_constraint before adding so re-running
-- schema.sql (e.g. via bootstrap default path) never errors on "already exists".
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_payroll_runs_source_email'
          AND conrelid = 'payroll_runs'::regclass
    ) THEN
        ALTER TABLE payroll_runs
            ADD CONSTRAINT fk_payroll_runs_source_email
            FOREIGN KEY (source_email_id) REFERENCES email_messages(id);
    END IF;
END;
$$;
