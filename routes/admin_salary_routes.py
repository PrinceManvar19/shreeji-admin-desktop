import calendar
import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from models.worker_model import create_worker, delete_worker, generate_next_worker_id, get_all_workers, get_worker, update_worker
from models.salary_model import get_salary_records, get_salary_record, update_salary_record
from models.advance_model import (
    add_pocket_money_entry,
    add_worker_debt,
    apply_debt_recovery,
    get_monthly_advance_summary,
    get_monthly_pocket_money_count,
    get_monthly_pocket_money_total,
    get_outstanding_debt_total,
    get_pocket_money_entries,
    get_recovery_history,
    get_worker_debts,
)



salary_bp = Blueprint("salary", __name__, url_prefix="/admin/salary")


def _require_admin():
    """Admin access guard."""
    if session.get("role") != "admin":
        flash("Admin access required", "error")
        return redirect(url_for("auth.login"))
    return None


def _get_current_user_id():
    """Current user ID for logging."""
    return session.get("user", {}).get("id") or session.get("admin_id") or "unknown"


@salary_bp.route("/workers", methods=["GET", "POST"])
def workers():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    if request.method == "POST":
        worker_id = request.form.get("worker_id", "").strip()
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        monthly_salary = request.form.get("monthly_salary", "").strip()
        worker_status = request.form.get("worker_status", "active").strip()

        success, message, worker = create_worker(worker_id, name, phone, monthly_salary, worker_status)
        if success:
            flash("Worker added successfully!", "success")
            return redirect(url_for("salary.workers"))
        else:
            flash(message, "error")

    workers_list = get_all_workers()
    return render_template(
        "admin_worker_management.html",
        workers=workers_list,
        next_worker_id=generate_next_worker_id(),
    )

@salary_bp.route("/", methods=["GET", "POST"])
def salary_calculator():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    workers_list = get_all_workers()
    now = datetime.datetime.now()
    current_total_days = calendar.monthrange(now.year, now.month)[1]
    year_options = list(range(now.year - 2, now.year + 3))
    days_by_period = {
        str(year): {
            f"{month:02d}": calendar.monthrange(year, month)[1]
            for month in range(1, 13)
        }
        for year in year_options
    }

    if request.method == "POST":
        worker_id = request.form.get("worker_id", "").strip()
        if not worker_id:
            flash("Please select a worker", "error")
            return redirect(url_for("salary.salary_calculator"))

        try:
            total_days = int(request.form.get("total_days") or 0)
            attended_days = float(request.form.get("attended_days") or 0)
        except ValueError:
            flash("Invalid days value", "error")
            return redirect(url_for("salary.salary_calculator"))

        if total_days <= 0:
            flash("Total days must be at least 1", "error")
            return redirect(url_for("salary.salary_calculator"))

        if attended_days < 0:
            flash("Attended days cannot be negative", "error")
            return redirect(url_for("salary.salary_calculator"))

        try:
            debt_recovery_amount = float(request.form.get("debt_recovery_amount") or 0)
        except ValueError:
            flash("Invalid debt recovery amount", "error")
            return redirect(url_for("salary.salary_calculator"))

        try:
            extra_salary_amount = float(request.form.get("extra_salary_amount") or 0)
            extra_salary_amount = max(extra_salary_amount, 0)
        except ValueError:
            extra_salary_amount = 0

        extra_salary_note = request.form.get("extra_salary_note", "").strip() or "Extra salary advance"

        month = request.form.get("month", "").strip()
        year = request.form.get("year", "").strip()
        year = int(year) if year.isdigit() else None
        salary_status = request.form.get("salary_status", "finalized").strip()

        from models.salary_model import save_salary_record
        generate_slip = request.form.get("generate_slip", "0") == "1"
        salary_status = request.form.get("salary_status", "finalized").strip()

        success, message, record_id = save_salary_record(
            worker_id, total_days, attended_days,
            0, False,
            0, False,
            0, False,
            month=month if month else None,
            year=year,
            salary_status=salary_status,
            debt_recovery_amount=debt_recovery_amount,
            extra_salary_amount=extra_salary_amount,
            extra_salary_note=extra_salary_note,
        )

        if success:
            if generate_slip:
                return redirect(url_for("salary.salary_payment_step", record_id=record_id))
            else:
                flash(f"Salary record saved as draft (#{record_id}).", "success")
                return redirect(url_for("salary.salary_history"))
        else:
            flash(message, "error")


    return render_template(
        "admin_salary.html",
        workers=workers_list,
        current_month=f"{now.month:02d}",
        current_year=now.year,
        current_total_days=current_total_days,
        year_options=year_options,
        days_by_period=days_by_period,
    )


@salary_bp.route("/advance-summary")
def advance_summary():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return jsonify({"error": "Unauthorized"}), 403

    worker_id = request.args.get("worker_id", "").strip().upper()
    month = request.args.get("month", "").strip()
    year = request.args.get("year", "").strip()
    if not worker_id or not month or not year:
        return jsonify({"error": "Missing params"}), 400

    pocket_entries = get_pocket_money_entries(worker_id=worker_id, month=month, year=year)
    debts = get_worker_debts(worker_id=worker_id, open_only=True)
    recoveries = get_recovery_history(worker_id=worker_id)
    return jsonify({
        "pocket_money_total": float(get_monthly_pocket_money_total(worker_id, month, year)),
        "pocket_money_count": get_monthly_pocket_money_count(worker_id, month, year),
        "pocket_entries": [
            {
                "entry_date": str(row.get("entry_date") or ""),
                "amount": float(row.get("amount") or 0),
                "note": row.get("note") or "",
            }
            for row in pocket_entries
        ],
        "outstanding_debt": float(get_outstanding_debt_total(worker_id)),
        "debts": [
            {
                "id": row.get("id"),
                "reason": row.get("reason") or "",
                "debt_date": str(row.get("debt_date") or ""),
                "remaining_balance": float(row.get("remaining_balance") or 0),
            }
            for row in debts
        ],
        "recoveries": [
            {
                "recovery_date": str(row.get("recovery_date") or ""),
                "amount": float(row.get("recovery_amount") or 0),
                "note": row.get("note") or "",
            }
            for row in recoveries[:8]
        ],
    })


@salary_bp.route("/advances", methods=["GET", "POST"])
def worker_advances():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    workers = get_all_workers()
    now = datetime.datetime.now()
    selected_worker = request.values.get("worker_id", "").strip().upper()
    selected_month = request.values.get("month", f"{now.month:02d}").strip()
    selected_year = request.values.get("year", str(now.year)).strip()

    if request.method == "POST":
        action = request.form.get("action", "").strip()
        worker_id = request.form.get("worker_id", "").strip().upper()
        entry_date = request.form.get("entry_date", "").strip() or now.strftime("%Y-%m-%d")
        note = request.form.get("note", "").strip()

        if action == "pocket":
            success, message = add_pocket_money_entry(worker_id, request.form.get("amount"), entry_date, note)
            flash("Monthly advance entry saved." if success else message, "success" if success else "error")
        elif action == "debt":
            success, message = add_worker_debt(worker_id, request.form.get("amount"), entry_date, note)
            flash("Long-term advance saved." if success else message, "success" if success else "error")
        elif action == "recovery":
            success, message = apply_debt_recovery(worker_id, request.form.get("amount"), entry_date, note=note or "Manual recovery")
            flash("Pending advance recovery saved." if success else message, "success" if success else "error")
        else:
            flash("Unknown advance action.", "error")

        return redirect(url_for(
            "salary.worker_advances",
            worker_id=worker_id,
            month=selected_month,
            year=selected_year,
        ))

    return render_template(
        "worker_advances.html",
        workers=workers,
        selected_worker=selected_worker,
        selected_month=selected_month,
        selected_year=selected_year,
        pocket_entries=get_pocket_money_entries(selected_worker or None, selected_month, selected_year),
        debts=get_worker_debts(selected_worker or None),
        recoveries=get_recovery_history(selected_worker or None),
        summaries=get_monthly_advance_summary(selected_worker or None, selected_month, selected_year),
    )


@salary_bp.route("/history", methods=["GET", "POST"])
def salary_history():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard
    
    workers = get_all_workers()
    records = []
    filters = {}
    
    if request.method == "POST":
        filters['worker_id'] = request.form.get('worker_id')
        filters['month'] = request.form.get('month')
        filters['year'] = request.form.get('year')
    else:
        # Preserve GET filters
        filters['worker_id'] = request.args.get('worker_id')
        filters['month'] = request.args.get('month')
        filters['year'] = request.args.get('year')
    
    records = get_salary_records(
        worker_id=filters.get('worker_id'),
        month=filters.get('month'),
        year=filters.get('year')
    )
    
    return render_template("salary_history.html", records=records, workers=workers, filters=filters)


@salary_bp.route("/<int:record_id>/edit", methods=["GET", "POST"])
def edit_salary_record(record_id):
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard
    
    record = get_salary_record(record_id)
    if not record:
        flash("Salary record not found", "error")
        return redirect(url_for("salary.salary_history"))

    # GET: allow viewing paid records too (UI will lock inputs / show banner)
    if request.method == "GET":
        worker = get_worker(record['worker_id'])
        entries = get_pocket_money_entries(record["worker_id"], record.get("month"), record.get("year"))
        return render_template("salary_history_edit.html", record=record, worker=worker, monthly_advance_entries=entries)

    
    # POST
    try:
        total_days = int(request.form.get("total_days") or 0)
        attended_days = float(request.form.get("attended_days") or 0)
        bonus_val = float(request.form.get("bonus_value") or 0)
        ot_val = float(request.form.get("ot_value") or 0)
        comm_val = float(request.form.get("comm_value") or 0)
        debt_recovery_amount = float(request.form.get("debt_recovery_amount") or 0)
        extra_salary_amount = float(request.form.get("extra_salary_amount") or 0)
    except ValueError:
        flash("Invalid numeric value", "error")
        return redirect(url_for("salary.salary_history"))

    bonus_pct = request.form.get("bonus_type") == "pct"
    ot_pct = request.form.get("ot_type") == "pct"
    comm_pct = request.form.get("comm_type") == "pct"
    salary_status = request.form.get("salary_status", "finalized").strip()
    extra_salary_note = request.form.get("extra_salary_note", "").strip() or "Extra salary advance"
    
    success, message = update_salary_record(
        record_id,
        total_days=total_days,
        attended_days=attended_days,
        bonus_val=bonus_val,
        bonus_pct=bonus_pct,
        ot_val=ot_val,
        ot_pct=ot_pct,
        comm_val=comm_val,
        comm_pct=comm_pct,
        debt_recovery_amount=debt_recovery_amount,
        extra_salary_amount=max(extra_salary_amount, 0),
        extra_salary_note=extra_salary_note,
        salary_status=salary_status,
    )
    if success:
        flash(message, "success")
        return redirect(url_for("salary.salary_history"))
    else:
        flash(message, "error")
        record = get_salary_record(record_id)
        worker = get_worker(record['worker_id']) if record else None
        entries = get_pocket_money_entries(record["worker_id"], record.get("month"), record.get("year")) if record else []
        return render_template("salary_history_edit.html", record=record, worker=worker, monthly_advance_entries=entries)

@salary_bp.route("/<int:record_id>/mark-paid", methods=["POST"])
def mark_salary_paid(record_id):
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    from models.salary_model import mark_salary_as_paid

    success, message = mark_salary_as_paid(record_id, admin_user_id=_get_current_user_id())
    if success:
        flash(message, "success")
    else:
        flash(message, "error")
    return redirect(url_for("salary.salary_history"))


@salary_bp.route("/<int:record_id>/pdf")
def salary_pdf(record_id):
    admin_guard = _require_admin()

    if admin_guard is not None:
        return admin_guard
    
    from utils.pdf_generator import send_salary_pdf
    try:
        return send_salary_pdf(record_id)
    except Exception as e:
        flash(f"PDF generation failed: {str(e)}", "error")
        return redirect(url_for("salary.salary_calculator"))


@salary_bp.route("/attendance-preview", methods=["GET"])
def attendance_preview():
    """Return JSON attendance summary for a worker+month+year."""
    admin_guard = _require_admin()
    if admin_guard is not None:
        from flask import jsonify
        return jsonify({"error": "Unauthorized"}), 403

    from flask import jsonify
    from services.attendance_service import get_attendance_preview_for_worker

    worker_id = request.args.get("worker_id", "").strip().upper()
    month = request.args.get("month", "").strip()
    year = request.args.get("year", "").strip()

    if not (worker_id and month and year):
        return jsonify({"error": "Missing params"}), 400

    try:
        data = get_attendance_preview_for_worker(worker_id, int(year), month)
        return jsonify({
            "attended_days": data["attended_days"],
            "total_days": data["total_days"],
            "present_days": data["present_days"],
            "half_days": data["half_days"],
            "absent_days": data["absent_days"],
            "has_records": data["has_any_records"],
            "missing_days": data["missing_days"],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@salary_bp.route("/<int:record_id>/payment-step", methods=["GET", "POST"])
def salary_payment_step(record_id):
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    record = get_salary_record(record_id)
    if not record:
        flash("Salary record not found.", "error")
        return redirect(url_for("salary.salary_history"))

    if request.method == "POST":
        payment_method = request.form.get("payment_method", "").strip()
        payment_done = request.form.get("payment_done", "no")

        if not payment_method:
            flash("Please select a payment method.", "error")
            return render_template("salary_payment_step.html", record=record)

        from models.salary_model import update_salary_payment_info, mark_salary_as_paid
        update_salary_payment_info(record_id, payment_method=payment_method)

        if payment_done == "yes":
            mark_salary_as_paid(record_id, admin_user_id=_get_current_user_id())

        from utils.pdf_generator import send_salary_pdf
        try:
            return send_salary_pdf(record_id)
        except Exception as e:
            flash(f"PDF generation failed: {str(e)}", "error")
            return redirect(url_for("salary.salary_history"))

    return render_template("salary_payment_step.html", record=record)


@salary_bp.route("/workers/<worker_id>/edit", methods=["GET", "POST"])
def edit_worker(worker_id):

    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    worker = get_worker(worker_id)
    if not worker:
        flash("Worker not found", "error")
        return redirect(url_for("salary.workers"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        monthly_salary = request.form.get("monthly_salary", "").strip()
        worker_status = request.form.get("worker_status", "active").strip()

        success, message = update_worker(worker_id, name, phone, monthly_salary, worker_status)
        if success:
            flash("Worker updated successfully!", "success")
            return redirect(url_for("salary.workers"))
        else:
            flash(message, "error")
            worker = get_worker(worker_id)  # Refresh

    return render_template("admin_worker_management.html", worker=worker, edit_mode=True)


@salary_bp.route("/workers/<worker_id>/delete", methods=["POST"])
def delete_worker_route(worker_id):
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    success, message = delete_worker(worker_id)
    if success:
        flash("Worker deleted successfully!", "success")
    else:
        flash(message, "error")
    return redirect(url_for("salary.workers"))
