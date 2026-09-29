from __future__ import annotations

from typing import Any, Dict, Optional, Set

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import text

from ..extensions import db


bp = Blueprint("conflicts_admin", __name__, url_prefix="/api/admin/conflicts")


_ALLOWED_TAX_TYPES = {"ALL", "GST", "CIT", "SWT"}
_ALLOWED_SOURCE_TABLES = {
    "gst_fraud_justification": "GST",
    "cit_fraud_justification": "CIT",
    "swt_fraud_justification": "SWT",
}
_PENDING = 0
_APPROVED = 1
_REJECTED = 2


def _unauthorized():
    return jsonify({"status": "error", "message": "Unauthorized access"}), 403


def _get_authenticated_user_id() -> Optional[int]:
    try:
        raw = get_jwt_identity()
        if raw is None:
            return None
        return int(raw)
    except Exception:
        return None


def _validate_user_exists(user_id: int) -> bool:
    try:
        cnt = (
            db.session.execute(text("SELECT COUNT(*) AS cnt FROM users WHERE id = :id"), {"id": int(user_id)})
            .scalar()
            or 0
        )
        return int(cnt) > 0
    except Exception:
        return False


def _is_ignored_field_name(field_name: object) -> bool:
    try:
        n = str(field_name or "").strip().lower().replace(" ", "")
    except Exception:
        return False
    return n in ("unnamed:_0", "unnamed:0", "unnamed_0")


def _load_table_columns(table_name: str) -> Set[str]:
    rows = db.session.execute(
        text(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
        ),
        {"t": table_name},
    ).fetchall()
    cols = set()
    for r in rows or []:
        try:
            cols.add(str(r[0] or "").strip())
        except Exception:
            continue
    return cols


def _load_table_columns_map(table_name: str) -> Dict[str, str]:
    """
    Returns {lower_column_name: actual_column_name}.
    Helps handle case differences safely while still quoting the real identifier.
    """
    cols = _load_table_columns(table_name)
    m: Dict[str, str] = {}
    for c in cols:
        try:
            m[str(c).lower()] = str(c)
        except Exception:
            continue
    return m


def _has_column(table: str, column: str) -> bool:
    try:
        cols = _load_table_columns(table)
        return column in cols
    except Exception:
        return False


def _normalize_identifier(value: object) -> str:
    if value is None:
        return ""
    try:
        normalized = str(value).strip()
    except Exception:
        return ""
    if normalized.endswith(".0") and normalized[:-2].isdigit():
        normalized = normalized[:-2]
    return normalized


def _coerce_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return None


def _normalize_compare_value(value: object) -> object:
    try:
        if value is None or (isinstance(value, str) and value.strip() == ""):
            value = 0
        return round(float(value), 2)
    except Exception:
        try:
            return str(value).strip()
        except Exception:
            return ""


def _resolve_gst_source_row_for_conflict(conflict: Any, *, field_name: str) -> Optional[Dict[str, Any]]:
    conflict_user_id = _coerce_int(conflict.get("user_id"))
    tin = _normalize_identifier(conflict.get("tin"))
    assessment_number = _normalize_identifier(conflict.get("assessment_number"))
    tax_period_year = _coerce_int(conflict.get("tax_period_year"))
    tax_period_month = _coerce_int(conflict.get("tax_period_month"))
    expected_batch_id = _normalize_identifier(conflict.get("upload_batch_id"))
    previous_value = conflict.get("previous_value")

    if conflict_user_id is None or not tin or tax_period_year is None or tax_period_month is None or not assessment_number:
        return None

    cols_map = _load_table_columns_map("gst_fraud_justification")
    actual_field = cols_map.get(str(field_name or "").strip().lower())
    if not actual_field:
        return None

    where_parts = [
        "CAST(COALESCE(user_id, 0) AS SIGNED) = :user_id",
        "TRIM(CAST(tin AS CHAR)) = :tin",
        "tax_period_year = :tax_period_year",
        "tax_period_month = :tax_period_month",
        "TRIM(CAST(assessment_number AS CHAR)) = :assessment_number",
    ]
    params: Dict[str, Any] = {
        "user_id": int(conflict_user_id),
        "tin": tin,
        "tax_period_year": tax_period_year,
        "tax_period_month": tax_period_month,
        "assessment_number": assessment_number,
    }
    if expected_batch_id:
        where_parts.append("TRIM(CAST(upload_batch_id AS CHAR)) = :upload_batch_id")
        params["upload_batch_id"] = expected_batch_id

    rows = db.session.execute(
        text(
            f"SELECT * FROM `gst_fraud_justification` WHERE {' AND '.join(where_parts)} ORDER BY uploaded_at DESC, id DESC"
        ),
        params,
    ).mappings().fetchall()
    if not rows:
        return None

    wanted_value = _normalize_compare_value(previous_value)
    matches = [row for row in rows if _normalize_compare_value(row.get(actual_field)) == wanted_value]
    if len(matches) != 1:
        return None
    return dict(matches[0])


def _ensure_upload_conflicts_audit_columns():
    """
    Phase 2 requires `approved_by` / `rejected_by` columns.
    If DB snapshot doesn't have them yet, add them in a minimal, NULL-safe way.
    """
    cols = _load_table_columns("upload_conflicts")

    alters = []
    if "approved_by" not in cols:
        alters.append("ADD COLUMN approved_by INT NULL")
    if "rejected_by" not in cols:
        alters.append("ADD COLUMN rejected_by INT NULL")

    if not alters:
        return

    # Best-effort schema patch. If DB user lacks ALTER privilege, later UPDATE will fail anyway.
    db.session.execute(text(f"ALTER TABLE upload_conflicts {', '.join(alters)}"))


def _row_to_conflict_dict(row: Any) -> Dict[str, Any]:
    created_at = getattr(row, "created_at", None)
    created_at_s = None
    if created_at is not None:
        try:
            created_at_s = created_at.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            created_at_s = str(created_at)

    def _to_float(v: Any) -> float:
        if v is None:
            return 0.0
        try:
            if isinstance(v, str):
                s = v.strip()
                if s == "":
                    return 0.0
                return float(s)
            return float(v)
        except Exception:
            try:
                return float(str(v).strip() or 0)
            except Exception:
                return 0.0

    prev_v = getattr(row, "previous_value", None)
    curr_v = getattr(row, "current_value", None)
    difference = abs(_to_float(curr_v) - _to_float(prev_v))

    return {
        "id": getattr(row, "id", None),
        "tax_type": getattr(row, "tax_type", None),
        "tin": getattr(row, "tin", None),
        "taxpayer_name": getattr(row, "taxpayer_name", None),
        "tax_period_year": getattr(row, "tax_period_year", None),
        "tax_period_month": getattr(row, "tax_period_month", None),
        "assessment_number": getattr(row, "assessment_number", None),
        "field_name": getattr(row, "field_name", None),
        "previous_value": getattr(row, "previous_value", None),
        "current_value": getattr(row, "current_value", None),
        "difference": difference,
        "status": getattr(row, "status", None),
        "created_at": created_at_s,
    }


def _build_upload_conflicts_select_expr(table_cols: Set[str]) -> str:
    """
    Always returns the response keys, but uses NULL for missing columns to avoid breaking
    older DB snapshots.
    """
    desired = [
        "id",
        "tax_type",
        "tin",
        "taxpayer_name",
        "tax_period_year",
        "tax_period_month",
        "assessment_number",
        "field_name",
        "previous_value",
        "current_value",
        "difference",
        "status",
        "created_at",
    ]
    parts = []
    for col in desired:
        if col in table_cols:
            parts.append(col)
        else:
            parts.append(f"NULL AS {col}")
    return ", ".join(parts)


def run_gst_process(*, current_user_id: Optional[int] = None) -> None:
    # IMPORTANT:
    # Running the full GST pipeline here would append into `gst_fraud_justification`
    # (see gst upload hook), which creates duplicate records. Phase 2 approve flow
    # must NEVER insert into fraud tables; only update the existing row.
    #
    # Keep this as a safe no-op rerun hook for now.
    return None


def run_cit_process(*, current_user_id: Optional[int] = None) -> None:
    return None


def run_swt_process(*, current_user_id: Optional[int] = None) -> None:
    return None


def _ensure_fraud_history_table():
    """
    Ensure `fraud_justification_history` exists for Phase 2 approvals.
    Minimal schema; safe to run multiple times.
    """
    exists = (
        db.session.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'fraud_justification_history'"
            )
        ).scalar()
        or 0
    )
    if int(exists) > 0:
        return

    db.session.execute(
        text(
            """
            CREATE TABLE fraud_justification_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                tax_type VARCHAR(10) NULL,
                conflict_id INT NULL,
                source_record_id INT NULL,
                tin VARCHAR(64) NULL,
                taxpayer_name VARCHAR(255) NULL,
                field_name VARCHAR(255) NULL,
                old_value TEXT NULL,
                new_value TEXT NULL,
                action_type VARCHAR(64) NULL,
                upload_batch_id VARCHAR(64) NULL,
                changed_by INT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )


def _safe_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    try:
        s = str(v)
        return s
    except Exception:
        return None


def _rerun_tax_engine(tax_type: str, user_id: Optional[int]) -> None:
    t = (tax_type or "").strip().upper()
    if t == "GST":
        run_gst_process(current_user_id=user_id)
        return
    if t == "CIT":
        run_cit_process(current_user_id=user_id)
        return
    if t == "SWT":
        run_swt_process(current_user_id=user_id)
        return
    raise ValueError("Invalid tax_type for rerun")


@bp.get("/list")
@jwt_required()
def list_pending_conflicts():
    user_id = _get_authenticated_user_id()
    if user_id is None or not _validate_user_exists(user_id):
        return _unauthorized()

    tax_type = str(request.args.get("tax_type", "ALL") or "ALL").strip().upper()
    if tax_type not in _ALLOWED_TAX_TYPES:
        tax_type = "ALL"

    try:
        cols = _load_table_columns("upload_conflicts")
        order_by = "created_at DESC, id DESC" if "created_at" in cols else "id DESC"
        select_expr = _build_upload_conflicts_select_expr(cols)

        where = "status = :status"
        params: Dict[str, Any] = {"status": _PENDING}
        if tax_type != "ALL":
            where += " AND UPPER(tax_type) = :tax_type"
            params["tax_type"] = tax_type

        rows = db.session.execute(
            text(
                f"SELECT {select_expr} "
                f"FROM upload_conflicts WHERE {where} ORDER BY {order_by}"
            ),
            params,
        ).fetchall()

        return jsonify({"status": "success", "data": [_row_to_conflict_dict(r) for r in (rows or [])]}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": "Failed to load conflicts", "error": str(e)}), 500


@bp.get("/history")
@jwt_required()
def conflicts_history():
    user_id = _get_authenticated_user_id()
    if user_id is None or not _validate_user_exists(user_id):
        return _unauthorized()

    tax_type = str(request.args.get("tax_type", "ALL") or "ALL").strip().upper()
    if tax_type not in _ALLOWED_TAX_TYPES:
        tax_type = "ALL"

    try:
        cols = _load_table_columns("upload_conflicts")
        order_by = "created_at DESC, id DESC" if "created_at" in cols else "id DESC"
        select_expr = _build_upload_conflicts_select_expr(cols)

        where = "status IN (:approved, :rejected)"
        params: Dict[str, Any] = {"approved": _APPROVED, "rejected": _REJECTED}
        if tax_type != "ALL":
            where += " AND UPPER(tax_type) = :tax_type"
            params["tax_type"] = tax_type

        rows = db.session.execute(
            text(
                f"SELECT {select_expr} "
                f"FROM upload_conflicts WHERE {where} ORDER BY {order_by}"
            ),
            params,
        ).fetchall()

        return jsonify({"status": "success", "data": [_row_to_conflict_dict(r) for r in (rows or [])]}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": "Failed to load history", "error": str(e)}), 500


@bp.post("/<int:conflict_id>/approve")
@jwt_required()
def approve_conflict(conflict_id: int):
    user_id = _get_authenticated_user_id()
    if user_id is None or not _validate_user_exists(user_id):
        return _unauthorized()

    try:
        _ensure_upload_conflicts_audit_columns()

        conflict = db.session.execute(
            text("SELECT * FROM upload_conflicts WHERE id = :id AND status = :st LIMIT 1"),
            {"id": int(conflict_id), "st": _PENDING},
        ).mappings().fetchone()

        if not conflict:
            return (
                jsonify({"status": "error", "message": "Conflict not found or already processed"}),
                404,
            )

        source_table = str(conflict.get("source_table") or "").strip()
        tax_type = str(conflict.get("tax_type") or "").strip().upper()
        if source_table not in _ALLOWED_SOURCE_TABLES:
            return jsonify({"status": "error", "message": "Invalid source table"}), 422

        source_record_id = conflict.get("source_record_id", None)
        source_record_id_int = _coerce_int(source_record_id)

        field_name_raw = conflict.get("field_name")
        if not field_name_raw or _is_ignored_field_name(field_name_raw):
            return jsonify({"status": "error", "message": "Invalid field_name"}), 422
        field_name = str(field_name_raw).strip()

        source_row = None
        resolved_upload_batch_id = None
        should_repair_gst_source = (
            tax_type == "GST" and source_table == "gst_fraud_justification"
        )

        if source_record_id_int:
            source_row = db.session.execute(
                text(f"SELECT * FROM `{source_table}` WHERE id = :id LIMIT 1"),
                {"id": source_record_id_int},
            ).mappings().fetchone()
            if should_repair_gst_source and source_row:
                conflict_owner_id = _coerce_int(conflict.get("user_id"))
                source_owner_id = _coerce_int(source_row.get("user_id"))
                if conflict_owner_id is not None and source_owner_id is not None and conflict_owner_id != source_owner_id:
                    source_row = None
                    source_record_id_int = None

        if not source_row and should_repair_gst_source:
            resolved_source_row = _resolve_gst_source_row_for_conflict(conflict, field_name=field_name)
            if resolved_source_row is not None:
                source_row = resolved_source_row
                source_record_id_int = _coerce_int(source_row.get("id"))
                resolved_upload_batch_id = source_row.get("upload_batch_id")

        if not source_record_id_int or not source_row:
            return jsonify({"status": "error", "message": "Source record not found"}), 422

        if should_repair_gst_source:
            conflict_owner_id = _coerce_int(conflict.get("user_id"))
            source_owner_id = _coerce_int(source_row.get("user_id"))
            if conflict_owner_id is not None and source_owner_id is not None and conflict_owner_id != source_owner_id:
                return jsonify({"status": "error", "message": "Source record not found"}), 422

        if resolved_upload_batch_id is not None or conflict.get("source_record_id") is None:
            repair_set = []
            repair_params: Dict[str, Any] = {"id": int(conflict_id), "source_record_id": int(source_record_id_int)}
            repair_set.append("source_record_id = :source_record_id")
            if resolved_upload_batch_id is not None:
                repair_set.append("upload_batch_id = :upload_batch_id")
                repair_params["upload_batch_id"] = resolved_upload_batch_id
            db.session.execute(
                text(f"UPDATE upload_conflicts SET {', '.join(repair_set)} WHERE id = :id"),
                repair_params,
            )

        if not field_name_raw or _is_ignored_field_name(field_name_raw):
            return jsonify({"status": "error", "message": "Invalid field_name"}), 422
        field_name = str(field_name_raw).strip()

        if not field_name_raw or _is_ignored_field_name(field_name_raw):
            return jsonify({"status": "error", "message": "Invalid field_name"}), 422
        field_name = str(field_name_raw).strip()

        # Whitelist field_name via information_schema columns (case-insensitive).
        cols_map = _load_table_columns_map(source_table)
        actual_field = cols_map.get(field_name.lower())
        if not actual_field:
            return jsonify({"status": "error", "message": "Invalid field_name"}), 422

        # History FIRST (before update).
        _ensure_fraud_history_table()

        old_value = source_row.get(actual_field, None)
        new_value = conflict.get("current_value", None)

        upload_batch_id = conflict.get("upload_batch_id", None)
        if upload_batch_id is None:
            # If upload_batch_id not stored in upload_conflicts snapshot, attempt from source row.
            upload_batch_id = source_row.get("upload_batch_id", None)

        db.session.execute(
            text(
                """
                INSERT INTO fraud_justification_history
                    (tax_type, conflict_id, source_record_id, tin, taxpayer_name, field_name,
                     old_value, new_value, action_type, upload_batch_id, changed_by)
                VALUES
                    (:tax_type, :conflict_id, :source_record_id, :tin, :taxpayer_name, :field_name,
                     :old_value, :new_value, :action_type, :upload_batch_id, :changed_by)
                """
            ),
            {
                "tax_type": tax_type,
                "conflict_id": int(conflict_id),
                "source_record_id": int(source_record_id_int),
                "tin": _safe_str(conflict.get("tin", None) or source_row.get("tin", None)),
                "taxpayer_name": _safe_str(conflict.get("taxpayer_name", None) or source_row.get("taxpayer_name", None) or source_row.get("taxpayer", None)),
                "field_name": actual_field,
                "old_value": _safe_str(old_value),
                "new_value": _safe_str(new_value),
                "action_type": "CONFLICT_APPROVED",
                "upload_batch_id": _safe_str(upload_batch_id),
                "changed_by": int(user_id),
            },
        )

        # Update only the changed field (and updated_at when available).
        current_value = conflict.get("current_value", None)
        set_parts = [f"`{actual_field}` = :val"]
        params: Dict[str, Any] = {"val": current_value, "id": source_record_id_int}

        cols = set(cols_map.values())
        if "updated_at" in cols:
            set_parts.append("updated_at = NOW()")

        db.session.execute(
            text(f"UPDATE `{source_table}` SET {', '.join(set_parts)} WHERE id = :id"),
            params,
        )

        # Mark conflict approved.
        uc_cols = _load_table_columns("upload_conflicts")
        uc_set = ["status = :st", "approved_by = :uid"]
        if "updated_at" in uc_cols:
            uc_set.append("updated_at = NOW()")
        db.session.execute(
            text(f"UPDATE upload_conflicts SET {', '.join(uc_set)} WHERE id = :id"),
            {"st": _APPROVED, "uid": int(user_id), "id": int(conflict_id)},
        )

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": "Approve failed", "error": str(e)}), 500

    # Rerun tax engine after commit so the runner sees the updated values.
    try:
        _rerun_tax_engine(tax_type, user_id)
    except Exception as e:
        return (
            jsonify({"status": "error", "message": "Rerun failed", "error": str(e)}),
            500,
        )

    return (
        jsonify(
            {
                "status": "success",
                "message": f"{tax_type} conflict approved successfully and rerun completed",
            }
        ),
        200,
    )


@bp.post("/<int:conflict_id>/reject")
@jwt_required()
def reject_conflict(conflict_id: int):
    user_id = _get_authenticated_user_id()
    if user_id is None or not _validate_user_exists(user_id):
        return _unauthorized()

    try:
        _ensure_upload_conflicts_audit_columns()

        conflict = db.session.execute(
            text("SELECT id FROM upload_conflicts WHERE id = :id AND status = :st LIMIT 1"),
            {"id": int(conflict_id), "st": _PENDING},
        ).fetchone()

        if not conflict:
            return (
                jsonify({"status": "error", "message": "Conflict not found or already processed"}),
                404,
            )

        uc_cols = _load_table_columns("upload_conflicts")
        uc_set = ["status = :st", "rejected_by = :uid"]
        if "updated_at" in uc_cols:
            uc_set.append("updated_at = NOW()")
        db.session.execute(
            text(f"UPDATE upload_conflicts SET {', '.join(uc_set)} WHERE id = :id"),
            {"st": _REJECTED, "uid": int(user_id), "id": int(conflict_id)},
        )
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": "Reject failed", "error": str(e)}), 500

    return jsonify({"status": "success", "message": "Conflict rejected successfully"}), 200
