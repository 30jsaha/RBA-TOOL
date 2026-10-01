import re

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from api.extensions import db


bp = Blueprint("invalid_tins", __name__, url_prefix="/api/invalid-tins")

_TIN_PATTERN = re.compile(r"^[1-9][0-9]{8}$")


def _normalize_tin(value):
    return str(value or "").strip()


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
            SET status = :status, modified_date = NOW()
            WHERE id = :tin_id
            """
        ),
        {"status": int(status), "tin_id": tin_id},
    )
    db.session.commit()
    return jsonify({"success": True, "message": "Invalid TIN status updated successfully"}), 200
