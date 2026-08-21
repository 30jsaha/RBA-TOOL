from flask import Blueprint, current_app, g, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy import text
from datetime import datetime
import time
from dateutil.relativedelta import relativedelta
from ..extensions import cache, db

bp = Blueprint("compliance", __name__, url_prefix="/api/compliance")

_COLUMN_CACHE = {}
_CACHE_TIMEOUTS = {
    "tax_summary_gst": 600,
    "filing_timeliness": 900,
    "profit_vs_loss": 600,
    "industry_kpi": 900,
    "compliance_kpi": 600,
}


def _request_cache_args():
    return tuple(sorted((key, value) for key, value in request.args.items() if value not in (None, "")))


def _cache_key(endpoint_name):
    parts = [f"compliance:{endpoint_name}"]
    for key, value in _request_cache_args():
        parts.append(f"{key}={value}")
    return "|".join(parts)


def _log_sql(query, params=None, sql_time=None, row_count=None):
    current_app.logger.info(
        "compliance_api.py :: sql rows=%s sql_time=%.4fs sql=%s params=%s",
        row_count if row_count is not None else "n/a",
        sql_time or 0,
        " ".join((query.text or "").split()),
        params or {},
    )


def _execute_mappings_all(query, params=None):
    params = params or {}
    started_at = time.time()
    rows = db.session.execute(query, params).mappings().all()
    _log_sql(query, params, sql_time=time.time() - started_at, row_count=len(rows))
    return rows


def _execute_mapping_first(query, params=None):
    params = params or {}
    started_at = time.time()
    row = db.session.execute(query, params).mappings().first()
    _log_sql(query, params, sql_time=time.time() - started_at, row_count=1 if row else 0)
    return row


def _execute_fetchone(query, params=None):
    params = params or {}
    started_at = time.time()
    row = db.session.execute(query, params).fetchone()
    _log_sql(query, params, sql_time=time.time() - started_at, row_count=1 if row else 0)
    return row


def _period_filter_sql(alias="pr"):
    return f"""
        ({alias}.tax_period_year > :start_year OR ({alias}.tax_period_year = :start_year AND {alias}.tax_period_month >= :start_month))
        AND
        ({alias}.tax_period_year < :end_year OR ({alias}.tax_period_year = :end_year AND {alias}.tax_period_month <= :end_month))
    """


def _year_filter_sql(alias="pr"):
    return f"{alias}.tax_period_year BETWEEN :start_year AND :end_year"


def _registration_industry_sql(alias="trm"):
    return f"COALESCE(NULLIF(TRIM({alias}.enterpriseactivity), ''), 'Unknown')"


def _registration_segment_sql(alias="trm"):
    return f"COALESCE(NULLIF(TRIM({alias}.taxpayertype), ''), 'Unknown')"


@bp.before_request
def _compliance_before_request():
    g.compliance_started_at = time.time()
    g.compliance_cache_key = None
    if request.method != "GET":
        return None

    endpoint_name = request.endpoint.rsplit(".", 1)[-1] if request.endpoint else None
    timeout = _CACHE_TIMEOUTS.get(endpoint_name)
    if not timeout:
        return None

    key = _cache_key(endpoint_name)
    g.compliance_cache_key = key
    cached_payload = cache.get(key)
    if cached_payload is not None:
        current_app.logger.info("compliance_api.py :: %s cache=hit key=%s", endpoint_name, key)
        return jsonify(cached_payload)

    current_app.logger.info("compliance_api.py :: %s cache=miss key=%s", endpoint_name, key)
    return None


@bp.after_request
def _compliance_after_request(response):
    endpoint_name = request.endpoint.rsplit(".", 1)[-1] if request.endpoint else "unknown"
    key = getattr(g, "compliance_cache_key", None)
    if key and response.status_code == 200 and response.is_json:
        try:
            serialization_started = time.time()
            payload = response.get_json()
            response.get_data()
            current_app.logger.info("compliance_api.py :: %s serialization_time=%.4fs", endpoint_name, time.time() - serialization_started)
            cache.set(key, payload, timeout=_CACHE_TIMEOUTS[endpoint_name])
        except Exception:
            current_app.logger.exception("compliance_api.py :: failed to cache response")

    started_at = getattr(g, "compliance_started_at", None)
    if started_at is not None:
        current_app.logger.info(
            "compliance_api.py :: %s total_request_time=%.4fs status=%s",
            endpoint_name,
            time.time() - started_at,
            response.status_code,
        )
    return response

# ============================================================
# Helpers: Table/column detection + date parsing
# ============================================================
def _table_has_column(table_name: str, column_name: str) -> bool:
    cache_key = (table_name, column_name)
    if cache_key in _COLUMN_CACHE:
        return _COLUMN_CACHE[cache_key]

    try:
        row = _execute_fetchone(
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
        )
        value = bool(row and int(row[0] or 0) > 0)
        _COLUMN_CACHE[cache_key] = value
        return value
    except Exception:
        return False

def _sql_parse_date(expr: str) -> str:
    # Try common formats seen in this DB (YYYY-MM-DD, DD-MM-YYYY, DD-Mon-YY, DD/Mon/YY)
    return f"""
        COALESCE(
            STR_TO_DATE({expr}, '%Y-%m-%d'),
            STR_TO_DATE({expr}, '%d-%m-%Y'),
            STR_TO_DATE({expr}, '%d-%b-%y'),
            STR_TO_DATE({expr}, '%d/%b/%y'),
            STR_TO_DATE({expr}, '%d/%m/%Y')
        )
    """

# ============================================================
# Common Helper: Date Range Normalization
# ============================================================
def get_date_range():
    """
    Returns normalized inclusive start/end (year, month) for queries based on:
      - ?range_type=1m|3m|6m|1y|custom  (default 3m)
      - ?start_date=YYYY-MM-DD & ?end_date=YYYY-MM-DD when range_type=custom
    Normalizes start to first of month and end to last day of month.
    """
    now = datetime.now()
    range_type = (request.args.get("range_type") or "3m").lower()
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    if range_type == "custom" and start_date and end_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            start = now.replace(day=1)
            end = now
    elif range_type == "1m":
        start = (now - relativedelta(months=1)).replace(day=1)
        end = now
    elif range_type == "3m":
        start = (now - relativedelta(months=2)).replace(day=1)
        end = now
    elif range_type == "6m":
        start = (now - relativedelta(months=5)).replace(day=1)
        end = now
    elif range_type == "1y":
        start = (now - relativedelta(years=1)).replace(day=1)
        end = now
    else:
        # Default to past 3 months (inclusive)
        start = (now - relativedelta(months=2)).replace(day=1)
        end = now

    # normalize end to last day of its month
    next_month = (end.replace(day=28) + relativedelta(days=4)).replace(day=1)
    end = next_month - relativedelta(days=1)

    return start.year, start.month, end.year, end.month

def success_response(data, message=None, **extra):
    if message is None:
        message = "No records found" if not data else "OK"
    payload = {"success": True, "data": data, "message": message}
    payload.update(extra)
    return jsonify(payload)

def error_response(message, status_code=500, **extra):
    payload = {"success": False, "data": [], "message": message}
    payload.update(extra)
    return jsonify(payload), status_code

# ============================================================
# OPTIMIZED: Tax Filing vs Non-Filing
# ============================================================

@bp.get("/tax-filing")
@jwt_required()
def tax_summary_gst():
    start_year, start_month, end_year, end_month = get_date_range()
    taxtype = request.args.get("taxtype", "gst").lower()
    query = None

    if taxtype not in ("gst", "swt", "cit"):
        return error_response("Invalid taxtype", status_code=400)

    industry_expr = _registration_industry_sql('trm')
    if taxtype == "gst":
        source_table = "gst_fraud_justification"
        filter_sql = _period_filter_sql('pr')
        params = {"start_year": start_year, "start_month": start_month, "end_year": end_year, "end_month": end_month}
        filed_join_sql = "filed_tins.tin = trm.tin"
    elif taxtype == "swt":
        source_table = "swt_fraud_justification"
        filter_sql = _period_filter_sql('pr')
        params = {"start_year": start_year, "start_month": start_month, "end_year": end_year, "end_month": end_month}
        filed_join_sql = "CAST(filed_tins.tin AS CHAR(50) CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci = CONVERT(trm.tin USING utf8mb4) COLLATE utf8mb4_unicode_ci"
    else:
        source_table = "cit_fraud_justification"
        filter_sql = _year_filter_sql('pr')
        params = {"start_year": start_year, "end_year": end_year}
        filed_join_sql = "filed_tins.tin = trm.tin"

    query = text(f"""
        WITH registered_by_industry AS (
            SELECT
                {industry_expr} AS enterpriseactivity,
                COUNT(*) AS total_taxpayers
            FROM tin_registration_mst trm
            GROUP BY {industry_expr}
        ),
        filed_tins AS (
            SELECT pr.tin
            FROM {source_table} pr
            WHERE {filter_sql}
            GROUP BY pr.tin
        ),
        filed_by_industry AS (
            SELECT
                {industry_expr} AS enterpriseactivity,
                COUNT(*) AS filed_taxpayers
            FROM filed_tins
            INNER JOIN tin_registration_mst trm
                ON {filed_join_sql}
            GROUP BY {industry_expr}
        )
        SELECT
            registered_by_industry.enterpriseactivity,
            COALESCE(filed_by_industry.filed_taxpayers, 0) AS filed_taxpayers,
            GREATEST(0, registered_by_industry.total_taxpayers - COALESCE(filed_by_industry.filed_taxpayers, 0)) AS non_filers
        FROM registered_by_industry
        LEFT JOIN filed_by_industry
            ON registered_by_industry.enterpriseactivity = filed_by_industry.enterpriseactivity
        ORDER BY filed_taxpayers DESC
    """)

    try:
        result = _execute_mappings_all(query, params)
        return success_response([dict(row) for row in result])
    except Exception as exc:
        current_app.logger.exception(
            "tax_summary_gst failed; taxtype=%s; original_exception=%r; sqlalchemy_exception=%r; sql=%s; params=%s",
            taxtype,
            getattr(exc, "orig", exc),
            exc,
            query.text if query is not None else None,
            params,
        )
        return jsonify({"success": False, "message": str(exc), "data": []}), 500


# ============================================================
# OPTIMIZED: Delayed vs On-Time Returns
# ============================================================

@bp.get("/timeliness")
@jwt_required()
def filing_timeliness():
    start_year, start_month, end_year, end_month = get_date_range()
    taxtype = request.args.get("taxtype", "gst").lower()
    query = None

    if taxtype == "gst":
        recv = _sql_parse_date("pr.received_date")
        due = _sql_parse_date("pr.due_date")
        params = {"start_year": start_year, "end_year": end_year}
        query = text(f"""
            SELECT
                COALESCE(NULLIF(TRIM(pr.taxpayer_type), ''), 'Unknown') AS segment_label,
                SUM(CASE WHEN {recv} IS NOT NULL AND {due} IS NOT NULL AND {recv} > {due} THEN 1 ELSE 0 END) AS delay,
                SUM(CASE WHEN {recv} IS NOT NULL AND {due} IS NOT NULL AND {recv} <= {due} THEN 1 ELSE 0 END) AS on_time
            FROM gst_fraud_justification pr
            WHERE {_year_filter_sql('pr')}
            GROUP BY segment_label
            ORDER BY delay DESC
        """)
    elif taxtype == "swt":
        entry = _sql_parse_date("pr.entry_date")
        due = _sql_parse_date("pr.due_date")
        segment_expr = _registration_segment_sql('trm')
        params = {"start_year": start_year, "end_year": end_year}
        query = text(f"""
            WITH taxpayer_rollup AS (
                SELECT
                    pr.tin,
                    COALESCE(SUM(CASE WHEN {entry} IS NOT NULL AND {due} IS NOT NULL AND {entry} > {due} THEN 1 ELSE 0 END), 0) AS delay,
                    COALESCE(SUM(CASE WHEN {entry} IS NOT NULL AND {due} IS NOT NULL AND {entry} <= {due} THEN 1 ELSE 0 END), 0) AS on_time
                FROM swt_fraud_justification pr
                WHERE {_year_filter_sql('pr')}
                GROUP BY pr.tin
            )
            SELECT
                {segment_expr} AS segment_label,
                COALESCE(SUM(taxpayer_rollup.delay), 0) AS delay,
                COALESCE(SUM(taxpayer_rollup.on_time), 0) AS on_time
            FROM taxpayer_rollup
            LEFT JOIN tin_registration_mst trm
                ON CAST(taxpayer_rollup.tin AS CHAR(50) CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci =
                   CONVERT(trm.tin USING utf8mb4) COLLATE utf8mb4_unicode_ci
            GROUP BY {segment_expr}
            ORDER BY delay DESC
        """)
    elif taxtype == "cit":
        recv = _sql_parse_date("pr.received_date")
        due = _sql_parse_date("pr.due_date")
        params = {"start_year": start_year, "end_year": end_year}
        query = text(f"""
            WITH taxpayer_rollup AS (
                SELECT
                    pr.tin,
                    SUM(CASE WHEN {recv} IS NOT NULL AND {due} IS NOT NULL AND {recv} > {due} THEN 1 ELSE 0 END) AS delay,
                    SUM(CASE WHEN {recv} IS NOT NULL AND {due} IS NOT NULL AND {recv} <= {due} THEN 1 ELSE 0 END) AS on_time
                FROM cit_fraud_justification pr
                WHERE {_year_filter_sql('pr')}
                GROUP BY pr.tin
            )
            SELECT
                {_registration_segment_sql('trm')} AS segment_label,
                SUM(taxpayer_rollup.delay) AS delay,
                SUM(taxpayer_rollup.on_time) AS on_time
            FROM taxpayer_rollup
            LEFT JOIN tin_registration_mst trm
                ON taxpayer_rollup.tin = trm.tin
            GROUP BY segment_label
            ORDER BY delay DESC
        """)
    else:
        return error_response("Invalid taxtype", status_code=400)

    try:
        result = _execute_mappings_all(query, params)
        return success_response([dict(row) for row in result])
    except Exception as exc:
        current_app.logger.exception(
            "filing_timeliness failed; taxtype=%s; original_exception=%r; sqlalchemy_exception=%r; sql=%s; params=%s",
            taxtype,
            getattr(exc, "orig", exc),
            exc,
            query.text if query is not None else None,
            params,
        )
        return jsonify({"success": False, "message": str(exc), "data": []}), 500


# ============================================================
# OPTIMIZED: Profit vs Loss
# ============================================================

@bp.get("/profitability")
@jwt_required()
def profit_vs_loss():
    start_year, start_month, end_year, end_month = get_date_range()
    taxtype = request.args.get("taxtype", "gst").lower()

    if taxtype == "cit":
        if not _table_has_column("cit_fraud_justification", "current_year_profit_or_loss"):
            return success_response([], message="Profitability is available only for CIT (profit/loss not present)")

        query = text(f"""
            WITH taxpayer_rollup AS (
                SELECT
                    pr.tin,
                    SUM(CASE WHEN pr.current_year_profit_or_loss > 0 THEN 1 ELSE 0 END) AS profit,
                    SUM(CASE WHEN pr.current_year_profit_or_loss < 0 THEN 1 ELSE 0 END) AS loss
                FROM cit_fraud_justification pr
                WHERE {_year_filter_sql('pr')}
                GROUP BY pr.tin
            )
            SELECT
                {_registration_segment_sql('trm')} AS segment_label,
                SUM(taxpayer_rollup.profit) AS profit,
                SUM(taxpayer_rollup.loss) AS loss
            FROM taxpayer_rollup
            LEFT JOIN tin_registration_mst trm
                ON taxpayer_rollup.tin = trm.tin
            GROUP BY segment_label
            ORDER BY profit DESC
        """)
    else:
        if taxtype in ("gst", "swt"):
            return success_response([], message="Profitability is available only for CIT")
        return error_response("Invalid taxtype", status_code=400)

    try:
        result = _execute_mappings_all(query, {"start_year": start_year, "end_year": end_year})
        return success_response([dict(row) for row in result])
    except Exception as e:
        print("[COMPLIANCE API ERROR]", str(e))
        return jsonify({"success": False, "message": str(e), "data": []}), 500


# ============================================================
# HELPER: Compute KPI metrics
# ============================================================
def compute_kpis(total_taxpayers, filed, delayed, on_time, profit, loss):
    filing_rate = (filed / total_taxpayers) if total_taxpayers else 0
    non_filing_rate = 1 - filing_rate
    
    total_returns = delayed + on_time
    delay_rate = (delayed / total_returns) if total_returns else 0
    
    total_profit_loss = profit + loss
    profitability_rate = (profit / total_profit_loss) if total_profit_loss else 0
    
    return {
        "filing_rate": round(filing_rate, 4),
        "non_filing_rate": round(non_filing_rate, 4),
        "delay_rate": round(delay_rate, 4),
        "on_time_rate": round(1 - delay_rate, 4),
        "profitability_rate": round(profitability_rate, 4),
        "loss_rate": round(1 - profitability_rate, 4) if total_profit_loss else 0
    }

# ============================================================
# NEW: Industry KPI Endpoint (Replaces Summary)
# ============================================================

@bp.get("/industry-kpi")
@jwt_required()
def industry_kpi():
    start_year, start_month, end_year, end_month = get_date_range()
    range_type = (request.args.get("range_type") or "3m").lower()
    taxtype = request.args.get("taxtype", "gst").lower()
    query = None
    if taxtype not in ("gst", "swt", "cit"):
        return error_response("Invalid taxtype", 400)

    industry_expr = _registration_industry_sql('trm')
    if taxtype == "gst":
        base_table = "gst_fraud_justification"
        filter_sql = _period_filter_sql('pr')
        recv = _sql_parse_date("pr.received_date")
        due = _sql_parse_date("pr.due_date")
        params = {"start_year": start_year, "start_month": start_month, "end_year": end_year, "end_month": end_month}
        profit_loss_sql = "0 AS profit_records, 0 AS loss_records"
        registration_join_sql = "taxpayer_rollup.tin = trm.tin"
    elif taxtype == "swt":
        base_table = "swt_fraud_justification"
        filter_sql = _period_filter_sql('pr')
        recv = _sql_parse_date("pr.entry_date")
        due = _sql_parse_date("pr.due_date")
        params = {"start_year": start_year, "start_month": start_month, "end_year": end_year, "end_month": end_month}
        profit_loss_sql = "0 AS profit_records, 0 AS loss_records"
        registration_join_sql = "CAST(taxpayer_rollup.tin AS CHAR(50) CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci = CONVERT(trm.tin USING utf8mb4) COLLATE utf8mb4_unicode_ci"
    else:
        base_table = "cit_fraud_justification"
        filter_sql = _year_filter_sql('pr')
        recv = _sql_parse_date("pr.received_date")
        due = _sql_parse_date("pr.due_date")
        params = {"start_year": start_year, "end_year": end_year}
        registration_join_sql = "taxpayer_rollup.tin = trm.tin"
        if _table_has_column("cit_fraud_justification", "current_year_profit_or_loss"):
            profit_loss_sql = """
                SUM(CASE WHEN pr.current_year_profit_or_loss > 0 THEN 1 ELSE 0 END) AS profit_records,
                SUM(CASE WHEN pr.current_year_profit_or_loss < 0 THEN 1 ELSE 0 END) AS loss_records
            """
        else:
            profit_loss_sql = "0 AS profit_records, 0 AS loss_records"

    query = text(f"""
        WITH taxpayer_rollup AS (
            SELECT
                pr.tin,
                COALESCE(SUM(CASE WHEN {recv} IS NOT NULL AND {due} IS NOT NULL AND {recv} > {due} THEN 1 ELSE 0 END), 0) AS delayed_records,
                COALESCE(SUM(CASE WHEN {recv} IS NOT NULL AND {due} IS NOT NULL AND {recv} <= {due} THEN 1 ELSE 0 END), 0) AS on_time_records,
                {profit_loss_sql}
            FROM {base_table} pr
            WHERE {filter_sql}
            GROUP BY pr.tin
        )
        SELECT
            {industry_expr} AS industry,
            COUNT(*) AS total_taxpayers,
            COUNT(*) AS filed_records,
            COALESCE(SUM(taxpayer_rollup.delayed_records), 0) AS delayed_records,
            COALESCE(SUM(taxpayer_rollup.on_time_records), 0) AS on_time_records,
            COALESCE(SUM(taxpayer_rollup.profit_records), 0) AS profit_records,
            COALESCE(SUM(taxpayer_rollup.loss_records), 0) AS loss_records
        FROM taxpayer_rollup
        LEFT JOIN tin_registration_mst trm
            ON {registration_join_sql}
        GROUP BY {industry_expr}
        ORDER BY filed_records DESC
    """)

    try:
        rows = [dict(r) for r in _execute_mappings_all(query, params)]
        return success_response(rows, requested_range={"start_year": start_year, "end_year": end_year, "range_type": range_type}, applied_range={"start_year": start_year, "end_year": end_year})
    except Exception as exc:
        current_app.logger.exception(
            "industry_kpi failed; taxtype=%s; original_exception=%r; sqlalchemy_exception=%r; sql=%s; params=%s",
            taxtype,
            getattr(exc, "orig", exc),
            exc,
            query.text if query is not None else None,
            params,
        )
        return jsonify({"success": False, "message": str(exc), "data": []}), 500


# ============================================================
# KPI Endpoint (Overall)
# ============================================================

@bp.get("/kpi")
@jwt_required()
def compliance_kpi():
    start_year, start_month, end_year, end_month = get_date_range()
    taxtype = request.args.get("taxtype", "gst").lower()

    if taxtype not in ("gst", "swt", "cit"):
        return error_response("Invalid taxtype", 400)

    if taxtype == "gst":
        base_table = "gst_fraud_justification"
        filter_sql = _period_filter_sql('pr')
        recv = _sql_parse_date("pr.received_date")
        due = _sql_parse_date("pr.due_date")
        profit_loss_sql = "0 AS profit, 0 AS loss"
        params = {"start_year": start_year, "start_month": start_month, "end_year": end_year, "end_month": end_month}
    elif taxtype == "swt":
        base_table = "swt_fraud_justification"
        filter_sql = _period_filter_sql('pr')
        recv = _sql_parse_date("pr.entry_date")
        due = _sql_parse_date("pr.due_date")
        profit_loss_sql = "0 AS profit, 0 AS loss"
        params = {"start_year": start_year, "start_month": start_month, "end_year": end_year, "end_month": end_month}
    else:
        base_table = "cit_fraud_justification"
        filter_sql = _year_filter_sql('pr')
        recv = _sql_parse_date("pr.received_date")
        due = _sql_parse_date("pr.due_date")
        if _table_has_column("cit_fraud_justification", "current_year_profit_or_loss"):
            profit_loss_sql = """
                SUM(CASE WHEN pr.current_year_profit_or_loss > 0 THEN 1 ELSE 0 END) AS profit,
                SUM(CASE WHEN pr.current_year_profit_or_loss < 0 THEN 1 ELSE 0 END) AS loss
            """
        else:
            profit_loss_sql = "0 AS profit, 0 AS loss"
        params = {"start_year": start_year, "end_year": end_year}

    query = text(f"""
        WITH taxpayer_rollup AS (
            SELECT
                pr.tin,
                SUM(CASE WHEN {recv} IS NOT NULL AND {due} IS NOT NULL AND {recv} > {due} THEN 1 ELSE 0 END) AS delayed,
                SUM(CASE WHEN {recv} IS NOT NULL AND {due} IS NOT NULL AND {recv} <= {due} THEN 1 ELSE 0 END) AS on_time,
                {profit_loss_sql}
            FROM {base_table} pr
            WHERE {filter_sql}
            GROUP BY pr.tin
        )
        SELECT
            COUNT(*) AS total_taxpayers,
            COUNT(*) AS filed,
            SUM(taxpayer_rollup.delayed) AS delayed,
            SUM(taxpayer_rollup.on_time) AS on_time,
            SUM(taxpayer_rollup.profit) AS profit,
            SUM(taxpayer_rollup.loss) AS loss
        FROM taxpayer_rollup
    """)

    try:
        row = _execute_mapping_first(query, params) or {}
        return success_response([dict(row)])
    except Exception as e:
        print("[COMPLIANCE API ERROR]", str(e))
        return jsonify({"success": False, "message": str(e), "data": []}), 500

