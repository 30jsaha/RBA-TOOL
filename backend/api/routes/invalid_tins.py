import re
import threading

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from api.extensions import db
from utils.rbac import require_permission
from business_decisions.jobs import create_status_job, get_active_job
from business_decisions.repository import ensure_schema, source_table, serialize_job
from business_decisions.service import admin_override
from business_decisions.tin import normalize_tin
from business_decisions.worker import run_claimed_job


bp = Blueprint("invalid_tins", __name__, url_prefix="/api/invalid-tins")

_TIN_PATTERN = re.compile(r"^[1-9][0-9]{8}$")


def _normalize_tin(value):
    return str(value or "").strip()


def _start_decision_worker():
    def _run():
        try:
            run_claimed_job(db.engine)
        except Exception as exc:
            print(f"[INVALID_TIN_WORKER] {exc}")
    threading.Thread(target=_run, name="invalid-tin-business-decision", daemon=True).start()


def _validate_tin(value):
    tin_number = _normalize_tin(value)
    if not _TIN_PATTERN.fullmatch(tin_number):
        return None, "TIN number must contain exactly 9 digits and cannot start with 0"
    return tin_number, None


def _serialize(row):
    return {
        "id": row["id"],
        "tin_number": row["tin_number"],
        "status": bool(row["status"]),
        "created_by": row["created_by"],
        "created_date": row["created_date"].isoformat() if row["created_date"] else None,
        "modified_date": row["modified_date"].isoformat() if row["modified_date"] else None,
    }


@bp.get("/list")
@jwt_required()
def list_invalid_tins():
    rows = db.session.execute(
        text(
            """
            SELECT id, tin_number, status, created_by, created_date, modified_date
            FROM invalid_tins
            ORDER BY created_date DESC, id DESC
            """
        )
    ).mappings().all()
    return jsonify({"success": True, "data": [_serialize(row) for row in rows]}), 200


@bp.post("/create-invalid-tin")
@jwt_required()
def create_invalid_tin():
    payload = request.get_json(silent=True) or {}
    tin_number, error = _validate_tin(payload.get("tin_number"))
    if error:
        return jsonify({"success": False, "message": error}), 400

    existing = db.session.execute(
        text("SELECT id FROM invalid_tins WHERE tin_number = :tin_number LIMIT 1"),
        {"tin_number": tin_number},
    ).first()
    if existing:
        return jsonify({"success": False, "message": "TIN number already exists"}), 409

    try:
        db.session.execute(
            text(
                """
                INSERT INTO invalid_tins
                    (tin_number, status, created_by, created_date, modified_date)
                VALUES
                    (:tin_number, 1, :created_by, NOW(), NOW())
                """
            ),
            {"tin_number": tin_number, "created_by": int(get_jwt_identity())},
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"success": False, "message": "TIN number already exists"}), 409
    except Exception:
        db.session.rollback()
        return jsonify({"success": False, "message": "Unable to create invalid TIN"}), 500

    return jsonify({"success": True, "message": "Invalid TIN created successfully"}), 201


@bp.put("/<int:tin_id>")
@jwt_required()
def update_invalid_tin(tin_id):
    payload = request.get_json(silent=True) or {}
    tin_number, error = _validate_tin(payload.get("tin_number"))
    if error:
        return jsonify({"success": False, "message": error}), 400

    try:
        duplicate = db.session.execute(
            text(
                """
                SELECT id FROM invalid_tins
                WHERE tin_number = :tin_number AND id <> :tin_id
                LIMIT 1
                """
            ),
            {"tin_number": tin_number, "tin_id": tin_id},
        ).first()
        if duplicate:
            return jsonify({"success": False, "message": "TIN number already exists"}), 409

        target = db.session.execute(
            text("SELECT id FROM invalid_tins WHERE id = :tin_id LIMIT 1"),
            {"tin_id": tin_id},
        ).first()
        if not target:
            db.session.rollback()
            return jsonify({"success": False, "message": "Invalid TIN not found"}), 404

        db.session.execute(
            text(
                """
                UPDATE invalid_tins
                SET tin_number = :tin_number, modified_date = NOW()
                WHERE id = :tin_id
                """
            ),
            {"tin_number": tin_number, "tin_id": tin_id},
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"success": False, "message": "TIN number already exists"}), 409
    except Exception:
        db.session.rollback()
        return jsonify({"success": False, "message": "Unable to update invalid TIN"}), 500

    return jsonify({"success": True, "message": "Invalid TIN updated successfully"}), 200


@bp.put("/<int:tin_id>/status")
@jwt_required()
def update_invalid_tin_status(tin_id):
    payload = request.get_json(silent=True) or {}
    status = payload.get("status")
    if not isinstance(status, bool):
        return jsonify({"success": False, "message": "Status must be a boolean"}), 400

    target = db.session.execute(
        text("SELECT id, tin_number, status FROM invalid_tins WHERE id = :tin_id LIMIT 1"),
        {"tin_id": tin_id},
    ).mappings().first()
    if not target:
        db.session.rollback()
        return jsonify({"success": False, "message": "Invalid TIN not found"}), 404

    current_status = bool(target["status"])
    if current_status == status:
        try:
            ensure_schema(db.engine)
            active = get_active_job(
                db.engine,
                normalize_tin(target["tin_number"]),
                "ENABLE" if status else "DISABLE",
            )
        except Exception:
            active = None
        if active:
            _start_decision_worker()
            return jsonify({"success": True, "job_id": active["job_id"],
                            "status": active["status"], "created": False,
                            "message": "Existing Invalid TIN status-change job returned"}), 202
        return jsonify({"success": True, "message": "Invalid TIN status is already set"}), 200
    try:
        ensure_schema(db.engine)
        job, created = create_status_job(
            db.engine,
            tin_key=normalize_tin(target["tin_number"]),
            tin_id=tin_id,
            action="ENABLE" if status else "DISABLE",
            requested_by=int(get_jwt_identity()),
            before=current_status,
            after=status,
        )
        _start_decision_worker()
        return jsonify({"success": True, "job_id": job["job_id"],
                        "status": job["status"], "created": created,
                        "message": "Invalid TIN status change queued"}), 202
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"success": False, "message": str(exc)}), 409
    except LookupError as exc:
        db.session.rollback()
        return jsonify({"success": False, "message": str(exc)}), 404
    except Exception:
        db.session.rollback()
        return jsonify({"success": False, "message": "Unable to queue Invalid TIN status change"}), 500


@bp.get("/<tin>/business-decisions")
@jwt_required()
@require_permission("business_decisions.view")
def business_decisions_history(tin):
    tin_key = normalize_tin(tin)
    if not tin_key:
        return jsonify({"success": False, "message": "Invalid TIN"}), 400
    try:
        page = max(int(request.args.get("page", 1)), 1)
        page_size = min(max(int(request.args.get("page_size", 50)), 1), 100)
    except ValueError:
        return jsonify({"success": False, "message": "Invalid pagination"}), 400
    clauses = ["tin_key=:tin_key"]
    params = {"tin_key": tin_key, "limit": page_size, "offset": (page - 1) * page_size}
    for field in ("tax_type", "decision_type"):
        value = request.args.get(field)
        if value:
            column = "tax_type" if field == "tax_type" else "business_decision_type"
            clauses.append(f"{column}=:_{field}")
            params[f"_{field}"] = value.upper()
    if request.args.get("tax_period_year"):
        clauses.append("tax_period_year=:year")
        params["year"] = int(request.args["tax_period_year"])
    if request.args.get("tax_period_month"):
        clauses.append("tax_period_month=:month")
        params["month"] = int(request.args["tax_period_month"])
    if request.args.get("current_only", "false").lower() == "true":
        clauses.append("is_current=1")
    where = " AND ".join(clauses)
    rows = db.session.execute(text(
        f"SELECT tax_type, source_table, source_record_id, tin_original, taxpayer_name_at_decision, "
        f"tax_period_year, tax_period_month, original_ml_result, original_rule_result, "
        f"current_business_result, business_decision_type, decision_reason, "
        f"invalid_tin_state_at_decision, invalid_tin_id, decision_version, is_current, "
        f"previous_decision_id, decided_by_user_id, override_reason, decided_at "
        f"FROM fraud_business_decisions WHERE {where} "
        f"ORDER BY source_record_id, decision_version LIMIT :limit OFFSET :offset"
    ), params).mappings().all()
    return jsonify({"success": True, "data": {
        "tin": tin_key,
        "records": [dict(row) for row in rows],
        "page": page, "page_size": page_size,
        "has_next": len(rows) == page_size,
    }}), 200


@bp.get("/jobs/<int:job_id>")
@jwt_required()
@require_permission("business_decisions.jobs")
def business_decision_job_status(job_id):
    row = db.session.execute(text(
        "SELECT * FROM fraud_business_decision_jobs WHERE job_id=:job_id LIMIT 1"
    ), {"job_id": job_id}).mappings().first()
    if not row:
        return jsonify({"success": False, "message": "Job not found"}), 404
    return jsonify({"success": True, "data": serialize_job(row)}), 200


@bp.post("/<tax_type>/<int:source_record_id>/business-decisions/override")
@jwt_required()
@require_permission("business_decisions.override")
def override_business_decision(tax_type, source_record_id):
    tax_type = str(tax_type).upper()
    if tax_type not in {"GST", "SWT", "CIT"}:
        return jsonify({"success": False, "message": "Invalid tax type"}), 400
    payload = request.get_json(silent=True) or {}
    result = payload.get("result")
    reason = payload.get("reason")
    user_id = int(get_jwt_identity())
    table = source_table(tax_type)
    name_col = "taxpayer" if tax_type == "CIT" else "taxpayer_name"
    row = db.session.execute(text(
        f"SELECT *, {name_col} AS taxpayer_name FROM `{table}` WHERE id=:id LIMIT 1"
    ), {"id": source_record_id}).mappings().first()
    if not row:
        return jsonify({"success": False, "message": "Source record not found"}), 404
    try:
        ensure_schema(db.engine)
        with db.engine.begin() as conn:
            decision_id = admin_override(conn, tax_type=tax_type, row=dict(row),
                                         result=result, reason=reason, actor_id=user_id)
        return jsonify({"success": True, "decision_id": decision_id}), 200
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception:
        db.session.rollback()
        return jsonify({"success": False, "message": "Unable to create override"}), 500
