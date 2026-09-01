"""TIN Master APIs for the Upload TIN Registration page."""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
from flask import Blueprint, jsonify, request, send_file
from flask_jwt_extended import jwt_required
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from api.extensions import db
from utils.rbac import require_permission

bp = Blueprint("tin_master", __name__, url_prefix="/api/tin-master")
ALLOWED_STATUS = {"ACTIVE", "INACTIVE"}
TAXPAYER_TYPE_MAP = {"COMPANY": "ENTERPRISE", "INDIVIDUAL": "INDIVIDUAL", "GOVERNMENT": "GOVERNMENT"}
ENTERPRISE_TYPE_MAP = {"COMPANY": "COMPANY", "INDIVIDUAL": "INDIVIDUAL", "GOVERNMENT": "GOVERNMENT"}
HEADERS = {
    "tin": "TIN", "taxpayer_name": "Taxpayer Name", "trade_name": "Trade Name",
    "enterprise_type": "Enterprise Type", "province": "Province", "address": "Address",
    "email": "Email", "phone": "Phone", "sector": "Sector", "status": "Status",
}


def _value(value):
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _tin(value):
    value = _value(value)
    return value[:-2] if value.endswith(".0") and value[:-2].isdigit() else value


def _page(value, default, maximum):
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def _template():
    root = Path(__file__).resolve().parents[2] / "download" / "sample"
    for path in (root / "tin_master_import_template.xlsx", root / "tin" / "_master" / "_import" / "_template.xlsx"):
        if path.is_file():
            return path
    return None


def _read_file(file_storage):
    filename = _value(file_storage.filename).lower()
    if filename.endswith(".csv"):
        return pd.read_csv(file_storage.stream, dtype=str, keep_default_na=False)
    if filename.endswith((".xls", ".xlsx")):
        return pd.read_excel(file_storage.stream, dtype=str, keep_default_na=False)
    raise ValueError("Only CSV, XLS, and XLSX files are supported.")


def _columns(frame):
    available = {str(column).strip().casefold(): column for column in frame.columns}
    missing = [label for label in HEADERS.values() if label.casefold() not in available]
    if missing:
        raise ValueError(f"Missing template column(s): {', '.join(missing)}")
    return frame.rename(columns={available[label.casefold()]: key for key, label in HEADERS.items()})


def _record(raw):
    record = {key: _value(raw.get(key)) for key in HEADERS}
    record["tin"] = _tin(record["tin"])
    record["sector"] = record["sector"]
    record["status"] = (record["status"] or "ACTIVE").upper()
    enterprise_type = ENTERPRISE_TYPE_MAP.get(record["enterprise_type"].upper())
    taxpayer_type = TAXPAYER_TYPE_MAP.get(record["enterprise_type"].upper())
    if not record["tin"]:
        return None, "TIN is required."
    if not record["taxpayer_name"]:
        return None, "Taxpayer Name is required."
    if not record["sector"]:
        return None, "Sector is required."
    if enterprise_type is None:
        return None, "Enterprise Type must be Company, Individual, or Government."
    if record["status"] not in ALLOWED_STATUS:
        return None, "Status must be ACTIVE or INACTIVE."
    if record["email"] and ("@" not in record["email"] or "." not in record["email"].rsplit("@", 1)[-1]):
        return None, "Email is invalid."
    record["enterprise_type"] = enterprise_type
    record["taxpayer_type"] = taxpayer_type
    return record, None


def _sector_id(sector):
    row = db.session.execute(
        text("SELECT sector_id FROM sector_mst WHERE UPPER(TRIM(sector_name)) = UPPER(TRIM(:sector)) LIMIT 1"),
        {"sector": sector},
    ).mappings().first()
    return row["sector_id"] if row else None


def _insert(record):
    exists = db.session.execute(
        text("SELECT tin FROM tin_registration_mst WHERE normalized_tin = :tin OR TRIM(tin) = :tin LIMIT 1 FOR UPDATE"),
        {"tin": record["tin"]},
    ).first()
    if exists:
        return "duplicate_existing", "TIN already exists."
    sector_id = _sector_id(record["sector"])
    if sector_id is None:
        return "sector_not_found", f"Sector not found: {record['sector']}"
    db.session.execute(
        text("""
            INSERT INTO tin_registration_mst
              (tin, taxpayername, maintradename, enterprisetype, province,
               mailingaddressprovince, address1, entcontemail, phoneno,
               status, normalized_tin, sector_id, taxpayertype)
            VALUES
              (:tin, :taxpayer_name, :trade_name, :enterprise_type, :province,
              :province, :address, :email, :phone, :status, :tin, :sector_id, :taxpayer_type)
        """),
        {**record, "sector_id": sector_id},
    )
    db.session.execute(
        text("INSERT INTO tin_province_lookup (tin, taxpayer_name, province) VALUES (:tin, :taxpayer_name, :province)"),
        record,
    )
    return "inserted", None


@bp.get("/template")
@jwt_required()
@require_permission("upload_tin_registration")
def download_template():
    path = _template()
    if path is None:
        return jsonify({"message": "TIN Master template is not available."}), 404
    return send_file(path, as_attachment=True, download_name="tin_master_import_template.xlsx", max_age=0)


@bp.get("/sectors")
@jwt_required()
@require_permission("upload_tin_registration")
def list_sectors():
    try:
        rows = db.session.execute(text("SELECT sector_id, sector_name FROM sector_mst ORDER BY sector_name ASC")).mappings().all()
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Unable to load sectors."}), 500
    return jsonify({"sectors": [dict(row) for row in rows]})


@bp.get("")
@jwt_required()
@require_permission("upload_tin_registration")
def list_tins():
    page_size = _page(request.args.get("page_size"), 25, 100)
    page = _page(request.args.get("page"), 1, 1_000_000)
    search = _value(request.args.get("search"))
    clauses, params = [], {}
    if search:
        clauses.append("(tr.tin LIKE :search OR tr.taxpayername LIKE :search OR tr.maintradename LIKE :search)")
        params["search"] = f"%{search}%"
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    try:
        total = int(db.session.execute(text(f"SELECT COUNT(*) FROM tin_registration_mst tr {where}"), params).scalar() or 0)
        total_pages = math.ceil(total / page_size) if total else 0
        page = min(page, total_pages) if total_pages else 1
        params.update(limit=page_size, offset=(page - 1) * page_size)
        rows = db.session.execute(text(f"""
            SELECT tr.tin, tr.taxpayername AS taxpayer_name, tr.maintradename AS trade_name,
                   tr.enterprisetype AS enterprise_type, tr.province, tr.status,
                   tr.sector_id
            FROM tin_registration_mst tr {where}
            ORDER BY tr.tin ASC LIMIT :limit OFFSET :offset
        """), params).mappings().all()
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Unable to load TIN Master records."}), 500
    return jsonify({"records": [dict(row) for row in rows], "page": page, "page_size": page_size,
                    "total_records": total, "total_pages": total_pages,
                    "has_next": page < total_pages, "has_previous": page > 1})


@bp.post("")
@jwt_required()
@require_permission("upload_tin_registration")
def create_tin():
    record, error = _record(request.get_json(silent=True) or {})
    if error:
        return jsonify({"message": error}), 400
    try:
        outcome, reason = _insert(record)
        if outcome != "inserted":
            db.session.rollback()
            return jsonify({"message": reason}), 409 if outcome == "duplicate_existing" else 400
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "TIN already exists."}), 409
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Unable to create TIN Master record."}), 500
    return jsonify({"message": "TIN Master record created successfully."}), 201


@bp.post("/import")
@jwt_required()
@require_permission("upload_tin_registration")
def import_tins():
    file_storage = request.files.get("file")
    if not file_storage:
        return jsonify({"message": "Select a TIN Master file."}), 400
    try:
        frame = _columns(_read_file(file_storage))
    except Exception as exc:
        return jsonify({"message": f"Invalid TIN Master file: {str(exc)}"}), 400
    summary = {"total_rows": len(frame.index), "inserted": 0, "duplicate_existing": 0,
               "duplicate_in_file": 0, "invalid": 0, "failed": 0, "sector_not_found": 0, "samples": []}
    seen = set()
    try:
        for index, raw in frame.iterrows():
            if not any(_value(raw.get(key)) for key in HEADERS):
                continue
            record, error = _record(raw)
            if error:
                summary["invalid"] += 1
                if len(summary["samples"]) < 20:
                    summary["samples"].append({"row": index + 2, "reason": error})
                continue
            if record["tin"] in seen:
                summary["duplicate_in_file"] += 1
                continue
            seen.add(record["tin"])
            outcome, reason = _insert(record)
            summary[outcome] += 1
            if outcome != "inserted" and len(summary["samples"]) < 20:
                summary["samples"].append({"row": index + 2, "reason": reason})
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "Import conflicted with a concurrent TIN change; no import was committed."}), 409
    except Exception:
        db.session.rollback()
        return jsonify({"message": "TIN Master import failed; no records were inserted."}), 500
    summary["message"] = "TIN Master import completed."
    return jsonify(summary)


@bp.put("/<path:tin>/status")
@jwt_required()
@require_permission("upload_tin_registration")
def update_status(tin):
    data = request.get_json(silent=True) or {}
    if not data or not set(data).issubset({"enterprisetype", "status"}):
        return jsonify({"message": "Only Enterprise Type and Status can be updated."}), 400
    enterprise_type = data.get("enterprisetype")
    taxpayer_type = None
    if enterprise_type is not None:
        enterprise_type = ENTERPRISE_TYPE_MAP.get(_value(enterprise_type).upper())
        if enterprise_type is None:
            return jsonify({"message": "Enterprise Type must be Company, Individual, or Government."}), 400
        taxpayer_type = TAXPAYER_TYPE_MAP[enterprise_type]
    status = _value(data.get("status")).upper() if "status" in data else None
    if status is not None and status not in ALLOWED_STATUS:
        return jsonify({"message": "Status must be ACTIVE or INACTIVE."}), 400
    clean_tin = _tin(tin)
    try:
        assignments = []
        params = {"tin": clean_tin}
        if enterprise_type is not None:
            assignments.extend(["enterprisetype = :enterprise_type", "taxpayertype = :taxpayer_type"])
            params.update(enterprise_type=enterprise_type, taxpayer_type=taxpayer_type)
        if status is not None:
            assignments.append("status = :status")
            params["status"] = status
        result = db.session.execute(text(f"UPDATE tin_registration_mst SET {', '.join(assignments)} WHERE normalized_tin = :tin OR TRIM(tin) = :tin"), params)
        if not result.rowcount:
            db.session.rollback()
            return jsonify({"message": "TIN not found."}), 404
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Unable to update TIN status."}), 500
    return jsonify({"message": "TIN record updated successfully.", "status": status, "enterprisetype": enterprise_type, "taxpayertype": taxpayer_type})
