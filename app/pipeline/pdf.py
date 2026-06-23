"""On-demand per-employee paystub PDF generator (HITL-03, D-11).

A PURE function: PaystubLineItem + employee metadata in, PDF bytes out.
No DB, no model, no connection. The orchestrator/route layer owns the
StreamingResponse wrapping and any gateway attachment assembly.

reportlab SimpleDocTemplate → Table → BytesIO.getvalue() → bytes.
Nothing is written to disk (HITL-03: Render ephemeral FS constraint).
"""
from __future__ import annotations

from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.contracts import PaystubLineItem

_STYLES = getSampleStyleSheet()

# Column widths: left=label (200pt), right=value (200pt)
_COL_WIDTHS = [200, 200]

# Header row background (matches UI-SPEC border/separator #E5E7EB)
_HEADER_BG = colors.HexColor("#E5E7EB")


def _fmt(val) -> str:
    """Format a Decimal or numeric value as $X,XXX.XX."""
    return f"${val:,.2f}"


def generate_paystub_pdf(
    item: PaystubLineItem,
    employee_full_name: str,
    pay_period_start: date | None,
    pay_period_end: date | None,
) -> bytes:
    """Pure: data in → PDF bytes out. No DB, no filesystem write (HITL-03).

    Returns raw PDF bytes. The caller wraps in StreamingResponse or passes
    as attachment bytes to gateway.send_outbound.

    Layout follows UI-SPEC Column 3 (Computed Paystubs) row order:
      Employee, Pay Period, Gross Pay, Pre-tax 401k (if non-zero),
      Social Security (6.2%), Medicare (1.45%), Federal Withholding, Net Pay.
      State Withholding row is OMITTED when state_withholding is None or zero
      (DASH-02). Footnote added when additional_medicare_not_modeled is True.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=72,
        rightMargin=72,
        topMargin=72,
        bottomMargin=72,
    )

    # --- Build table rows per UI-SPEC Column 3 order ---
    if pay_period_start and pay_period_end:
        period_label = f"{pay_period_start} to {pay_period_end}"
    elif pay_period_start:
        period_label = str(pay_period_start)
    else:
        period_label = "—"  # em dash

    data = [
        # Header row
        ["Field", "Amount"],
        # Employee / period metadata
        ["Employee", employee_full_name],
        ["Pay Period", period_label],
    ]

    # Earnings / deductions per UI-SPEC Column 3
    data.append(["Gross Pay", _fmt(item.gross_pay)])

    # Pre-tax 401k — omit if None or zero (avoids clutter on zero-contribution stubs)
    if item.pretax_401k:
        data.append(["Pre-tax 401k", _fmt(item.pretax_401k)])

    data.extend([
        ["Social Security (6.2%)", _fmt(item.fica_ss)],
        ["Medicare (1.45%)", _fmt(item.fica_medicare)],
        ["Federal Withholding", _fmt(item.federal_withholding)],
    ])

    # State Withholding — omit row when None or zero (DASH-02)
    if item.state_withholding:
        data.append(["State Withholding", _fmt(item.state_withholding)])

    data.append(["Net Pay", _fmt(item.net_pay)])

    # --- Build table style ---
    num_rows = len(data)
    style = TableStyle([
        # Header row: light grey background, bold text
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        # Body rows
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        # Net Pay row bold (last data row)
        ("FONTNAME", (0, num_rows - 1), (-1, num_rows - 1), "Helvetica-Bold"),
        # Grid / borders
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        # Cell padding
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        # Right-align the value column
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ])

    table = Table(data, colWidths=_COL_WIDTHS)
    table.setStyle(style)

    story = [table]

    # Additional Medicare footnote when the surtax was not modeled
    if item.additional_medicare_not_modeled:
        story.append(Spacer(1, 8))
        footnote_style = _STYLES["Normal"]
        story.append(
            Paragraph(
                "* Additional Medicare (0.9% over $200k) not modeled.",
                footnote_style,
            )
        )

    doc.build(story)
    return buf.getvalue()
