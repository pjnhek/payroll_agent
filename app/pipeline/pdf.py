"""On-demand per-employee paystub PDF generator (HITL-03, D-11).

A PURE function: PaystubLineItem + employee metadata in, PDF bytes out.
No DB, no model, no connection. The orchestrator/route layer owns the
StreamingResponse wrapping and any gateway attachment assembly.

reportlab SimpleDocTemplate → Table / Paragraph / Spacer → BytesIO.getvalue() → bytes.
Nothing is written to disk (HITL-03: Render ephemeral FS constraint).

Layout: professional QuickBooks-style pay stub — navy header band, employee
block, earnings table, deductions table, net-pay summary band, demo footer.
NO YTD columns (deferred to v2). NO check / MICR line. NO fabricated fields.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.contracts import PaystubLineItem

# ---------------------------------------------------------------------------
# Palette — aligned with dashboard UI-SPEC (#111827 / #6B7280 / #E5E7EB)
# ---------------------------------------------------------------------------

_C_NAVY = colors.HexColor("#1E3A5F")        # header/net-pay band background
_C_NAVY_LIGHT = colors.HexColor("#F0F4F8")  # very light tint for alternate rows
_C_WHITE = colors.white
_C_TEXT_PRI = colors.HexColor("#111827")    # UI-SPEC text primary
_C_TEXT_SEC = colors.HexColor("#6B7280")    # UI-SPEC text secondary
_C_BORDER = colors.HexColor("#E5E7EB")      # UI-SPEC border/separator
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


def _fmt(val) -> str:
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
    left_paras: list = []
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


def _build_earnings_table(item: PaystubLineItem, full_width: float) -> Table:
    """Earnings table: [Earnings | Hours | Amount].

    Rows for non-zero hour buckets. Per-bucket dollar splits are not available
    on PaystubLineItem (gross_pay is the total only), so the Amount column is
    blank for individual hour rows and filled only on the TOTAL GROSS footer row.

    Salaried path: if ALL hour buckets are zero, show a single "Salary" row
    with gross_pay as the amount (no empty table).
    """
    HOUR_BUCKETS = [
        ("hours_regular", "Regular"),
        ("hours_overtime", "Overtime"),
        ("hours_vacation", "Vacation"),
        ("hours_sick", "Sick"),
        ("hours_holiday", "Holiday"),
    ]

    header = [["Earnings", "Hours", "Amount"]]

    all_zero = all(getattr(item, field) == 0 for field, _ in HOUR_BUCKETS)

    if all_zero:
        # Salaried: single salary row with gross amount
        body_rows = [["Salary", "", _fmt(item.gross_pay)]]
        total_row = [["TOTAL GROSS", "", _fmt(item.gross_pay)]]
    else:
        body_rows = []
        for field, label in HOUR_BUCKETS:
            val = getattr(item, field)
            if val != 0:
                body_rows.append([label, str(val), ""])
        # Total gross row (dollar amount only — individual splits not available)
        total_row = [["TOTAL GROSS", "", _fmt(item.gross_pay)]]

    all_rows = header + body_rows + total_row
    num_rows = len(all_rows)
    header_row_idx = 0
    total_row_idx = num_rows - 1

    # Column widths: label wide, hours narrow, amount medium
    col_widths = [full_width * 0.50, full_width * 0.20, full_width * 0.30]

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
        # Right-align Hours and Amount columns
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))
    return table


def _build_deductions_table(item: PaystubLineItem, full_width: float) -> Table:
    """Deductions table: [Deductions | Amount].

    Rows: Federal Income Tax, Social Security 6.2%, Medicare 1.45%,
    State Income Tax (omit if None/zero, DASH-02), Pre-tax 401(k) (omit if zero).
    TOTAL DEDUCTIONS is computed and must reconcile.
    """
    header = [["Deductions", "Amount"]]

    body_rows = [
        ["Federal Income Tax", _fmt(item.federal_withholding)],
        ["Social Security (6.2%)", _fmt(item.fica_ss)],
        ["Medicare (1.45%)", _fmt(item.fica_medicare)],
    ]

    # State Withholding — omit when None or zero (DASH-02)
    if item.state_withholding:
        body_rows.append(["State Income Tax", _fmt(item.state_withholding)])

    # Pre-tax 401(k) — omit when zero/None
    if item.pretax_401k:
        body_rows.append(["Pre-tax 401(k)", _fmt(item.pretax_401k)])

    total_deductions = _sum_deductions(item)
    total_row = [["TOTAL DEDUCTIONS", _fmt(total_deductions)]]

    all_rows = header + body_rows + total_row
    num_rows = len(all_rows)
    header_row_idx = 0
    total_row_idx = num_rows - 1

    col_widths = [full_width * 0.60, full_width * 0.40]

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
        # Right-align Amount column
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))
    return table


def _build_net_pay_band(item: PaystubLineItem, full_width: float) -> Table:
    """Muted-navy summary band: GROSS / TOTAL DEDUCTIONS / NET PAY.

    Three equal-width columns; NET PAY is emphasized with larger bold text.
    """
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

    gross_cell = [
        Paragraph("GROSS PAY", _style_label),
        Paragraph(_fmt(item.gross_pay), _style_value),
    ]
    deductions_cell = [
        Paragraph("TOTAL DEDUCTIONS", _style_label),
        Paragraph(_fmt(total_deductions), _style_value),
    ]
    net_cell = [
        Paragraph("NET PAY", _style_net_label),
        Paragraph(_fmt(item.net_pay), _style_net_value),
    ]

    col_w = full_width / 3
    data = [[gross_cell, deductions_cell, net_cell]]
    table = Table(data, colWidths=[col_w, col_w, col_w])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _C_NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        # Vertical dividers between columns
        ("LINEAFTER", (0, 0), (1, -1), 0.5, colors.HexColor("#2D5F8F")),
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
) -> bytes:
    """Pure: data in -> PDF bytes out. No DB, no filesystem write (HITL-03).

    Returns raw PDF bytes. The caller wraps in StreamingResponse or passes
    as attachment bytes to gateway.send_outbound.

    Layout (top to bottom):
      1. Navy company header band — business_name (optional) + PAY STATEMENT label
         + pay-period sub-line.
      2. Employee info block — name + filing_status (optional; omitted if not passed).
      3. Earnings table — non-zero hour buckets or single Salary row if all-zero.
         Per-bucket dollar splits are NOT shown (not available on PaystubLineItem);
         hours are shown per row; dollar total on TOTAL GROSS row = gross_pay.
      4. Deductions table — Federal, SS, Medicare, State (DASH-02: omit if None/zero),
         Pre-tax 401(k) (omit if zero). TOTAL DEDUCTIONS is computed and reconciled.
      5. Net-pay summary band — GROSS / TOTAL DEDUCTIONS / NET PAY (emphasized).
      6. Footer footnotes.

    YTD figures are deliberately excluded (deferred to v2).
    No check / MICR / bank / fabricated fields of any kind.

    Signature adds optional keyword params `business_name` and `filing_status`
    (both default None) — existing callers are unchanged.
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
    story.append(_build_earnings_table(item, _FULL_WIDTH))
    story.append(Spacer(1, 10))

    # 4. Deductions table
    story.append(Paragraph("DEDUCTIONS", _STYLE_SECTION_HEADER))
    story.append(_build_deductions_table(item, _FULL_WIDTH))
    story.append(Spacer(1, 14))

    # 5. Net-pay summary band
    story.append(_build_net_pay_band(item, _FULL_WIDTH))
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
