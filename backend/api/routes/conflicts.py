from flask import Blueprint, request, jsonify
from datetime import datetime
from flask_jwt_extended import jwt_required, get_jwt_identity

from ..extensions import db
from ..models.prediction_temp_records import PredictionTempRecords
from ..models.swt_prediction_temp_records import SWTPredictionTempRecords
from ..models.cit_prediction_temp_records import CITPredictionTempRecords
from ..models.predicted_records import PredictedRecords
from ..models.predicted_swt_records import PredictedSWTRecords
from ..models.predicted_cit_records import PredictedCITRecords
from ..models.flagged_audit_records_swt import FlaggedAuditRecordSWT
from ..models.upload_history import UploadHistory
from ..models.security import User

bp = Blueprint("conflicts", __name__)

STATUS_MAP = {0: "Pending", 1: "Approved", 2: "Rejected"}

GST_FIELDS = {
    "total_sales_income",
    "exempt_sales",
    "zero_rated_sales",
    "add_exempt_and_zero_rated_sales",
    "gst_taxable_sales",
    "output_debits",
    "deferred_import_liabilities",
    "gst_paid_on_inputs",
    "gst_paid_exempt_sales",
    "gst_paid_private",
    "add_private_and_exempt_gst_paid",
    "input_credits",
    "deduct_input_credits",
    "gst_payable",
    "gst_refundable",
    "gst_sec65a_credit_allowable",
}

SWT_FIELDS = {
    "total_salary_wages_paid",
    "employees_on_payroll",
    "employees_paid_swt",
    "sw_paid_for_swt_deduction",
    "total_swt_tax_deducted",
}

CIT_FIELDS = {
    "gross_sales_cash_or_credit",
    "total_gross_income",
    "cost_of_goods_sold",
    "property_or_equipment",
    "leasehold_improvements",
    "management_fees_foreign",
    "total_operating_expenses",
    "royalties_foreign",
    "advertising_and_promotion",
    "bad_debts_written_off",
    "accounts_receivable_trade",
    "consultancy_fees",
    "legal_expenses",
    "repairs_and_maintenance",
    "travel_and_accommodation",
    "other_gross_income",
    "total_current_assets",
    "gross_tax",
}


def _field_list(change_json):
    if not change_json:
        return ""
    if isinstance(change_json, dict):
        return ", ".join(change_json.keys())
    return ""


def _apply_status_filter(query, model, status_raw):
    if status_raw is None or status_raw == "":
        return query

    status_raw = str(status_raw).strip()
    if status_raw == "0":
        return query.filter(model.status == 0)
    if status_raw.startswith("!=") and status_raw[2:] == "0":
        return query.filter(model.status != 0)
    try:
        status_val = int(status_raw)
        return query.filter(model.status == status_val)
    except ValueError:
        return query


def _apply_submit_filter(query, model, submit_raw):
    if submit_raw is None or submit_raw == "":
        return query
    submit_raw = str(submit_raw).strip()
    if submit_raw in ("0", "1"):
        return query.filter(model.is_submit == int(submit_raw))
    return query


def _build_conflict_rows(tax_type, status_raw=None, submit_raw=None):
    data = []

    def enrich_rows(rows, ttype):
        for r in rows:
            upload = db.session.query(UploadHistory).filter(
                UploadHistory.id == r.file_upload_history_id
            ).first()
            uploader = db.session.query(User).filter(User.id == upload.uploaded_by).first() if upload else None

            data.append({
                "id": r.id,
                "tax_type": ttype.upper(),
                "field_name": _field_list(r.change_json),
                "tin": getattr(r, "tin_number", None) or getattr(r, "tin", None),
                "tax_period_year": getattr(r, "tax_period_year", None),
                "tax_period_month": getattr(r, "tax_period_month", None),
                "assessment_no": getattr(r, "assessment_no", None) or getattr(r, "assessment_number", None),
                "change_json": r.change_json,
                "status": STATUS_MAP.get(int(getattr(r, "status", 0)), "Pending"),
                "is_submit": int(getattr(r, "is_submit", 0) or 0),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "uploaded_by": uploader.full_name if uploader and uploader.full_name else (uploader.email if uploader else upload.uploaded_by if upload else None),
                "file_upload_history_id": r.file_upload_history_id,
                "upload_path": getattr(upload, "upload_path", None) if upload else None,
                "start_date": getattr(upload, "date_from", None),
                "end_date": getattr(upload, "date_to", None),
            })

    if tax_type in (None, "gst"):
        q = db.session.query(PredictionTempRecords)
        q = _apply_status_filter(q, PredictionTempRecords, status_raw)
        q = _apply_submit_filter(q, PredictionTempRecords, submit_raw)
        rows = q.order_by(PredictionTempRecords.created_at.desc()).all()
        enrich_rows(rows, "gst")

    if tax_type in (None, "swt"):
        q = db.session.query(SWTPredictionTempRecords)
        q = _apply_status_filter(q, SWTPredictionTempRecords, status_raw)
        q = _apply_submit_filter(q, SWTPredictionTempRecords, submit_raw)
        rows = q.order_by(SWTPredictionTempRecords.created_at.desc()).all()
        enrich_rows(rows, "swt")

    if tax_type in (None, "cit"):
        q = db.session.query(CITPredictionTempRecords)
        q = _apply_status_filter(q, CITPredictionTempRecords, status_raw)
        q = _apply_submit_filter(q, CITPredictionTempRecords, submit_raw)
        rows = q.order_by(CITPredictionTempRecords.created_at.desc()).all()
        enrich_rows(rows, "cit")

    return data


@bp.get("/conflicts/list")
@jwt_required()
def list_conflicts():
    tax_type = request.args.get("tax_type")
    tax_type = tax_type.strip().lower() if tax_type else None
    status_raw = request.args.get("status")
    submit_raw = request.args.get("is_submit")

    data = _build_conflict_rows(tax_type, status_raw, submit_raw)
    return jsonify({"status": "success", "data": data}), 200


@bp.get("/conflicts")
@jwt_required()
def list_conflicts_v2():
    tax_type = request.args.get("tax_type")
    tax_type = tax_type.strip().lower() if tax_type else None
    status_raw = request.args.get("status")
    submit_raw = request.args.get("is_submit")

    data = _build_conflict_rows(tax_type, status_raw, submit_raw)
    return jsonify({"status": "success", "data": data}), 200


@bp.post("/conflicts/mark-submitted")
@jwt_required()
def mark_conflicts_submitted():
    payload = request.get_json() or {}
    ttype = payload.get("tax_type")
    file_upload_history_id = payload.get("file_upload_history_id")
    if not ttype or not file_upload_history_id:
        return jsonify({"status": "error", "message": "tax_type and file_upload_history_id are required"}), 400

    ttype = ttype.lower()
    if ttype == "gst":
        db.session.query(PredictionTempRecords).filter(
            PredictionTempRecords.file_upload_history_id == file_upload_history_id
        ).update({"is_submit": 1})
    elif ttype == "swt":
        db.session.query(SWTPredictionTempRecords).filter(
            SWTPredictionTempRecords.file_upload_history_id == file_upload_history_id
        ).update({"is_submit": 1})
    elif ttype == "cit":
        db.session.query(CITPredictionTempRecords).filter(
            CITPredictionTempRecords.file_upload_history_id == file_upload_history_id
        ).update({"is_submit": 1})
    else:
        return jsonify({"status": "error", "message": "Invalid tax_type"}), 400

    db.session.commit()
    return jsonify({"status": "success", "message": "Marked submitted"}), 200


@bp.post("/conflicts/submit")
@jwt_required()
def submit_conflicts():
    payload = request.get_json() or {}
    ttype = (payload.get("tax_type") or "").strip().lower()
    file_upload_history_id = payload.get("file_upload_history_id")

    if not ttype or not file_upload_history_id:
        return jsonify({
            "status": "error",
            "message": "tax_type and file_upload_history_id are required"
        }), 400

    if ttype != "swt":
        return jsonify({
            "status": "error",
            "message": "Submit flow currently supported only for SWT."
        }), 400

    try:
        approved_rows = db.session.query(SWTPredictionTempRecords).filter(
            SWTPredictionTempRecords.file_upload_history_id == file_upload_history_id,
            SWTPredictionTempRecords.status == 1,
            SWTPredictionTempRecords.is_submit == 0
        ).all()

        if not approved_rows:
            return jsonify({
                "status": "error",
                "message": "No approved records pending submit."
            }), 400

        # STEP 2 — Apply approved changes to predicted records
        updated_count = 0
        for rec in approved_rows:
            if not rec.predicted_swt_record_id:
                continue
            change_json = rec.change_json or {}
            update_data = {k: v.get("new") for k, v in change_json.items() if isinstance(v, dict) and "new" in v}
            if update_data:
                db.session.query(PredictedSWTRecords).filter(
                    PredictedSWTRecords.id == rec.predicted_swt_record_id
                ).update(update_data)
                updated_count += 1

        db.session.commit()

        # STEP 4 — Rebuild flagged audit table for this upload
        db.session.query(FlaggedAuditRecordSWT).filter(
            FlaggedAuditRecordSWT.file_history_id == file_upload_history_id
        ).delete()
        db.session.commit()

        flagged_rows = db.session.query(PredictedSWTRecords).filter(
            PredictedSWTRecords.file_upload_history_id == file_upload_history_id,
            PredictedSWTRecords.is_flag == True
        ).all()

        now = datetime.utcnow()
        insert_rows = []
        for r in flagged_rows:
            insert_rows.append({
                "prediction_id": r.id,
                "file_history_id": r.file_upload_history_id,
                "tin": r.tin,
                "taxpayer_name": r.taxpayer_name,
                "segmentation": r.segmentation,
                "total_salary_wages_paid": r.total_salary_wages_paid,
                "employees_on_payroll": r.employees_on_payroll,
                "employees_paid_swt": r.employees_paid_swt,
                "sw_paid_for_swt_deduction": r.sw_paid_for_swt_deduction,
                "total_swt_tax_deducted": r.total_swt_tax_deducted,
                "is_flag": r.is_flag,
                "created_at": now,
                "updated_at": now,
            })

        if insert_rows:
            db.session.bulk_insert_mappings(FlaggedAuditRecordSWT, insert_rows)
            db.session.commit()

        # STEP 5 — Mark submitted
        db.session.query(SWTPredictionTempRecords).filter(
            SWTPredictionTempRecords.file_upload_history_id == file_upload_history_id,
            SWTPredictionTempRecords.status == 1
        ).update({"is_submit": 1})
        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "Submit completed.",
            "updated_records": updated_count,
            "flagged_records": len(insert_rows)
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


def _get_conflict_record(ttype, conflict_id):
    if ttype == "gst":
        return db.session.query(PredictionTempRecords).filter(PredictionTempRecords.id == conflict_id).first()
    if ttype == "swt":
        return db.session.query(SWTPredictionTempRecords).filter(SWTPredictionTempRecords.id == conflict_id).first()
    if ttype == "cit":
        return db.session.query(CITPredictionTempRecords).filter(CITPredictionTempRecords.id == conflict_id).first()
    return None


def _approve_conflict_record(ttype, rec):
    if ttype == "gst":
        change_json = rec.change_json or {}
        update_data = {k: v.get("new") for k, v in change_json.items() if k in GST_FIELDS}
        if update_data and rec.predicted_record_id:
            db.session.query(PredictedRecords).filter(PredictedRecords.id == rec.predicted_record_id).update(update_data)
        rec.status = 1
        return

    if ttype == "swt":
        change_json = rec.change_json or {}
        update_data = {k: v.get("new") for k, v in change_json.items() if k in SWT_FIELDS}
        if update_data and rec.predicted_swt_record_id:
            db.session.query(PredictedSWTRecords).filter(PredictedSWTRecords.id == rec.predicted_swt_record_id).update(update_data)
        rec.status = 1
        return

    if ttype == "cit":
        change_json = rec.change_json or {}
        update_data = {k: v.get("new") for k, v in change_json.items() if k in CIT_FIELDS}
        if update_data and rec.old_predicted_record_id:
            db.session.query(PredictedCITRecords).filter(PredictedCITRecords.id == rec.old_predicted_record_id).update(update_data)
        rec.status = 1
        return


@bp.post("/conflicts/approve")
@jwt_required()
def approve_conflict():
    payload = request.get_json() or {}
    ttype = payload.get("tax_type")
    conflict_id = payload.get("id")
    if not ttype or conflict_id is None:
        return jsonify({"status": "error", "message": "tax_type and id are required"}), 400

    ttype = ttype.lower()
    rec = _get_conflict_record(ttype, conflict_id)
    if not rec:
        return jsonify({"status": "error", "message": "Conflict not found"}), 404
    if rec.status != 0:
        return jsonify({"status": "error", "message": "Conflict already processed"}), 400

    _approve_conflict_record(ttype, rec)
    db.session.commit()
    return jsonify({"status": "success", "message": "Approved"}), 200


@bp.post("/conflicts/<int:conflict_id>/approve")
@jwt_required()
def approve_conflict_v2(conflict_id):
    payload = request.get_json() or {}
    ttype = payload.get("tax_type") or request.args.get("tax_type")
    if not ttype:
        return jsonify({"status": "error", "message": "tax_type is required"}), 400

    ttype = ttype.lower()
    rec = _get_conflict_record(ttype, conflict_id)
    if not rec:
        return jsonify({"status": "error", "message": "Conflict not found"}), 404
    if rec.status != 0:
        return jsonify({"status": "error", "message": "Conflict already processed"}), 400

    _approve_conflict_record(ttype, rec)
    db.session.commit()
    return jsonify({"status": "success", "message": "Approved"}), 200


@bp.post("/conflicts/reject")
@jwt_required()
def reject_conflict():
    payload = request.get_json() or {}
    ttype = payload.get("tax_type")
    conflict_id = payload.get("id")
    if not ttype or conflict_id is None:
        return jsonify({"status": "error", "message": "tax_type and id are required"}), 400

    ttype = ttype.lower()
    rec = _get_conflict_record(ttype, conflict_id)
    if not rec:
        return jsonify({"status": "error", "message": "Conflict not found"}), 404
    if rec.status != 0:
        return jsonify({"status": "error", "message": "Conflict already processed"}), 400

    rec.status = 2
    db.session.commit()
    return jsonify({"status": "success", "message": "Rejected"}), 200


@bp.post("/conflicts/<int:conflict_id>/reject")
@jwt_required()
def reject_conflict_v2(conflict_id):
    payload = request.get_json() or {}
    ttype = payload.get("tax_type") or request.args.get("tax_type")
    if not ttype:
        return jsonify({"status": "error", "message": "tax_type is required"}), 400

    ttype = ttype.lower()
    rec = _get_conflict_record(ttype, conflict_id)
    if not rec:
        return jsonify({"status": "error", "message": "Conflict not found"}), 404
    if rec.status != 0:
        return jsonify({"status": "error", "message": "Conflict already processed"}), 400

    rec.status = 2
    db.session.commit()
    return jsonify({"status": "success", "message": "Rejected"}), 200
