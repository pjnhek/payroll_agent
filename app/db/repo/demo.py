"""DB repo — demo/dashboard aggregate: demo_sender_bindings + record_only +
dashboard list queries."""
from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import psycopg
import psycopg.rows

from app.db.repo._shared import _conn_ctx, _nulltx
from app.models.contracts import PaystubLineItem

logger = logging.getLogger("payroll_agent.repo")


def list_businesses(
    conn: psycopg.Connection | None = None,
) -> list[dict[str, Any]]:
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
    seed_business_ids: dict[str, uuid.UUID],
    conn: psycopg.Connection | None = None,
) -> bool:
    """UPSERT operator email → business into demo_sender_bindings.

    NEVER touches businesses.contact_email — the seeded .example contacts stay
    permanently stable, and only demo_sender_bindings is written. The operator_email
    is the hardcoded DEMO_OPERATOR_EMAIL constant from the call site, never
    user-supplied: this table feeds sender→business routing, so a user-supplied
    value here would let an arbitrary sender bind themselves to a business.

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


def get_demo_binding(
    operator_email: str, conn: psycopg.Connection | None = None
) -> uuid.UUID | None:
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


def set_record_only(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> None:
    """Set record_only = TRUE on a run.

    Ad-hoc repair helper. In normal operation, create_run(record_only=True) is used
    directly, so no separate UPDATE is needed at compose time.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            "UPDATE payroll_runs SET record_only = TRUE WHERE id = %s",
            (str(run_id),),
        )


def get_record_only_flag(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> bool:
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


def load_line_items(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> list[PaystubLineItem]:
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


def load_prior_reconciled_paystub_totals(
    business_id: uuid.UUID,
    employee_ids: list[uuid.UUID],
    pay_period_start: date | None,
    conn: psycopg.Connection | None = None,
) -> dict[uuid.UUID, dict[str, Decimal]]:
    """Return each employee's completed calendar-year totals before this pay period.

    The paystub display ledger is intentionally separate from the employee's Social
    Security wage-base field.  A missing current-period start has no honest calendar
    scope, so it yields no prior values instead of treating one category as complete.
    """
    if pay_period_start is None or not employee_ids:
        return {}

    sql = (
        "SELECT item.employee_id,"
        " COALESCE(SUM(item.gross_pay), 0) AS gross_pay,"
        " COALESCE(SUM(item.federal_withholding), 0) AS federal_withholding,"
        " COALESCE(SUM(item.fica_ss), 0) AS fica_ss,"
        " COALESCE(SUM(item.fica_medicare), 0) AS fica_medicare,"
        " COALESCE(SUM(item.state_withholding), 0) AS state_withholding,"
        " COALESCE(SUM(item.pretax_401k), 0) AS pretax_401k,"
        " COALESCE(SUM(item.net_pay), 0) AS net_pay"
        " FROM paystub_line_items AS item"
        " JOIN payroll_runs AS historical ON historical.id = item.run_id"
        " WHERE historical.business_id = %s"
        " AND historical.status = 'reconciled'"
        " AND item.employee_id = ANY(%s::uuid[])"
        " AND historical.pay_period_start >= date_trunc('year', %s::date)::date"
        " AND historical.pay_period_end < %s"
        " GROUP BY item.employee_id"
    )
    with (
        _conn_ctx(conn) as (c, _owns),
        c.cursor(row_factory=psycopg.rows.dict_row) as cur,
    ):
        cur.execute(
            sql,
            (
                str(business_id),
                [str(employee_id) for employee_id in employee_ids],
                pay_period_start,
                pay_period_start,
            ),
        )
        rows = cur.fetchall()
    categories = (
        "gross_pay",
        "federal_withholding",
        "fica_ss",
        "fica_medicare",
        "state_withholding",
        "pretax_401k",
        "net_pay",
    )
    return {
        uuid.UUID(str(row["employee_id"])): {
            category: Decimal(str(row[category])) for category in categories
        }
        for row in rows
    }


def load_all_runs(conn: psycopg.Connection | None = None) -> list[dict[str, Any]]:
    """Return all payroll runs in reverse-chronological order, with business_name.

    Used by the runs-list route. Joins businesses to surface business_name without a
    second query in the route layer.

    Selects an EXPLICIT scalar column list — no `pr.*` / `SELECT *` — so a new
    payroll_runs column can never silently reach the dashboard list view without a
    reviewed SQL edit. Two SQL-computed aliases keep the raw JSONB blobs off the
    wire: `summary_gate_reason` (NULL-safe by construction via `->`/`->>` on a NULL
    `decision` column) and `employee_count`.

    `employee_count` is guarded by `jsonb_typeof` rather than written as a bare
    `COALESCE(jsonb_array_length(...), 0)`. The bare form is NULL-safe only for a SQL
    NULL; on a non-array JSON scalar or JSON `null` literal in
    `extracted_data->'employees'` Postgres RAISES, which would take down the entire
    runs list over one corrupt row. The `CASE WHEN jsonb_typeof(...) = 'array'` guard
    degrades that row to `employee_count = 0` instead.
    """
    sql = (
        "SELECT pr.id, pr.business_id, pr.status, pr.created_at, pr.updated_at,"
        " pr.error_reason, pr.error_detail,"
        " b.name AS business_name,"
        " pr.decision->'gate_reasons'->>0 AS summary_gate_reason,"
        " CASE WHEN jsonb_typeof(pr.extracted_data->'employees') = 'array'"
        "      THEN jsonb_array_length(pr.extracted_data->'employees')"
        "      ELSE 0 END AS employee_count,"
        " latest_job.attempts AS job_attempts,"
        " latest_job.max_attempts AS job_max_attempts,"
        " open_job.queue_label"
        " FROM payroll_runs pr"
        " JOIN businesses b ON pr.business_id = b.id"
        " LEFT JOIN LATERAL ("
        "   SELECT j.attempts, j.max_attempts"
        "   FROM jobs j WHERE j.run_id = pr.id"
        "   ORDER BY j.created_at DESC, j.id DESC LIMIT 1"
        " ) latest_job ON TRUE"
        " LEFT JOIN LATERAL ("
        "   SELECT CASE"
        "     WHEN bool_or(j.state = 'leased') THEN 'Running'"
        "     WHEN bool_or(j.state = 'pending' AND j.available_at <= now())"
        "       THEN 'Queued'"
        "     WHEN bool_or(j.state = 'pending') THEN 'Retry queued'"
        "   END AS queue_label"
        "   FROM jobs j"
        "   WHERE j.run_id = pr.id AND j.state IN ('pending', 'leased')"
        " ) open_job ON TRUE"
        " ORDER BY pr.created_at DESC"
    )
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql)
        return cur.fetchall() or []
