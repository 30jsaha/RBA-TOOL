from flask import Blueprint, current_app, g, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy import text
from datetime import datetime
from dateutil.relativedelta import relativedelta
from functools import wraps
import re
import time
from ..extensions import cache, db

bp = Blueprint("risk_assessment", __name__, url_prefix="/api/risk-assessment")

_CACHE_TIMEOUTS = {
    "risk_assessment_filters": 600,
    "risk_analysis_by_industry": 900,
    "risk_analysis_by_category": 900,
    "taxpayer_vs_risk": 900,
    "frequency_of_risk_anomalies": 900,
    "top_fraud_companies": 900,
}


@bp.before_request
def _risk_before_request():
    g.risk_started_at = time.time()
    g.risk_cache_key = None
    if request.method != "GET":
        return None

    endpoint_name = request.endpoint.rsplit(".", 1)[-1] if request.endpoint else None
    timeout = _CACHE_TIMEOUTS.get(endpoint_name)
    if not timeout:
        return None

    key = _cache_key(endpoint_name, dict(_request_cache_args()))
    g.risk_cache_key = key
    cached_payload = cache.get(key)
    if cached_payload is not None:
        current_app.logger.info("risk_assessment.py :: %s cache=hit key=%s", endpoint_name, key)
        return jsonify(cached_payload)

    current_app.logger.info("risk_assessment.py :: %s cache=miss key=%s", endpoint_name, key)
    return None


@bp.after_request
def _risk_after_request(response):
    endpoint_name = request.endpoint.rsplit(".", 1)[-1] if request.endpoint else "unknown"
    key = getattr(g, "risk_cache_key", None)
    if key and response.status_code == 200 and response.is_json:
        try:
            serialization_started = time.time()
            payload = response.get_json()
            response.get_data()
            current_app.logger.info("risk_assessment.py :: %s serialization_time=%.4fs", endpoint_name, time.time() - serialization_started)
            cache.set(key, payload, timeout=_CACHE_TIMEOUTS[endpoint_name])
        except Exception:
            current_app.logger.exception("risk_assessment.py :: failed to cache response")

    started_at = getattr(g, "risk_started_at", None)
    if started_at is not None:
        current_app.logger.info(
            "risk_assessment.py :: %s total_request_time=%.4fs status=%s",
            endpoint_name,
            time.time() - started_at,
            response.status_code,
        )
    return response


def get_requested_taxtype(default="gst"):
    value = request.args.get("taxtype", default)
    return (value or "").lower()


_DEFAULT_PERIOD_CACHE = {}


def _request_cache_args():
    return tuple(sorted((key, value) for key, value in request.args.items() if value not in (None, "")))


def _cache_key(endpoint_name, params=None):
    parts = [f"risk_assessment:{endpoint_name}", f"taxtype={get_requested_taxtype('gst')}"]
    if params:
        for key in sorted(params):
            parts.append(f"{key}={params[key]}")
    for key, value in _request_cache_args():
        parts.append(f"{key}={value}")
    return "|".join(parts)


def _log_timing(endpoint_name, started_at):
    current_app.logger.info(
        "risk_assessment.py :: %s total_request_time=%.4fs",
        endpoint_name,
        time.time() - started_at,
    )


def _cache_timeout(endpoint_name):
    return 600 if endpoint_name == "filters" else 900


def _cached_json(endpoint_name, params, timeout, builder):
    key = _cache_key(endpoint_name, params)
    cached_payload = cache.get(key)
    if cached_payload is not None:
        current_app.logger.info("risk_assessment.py :: %s cache=hit key=%s", endpoint_name, key)
        return cached_payload

    current_app.logger.info("risk_assessment.py :: %s cache=miss key=%s", endpoint_name, key)
    payload = builder()
    cache.set(key, payload, timeout=timeout)
    return payload


def log_sql(query, params=None, sql_time=None, row_count=None, stream=False):
    current_app.logger.info(
        "risk_assessment.py :: sql stream=%s rows=%s sql_time=%.4fs sql=%s params=%s",
        stream,
        row_count if row_count is not None else "n/a",
        sql_time or 0,
        " ".join((query.text or "").split()),
        params or {},
    )


def execute_fetchall(query, params=None):
    params = params or {}
    started_at = time.time()
    rows = db.session.execute(query, params).fetchall()
    log_sql(query, params, sql_time=time.time() - started_at, row_count=len(rows))
    return rows


def execute_fetchone(query, params=None):
    params = params or {}
    started_at = time.time()
    row = db.session.execute(query, params).fetchone()
    log_sql(query, params, sql_time=time.time() - started_at, row_count=1 if row else 0)
    return row


def execute_mappings_all(query, params=None):
    params = params or {}
    started_at = time.time()
    rows = db.session.execute(query, params).mappings().all()
    log_sql(query, params, sql_time=time.time() - started_at, row_count=len(rows))
    return rows


def execute_stream_mappings(query, params=None):
    params = params or {}
    started_at = time.time()
    rows = db.session.execute(query.execution_options(stream_results=True), params).mappings().all()
    log_sql(query, params, sql_time=time.time() - started_at, row_count=len(rows), stream=True)
    return rows


def _period_filter_sql(alias="pr"):
    return f"""
        ({alias}.tax_period_year > :start_year OR ({alias}.tax_period_year = :start_year AND {alias}.tax_period_month >= :start_month))
        AND
        ({alias}.tax_period_year < :end_year OR ({alias}.tax_period_year = :end_year AND {alias}.tax_period_month <= :end_month))
    """


def _year_filter_sql(alias="pr"):
    return f"{alias}.tax_period_year >= :start_year AND {alias}.tax_period_year <= :end_year"


def _swt_cit_fraud_sql(alias="pr", default_normal=False):
    default_value = "'normal'" if default_normal else "''"
    return f"LOWER(COALESCE({alias}.predicted_fraud, {default_value})) = 'fraud'"



def _registration_sector_sql(alias="trm"):
    return f"COALESCE(NULLIF(TRIM({alias}.enterpriseactivity), ''), 'Unknown')"


def _registration_segment_sql(alias="trm"):
    return f"COALESCE(NULLIF(TRIM({alias}.taxpayertype), ''), 'Unknown')"


def _get_default_period_bounds(taxtype):
    cached = _DEFAULT_PERIOD_CACHE.get(taxtype)
    if cached is not None:
        return cached

    now = datetime.now()
    if taxtype in {"gst", "swt"}:
        table = "gst_fraud_justification" if taxtype == "gst" else "swt_fraud_justification"
        row = execute_fetchone(text(f"""
            SELECT tax_period_year, tax_period_month
            FROM {table}
            ORDER BY tax_period_year ASC, tax_period_month ASC
            LIMIT 1
        """))
        row_max = execute_fetchone(text(f"""
            SELECT tax_period_year, tax_period_month
            FROM {table}
            ORDER BY tax_period_year DESC, tax_period_month DESC
            LIMIT 1
        """))
        if row and row_max:
            cached = (row.tax_period_year, row.tax_period_month, row_max.tax_period_year, row_max.tax_period_month)
        else:
            cached = (now.year, now.month, now.year, now.month)
    elif taxtype == "cit":
        row = execute_fetchone(text("""
            SELECT tax_period_year
            FROM cit_fraud_justification
            ORDER BY tax_period_year ASC
            LIMIT 1
        """))
        row_max = execute_fetchone(text("""
            SELECT tax_period_year
            FROM cit_fraud_justification
            ORDER BY tax_period_year DESC
            LIMIT 1
        """))
        if row and row_max:
            cached = (row.tax_period_year, 1, row_max.tax_period_year, 12)
        else:
            cached = (now.year, now.month, now.year, now.month)
    else:
        cached = (now.year, now.month, now.year, now.month)

    _DEFAULT_PERIOD_CACHE[taxtype] = cached
    return cached


# ============================================================
# Enhanced Helper: Date Range (supports full custom filters)
# ============================================================
def get_date_range(taxtype=None):
    """
    Handles '1m', '3m', '6m', '1y', and 'custom' ranges dynamically.
    Returns accurate (start_year, start_month, end_year, end_month)
    to filter using tax_period_year and tax_period_month fields.
    """
    now = datetime.now()
    range_type = request.args.get("range_type")
    if range_type:
        range_type = range_type.lower()
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    # Default: show all available data for the tax type
    if not range_type or range_type == "all":
        return _get_default_period_bounds(taxtype)

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
        start = now.replace(day=1)
        end = now

    # Round start_date to first day of month and end_date to last day of month
    start = start.replace(day=1)
    next_month = (end.replace(day=28) + relativedelta(days=4)).replace(day=1)
    end = next_month - relativedelta(days=1)

    return start.year, start.month, end.year, end.month


def get_tables():
    taxtype = get_requested_taxtype("gst")

    table_map = {
        "gst": {
            "predicted": "gst_fraud_justification",
            "flagged": "flagged_audit_records",
            "tin_column": "tin"
        },
        "swt": {
            "predicted": "swt_fraud_justification",
            "flagged": "flagged_audit_records_swt",
            "tin_column": "tin"
        },
        "cit": {
            "predicted": "cit_fraud_justification",
            "flagged": "flagged_audit_records_cit",
            "tin_column": "tin"
        }
    }

    return table_map.get(taxtype, table_map["gst"])



@bp.get("/filters")
@jwt_required()
def risk_assessment_filters():
    taxtype = get_requested_taxtype("gst")
    start_year, start_month, end_year, end_month = get_date_range(taxtype)
    params = {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month,
    }

    if taxtype in {"gst", "swt"}:
        table = "gst_fraud_justification" if taxtype == "gst" else "swt_fraud_justification"
        rows = execute_fetchall(
            text(f"""
                SELECT pr.tax_period_year, pr.tax_period_month
                FROM {table} pr
                WHERE {_period_filter_sql('pr')}
                GROUP BY pr.tax_period_year, pr.tax_period_month
                ORDER BY pr.tax_period_year, pr.tax_period_month
            """),
            params,
        )

        years = sorted({int(row.tax_period_year) for row in rows})
        months = sorted({int(row.tax_period_month) for row in rows})
        return jsonify({"years": years, "tins": [], "months": months})

    if taxtype == "cit":
        year_rows = execute_fetchall(
            text(f"""
                SELECT pr.tax_period_year
                FROM cit_fraud_justification pr
                WHERE {_year_filter_sql('pr')}
                GROUP BY pr.tax_period_year
                ORDER BY pr.tax_period_year
            """),
            params,
        )
        return jsonify({
            "years": [int(row.tax_period_year) for row in year_rows],
            "tins": [],
            "months": [],
        })

    return jsonify({"years": [], "tins": [], "months": []})


# ============================================================
# G) Risk Analysis by Industry (Sector-based Risk - FIXED)
# ============================================================

@bp.get("/industry")
@jwt_required()
def risk_analysis_by_industry():
    taxtype = get_requested_taxtype("")
    start_year, start_month, end_year, end_month = get_date_range(taxtype)
    params = {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month,
    }

    if taxtype == "gst":
        query = text(f"""
            WITH taxpayer_rollup AS (
                SELECT
                    pr.tin,
                    SUM(COALESCE(pr.total_sales_income, 0)) AS total_sales,
                    MAX(CASE WHEN COALESCE(pr.is_fraud, 0) = 1 THEN 1 ELSE 0 END) AS risk_flagged
                FROM gst_fraud_justification pr
                WHERE {_period_filter_sql('pr')}
                GROUP BY pr.tin
            )
            SELECT
                {_registration_sector_sql('trm')} AS sector,
                COUNT(*) AS total_taxpayers,
                SUM(taxpayer_rollup.risk_flagged) AS risk_flagged,
                SUM(taxpayer_rollup.total_sales) AS total_sales
            FROM taxpayer_rollup
            LEFT JOIN tin_registration_mst trm
                ON taxpayer_rollup.tin = trm.tin
            GROUP BY sector
            ORDER BY total_sales DESC
        """)
    elif taxtype == "swt":
        sector_expr = _registration_sector_sql('trm')
        query = text(f"""
            WITH taxpayer_rollup AS (
                SELECT
                    pr.tin,
                    SUM(COALESCE(pr.total_salary_wages_paid, 0)) AS total_sales,
                    MAX(CASE WHEN {_swt_cit_fraud_sql('pr')} THEN 1 ELSE 0 END) AS risk_flagged
                FROM swt_fraud_justification pr
                WHERE {_period_filter_sql('pr')}
                GROUP BY pr.tin
            )
            SELECT
                {sector_expr} AS sector,
                COUNT(*) AS total_taxpayers,
                SUM(taxpayer_rollup.risk_flagged) AS risk_flagged,
                SUM(taxpayer_rollup.total_sales) AS total_sales
            FROM taxpayer_rollup
            LEFT JOIN tin_registration_mst trm
                ON CAST(taxpayer_rollup.tin AS CHAR(50)) = CAST(trm.tin AS CHAR(50))
            GROUP BY {sector_expr}
            ORDER BY total_sales DESC
        """)
    elif taxtype == "cit":
        query = text(f"""
            WITH taxpayer_rollup AS (
                SELECT
                    pr.tin,
                    SUM(COALESCE(pr.total_gross_income, 0)) AS total_sales,
                    MAX(CASE WHEN {_swt_cit_fraud_sql('pr')} THEN 1 ELSE 0 END) AS risk_flagged
                FROM cit_fraud_justification pr
                WHERE {_year_filter_sql('pr')}
                GROUP BY pr.tin
            )
            SELECT
                {_registration_sector_sql('trm')} AS sector,
                COUNT(*) AS total_taxpayers,
                SUM(taxpayer_rollup.risk_flagged) AS risk_flagged,
                SUM(taxpayer_rollup.total_sales) AS total_sales
            FROM taxpayer_rollup
            LEFT JOIN tin_registration_mst trm
                ON taxpayer_rollup.tin = trm.tin
            GROUP BY sector
            ORDER BY total_sales DESC
        """)
    else:
        return jsonify({"error": "Invalid taxtype"}), 400

    try:
        rows = execute_fetchall(query, params)
    except Exception as exc:
        current_app.logger.exception(
            "risk_analysis_by_industry failed; taxtype=%s; sql=%s; params=%s",
            taxtype,
            query.text if query is not None else None,
            params,
        )
        return jsonify({"error": str(exc)}), 500

    return jsonify([
        {
            "sector": r.sector,
            "total_taxpayers": int(r.total_taxpayers or 0),
            "risk_flagged": int(r.risk_flagged or 0),
            "risk_percentage": round((int(r.risk_flagged or 0) / int(r.total_taxpayers or 1)) * 100, 2),
            "total_sales": float(r.total_sales or 0),
        }
        for r in rows
    ])


# ============================================================
# H) Risk Analysis by Category (Segment-based Risk)
# ============================================================

@bp.get("/category")
@jwt_required()
def risk_analysis_by_category():
    taxtype = get_requested_taxtype("")
    start_year, start_month, end_year, end_month = get_date_range(taxtype)
    params = {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month,
    }

    if taxtype == "gst":
        query = text(f"""
            SELECT
                COALESCE(NULLIF(TRIM(pr.taxpayer_type), ''), 'Unknown') AS segment_label,
                COUNT(*) AS total_records,
                SUM(CASE WHEN COALESCE(pr.is_fraud, 0) = 1 THEN 1 ELSE 0 END) AS flagged_records
            FROM gst_fraud_justification pr
            WHERE {_period_filter_sql('pr')}
            GROUP BY segment_label
            ORDER BY flagged_records DESC
        """)
    elif taxtype == "swt":
        segment_expr = _registration_segment_sql('trm')
        query = text(f"""
            WITH taxpayer_rollup AS (
                SELECT
                    pr.tin,
                    COUNT(*) AS total_records,
                    SUM(CASE WHEN {_swt_cit_fraud_sql('pr')} THEN 1 ELSE 0 END) AS flagged_records
                FROM swt_fraud_justification pr
                WHERE {_period_filter_sql('pr')}
                GROUP BY pr.tin
            )
            SELECT
                {segment_expr} AS segment_label,
                SUM(taxpayer_rollup.total_records) AS total_records,
                SUM(taxpayer_rollup.flagged_records) AS flagged_records
            FROM taxpayer_rollup
            LEFT JOIN tin_registration_mst trm
                ON CAST(taxpayer_rollup.tin AS CHAR(50)) = CAST(trm.tin AS CHAR(50))
            GROUP BY {segment_expr}
            ORDER BY flagged_records DESC
        """)
    elif taxtype == "cit":
        query = text(f"""
            WITH taxpayer_rollup AS (
                SELECT
                    pr.tin,
                    COUNT(*) AS total_records,
                    SUM(CASE WHEN {_swt_cit_fraud_sql('pr')} THEN 1 ELSE 0 END) AS flagged_records
                FROM cit_fraud_justification pr
                WHERE {_year_filter_sql('pr')}
                GROUP BY pr.tin
            )
            SELECT
                {_registration_segment_sql('trm')} AS segment_label,
                SUM(taxpayer_rollup.total_records) AS total_records,
                SUM(taxpayer_rollup.flagged_records) AS flagged_records
            FROM taxpayer_rollup
            LEFT JOIN tin_registration_mst trm
                ON taxpayer_rollup.tin = trm.tin
            GROUP BY segment_label
            ORDER BY flagged_records DESC
        """)
    else:
        return jsonify({"error": "Invalid taxtype"}), 400

    try:
        rows = execute_fetchall(query, params)
    except Exception as exc:
        current_app.logger.exception(
            "risk_analysis_by_category failed; taxtype=%s; sql=%s; params=%s",
            taxtype,
            query.text if query is not None else None,
            params,
        )
        return jsonify({"error": str(exc)}), 500

    result = [
        {
            "segment_label": str(r.segment_label).strip() if hasattr(r, "segment_label") else "Unknown",
            "total_records": int(r.total_records or 0),
            "flagged_records": int(r.flagged_records or 0),
            "flagged_percentage": round((int(r.flagged_records or 0) / int(r.total_records or 1)) * 100, 2),
        }
        for r in rows
    ]
    return jsonify(result)


#===========================================================
# Download Segment Risk as CSV
#===========================================================

@bp.get("/download-segment-risk")
@jwt_required()
def download_segment_risk():
    taxtype = get_requested_taxtype("")
    start_year, start_month, end_year, end_month = get_date_range(taxtype)
    params = {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month,
    }

    if taxtype == "gst":
        query = text(f"""
            SELECT
                CASE WHEN CAST(pr.tin AS CHAR(30)) REGEXP '^[0-9]+$' THEN CAST(pr.tin AS CHAR(30)) ELSE NULL END AS tin,
                COALESCE(NULLIF(TRIM(pr.taxpayer_name),''), 'Unknown') AS taxpayer_name,
                COALESCE(NULLIF(TRIM(pr.taxpayer_type),''), 'Unknown') AS segment,
                pr.tax_period_year,
                pr.tax_period_month
            FROM gst_fraud_justification pr
            WHERE pr.taxpayer_type IS NOT NULL
              AND pr.taxpayer_type <> ''
              AND {_period_filter_sql('pr')}
            GROUP BY tin, taxpayer_name, segment, pr.tax_period_year, pr.tax_period_month
            ORDER BY segment, tin, pr.tax_period_year, pr.tax_period_month
        """)
        rows = execute_fetchall(query, params)
    elif taxtype == "swt":
        query = text(f"""
            WITH base_rows AS (
                SELECT
                    CAST(pr.tin AS CHAR(30)) AS tin,
                    COALESCE(NULLIF(TRIM(pr.taxpayer_name),''), 'Unknown') AS taxpayer_name,
                    pr.tax_period_year,
                    pr.tax_period_month
                FROM swt_fraud_justification pr
                WHERE {_period_filter_sql('pr')}
                GROUP BY pr.tin, taxpayer_name, pr.tax_period_year, pr.tax_period_month
            )
            SELECT
                CASE WHEN base_rows.tin REGEXP '^[0-9]+$' THEN base_rows.tin ELSE NULL END AS tin,
                base_rows.taxpayer_name,
                {_registration_segment_sql('trm')} AS segment,
                base_rows.tax_period_year,
                base_rows.tax_period_month
            FROM base_rows
            LEFT JOIN tin_registration_mst trm
                ON base_rows.tin = trm.tin
            ORDER BY segment, tin, base_rows.tax_period_year, base_rows.tax_period_month
        """)
        rows = execute_fetchall(query, params)
    elif taxtype == "cit":
        query = text(f"""
            WITH base_rows AS (
                SELECT
                    CAST(pr.tin AS CHAR(30)) AS tin,
                    COALESCE(NULLIF(TRIM(pr.taxpayer),''), 'Unknown') AS taxpayer_name,
                    pr.tax_period_year,
                    12 AS tax_period_month
                FROM cit_fraud_justification pr
                WHERE {_year_filter_sql('pr')}
                GROUP BY pr.tin, taxpayer_name, pr.tax_period_year
            )
            SELECT
                base_rows.tin,
                base_rows.taxpayer_name,
                {_registration_segment_sql('trm')} AS segment,
                base_rows.tax_period_year,
                base_rows.tax_period_month
            FROM base_rows
            LEFT JOIN tin_registration_mst trm
                ON base_rows.tin = trm.tin
            ORDER BY segment, tin, base_rows.tax_period_year
        """)
        rows = execute_fetchall(query, params)
    else:
        return jsonify({"error": "Invalid taxtype"}), 400

    formatted = [
        {
            "tin": r.tin,
            "taxpayer_name": r.taxpayer_name,
            "segment": r.segment,
            "tax_period_year": r.tax_period_year,
            "tax_period_month": r.tax_period_month,
        }
        for r in rows
    ]
    return jsonify({"count": len(formatted), "rows": formatted})


# ============================================================
# I) Total Taxpayers vs Risk Flagged (Line Chart)
# ============================================================

@bp.get("/taxpayer-vs-risk")
@jwt_required()
def taxpayer_vs_risk():
    taxtype = get_requested_taxtype("")
    start_year, start_month, end_year, end_month = get_date_range(taxtype)
    params = {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month,
    }

    if taxtype == "gst":
        query = text(f"""
            WITH taxpayer_period AS (
                SELECT
                    pr.tax_period_year,
                    pr.tax_period_month,
                    pr.tin,
                    MAX(CASE WHEN COALESCE(pr.is_fraud, 0) = 1 THEN 1 ELSE 0 END) AS risk_flagged
                FROM gst_fraud_justification pr
                WHERE {_period_filter_sql('pr')}
                GROUP BY pr.tax_period_year, pr.tax_period_month, pr.tin
            )
            SELECT
                CONCAT(LPAD(taxpayer_period.tax_period_month, 2, '0'), '-', taxpayer_period.tax_period_year) AS month_label,
                COUNT(*) AS total_taxpayers,
                SUM(taxpayer_period.risk_flagged) AS risk_flagged
            FROM taxpayer_period
            GROUP BY taxpayer_period.tax_period_year, taxpayer_period.tax_period_month
            ORDER BY taxpayer_period.tax_period_year, taxpayer_period.tax_period_month
        """)
    elif taxtype == "swt":
        query = text(f"""
            WITH taxpayer_period AS (
                SELECT
                    pr.tax_period_year,
                    pr.tax_period_month,
                    pr.tin,
                    MAX(CASE WHEN {_swt_cit_fraud_sql('pr')} THEN 1 ELSE 0 END) AS risk_flagged
                FROM swt_fraud_justification pr
                WHERE {_period_filter_sql('pr')}
                GROUP BY pr.tax_period_year, pr.tax_period_month, pr.tin
            )
            SELECT
                CONCAT(LPAD(taxpayer_period.tax_period_month, 2, '0'), '-', taxpayer_period.tax_period_year) AS month_label,
                COUNT(*) AS total_taxpayers,
                SUM(taxpayer_period.risk_flagged) AS risk_flagged
            FROM taxpayer_period
            GROUP BY taxpayer_period.tax_period_year, taxpayer_period.tax_period_month
            ORDER BY taxpayer_period.tax_period_year, taxpayer_period.tax_period_month
        """)
    elif taxtype == "cit":
        query = text(f"""
            WITH taxpayer_period AS (
                SELECT
                    pr.tax_period_year,
                    pr.tin,
                    MAX(CASE WHEN {_swt_cit_fraud_sql('pr')} THEN 1 ELSE 0 END) AS risk_flagged
                FROM cit_fraud_justification pr
                WHERE {_year_filter_sql('pr')}
                GROUP BY pr.tax_period_year, pr.tin
            )
            SELECT
                taxpayer_period.tax_period_year,
                12 AS tax_period_month,
                COUNT(*) AS total_taxpayers,
                SUM(taxpayer_period.risk_flagged) AS risk_flagged
            FROM taxpayer_period
            GROUP BY taxpayer_period.tax_period_year
            ORDER BY taxpayer_period.tax_period_year
        """)
    else:
        return jsonify({"error": "Invalid taxtype"}), 400

    try:
        rows = execute_fetchall(query, params)
    except Exception as e:
        print("[RISK ASSESSMENT ERROR]", str(e))
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "labels": [str(r.tax_period_year) if taxtype == "cit" else r.month_label for r in rows],
        "total_series": [int(r.total_taxpayers or 0) for r in rows],
        "flagged_series": [int(r.risk_flagged or 0) for r in rows],
    })


# ============================================================
# J) Frequency of Risk Anomalies (Pie Chart)
# ============================================================

@bp.get("/frequency-anomalies")
@jwt_required()
def frequency_of_risk_anomalies():
    taxtype = get_requested_taxtype("")
    start_year, start_month, end_year, end_month = get_date_range(taxtype)
    filters = {
        "year": (request.args.get("year") or "").strip(),
        "month": (request.args.get("month") or "").strip(),
    }
    params = {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month,
    }

    if taxtype == "gst":
        where_clauses = [_period_filter_sql('pr')]
        if filters.get("year"):
            where_clauses.append("pr.tax_period_year = :filter_year")
            params["filter_year"] = int(filters["year"])
        if filters.get("month"):
            where_clauses.append("pr.tax_period_month = :filter_month")
            params["filter_month"] = int(filters["month"])
        query = text(f"""
            SELECT
                SUM(pr.exempt_sales > pr.total_sales_income * 0.5) AS anomaly_1_count,
                SUM(pr.gst_payable < pr.total_sales_income * 0.01) AS anomaly_2_count
            FROM gst_fraud_justification pr
            WHERE {' AND '.join(where_clauses)}
        """)
        labels = ["Excessive Exempt Sales", "Suspiciously Low Output"]
    elif taxtype == "swt":
        where_clauses = [_period_filter_sql('pr')]
        if filters.get("year"):
            where_clauses.append("pr.tax_period_year = :filter_year")
            params["filter_year"] = int(filters["year"])
        if filters.get("month"):
            where_clauses.append("pr.tax_period_month = :filter_month")
            params["filter_month"] = int(filters["month"])
        query = text(f"""
            SELECT
                SUM(pr.employees_paid_swt > pr.employees_on_payroll) AS anomaly_1_count,
                SUM(pr.total_swt_tax_deducted > pr.total_salary_wages_paid * 0.40) AS anomaly_2_count
            FROM swt_fraud_justification pr
            WHERE {' AND '.join(where_clauses)}
        """)
        labels = ["Ghost Employees", "Excessive Tax"]
    elif taxtype == "cit":
        where_clauses = [_year_filter_sql('pr')]
        if filters.get("year"):
            where_clauses.append("pr.tax_period_year = :filter_year")
            params["filter_year"] = int(filters["year"])
        query = text(f"""
            SELECT
                COUNT(DISTINCT CASE WHEN {_swt_cit_fraud_sql('pr')} THEN pr.tin END) AS anomaly_1_count,
                COUNT(DISTINCT CASE WHEN NOT {_swt_cit_fraud_sql('pr', default_normal=True)} THEN pr.tin END) AS anomaly_2_count
            FROM cit_fraud_justification pr
            WHERE {' AND '.join(where_clauses)}
        """)
        labels = ["Predicted Fraud", "Predicted Normal"]
    else:
        return jsonify({"error": "Invalid taxtype"}), 400

    try:
        row = execute_fetchone(query, params)
    except Exception as e:
        print("[RISK ASSESSMENT ERROR]", str(e))
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "labels": labels,
        "values": [int(row.anomaly_1_count or 0), int(row.anomaly_2_count or 0)],
    })


# ============================================================
# K) Top 10 Fraud Companies (is_flag = 1)
# ============================================================

@bp.get("/top-fraud-companies")
@jwt_required()
def top_fraud_companies():
    taxtype = get_requested_taxtype("")
    start_year, start_month, end_year, end_month = get_date_range(taxtype)
    params = {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month,
    }

    if taxtype == "gst":
        query = text(f"""
            WITH flagged_taxpayers AS (
                SELECT
                    pr.tin,
                    MAX(COALESCE(NULLIF(TRIM(pr.taxpayer_name), ''), 'Unknown')) AS taxpayer_name,
                    SUM(COALESCE(pr.total_sales_income, 0)) AS total_sales,
                    COUNT(*) AS total_flags,
                    COUNT(DISTINCT pr.taxpayer_type) AS segments
                FROM gst_fraud_justification pr
                WHERE COALESCE(pr.is_fraud, 0) = 1
                  AND {_period_filter_sql('pr')}
                GROUP BY pr.tin
            )
            SELECT CAST(tin AS CHAR(30)) AS tin, taxpayer_name, total_sales, total_flags, segments
            FROM flagged_taxpayers
            ORDER BY total_flags DESC, total_sales DESC
            LIMIT 10
        """)
    elif taxtype == "swt":
        query = text(f"""
            WITH flagged_taxpayers AS (
                SELECT
                    pr.tin,
                    MAX(COALESCE(NULLIF(TRIM(pr.taxpayer_name), ''), 'Unknown')) AS taxpayer_name,
                    SUM(COALESCE(pr.total_salary_wages_paid, 0)) AS total_sales,
                    COUNT(*) AS total_flags
                FROM swt_fraud_justification pr
                WHERE {_swt_cit_fraud_sql('pr')}
                  AND {_period_filter_sql('pr')}
                GROUP BY pr.tin
            )
            SELECT CAST(tin AS CHAR(30)) AS tin, taxpayer_name, total_sales, total_flags, 1 AS segments
            FROM flagged_taxpayers
            ORDER BY total_flags DESC, total_sales DESC
            LIMIT 10
        """)
    elif taxtype == "cit":
        query = text(f"""
            WITH flagged_taxpayers AS (
                SELECT
                    pr.tin,
                    MAX(COALESCE(NULLIF(TRIM(pr.taxpayer), ''), 'Unknown')) AS taxpayer_name,
                    SUM(COALESCE(pr.total_gross_income, 0)) AS total_sales,
                    COUNT(*) AS total_flags
                FROM cit_fraud_justification pr
                WHERE {_swt_cit_fraud_sql('pr')}
                  AND {_year_filter_sql('pr')}
                GROUP BY pr.tin
            )
            SELECT CAST(tin AS CHAR(30)) AS tin, taxpayer_name, total_sales, total_flags, 1 AS segments
            FROM flagged_taxpayers
            ORDER BY total_flags DESC, total_sales DESC
            LIMIT 10
        """)
    else:
        return jsonify({"error": "Invalid taxtype"}), 400

    try:
        rows = execute_fetchall(query, params)
    except Exception as e:
        print("[RISK ASSESSMENT ERROR]", str(e))
        return jsonify({"error": str(e)}), 500

    return jsonify([
        {
            "tin": r.tin,
            "taxpayer_name": r.taxpayer_name or "Unknown",
            "total_sales": float(r.total_sales or 0),
            "total_flags": int(r.total_flags or 0),
            "segments": int(r.segments or 0),
        }
        for r in rows
    ])


# ============================================================
# DOWNLOAD: Industry Full Records
# ============================================================

@bp.get("/download-industry")
@jwt_required()
def download_industry():
    taxtype = get_requested_taxtype("")
    start_year, start_month, end_year, end_month = get_date_range(taxtype)
    params = {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month,
    }

    if taxtype == "gst":
        query = text(f"""
            WITH taxpayer_rollup AS (
                SELECT
                    pr.tin,
                    MAX(pr.taxpayer_name) AS taxpayer_name,
                    SUM(COALESCE(pr.total_sales_income, 0)) AS total_sales,
                    SUM(CASE WHEN COALESCE(pr.is_fraud, 0) = 1 THEN 1 ELSE 0 END) AS flagged
                FROM gst_fraud_justification pr
                WHERE {_period_filter_sql('pr')}
                GROUP BY pr.tin
            )
            SELECT
                CAST(taxpayer_rollup.tin AS CHAR(30)) AS tin,
                taxpayer_rollup.taxpayer_name,
                {_registration_sector_sql('trm')} AS sector,
                taxpayer_rollup.total_sales,
                taxpayer_rollup.flagged
            FROM taxpayer_rollup
            LEFT JOIN tin_registration_mst trm
                ON taxpayer_rollup.tin = trm.tin
            ORDER BY taxpayer_rollup.total_sales DESC
        """)
    elif taxtype == "swt":
        query = text(f"""
            WITH taxpayer_rollup AS (
                SELECT
                    pr.tin,
                    MAX(pr.taxpayer_name) AS taxpayer_name,
                    SUM(COALESCE(pr.total_salary_wages_paid, 0)) AS total_sales,
                    SUM(CASE WHEN {_swt_cit_fraud_sql('pr')} THEN 1 ELSE 0 END) AS flagged
                FROM swt_fraud_justification pr
                WHERE {_period_filter_sql('pr')}
                GROUP BY pr.tin
            )
            SELECT
                CAST(taxpayer_rollup.tin AS CHAR(30)) AS tin,
                taxpayer_rollup.taxpayer_name,
                {_registration_sector_sql('trm')} AS sector,
                taxpayer_rollup.total_sales,
                taxpayer_rollup.flagged
            FROM taxpayer_rollup
            LEFT JOIN tin_registration_mst trm
                ON taxpayer_rollup.tin = trm.tin
            ORDER BY taxpayer_rollup.total_sales DESC
        """)
    elif taxtype == "cit":
        query = text(f"""
            WITH taxpayer_rollup AS (
                SELECT
                    pr.tin,
                    MAX(pr.taxpayer) AS taxpayer_name,
                    MAX(COALESCE(NULLIF(TRIM(pr.enterprise_activity), ''), 'Unknown')) AS sector,
                    SUM(COALESCE(pr.total_gross_income, 0)) AS total_sales,
                    SUM(CASE WHEN {_swt_cit_fraud_sql('pr')} THEN 1 ELSE 0 END) AS flagged
                FROM cit_fraud_justification pr
                WHERE {_year_filter_sql('pr')}
                GROUP BY pr.tin
            )
            SELECT
                CAST(taxpayer_rollup.tin AS CHAR(30)) AS tin,
                taxpayer_rollup.taxpayer_name,
                taxpayer_rollup.sector,
                taxpayer_rollup.total_sales,
                taxpayer_rollup.flagged
            FROM taxpayer_rollup
            ORDER BY taxpayer_rollup.total_sales DESC
        """)
    else:
        return jsonify({"error": "Invalid taxtype"}), 400

    try:
        rows = execute_stream_mappings(query, params)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    formatted = [
        {
            "tin": r["tin"],
            "taxpayer_name": r["taxpayer_name"],
            "sector": r["sector"],
            "total_sales": float(r["total_sales"] or 0),
            "flagged": int(r["flagged"] or 0),
        }
        for r in rows
    ]
    return jsonify({"count": len(formatted), "rows": formatted})


# ============================================================
# DOWNLOAD: Taxpayer vs Risk
# ============================================================
@bp.get("/download-taxpayer-vs-risk")
@jwt_required()
def download_taxpayer_vs_risk():
    taxtype = get_requested_taxtype("")
    start_year, start_month, end_year, end_month = get_date_range(taxtype)
    
    if taxtype == "gst":
        query = text("""
            SELECT
                CAST(tin AS CHAR(30)) AS tin,
                taxpayer_name,
                tax_period_year,
                tax_period_month,
                CASE WHEN COALESCE(is_fraud, 0) = 1 THEN 1 ELSE 0 END AS flagged
            FROM gst_fraud_justification
            WHERE (tax_period_year > :start_year
                OR (tax_period_year = :start_year AND tax_period_month >= :start_month))
              AND (tax_period_year < :end_year
                OR (tax_period_year = :end_year AND tax_period_month <= :end_month))
            ORDER BY tax_period_year, tax_period_month;
        """)
    elif taxtype == "swt":
        query = text("""
            SELECT
                CAST(tin AS CHAR(30)) AS tin,
                taxpayer_name,
                tax_period_year,
                tax_period_month,
                CASE WHEN LOWER(
                    CONVERT(COALESCE(predicted_fraud,'') USING utf8mb4)
                    COLLATE utf8mb4_unicode_ci
                ) = 'fraud' THEN 1 ELSE 0 END AS flagged
            FROM swt_fraud_justification
            WHERE (tax_period_year > :start_year
                OR (tax_period_year = :start_year AND tax_period_month >= :start_month))
              AND (tax_period_year < :end_year
                OR (tax_period_year = :end_year AND tax_period_month <= :end_month))
            ORDER BY tax_period_year, tax_period_month;
        """)
    elif taxtype == "cit":
        query = text("""
            SELECT
                CAST(tin AS CHAR(30)) AS tin,
                taxpayer AS taxpayer_name,
                tax_period_year,
                12 AS tax_period_month,
                CASE WHEN LOWER(
                    CONVERT(COALESCE(predicted_fraud,'') USING utf8mb4)
                    COLLATE utf8mb4_unicode_ci
                ) = 'fraud' THEN 1 ELSE 0 END AS flagged
            FROM cit_fraud_justification
            WHERE (tax_period_year >= :start_year)
              AND (tax_period_year <= :end_year)
            ORDER BY tax_period_year;
        """)
    else:
        return jsonify({"error": "Invalid taxtype"}), 400

    params = {
        "start_year": start_year, "start_month": start_month,
        "end_year": end_year, "end_month": end_month
    }
    rows = execute_stream_mappings(query, params)

    formatted = [
        {
            "tin": r["tin"],
            "taxpayer_name": r["taxpayer_name"],
            "tax_period_year": r["tax_period_year"],
            "tax_period_month": r["tax_period_month"],
            "flagged": r["flagged"],
        }
        for r in rows
    ]

    return jsonify({"count": len(formatted), "rows": formatted})


# ============================================================
# DOWNLOAD Frequency Anomalies Full Records (Corrected)
# ============================================================
@bp.get("/download-frequency-anomalies")
@jwt_required()
def download_frequency_anomalies():
    taxtype = get_requested_taxtype("")
    start_year, start_month, end_year, end_month = get_date_range(taxtype)

    if taxtype == "gst":
        query = text("""
            SELECT 
                CAST(pr.tin AS CHAR(30)) AS tin,
                pr.taxpayer_name,
                pr.tax_period_year,
                pr.tax_period_month,
                pr.exempt_sales,
                pr.total_sales_income,
                pr.gst_payable,
                CASE WHEN pr.exempt_sales > pr.total_sales_income * 0.5 THEN 1 ELSE 0 END AS excessive_exempt_sales_flag,
                CASE WHEN pr.gst_payable < pr.total_sales_income * 0.01 THEN 1 ELSE 0 END AS suspiciously_low_output_flag
            FROM gst_fraud_justification pr
            WHERE (pr.tax_period_year > :start_year 
                OR (pr.tax_period_year = :start_year AND pr.tax_period_month >= :start_month))
              AND (pr.tax_period_year < :end_year 
                OR (pr.tax_period_year = :end_year AND pr.tax_period_month <= :end_month))
              AND (
                    pr.exempt_sales > pr.total_sales_income * 0.5
                    OR pr.gst_payable < pr.total_sales_income * 0.01
              );
        """)
    elif taxtype == "swt":
        query = text("""
            SELECT 
                CAST(pr.tin AS CHAR(30)) AS tin,
                pr.taxpayer_name,
                pr.tax_period_year,
                pr.tax_period_month,
                pr.employees_paid_swt,
                pr.employees_on_payroll,
                pr.total_swt_tax_deducted,
                pr.total_salary_wages_paid,
                CASE WHEN pr.employees_paid_swt > pr.employees_on_payroll THEN 1 ELSE 0 END AS ghost_employee_flag,
                CASE WHEN pr.total_swt_tax_deducted > pr.total_salary_wages_paid * 0.40 THEN 1 ELSE 0 END AS excessive_tax_flag
            FROM swt_fraud_justification pr
            WHERE (pr.tax_period_year > :start_year 
                OR (pr.tax_period_year = :start_year AND pr.tax_period_month >= :start_month))
              AND (pr.tax_period_year < :end_year 
                OR (pr.tax_period_year = :end_year AND pr.tax_period_month <= :end_month))
              AND (
                    pr.employees_paid_swt > pr.employees_on_payroll
                    OR pr.total_swt_tax_deducted > pr.total_salary_wages_paid * 0.40
              );
        """)
    elif taxtype == "cit":
        query = text("""
            SELECT 
                CAST(pr.tin AS CHAR(30)) AS tin,
                pr.taxpayer AS taxpayer_name,
                pr.tax_period_year,
                12 AS tax_period_month,
                pr.total_gross_income,
                pr.total_tax_payable,
                CASE WHEN LOWER(
                    CONVERT(COALESCE(pr.predicted_fraud,'') USING utf8mb4)
                    COLLATE utf8mb4_unicode_ci
                ) = 'fraud' THEN 1 ELSE 0 END AS fraud_flag
            FROM cit_fraud_justification pr
            WHERE pr.tax_period_year >= :start_year
              AND pr.tax_period_year <= :end_year
        """)
        
    else:
        return jsonify({"error": "Invalid taxtype"}), 400

    params = {
        "start_year": start_year, "start_month": start_month,
        "end_year": end_year, "end_month": end_month
    }
    rows = execute_stream_mappings(query, params)

    formatted = [
        {
            "tin": r["tin"],
            "taxpayer_name": r["taxpayer_name"],
            **{k: v for k, v in r.items() if k not in ["tin", "taxpayer_name"]}
        }
        for r in rows
    ]

    return jsonify({"count": len(formatted), "rows": formatted})


# ============================================================
# DOWNLOAD: Top Fraud Full Detail Records
# ============================================================
@bp.get("/download-top-fraud-companies")
@jwt_required()
def download_top_fraud():
    taxtype = get_requested_taxtype("")
    start_year, start_month, end_year, end_month = get_date_range(taxtype)

    if taxtype == "gst":
        query = text("""
            SELECT 
                CAST(pr.tin AS CHAR(30)) AS tin,
                pr.taxpayer_name,
                pr.tax_period_year,
                pr.tax_period_month,
                pr.total_sales_income AS total_sales,   -- 👈 rename here
                COALESCE(pr.is_fraud, 0) AS is_flag
            FROM gst_fraud_justification pr
            WHERE COALESCE(pr.is_fraud, 0) = 1
              AND (pr.tax_period_year > :start_year 
                OR (pr.tax_period_year = :start_year AND pr.tax_period_month >= :start_month))
              AND (pr.tax_period_year < :end_year 
                OR (pr.tax_period_year = :end_year AND pr.tax_period_month <= :end_month))
        """)
    elif taxtype == "swt":
        query = text("""
            SELECT 
                pr.tin AS tin,
                pr.taxpayer_name,
                pr.tax_period_year,
                pr.tax_period_month,
                pr.total_salary_wages_paid AS total_sales,
                CASE WHEN LOWER(
                    CONVERT(COALESCE(pr.predicted_fraud,'') USING utf8mb4)
                    COLLATE utf8mb4_unicode_ci
                ) = 'fraud' THEN 1 ELSE 0 END AS is_flag
            FROM swt_fraud_justification pr
            WHERE LOWER(
                CONVERT(COALESCE(pr.predicted_fraud,'') USING utf8mb4)
                COLLATE utf8mb4_unicode_ci
            ) = 'fraud'
              AND (pr.tax_period_year > :start_year 
                OR (pr.tax_period_year = :start_year AND pr.tax_period_month >= :start_month))
              AND (pr.tax_period_year < :end_year 
                OR (pr.tax_period_year = :end_year AND pr.tax_period_month <= :end_month))
        """)
    elif taxtype == "cit":
        query = text("""
            SELECT 
                COALESCE(NULLIF(TRIM(pr.taxpayer), ''), 'Unknown') AS taxpayer_name,
                SUM(COALESCE(pr.total_gross_income, 0)) AS total_sales,
                COUNT(pr.id) AS total_flags,
                1 AS segments
            FROM cit_fraud_justification pr
            WHERE LOWER(
                CONVERT(COALESCE(pr.predicted_fraud,'') USING utf8mb4)
                COLLATE utf8mb4_unicode_ci
            ) = 'fraud'
                AND (pr.tax_period_year > :start_year OR
                    (pr.tax_period_year = :start_year))
                AND
                    (pr.tax_period_year < :end_year OR
                    (pr.tax_period_year = :end_year))
            GROUP BY taxpayer_name
            ORDER BY total_flags DESC, total_sales DESC
            LIMIT 10
        """)
    else:
        return jsonify({"error": "Invalid taxtype"}), 400
    
    params = {
        "start_year": start_year, "start_month": start_month,
        "end_year": end_year, "end_month": end_month
    }
    rows = execute_stream_mappings(query, params)

    return jsonify({"count": len(rows), "rows": [dict(r) for r in rows]})


