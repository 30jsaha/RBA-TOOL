# app/blueprints/dashboard.py
from flask import Blueprint, jsonify, request, Response, current_app
from flask_jwt_extended import jwt_required
from sqlalchemy import text
from datetime import datetime
from dateutil.relativedelta import relativedelta
from ..extensions import db
from .dashboard_common import get_date_filter
import csv
from io import StringIO

bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")
download_bp = Blueprint("dashboard_download", __name__, url_prefix="/api/gst/download-csv")

CSV_HEADERS = [
    "tin",
    "taxpayer_name",
    "total_sales",
    "taxable_sales",
    "exempt_sales",
    "zero_rated_sales",
    "gst_payable",
    "gst_refundable",
    "risk_flag",
    "month",
    "province",
    "segmentation",
]


# ============================================================
# Helper: Determine date range
# ============================================================
def get_date_range():
    """
    Handles '1m', '3m', '6m', '1y', and 'custom' ranges dynamically.
    Defaults to the current month.
    Returns (start_year, start_month, end_year, end_month)
    """
    _, params = get_date_filter(
        column_year="tax_period_year",
        column_month="tax_period_month",
    )

    now = datetime.now()
    return (
        int(params.get("start_year", now.year)),
        int(params.get("start_month", now.month)),
        int(params.get("end_year", now.year)),
        int(params.get("end_month", now.month)),
    )


def _collect_date_params():
    _, params = get_date_filter(
        column_year="tax_period_year",
        column_month="tax_period_month",
    )
    return params


def _gst_base_query(extra_filter=""):
    date_filter, _ = get_date_filter(
        column_year="pr.tax_period_year",
        column_month="pr.tax_period_month",
    )
    return text(f"""
        SELECT
            pr.tin AS tin,
            pr.taxpayer_name,
            COALESCE(ag.gst_total_sales_income, pr.total_sales_income) AS total_sales,
            COALESCE(ag.gst_taxable_sales, pr.gst_taxable_sales) AS taxable_sales,
            pr.exempt_sales AS exempt_sales,
            pr.zero_rated_sales AS zero_rated_sales,
            COALESCE(ag.gst_payable, pr.gst_payable) AS gst_payable,
            COALESCE(ag.gst_refundable, pr.gst_refundable) AS gst_refundable,
            COALESCE(pr.is_fraud, ag.gst_fraud_flag, 0) AS risk_flag,
            pr.tax_period_month,
            pr.tax_period_year,
            COALESCE(tr.province, 'UNKNOWN') AS province,
            pr.taxpayer_type AS segmentation
        FROM gst_fraud_justification pr
        LEFT JOIN agg_gst ag
            ON pr.tin = ag.tin
            AND pr.tax_period_year = ag.tax_period_year
        LEFT JOIN tin_registration_mst tr
            ON TRIM(pr.tin) COLLATE utf8mb4_unicode_ci = TRIM(tr.tin) COLLATE utf8mb4_unicode_ci
        WHERE ({date_filter})
          {extra_filter}
        ORDER BY pr.tax_period_year, pr.tax_period_month, pr.tin
    """)


def _format_month_label(month, year):
    try:
        return f"{int(month):02d}-{int(year)}"
    except (TypeError, ValueError):
        return ""

def _debug_csv_sample(label, data):
    try:
        print(f"[csv-debug] {label}: {data[:5]}")
    except Exception:
        pass

def _parse_columns(default_columns, allowed_columns, include_ids=True):
    raw = request.args.get("columns")
    if raw:
        cols = [c.strip() for c in raw.split(",") if c.strip()]
    else:
        cols = list(default_columns)

    ordered = []
    if include_ids:
        for key in ["tin", "taxpayer_name"]:
            if key in allowed_columns and key not in ordered:
                ordered.append(key)

    for col in cols:
        if col in allowed_columns and col not in ordered:
            ordered.append(col)

    return ordered


def _build_csv_response(rows, filename, columns):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)

    for row in rows:
        writer.writerow([
            row.get(col, "") if row.get(col, "") is not None else ""
            for col in columns
        ])

    response = Response(buffer.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ============================================================
# A) Dashboard Summary Cards
# ============================================================
@bp.get("/data")
@jwt_required()
def dashboard_data():
    try:
        date_filter, date_params = get_date_filter(
            column_year="pr.tax_period_year",
            column_month="pr.tax_period_month",
        )
        start_year, start_month, end_year, end_month = get_date_range()

        query = text(f"""
            SELECT 
                COUNT(DISTINCT pr.tin) AS total_tax_payers,
                SUM(COALESCE(ag.gst_total_sales_income, pr.total_sales_income, 0)) AS total_sales_income,
                SUM(COALESCE(ag.gst_payable, pr.gst_payable, 0)) AS total_gst_payable,
                SUM(COALESCE(ag.gst_refundable, pr.gst_refundable, 0)) AS total_gst_refundable
            FROM gst_fraud_justification pr
            LEFT JOIN agg_gst ag
                ON pr.tin = ag.tin
                AND pr.tax_period_year = ag.tax_period_year
            WHERE ({date_filter})
        """)

        result = db.session.execute(query, date_params).fetchone()

        return jsonify({
            "period_range": f"{start_month:02d}-{start_year} to {end_month:02d}-{end_year}",
            "total_tax_payers": result.total_tax_payers or 0,
            "total_sales_income": result.total_sales_income or 0,
            "total_gst_payable": result.total_gst_payable or 0,
            "total_gst_refundable": result.total_gst_refundable or 0
        })
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# B) Sales Comparison
# ============================================================
@bp.get("/sales-comparison")
@jwt_required()
def sales_comparison():
    try:
        date_filter, date_params = get_date_filter(
            column_year="pr.tax_period_year",
            column_month="pr.tax_period_month",
        )

        query = text(f"""
            SELECT 
                pr.tax_period_year,
                pr.tax_period_month,
                SUM(COALESCE(ag.gst_total_sales_income, pr.total_sales_income, 0)) AS total_sales_income,
                SUM(COALESCE(pr.exempt_sales, 0)) AS exempt_sales,
                SUM(COALESCE(pr.zero_rated_sales, 0)) AS zero_rated_sales,
                SUM(COALESCE(ag.gst_taxable_sales, pr.gst_taxable_sales, 0)) AS gst_taxable_sales
            FROM gst_fraud_justification pr
            LEFT JOIN agg_gst ag
                ON pr.tin = ag.tin
                AND pr.tax_period_year = ag.tax_period_year
            WHERE ({date_filter})
            GROUP BY pr.tax_period_year, pr.tax_period_month
            ORDER BY pr.tax_period_year, pr.tax_period_month
        """)

        rows = db.session.execute(query, date_params).fetchall()

        categories, total_sales, exempt, zero_rated, taxable = [], [], [], [], []
        for r in rows:
            categories.append(f"{r.tax_period_month:02d}-{r.tax_period_year}")
            total_sales.append(float(r.total_sales_income or 0))
            exempt.append(float(r.exempt_sales or 0))
            zero_rated.append(float(r.zero_rated_sales or 0))
            taxable.append(float(r.gst_taxable_sales or 0))

        return jsonify({
            "categories": categories,
            "series": [
                {"name": "Total Sales", "data": total_sales},
                {"name": "Exempt Sales", "data": exempt},
                {"name": "Zero Rated Sales", "data": zero_rated},
                {"name": "Taxable Sales", "data": taxable}
            ]
        })
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# C) GST Payable vs Refundable
# ============================================================
@bp.get("/gst-payable-vs-refund")
@jwt_required()
def gst_payable_vs_refundable():
    try:
        date_filter, date_params = get_date_filter(
            column_year="pr.tax_period_year",
            column_month="pr.tax_period_month",
        )

        query = text(f"""
            SELECT 
                pr.tax_period_year,
                pr.tax_period_month,
                SUM(COALESCE(ag.gst_payable, pr.gst_payable, 0)) AS gst_payable,
                SUM(COALESCE(ag.gst_refundable, pr.gst_refundable, 0)) AS gst_refundable
            FROM gst_fraud_justification pr
            LEFT JOIN agg_gst ag
                ON pr.tin = ag.tin
                AND pr.tax_period_year = ag.tax_period_year
            WHERE ({date_filter})
            GROUP BY pr.tax_period_year, pr.tax_period_month
            ORDER BY pr.tax_period_year, pr.tax_period_month
        """)

        rows = db.session.execute(query, date_params).fetchall()

        categories, payable, refundable = [], [], []
        for r in rows:
            categories.append(f"{r.tax_period_month:02d}-{r.tax_period_year}")
            payable.append(float(r.gst_payable or 0))
            refundable.append(float(r.gst_refundable or 0))

        return jsonify({
            "categories": categories,
            "series": [
                {"name": "GST Payable", "data": payable},
                {"name": "GST Refundable", "data": refundable}
            ]
        })
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# D) Segmentation Distribution (Pie)
# ============================================================
@bp.get("/segmentation-distribution")
@jwt_required()
def segmentation_distribution():
    try:
        date_filter, date_params = get_date_filter(
            column_year="tax_period_year",
            column_month="tax_period_month",
        )

        # gst_fraud_justification does not have segment_label; use taxpayer_type as a best-effort segment proxy
        query = text(f"""
            SELECT
                COALESCE(NULLIF(TRIM(taxpayer_type), ''), 'Unknown') AS segment_label,
                COUNT(DISTINCT tin) AS tin_count
            FROM gst_fraud_justification
            WHERE ({date_filter})
            GROUP BY COALESCE(NULLIF(TRIM(taxpayer_type), ''), 'Unknown')
            ORDER BY segment_label
        """)

        rows = db.session.execute(query, date_params).fetchall()

        # Keep existing fixed order; anything else won't map and will remain 0
        segment_counts = {"Large": 0, "Medium": 0, "Small": 0}
        for r in rows:
            if r.segment_label in segment_counts:
                segment_counts[r.segment_label] = int(r.tin_count)

        labels = ["Large", "Medium", "Small"]
        series = [segment_counts[l] for l in labels]

        return jsonify({"labels": labels, "series": series})
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# E) Risk Flagged vs Non-Risk
# ============================================================
@bp.get("/risk-flagged")
@jwt_required()
def risk_flagged_vs_non():
    try:
        date_filter, date_params = get_date_filter(
            column_year="tax_period_year",
            column_month="tax_period_month",
        )

        query = text(f"""
            SELECT 
                SUM(CASE WHEN COALESCE(is_fraud, 0) = 1 THEN 1 ELSE 0 END) AS risk_flagged,
                SUM(CASE WHEN COALESCE(is_fraud, 0) = 0 THEN 1 ELSE 0 END) AS non_risk_flagged
            FROM gst_fraud_justification
            WHERE ({date_filter})
        """)

        result = db.session.execute(query, date_params).fetchone()

        return jsonify({
            "labels": ["Risk Flagged", "Non-Risk Flagged"],
            "series": [int(result.risk_flagged or 0), int(result.non_risk_flagged or 0)]
        })
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# F) Latest Tax Records (Table)
# ============================================================
@bp.get("/latest-records")
@jwt_required()
def latest_tax_records():
    """
    Returns the latest 20 GST tax records merged with fraud audit info.
    Fixes duplicate frauds by matching TIN + file_upload_history_id exactly,
    same logic as upload_history.py.
    """
    from datetime import datetime
    import pandas as pd, os

    date_filter, date_params = get_date_filter(
        column_year="p.tax_period_year",
        column_month="p.tax_period_month",
    )

    query = f"""
        SELECT
            p.tin AS tin_number,
            p.taxpayer_name,
            p.taxpayer_type,
            p.tax_period_year,
            p.tax_period_month,
            COALESCE(ag.gst_payable, p.gst_payable) AS gst_payable,
            COALESCE(ag.gst_refundable, p.gst_refundable) AS gst_refundable,
            p.taxpayer_type AS segment_label,
            CASE
                WHEN COALESCE(p.is_fraud, 0) = 1 THEN COALESCE(p.explanation, '')
                ELSE ''
            END AS fraud_reason,
            CASE
                WHEN COALESCE(p.is_fraud, 0) = 1 THEN 'Risk'
                ELSE 'Normal'
            END AS risk_type,
            0 AS risk_score,
            COALESCE(p.is_fraud, 0) AS is_flag,
            p.uploaded_at AS created_at
        FROM gst_fraud_justification p
        LEFT JOIN agg_gst ag
            ON p.tin = ag.tin
            AND p.tax_period_year = ag.tax_period_year
        WHERE ({date_filter})
        ORDER BY p.uploaded_at DESC
        LIMIT 20;
    """

    rows = db.session.execute(text(query), date_params).fetchall()

    # Convert to JSON-serializable structure
    data = []
    for r in rows:
        data.append({
            "tin_number": r.tin_number,
            "taxpayer_name": r.taxpayer_name,
            "taxpayer_type": r.taxpayer_type,
            "tax_period_year": r.tax_period_year,
            "tax_period_month": r.tax_period_month,
            "gst_payable": float(r.gst_payable or 0),
            "gst_refundable": float(r.gst_refundable or 0),
            "segment_label": r.segment_label,
            "risk_score": float(r.risk_score or 0),
            "flagged": "Yes" if r.is_flag else "No",
            "risk_type": r.risk_type or "Normal",
            "fraud_reason": r.fraud_reason or "",
            "created_at": str(r.created_at)
        })

    # Export results to Excel
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = "outputs"
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"latest_tax_records_{timestamp}.xlsx")

    pd.DataFrame(data).to_excel(output_file, index=False)

    return jsonify({
        "status": "success",
        "message": "Latest tax records retrieved successfully.",
        "total_records": len(data),
        "excel_download": output_file.replace("\\", "/"),
        "records": data
    }), 200
    


# ============================================================
# F) Fraud Province Distribution
# ============================================================
@bp.get("/fraud-province-distribution")
@jwt_required()
def fraud_province_distribution():

    # -----------------------------------------
    # Province Standardization (kept as-is — good enough)
    # -----------------------------------------
    PROVINCE_STANDARD = {
        # Common variations and old names
        "CHIMBU": "Simbu",
        "SIMBU": "Simbu",
        "CHIMBU PROVINCE": "Simbu",
        
        "WEST SEPIK": "Sandaun",
        "SANDAUN": "Sandaun",
        "WEST SEPIK PROVINCE": "Sandaun",
        
        "EAST SEPIK": "East Sepik",
        "EAST SEPIK PROVINCE": "East Sepik",
        
        "EASTERN HIGHLANDS": "Eastern Highlands",
        "EASTERN HIGHLANDS PROVINCE": "Eastern Highlands",
        
        "WESTERN HIGHLANDS": "Western Highlands",
        "WESTERN HIGHLANDS PROVINCE": "Western Highlands",
        
        "SOUTHERN HIGHLANDS": "Southern Highlands",
        "SOUTHERN HIGHLANDS PROVINCE": "Southern Highlands",
        
        "NEW IRELAND": "New Ireland",
        "NEW IRELAND PROVINCE": "New Ireland",
        
        "MANUS": "Manus",
        "MANUS PROVINCE": "Manus",
        
        "MILNE BAY": "Milne Bay",
        "MILNE BAY PROVINCE": "Milne Bay",
        
        "ORO": "Oro (Northern)",
        "ORO PROVINCE": "Oro (Northern)",
        "NORTHERN": "Oro (Northern)",
        "NORTHERN PROVINCE": "Oro (Northern)",
        
        "BOUGAINVILLE": "Bougainville",
        "NORTH SOLOMONS": "Bougainville",
        "AUTONOMOUS REGION OF BOUGAINVILLE": "Bougainville",
        
        "WEST NEW BRITAIN": "West New Britain",
        "WEST NEW BRITAIN PROVINCE": "West New Britain",
        
        "EAST NEW BRITAIN": "East New Britain",
        "EAST NEW BRITAIN PROVINCE": "East New Britain",
        
        "WESTERN": "Western (Fly)",
        "WESTERN PROVINCE": "Western (Fly)",
        "FLY": "Western (Fly)",
        
        "NATIONAL CAPITAL DISTRICT": "National Capital District",
        "PORT MORESBY": "National Capital District",
        
        # Add newer provinces (even if not in your current data yet)
        "HELA": "Hela",
        "JIWAKA": "Jiwaka",
        
        # Others that might appear
        "CENTRAL": "Central",
        "CENTRAL PROVINCE": "Central",
        "ENGA": "Enga",
        "GULF": "Gulf",
        "MADANG": "Madang",
        "MOROBE": "Morobe",
    }

    def normalize_province(p):
        if not p:
            return "UNKNOWN"

        key = p.strip().upper()

        if key in PROVINCE_STANDARD:
            return PROVINCE_STANDARD[key]

        cleaned = key.replace("PROVINCE", "").strip()
        if cleaned in PROVINCE_STANDARD:
            return PROVINCE_STANDARD[cleaned]

        return cleaned.title()

    # -----------------------------------------
    # Date Range
    # -----------------------------------------
    start_year, start_month, end_year, end_month = get_date_range()

    params = {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month
    }

    # -----------------------------------------
    # 4. Province Summary — IMPROVED
    # -----------------------------------------
    summary_sql = """
        SELECT
            COALESCE(tr.province, 'UNKNOWN') AS province,
            COUNT(DISTINCT pr.tin) AS total_tins,
            COUNT(DISTINCT CASE WHEN COALESCE(pr.is_fraud, 0) = 1 THEN pr.tin END) AS fraud_tins
        FROM gst_fraud_justification pr
        INNER JOIN tin_registration_mst tr
            ON TRIM(pr.tin) COLLATE utf8mb4_unicode_ci = TRIM(tr.tin) COLLATE utf8mb4_unicode_ci
        WHERE (pr.tax_period_year, pr.tax_period_month) >= (:start_year, :start_month)
          AND (pr.tax_period_year, pr.tax_period_month) <= (:end_year, :end_month)
        GROUP BY COALESCE(tr.province, 'UNKNOWN')
    """

    summary_rows = db.session.execute(
        text(summary_sql), params
    ).mappings().all()

    # -----------------------------------------
    # 5. Fraud Taxpayer List — IMPROVED
    # -----------------------------------------
    fraud_sql = """
        SELECT DISTINCT
            COALESCE(tr.province, 'UNKNOWN') AS province,
            pr.tin AS tin_number,
            pr.taxpayer_name
        FROM gst_fraud_justification pr
        INNER JOIN tin_registration_mst tr
            ON TRIM(pr.tin) COLLATE utf8mb4_unicode_ci = TRIM(tr.tin) COLLATE utf8mb4_unicode_ci
        WHERE COALESCE(pr.is_fraud, 0) = 1
          AND (pr.tax_period_year, pr.tax_period_month) >= (:start_year, :start_month)
          AND (pr.tax_period_year, pr.tax_period_month) <= (:end_year, :end_month)
    """

    fraud_rows = db.session.execute(
        text(fraud_sql), params
    ).mappings().all()

    # -----------------------------------------
    # 6. Build Province Map
    # -----------------------------------------
    province_map = {}

    # Initialize from summary
    for row in summary_rows:
        raw_province = row["province"]
        province = normalize_province(raw_province)

        total = row["total_tins"] or 0
        fraud = row["fraud_tins"] or 0

        risk_percentage = round((fraud / total) * 100, 2) if total > 0 else 0

        province_map[province] = {
            "total_tins": total,
            "fraud_tins": fraud,
            "risk_percentage": risk_percentage,
            "fraud_taxpayers": []
        }

    # Attach fraud taxpayers
    for row in fraud_rows:
        raw_province = row["province"]
        province = normalize_province(raw_province)

        if province not in province_map:
            province_map[province] = {
                "total_tins": 0,
                "fraud_tins": 0,
                "risk_percentage": 0,
                "fraud_taxpayers": []
            }

        province_map[province]["fraud_taxpayers"].append({
            "tin": row["tin_number"],
            "taxpayer_name": row["taxpayer_name"]
        })

    # -----------------------------------------
    # 7. Response
    # -----------------------------------------
    return jsonify({
        "date_range": {
            "start": f"{start_month:02d}-{start_year}",
            "end": f"{end_month:02d}-{end_year}"
        },
        "province_distribution": province_map
    })


@download_bp.get("/sales-comparison")
@jwt_required()
def download_sales_comparison():
    start_year, start_month, end_year, end_month = get_date_range()
    query = text("""
        SELECT 
            pr.tin AS tin,
            pr.taxpayer_name AS taxpayer_name,
            pr.tax_period_year,
            pr.tax_period_month,
            SUM(COALESCE(ag.gst_total_sales_income, pr.total_sales_income, 0)) AS total_sales_income,
            SUM(COALESCE(pr.exempt_sales, 0)) AS exempt_sales,
            SUM(COALESCE(pr.zero_rated_sales, 0)) AS zero_rated_sales,
            SUM(COALESCE(ag.gst_taxable_sales, pr.gst_taxable_sales, 0)) AS gst_taxable_sales
        FROM gst_fraud_justification pr
        LEFT JOIN agg_gst ag
            ON pr.tin = ag.tin
            AND pr.tax_period_year = ag.tax_period_year
        WHERE (pr.tax_period_year > :start_year OR 
              (pr.tax_period_year = :start_year AND pr.tax_period_month >= :start_month))
          AND (pr.tax_period_year < :end_year OR 
              (pr.tax_period_year = :end_year AND pr.tax_period_month <= :end_month))
        GROUP BY pr.tin, pr.taxpayer_name, pr.tax_period_year, pr.tax_period_month
        ORDER BY pr.tax_period_year, pr.tax_period_month, pr.tin
    """)

    rows = db.session.execute(query, {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month
    }).fetchall()

    data = [{
        "tin": r.tin or "",
        "taxpayer_name": r.taxpayer_name or None,
        "month": f"{int(r.tax_period_month):02d}-{int(r.tax_period_year)}",
        "total_sales": float(r.total_sales_income or 0),
        "exempt_sales": float(r.exempt_sales or 0),
        "zero_rated_sales": float(r.zero_rated_sales or 0),
        "taxable_sales": float(r.gst_taxable_sales or 0),
    } for r in rows]

    _debug_csv_sample("gst-sales-comparison", data)
    allowed = [
        "tin",
        "taxpayer_name",
        "month",
        "total_sales",
        "exempt_sales",
        "zero_rated_sales",
        "taxable_sales",
    ]
    columns = _parse_columns(
        ["month", "total_sales", "exempt_sales", "zero_rated_sales", "taxable_sales"],
        allowed,
        include_ids=True
    )
    return _build_csv_response(data, "sales-comparison.csv", columns)


@download_bp.get("/payable-vs-refundable")
@jwt_required()
def download_payable_vs_refundable():
    start_year, start_month, end_year, end_month = get_date_range()
    query = text("""
        SELECT 
            pr.tin AS tin,
            pr.taxpayer_name AS taxpayer_name,
            pr.tax_period_year,
            pr.tax_period_month,
            SUM(COALESCE(ag.gst_payable, pr.gst_payable, 0)) AS gst_payable,
            SUM(COALESCE(ag.gst_refundable, pr.gst_refundable, 0)) AS gst_refundable
        FROM gst_fraud_justification pr
        LEFT JOIN agg_gst ag
            ON pr.tin = ag.tin
            AND pr.tax_period_year = ag.tax_period_year
        WHERE (pr.tax_period_year > :start_year OR 
              (pr.tax_period_year = :start_year AND pr.tax_period_month >= :start_month))
          AND (pr.tax_period_year < :end_year OR 
              (pr.tax_period_year = :end_year AND pr.tax_period_month <= :end_month))
        GROUP BY pr.tin, pr.taxpayer_name, pr.tax_period_year, pr.tax_period_month
        ORDER BY pr.tax_period_year, pr.tax_period_month, pr.tin
    """)

    rows = db.session.execute(query, {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month
    }).fetchall()

    data = [{
        "tin": r.tin or "",
        "taxpayer_name": r.taxpayer_name or None,
        "month": f"{int(r.tax_period_month):02d}-{int(r.tax_period_year)}",
        "gst_payable": float(r.gst_payable or 0),
        "gst_refundable": float(r.gst_refundable or 0),
    } for r in rows]

    _debug_csv_sample("gst-payable-vs-refundable", data)
    allowed = ["tin", "taxpayer_name", "month", "gst_payable", "gst_refundable"]
    columns = _parse_columns(["month", "gst_payable", "gst_refundable"], allowed, include_ids=True)
    return _build_csv_response(data, "payable-vs-refundable.csv", columns)


@download_bp.get("/segmentation")
@jwt_required()
def download_segmentation_distribution():
    start_year, start_month, end_year, end_month = get_date_range()
    query = text("""
        SELECT
            pr.tin AS tin,
            COALESCE(NULLIF(TRIM(pr.taxpayer_name), ''), 'Unknown') AS taxpayer_name,
            MAX(pr.taxpayer_type) AS segment
        FROM gst_fraud_justification pr
        WHERE pr.taxpayer_type IS NOT NULL
          AND (pr.tax_period_year > :start_year OR 
              (pr.tax_period_year = :start_year AND pr.tax_period_month >= :start_month))
          AND (pr.tax_period_year < :end_year OR 
              (pr.tax_period_year = :end_year AND pr.tax_period_month <= :end_month))
        GROUP BY pr.tin, pr.taxpayer_name
        ORDER BY pr.tin
    """)

    rows = db.session.execute(query, {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month
    }).fetchall()

    data = [{
        "tin": r.tin or "",
        "taxpayer_name": r.taxpayer_name or None,
        "segment": r.segment or None,
    } for r in rows]

    _debug_csv_sample("gst-segmentation", data)
    allowed = ["tin", "taxpayer_name", "segment"]
    columns = _parse_columns(["segment"], allowed, include_ids=True)
    return _build_csv_response(data, "segmentation.csv", columns)


@download_bp.get("/risk-flagged")
@jwt_required()
def download_risk_flagged():
    start_year, start_month, end_year, end_month = get_date_range()
    query = text("""
        SELECT 
            pr.tin AS tin,
            pr.taxpayer_name AS taxpayer_name,
            pr.is_fraud AS risk_flag,
            COUNT(*) AS count
        FROM gst_fraud_justification pr
        WHERE (pr.tax_period_year > :start_year OR 
              (pr.tax_period_year = :start_year AND pr.tax_period_month >= :start_month))
          AND (pr.tax_period_year < :end_year OR 
              (pr.tax_period_year = :end_year AND pr.tax_period_month <= :end_month))
        GROUP BY pr.tin, pr.taxpayer_name, pr.is_fraud
        ORDER BY pr.tin
    """)

    rows = db.session.execute(query, {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month
    }).fetchall()

    data = [{
        "tin": r.tin or "",
        "taxpayer_name": r.taxpayer_name or None,
        "risk_flag": "Risk Flagged" if int(r.risk_flag or 0) == 1 else "Non-Risk Flagged",
        "count": int(r.count or 0)
    } for r in rows]

    _debug_csv_sample("gst-risk-flagged", data)

    allowed = ["tin", "taxpayer_name", "risk_flag", "count"]
    columns = _parse_columns(["risk_flag", "count"], allowed, include_ids=True)
    return _build_csv_response(data, "risk-flagged.csv", columns)


@download_bp.get("/province")
@jwt_required()
def download_province_distribution():
    start_year, start_month, end_year, end_month = get_date_range()
    params = {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month
    }

    summary_sql = """
        SELECT
            COALESCE(tr.province, 'UNKNOWN') AS province,
            COUNT(DISTINCT pr.tin) AS total_tins,
            COUNT(DISTINCT CASE WHEN COALESCE(pr.is_fraud, 0) = 1 THEN pr.tin END) AS fraud_tins
        FROM gst_fraud_justification pr
        INNER JOIN tin_registration_mst tr
            ON TRIM(pr.tin) COLLATE utf8mb4_unicode_ci = TRIM(tr.tin) COLLATE utf8mb4_unicode_ci
        WHERE (pr.tax_period_year, pr.tax_period_month) >= (:start_year, :start_month)
          AND (pr.tax_period_year, pr.tax_period_month) <= (:end_year, :end_month)
        GROUP BY COALESCE(tr.province, 'UNKNOWN')
    """

    fraud_sql = """
        SELECT DISTINCT
            COALESCE(tr.province, 'UNKNOWN') AS province,
            pr.tin AS tin,
            pr.taxpayer_name AS taxpayer_name
        FROM gst_fraud_justification pr
        INNER JOIN tin_registration_mst tr
            ON TRIM(pr.tin) COLLATE utf8mb4_unicode_ci = TRIM(tr.tin) COLLATE utf8mb4_unicode_ci
        WHERE COALESCE(pr.is_fraud, 0) = 1
          AND (pr.tax_period_year, pr.tax_period_month) >= (:start_year, :start_month)
          AND (pr.tax_period_year, pr.tax_period_month) <= (:end_year, :end_month)
    """

    summary_rows = db.session.execute(text(summary_sql), params).mappings().all()
    fraud_rows = db.session.execute(text(fraud_sql), params).mappings().all()

    province_map = {}
    for row in summary_rows:
        total = row["total_tins"] or 0
        fraud = row["fraud_tins"] or 0
        risk_percentage = round((fraud / total) * 100, 2) if total > 0 else 0
        province_map[row["province"]] = {
            "risk_percentage": risk_percentage,
            "fraud_taxpayers": []
        }

    for row in fraud_rows:
        province = row["province"]
        if province not in province_map:
            province_map[province] = {"risk_percentage": 0, "fraud_taxpayers": []}
        province_map[province]["fraud_taxpayers"].append({
            "tin": row["tin"],
            "taxpayer_name": row["taxpayer_name"]
        })

    data = []
    for province, info in province_map.items():
        taxpayers = info.get("fraud_taxpayers", [])
        if taxpayers:
            for tp in taxpayers:
                data.append({
                    "tin": tp.get("tin") or "",
                    "taxpayer_name": tp.get("taxpayer_name") or "",
                    "province": province,
                    "risk_percentage": info.get("risk_percentage", 0),
                })
        else:
            data.append({
                "tin": "",
                "taxpayer_name": "",
                "province": province,
                "risk_percentage": info.get("risk_percentage", 0),
            })

    allowed = ["tin", "taxpayer_name", "province", "risk_percentage"]
    columns = _parse_columns(["province", "risk_percentage"], allowed, include_ids=True)
    _debug_csv_sample("gst-province", data)
    return _build_csv_response(data, "province.csv", columns)
