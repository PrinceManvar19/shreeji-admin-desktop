"""Admin attendance routes — daily attendance management and history."""

import calendar
import datetime
import io

from flask import Blueprint, flash, redirect, render_template, request, session, url_for, make_response

from models.worker_model import get_all_workers, get_worker
from models.attendance_model import (
    ensure_attendance_table,
    upsert_attendance,
    get_attendance_for_date,
    get_today_summary,
    bulk_save_attendance,
    get_attendance_history,
    get_attendance_for_worker,
)
from services.attendance_service import (
    get_attendance_summary_for_period,
    get_attendance_preview_for_worker,
    get_status_badge_info,
    export_to_csv,
)
from utils.helpers import log_action


att_bp = Blueprint("attendance", __name__, url_prefix="/admin/attendance")


def _require_admin():
    if session.get("role") != "admin":
        flash("Admin access required", "error")
        return redirect(url_for("auth.login"))
    return None


@att_bp.route("", methods=["GET", "POST"])
def attendance_page():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    workers = get_all_workers()
    today = datetime.date.today()

    # Date from query param or form
    selected_date = request.args.get("date") or request.form.get("date")
    if selected_date:
        try:
            selected_date = datetime.date.fromisoformat(selected_date)
        except ValueError:
            selected_date = today
    else:
        selected_date = today

    date_str = selected_date.isoformat()

    if request.method == "POST":
        action = request.form.get("action", "")

        if action in ("mark_all_present", "mark_all_absent", "mark_all_half", "save"):
            records = []
            status_map = {
                "mark_all_present": "present",
                "mark_all_absent":  "absent",
                "mark_all_half":    "half_day",
                "save":             None,
            }
            bulk_status = status_map.get(action)

            for w in workers:
                worker_status = request.form.get(f"status_{w['id']}", "present").strip()
                notes = request.form.get(f"notes_{w['id']}", "").strip()
                final_status = bulk_status if bulk_status else worker_status
                records.append({
                    "worker_id": w["id"],
                    "attendance_date": date_str,
                    "status": final_status,
                    "notes": notes,
                })

            ok, err = bulk_save_attendance(records)
            if action == "save":
                flash(f"Attendance saved — {ok} records updated.", "success")
            else:
                flash(f"Bulk update complete — {ok} records.", "success")
            return redirect(url_for("attendance.attendance_page", date=date_str))

        # Single record update via inline edit
        worker_id = request.form.get("worker_id", "").strip()
        status = request.form.get("status", "present").strip()
        notes = request.form.get("notes", "").strip()
        if worker_id:
            ok, msg = upsert_attendance(worker_id, date_str, status, notes)
            if ok:
                flash("Attendance updated.", "success")
            else:
                flash(msg, "error")
            return redirect(url_for("attendance.attendance_page", date=date_str))

    # GET — load records for selected date
    existing = get_attendance_for_date(date_str)
    record_map = {r["worker_id"]: r for r in existing}

    # Build worker rows with attendance status
    worker_rows = []
    for w in workers:
        rec = record_map.get(w["id"], {})
        worker_rows.append({
            "worker": w,
            "status": rec.get("status", ""),
            "notes":  rec.get("notes", ""),
        })

    summary = get_today_summary()
    badge_info = get_status_badge_info()

    return render_template(
        "admin_attendance.html",
        workers=workers,
        worker_rows=worker_rows,
        selected_date=selected_date,
        date_str=date_str,
        summary=summary,
        badge_info=badge_info,
    )


@att_bp.route("/history", methods=["GET", "POST"])
def attendance_history():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    workers = get_all_workers()

    # Filters
    if request.method == "POST":
        worker_id = request.form.get("worker_id", "").strip() or None
        year      = request.form.get("year", "").strip() or None
        month     = request.form.get("month", "").strip() or None
        date_from = request.form.get("date_from", "").strip() or None
        date_to   = request.form.get("date_to", "").strip() or None
    else:
        worker_id = request.args.get("worker_id") or None
        year      = request.args.get("year") or None
        month     = request.args.get("month") or None
        date_from = request.args.get("date_from") or None
        date_to   = request.args.get("date_to") or None

    records = get_attendance_history(
        worker_id=worker_id,
        year=year,
        month=month,
        date_from=date_from,
        date_to=date_to,
    )

    badge_info = get_status_badge_info()
    now = datetime.datetime.now()
    year_options = list(range(now.year - 2, now.year + 1))

    return render_template(
        "admin_attendance_history.html",
        records=records,
        workers=workers,
        badge_info=badge_info,
        filters={"worker_id": worker_id, "year": year, "month": month,
                 "date_from": date_from, "date_to": date_to},
        year_options=year_options,
    )


@att_bp.route("/history/export")
def attendance_export():
    """Export filtered attendance as CSV."""
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    worker_id = request.args.get("worker_id") or None
    year      = request.args.get("year") or None
    month     = request.args.get("month") or None
    date_from = request.args.get("date_from") or None
    date_to   = request.args.get("date_to") or None

    records = get_attendance_history(
        worker_id=worker_id, year=year, month=month,
        date_from=date_from, date_to=date_to,
    )

    csv = export_to_csv(records)
    response = make_response(csv)
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = (
        f"attachment; filename=attendance_export_{datetime.date.today().isoformat()}.csv"
    )
    return response


@att_bp.route("/api/preview/<worker_id>/<year>/<month>")
def api_attendance_preview(worker_id, year, month):
    """JSON endpoint for salary calculator to fetch auto-attendance."""
    admin_guard = _require_admin()
    if admin_guard is not None:
        return {"error": "unauthorized"}, 403

    try:
        data = get_attendance_preview_for_worker(worker_id, int(year), int(month))
        return data
    except Exception as e:
        return {"error": str(e)}, 400