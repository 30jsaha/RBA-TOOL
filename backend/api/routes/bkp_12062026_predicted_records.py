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

    # Apply search/date filters at outer level to keep params simple and stable.
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
        LIMIT 2000
    """)

    try:
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
            "total_records": len(records),
            "total_pages": 1,
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

    taxtype = (request.args.get("taxtype") or "gst").lower()

    if taxtype not in ("gst", "swt", "cit"):
        return jsonify({
            "status": "error",
            "message": "Invalid taxtype",
            "records": []
        }), 400

    queries = []

    # -----------------------------
    # GET DATE RANGE
    # -----------------------------
    start_year, start_month, end_year, end_month = get_date_range()

    params = {
        "start_ym": (start_year * 100) + start_month,
        "end_ym": (end_year * 100) + end_month
    }

    # ==========================
    # GST
    # ==========================
    if taxtype == "gst":

        queries.append("""
            SELECT
                CAST(pr.tin AS CHAR(30)) AS tin,
                COALESCE(NULLIF(TRIM(pr.taxpayer_name), ''), 'Unknown') AS taxpayer_name,
                'Normal' AS risk_type,

                COALESCE(pr.is_fraud, 0) AS is_fraud,

                CASE
                    WHEN COALESCE(pr.is_fraud, 0) = 1
                    THEN 1 ELSE 0
                END AS flagged,

                CASE
                    WHEN COALESCE(pr.is_fraud, 0) = 1
                    THEN COALESCE(NULLIF(TRIM(pr.explanation), ''), '')
                    ELSE ''
                END AS fraud_reason,

                COALESCE(pr.total_sales_income, 0)
                    AS total_sales_income,

                COALESCE(pr.gst_payable, 0)
                    AS gst_payable,

                COALESCE(
                    NULLIF(TRIM(pr.taxpayer_type), ''),
                    'Unknown'
                ) AS segment_label,

                pr.tax_period_year,
                pr.tax_period_month,

                COALESCE(pr.tax_account_number, 0)
                    AS tax_account_number

            FROM gst_fraud_justification pr

            WHERE
            ((pr.tax_period_year * 100)
            + pr.tax_period_month)
            BETWEEN :start_ym AND :end_ym
        """)

    # ==========================
    # SWT
    # ==========================
    elif taxtype == "swt":

        queries.append("""
            SELECT
                CAST(pr.tin AS CHAR(30)) AS tin,

                COALESCE(
                    NULLIF(TRIM(pr.taxpayer_name), ''),
                    'Unknown'
                ) AS taxpayer_name,

                'Normal' AS risk_type,

                CASE
                    WHEN LOWER(
                        COALESCE(pr.predicted_fraud, '')
                    ) = 'fraud'
                    THEN 1 ELSE 0
                END AS is_fraud,

                CASE
                    WHEN LOWER(
                        COALESCE(pr.predicted_fraud, '')
                    ) = 'fraud'
                    THEN 1 ELSE 0
                END AS flagged,

                CASE
                    WHEN LOWER(
                        COALESCE(pr.predicted_fraud, '')
                    ) = 'fraud'
                    THEN COALESCE(
                        NULLIF(TRIM(pr.explanation), ''),
                        ''
                    )
                    ELSE ''
                END AS fraud_reason,

                COALESCE(
                    pr.total_salary_wages_paid,
                    0
                ) AS total_sales_income,

                COALESCE(
                    pr.total_swt_tax_deducted,
                    0
                ) AS gst_payable,

                'Salary/Wage'
                    AS segment_label,

                pr.tax_period_year,
                pr.tax_period_month,

                COALESCE(
                    pr.tax_account_number,
                    0
                ) AS tax_account_number

            FROM swt_fraud_justification pr

            WHERE
            ((pr.tax_period_year * 100)
            + pr.tax_period_month)
            BETWEEN :start_ym AND :end_ym
        """)

    # ==========================
    # CIT
    # ==========================
    else:

        queries.append("""
            SELECT
                CAST(pr.tin AS CHAR(30)) AS tin,

                COALESCE(
                    NULLIF(TRIM(pr.taxpayer), ''),
                    'Unknown'
                ) AS taxpayer_name,

                'Normal' AS risk_type,

                CASE
                    WHEN LOWER(
                        COALESCE(pr.predicted_fraud, '')
                    ) = 'fraud'
                    THEN 1 ELSE 0
                END AS is_fraud,

                CASE
                    WHEN LOWER(
                        COALESCE(pr.predicted_fraud, '')
                    ) = 'fraud'
                    THEN 1 ELSE 0
                END AS flagged,

                CASE
                    WHEN LOWER(
                        COALESCE(pr.predicted_fraud, '')
                    ) = 'fraud'
                    THEN 'Fraud predicted'
                    ELSE ''
                END AS fraud_reason,

                COALESCE(pr.total_gross_income, 0)
                    AS total_sales_income,

                COALESCE(pr.total_tax_payable, 0)
                    AS gst_payable,

                'CIT' AS segment_label,

                pr.tax_period_year,
                NULL AS tax_period_month,

                COALESCE(pr.tax_account_no, 0)
                    AS tax_account_number

            FROM cit_fraud_justification pr

            WHERE pr.tax_period_year
            BETWEEN :start_year AND :end_year
        """)

        params["start_year"] = start_year
        params["end_year"] = end_year

    final_sql = text(f"""
        SELECT *
        FROM (
            {" UNION ALL ".join(queries)}
        ) x
        ORDER BY
            tax_period_year DESC,
            COALESCE(tax_period_month, 12) DESC,
            tin
    """)

    try:
        rows = db.session.execute(
            final_sql,
            params
        ).mappings().all()

    except Exception as e:
        current_app.logger.exception(e)

        return jsonify({
            "status": "error",
            "message": str(e),
            "records": []
        }), 500

    records = [dict(r) for r in rows]

    return jsonify({
        "records": records,
        "total_records": len(records),
        "total_pages": 1
    })
