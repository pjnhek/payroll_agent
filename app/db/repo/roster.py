"""DB repo — roster read (explicit-column Employee/Roster rebuild, no SELECT *)."""
from __future__ import annotations

import uuid

import psycopg.rows

from app.db.repo._shared import _conn_ctx
from app.models.roster import Employee, Roster

# Explicit column list for rebuilding Employee (no SELECT * — extra="forbid").
EMPLOYEE_COLS = (
    "id, business_id, full_name, known_aliases, pay_type, hourly_rate,"
    " annual_salary, retirement_contribution_pct, filing_status,"
    " step_2_checkbox, step_3_dependents, step_4a_other_income,"
    " step_4b_deductions, ytd_ss_wages, pay_periods_per_year"
)


def load_roster_for_business(business_id: uuid.UUID, conn=None) -> Roster:
    """Rebuild a typed Roster (explicit EMPLOYEE_COLS + dict_row, no SELECT *)."""
    # EMPLOYEE_COLS is a trusted module constant; build the statement as a local
    # (no inline f-string in execute) to keep the parameterized-SQL discipline.
    sql = "SELECT " + EMPLOYEE_COLS + " FROM employees WHERE business_id = %s"
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, (str(business_id),))
        rows = cur.fetchall()
    return Roster(
        business_id=business_id,
        employees=[Employee(**row) for row in rows],
    )
