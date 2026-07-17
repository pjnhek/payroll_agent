"""On-demand per-employee paystub PDF generator.

A PURE function: PaystubLineItem + employee metadata in, PDF bytes out. No DB, no model,
no connection. The orchestrator/route layer owns the StreamingResponse wrapping and any
gateway attachment assembly.

reportlab SimpleDocTemplate → Table / Paragraph / Spacer → BytesIO.getvalue() → bytes.
Every paystub is generated IN MEMORY on demand and nothing is written to disk: the
deployment filesystem is ephemeral, so a file written here would silently vanish on the
next restart.

Layout: a QuickBooks-style pay stub — navy header band, employee block, earnings table,
deductions table, net-pay summary band, footer. Current/YTD amounts are supplied by the
caller before snapshot reservation. NO check / MICR line.
NO fabricated fields: a paystub only ever shows numbers the calc actually produced.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.contracts import PaystubLineItem

# ---------------------------------------------------------------------------
# Palette — the same color roles the dashboard uses, so a paystub and the run page it
# was generated from read as one product.
# ---------------------------------------------------------------------------

_C_NAVY = colors.HexColor("#1E3A5F")        # header/net-pay band background
_C_NAVY_LIGHT = colors.HexColor("#F0F4F8")  # very light tint for alternate rows
_C_WHITE = colors.white
_C_TEXT_PRI = colors.HexColor("#111827")    # text primary
_C_TEXT_SEC = colors.HexColor("#6B7280")    # text secondary
_C_BORDER = colors.HexColor("#E5E7EB")      # border/separator
_C_BAND_TEXT = colors.HexColor("#F9FAFB")   # text on dark navy bands

# ---------------------------------------------------------------------------
# Paragraph styles — Helvetica only (built-in, no font files)
# ---------------------------------------------------------------------------

_BASE = getSampleStyleSheet()

_STYLE_BAND_TITLE = ParagraphStyle(
    "BandTitle",
    fontName="Helvetica-Bold",
    fontSize=16,
    textColor=_C_BAND_TEXT,
    leading=20,
    spaceAfter=0,
)
_STYLE_BAND_LABEL = ParagraphStyle(
    "BandLabel",
    fontName="Helvetica",
    fontSize=10,
    textColor=_C_BAND_TEXT,
    leading=13,
    alignment=2,  # RIGHT
)
_STYLE_BAND_PERIOD = ParagraphStyle(
    "BandPeriod",
    fontName="Helvetica",
    fontSize=9,
    textColor=colors.HexColor("#B0C4DE"),  # muted on dark bg
    leading=12,
    spaceAfter=0,
)
_STYLE_SECTION_HEADER = ParagraphStyle(
    "SectionHeader",
    fontName="Helvetica-Bold",
    fontSize=9,
    textColor=_C_TEXT_SEC,
    leading=11,
    spaceBefore=10,
    spaceAfter=4,
)
_STYLE_FOOTER = ParagraphStyle(
    "Footer",
    fontName="Helvetica",
    fontSize=8,
    textColor=_C_TEXT_SEC,
    leading=10,
    spaceAfter=0,
)
_STYLE_FOOTNOTE = ParagraphStyle(
    "Footnote",
    fontName="Helvetica",
    fontSize=8,
    textColor=_C_TEXT_PRI,
    leading=10,
    spaceAfter=0,
)

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

# Full printable width: LETTER(612) - left(54) - right(54) = 504
_FULL_WIDTH = 504.0
_MARGIN = 54.0  # 0.75 inch margins (slightly tighter than default for a compact stub)

_ZERO = Decimal("0")


@dataclass(frozen=True)
class PaystubYtdTotals:
    """Complete year-to-date display totals for one employee's current paystub."""

    gross_pay: Decimal = _ZERO
    federal_withholding: Decimal = _ZERO
    fica_ss: Decimal = _ZERO
    fica_medicare: Decimal = _ZERO
    state_withholding: Decimal = _ZERO
    pretax_401k: Decimal = _ZERO
    net_pay: Decimal = _ZERO

    @classmethod
    def from_prior(
        cls, prior: Mapping[str, Decimal] | None, item: PaystubLineItem
    ) -> PaystubYtdTotals:
        """Combine reconciled prior values with this pay period for display only."""
        values = prior or {}
        return cls(
            gross_pay=values.get("gross_pay", _ZERO) + item.gross_pay,
            federal_withholding=(
                values.get("federal_withholding", _ZERO) + item.federal_withholding
            ),
            fica_ss=values.get("fica_ss", _ZERO) + item.fica_ss,
            fica_medicare=values.get("fica_medicare", _ZERO) + item.fica_medicare,
            state_withholding=(
                values.get("state_withholding", _ZERO)
                + (item.state_withholding or _ZERO)
            ),
            pretax_401k=values.get("pretax_401k", _ZERO) + (item.pretax_401k or _ZERO),
            net_pay=values.get("net_pay", _ZERO) + item.net_pay,
        )


def _fmt(val: Decimal) -> str:
    """Format a Decimal or numeric value as $X,XXX.XX."""
    return f"${val:,.2f}"


def _period_label(pay_period_start: date | None, pay_period_end: date | None) -> str:
    """Build a human-readable pay period label (preserves original logic)."""
    if pay_period_start and pay_period_end:
        return f"{pay_period_start} to {pay_period_end}"
    elif pay_period_start:
        return str(pay_period_start)
    return "—"  # em dash


def _sum_deductions(item: PaystubLineItem) -> Decimal:
    """Compute total deductions from the deduction rows that will be shown.

    Includes: federal_withholding, fica_ss, fica_medicare, state_withholding
    (if non-None/non-zero, per DASH-02), pretax_401k (if non-zero).
    Must reconcile with the deductions table rows displayed.
    """
    total = item.federal_withholding + item.fica_ss + item.fica_medicare
    if item.state_withholding:
        total += item.state_withholding
    if item.pretax_401k:
        total += item.pretax_401k
    return total


def _sum_ytd_deductions(ytd: PaystubYtdTotals) -> Decimal:
    """Return the same deduction categories shown in the YTD column."""
    return (
        ytd.federal_withholding
        + ytd.fica_ss
        + ytd.fica_medicare
        + ytd.state_withholding
        + ytd.pretax_401k
    )


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _build_header_band(
    business_name: str | None,
    period_lbl: str,
    full_width: float,
) -> Table:
    """Navy band: company name (left) + PAY STATEMENT label (right).

    The band is implemented as a 2-column Table so the left and right
    cells sit on the same baseline without manual x/y positioning.
    """
    left_paras: list[Paragraph] = []
    if business_name:
        left_paras.append(Paragraph(business_name, _STYLE_BAND_TITLE))
    left_paras.append(Paragraph(f"Pay Period: {period_lbl}", _STYLE_BAND_PERIOD))

    right_para = Paragraph("PAY STATEMENT", _STYLE_BAND_LABEL)

    data = [[left_paras, right_para]]
    col_widths = [full_width * 0.65, full_width * 0.35]

    table = Table(data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _C_NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING", (0, 0), (0, -1), 14),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 14),
        ("LEFTPADDING", (-1, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), 0),
    ]))
    return table


def _build_employee_block(
    employee_full_name: str,
    filing_status: str | None,
    full_width: float,
) -> Table:
    """Compact employee info block: name + optional filing status."""
    rows = [["Employee", employee_full_name]]
    if filing_status:
        rows.append(["Filing Status", filing_status])

    col_widths = [full_width * 0.35, full_width * 0.65]
    table = Table(rows, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, -1), _C_TEXT_PRI),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, _C_BORDER),
    ]))
    return table


def _build_earnings_table(
    item: PaystubLineItem,
    ytd: PaystubYtdTotals,
    full_width: float,
    hourly_rate: Decimal | None = None,
) -> Table:
    """Earnings table with aligned current and calendar-year total amounts.

    Rows for non-zero hour buckets. Per-bucket dollar splits are not available
    on PaystubLineItem (gross_pay is the total only), so the Amount column is
    blank for individual hour rows and filled only on the TOTAL GROSS footer row.

    When ``hourly_rate`` is provided (hourly employees only):
      - A "Rate" column is inserted between "Earnings" and "Hours".
      - Regular row shows the base rate (e.g. "$20.00/hr").
      - Overtime row shows 1.5× rate (e.g. "$30.00/hr") — computed as
        ``hourly_rate * Decimal("1.5")``, which is accurate for standard OT.
      - All other buckets (Vacation, Sick, Holiday) show the base rate.
    When ``hourly_rate`` is None (salaried or unknown) the Rate column is
    omitted entirely — nothing is fabricated.

    Salaried path: if ALL hour buckets are zero, show a single "Salary" row
    with gross_pay as the amount (no empty table). Rate column also omitted
    for salaried employees.
    """
    HOUR_BUCKETS = [
        ("hours_regular", "Regular"),
        ("hours_overtime", "Overtime"),
        ("hours_vacation", "Vacation"),
        ("hours_sick", "Sick"),
        ("hours_holiday", "Holiday"),
    ]

    show_rate = hourly_rate is not None
    ot_rate = (
        (hourly_rate * Decimal("1.5")).quantize(Decimal("0.01"))
        if hourly_rate is not None
        else None
    )

    if show_rate:
        header = [["Earnings", "Rate", "Hours", "Current", "YTD"]]
    else:
        header = [["Earnings", "Hours", "Current", "YTD"]]

    all_zero = all(getattr(item, field) == 0 for field, _ in HOUR_BUCKETS)

    if all_zero:
        # Salaried: single salary row with gross amount; no rate shown
        if show_rate:
            body_rows = [
                ["Salary", "", "", _fmt(item.gross_pay), _fmt(ytd.gross_pay)]
            ]
            total_row = [
                ["TOTAL GROSS", "", "", _fmt(item.gross_pay), _fmt(ytd.gross_pay)]
            ]
        else:
            body_rows = [["Salary", "", _fmt(item.gross_pay), _fmt(ytd.gross_pay)]]
            total_row = [["TOTAL GROSS", "", _fmt(item.gross_pay), _fmt(ytd.gross_pay)]]
    else:
        body_rows = []
        for field, label in HOUR_BUCKETS:
            val = getattr(item, field)
            if val != 0:
                if show_rate:
                    rate_cell = f"${ot_rate}/hr" if label == "Overtime" else f"${hourly_rate}/hr"
                    body_rows.append([label, rate_cell, str(val), "", ""])
                else:
                    body_rows.append([label, str(val), "", ""])
        # Total gross row (dollar amount only — individual splits not available)
        if show_rate:
            total_row = [
                ["TOTAL GROSS", "", "", _fmt(item.gross_pay), _fmt(ytd.gross_pay)]
            ]
        else:
            total_row = [["TOTAL GROSS", "", _fmt(item.gross_pay), _fmt(ytd.gross_pay)]]

    all_rows = header + body_rows + total_row
    num_rows = len(all_rows)
    header_row_idx = 0
    total_row_idx = num_rows - 1

    # Column widths: vary by whether Rate column is present
    if show_rate:
        # [Earnings | Rate | Hours | Current | YTD]
        col_widths = [
            full_width * 0.31,
            full_width * 0.17,
            full_width * 0.12,
            full_width * 0.20,
            full_width * 0.20,
        ]
        # Right-align Rate, Hours, Current, and YTD columns.
        align_start = 1
    else:
        # [Earnings | Hours | Current | YTD]
        col_widths = [
            full_width * 0.38,
            full_width * 0.16,
            full_width * 0.23,
            full_width * 0.23,
        ]
        # Right-align Hours, Current, and YTD columns.
        align_start = 1

    table = Table(all_rows, colWidths=col_widths)
    table.setStyle(TableStyle([
        # Header row
        ("BACKGROUND", (0, header_row_idx), (-1, header_row_idx), _C_NAVY),
        ("TEXTCOLOR", (0, header_row_idx), (-1, header_row_idx), _C_BAND_TEXT),
        ("FONTNAME", (0, header_row_idx), (-1, header_row_idx), "Helvetica-Bold"),
        ("FONTSIZE", (0, header_row_idx), (-1, header_row_idx), 9),
        # Body rows
        ("FONTNAME", (0, 1), (-1, total_row_idx - 1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, total_row_idx - 1), 10),
        ("TEXTCOLOR", (0, 1), (-1, total_row_idx - 1), _C_TEXT_PRI),
        # Total gross row — bold
        ("FONTNAME", (0, total_row_idx), (-1, total_row_idx), "Helvetica-Bold"),
        ("FONTSIZE", (0, total_row_idx), (-1, total_row_idx), 10),
        ("TEXTCOLOR", (0, total_row_idx), (-1, total_row_idx), _C_TEXT_PRI),
        ("LINEABOVE", (0, total_row_idx), (-1, total_row_idx), 0.5, _C_BORDER),
        # Borders & padding
        ("GRID", (0, 0), (-1, -1), 0.5, _C_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        # Right-align numeric columns (Rate onward)
        ("ALIGN", (align_start, 0), (-1, -1), "RIGHT"),
    ]))
    return table


def _build_deductions_table(
    item: PaystubLineItem, ytd: PaystubYtdTotals, full_width: float
) -> Table:
    """Deductions table with aligned current and calendar-year total amounts.

    Rows: Federal Income Tax, Social Security 6.2%, Medicare 1.45%,
    State Income Tax (omit if None/zero, DASH-02), Pre-tax 401(k) (omit if zero).
    TOTAL DEDUCTIONS is computed and must reconcile.
    """
    header = [["Deductions", "Current", "YTD"]]

    body_rows = [
        [
            "Federal Income Tax",
            _fmt(item.federal_withholding),
            _fmt(ytd.federal_withholding),
        ],
        ["Social Security (6.2%)", _fmt(item.fica_ss), _fmt(ytd.fica_ss)],
        ["Medicare (1.45%)", _fmt(item.fica_medicare), _fmt(ytd.fica_medicare)],
    ]

    # State Withholding — omit only when it is absent from both display periods.
    if item.state_withholding or ytd.state_withholding:
        body_rows.append(
            [
                "State Income Tax",
                _fmt(item.state_withholding or _ZERO),
                _fmt(ytd.state_withholding),
            ]
        )

    # Pre-tax 401(k) — omit only when it is absent from both display periods.
    if item.pretax_401k or ytd.pretax_401k:
        body_rows.append(
            ["Pre-tax 401(k)", _fmt(item.pretax_401k or _ZERO), _fmt(ytd.pretax_401k)]
        )

    total_deductions = _sum_deductions(item)
    total_row = [
        [
            "TOTAL DEDUCTIONS",
            _fmt(total_deductions),
            _fmt(_sum_ytd_deductions(ytd)),
        ]
    ]

    all_rows = header + body_rows + total_row
    num_rows = len(all_rows)
    header_row_idx = 0
    total_row_idx = num_rows - 1

    col_widths = [full_width * 0.45, full_width * 0.275, full_width * 0.275]

    table = Table(all_rows, colWidths=col_widths)
    table.setStyle(TableStyle([
        # Header row
        ("BACKGROUND", (0, header_row_idx), (-1, header_row_idx), _C_NAVY),
        ("TEXTCOLOR", (0, header_row_idx), (-1, header_row_idx), _C_BAND_TEXT),
        ("FONTNAME", (0, header_row_idx), (-1, header_row_idx), "Helvetica-Bold"),
        ("FONTSIZE", (0, header_row_idx), (-1, header_row_idx), 9),
        # Body rows
        ("FONTNAME", (0, 1), (-1, total_row_idx - 1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, total_row_idx - 1), 10),
        ("TEXTCOLOR", (0, 1), (-1, total_row_idx - 1), _C_TEXT_PRI),
        # Total deductions row — bold
        ("FONTNAME", (0, total_row_idx), (-1, total_row_idx), "Helvetica-Bold"),
        ("FONTSIZE", (0, total_row_idx), (-1, total_row_idx), 10),
        ("TEXTCOLOR", (0, total_row_idx), (-1, total_row_idx), _C_TEXT_PRI),
        ("LINEABOVE", (0, total_row_idx), (-1, total_row_idx), 0.5, _C_BORDER),
        # Borders & padding
        ("GRID", (0, 0), (-1, -1), 0.5, _C_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        # Right-align Current and YTD columns
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))
    return table


def _build_net_pay_band(
    item: PaystubLineItem, ytd: PaystubYtdTotals, full_width: float
) -> Table:
    """Muted-navy summary band: current and YTD gross, deductions, and net pay."""
    total_deductions = _sum_deductions(item)

    _style_label = ParagraphStyle(
        "NetBandLabel",
        fontName="Helvetica",
        fontSize=8,
        textColor=colors.HexColor("#B0C4DE"),
        leading=10,
        alignment=1,  # CENTER
    )
    _style_value = ParagraphStyle(
        "NetBandValue",
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=_C_BAND_TEXT,
        leading=14,
        alignment=1,  # CENTER
    )
    _style_net_label = ParagraphStyle(
        "NetBandNetLabel",
        fontName="Helvetica-Bold",
        fontSize=9,
        textColor=colors.HexColor("#B0C4DE"),
        leading=11,
        alignment=1,  # CENTER
    )
    _style_net_value = ParagraphStyle(
        "NetBandNetValue",
        fontName="Helvetica-Bold",
        fontSize=15,
        textColor=_C_BAND_TEXT,
        leading=18,
        alignment=1,  # CENTER
    )

    data = [
        [
            Paragraph("", _style_label),
            Paragraph("GROSS PAY", _style_label),
            Paragraph("TOTAL DEDUCTIONS", _style_label),
            Paragraph("NET PAY", _style_net_label),
        ],
        [
            Paragraph("CURRENT", _style_label),
            Paragraph(_fmt(item.gross_pay), _style_value),
            Paragraph(_fmt(total_deductions), _style_value),
            Paragraph(_fmt(item.net_pay), _style_net_value),
        ],
        [
            Paragraph("YTD", _style_label),
            Paragraph(_fmt(ytd.gross_pay), _style_value),
            Paragraph(_fmt(_sum_ytd_deductions(ytd)), _style_value),
            Paragraph(_fmt(ytd.net_pay), _style_net_value),
        ],
    ]
    col_widths = [
        full_width * 0.14,
        full_width * 0.29,
        full_width * 0.29,
        full_width * 0.28,
    ]
    table = Table(data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _C_NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        # Vertical dividers between columns
        ("LINEAFTER", (0, 0), (2, -1), 0.5, colors.HexColor("#2D5F8F")),
    ]))
    return table


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_paystub_pdf(
    item: PaystubLineItem,
    employee_full_name: str,
    pay_period_start: date | None,
    pay_period_end: date | None,
    *,
    business_name: str | None = None,
    filing_status: str | None = None,
    hourly_rate: Decimal | None = None,
    ytd: PaystubYtdTotals | None = None,
) -> bytes:
    """Pure: data in -> PDF bytes out. No DB, no filesystem write (the FS is ephemeral).

    Returns raw PDF bytes. The caller wraps in StreamingResponse or passes
    as attachment bytes to gateway.send_outbound.

    Layout (top to bottom):
      1. Navy company header band — business_name (optional) + PAY STATEMENT label
         + pay-period sub-line.
      2. Employee info block — name + filing_status (optional; omitted if not passed).
      3. Earnings table — non-zero hour buckets or single Salary row if all-zero,
         with aligned Current and YTD amounts for the supported total.
         When hourly_rate is provided, a Rate column is shown (base rate for Regular
         and most buckets; 1.5× for Overtime). Salaried employees (hourly_rate=None)
         never show a Rate column — a salaried employee has no hourly rate, and inventing
         one (e.g. annual/2080) would print a number on a paystub that no calculation
         actually used. Nothing on this document is fabricated.
         Per-bucket dollar splits are NOT shown (not available on PaystubLineItem);
         hours are shown per row; dollar total on TOTAL GROSS row = gross_pay.
      4. Deductions table — Federal, SS, Medicare, State, and Pre-tax 401(k), each
         with Current and YTD values. TOTAL DEDUCTIONS is computed and reconciled.
      5. Net-pay summary band — Current and YTD GROSS / TOTAL DEDUCTIONS / NET PAY.
      6. Footer footnotes.

    No check / MICR / bank / fabricated fields of any kind.

    Signature adds optional keyword params `business_name`, `filing_status`, and
    `hourly_rate` plus the supplied `ytd` display total (all default None) — existing
    callers remain valid and receive an honest current-period-as-YTD display.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN,
    )

    period_lbl = _period_label(pay_period_start, pay_period_end)
    display_ytd = ytd or PaystubYtdTotals.from_prior(None, item)

    story = []

    # 1. Company header band
    story.append(_build_header_band(business_name, period_lbl, _FULL_WIDTH))
    story.append(Spacer(1, 10))

    # 2. Employee info block
    story.append(Paragraph("EMPLOYEE INFORMATION", _STYLE_SECTION_HEADER))
    story.append(_build_employee_block(employee_full_name, filing_status, _FULL_WIDTH))
    story.append(Spacer(1, 12))

    # 3. Earnings table
    story.append(Paragraph("EARNINGS", _STYLE_SECTION_HEADER))
    story.append(
        _build_earnings_table(item, display_ytd, _FULL_WIDTH, hourly_rate=hourly_rate)
    )
    story.append(Spacer(1, 10))

    # 4. Deductions table
    story.append(Paragraph("DEDUCTIONS", _STYLE_SECTION_HEADER))
    story.append(_build_deductions_table(item, display_ytd, _FULL_WIDTH))
    story.append(Spacer(1, 14))

    # 5. Net-pay summary band
    story.append(_build_net_pay_band(item, display_ytd, _FULL_WIDTH))
    story.append(Spacer(1, 10))

    # 6. Footnotes / footer
    if item.additional_medicare_not_modeled:
        story.append(
            Paragraph(
                "* Additional Medicare (0.9% over $200k) not modeled.",
                _STYLE_FOOTNOTE,
            )
        )
        story.append(Spacer(1, 4))

    story.append(
        Paragraph(
            "Demo pay statement — not a negotiable instrument.",
            _STYLE_FOOTER,
        )
    )

    doc.build(story)
    return buf.getvalue()
