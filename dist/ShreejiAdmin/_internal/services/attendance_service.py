"""Attendance service layer — business logic for attendance-to-salary integration."""

import calendar

from models.attendance_model import (
    calculate_month_attendance,
)


def get_attendance_summary_for_period(worker_id, year, month):
    """
    Returns attendance data for salary calculation.
    Includes auto-computed attended_days and total_days from attendance records,
    plus a breakdown of each status type.
    """
    month_int = int(month)
    year_int = int(year)
    total_days = calendar.monthrange(year_int, month_int)[1]

    att_data = calculate_month_attendance(worker_id, year_int, month_int)

    return {
        "worker_id": worker_id,
        "year": year_int,
        "month": month_int,
        "total_days": total_days,
        "attended_days": att_data["attended_days"],
        "present_days": att_data["present_days"],
        "half_days": att_data["half_days"],
        "absent_days": att_data["absent_days"],
        "leave_days": att_data["leave_days"],
        "holiday_days": att_data["holiday_days"],
        "attendance_pct": att_data["attendance_pct"],
        "is_fully_recorded": att_data["total_days"] >= total_days,
    }


def get_attendance_preview_for_worker(worker_id, year, month):
    """
    Lightweight preview used by the salary calculator to show
    auto-filled attendance before saving.
    """
    data = get_attendance_summary_for_period(worker_id, year, month)
    total = data["total_days"]
    attended = data["attended_days"]
    pct = data["attendance_pct"]

    # If attendance records are sparse vs total days, note it
    recorded = data["present_days"] + data["half_days"] + data["absent_days"] + data["leave_days"] + data["holiday_days"]
    missing = total - recorded

    data["missing_days"] = missing
    data["has_any_records"] = recorded > 0
    return data


def get_leave_config():
    """
    Returns configurable weights for leave days.
    Currently leave=0 (not counted as attended).
    Extensible: return {"leave": 0.5} to count half leave days.
    """
    return {
        "leave": 0.0,   # leave days are not paid
        "holiday": 0.0,  # holidays are not worked days
    }


def get_status_badge_info():
    """Returns badge styling metadata for each attendance status."""
    return {
        "present":  {"label": "Present",  "color": "#067647", "bg": "#ecfdf3", "icon": "fa-check-circle"},
        "absent":   {"label": "Absent",   "color": "#991b1b", "bg": "#fef2f2", "icon": "fa-xmark-circle"},
        "half_day": {"label": "Half Day", "color": "#c2410c", "bg": "#fff7ed", "icon": "fa-adjust"},
        "leave":    {"label": "Leave",    "color": "#1d4ed8", "bg": "#eff6ff", "icon": "fa-calendar-minus"},
        "holiday":  {"label": "Holiday",  "color": "#7c3aed", "bg": "#f5f3ff", "icon": "fa-star"},
    }


def status_color(status):
    """Return CSS color for a given status key."""
    colors = {
        "present":  "#067647",
        "absent":   "#991b1b",
        "half_day": "#c2410c",
        "leave":    "#1d4ed8",
        "holiday":  "#7c3aed",
    }
    return colors.get(status, "#6b7280")


def status_bg(status):
    """Return CSS background for a given status key."""
    bgs = {
        "present":  "#ecfdf3",
        "absent":   "#fef2f2",
        "half_day": "#fff7ed",
        "leave":    "#eff6ff",
        "holiday":  "#f5f3ff",
    }
    return bgs.get(status, "#f9fafb")


def export_to_csv(records):
    """Convert a list of attendance records to CSV string."""
    lines = ["Worker ID,Name,Phone,Date,Status,Notes"]
    for r in records:
        lines.append(
            f"{r.get('worker_id','')},{r.get('name','')},{r.get('phone','')},"
            f"{r.get('attendance_date','')},{r.get('status','')},{r.get('notes','')}"
        )
    return "\n".join(lines)


def export_to_dict(records):
    """Convert attendance records for PDF export."""
    return records
