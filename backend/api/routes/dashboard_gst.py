# app/blueprints/dashboard.py
from flask import Blueprint, jsonify, request, Response, current_app
from flask_jwt_extended import jwt_required
from sqlalchemy import text
from datetime import datetime
from dateutil.relativedelta import relativedelta
from ..extensions import cache, db
import csv
from io import StringIO
import time

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
def _parse_date_value(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _get_month_period_bounds():
    now = datetime.now()
    range_type = request.args.get("range_type", "1y")
    start_date = request.args.get("start_date") or request.args.get("from_date")
    end_date = request.args.get("end_date") or request.args.get("to_date")

    if range_type == "custom":
        start_dt = _parse_date_value(start_date)
        end_dt = _parse_date_value(end_date)

        if start_dt and end_dt:
            start_year, start_month = int(start_dt.year), int(start_dt.month)
            end_year, end_month = int(end_dt.year), int(end_dt.month)
        else:
            try:
                start_year = int(request.args.get("start_year"))
                end_year = int(request.args.get("end_year"))
                start_month = int(request.args.get("start_month") or 1)
                end_month = int(request.args.get("end_month") or 12)
            except (TypeError, ValueError):
                start_year = end_year = int(now.year)
                start_month = end_month = int(now.month)
    else:
        months_by_range = {
            "1m": 1,
            "3m": 3,
            "6m": 6,
            "1y": 12,
            "3y": 36,
            "5y": 60,
            "10y": 120,
        }
        month_count = months_by_range.get(range_type, 12)
        end_dt = now.replace(day=1)
        start_dt = end_dt - relativedelta(months=month_count - 1)
        start_year, start_month = int(start_dt.year), int(start_dt.month)
        end_year, end_month = int(end_dt.year), int(end_dt.month)

    start_ym = (start_year * 100) + start_month
    end_ym = (end_year * 100) + end_month

    if start_ym > end_ym:
        start_year, end_year = end_year, start_year
        start_month, end_month = end_month, start_month
        start_ym, end_ym = end_ym, start_ym

    return {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month,
        "start_ym": start_ym,
        "end_ym": end_ym,
    }


def get_date_range():
    """
    Handles '1m', '3m', '6m', '1y', and 'custom' ranges dynamically.
    Defaults to the current month.
    Returns (start_year, start_month, end_year, end_month)
    """
    params = _get_month_period_bounds()
    return (
        int(params["start_year"]),
        int(params["start_month"]),
        int(params["end_year"]),
        int(params["end_month"]),
    )


def _collect_date_params():
    return _get_month_period_bounds()

def _get_period_bounds():
    params = _collect_date_params()
    start_year = int(params["start_year"])
    start_month = int(params["start_month"])
    end_year = int(params["end_year"])
    end_month = int(params["end_month"])
    start_ym = (start_year * 100) + start_month
    end_ym = (end_year * 100) + end_month

    if start_ym > end_ym:
        start_year, end_year = end_year, start_year
        start_month, end_month = end_month, start_month
        start_ym, end_ym = end_ym, start_ym

    return {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month,
        "start_ym": start_ym,
        "end_ym": end_ym,
    }


def _range_month_count(params):
    return ((params["end_year"] - params["start_year"]) * 12) + (
        params["end_month"] - params["start_month"]
    ) + 1


def _use_yearly_aggregation(params):
    return _range_month_count(params) > 24


def _period_filter_sql(column_year="tax_period_year", column_month="tax_period_month"):
    return f"""
    (
        (
            {column_year} > :start_year
            OR (
                {column_year} = :start_year
                AND {column_month} >= :start_month
            )
        )
        AND
        (
            {column_year} < :end_year
            OR (
                {column_year} = :end_year
                AND {column_month} <= :end_month
            )
        )
    )
    """


def _log_timing(endpoint_name, started_at):
    try:
        elapsed = round(time.time() - started_at, 2)
        current_app.logger.info(
            f"dashboard_gst.py :: {endpoint_name} took {elapsed}s"
        )
    except Exception:
        pass


def _cache_key(endpoint_name, params):
    return (
        f"gst_dashboard:{endpoint_name}:"
        f"{params['start_year']}-{params['start_month']}:"
        f"{params['end_year']}-{params['end_month']}"
    )


def _cached_json(endpoint_name, params, timeout, builder):
    key = _cache_key(endpoint_name, params)
    cached = cache.get(key)
    if cached is not None:
        return cached

    payload = builder()
    cache.set(key, payload, timeout=timeout)
    return payload


def _stream_mappings(statement, params):
    return db.session.execute(
        statement.execution_options(stream_results=True),
        params,
    ).mappings()


def _gst_base_query(extra_filter=""):
    date_filter = _period_filter_sql(
        column_year="pr.tax_period_year",
        column_month="pr.tax_period_month",
    )
    return text(f"""
        SELECT
            pr.tin AS tin,
            pr.taxpayer_name,
            COALESCE(pr.total_sales_income, 0) AS total_sales,
            COALESCE(pr.gst_taxable_sales, 0) AS taxable_sales,
            pr.exempt_sales AS exempt_sales,
            pr.zero_rated_sales AS zero_rated_sales,
            COALESCE(pr.gst_payable, 0) AS gst_payable,
            COALESCE(pr.gst_refundable, 0) AS gst_refundable,
            COALESCE(pr.is_fraud, 0) AS risk_flag,
            pr.tax_period_month,
            pr.tax_period_year,
            COALESCE(tr.province, 'UNKNOWN') AS province,
            COALESCE(sm.segmentation, 'Unknown') AS segmentation
        FROM gst_fraud_justification pr
        LEFT JOIN tin_registration_mst tr
            ON pr.tin = tr.tin
        LEFT JOIN taxpayer_segmentation_master sm
            ON sm.tin = pr.tin
        WHERE ({date_filter})
          {extra_filter}
        ORDER BY pr.tax_period_year, pr.tax_period_month, pr.tin
    """)


def _format_month_label(month, year):
    try:
        return f"{int(month):02d}-{int(year)}"
    except (TypeError, ValueError):
        return ""


def _format_period_label(row):
    month = row.get("tax_period_month")
    year = row.get("tax_period_year")
    if month is None:
        return str(year or "")
    return _format_month_label(month, year)


def _normalize_segment_label(value):
    label = str(value or "").strip()
    return label if label else "Unknown"


def _normalize_unknown_label(value, fallback="Unknown"):
    label = str(value or "").strip()
    return label if label else fallback

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


def _build_sales_comparison_payload(query, date_params):
    rows = db.session.execute(query, date_params).mappings()
    categories, total_sales, exempt, zero_rated, taxable = [], [], [], [], []
    for r in rows:
        categories.append(_format_period_label(r))
        total_sales.append(float(r["total_sales_income"] or 0))
        exempt.append(float(r["exempt_sales"] or 0))
        zero_rated.append(float(r["zero_rated_sales"] or 0))
        taxable.append(float(r["gst_taxable_sales"] or 0))
    return {
        "categories": categories,
        "series": [
            {"name": "Total Sales", "data": total_sales},
            {"name": "Exempt Sales", "data": exempt},
            {"name": "Zero Rated Sales", "data": zero_rated},
            {"name": "Taxable Sales", "data": taxable},
        ],
    }


def _build_gst_payable_payload(query, date_params):
    rows = db.session.execute(query, date_params).mappings()
    categories, payable, refundable = [], [], []
    for r in rows:
        categories.append(_format_period_label(r))
        payable.append(float(r["gst_payable"] or 0))
        refundable.append(float(r["gst_refundable"] or 0))
    return {
        "categories": categories,
        "series": [
            {"name": "GST Payable", "data": payable},
            {"name": "GST Refundable", "data": refundable},
        ],
    }


def _build_segmentation_payload(query, date_params):
    rows = db.session.execute(query, date_params).mappings()
    segment_counts = {}
    for r in rows:
        label = _normalize_segment_label(r["segment_label"])
        segment_counts[label] = segment_counts.get(label, 0) + int(r["tin_count"] or 0)

    labels = [label for label in ["Large", "Medium", "Small"] if label in segment_counts]
    labels.extend(
        label for label in segment_counts
        if label not in {"Large", "Medium", "Small"}
    )
    return {"labels": labels, "series": [segment_counts[l] for l in labels]}


def _build_risk_payload(query, date_params):
    result = db.session.execute(query, date_params).mappings().one()
    return {
        "labels": ["Risk Flagged", "Non-Risk Flagged"],
        "series": [
            int(result["risk_flagged"] or 0),
            int(result["non_risk_flagged"] or 0),
        ],
    }


def _build_province_payload(
    province_sql,
    params,
    normalize_province,
    start_month,
    start_year,
    end_month,
    end_year,
):
    province_rows = db.session.execute(province_sql, params).mappings()
    province_map = {}
    for row in province_rows:
        province = normalize_province(row["province"])
        total = int(row["total_tins"] or 0)
        fraud = int(row["fraud_tins"] or 0)
        province_map[province] = {
            "total_tins": total,
            "fraud_tins": fraud,
            "risk_percentage": round((fraud / total) * 100, 2) if total > 0 else 0,
            "fraud_taxpayers": [],
        }

    return {
        "date_range": {
            "start": f"{start_month:02d}-{start_year}",
            "end": f"{end_month:02d}-{end_year}",
        },
        "province_distribution": province_map,
    }


_GST_PROVINCE_INDEX_WARNING_EMITTED = False
_GST_PROVINCE_INDEX_CHECKED = False
_TIN_PROVINCE_LOOKUP_READY = False


def _ensure_tin_province_lookup():
    global _TIN_PROVINCE_LOOKUP_READY
    if _TIN_PROVINCE_LOOKUP_READY:
        return

    create_sql = text("""
        CREATE TABLE IF NOT EXISTS tin_province_lookup (
            tin VARCHAR(50) PRIMARY KEY,
            taxpayer_name VARCHAR(255),
            province VARCHAR(255),
            INDEX idx_lookup_province (province)
        )
    """)

    populate_sql = text("""
        INSERT IGNORE INTO tin_province_lookup (tin, taxpayer_name, province)
        SELECT
            tr.tin,
            MAX(tr.taxpayername) AS taxpayer_name,
            MAX(tr.province) AS province
        FROM tin_registration_mst tr
        WHERE tr.tin IS NOT NULL
          AND tr.tin <> ''
          AND tr.province IS NOT NULL
          AND tr.province <> ''
        GROUP BY tr.tin
    """)

    try:
        db.session.execute(create_sql)
        db.session.execute(populate_sql)
        db.session.commit()
        _TIN_PROVINCE_LOOKUP_READY = True
    except Exception:
        db.session.rollback()
        raise


def _warn_if_gst_province_index_missing():
    global _GST_PROVINCE_INDEX_WARNING_EMITTED, _GST_PROVINCE_INDEX_CHECKED
    if _GST_PROVINCE_INDEX_CHECKED:
        return

    index_sql = text("""
        SELECT
            index_name,
            seq_in_index,
            column_name
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'gst_fraud_justification'
        ORDER BY index_name, seq_in_index
    """)

    result = db.session.execute(index_sql)
    indexes = {}
    for row in result:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        index_name = mapping.get("index_name")
        column_name = mapping.get("column_name")
        if index_name and column_name:
            indexes.setdefault(index_name, []).append(column_name)

    expected = ["tin", "tax_period_year", "tax_period_month", "is_fraud"]
    has_expected_index = any(columns[:4] == expected for columns in indexes.values())
    if not has_expected_index:
        current_app.logger.warning(
            "dashboard_gst.py :: Recommended index missing on "
            "gst_fraud_justification: (tin, tax_period_year, tax_period_month, is_fraud)"
        )
        _GST_PROVINCE_INDEX_WARNING_EMITTED = True
    _GST_PROVINCE_INDEX_CHECKED = True


# ============================================================
# A) Dashboard Summary Cards
# ============================================================
@bp.get("/data")
@jwt_required()
def dashboard_data():
    started_at = time.time()
    try:
        date_params = _get_period_bounds()
        start_year = date_params["start_year"]
        start_month = date_params["start_month"]
        end_year = date_params["end_year"]
        end_month = date_params["end_month"]

        query = text(f"""
            SELECT 
                COUNT(DISTINCT ag.tin) AS total_tax_payers,
                SUM(COALESCE(ag.total_sales_income, 0)) AS total_sales_income,
                SUM(COALESCE(ag.gst_payable, 0)) AS total_gst_payable,
                SUM(COALESCE(ag.gst_refundable, 0)) AS total_gst_refundable
            FROM gst_fraud_justification ag
            WHERE ag.tax_period_year BETWEEN :start_year AND :end_year
        """)

        payload = _cached_json(
            "dashboard_data",
            date_params,
            600,
            lambda: {
                "period_range": f"{start_month:02d}-{start_year} to {end_month:02d}-{end_year}",
                **{
                    "total_tax_payers": result["total_tax_payers"] or 0,
                    "total_sales_income": result["total_sales_income"] or 0,
                    "total_gst_payable": result["total_gst_payable"] or 0,
                    "total_gst_refundable": result["total_gst_refundable"] or 0,
                },
            }
            if (result := db.session.execute(query, date_params).mappings().one()) else {}
        )

        return jsonify(payload)
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        _log_timing("dashboard_data", started_at)


# ============================================================
# B) Sales Comparison
# ============================================================
@bp.get("/sales-comparison")
@jwt_required()
def sales_comparison():
    started_at = time.time()
    try:
        date_params = _get_period_bounds()
        use_yearly = _use_yearly_aggregation(date_params)

        if use_yearly:
            query = text(f"""
                SELECT 
                    filtered.tax_period_year,
                    SUM(filtered.total_sales_income) AS total_sales_income,
                    SUM(filtered.exempt_sales) AS exempt_sales,
                    SUM(filtered.zero_rated_sales) AS zero_rated_sales,
                    SUM(filtered.gst_taxable_sales) AS gst_taxable_sales
                FROM (
                    SELECT
                        pr.tax_period_year,
                        COALESCE(pr.total_sales_income, 0) AS total_sales_income,
                        COALESCE(pr.exempt_sales, 0) AS exempt_sales,
                        COALESCE(pr.zero_rated_sales, 0) AS zero_rated_sales,
                        COALESCE(pr.gst_taxable_sales, 0) AS gst_taxable_sales
                    FROM gst_fraud_justification pr
                    WHERE {_period_filter_sql("pr.tax_period_year", "pr.tax_period_month")}
                ) AS filtered
                GROUP BY filtered.tax_period_year
                ORDER BY filtered.tax_period_year
            """)
        else:
            query = text(f"""
                SELECT 
                    filtered.tax_period_year,
                    filtered.tax_period_month,
                    SUM(filtered.total_sales_income) AS total_sales_income,
                    SUM(filtered.exempt_sales) AS exempt_sales,
                    SUM(filtered.zero_rated_sales) AS zero_rated_sales,
                    SUM(filtered.gst_taxable_sales) AS gst_taxable_sales
                FROM (
                    SELECT
                        pr.tax_period_year,
                        pr.tax_period_month,
                        COALESCE(pr.total_sales_income, 0) AS total_sales_income,
                        COALESCE(pr.exempt_sales, 0) AS exempt_sales,
                        COALESCE(pr.zero_rated_sales, 0) AS zero_rated_sales,
                        COALESCE(pr.gst_taxable_sales, 0) AS gst_taxable_sales
                    FROM gst_fraud_justification pr
                    WHERE {_period_filter_sql("pr.tax_period_year", "pr.tax_period_month")}
                ) AS filtered
                GROUP BY filtered.tax_period_year, filtered.tax_period_month
                ORDER BY filtered.tax_period_year, filtered.tax_period_month
            """)

        payload = _cached_json(
            "sales_comparison",
            date_params,
            600,
            lambda: _build_sales_comparison_payload(query, date_params)
        )

        return jsonify(payload)
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        _log_timing("sales_comparison", started_at)


# ============================================================
# C) GST Payable vs Refundable
# ============================================================
@bp.get("/gst-payable-vs-refund")
@jwt_required()
def gst_payable_vs_refundable():
    started_at = time.time()
    try:
        date_params = _get_period_bounds()
        use_yearly = _use_yearly_aggregation(date_params)

        if use_yearly:
            query = text(f"""
                SELECT 
                    filtered.tax_period_year,
                    SUM(filtered.gst_payable) AS gst_payable,
                    SUM(filtered.gst_refundable) AS gst_refundable
                FROM (
                    SELECT
                        pr.tax_period_year,
                        COALESCE(pr.gst_payable, 0) AS gst_payable,
                        COALESCE(pr.gst_refundable, 0) AS gst_refundable
                    FROM gst_fraud_justification pr
                    WHERE {_period_filter_sql("pr.tax_period_year", "pr.tax_period_month")}
                ) AS filtered
                GROUP BY filtered.tax_period_year
                ORDER BY filtered.tax_period_year
            """)
        else:
            query = text(f"""
                SELECT 
                    filtered.tax_period_year,
                    filtered.tax_period_month,
                    SUM(filtered.gst_payable) AS gst_payable,
                    SUM(filtered.gst_refundable) AS gst_refundable
                FROM (
                    SELECT
                        pr.tax_period_year,
                        pr.tax_period_month,
                        COALESCE(pr.gst_payable, 0) AS gst_payable,
                        COALESCE(pr.gst_refundable, 0) AS gst_refundable
                    FROM gst_fraud_justification pr
                    WHERE {_period_filter_sql("pr.tax_period_year", "pr.tax_period_month")}
                ) AS filtered
                GROUP BY filtered.tax_period_year, filtered.tax_period_month
                ORDER BY filtered.tax_period_year, filtered.tax_period_month
            """)

        payload = _cached_json(
            "gst_payable_vs_refundable",
            date_params,
            600,
            lambda: _build_gst_payable_payload(query, date_params)
        )

        return jsonify(payload)
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        _log_timing("gst_payable_vs_refundable", started_at)


# ============================================================
# D) Segmentation Distribution (Pie)
# ============================================================
@bp.get("/segmentation-distribution")
@jwt_required()
def segmentation_distribution():
    started_at = time.time()
    try:
        date_params = _get_period_bounds()

        query = text(f"""
            SELECT
                COALESCE(sm.segmentation, 'Unknown') AS segment_label,
                COUNT(*) AS tin_count
            FROM (
                SELECT DISTINCT tin
                FROM gst_fraud_justification
                WHERE {_period_filter_sql("tax_period_year", "tax_period_month")}
            ) pr
            LEFT JOIN taxpayer_segmentation_master sm
                ON sm.tin = pr.tin
            GROUP BY COALESCE(sm.segmentation, 'Unknown')
        """)

        payload = _cached_json(
            "segmentation_distribution",
            date_params,
            300,
            lambda: _build_segmentation_payload(query, date_params)
        )

        return jsonify(payload)
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        _log_timing("segmentation_distribution", started_at)


# ============================================================
# E) Risk Flagged vs Non-Risk
# ============================================================
@bp.get("/risk-flagged")
@jwt_required()
def risk_flagged_vs_non():
    started_at = time.time()
    try:
        date_params = _get_period_bounds()

        query = text(f"""
            SELECT 
                SUM(CASE WHEN COALESCE(is_fraud, 0) = 1 THEN 1 ELSE 0 END) AS risk_flagged,
                SUM(CASE WHEN COALESCE(is_fraud, 0) = 0 THEN 1 ELSE 0 END) AS non_risk_flagged
            FROM gst_fraud_justification
            WHERE {_period_filter_sql("tax_period_year", "tax_period_month")}
        """)

        payload = _cached_json(
            "risk_flagged_vs_non",
            date_params,
            300,
            lambda: _build_risk_payload(query, date_params)
        )

        return jsonify(payload)
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        _log_timing("risk_flagged_vs_non", started_at)


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
    started_at = time.time()
    from datetime import datetime
    import pandas as pd, os

    try:
        date_params = _get_period_bounds()

        query = f"""
            SELECT
                p.tin AS tin_number,
                p.taxpayer_name,
                p.taxpayer_type,
                p.tax_period_year,
                p.tax_period_month,
                COALESCE(p.gst_payable, 0) AS gst_payable,
                COALESCE(p.gst_refundable, 0) AS gst_refundable,
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
            WHERE {_period_filter_sql("p.tax_period_year", "p.tax_period_month")}
            ORDER BY p.uploaded_at DESC, p.tin
            LIMIT 20;
        """

        rows = db.session.execute(text(query), date_params).mappings()

        data = []
        for r in rows:
            data.append({
                "tin_number": r["tin_number"],
                "taxpayer_name": r["taxpayer_name"],
                "taxpayer_type": r["taxpayer_type"],
                "tax_period_year": r["tax_period_year"],
                "tax_period_month": r["tax_period_month"],
                "gst_payable": float(r["gst_payable"] or 0),
                "gst_refundable": float(r["gst_refundable"] or 0),
                "segment_label": r["segment_label"],
                "risk_score": float(r["risk_score"] or 0),
                "flagged": "Yes" if r["is_flag"] else "No",
                "risk_type": r["risk_type"] or "Normal",
                "fraud_reason": r["fraud_reason"] or "",
                "created_at": str(r["created_at"])
            })

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
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        _log_timing("latest_tax_records", started_at)
    

# ============================================================
# F) Fraud Province Distribution
# ============================================================
@bp.get("/fraud-province-distribution")
@jwt_required()
def fraud_province_distribution():
    started_at = time.time()
    try:
        params = _get_period_bounds()
        _ensure_tin_province_lookup()
        try:
            _warn_if_gst_province_index_missing()
        except Exception as ex:
            current_app.logger.warning(
                "Skipping province index diagnostic: %s",
                ex,
                exc_info=True,
            )

        PROVINCE_STANDARD = {
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
            "HELA": "Hela",
            "JIWAKA": "Jiwaka",
            "CENTRAL": "Central",
            "CENTRAL PROVINCE": "Central",
            "ENGA": "Enga",
            "GULF": "Gulf",
            "MADANG": "Madang",
            "MOROBE": "Morobe",
        }

        def normalize_province(p):
            normalized = _normalize_unknown_label(p, "Unknown")
            if normalized == "Unknown":
                return normalized

            key = normalized.upper()
            if key in PROVINCE_STANDARD:
                return PROVINCE_STANDARD[key]

            cleaned = key.replace("PROVINCE", "").strip()
            if cleaned in PROVINCE_STANDARD:
                return PROVINCE_STANDARD[cleaned]

            return cleaned.title()

        start_year = params["start_year"]
        start_month = params["start_month"]
        end_year = params["end_year"]
        end_month = params["end_month"]

        province_sql = text(f"""
            SELECT
                lookup.province AS province,
                COUNT(*) AS total_tins,
                SUM(tin_data.is_fraud) AS fraud_tins
            FROM (
                SELECT
                    pr.tin,
                    MAX(COALESCE(pr.is_fraud, 0)) AS is_fraud
                FROM gst_fraud_justification pr
                WHERE {_period_filter_sql(
                    "pr.tax_period_year",
                    "pr.tax_period_month"
                )}
                GROUP BY pr.tin
            ) tin_data
            INNER JOIN tin_province_lookup lookup
                ON tin_data.tin = lookup.tin
            WHERE lookup.province IS NOT NULL
            AND lookup.province <> ''
            GROUP BY lookup.province
            ORDER BY lookup.province
        """)

        payload = _cached_json(
            "fraud_province_distribution",
            params,
            900,
            lambda: _build_province_payload(
                province_sql,
                params,
                normalize_province,
                start_month,
                start_year,
                end_month,
                end_year,
            )
        )

        return jsonify(payload)
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        _log_timing("fraud_province_distribution", started_at)



@download_bp.get("/sales-comparison")
@jwt_required()
def download_sales_comparison():
    started_at = time.time()
    params = _get_period_bounds()
    query = text("""
        SELECT 
            pr.tin AS tin,
            pr.taxpayer_name AS taxpayer_name,
            pr.tax_period_year,
            pr.tax_period_month,
            SUM(COALESCE(pr.total_sales_income, 0)) AS total_sales_income,
            SUM(COALESCE(pr.exempt_sales, 0)) AS exempt_sales,
            SUM(COALESCE(pr.zero_rated_sales, 0)) AS zero_rated_sales,
            SUM(COALESCE(pr.gst_taxable_sales, 0)) AS gst_taxable_sales
        FROM gst_fraud_justification pr
        WHERE (
            (
                pr.tax_period_year > :start_year
                OR (pr.tax_period_year = :start_year AND pr.tax_period_month >= :start_month)
            )
            AND
            (
                pr.tax_period_year < :end_year
                OR (pr.tax_period_year = :end_year AND pr.tax_period_month <= :end_month)
            )
        )
        GROUP BY pr.tin, pr.taxpayer_name, pr.tax_period_year, pr.tax_period_month
        ORDER BY pr.tax_period_year, pr.tax_period_month, pr.tin
    """)

    rows = _stream_mappings(query, params)

    data = [{
        "tin": r["tin"] or "",
        "taxpayer_name": r["taxpayer_name"] or None,
        "month": f"{int(r['tax_period_month']):02d}-{int(r['tax_period_year'])}",
        "total_sales": float(r["total_sales_income"] or 0),
        "exempt_sales": float(r["exempt_sales"] or 0),
        "zero_rated_sales": float(r["zero_rated_sales"] or 0),
        "taxable_sales": float(r["gst_taxable_sales"] or 0),
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
    try:
        return _build_csv_response(data, "sales-comparison.csv", columns)
    finally:
        _log_timing("download_sales_comparison", started_at)


@download_bp.get("/payable-vs-refundable")
@jwt_required()
def download_payable_vs_refundable():
    started_at = time.time()
    params = _get_period_bounds()
    query = text("""
        SELECT 
            pr.tin AS tin,
            pr.taxpayer_name AS taxpayer_name,
            pr.tax_period_year,
            pr.tax_period_month,
            SUM(COALESCE(pr.gst_payable, 0)) AS gst_payable,
            SUM(COALESCE(pr.gst_refundable, 0)) AS gst_refundable
        FROM gst_fraud_justification pr
        WHERE (
            (
                pr.tax_period_year > :start_year
                OR (pr.tax_period_year = :start_year AND pr.tax_period_month >= :start_month)
            )
            AND
            (
                pr.tax_period_year < :end_year
                OR (pr.tax_period_year = :end_year AND pr.tax_period_month <= :end_month)
            )
        )
        GROUP BY pr.tin, pr.taxpayer_name, pr.tax_period_year, pr.tax_period_month
        ORDER BY pr.tax_period_year, pr.tax_period_month, pr.tin
    """)

    rows = _stream_mappings(query, params)

    data = [{
        "tin": r["tin"] or "",
        "taxpayer_name": r["taxpayer_name"] or None,
        "month": f"{int(r['tax_period_month']):02d}-{int(r['tax_period_year'])}",
        "gst_payable": float(r["gst_payable"] or 0),
        "gst_refundable": float(r["gst_refundable"] or 0),
    } for r in rows]

    _debug_csv_sample("gst-payable-vs-refundable", data)
    allowed = ["tin", "taxpayer_name", "month", "gst_payable", "gst_refundable"]
    columns = _parse_columns(["month", "gst_payable", "gst_refundable"], allowed, include_ids=True)
    try:
        return _build_csv_response(data, "payable-vs-refundable.csv", columns)
    finally:
        _log_timing("download_payable_vs_refundable", started_at)


@download_bp.get("/segmentation")
@jwt_required()
def download_segmentation_distribution():
    started_at = time.time()
    params = _get_period_bounds()
    query = text("""
        SELECT
            pr.tin,
            COALESCE(NULLIF(TRIM(sm.taxpayer_name), ''), pr.taxpayer_name, 'Unknown') AS taxpayer_name,
            COALESCE(sm.segmentation, 'Unknown') AS segment
        FROM (
            SELECT
                tin,
                MAX(NULLIF(TRIM(taxpayer_name), '')) AS taxpayer_name
            FROM gst_fraud_justification
            WHERE (
                (
                    tax_period_year > :start_year
                    OR (tax_period_year = :start_year AND tax_period_month >= :start_month)
                )
                AND
                (
                    tax_period_year < :end_year
                    OR (tax_period_year = :end_year AND tax_period_month <= :end_month)
                )
            )
            GROUP BY tin
        ) pr
        LEFT JOIN taxpayer_segmentation_master sm
            ON sm.tin = pr.tin
        ORDER BY pr.tin
    """)

    rows = _stream_mappings(query, params)

    data = [{
        "tin": r["tin"] or "",
        "taxpayer_name": r["taxpayer_name"] or None,
        "segment": r["segment"] or None,
    } for r in rows]

    _debug_csv_sample("gst-segmentation", data)
    allowed = ["tin", "taxpayer_name", "segment"]
    columns = _parse_columns(["segment"], allowed, include_ids=True)
    try:
        return _build_csv_response(data, "segmentation.csv", columns)
    finally:
        _log_timing("download_segmentation_distribution", started_at)


@download_bp.get("/risk-flagged")
@jwt_required()
def download_risk_flagged():
    started_at = time.time()
    params = _get_period_bounds()
    query = text("""
        SELECT 
            pr.tin AS tin,
            pr.taxpayer_name AS taxpayer_name,
            pr.is_fraud AS risk_flag,
            COUNT(*) AS count
        FROM gst_fraud_justification pr
        WHERE (
            (
                pr.tax_period_year > :start_year
                OR (pr.tax_period_year = :start_year AND pr.tax_period_month >= :start_month)
            )
            AND
            (
                pr.tax_period_year < :end_year
                OR (pr.tax_period_year = :end_year AND pr.tax_period_month <= :end_month)
            )
        )
        GROUP BY pr.tin, pr.taxpayer_name, pr.is_fraud
        ORDER BY pr.tin
    """)

    rows = _stream_mappings(query, params)

    data = [{
        "tin": r["tin"] or "",
        "taxpayer_name": r["taxpayer_name"] or None,
        "risk_flag": "Risk Flagged" if int(r["risk_flag"] or 0) == 1 else "Non-Risk Flagged",
        "count": int(r["count"] or 0)
    } for r in rows]

    _debug_csv_sample("gst-risk-flagged", data)

    allowed = ["tin", "taxpayer_name", "risk_flag", "count"]
    columns = _parse_columns(["risk_flag", "count"], allowed, include_ids=True)
    try:
        return _build_csv_response(data, "risk-flagged.csv", columns)
    finally:
        _log_timing("download_risk_flagged", started_at)


@download_bp.get("/province")
@jwt_required()
def download_province_distribution():
    started_at = time.time()
    try:
        params = _get_period_bounds()

        sql = text("""
            SELECT
                pr.tin,
                MAX(pr.taxpayer_name) AS taxpayer_name,
                tr.province,
                CASE
                    WHEN MAX(COALESCE(pr.is_fraud, 0)) = 1
                    THEN 'Fraud'
                    ELSE 'Non-Fraud'
                END AS predicted_fraud,
                MAX(pr.explanation) AS explanation
            FROM gst_fraud_justification pr
            INNER JOIN tin_province_lookup tr
                ON pr.tin = tr.tin
            WHERE (
                    (
                        pr.tax_period_year > :start_year
                        OR (
                            pr.tax_period_year = :start_year
                            AND pr.tax_period_month >= :start_month
                        )
                    )
                    AND
                    (
                        pr.tax_period_year < :end_year
                        OR (
                            pr.tax_period_year = :end_year
                            AND pr.tax_period_month <= :end_month
                        )
                    )
            )
            GROUP BY pr.tin, tr.province
            ORDER BY tr.province, taxpayer_name
        """)

        rows = _stream_mappings(sql, params)

        data = [
            {
                "tin": row["tin"],
                "taxpayer_name": row["taxpayer_name"],
                "province": row["province"],
                "predicted_fraud": row["predicted_fraud"] or "",
                "explanation": row["explanation"] or ""
            }
            for row in rows
        ]

        columns = [
            "tin",
            "taxpayer_name",
            "province",
            "predicted_fraud",
            "explanation"
        ]

        _debug_csv_sample("gst-province", data)

        filename = f"province_distribution_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return _build_csv_response(
            data,
            filename,
            columns
        )
    finally:
        _log_timing("download_province_distribution", started_at)



