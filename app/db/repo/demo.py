"""DB repo — demo/dashboard aggregate: demo_sender_bindings + record_only +
dashboard list queries."""
from __future__ import annotations

import logging
import uuid

import psycopg.rows

from app.db.repo._shared import _conn_ctx, _nulltx
from app.models.contracts import PaystubLineItem

logger = logging.getLogger("payroll_agent.repo")


def list_businesses(conn=None) -> list[dict]:
    """Return all businesses ordered by name for the landing page picker.

    Explicit column list (no SELECT *) per repo discipline. Returns [] on empty.
    """
    sql = "SELECT id, name, contact_email FROM businesses ORDER BY name"
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql)
        return cur.fetchall() or []


def bind_demo_business(
    business_name: str,
    operator_email: str,
    seed_business_ids: dict,
    conn=None,
) -> bool:
    """UPSERT operator email → business into demo_sender_bindings (HIGH-2 fix).

    NEVER touches businesses.contact_email. The seed .example contacts are permanently
    stable. Only demo_sender_bindings is written. The operator_email is the hardcoded
    DEMO_OPERATOR_EMAIL constant from the call site — never user-supplied.

    Args:
        business_name: validated against the seed_business_ids allowlist.
        operator_email: the hardcoded operator email (DEMO_OPERATOR_EMAIL).
        seed_business_ids: dict[str, UUID] of the three stable seed businesses.

    Returns:
        True on success, False if business_name is not in the allowlist.
    """
    business_id = seed_business_ids.get(business_name)
    if business_id is None:
        return False  # unknown business name — allowlist enforced at route layer too
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            """
                INSERT INTO demo_sender_bindings (operator_email, business_id, bound_at)
                VALUES (%s, %s, now())
                ON CONFLICT (operator_email) DO UPDATE
                    SET business_id = EXCLUDED.business_id,
                        bound_at    = now()
                """,
            (operator_email, str(business_id)),
        )
    return True


def get_demo_binding(operator_email: str, conn=None) -> uuid.UUID | None:
    """Return the business_id bound to operator_email in demo_sender_bindings, or None.

    Used by find_business_by_sender's additive check AND by GET / to display the
    currently-armed business (read-only — never mutates any state).
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            "SELECT business_id FROM demo_sender_bindings WHERE operator_email = %s",
            (operator_email,),
        ).fetchone()
    return uuid.UUID(str(row[0])) if row else None


def set_record_only(run_id: uuid.UUID, conn=None) -> None:
    """Set record_only = TRUE on a run.

    Ad-hoc repair helper. In normal operation, create_run(record_only=True) is used
    directly (LOW-6 — no separate UPDATE needed at compose time).
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            "UPDATE payroll_runs SET record_only = TRUE WHERE id = %s",
            (str(run_id),),
        )


def get_record_only_flag(run_id: uuid.UUID, conn=None) -> bool:
    """Return the record_only flag for a run.

    Returns False if the run is not found (safe default: live Resend path).
    Called by the orchestrator at each send_outbound call site (_clarify and _deliver).
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            "SELECT record_only FROM payroll_runs WHERE id = %s",
            (str(run_id),),
        ).fetchone()
    if row is None:
        return False
    return bool(row[0])


def load_line_items(run_id: uuid.UUID, conn=None) -> list[PaystubLineItem]:
    """Return the paystub line items for a run (explicit column list — no SELECT *).

    LOW finding fix: explicit SELECT list matches PaystubLineItem fields.
    NOTE: additional_medicare_not_modeled is a PaystubLineItem model field (default=False)
    but is NOT a DB column in paystub_line_items — omitted from the SELECT list and the
    model uses its Python default (False). Never invent a column that does not exist.
    """
    sql = (
        "SELECT id, run_id, employee_id, submitted_name,"
        " hours_regular, hours_overtime, hours_vacation, hours_sick, hours_holiday,"
        " gross_pay, pretax_401k, fica_ss, fica_medicare, federal_withholding,"
        " state_withholding, net_pay, created_at"
        " FROM paystub_line_items WHERE run_id = %s ORDER BY employee_id"
    )
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, (str(run_id),))
        rows = cur.fetchall()
    return [PaystubLineItem(**row) for row in rows]


def load_all_runs(conn=None) -> list[dict]:
    """Return all payroll runs in reverse-chronological order, with business_name.

    Used by the runs-list route (DASH-01). Joins businesses to surface business_name
    without requiring a second query in the route layer.

    D-8-07 (OPS2-02): selects an explicit scalar column list — no `pr.*` / `SELECT *`
    — so a new payroll_runs column can never silently reach the dashboard list view
    without an explicit, reviewed SQL edit (T-8-07). Two SQL-computed aliases avoid
    shipping a raw JSONB blob to the list view: `summary_gate_reason` (unchanged,
    already NULL-safe via `->`/`->>` on a NULL `decision` column) and `employee_count`,
    guarded by `jsonb_typeof` (review fix #2 / T-8-12) rather than a bare
    `COALESCE(jsonb_array_length(...), 0)` — the bare form is only NULL-safe for SQL
    NULL and still raises a Postgres error on a non-array JSON scalar/null literal in
    `extracted_data->'employees'`; the `CASE WHEN jsonb_typeof(...) = 'array'` guard
    degrades a corrupt/legacy row to `employee_count = 0` instead of erroring the
    entire runs list.
    """
    sql = (
        "SELECT pr.id, pr.business_id, pr.status, pr.created_at, pr.updated_at,"
        " b.name AS business_name,"
        " pr.decision->'gate_reasons'->>0 AS summary_gate_reason,"
        " CASE WHEN jsonb_typeof(pr.extracted_data->'employees') = 'array'"
        "      THEN jsonb_array_length(pr.extracted_data->'employees')"
        "      ELSE 0 END AS employee_count"
        " FROM payroll_runs pr"
        " JOIN businesses b ON pr.business_id = b.id"
        " ORDER BY pr.created_at DESC"
    )
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql)
        return cur.fetchall() or []
