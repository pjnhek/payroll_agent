-- Pyrl — DDL source of truth
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
    -- Verify, don't duplicate: the UNIQUE constraint above already creates an
    -- implicit btree index that serves find_business_by_sender's plain-equality
    -- lookup. A separate CREATE INDEX here would be dead weight on every write.
    pay_period      TEXT        NOT NULL CHECK (pay_period IN ('weekly','biweekly','semi_monthly','monthly')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 2. employees ─────────────────────────────────────────────────────────────
-- updated_at + UNIQUE(business_id, full_name) are both required by seed.py's
-- ON CONFLICT (business_id, full_name) DO UPDATE upsert — without the constraint
-- there is no conflict target and the upsert cannot compile.
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
    -- The Employee model's ge=0 is mirrored here as a DB-level backstop. A
    -- negative W-4 dollar amount or YTD wage does not error anywhere — it silently
    -- corrupts the Pub 15-T worksheet or the SS wage-base cap and mis-taxes the
    -- employee, so the database refuses to store one.
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
-- source_email_id is declared as a plain UUID with NO inline REFERENCES
-- email_messages: that FK is added in the deferred block at the bottom of this file.
-- The two tables reference each other (email_messages.run_id -> payroll_runs.id, and
-- payroll_runs.source_email_id -> email_messages.id), so an inline FK here is a
-- circular-dependency DDL error.
--
-- status is TEXT + CHECK, deliberately NOT a native ENUM, so adding a value is a
-- one-line CHECK edit that runs inside a transaction (ALTER TYPE ... ADD VALUE
-- cannot). The 11 values mirror RunStatus in app/models/status.py exactly, and a CI
-- test asserts set-equality — this column IS the state machine, so a drift between
-- the enum and the DB is a runtime crash at a status write.
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
    extracted_data  JSONB,      -- persisted from Extracted.model_dump(mode="json")
    decision        JSONB,      -- persisted from Decision.model_dump(mode="json")
    -- The per-name resolutions (submitted_name, matched_employee_id, source, resolved,
    -- reason) live HERE as list[NameMatchResult].model_dump(mode="json"). This JSONB
    -- is the SINGLE source of truth for reconciliation; there is deliberately no
    -- relational name_matches table (CREATE IF NOT EXISTS cannot drop a live table, so
    -- bootstrap.py drops the legacy one explicitly). The deterministic NameMatchResult
    -- shape carries no confidence score — there is nothing here to mistake for one.
    reconciliation  JSONB,
    -- Alias candidates get their OWN column, not a key inside reconciliation, so
    -- persist_reconciliation on resume can never overwrite them. Written by
    -- repo.set_alias_candidates.
    alias_candidates JSONB,
    pre_clarify_extracted JSONB,    -- write-once snapshot taken at awaiting_reply
    clarified_fields      JSONB,    -- {employee_id: {field: outcome}} field-regression outcomes
    -- list[HoursChange] — cross-round paid->paid hours CHANGES (20 -> 40 regular). Written
    -- UNCONDITIONALLY (as [] when there are none) by every run and every resume, so a stale
    -- value from a dead attempt is structurally impossible. DISPLAY-ONLY: rendered to the
    -- operator at the approval gate, never read by decide().
    hours_changes         JSONB,
    -- Counts clarification / clarification_field_regression sends for this run. Drives
    -- the round-aware send guard and the cap-to-needs_operator escalation. NOT NULL
    -- DEFAULT 0, so a run that has never clarified reads as round 0 rather than NULL.
    clarification_round  INT     NOT NULL DEFAULT 0,
    -- Bumped by clear_reply_context on every retrigger. Scopes every round-machine
    -- email_messages read/write to the CURRENT conversation WITHOUT deleting or
    -- mutating the append-only audit log's historical rows: the old rows stay
    -- queryable, just invisible to the current epoch. NOT NULL DEFAULT 0, so a run
    -- that never retriggered stays at epoch 0 forever.
    reply_epoch     INT     NOT NULL DEFAULT 0,
    error_reason    TEXT,       -- the orchestrator's persisted ERROR reason
    pay_period_start DATE,
    pay_period_end   DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Idempotent column adds for payroll_runs ───────────────────────────────────
-- CREATE TABLE IF NOT EXISTS above is a no-op on an EXISTING table, so it cannot add
-- a new column to a live DB. These ALTER ... ADD COLUMN IF NOT EXISTS statements are
-- what actually migrate a running database when schema.sql is re-applied via the
-- non-destructive bootstrap path. They are no-ops on a fresh CREATE (the columns are
-- already declared inline) and on re-runs (IF NOT EXISTS). A new JSONB/TEXT column is
-- invisible to the status-drift guard, which parses only CHECK (col IN (...)) sets.
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS reconciliation    JSONB;
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS error_reason      TEXT;
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS alias_candidates  JSONB;
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS record_only       BOOLEAN NOT NULL DEFAULT FALSE;  -- compose-created demo runs skip the real provider send
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS pre_clarify_extracted JSONB;
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS clarified_fields      JSONB;
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS hours_changes         JSONB;   -- display-only cross-round paid->paid hours changes
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS error_detail          TEXT;   -- PII-scrubbed, stage-prefixed, truncated exception detail
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS clarification_round   INT NOT NULL DEFAULT 0;
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS reply_epoch            INT NOT NULL DEFAULT 0;

-- ── Hot-path indexes for payroll_runs ─────────────────────────────────────────
-- Serve load_all_runs's ORDER BY created_at DESC and find_awaiting_reply_for_header's
-- pr.status = 'awaiting_reply' filter — both traced against the live queries in
-- app/db/repo/, not guessed.
CREATE INDEX IF NOT EXISTS idx_payroll_runs_created_at
    ON payroll_runs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_payroll_runs_status
    ON payroll_runs (status);

-- Idempotent DROP + RE-ADD of the payroll_runs status CHECK constraint. The DROP and
-- the re-ADD live inside ONE DO $$ ... END $$; block so a failed ADD rolls back the
-- DROP too — a live migration can never leave the table with NO status constraint,
-- which would let any string be written into the column that drives the state machine.
--
-- The DROP is anchored on the constraint's actual COLUMN SET (conkey -> pg_attribute),
-- never on a name substring. A `conname LIKE '%status%'` lookup would also match an
-- unrelated future constraint whose NAME merely contains 'status' (e.g. a send_status
-- CHECK) and silently drop it without ever restoring it. Matching conkey = {status}
-- selects exactly the CHECK constraints on the status column, however they are named.
-- The loop drops ALL of them, so the named re-ADD below can never collide and the
-- block stays idempotent on every bootstrap re-apply.
--
-- This DO-block only migrates an EXISTING table; a fresh bootstrap already gets the
-- correct value set from the inline CHECK above. Both lists must be edited together.
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
-- UNIQUE on message_id is what makes duplicate webhook deliveries idempotent: a
-- provider redelivery hits the constraint instead of creating a second run.
-- run_id references payroll_runs (which exists at this point in the file).
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
    -- purpose distinguishes clarification from confirmation; inbound rows keep NULL.
    -- 'clarification_field_regression' is the field-regression ("did you forget the
    -- OT?") variant, kept distinct so its sends have their own idempotency key.
    purpose          TEXT        CHECK (purpose IN ('clarification','confirmation','clarification_field_regression')),
    -- send_state is deliberately NULLABLE rather than NOT NULL DEFAULT 'sent':
    -- inbound rows have no send lifecycle and must keep NULL. Defaulting them to
    -- 'sent' would assert a delivery that never happened and corrupt the audit trail.
    -- Outbound rows: 'reserved' before the provider call, 'sent' on success, 'failed'
    -- on error — so a crash mid-send is distinguishable from a completed send.
    send_state       TEXT        CHECK (send_state IN ('reserved','sent','failed')),
    -- NOT NULL DEFAULT 0 is load-bearing: Postgres treats NULLs as DISTINCT in a
    -- UNIQUE constraint, so a nullable round would make every confirmation row unique
    -- under the widened UNIQUE below — silently disabling the one-confirmation-per-run
    -- dedup guard and letting the client be emailed the same payroll twice.
    round            INT         NOT NULL DEFAULT 0,
    -- NULL = unconsumed. This is the signal the resume path and the redelivery sweep
    -- both read. Set once, write-once, by repo.mark_reply_consumed.
    consumed_round   INT,
    -- Stamped at write time from the OWNING RUN's reply_epoch, at the moment the row
    -- is created or linked (an outbound send, or an inbound reply's linkage) — and
    -- NEVER read back and mutated afterward. A row's epoch is a permanent,
    -- point-in-time fact about which conversation it belonged to. NOT NULL DEFAULT 0,
    -- so a row written before any run ever retriggered is correctly epoch 0.
    epoch            INT         NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_message_id UNIQUE (message_id),
    -- Each run has at most one clarification (per round, per epoch) and one
    -- confirmation outbound row. Postgres treats NULL != NULL, so inbound rows
    -- (purpose=NULL) never conflict here.
    --
    -- WHY epoch MUST be in this CONSTRAINT, not only in the WHERE-clause reads:
    -- a retrigger resets clarification_round to 0, so the retriggered run's fresh
    -- round-0 send carries the SAME (run_id, purpose, round) tuple as the stale
    -- pre-retrigger round-0 row. Without epoch here, insert_email_message's
    -- `ON CONFLICT (run_id, purpose, round) DO UPDATE` would silently UPSERT (mutate)
    -- that historical row instead of appending a new one — corrupting the append-only
    -- audit log on every retrigger and destroying the evidence of what was actually
    -- sent to the client. With epoch in the key the two rows are distinct conflict
    -- targets, so the retriggered send always INSERTs a genuinely new row.
    --
    -- INVARIANT: this constraint and insert_email_message's ON CONFLICT arbiter name
    -- the SAME four columns. If they ever drift apart, the INSERT either crashes on a
    -- constraint it does not name or mutates a row it should have inserted beside.
    -- Change both, in the same step, or neither.
    CONSTRAINT uq_email_run_purpose_round_epoch UNIQUE (run_id, purpose, round, epoch)
);

-- ── Idempotent column adds for email_messages ────────────────────────────────
-- CREATE TABLE IF NOT EXISTS above is a no-op on an existing table, so these
-- ALTER ... ADD COLUMN IF NOT EXISTS statements are what migrate a running DB.
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS purpose
    TEXT CHECK (purpose IN ('clarification','confirmation','clarification_field_regression'));
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS send_state
    TEXT CHECK (send_state IN ('reserved','sent','failed'));   -- NULLABLE by design (see above)
-- round is NOT NULL DEFAULT 0 (a nullable round breaks the dedup guard — see the
-- inline CREATE TABLE comment); consumed_round stays nullable (NULL = unconsumed).
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS round INT NOT NULL DEFAULT 0;
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS consumed_round INT;
-- epoch: NOT NULL DEFAULT 0 — every row that predates the epoch mechanism belongs to
-- epoch 0, matching every existing run's reply_epoch default.
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS epoch INT NOT NULL DEFAULT 0;

-- Idempotent DROP + RE-ADD of the email_messages purpose CHECK, in one atomic
-- DO-block (a failed ADD rolls back the DROP, so the table is never left
-- unconstrained). Same column-anchored matcher as the payroll_runs status block: the
-- DROP selects CHECK constraints by their actual column set (conkey = {purpose}),
-- never by name substring, so it cannot silently drop an unrelated future constraint
-- whose name merely contains 'purpose'. (uq_email_run_purpose is a UNIQUE constraint,
-- contype='u', so the contype='c' filter already excludes it.)
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

-- Widen uq_email_run_purpose -> uq_email_run_purpose_round on a running DB.
-- Postgres does NOT support ADD CONSTRAINT IF NOT EXISTS, so a DO $$ pg_constraint
-- guard is the only correct idempotent pattern for adding a named constraint to an
-- existing table (same shape as the fk_payroll_runs_source_email block below).
-- The DROP of the old 2-column constraint and the ADD of the new 3-column one live in
-- ONE atomic DO-block: a failed ADD rolls back the DROP, so a live migration can never
-- end up with NEITHER constraint present — which would leave insert_email_message's
-- ON CONFLICT arbiter with no matching constraint, and every send would raise.
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

-- Widen uq_email_run_purpose_round -> uq_email_run_purpose_round_epoch.
-- Same atomic DROP+ADD-in-one-DO-block idiom as the widening above: a failed ADD rolls
-- back the DROP, so a live migration can never end up with neither constraint present.
-- insert_email_message's ON CONFLICT arbiter must always have a matching constraint —
-- now on all four columns (run_id, purpose, round, epoch).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_email_run_purpose_round'
          AND conrelid = 'email_messages'::regclass
    ) THEN
        ALTER TABLE email_messages DROP CONSTRAINT uq_email_run_purpose_round;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_email_run_purpose_round_epoch'
          AND conrelid = 'email_messages'::regclass
    ) THEN
        ALTER TABLE email_messages
            ADD CONSTRAINT uq_email_run_purpose_round_epoch UNIQUE (run_id, purpose, round, epoch);
    END IF;
END;
$$;

-- One-shot backfill: live payroll_runs rows that already sent clarification(s) predate
-- the clarification_round column entirely and would otherwise read as round 0, letting
-- the round-aware guard re-ask a question already asked. Deterministic and idempotent:
-- re-running recomputes the same count from the immutable sent-row history, since
-- clarification_round is simply the count of this run's SENT outbound
-- clarification-purpose rows.
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

-- One-shot alias_candidates shape migration: live rows may carry the old flat shape
-- ({token: null} or {token: "uuid-str"}), while the bind-on-confirmation alias learning
-- reads the nested {token: {"suggested": id|null, "bound": id|null}} shape. Idempotent:
-- entries whose jsonb_typeof is already 'object' are left untouched, so re-running this
-- block on an already-migrated (or fresh) DB is a no-op.
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

-- ── Hot-path index for email_messages ────────────────────────────────────────
-- Column order (run_id, direction, send_state) is traced against the live query
-- predicates in app/db/repo/emails.py, not guessed — a composite index only helps if
-- its leading columns match the query's equality filters. businesses.contact_email is
-- deliberately NOT indexed here: it is already covered by the implicit index behind
-- its NOT NULL UNIQUE constraint (see the comment on that column above).
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

-- ── 7. jobs (NEW — durable queue transport substrate) ───────────────────────
-- The durable transport layer the async worker claims work from. The
-- authoritative external design for this table has FOUR DOCUMENTED DEVIATIONS
-- applied below — each a correction, not an improvisation. See the inline
-- comments for the reasoning behind each one.
--
-- Carries IDENTIFIERS ONLY. There is physically nowhere to store a payroll
-- status or business data — no payload column, no "next status" column. The
-- queue's vocabulary (JobKind/JobState, app/models/job.py) is transport state;
-- payroll_runs.status is the SOLE business state machine. A job row can never
-- say "advance this run to APPROVED" because there is no column that could
-- hold such a thing.
CREATE TABLE IF NOT EXISTS jobs (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- DEVIATION 1: an earlier full design lists four eventual kinds
    -- ('ingest','run_pipeline','resume_reply','operator_resume'). Only
    -- 'run_pipeline' has a real handler today, and the CI drift guard for this
    -- table asserts set(JobKind) == set(dispatch.HANDLERS) — set EQUALITY.
    -- Declaring three kinds with no handler makes that guard permanently
    -- unsatisfiable. Widening this CHECK later (once `jobs` holds live rows)
    -- must use the idempotent DO-block DROP+RE-ADD idiom already proven twice
    -- in this file (payroll_runs.status, email_messages.purpose) — NOT a
    -- second inline edit, because by then a bare CREATE TABLE-time CHECK edit
    -- would be a no-op against a live table. Today jobs has zero rows, so an
    -- inline CHECK is correct and deliberately adds NO third conkey-anchored
    -- DO-block (test_do_block_constraint_drops_are_column_anchored's count of
    -- 2 stays correct).
    kind          TEXT        NOT NULL CHECK (kind IN ('run_pipeline')),
    dedup_key     TEXT        NOT NULL,
    -- DEVIATION 3: an earlier full design cascades this FK on delete. This
    -- table deliberately does NOT cascade, matching the email_messages
    -- precedent (append-only audit log). A cascading delete would silently
    -- vaporize a run's attempt history — the one thing this queue exists to
    -- make auditable. Runs are never deleted today, so this is theoretical
    -- either way; choose the direction that cannot lose the audit trail.
    run_id        UUID        REFERENCES payroll_runs(id),
    -- Reserved for a future durable-ingest / resume-reply kind. Nullable and
    -- unused today; its FK target (email_messages) already exists, so
    -- declaring it now is free — CREATE TABLE IF NOT EXISTS is a no-op against
    -- a live table, so adding it later would cost an explicit ALTER block.
    email_id      UUID        REFERENCES email_messages(id),
    -- DEVIATION 2: an earlier full design also declares an `event_id` column
    -- with a REFERENCES clause pointing at a durable-ingest events table.
    -- OMITTED ENTIRELY — that table does NOT EXIST in this schema yet (grep
    -- CREATE TABLE: businesses, employees, payroll_runs, paystub_line_items,
    -- email_messages, eval_results, demo_sender_bindings, jobs). A FK to a
    -- non-existent relation fails the bootstrap outright. A future durable
    -- ingest effort creates that events table AND adds this column together,
    -- via the ALTER TABLE ... ADD COLUMN IF NOT EXISTS idiom this file already
    -- documents (see the comments above payroll_runs's and email_messages's
    -- idempotent column-add blocks).
    --
    -- Reserved for the same future ingest work. Nullable and unused today; its
    -- FK target (businesses) already exists, so declaring it now is free for
    -- the same reason as email_id above.
    business_id   UUID        REFERENCES businesses(id),
    -- Written, never read today — exists so per-tenant fairness stays a later
    -- ORDER BY change rather than a migration. Fairness lanes are out of
    -- scope for the current build.
    priority      INT         NOT NULL DEFAULT 100,
    state         TEXT        NOT NULL DEFAULT 'pending'
                              CHECK (state IN ('pending','leased','done','dead')),
    attempts      INT         NOT NULL DEFAULT 0,
    max_attempts  INT         NOT NULL DEFAULT 5,
    available_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_token   UUID,
    leased_until  TIMESTAMPTZ,
    last_error    TEXT,       -- PII-scrubbed through the existing repo._scrub/_build_error_detail
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_jobs_dedup_key UNIQUE (dedup_key),
    -- Load-bearing: a half-written lease (state='leased' with a NULL
    -- lease_token) is indistinguishable from an unclaimed job, and the fencing
    -- predicate `lease_token = %(token)s` would silently degrade to no fence at
    -- all — a zombie worker's write could then land undetected. The database
    -- refuses to store one. Same discipline as employees.step_3_dependents >= 0.
    CONSTRAINT ck_jobs_lease_coherent CHECK (
        (state =  'leased' AND lease_token IS NOT NULL AND leased_until IS NOT NULL) OR
        (state <> 'leased' AND lease_token IS NULL     AND leased_until IS NULL)
    ),
    -- DEVIATION 4 — ADDS a constraint an earlier full design does NOT have.
    -- run_id stays NULLABLE at the column level (a future `ingest` kind
    -- genuinely has no run yet), but 'run_pipeline' is the ONLY kind that
    -- exists today, and it is meaningless without a run. Trace what a
    -- null-run run_pipeline job does today: it is claimed, dispatched to
    -- handle_run_pipeline, which calls claim_status(None, ...) — a no-op —
    -- and returns normally, so drain_once() marks it 'done'. A job that
    -- processed no payroll, recorded as a SUCCESS — silent loss, in the money
    -- path, with no error anywhere. This is a DATABASE constraint, not only a
    -- Python check, because the guarantee must hold against every FUTURE
    -- caller — a future ingest producer, a raw SQL insert, an ops script —
    -- not merely against enqueue_job's signature. enqueue_job ALSO rejects
    -- this in Python because a legible ValueError beats a driver
    -- IntegrityError; the two are independent guards, each proven by its own
    -- test. This is an INLINE table constraint (jobs has no live rows to
    -- migrate on first deploy), so it deliberately adds NO third
    -- conkey-anchored DO-block — same reasoning as DEVIATION 1.
    CONSTRAINT ck_jobs_run_pipeline_requires_run CHECK (
        kind <> 'run_pipeline' OR run_id IS NOT NULL
    )
);

-- Partial index matching the claim query's WHERE predicate EXACTLY. done/dead
-- rows (the overwhelming majority over time) are never indexed, so the claim
-- stays O(1) forever with no purge job. No index on run_id today: nothing in
-- the current scope queries jobs by run_id — an ops view that would is a
-- future addition.
CREATE INDEX IF NOT EXISTS idx_jobs_claimable
    ON jobs (priority, available_at)
    WHERE state IN ('pending','leased');

-- ── demo_sender_bindings ─────────────────────────────────────────────────────
-- Operator email → business mapping, used to route real inbound mail from the
-- operator's own mailbox. Exists so that routing NEVER requires modifying
-- businesses.contact_email, which the seed data owns.
-- POST /demo/bind UPSERTs here; find_business_by_sender consults this table only as a
-- fallback, when the primary contact_email match returns None.
-- One row per operator, enforced by the PRIMARY KEY.
CREATE TABLE IF NOT EXISTS demo_sender_bindings (
    operator_email  TEXT        PRIMARY KEY,
    business_id     UUID        NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    bound_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Deferred FK: payroll_runs.source_email_id → email_messages.id ─────────────
-- Resolves the circular FK between payroll_runs and email_messages: the constraint is
-- added HERE, at the bottom, because email_messages does not exist yet when
-- payroll_runs is created above.
-- The DO block is idempotent — it checks pg_constraint before adding, so re-running
-- schema.sql (the default bootstrap path) never errors with "already exists".
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
