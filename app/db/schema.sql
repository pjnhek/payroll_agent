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
    step_3_dependents           NUMERIC(12,2) NOT NULL DEFAULT 0,
    step_4a_other_income        NUMERIC(12,2) NOT NULL DEFAULT 0,
    step_4b_deductions          NUMERIC(12,2) NOT NULL DEFAULT 0,
    ytd_ss_wages                NUMERIC(14,2) NOT NULL DEFAULT 0,
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
                                    'needs_clarification',
                                    'awaiting_reply',
                                    'computed',
                                    'awaiting_approval',
                                    'approved',
                                    'sent',
                                    'reconciled',
                                    'rejected',
                                    'error'
                                )),
    extracted_data  JSONB,      -- D-06: persisted from Extracted.model_dump(mode="json")
    decision        JSONB,      -- D-06: persisted from Decision.model_dump(mode="json")
    pay_period_start DATE,
    pay_period_end   DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 4. paystub_line_items ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS paystub_line_items (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID        NOT NULL REFERENCES payroll_runs(id) ON DELETE CASCADE,
    employee_id         UUID        REFERENCES employees(id),
    submitted_name      TEXT        NOT NULL,
    match_confidence    NUMERIC(4,3)  NOT NULL DEFAULT 0,
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
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_message_id UNIQUE (message_id)
);

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
