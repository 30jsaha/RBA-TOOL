from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required
from sqlalchemy import text
from datetime import datetime
from ..extensions import db
from .dashboard_common import get_date_filter
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

bp = Blueprint("predicted_records", __name__, url_prefix="/api/predicted-records")


def _parse_date(value: str):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _table_has_column(table_name: str, column_name: str) -> bool:
    try:
        row = db.session.execute(
            text(
                """
                SELECT COUNT(*) AS c
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = :t
                  AND column_name = :c
                """
            ),
            {"t": table_name, "c": column_name},
        ).fetchone()
        return bool(row and int(row[0] or 0) > 0)
    except Exception:
        return False


# ============================================================
# Helper: Determine date range
# ============================================================
def get_date_range():
    """
    Handles '1m', '3m', '6m', '1y', and 'custom' ranges dynamically.
    Defaults to the current month.
    Returns (start_year, start_month, end_year, end_month)
    """
    now = datetime.now()
    range_type = request.args.get("range_type", "1m")  # default: 1 Month
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    if range_type == "custom" and start_date and end_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            start, end = now.replace(day=1), now
    elif range_type == "3m":
        start = now - relativedelta(months=2)
        end = now
    elif range_type == "6m":
        start = now - relativedelta(months=5)
        end = now
    elif range_type == "1y":
        start = now - relativedelta(years=1)
        end = now
    else:
        # Default: current month only
        start = now.replace(day=1)
        end = now

    return start.year, start.month, end.year, end.month


def _safe_int(value, default, minimum=1, maximum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default

    if minimum is not None:
        parsed = max(parsed, minimum)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def _get_tax_records_order_by(sort_by: str, sort_order: str) -> str:
    direction = "ASC" if (sort_order or "").lower() == "asc" else "DESC"
    sortable_columns = {
        "tin": "tin",
        "taxpayer_name": "taxpayer_name",
        "risk_type": "risk_type",
        "flagged": "flagged",
        "is_fraud": "is_fraud",
        "fraud_reason": "fraud_reason",
        "total_sales_income": "total_sales_income",
        "gst_payable": "gst_payable",
        "segment_label": "segment_label",
        "tax_account_number": "tax_account_number",
        "tax_period_year": "tax_period_year",
        "tax_period_month": "COALESCE(tax_period_month, 12)",
    }

    sort_expr = sortable_columns.get((sort_by or "").strip().lower())
    if not sort_expr:
        return "tax_period_year DESC, COALESCE(tax_period_month, 12) DESC, tin ASC"

    return f"{sort_expr} {direction}, tax_period_year DESC, COALESCE(tax_period_month, 12) DESC, tin ASC"


def _normalize_tax_type(value):
    return (value or "gst").lower().strip()


def _get_taxpayer_profile_params():
    taxtype = _normalize_tax_type(request.args.get("taxtype"))
    start_year, start_month, end_year, end_month = get_date_range()
    params = {
        "start_ym": (start_year * 100) + start_month,
        "end_ym": (end_year * 100) + end_month,
    }
    if taxtype == "cit":
        params["start_year"] = start_year
        params["end_year"] = end_year
    return taxtype, params


def _taxpayer_profile_base_query(taxtype):
    if taxtype == "gst":
        return """
            SELECT
                CAST(pr.tin AS CHAR(30)) AS tin,
                COALESCE(NULLIF(TRIM(pr.taxpayer_name), ''), 'Unknown') AS taxpayer_name,
                'Normal' AS risk_type,
                COALESCE(pr.is_fraud, 0) AS is_fraud,
                CASE
                    WHEN COALESCE(pr.is_fraud, 0) = 1 THEN 1 ELSE 0
                END AS flagged,
                CASE
                    WHEN COALESCE(pr.is_fraud, 0) = 1
                    THEN COALESCE(NULLIF(TRIM(pr.explanation), ''), '')
                    ELSE ''
                END AS fraud_reason,
                COALESCE(pr.total_sales_income, 0) AS total_sales_income,
                COALESCE(pr.gst_payable, 0) AS gst_payable,
                COALESCE(NULLIF(TRIM(pr.taxpayer_type), ''), 'Unknown') AS segment_label,
                pr.tax_period_year,
                pr.tax_period_month,
                COALESCE(pr.tax_account_number, 0) AS tax_account_number
            FROM gst_fraud_justification pr
            WHERE ((pr.tax_period_year * 100) + pr.tax_period_month) BETWEEN :start_ym AND :end_ym
        """

    if taxtype == "swt":
        return """
            SELECT
                CAST(pr.tin AS CHAR(30)) AS tin,
                COALESCE(NULLIF(TRIM(pr.taxpayer_name), ''), 'Unknown') AS taxpayer_name,
                'Normal' AS risk_type,
                CASE
                    WHEN LOWER(COALESCE(pr.predicted_fraud, '')) = 'fraud' THEN 1 ELSE 0
                END AS is_fraud,
                CASE
                    WHEN LOWER(COALESCE(pr.predicted_fraud, '')) = 'fraud' THEN 1 ELSE 0
                END AS flagged,
                CASE
                    WHEN LOWER(COALESCE(pr.predicted_fraud, '')) = 'fraud'
                    THEN COALESCE(NULLIF(TRIM(pr.explanation), ''), '')
                    ELSE ''
                END AS fraud_reason,
                COALESCE(pr.total_salary_wages_paid, 0) AS total_sales_income,
                COALESCE(pr.total_swt_tax_deducted, 0) AS gst_payable,
                'Salary/Wage' AS segment_label,
                pr.tax_period_year,
                pr.tax_period_month,
                COALESCE(pr.tax_account_number, 0) AS tax_account_number
            FROM swt_fraud_justification pr
            WHERE ((pr.tax_period_year * 100) + pr.tax_period_month) BETWEEN :start_ym AND :end_ym
        """

    return """
        SELECT
            CAST(pr.tin AS CHAR(30)) AS tin,
            COALESCE(NULLIF(TRIM(pr.taxpayer), ''), 'Unknown') AS taxpayer_name,
            'Normal' AS risk_type,
            CASE
                WHEN LOWER(COALESCE(pr.predicted_fraud, '')) = 'fraud' THEN 1 ELSE 0
            END AS is_fraud,
            CASE
                WHEN LOWER(COALESCE(pr.predicted_fraud, '')) = 'fraud' THEN 1 ELSE 0
            END AS flagged,
            CASE
                WHEN LOWER(COALESCE(pr.predicted_fraud, '')) = 'fraud' THEN COALESCE(NULLIF(TRIM(pr.Justification), ''), '')
                ELSE ''
            END AS fraud_reason,
            COALESCE(pr.total_gross_income, 0) AS total_sales_income,
            COALESCE(pr.total_tax_payable, 0) AS gst_payable,
            'CIT' AS segment_label,
            pr.tax_period_year,
            NULL AS tax_period_month,
            COALESCE(pr.tax_account_no, 0) AS tax_account_number
        FROM cit_fraud_justification pr
        WHERE pr.tax_period_year BETWEEN :start_year AND :end_year
    """


def _serialize_tax_record(record, taxtype=None):
    result = dict(record)
    if taxtype:
        result["row_key"] = (
            f"{taxtype}-{result.get('tin') or ''}-"
            f"{result.get('tax_period_year') or ''}-"
            f"{result.get('tax_period_month') if result.get('tax_period_month') is not None else 'annual'}"
        )
    return result


@bp.route("/recent-uploads", methods=["OPTIONS"])
def recent_uploads_options():
    return ("", 200)


@bp.get("/recent-uploads")
@jwt_required()
def recent_uploads():
    tax_type = (request.args.get("tax_type") or "all").lower()
    search = (request.args.get("search") or "").strip()
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    page = max(int(request.args.get("page", 1) or 1), 1)
    per_page = max(int(request.args.get("per_page", 2000) or 2000), 1)
    offset = (page - 1) * per_page

    sd = _parse_date(start_date) if start_date else None
    ed = _parse_date(end_date) if end_date else None

    start_ym = None
    end_ym = None
    if sd and ed:
        start_ym = (sd.year * 100) + sd.month
        end_ym = (ed.year * 100) + ed.month
        if start_ym > end_ym:
            start_ym, end_ym = end_ym, start_ym

    params = {}
    where = []

    if start_ym is not None and end_ym is not None:
        where.append("((tax_period_year * 100) + COALESCE(tax_period_month, 12)) BETWEEN :start_ym AND :end_ym")
        params["start_ym"] = int(start_ym)
        params["end_ym"] = int(end_ym)

    if search:
        where.append(
            "(tin LIKE :s OR taxpayer_name LIKE :s OR CAST(tax_period_year AS CHAR(10)) LIKE :s)"
        )
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
            tax_period_year
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
            tax_period_year
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
            tax_period_year
        FROM cit_fraud_justification
    """

    tax_filter_sql = ""
    if tax_type in ("gst", "swt", "cit"):
        tax_filter_sql = "WHERE tax_type = :tax_type"
        params["tax_type"] = tax_type

    sql = text(f"""
        SELECT
            tin,
            taxpayer_name,
            taxpayer_type,
            tax_account_number,
            is_fraud,
            tax_period_month,
            tax_period_year
        FROM (
            {union_sql}
        ) x
        {tax_filter_sql}
    """)

    final_sql = text(f"""
        SELECT
            tin,
            taxpayer_name,
            taxpayer_type,
            tax_account_number,
            is_fraud,
            tax_period_month,
            tax_period_year
        FROM (
            {sql.text}
        ) y
        {where_sql}
        ORDER BY tax_period_year DESC, COALESCE(tax_period_month, 12) DESC, tin
        LIMIT :limit OFFSET :offset
    """)

    count_sql = text(f"""
        SELECT COUNT(*) AS total_records
        FROM (
            {sql.text}
        ) y
        {where_sql}
    """)

    try:
        params["limit"] = per_page
        params["offset"] = offset

        total_records = int(
            (db.session.execute(count_sql, params).mappings().first() or {}).get("total_records") or 0
        )
        rows = db.session.execute(final_sql, params).mappings().all()
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"message": str(e), "records": [], "total_records": 0, "total_pages": 1}), 500

    records = [
        {
            "tin": r.get("tin") or "",
            "taxpayer_name": r.get("taxpayer_name") or "Unknown",
            "taxpayer_type": r.get("taxpayer_type") or "Unknown",
            "tax_account_number": r.get("tax_account_number"),
            "is_fraud": int(r.get("is_fraud") or 0),
            "tax_period_month": r.get("tax_period_month"),
            "tax_period_year": r.get("tax_period_year"),
        }
        for r in rows
    ]

    return jsonify(
        {
            "records": records,
            "total_records": total_records,
            "total_pages": max((total_records + per_page - 1) // per_page, 1),
            "current_page": page,
            "per_page": per_page,
            "date_range": {
                "start_date": start_date,
                "end_date": end_date,
            },
        }
    )


@bp.route("/all-tax-records", methods=["OPTIONS"])
def all_tax_records_options():
    return ("", 200)


@bp.get("/all-tax-records")
@jwt_required()
def all_tax_records():

    taxtype, params = _get_taxpayer_profile_params()
    search = (request.args.get("search") or "").strip()
    page = _safe_int(request.args.get("page", 1), 1, minimum=1)
    page_size = _safe_int(
        request.args.get("page_size", request.args.get("per_page", 100)),
        100,
        minimum=1,
        maximum=1000,
    )
    sort_by = (request.args.get("sort_by") or "").strip()
    sort_order = (request.args.get("sort_order") or "desc").strip()

    if taxtype not in ("gst", "swt", "cit"):
        return jsonify({
            "status": "error",
            "message": "Invalid taxtype",
            "records": []
        }), 400

    offset = (page - 1) * page_size
    order_by_sql = _get_tax_records_order_by(sort_by, sort_order)
    where_clauses = []

    if search:
        where_clauses.append("""
            (
                tin LIKE :search
                OR taxpayer_name LIKE :search
                OR CAST(tax_period_year AS CHAR(10)) LIKE :search
                OR CAST(COALESCE(tax_period_month, 0) AS CHAR(2)) LIKE :search
                OR fraud_reason LIKE :search
            )
        """)
        params["search"] = f"%{search}%"

    base_query = _taxpayer_profile_base_query(taxtype)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    count_sql = text(f"""
        SELECT COUNT(*) AS total_records
        FROM (
            {base_query}
        ) x
        {where_sql}
    """)

    final_sql = text(f"""
        SELECT *
        FROM (
            {base_query}
        ) x
        {where_sql}
        ORDER BY {order_by_sql}
        LIMIT :limit OFFSET :offset
    """)

    try:
        total_records = int(
            (db.session.execute(count_sql, params).mappings().first() or {}).get("total_records") or 0
        )
        rows = db.session.execute(
            final_sql,
            {
                **params,
                "limit": page_size,
                "offset": offset,
            }
        ).mappings().all()

    except Exception as e:
        current_app.logger.exception(e)

        return jsonify({
            "status": "error",
            "message": str(e),
            "records": [],
            "total_records": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 0,
            "has_next": False,
            "has_previous": page > 1,
        }), 500

    records = [_serialize_tax_record(row, taxtype=taxtype) for row in rows]
    total_pages = (total_records + page_size - 1) // page_size if total_records else 0

    return jsonify({
        "records": records,
        "total_records": total_records,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1,
        "current_page": page,
        "per_page": page_size,
    })


@bp.get("/taxpayer-history")
@jwt_required()
def taxpayer_history():
    taxtype, params = _get_taxpayer_profile_params()
    tin = (request.args.get("tin") or "").strip()

    if taxtype not in ("gst", "swt", "cit"):
        return jsonify({"status": "error", "message": "Invalid taxtype", "records": []}), 400

    if not tin:
        return jsonify({"status": "error", "message": "TIN is required", "records": []}), 400

    params["tin"] = tin
    base_query = _taxpayer_profile_base_query(taxtype)
    sql = text(f"""
        SELECT *
        FROM (
            {base_query}
        ) x
        WHERE tin = :tin
        ORDER BY tax_period_year DESC, COALESCE(tax_period_month, 12) DESC, tin ASC
    """)

    try:
        rows = db.session.execute(sql, params).mappings().all()
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"status": "error", "message": str(e), "records": []}), 500

    return jsonify({
        "records": [_serialize_tax_record(row, taxtype=taxtype) for row in rows]
    })


@bp.get("/fraud-reasons")
@jwt_required()
def taxpayer_fraud_reasons():
    taxtype, params = _get_taxpayer_profile_params()
    tin = (request.args.get("tin") or "").strip()

    if taxtype not in ("gst", "swt", "cit"):
        return jsonify({"status": "error", "message": "Invalid taxtype", "records": []}), 400

    if not tin:
        return jsonify({"status": "error", "message": "TIN is required", "records": []}), 400

    params["tin"] = tin
    base_query = _taxpayer_profile_base_query(taxtype)
    sql = text(f"""
        SELECT
            tin,
            tax_period_year AS year,
            tax_period_month AS month,
            fraud_reason
        FROM (
            {base_query}
        ) x
        WHERE tin = :tin
          AND COALESCE(NULLIF(TRIM(fraud_reason), ''), '') <> ''
        ORDER BY tax_period_year DESC, COALESCE(tax_period_month, 12) DESC, tin ASC
    """)

    try:
        rows = db.session.execute(sql, params).mappings().all()
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"status": "error", "message": str(e), "records": []}), 500

    return jsonify({
        "records": [dict(row) for row in rows]
    })


