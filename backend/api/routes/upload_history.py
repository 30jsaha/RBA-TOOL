from flask import Blueprint, Response, request, jsonify, make_response, send_file, send_from_directory, current_app, stream_with_context, url_for
from flask_jwt_extended import jwt_required
from sqlalchemy import text
from ..extensions import db
from utils.auth_helper import get_authenticated_user_id
from utils.file_utils import get_backend_storage_dir, get_backend_upload_dir
from utils.rbac import get_current_security_context, has_any_permission
from datetime import datetime
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import csv
import io
import os
from pathlib import Path

bp = Blueprint("upload_history", __name__, url_prefix="/api/upload-history")


def _permission_denied_response():
    return jsonify({"success": False, "message": "Permission denied"}), 403


def _normalized_authenticated_user_id():
    user_id = get_authenticated_user_id()
    try:
        return int(user_id) if user_id is not None else None
    except (TypeError, ValueError):
        return None


def _upload_history_supports_user_ownership() -> bool:
    try:
        return (
            db.session.execute(
                text(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'upload_log'
                      AND COLUMN_NAME = 'user_id'
                    """
                )
            ).scalar()
            or 0
        ) > 0
    except Exception:
        return False


def _can_view_global_upload_history() -> bool:
    context = get_current_security_context()
    role_names = {
        str(role.get("name", "")).upper()
        for role in (context.get("roles") or [])
        if isinstance(role, dict)
    }
    if "ADMIN" in role_names:
        return True

    return has_any_permission(
        "settings.users",
        "settings.roles",
        "settings.role_permissions",
        "settings.reset_db",
    )


def _upload_history_authorization_scope():
    return {
        "is_global": _can_view_global_upload_history(),
        "user_id": _normalized_authenticated_user_id(),
        "has_user_id_column": _upload_history_supports_user_ownership(),
    }


def _apply_upload_history_scope(where_clauses, params, table_alias="upload_log"):
    scope = _upload_history_authorization_scope()
    if scope["is_global"]:
        return scope

    if scope["user_id"] is None:
        where_clauses.append("1 = 0")
        return scope

    if scope["has_user_id_column"]:
        where_clauses.append(f"{table_alias}.user_id = :current_user_id")
        params["current_user_id"] = scope["user_id"]
        return scope

    where_clauses.append("1 = 0")
    return scope


def _parse_date(value: str):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


# ======================================================
# POST /api/upload-history
# ======================================================
@bp.route("/details", methods=["OPTIONS"])
def list_upload_history_with_user_roles_options():
    return ("", 200)


@bp.post("/")
@jwt_required()
def add_upload_history():
    """
    Add a record when a file is uploaded.
    Expected JSON body:
    {
        "file_name": "gst_report_2025.xlsx",
        "tax_parameter": "GST"
    }
    """
    data = request.get_json() or {}

    file_name = data.get("file_name")
    tax_parameter = data.get("tax_parameter")

    if not file_name or not tax_parameter:
        return jsonify({"error": "Both 'file_name' and 'tax_parameter' are required"}), 400

    try:
        user_id = get_authenticated_user_id()
        # NULL-safe: only include user_id if the column exists (never break existing DBs).
        has_user_id = _upload_history_supports_user_ownership()

        if has_user_id:
            db.session.execute(
                text(
                    """
                    INSERT INTO upload_log (tax_type, filename, status, pipeline_run, uploaded_at, user_id)
                    VALUES (:tax_type, :filename, 'Success', 0, NOW(), :user_id)
                    """
                ),
                {"tax_type": str(tax_parameter).upper(), "filename": str(file_name), "user_id": user_id},
            )
        else:
            db.session.execute(
                text(
                    """
                    INSERT INTO upload_log (tax_type, filename, status, pipeline_run, uploaded_at)
                    VALUES (:tax_type, :filename, 'Success', 0, NOW())
                    """
                ),
                {"tax_type": str(tax_parameter).upper(), "filename": str(file_name)},
            )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

    return jsonify({"message": "Upload history recorded successfully"}), 201


# ======================================================
# GET /api/upload-history
# ======================================================
@bp.get("/")
@jwt_required()
def list_upload_history():
    """
    List all uploaded files sorted by date (latest first)
    """
    params = {}
    where = []
    _apply_upload_history_scope(where, params, table_alias="upload_log")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    rows = db.session.execute(
        text(
            f"""
            SELECT
                id,
                filename AS file_name,
                UPPER(COALESCE(tax_type, '')) AS tax_parameter,
                uploaded_at
            FROM upload_log
            {where_sql}
            ORDER BY uploaded_at DESC
            """
        ),
        params,
    ).fetchall()
    return jsonify(
        [
            {
                "id": r.id,
                "file_name": r.file_name,
                "tax_parameter": r.tax_parameter,
                "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None,
            }
            for r in rows
        ]
    ), 200


# ======================================================
# GET /api/upload-history/<tax_parameter>
# ======================================================
@bp.get("/<string:tax_parameter>")
@jwt_required()
def list_uploads_by_type(tax_parameter):
    """
    List uploaded files by tax type: GST, SWT, CIT
    """
    params = {"tax_type": str(tax_parameter).upper()}
    where = ["UPPER(COALESCE(upload_log.tax_type, '')) = :tax_type"]
    _apply_upload_history_scope(where, params, table_alias="upload_log")
    where_sql = "WHERE " + " AND ".join(where)

    rows = db.session.execute(
        text(
            f"""
            SELECT
                id,
                filename AS file_name,
                UPPER(COALESCE(tax_type, '')) AS tax_parameter,
                uploaded_at
            FROM upload_log
            {where_sql}
            ORDER BY uploaded_at DESC
            """
        ),
        params,
    ).fetchall()
    return jsonify(
        [
            {
                "id": r.id,
                "file_name": r.file_name,
                "tax_parameter": r.tax_parameter,
                "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None,
            }
            for r in rows
        ]
    ), 200


# ======================================================
# GET /api/upload-history/details
# Supports:
# /details?tax_type=gst|swt|cit|all
# /details?page=1&limit=50
# /details?search=filename
# ======================================================
# ======================================================
# GET /api/upload-history/details
# Supports:
# /details?tax_type=gst|swt|cit|all
# /details?page=1&limit=50
# /details?search=filename
# ======================================================
@bp.get("/details")
@jwt_required()
def list_upload_history_with_user_roles():
    tax_filter = request.args.get("tax_type")      # gst | swt | cit | all | None
    search = request.args.get("search")            # filename
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 50))
    offset = (page - 1) * limit

    params = {"limit": limit, "offset": offset}
    where = []
    _apply_upload_history_scope(where, params, table_alias="ul")

    if tax_filter and tax_filter.lower() != "all":
        where.append("LOWER(ul.tax_type) = :tax_type")
        params["tax_type"] = tax_filter.lower()

    if search:
        where.append("ul.filename LIKE :search")
        params["search"] = f"%{search}%"

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    # Fixed query with proper joins to users and user_roles tables
    query = text(f"""
        SELECT
            ul.id AS upload_id,
            ul.filename AS file_name,
            COALESCE(u.full_name, 'Unknown User') AS uploaded_by,
            COALESCE(r.name, 'No Role Assigned') AS role,
            UPPER(COALESCE(ul.tax_type, '')) AS tax_parameter,
            DATE(ul.uploaded_at) AS date,
            TIME(ul.uploaded_at) AS time,
            NULL AS tin,
            NULL AS taxpayer_name,
            NULL AS taxpayer_type,
            NULL AS segmentation,
            COALESCE(ul.row_count, 0) AS total_sales,
            0 AS gst_payable,
            0 AS gst_refundable,
            COALESCE(ul.status, 'Unknown') AS fraud,
            COALESCE(ul.error_message, '') AS fraud_reason,
            'Normal' AS risk_type
        FROM upload_log ul
        LEFT JOIN users u ON ul.user_id = u.id
        LEFT JOIN user_roles ur ON u.id = ur.user_id
        LEFT JOIN roles r ON ur.role_id = r.id
        {where_sql}
        ORDER BY ul.uploaded_at DESC
        LIMIT :limit OFFSET :offset
    """)

    try:
        rows = db.session.execute(query, params).fetchall()
    except Exception as e:
        return jsonify({"status": "error", "message": "Database query failed", "error": str(e)}), 500

    if not rows:
        return jsonify({"status": "error", "message": "No data found"}), 404

    data = [
        {
            "upload_id": r[0],
            "file_name": r[1],
            "uploaded_by": r[2],
            "role": r[3],
            "tax_parameter": r[4],
            "date": str(r[5]),
            "time": str(r[6]),
            "Tin": r[7],
            "Taxpayer_Name": r[8],
            "Type": r[9],
            "Segmentation": r[10],
            "Total_Sales": r[11],
            "Gst_Payable": r[12],
            "Gst_Refundable": r[13],
            "Fraud": r[14],
            "Fraud_Reason": r[15],
            "Risk_Type": r[16],
        }
        for r in rows
    ]

    # Also get total count for pagination
    count_query = text(f"""
        SELECT COUNT(*) as total
        FROM upload_log ul
        LEFT JOIN users u ON ul.user_id = u.id
        LEFT JOIN user_roles ur ON u.id = ur.user_id
        LEFT JOIN roles r ON ur.role_id = r.id
        {where_sql}
    """)
    
    total_count = db.session.execute(count_query, params).scalar() or 0
    total_pages = (total_count + limit - 1) // limit

    return jsonify({
        "status": "success", 
        "page": page, 
        "limit": limit,
        "total_records": total_count,
        "total_pages": total_pages,
        "records": data
    }), 200


def _upload_history_raw_folder(tax_type):
    normalized = str(tax_type or "").strip().upper()
    folder_name = {
        "GST": "gst",
        "SWT": "swt",
        "CIT": "cit",
    }.get(normalized)
    if not folder_name:
        return None
    return (Path(__file__).resolve().parents[2] / folder_name / "final_output").resolve()


def _allowed_upload_history_roots():
    backend_root = Path(__file__).resolve().parents[2]
    return [
        Path(get_backend_upload_dir()).resolve(),
        Path(get_backend_storage_dir('outputs')).resolve(),
        (backend_root / 'gst' / 'data').resolve(),
        (backend_root / 'swt' / 'Data').resolve(),
        (backend_root / 'cit' / 'data').resolve(),
    ]


def _is_allowed_upload_history_download_path(resolved_path: Path) -> bool:
    try:
        candidate = resolved_path.resolve(strict=False)
    except Exception:
        return False
    for allowed_root in _allowed_upload_history_roots():
        try:
            candidate.relative_to(allowed_root)
            return True
        except ValueError:
            continue
    return False


@bp.get("/raw-file/<int:upload_id>")
@jwt_required()
def download_upload_history_raw_file(upload_id):
    row = None
    filepath = ""
    filename = ""
    tax_type = ""
    resolved_path = None

    try:
        params = {"upload_id": upload_id}
        where = ["id = :upload_id"]
        scope = _apply_upload_history_scope(where, params, table_alias="upload_log")
        where_sql = "WHERE " + " AND ".join(where)

        row = db.session.execute(
            text(
                f"""
                SELECT id, filename, filepath, UPPER(COALESCE(tax_type, '')) AS tax_type
                FROM upload_log
                {where_sql}
                LIMIT 1
                """
            ),
            params,
        ).mappings().first()

        if not row:
            if not scope["is_global"] and scope["has_user_id_column"] and scope["user_id"] is not None:
                exists = db.session.execute(
                    text(
                        """
                        SELECT 1
                        FROM upload_log
                        WHERE id = :upload_id
                        LIMIT 1
                        """
                    ),
                    {"upload_id": upload_id},
                ).scalar()
                if exists:
                    return _permission_denied_response()
            return jsonify({"message": "Upload record not found."}), 404

        tax_type = str(row.get("tax_type") or "").strip().upper()
        filename = str(row.get("filename") or "").strip()
        filepath = str(row.get("filepath") or "").strip()

        if not filepath:
            return jsonify({"message": "File path is missing."}), 404

        resolved_path = Path(filepath).expanduser().resolve(strict=False)
        file_exists = os.path.isfile(resolved_path)
        current_app.logger.info(
            "Upload history raw file download lookup: upload_id=%s tax_type=%s filepath=%s filename=%s resolved_absolute_path=%s exists=%s",
            upload_id,
            tax_type,
            filepath,
            filename,
            str(resolved_path),
            file_exists,
        )

        if not file_exists:
            return jsonify({"message": "Raw file does not exist on server."}), 404
        if not _is_allowed_upload_history_download_path(resolved_path):
            return jsonify({"message": "File not available for download."}), 403

        return send_file(
            resolved_path,
            as_attachment=True,
            download_name=filename or resolved_path.name,
            mimetype="text/csv",
            conditional=True,
        )
    except Exception:
        current_app.logger.exception(
            "Unable to download raw file. upload_id=%s tax_type=%s filepath=%s filename=%s resolved_absolute_path=%s",
            upload_id,
            tax_type,
            filepath,
            filename,
            str(resolved_path) if resolved_path is not None else None,
        )
        return jsonify({"message": "Unable to download raw file."}), 500

def _recent_uploads_output_dir():
    from pathlib import Path

    return Path("/var/www/rbatool/backend/outputs")


def _recent_uploads_download_serializer():
    secret = (
        current_app.config.get("JWT_SECRET_KEY")
        or current_app.config.get("SECRET_KEY")
        or "recent-uploads-download"
    )
    return URLSafeTimedSerializer(secret_key=secret, salt="recent-uploads-csv")


def _build_recent_uploads_download_token(filename):
    return _recent_uploads_download_serializer().dumps({"filename": filename})


def _verify_recent_uploads_download_token(filename, token, max_age=300):
    if not token:
        return False

    try:
        payload = _recent_uploads_download_serializer().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return False

    return payload.get("filename") == filename


@bp.get("/recent-uploads/downloads/<path:filename>")
@jwt_required()
def download_recent_uploads_csv_file(filename):
    from pathlib import Path

    safe_name = Path(filename).name
    if safe_name != filename or not safe_name.lower().endswith(".csv"):
        return jsonify({"message": "File not found"}), 404

    token = request.args.get("token")
    if not _verify_recent_uploads_download_token(safe_name, token):
        return jsonify({"message": "File not found"}), 404

    output_dir = _recent_uploads_output_dir()
    file_path = output_dir / safe_name
    if not file_path.is_file():
        return jsonify({"message": "File not found"}), 404

    return send_from_directory(
        output_dir,
        safe_name,
        as_attachment=True,
        mimetype="text/csv",
        download_name=safe_name,
    )


@bp.get("/recent-uploads/download-csv")
@jwt_required()
def download_recent_uploads_csv():
    from pathlib import Path
    import pandas as pd

    tax_type = (request.args.get("tax_type") or "all").lower()
    search = (request.args.get("search") or "").strip()
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    sd = _parse_date(start_date) if start_date else None
    ed = _parse_date(end_date) if end_date else None

    start_year = None
    start_month = None
    end_year = None
    end_month = None
    if sd and ed:
        start_year = int(sd.year)
        start_month = int(sd.month)
        end_year = int(ed.year)
        end_month = int(ed.month)

        start_ym = (start_year * 100) + start_month
        end_ym = (end_year * 100) + end_month
        if start_ym > end_ym:
            start_year, end_year = end_year, start_year
            start_month, end_month = end_month, start_month

    params = {}
    where = []

    if (
        start_year is not None
        and start_month is not None
        and end_year is not None
        and end_month is not None
    ):
        where.append("""
            (
                (
                    tax_type = 'cit'
                    AND tax_period_year BETWEEN :start_year AND :end_year
                )
                OR
                (
                    tax_type <> 'cit'
                    AND (
                        (
                            tax_period_year > :start_year
                            OR (
                                tax_period_year = :start_year
                                AND tax_period_month >= :start_month
                            )
                        )
                        AND
                        (
                            tax_period_year < :end_year
                            OR (
                                tax_period_year = :end_year
                                AND tax_period_month <= :end_month
                            )
                        )
                    )
                )
            )
        """)
        params["start_year"] = start_year
        params["start_month"] = start_month
        params["end_year"] = end_year
        params["end_month"] = end_month

    if search:
        where.append("(tin LIKE :s OR taxpayer_name LIKE :s OR CAST(tax_period_year AS CHAR(10)) LIKE :s)")
        params["s"] = f"%{search}%"

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    union_sql = """
        SELECT
            'gst' AS tax_type,
            CAST(tin AS CHAR(30)) AS tin,
            COALESCE(NULLIF(TRIM(taxpayer_name), ''), 'Unknown') AS taxpayer_name,
            COALESCE(NULLIF(TRIM(taxpayer_type), ''), 'Unknown') AS taxpayer_type,
            COALESCE(tax_account_number, 0) AS tax_account_number,
            COALESCE(is_fraud, 0) AS is_fraud,
            tax_period_month,
            tax_period_year,
            COALESCE(total_sales_income, 0) AS total_sales_income,
            COALESCE(gst_payable, 0) AS gst_payable,
            COALESCE(exempt_sales, 0) AS exempt_sales,
            COALESCE(zero_rated_sales, 0) AS zero_rated_sales,
            COALESCE(gst_paid_on_inputs, 0) AS total_purchase,
            COALESCE(gst_payable, 0) AS net_vat,
            COALESCE(gst_refundable, 0) AS refund_approved,
            COALESCE(explanation, '') AS explanation,
            NULL AS employees_on_payroll,
            NULL AS employees_paid_swt,
            NULL AS total_salary_wages_paid,
            NULL AS total_swt_tax_deducted,
            NULL AS total_gross_income,
            NULL AS total_tax_payable,
            NULL AS predicted_fraud
        FROM gst_fraud_justification

        UNION ALL

        SELECT
            'swt' AS tax_type,
            CAST(tin AS CHAR(30)) AS tin,
            COALESCE(NULLIF(TRIM(taxpayer_name), ''), 'Unknown') AS taxpayer_name,
            'Salary/Wage' AS taxpayer_type,
            COALESCE(tax_account_number, 0) AS tax_account_number,
            CASE
                WHEN LOWER(COALESCE(predicted_fraud, '')) = 'fraud'
                THEN 1 ELSE 0
            END AS is_fraud,
            tax_period_month,
            tax_period_year,
            NULL AS total_sales_income,
            NULL AS gst_payable,
            NULL AS exempt_sales,
            NULL AS zero_rated_sales,
            NULL AS total_purchase,
            NULL AS net_vat,
            NULL AS refund_approved,
            COALESCE(explanation, '') AS explanation,
            COALESCE(employees_on_payroll, 0) AS employees_on_payroll,
            COALESCE(employees_paid_swt, 0) AS employees_paid_swt,
            COALESCE(total_salary_wages_paid, 0) AS total_salary_wages_paid,
            COALESCE(total_swt_tax_deducted, 0) AS total_swt_tax_deducted,
            NULL AS total_gross_income,
            NULL AS total_tax_payable,
            COALESCE(predicted_fraud, '') AS predicted_fraud
        FROM swt_fraud_justification

        UNION ALL

        SELECT
            'cit' AS tax_type,
            CAST(tin AS CHAR(30)) AS tin,
            COALESCE(NULLIF(TRIM(taxpayer), ''), 'Unknown') AS taxpayer_name,
            'CIT' AS taxpayer_type,
            COALESCE(tax_account_no, 0) AS tax_account_number,
            CASE
                WHEN LOWER(COALESCE(predicted_fraud, '')) = 'fraud'
                THEN 1 ELSE 0
            END AS is_fraud,
            NULL AS tax_period_month,
            tax_period_year,
            NULL AS total_sales_income,
            NULL AS gst_payable,
            NULL AS exempt_sales,
            NULL AS zero_rated_sales,
            NULL AS total_purchase,
            NULL AS net_vat,
            NULL AS refund_approved,
            NULL AS explanation,
            NULL AS employees_on_payroll,
            NULL AS employees_paid_swt,
            NULL AS total_salary_wages_paid,
            NULL AS total_swt_tax_deducted,
            COALESCE(total_gross_income, 0) AS total_gross_income,
            COALESCE(total_tax_payable, 0) AS total_tax_payable,
            COALESCE(predicted_fraud, '') AS predicted_fraud
        FROM cit_fraud_justification
    """

    tax_filter_sql = ""
    if tax_type in ("gst", "swt", "cit"):
        tax_filter_sql = "WHERE tax_type = :tax_type"
        params["tax_type"] = tax_type

    sql = text(f"""
        SELECT
            tax_type,
            tin,
            taxpayer_name,
            taxpayer_type,
            tax_account_number,
            is_fraud,
            tax_period_month,
            tax_period_year,
            total_sales_income,
            gst_payable,
            exempt_sales,
            zero_rated_sales,
            total_purchase,
            net_vat,
            refund_approved,
            explanation,
            employees_on_payroll,
            employees_paid_swt,
            total_salary_wages_paid,
            total_swt_tax_deducted,
            total_gross_income,
            total_tax_payable,
            predicted_fraud
        FROM (
            {union_sql}
        ) x
        {tax_filter_sql}
    """)

    final_sql = text(f"""
        SELECT
            tax_type,
            tin,
            taxpayer_name,
            taxpayer_type,
            tax_account_number,
            is_fraud,
            tax_period_month,
            tax_period_year,
            total_sales_income,
            gst_payable,
            exempt_sales,
            zero_rated_sales,
            total_purchase,
            net_vat,
            refund_approved,
            explanation,
            employees_on_payroll,
            employees_paid_swt,
            total_salary_wages_paid,
            total_swt_tax_deducted,
            total_gross_income,
            total_tax_payable,
            predicted_fraud
        FROM (
            {sql.text}
        ) y
        {where_sql}
        ORDER BY tax_period_year DESC, COALESCE(tax_period_month, 12) DESC, tin
    """)

    all_columns = [
        "tax_type",
        "tin",
        "taxpayer_name",
        "taxpayer_type",
        "tax_account_number",
        "is_fraud",
        "tax_period_month",
        "tax_period_year",
        "total_sales_income",
        "gst_payable",
        "exempt_sales",
        "zero_rated_sales",
        "total_purchase",
        "net_vat",
        "refund_approved",
        "explanation",
        "employees_on_payroll",
        "employees_paid_swt",
        "total_salary_wages_paid",
        "total_swt_tax_deducted",
        "total_gross_income",
        "total_tax_payable",
        "predicted_fraud",
    ]
    gst_columns = [
        "tax_type",
        "tin",
        "taxpayer_name",
        "taxpayer_type",
        "tax_account_number",
        "is_fraud",
        "tax_period_month",
        "tax_period_year",
        "total_sales_income",
        "gst_payable",
        "exempt_sales",
        "zero_rated_sales",
        "total_purchase",
        "net_vat",
        "refund_approved",
        "explanation",
    ]
    swt_columns = [
        "tax_type",
        "tin",
        "taxpayer_name",
        "taxpayer_type",
        "tax_account_number",
        "is_fraud",
        "tax_period_month",
        "tax_period_year",
        "employees_on_payroll",
        "employees_paid_swt",
        "total_salary_wages_paid",
        "total_swt_tax_deducted",
        "explanation",
        "predicted_fraud",
    ]
    cit_columns = [
        "tax_type",
        "tin",
        "taxpayer_name",
        "taxpayer_type",
        "tax_account_number",
        "is_fraud",
        "tax_period_year",
        "total_gross_income",
        "total_tax_payable",
        "predicted_fraud",
    ]
    csv_columns = {
        "gst": gst_columns,
        "swt": swt_columns,
        "cit": cit_columns,
    }.get(tax_type, all_columns)

    filename_start = sd.strftime("%Y-%m-%d") if sd else "2015-06-01"
    filename_end = ed.strftime("%Y-%m-%d") if ed else datetime.now().strftime("%Y-%m-%d")
    filename = f"recent_uploads_{tax_type}_{filename_start}_to_{filename_end}.csv"

    def generate_csv():
        connection = None
        try:
            connection = db.engine.connect()
            wrote_rows = False
            first_chunk = True

            for chunk in pd.read_sql_query(
                final_sql,
                connection,
                params=params,
                chunksize=5000,
            ):
                export_chunk = chunk.reindex(columns=all_columns)[csv_columns]
                buffer = io.StringIO()
                export_chunk.to_csv(
                    buffer,
                    index=False,
                    header=first_chunk,
                )
                yield buffer.getvalue()
                buffer.close()
                wrote_rows = True
                first_chunk = False

            if not wrote_rows:
                buffer = io.StringIO()
                pd.DataFrame(columns=csv_columns).to_csv(
                    buffer,
                    index=False,
                    header=True,
                )
                yield buffer.getvalue()
                buffer.close()
        finally:
            if connection is not None:
                connection.close()

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
    }
    return Response(stream_with_context(generate_csv()), mimetype="text/csv", headers=headers)


