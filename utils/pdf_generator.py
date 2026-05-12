import calendar
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from xml.sax.saxutils import escape

from flask import current_app
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from models.db import get_db
from models.worker_model import get_worker


COMPANY_NAME = "SHREEJI AUTO SERVICE"
COMPANY_ADDRESS = "Shreeji Auto Service, Garage Management Office"
FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"


def _register_fonts():
    """Prefer a Unicode font so the rupee symbol renders in PDFs."""
    global FONT_REGULAR, FONT_BOLD
    font_candidates = [
        (
            "Arial",
            r"C:\Windows\Fonts\arial.ttf",
            "Arial-Bold",
            r"C:\Windows\Fonts\arialbd.ttf",
        ),
        (
            "DejaVuSans",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "DejaVuSans-Bold",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ),
    ]
    for regular_name, regular_path, bold_name, bold_path in font_candidates:
        if os.path.exists(regular_path) and os.path.exists(bold_path):
            try:
                pdfmetrics.registerFont(TTFont(regular_name, regular_path))
                pdfmetrics.registerFont(TTFont(bold_name, bold_path))
                FONT_REGULAR = regular_name
                FONT_BOLD = bold_name
                return
            except Exception:
                continue


def _decimal(value):
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _is_present(value):
    if value in (None, ""):
        return False
    if isinstance(value, str) and not value.strip():
        return False
    try:
        return Decimal(str(value).strip()) != Decimal("0")
    except (InvalidOperation, TypeError, ValueError):
        return True


def _money(value):
    amount = _decimal(value).quantize(Decimal("0.01"))
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    whole, fraction = f"{amount:.2f}".split(".")

    if len(whole) > 3:
        last_three = whole[-3:]
        rest = whole[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        whole = ",".join(groups + [last_three])

    return f"{sign}₹{whole}.{fraction}/-"


def _date_label(value):
    if not value:
        return ""
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:19], fmt).strftime("%d-%b-%Y")
        except ValueError:
            continue
    return text


def _month_label(month, year):
    try:
        return f"{calendar.month_name[int(month)]} {int(year)}"
    except (TypeError, ValueError):
        return f"{month}/{year}"


def _record_value(record, *names, default=None):
    for name in names:
        if name in record and record.get(name) not in (None, ""):
            return record.get(name)
    return default


def _paid_on_label(record):
    paid_at = _record_value(record, "paid_at")
    if not paid_at:
        return ""
    return _date_label(paid_at)


def _status_label(record):
    explicit = str(_record_value(record, "payment_status", default="")).strip().lower()
    salary_status = str(record.get("salary_status") or "").strip().lower()
    is_paid = (explicit == "paid") or (salary_status == "paid")
    return "✓ PAID" if is_paid else "✗ UNPAID"


def _build_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            "CompanyName",
            parent=styles["Normal"],
            fontName=FONT_BOLD,
            fontSize=17,
            leading=20,
            alignment=TA_RIGHT,
            textColor=colors.HexColor("#1F2933"),
        )
    )
    styles.add(
        ParagraphStyle(
            "Address",
            parent=styles["Normal"],
            fontName=FONT_REGULAR,
            fontSize=9.5,
            leading=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#374151"),
        )
    )
    styles.add(
        ParagraphStyle(
            "SlipTitle",
            parent=styles["Normal"],
            fontName=FONT_BOLD,
            fontSize=15,
            leading=18,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#111827"),
            spaceBefore=4,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            "Label",
            parent=styles["Normal"],
            fontName=FONT_BOLD,
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#4B5563"),
        )
    )
    styles.add(
        ParagraphStyle(
            "Cell",
            parent=styles["Normal"],
            fontName=FONT_REGULAR,
            fontSize=9.5,
            leading=12,
            textColor=colors.HexColor("#111827"),
        )
    )
    styles.add(
        ParagraphStyle(
            "CellRight",
            parent=styles["Cell"],
            alignment=TA_RIGHT,
        )
    )
    styles.add(
        ParagraphStyle(
            "CellBold",
            parent=styles["Cell"],
            fontName=FONT_BOLD,
        )
    )
    styles.add(
        ParagraphStyle(
            "CellBoldRight",
            parent=styles["CellBold"],
            alignment=TA_RIGHT,
        )
    )
    styles.add(
        ParagraphStyle(
            "FinalCell",
            parent=styles["CellBold"],
            fontSize=11,
            leading=14,
            textColor=colors.white,
        )
    )
    styles.add(
        ParagraphStyle(
            "FinalCellRight",
            parent=styles["FinalCell"],
            alignment=TA_RIGHT,
        )
    )
    styles.add(
        ParagraphStyle(
            "Footer",
            parent=styles["Normal"],
            fontName=FONT_REGULAR,
            fontSize=8,
            leading=10,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#6B7280"),
        )
    )
    return styles


def _paragraph(text, style):
    return Paragraph(escape(str(text or "")), style)


def _logo_flowable(width=35 * mm, height=22 * mm):
    logo_path = os.path.join(current_app.root_path, "static", "images", "logo1.png")
    if not os.path.exists(logo_path):
        return Paragraph("", getSampleStyleSheet()["Normal"])
    try:
        image = Image(logo_path, width=width, height=height)
        image.hAlign = "LEFT"
        return image
    except Exception:
        return Paragraph("", getSampleStyleSheet()["Normal"])


def _add_salary_row(rows, label, value, styles, amount=True, always=False, bold=False):
    if not always and not _is_present(value):
        return
    label_style = styles["CellBold"] if bold else styles["Cell"]
    amount_style = styles["CellBoldRight"] if bold else styles["CellRight"]
    display_value = _money(value) if amount else value
    rows.append([_paragraph(label, label_style), _paragraph(display_value, amount_style)])


def _salary_rows(record, worker, styles):
    total_days = _decimal(record.get("total_days"))
    attended_days = _decimal(record.get("attended_days"))
    absent_days = total_days - attended_days
    absent_deduction = _decimal(record.get("per_day_salary")) * absent_days

    # DEBUG: quick snapshot of possible mappings (do not remove)
    # Helps diagnose cases where FINAL PAYABLE shows ₹0.00
    print("PDF FINAL DEBUG:", {
        "id": record.get("id"),
        "total_salary": record.get("total_salary"),
        "net_salary": record.get("net_salary"),
        "final_payable_salary": record.get("final_payable_salary"),
        "payable_salary": record.get("payable_salary"),
        "paid_amount": record.get("paid_amount"),
        "payment_amount": record.get("payment_amount"),
    })

    # Prefer correct computed fields; fall back to total_salary.
    final_payable = _record_value(
        record,
        "net_payable",
        "final_payable_salary",
        "final_salary",
        "final_payable",
        "payable_salary",
        "net_salary",
        default=record.get("total_salary"),
    )


    rows = [[_paragraph("DETAIL", styles["CellBold"]), _paragraph("AMOUNT", styles["CellBoldRight"])]]
    _add_salary_row(rows, "TOTAL BASIC AMOUNT", worker.get("monthly_salary"), styles)
    _add_salary_row(rows, "PER DAY SALARY", record.get("per_day_salary"), styles)
    if absent_days > 0:
        _add_salary_row(rows, f"ABSENT DAY ({absent_days:.1f} days)", f"({_money(absent_deduction)})", styles, amount=False)
    _add_salary_row(rows, f"PRESENT DAY ({attended_days:.1f} days)", record.get("base_salary"), styles)
    _add_salary_row(rows, "BONUS", record.get("bonus"), styles)
    _add_salary_row(rows, "OVERTIME", record.get("overtime"), styles)
    _add_salary_row(rows, "COMMISSION", record.get("commission"), styles)

    advance = _record_value(record, "advance_salary", "advance_amount", "advance")
    advance_date = _record_value(record, "advance_date", "advance_salary_date")
    advance_label = "ADVANCE SALARY"
    if advance_date:
        advance_label += f" ({_date_label(advance_date)})"
    _add_salary_row(rows, advance_label, advance, styles)

    advance_note = _record_value(record, "advance_note", "advance_salary_note")
    _add_salary_row(rows, "ADVANCE NOTE", advance_note, styles, amount=False)
    _add_salary_row(rows, "PF DEDUCTION", _record_value(record, "pf_deduction", "pf"), styles)
    _add_salary_row(rows, "ESI DEDUCTION", _record_value(record, "esi_deduction", "esi"), styles)
    _add_salary_row(rows, "TDS", _record_value(record, "tds", "tds_deduction"), styles)
    _add_salary_row(rows, "TOTAL SALARY", record.get("total_salary"), styles, always=True, bold=True)
    rows.append(
        [
            _paragraph("FINAL PAYABLE SALARY", styles["FinalCell"]),
            _paragraph(_money(final_payable), styles["FinalCellRight"]),
        ]
    )
    return rows


def _table(data, col_widths, commands):
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle(commands))
    return table


def generate_salary_pdf(record_id):
    _register_fonts()
    buffer = BytesIO()

    db = get_db()
    record = db.execute("SELECT * FROM salary_records WHERE id = ?", (record_id,)).fetchone()


    if not record:
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = _build_styles()
        doc.build([Paragraph("<b>Error: Record not found</b>", styles["SlipTitle"])])
        buffer.seek(0)
        return buffer

    record = dict(record)
    worker = get_worker(record["worker_id"]) or {"name": "Unknown", "phone": "", "monthly_salary": 0}
    month_text = _month_label(record.get("month"), record.get("year"))
    generated_at = datetime.now().strftime("%d-%b-%Y %I:%M %p")

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.45 * cm,
        leftMargin=1.45 * cm,
        topMargin=1.25 * cm,
        bottomMargin=1.2 * cm,
    )
    styles = _build_styles()
    story = []
    page_width = A4[0] - doc.leftMargin - doc.rightMargin

    header = Table(
        [[_logo_flowable(), _paragraph(COMPANY_NAME, styles["CompanyName"])]],
        colWidths=[page_width * 0.38, page_width * 0.62],
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(header)

    address = Table(
        [[_paragraph(COMPANY_ADDRESS, styles["Address"])]],
        colWidths=[page_width],
    )
    address.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#9CA3AF")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend([address, Spacer(1, 8)])

    info = Table(
        [
            [
                _paragraph("EMPLOYEE NAME", styles["Label"]),
                _paragraph(worker.get("name") or record.get("worker_id"), styles["CellBold"]),
                _paragraph("MONTH", styles["Label"]),
                _paragraph(month_text, styles["CellBold"]),
            ]
        ],
        colWidths=[page_width * 0.22, page_width * 0.33, page_width * 0.15, page_width * 0.30],
    )
    info.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#9CA3AF")),
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#EEF2F7")),
                ("BACKGROUND", (2, 0), (2, 0), colors.HexColor("#EEF2F7")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.extend([info, Spacer(1, 8), _paragraph("MONTHLY SALARY SLIP", styles["SlipTitle"])])

    salary_data = _salary_rows(record, worker, styles)
    salary_table = _table(
        salary_data,
        [page_width * 0.58, page_width * 0.42],
        [
            ("GRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#6B7280")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9E2EC")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, -2), (-1, -2), colors.HexColor("#DCFCE7")),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#22C55E")),
            ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
            ("FONTSIZE", (0, -1), (-1, -1), 11),
        ],
    )
    story.extend([salary_table, Spacer(1, 10)])

    payment_method = _record_value(record, "payment_method", "pay_method", default="Pending")
    payment_reference = _record_value(record, "payment_reference", "payment_ref", "transaction_id", default="—")
    final_payable = _record_value(
        record,
        "final_payable_salary",
        "payable_salary",
        "net_salary",
        default=record.get("total_salary"),
    )
    paid_on = _paid_on_label(record)
    payment_data = [
        [_paragraph("PAYMENT METHOD", styles["Label"]), _paragraph(payment_method or "Pending", styles["CellBold"])],
        [_paragraph("PAYMENT STATUS", styles["Label"]), _paragraph(_status_label(record), styles["CellBold"])],
        [_paragraph("PAID ON", styles["Label"]), _paragraph(paid_on or "—", styles["CellBold"])],
        [_paragraph("PAYMENT REFERENCE", styles["Label"]), _paragraph(payment_reference or "—", styles["CellBold"])],
        [_paragraph("FINAL PAYABLE SALARY", styles["Label"]), _paragraph(_money(final_payable), styles["CellBoldRight"])],
    ]
    payment = Table(payment_data, colWidths=[page_width * 0.36, page_width * 0.64])
    payment.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#6B7280")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1F5F9")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#DCFCE7")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(KeepTogether([payment, Spacer(1, 18)]))

    signature_line = "." * 34
    signatures = Table(
        [
            [_paragraph(signature_line, styles["Cell"]), _paragraph(signature_line, styles["CellRight"])],
            [_paragraph("OWNER SIGNATURE", styles["Label"]), _paragraph("RECEIVER SIGNATURE", styles["Label"])],
        ],
        colWidths=[page_width * 0.50, page_width * 0.50],
    )
    signatures.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(signatures)
    story.append(Spacer(1, 12))

    footer_text = (
        f"Generated by Shreeji Auto Service | Worker ID {record.get('worker_id')} | "
        f"Record ID {record_id} | Generated {generated_at}"
    )
    story.append(_paragraph(footer_text, styles["Footer"]))

    doc.build(story)
    buffer.seek(0)
    return buffer


def send_salary_pdf(record_id):
    from flask import send_file

    buffer = generate_salary_pdf(record_id)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"salary_slip_{record_id}.pdf",
        mimetype="application/pdf",
    )
