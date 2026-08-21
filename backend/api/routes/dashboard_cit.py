from flask import Blueprint, jsonify, request, Response, current_app
from flask_jwt_extended import jwt_required
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from datetime import datetime
from ..extensions import cache, db
from .dashboard_common import get_date_filter
import csv
from io import StringIO
import time

bp = Blueprint("dashboard_cit", __name__, url_prefix="/api/cit/dashboard")
download_bp = Blueprint("dashboard_cit_download", __name__, url_prefix="/api/cit/download-csv")
details_bp = Blueprint("dashboard_cit_details", __name__, url_prefix="/api/cit")

CSV_HEADERS = [
    "tin",
    "taxpayer_name",
    "net_profit",
    "net_loss",
    "gross_sales",
    "cogs",
    "superannuation_type",
    "interest_type",
    "amount",
    "risk_flag",
    "province",
    "segmentation",
    "year",
]


# ============================================================
# Helper: Year range
# ============================================================
def get_year_range():
    _, params = get_date_filter(column_year="tax_period_year")
    now = datetime.now()
    return (
        int(params.get("start_year", now.year)),
        int(params.get("end_year", now.year)),
    )


def get_top_n():
    raw = request.args.get("top_n")
    allowed = {10, 20, 30, 40, 50}
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 50
    return value if value in allowed else 50


def _get_request_limit(param_name="limit", default=100, maximum=500):
    raw = request.args.get(param_name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default

    if value <= 0:
        return default
    return min(value, maximum)


def _get_year_filter_context(column_year="tax_period_year"):
    cache_params = _get_period_bounds()
    date_filter, date_params = get_date_filter(
        column_year=column_year,
    )
    return cache_params, date_filter, date_params

def get_latest_available_year():
    row = db.session.execute(
        text("SELECT MAX(tax_period_year) AS y FROM cit_fraud_justification")
    ).mappings().one()
    return row["y"]


def ensure_year_range_has_data(start_year, end_year):
    row = db.session.execute(
        text("""
            SELECT COUNT(*) AS cnt
            FROM cit_fraud_justification
            WHERE tax_period_year BETWEEN :s AND :e
        """),
        {"s": start_year, "e": end_year}
    ).mappings().one()

    if row["cnt"] == 0:
        latest = get_latest_available_year()
        return latest, latest

    return start_year, end_year


def _get_period_bounds():
    now = datetime.now()
    _, params = get_date_filter(column_year="tax_period_year")
    start_year = int(params.get("start_year", now.year))
    end_year = int(params.get("end_year", now.year))
    if start_year > end_year:
        start_year, end_year = end_year, start_year
    return {"start_year": start_year, "end_year": end_year}


def _log_timing(endpoint_name, started_at):
    try:
        elapsed_ms = round((time.time() - started_at) * 1000, 2)
        current_app.logger.info(
            f"{endpoint_name:<24} {elapsed_ms} ms"
        )
    except Exception:
        pass


def _cache_key(endpoint_name, params, extra=""):
    key = f"cit_dashboard:{endpoint_name}:{params['start_year']}:{params['end_year']}"
    if extra:
        key = f"{key}:{extra}"
    return key


def _cached_json(endpoint_name, params, timeout, builder, extra=""):
    key = _cache_key(endpoint_name, params, extra=extra)
    cached = cache.get(key)
    if cached is not None:
        return cached

    payload = builder()
    cache.set(key, payload, timeout=timeout)
    return payload


def _normalize_unknown_label(value, fallback="Unknown"):
    label = str(value or "").strip()
    return label if label else fallback


def _normalize_predicted_fraud(value):
    label = str(value or "").strip()
    if not label:
        return "Unknown"
    return label


def _predicted_fraud_flag_sql(column="predicted_fraud"):
    normalized = f"UPPER(TRIM(COALESCE({column}, '')))"
    return f"CASE WHEN {normalized} IN ('FRAUD','RISK','YES','Y','1','TRUE') THEN 1 ELSE 0 END"


def _predicted_fraud_label_sql(column="predicted_fraud"):
    normalized = f"UPPER(TRIM(COALESCE({column}, '')))"
    return (
        f"CASE \
            WHEN {normalized} IN ('FRAUD','RISK','YES','Y','1','TRUE') THEN 'Fraud' \
            WHEN {normalized} IN ('NON-FRAUD','NON FRAUD','NO','N','0','FALSE') THEN 'Non-Fraud' \
            ELSE COALESCE(NULLIF(TRIM({column}), ''), 'Unknown') \
        END"
    )


def _unicode_ci_sql(expression):
    return f"CONVERT({expression} USING utf8mb4) COLLATE utf8mb4_unicode_ci"


def _tin_join_sql(left_expression, right_expression):
    return f"{_unicode_ci_sql(left_expression)} = {_unicode_ci_sql(right_expression)}"

def _cit_taxpayer_name_sql(pr_alias="pr", agg_alias="ac", reg_alias="tr"):
    return (
        "COALESCE("
        f"NULLIF(TRIM({pr_alias}.taxpayer), ''), "
        f"NULLIF(TRIM({agg_alias}.taxpayer_name), ''), "
        f"NULLIF(TRIM({reg_alias}.taxpayername), ''), "
        f"NULLIF(TRIM({reg_alias}.maintradename), ''), "
        "''"
        ")"
    )


def _cit_taxpayer_name_agg_sql(pr_alias="pr", agg_alias="ac", reg_alias="tr"):
    return f"MAX(CONVERT({_cit_taxpayer_name_sql(pr_alias, agg_alias, reg_alias)} USING utf8mb4))"


def _cit_rows_exist(date_filter, date_params):
    row = db.session.execute(
        text(f"""
            SELECT 1
            FROM cit_fraud_justification pr
            WHERE ({date_filter})
            LIMIT 1
        """),
        date_params,
    ).first()
    return row is not None


def _build_province_payload(
    province_sql,
    params,
    normalize_province,
    start_year,
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
        "success": True,
        "date_range": {
            "start": str(start_year),
            "end": str(end_year),
        },
        "province_distribution": province_map,
    }


_CIT_PROVINCE_INDEX_CHECKED = False
_CIT_PROVINCE_INDEX_WARNING_EMITTED = False


def _warn_if_cit_province_index_missing():
    global _CIT_PROVINCE_INDEX_CHECKED, _CIT_PROVINCE_INDEX_WARNING_EMITTED
    if _CIT_PROVINCE_INDEX_CHECKED:
        return

    index_sql = text("""
        SELECT
            index_name,
            seq_in_index,
            column_name
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'tin_province_lookup'
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

    has_province_index = any("province" in columns for columns in indexes.values())
    if not has_province_index:
        current_app.logger.warning(
            "dashboard_cit.py :: Recommended index missing on "
            "tin_province_lookup: province"
        )
        _CIT_PROVINCE_INDEX_WARNING_EMITTED = True
    _CIT_PROVINCE_INDEX_CHECKED = True



def _build_latest_records_query(date_filter):
    taxpayer_name_sql = _cit_taxpayer_name_sql(pr_alias="base")
    return text(f"""
        SELECT
            base.tin,
            {taxpayer_name_sql} AS taxpayer_name,
            base.tax_period_year,
            COALESCE(ac.cit_total_gross_income, base.total_gross_income, 0) AS gross_income,
            COALESCE(ac.cit_total_gross_income, base.total_gross_income, 0) AS gross_sales,
            COALESCE(base.cost_of_goods_sold, 0) AS cogs,
            COALESCE(ac.cit_total_gross_income, base.total_gross_income, 0)
                - COALESCE(base.cost_of_goods_sold, 0) AS net_profit,
            COALESCE(base.predicted_fraud, 'Unknown') AS predicted_fraud
        FROM (
            SELECT
                pr.tin,
                {_unicode_ci_sql("CAST(pr.tin AS CHAR(20))")} AS tin_key_general,
                {_unicode_ci_sql("CAST(pr.tin AS CHAR(20))")} AS tin_key_unicode,
                pr.taxpayer,
                pr.tax_period_year,
                pr.total_gross_income,
                pr.cost_of_goods_sold,
                pr.predicted_fraud
            FROM cit_fraud_justification pr
            WHERE ({date_filter})
            ORDER BY pr.tax_period_year DESC, pr.tin ASC
            LIMIT :limit
        ) base
        LEFT JOIN agg_cit ac FORCE INDEX (idx_tin_year)
            ON {_tin_join_sql("base.tin_key_general", "ac.tin")}
            AND base.tax_period_year = ac.tax_period_year
        LEFT JOIN tin_registration_mst tr FORCE INDEX (idx_trm_norm_tin)
            ON {_tin_join_sql("base.tin_key_unicode", "tr.normalized_tin")}
        ORDER BY base.tax_period_year DESC, base.tin ASC
    """)


def _fetch_latest_records_rows(date_filter, date_params, limit):
    query = _build_latest_records_query(date_filter)
    query_params = {**date_params, "limit": limit}

    sql_started_at = time.perf_counter()
    result = db.session.execute(query, query_params)
    sql_execution_ms = round((time.perf_counter() - sql_started_at) * 1000, 2)

    fetch_started_at = time.perf_counter()
    rows = result.mappings().all()
    fetch_ms = round((time.perf_counter() - fetch_started_at) * 1000, 2)

    return rows, sql_execution_ms, fetch_ms


def _build_latest_records_payload(date_filter, date_params, limit):
    rows, sql_execution_ms, fetch_ms = _fetch_latest_records_rows(date_filter, date_params, limit)

    serialize_started_at = time.perf_counter()
    payload = [
        {
            "tin": row.get("tin") or "",
            "taxpayer_name": row.get("taxpayer_name") or "",
            "tax_period_year": int(row.get("tax_period_year") or 0),
            "gross_income": float(row.get("gross_income") or 0),
            "gross_sales": float(row.get("gross_sales") or 0),
            "cogs": float(row.get("cogs") or 0),
            "net_profit": float(row.get("net_profit") or 0),
            "predicted_fraud": _normalize_predicted_fraud(row.get("predicted_fraud")),
        }
        for row in rows
    ]
    serialization_ms = round((time.perf_counter() - serialize_started_at) * 1000, 2)

    current_app.logger.info(
        "latest_records stages sql_execution_ms=%s fetch_ms=%s json_serialization_ms=%s row_count=%s",
        sql_execution_ms,
        fetch_ms,
        serialization_ms,
        len(payload),
    )
    return payload

def _log_stage_timings(endpoint_name, **timings):
    try:
        if not timings:
            return
        metric_parts = [f"{key}={value}" for key, value in timings.items()]
        current_app.logger.info("%s stages %s", endpoint_name, " ".join(metric_parts))
    except Exception:
        pass


def _fetch_mappings_with_timing(statement, params):
    sql_started_at = time.perf_counter()
    result = db.session.execute(statement, params)
    sql_execution_ms = round((time.perf_counter() - sql_started_at) * 1000, 2)

    fetch_started_at = time.perf_counter()
    rows = result.mappings().all()
    fetch_ms = round((time.perf_counter() - fetch_started_at) * 1000, 2)
    return rows, sql_execution_ms, fetch_ms


def _cit_yearly_financials_subquery(date_filter):
    return f"""
        SELECT
            CAST(pr.tin AS CHAR(50)) AS tin,
            pr.tax_period_year,
            COUNT(*) AS row_count,
            SUM(COALESCE(pr.total_gross_income, 0)) AS gross_sales_from_returns,
            SUM(COALESCE(pr.cost_of_goods_sold, 0)) AS cogs
        FROM cit_fraud_justification pr
        WHERE ({date_filter})
        GROUP BY CAST(pr.tin AS CHAR(50)), pr.tax_period_year
    """


def _cit_resolved_sales_sql(yearly_alias="yearly", agg_alias="ac"):
    return (
        "COALESCE("
        f"CASE WHEN {agg_alias}.cit_total_gross_income IS NULL "
        f"THEN {yearly_alias}.gross_sales_from_returns "
        f"ELSE {agg_alias}.cit_total_gross_income * {yearly_alias}.row_count END, "
        "0)"
    )


def _build_taxpayer_name_lookup_query(date_filter, extra_filter=""):
    return text(f"""
        SELECT
            CAST(pr.tin AS CHAR(50)) AS tin,
            MAX(CONVERT(COALESCE(
                NULLIF(TRIM(pr.taxpayer), ''),
                NULLIF(TRIM(ac_name.taxpayer_name), ''),
                NULLIF(TRIM(tr.taxpayername), ''),
                NULLIF(TRIM(tr.maintradename), ''),
                ''
            ) USING utf8mb4)) AS taxpayer_name
        FROM cit_fraud_justification pr
        LEFT JOIN agg_cit ac_name
            ON {_tin_join_sql("CAST(pr.tin AS CHAR(50))", "ac_name.tin")}
            AND pr.tax_period_year = ac_name.tax_period_year
        LEFT JOIN tin_registration_mst tr
            ON {_tin_join_sql("CAST(pr.tin AS CHAR(50))", "tr.normalized_tin")}
        WHERE ({date_filter})
        {extra_filter}
        GROUP BY CAST(pr.tin AS CHAR(50))
    """)


def _build_top_net_amount_query(date_filter, positive=True):
    operator = ">" if positive else "<"
    sort_order = "DESC" if positive else "ASC"
    yearly_financials = _cit_yearly_financials_subquery(date_filter)
    resolved_sales_sql = _cit_resolved_sales_sql("yearly", "ac")
    return text(f"""
        SELECT
            yearly.tin,
            SUM({resolved_sales_sql} - COALESCE(yearly.cogs, 0)) AS net_profit
        FROM ({yearly_financials}) yearly
        LEFT JOIN agg_cit ac
            ON {_tin_join_sql("yearly.tin", "ac.tin")}
            AND yearly.tax_period_year = ac.tax_period_year
        GROUP BY yearly.tin
        HAVING net_profit {operator} 0
        ORDER BY net_profit {sort_order}
        LIMIT :limit
    """)


def _fetch_top_net_amount_rows(date_filter, date_params, top_n, positive=True):
    metric_rows, metric_sql_ms, metric_fetch_ms = _fetch_mappings_with_timing(
        _build_top_net_amount_query(date_filter, positive=positive),
        {**date_params, "limit": top_n},
    )

    tins = [row["tin"] for row in metric_rows]
    taxpayer_map = {}
    name_sql_ms = 0
    name_fetch_ms = 0
    if tins:
        tin_clause, tin_params = _build_in_clause("CAST(pr.tin AS CHAR(50))", tins, "top_tin")
        name_rows, name_sql_ms, name_fetch_ms = _fetch_mappings_with_timing(
            _build_taxpayer_name_lookup_query(date_filter, tin_clause),
            {**date_params, **tin_params},
        )
        taxpayer_map = {
            row["tin"]: row.get("taxpayer_name") or ""
            for row in name_rows
        }

    rows = [
        {
            "tin": row["tin"],
            "taxpayer": taxpayer_map.get(row["tin"], ""),
            "net_profit": float(row["net_profit"] or 0),
        }
        for row in metric_rows
    ]
    return rows, {
        "metric_sql_ms": metric_sql_ms,
        "metric_fetch_ms": metric_fetch_ms,
        "name_sql_ms": name_sql_ms,
        "name_fetch_ms": name_fetch_ms,
    }


def _build_sales_vs_cogs_query(date_filter):
    yearly_financials = _cit_yearly_financials_subquery(date_filter)
    resolved_sales_sql = _cit_resolved_sales_sql("yearly", "ac")
    return text(f"""
        SELECT
            yearly.tax_period_year,
            SUM({resolved_sales_sql}) AS sales,
            SUM(COALESCE(yearly.cogs, 0)) AS cogs
        FROM ({yearly_financials}) yearly
        LEFT JOIN agg_cit ac
            ON {_tin_join_sql("yearly.tin", "ac.tin")}
            AND yearly.tax_period_year = ac.tax_period_year
        GROUP BY yearly.tax_period_year
        ORDER BY yearly.tax_period_year
    """)


def _fetch_sales_vs_cogs_rows(date_filter, date_params):
    rows, sql_execution_ms, fetch_ms = _fetch_mappings_with_timing(
        _build_sales_vs_cogs_query(date_filter),
        date_params,
    )
    return rows, {
        "sql_execution_ms": sql_execution_ms,
        "fetch_ms": fetch_ms,
    }


def _build_gross_sales_cogs_query(date_filter):
    yearly_financials = _cit_yearly_financials_subquery(date_filter)
    resolved_sales_sql = _cit_resolved_sales_sql("yearly", "ac")
    taxpayer_lookup_sql = str(_build_taxpayer_name_lookup_query(date_filter))
    return text(f"""
        SELECT
            yearly.tin AS tin,
            taxpayer_lookup.taxpayer_name,
            yearly.tax_period_year,
            {resolved_sales_sql} AS sales,
            COALESCE(yearly.cogs, 0) AS cogs
        FROM ({yearly_financials}) yearly
        LEFT JOIN agg_cit ac
            ON {_tin_join_sql("yearly.tin", "ac.tin")}
            AND yearly.tax_period_year = ac.tax_period_year
        LEFT JOIN ({taxpayer_lookup_sql}) taxpayer_lookup
            ON {_tin_join_sql("yearly.tin", "taxpayer_lookup.tin")}
        ORDER BY yearly.tax_period_year, yearly.tin
    """)


def _build_province_download_query(date_filter):
    taxpayer_lookup_sql = _build_taxpayer_name_lookup_query(date_filter).text
    return text(f"""
        SELECT
            province_base.tin,
            COALESCE(taxpayer_lookup.taxpayer_name, '') AS taxpayer_name,
            province_base.province,
            province_base.predicted_fraud,
            province_base.explanation
        FROM (
            SELECT
                CAST(pr.tin AS CHAR(50)) AS tin,
                lookup.province,
                MAX(pr.predicted_fraud) AS predicted_fraud,
                MAX(pr.Justification) AS explanation
            FROM cit_fraud_justification pr
            INNER JOIN tin_province_lookup lookup
                ON {_tin_join_sql("CAST(pr.tin AS CHAR(50))", "lookup.tin")}
            WHERE ({date_filter})
            GROUP BY CAST(pr.tin AS CHAR(50)), lookup.province
        ) province_base
        LEFT JOIN ({taxpayer_lookup_sql}) taxpayer_lookup
            ON {_tin_join_sql("province_base.tin", "taxpayer_lookup.tin")}
        ORDER BY province_base.province, taxpayer_name
    """)


# ============================================================
# Top 50 Net Profit Tax Payers
# ============================================================
@bp.get("/top-profit")
@jwt_required()
def top_profit():
    started_at = time.time()
    try:
        cache_params = _get_period_bounds()
        date_filter, date_params = get_date_filter(
            column_year="CAST(pr.tax_period_year AS UNSIGNED)",
        )
        top_n = get_top_n()

        def build_payload():
            rows, timings = _fetch_top_net_amount_rows(
                date_filter,
                date_params,
                top_n,
                positive=True,
            )
            serialization_started_at = time.perf_counter()
            payload = [
                {
                    "tin": row["tin"],
                    "taxpayer": row["taxpayer"],
                    "net_profit": row["net_profit"],
                }
                for row in rows
            ]
            json_serialization_ms = round((time.perf_counter() - serialization_started_at) * 1000, 2)
            _log_stage_timings(
                "top_profit",
                **timings,
                json_serialization_ms=json_serialization_ms,
                row_count=len(payload),
            )
            return payload

        payload = _cached_json(
            "top_profit",
            cache_params,
            900,
            build_payload,
            extra=str(top_n),
        )
        return jsonify(payload)
    finally:
        _log_timing("top_profit", started_at)

# ============================================================
# Top 50 Net Loss Tax Payers
# ============================================================
@bp.get("/top-loss")
@jwt_required()
def top_loss():
    started_at = time.time()
    try:
        cache_params = _get_period_bounds()
        date_filter, date_params = get_date_filter(
            column_year="CAST(pr.tax_period_year AS UNSIGNED)",
        )
        top_n = get_top_n()

        def build_payload():
            rows, timings = _fetch_top_net_amount_rows(
                date_filter,
                date_params,
                top_n,
                positive=False,
            )
            serialization_started_at = time.perf_counter()
            payload = [
                {
                    "tin": row["tin"],
                    "taxpayer": row["taxpayer"],
                    "net_loss": row["net_profit"],
                }
                for row in rows
            ]
            json_serialization_ms = round((time.perf_counter() - serialization_started_at) * 1000, 2)
            _log_stage_timings(
                "top_loss",
                **timings,
                json_serialization_ms=json_serialization_ms,
                row_count=len(payload),
            )
            return payload

        payload = _cached_json(
            "top_loss",
            cache_params,
            900,
            build_payload,
            extra=str(top_n),
        )
        return jsonify(payload)
    finally:
        _log_timing("top_loss", started_at)

# ============================================================
# Segmentation Distribution
# ============================================================
@bp.get("/segmentation-distribution")
@jwt_required()
def segmentation_distribution():
    started_at = time.time()
    try:
        cache_params = _get_period_bounds()
        date_filter, date_params = get_date_filter(
            column_year="tax_period_year",
        )
        if not _cit_rows_exist(date_filter, date_params):
            return jsonify({"labels": [], "series": []})

        query = text(f"""
            SELECT
                COALESCE(sm.segmentation, 'Unknown') AS segmentation,
                COUNT(*) AS total
            FROM (
                SELECT DISTINCT CAST(pr.tin AS CHAR(50)) AS tin
                FROM cit_fraud_justification pr
                WHERE ({date_filter})
            ) pr
            LEFT JOIN taxpayer_segmentation_master sm
                ON {_tin_join_sql("sm.tin", "pr.tin")}
            GROUP BY COALESCE(sm.segmentation, 'Unknown')
        """)

        payload = _cached_json(
            "segmentation_distribution",
            cache_params,
            900,
            lambda: (
                lambda rows: {
                    "labels": [
                        _normalize_unknown_label(r.segmentation, "Unknown")
                        for r in rows
                    ],
                    "series": [r.total for r in rows],
                }
            )(db.session.execute(query, date_params).fetchall())
        )
        return jsonify(payload)
    finally:
        _log_timing("segmentation_distribution", started_at)


# ============================================================
# Risk Distribution
# ============================================================
@bp.get("/risk-distribution")
@jwt_required()
def risk_distribution():
    started_at = time.time()
    try:
        cache_params = _get_period_bounds()
        date_filter, date_params = get_date_filter(
            column_year="tax_period_year",
        )
        if not _cit_rows_exist(date_filter, date_params):
            return jsonify({"labels": [], "series": []})

        risk_flag_expr = _predicted_fraud_flag_sql("predicted_fraud")
        risk_label_expr = _predicted_fraud_label_sql("predicted_fraud")

        query = text(f"""
            SELECT
                SUM(CASE WHEN {risk_flag_expr} = 1 THEN 1 ELSE 0 END) AS risk_flagged,
                SUM(CASE WHEN {risk_label_expr} = 'Non-Fraud' THEN 1 ELSE 0 END) AS non_risk_flagged
            FROM cit_fraud_justification
            WHERE ({date_filter})
        """)

        payload = _cached_json(
            "risk_distribution",
            cache_params,
            900,
            lambda: (
                lambda row: (
                    {"labels": [], "series": []}
                    if ((row["risk_flagged"] or 0) + (row["non_risk_flagged"] or 0)) == 0
                    else {
                        "labels": ["Risk Flagged", "Non-Risk Flagged"],
                        "series": [
                            int(row["risk_flagged"] or 0),
                            int(row["non_risk_flagged"] or 0),
                        ],
                    }
                )
            )(db.session.execute(query, date_params).mappings().one())
        )
        return jsonify(payload)
    finally:
        _log_timing("risk_distribution", started_at)

# ============================================================
# Superannuation PNG vs Foreign
# ============================================================
@bp.get("/superannuation")
@jwt_required()
def superannuation_distribution():
    started_at = time.time()
    try:
        cache_params = _get_period_bounds()
        date_filter, date_params = get_date_filter(
            column_year="pr.tax_period_year",
        )
        if not _cit_rows_exist(date_filter, date_params):
            return jsonify({
                "categories": ["PNG", "Foreign"],
                "series": [{
                    "name": "Amount (PGK)",
                    "data": [0.0, 0.0],
                }]
            })

        query = text(f"""
            SELECT
                COALESCE(SUM(COALESCE(pr.superannuation_png, 0)), 0) AS png,
                COALESCE(SUM(COALESCE(pr.superannuation_foreign, 0)), 0) AS foreign_amt
            FROM cit_fraud_justification pr
            LEFT JOIN agg_cit ac
                ON {_tin_join_sql("pr.tin", "ac.tin")}
                AND pr.tax_period_year = ac.tax_period_year
            WHERE ({date_filter})
        """)

        payload = _cached_json(
            "superannuation_distribution",
            cache_params,
            900,
            lambda: (
                lambda row: {
                    "categories": ["PNG", "Foreign"],
                    "series": [{
                        "name": "Amount (PGK)",
                        "data": [float(row["png"] or 0), float(row["foreign_amt"] or 0)],
                    }]
                }
            )(db.session.execute(query, date_params).mappings().one())
        )
        return jsonify(payload)
    finally:
        _log_timing("superannuation_distribution", started_at)



# ============================================================
# Interest (Income)
# ============================================================
@bp.get("/interest")
@jwt_required()
def interest_distribution():
    started_at = time.time()
    try:
        cache_params = _get_period_bounds()
        date_filter, date_params = get_date_filter(
            column_year="pr.tax_period_year",
        )
        if not _cit_rows_exist(date_filter, date_params):
            return jsonify({
                "categories": [
                    "Interest Income",
                    "Foreign Interest Expense"
                ],
                "series": [{
                    "name": "Amount (PGK)",
                    "data": [0.0, 0.0],
                }]
            })

        query = text(f"""
            SELECT
                COALESCE(SUM(COALESCE(pr.interest_income, 0)), 0) AS interest,
                COALESCE(SUM(COALESCE(pr.interest_expense_foreign, 0)), 0) AS foreign_interest_expense
            FROM cit_fraud_justification pr
            LEFT JOIN agg_cit ac
                ON {_tin_join_sql("pr.tin", "ac.tin")}
                AND pr.tax_period_year = ac.tax_period_year
            WHERE ({date_filter})
        """)

        payload = _cached_json(
            "interest_distribution",
            cache_params,
            900,
            lambda: (
                lambda row: {
                    "categories": [
                        "Interest Income",
                        "Foreign Interest Expense"
                    ],
                    "series": [{
                        "name": "Amount (PGK)",
                        "data": [
                            float(row["interest"] or 0),
                            float(row["foreign_interest_expense"] or 0),
                        ],
                    }]
                }
            )(db.session.execute(query, date_params).mappings().one())
        )
        return jsonify(payload)
    finally:
        _log_timing("interest_distribution", started_at)



# ============================================================
# Sales vs COGS
# ============================================================
@bp.get("/sales-vs-cogs")
@jwt_required()
def sales_vs_cogs():
    started_at = time.time()
    try:
        cache_params = _get_period_bounds()
        date_filter, date_params = get_date_filter(
            column_year="pr.tax_period_year",
        )
        if not _cit_rows_exist(date_filter, date_params):
            return jsonify({
                "categories": [],
                "series": [
                    {"name": "Gross Income", "data": []},
                    {"name": "COGS", "data": []},
                ],
            })

        def build_payload():
            rows, timings = _fetch_sales_vs_cogs_rows(date_filter, date_params)
            serialization_started_at = time.perf_counter()
            payload = {
                "categories": [str(row["tax_period_year"]) for row in rows],
                "series": [
                    {"name": "Gross Income", "data": [float(row["sales"] or 0) for row in rows]},
                    {"name": "COGS", "data": [float(row["cogs"] or 0) for row in rows]},
                ],
            }
            json_serialization_ms = round((time.perf_counter() - serialization_started_at) * 1000, 2)
            _log_stage_timings(
                "sales_vs_cogs",
                **timings,
                json_serialization_ms=json_serialization_ms,
                row_count=len(rows),
            )
            return payload

        payload = _cached_json(
            "sales_vs_cogs",
            cache_params,
            900,
            build_payload,
        )
        return jsonify(payload)
    finally:
        _log_timing("sales_vs_cogs", started_at)


# ============================================================
# Latest CIT Records
# ============================================================
@bp.get("/latest-records")
@jwt_required()
def latest_records():
    started_at = time.time()
    total_started_at = time.perf_counter()
    try:
        cache_params, date_filter, date_params = _get_year_filter_context(
            column_year="pr.tax_period_year"
        )
        limit = _get_request_limit(default=100, maximum=500)
        if not _cit_rows_exist(date_filter, date_params):
            return jsonify([])

        payload = _cached_json(
            "latest_records",
            cache_params,
            900,
            lambda: _build_latest_records_payload(date_filter, date_params, limit),
            extra=str(limit),
        )
        response = jsonify(payload)
        total_api_ms = round((time.perf_counter() - total_started_at) * 1000, 2)
        current_app.logger.info(
            "latest_records total_api_ms=%s payload_rows=%s",
            total_api_ms,
            len(payload),
        )
        return response
    finally:
        _log_timing("latest_records", started_at)

# ============================================================
# Sales vs COGS Details (By Year)
# ============================================================
@details_bp.get("/sales-cogs-details")
@jwt_required()
def sales_cogs_details():
    year = request.args.get("year")
    limit = request.args.get("limit", 200)

    if not year:
        return jsonify({"success": False, "message": "year is required"}), 400

    try:
        year = int(year)
    except ValueError:
        return jsonify({"success": False, "message": "year must be a valid number"}), 400

    try:
        limit = int(limit)
    except ValueError:
        limit = 200

    if limit <= 0:
        limit = 200
    if limit > 1000:
        limit = 1000

    try:
        taxpayer_name_sql = _cit_taxpayer_name_sql()
        rows = db.session.execute(
            text("""
                SELECT
                    pr.tin,
                    {taxpayer_name_sql} AS taxpayer_name,
                    COALESCE(ac.cit_total_gross_income, pr.total_gross_income, 0) AS gross_sales,
                    COALESCE(pr.cost_of_goods_sold, 0) AS cogs,
                    COALESCE(NULLIF(TRIM(tr.enterpriseactivity), ''), NULL) AS sector
                FROM cit_fraud_justification pr
                LEFT JOIN agg_cit ac
                    ON {_tin_join_sql("pr.tin", "ac.tin")}
                    AND pr.tax_period_year = ac.tax_period_year
                LEFT JOIN tin_registration_mst tr
                    ON {_tin_join_sql("TRIM(pr.tin)", "TRIM(tr.tin)")}
                WHERE pr.tax_period_year = :year
                ORDER BY gross_sales DESC
                LIMIT :limit
            """.format(taxpayer_name_sql=taxpayer_name_sql)),
            {"year": year, "limit": limit}
        ).mappings().all()

        data = [{
            "tin": r.get("tin") or "",
            "taxpayer_name": r.get("taxpayer_name") or "",
            "gross_sales": float(r.get("gross_sales") or 0),
            "cogs": float(r.get("cogs") or 0),
            "sector": r.get("sector") or "",
        } for r in rows]

        return jsonify({"success": True, "data": data})

    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500

# ============================================================
# Province by Fraud Risk
# ============================================================


# --------------------------------------------------
# Helper utilities for CIT CSV downloads
# --------------------------------------------------
_CIT_BASE_QUERY = """
    SELECT
        pr.tin,
        {taxpayer_name_sql} AS taxpayer_name,
        COALESCE(ac.cit_total_gross_income, pr.total_gross_income, 0) AS gross_sales,
        COALESCE(pr.cost_of_goods_sold, 0) AS cogs,
        COALESCE(ac.cit_total_gross_income, pr.total_gross_income, 0) - COALESCE(pr.cost_of_goods_sold, 0) AS net_profit,
        COALESCE(pr.cost_of_goods_sold, 0) - COALESCE(ac.cit_total_gross_income, pr.total_gross_income, 0) AS net_loss,
        COALESCE(pr.superannuation_png, 0) AS superannuation_png,
        COALESCE(pr.superannuation_foreign, 0) AS superannuation_foreign,
        COALESCE(pr.interest_income, 0) AS interest_income,
        COALESCE(pr.predicted_fraud, 'Fraud') AS risk_flag,
        COALESCE(tr.province, 'UNKNOWN') AS province,
        COALESCE(sm.segmentation, 'Unknown') AS segmentation,
        pr.tax_period_year
    FROM cit_fraud_justification pr
    LEFT JOIN agg_cit ac
        ON {_tin_join_sql("pr.tin", "ac.tin")}
        AND pr.tax_period_year = ac.tax_period_year
    LEFT JOIN tin_registration_mst tr ON {_tin_join_sql("TRIM(pr.tin)", "TRIM(tr.tin)")}
    LEFT JOIN taxpayer_segmentation_master sm
        ON {_tin_join_sql("sm.tin", "CAST(pr.tin AS CHAR(50))")}
    WHERE ({date_filter})
    {extra_filter}
    ORDER BY pr.tax_period_year, pr.tin
"""


def _collect_year_params():
    _, params = get_date_filter(column_year="pr.tax_period_year")
    return params


def _cit_base_query(extra_filter=""):
    date_filter, _ = get_date_filter(column_year="pr.tax_period_year")
    return text(_CIT_BASE_QUERY.format(
        extra_filter=extra_filter,
        date_filter=date_filter,
        taxpayer_name_sql=_cit_taxpayer_name_sql(),
    ))


def _fetch_base_rows(extra_filter="", extra_params=None, base_params=None):
    params = dict(base_params) if base_params else _collect_year_params()
    if extra_params:
        params.update(extra_params)
    query = _cit_base_query(extra_filter)
    return db.session.execute(query, params).mappings().all()


def _normalize_row(row):
    return {
        "tin": row.get("tin") or "",
        "taxpayer_name": row.get("taxpayer_name") or "",
        "net_profit": float(row.get("net_profit") or 0),
        "net_loss": float(row.get("net_loss") or 0),
        "gross_sales": float(row.get("gross_sales") or 0),
        "cogs": float(row.get("cogs") or 0),
        "superannuation_type": "",
        "interest_type": "",
        "amount": 0,
        "risk_flag": int(bool(row.get("risk_flag"))),
        "province": row.get("province") or "",
        "segmentation": row.get("segmentation") or "",
        "year": row.get("tax_period_year"),
        "superannuation_png": float(row.get("superannuation_png") or 0),
        "superannuation_foreign": float(row.get("superannuation_foreign") or 0),
        "interest_income": float(row.get("interest_income") or 0),
    }

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


def _debug_csv_sample(label, data):
    try:
        print(f"[csv-debug] {label}: {data[:5]}")
    except Exception:
        pass


def _build_in_clause(field, values, prefix):
    if not values:
        return "", {}

    placeholders = []
    params = {}
    for idx, value in enumerate(values, start=1):
        key = f"{prefix}_{idx}"
        placeholders.append(f":{key}")
        params[key] = value

    clause = f" AND {field} IN ({', '.join(placeholders)})"
    return clause, params


def _get_top_tins_by_profit(params, positive=True):
    operator = ">" if positive else "<"
    order = "DESC" if positive else "ASC"
    date_filter, date_params = get_date_filter(column_year="pr.tax_period_year")

    merged_params = dict(date_params)
    if params:
        merged_params.update(params)

    query = text(f"""
        SELECT
            tin,
            SUM(COALESCE(ac.cit_total_gross_income, pr.total_gross_income, 0))
          - SUM(COALESCE(pr.cost_of_goods_sold, 0)) AS net_profit
        FROM cit_fraud_justification pr
        LEFT JOIN agg_cit ac
            ON {_tin_join_sql("pr.tin", "ac.tin")}
            AND pr.tax_period_year = ac.tax_period_year
        WHERE ({date_filter})
        GROUP BY pr.tin
        HAVING net_profit {operator} 0
        ORDER BY net_profit {order}
        LIMIT 50
    """)

    rows = db.session.execute(query, merged_params).mappings().all()
    return [r["tin"] for r in rows]


def _prepare_rows_for_response(base_rows):
    return [_normalize_row(r) for r in base_rows]


def _attach_superannuation_entries(rows):
    entries = []
    for row in rows:
        if row["superannuation_png"] > 0:
            entry = row.copy()
            entry["superannuation_type"] = "PNG"
            entry["amount"] = row["superannuation_png"]
            entries.append(entry)

        if row["superannuation_foreign"] > 0:
            entry = row.copy()
            entry["superannuation_type"] = "Foreign"
            entry["amount"] = row["superannuation_foreign"]
            entries.append(entry)

    return entries


def _attach_interest_entries(rows):
    entries = []
    for row in rows:
        if row["interest_income"] > 0:
            entry = row.copy()
            entry["interest_type"] = "Interest Income"
            entry["amount"] = row["interest_income"]
            entries.append(entry)
    return entries


# ========================================
# CIT CSV Download endpoints
# ========================================
@download_bp.get("/net-profit")
@jwt_required()
def download_net_profit():
    started_at = time.time()
    try:
        date_filter, date_params = get_date_filter(
            column_year="CAST(pr.tax_period_year AS UNSIGNED)",
        )
        top_n = get_top_n()

        rows, timings = _fetch_top_net_amount_rows(
            date_filter,
            date_params,
            top_n,
            positive=True,
        )

        transform_started_at = time.perf_counter()
        data = [{
            "tin": row.get("tin") or "",
            "taxpayer_name": row.get("taxpayer"),
            "net_profit": float(row.get("net_profit") or 0),
        } for row in rows if (row.get("net_profit") or 0) > 0]
        transform_ms = round((time.perf_counter() - transform_started_at) * 1000, 2)

        _debug_csv_sample("cit-net-profit", data)
        allowed = ["tin", "taxpayer_name", "net_profit"]
        columns = _parse_columns(["net_profit"], allowed, include_ids=True)

        csv_started_at = time.perf_counter()
        response = _build_csv_response(data, "net-profit.csv", columns)
        csv_generation_ms = round((time.perf_counter() - csv_started_at) * 1000, 2)
        _log_stage_timings(
            "download_net_profit",
            **timings,
            transform_ms=transform_ms,
            csv_generation_ms=csv_generation_ms,
            row_count=len(data),
        )
        return response
    finally:
        _log_timing("download_net_profit", started_at)


@download_bp.get("/net-loss")
@jwt_required()
def download_net_loss():
    started_at = time.time()
    try:
        date_filter, date_params = get_date_filter(
            column_year="CAST(pr.tax_period_year AS UNSIGNED)",
        )
        top_n = get_top_n()

        rows, timings = _fetch_top_net_amount_rows(
            date_filter,
            date_params,
            top_n,
            positive=False,
        )

        transform_started_at = time.perf_counter()
        data = [{
            "tin": row.get("tin") or "",
            "taxpayer_name": row.get("taxpayer"),
            "net_loss": float(row.get("net_profit") or 0),
        } for row in rows if (row.get("net_profit") or 0) < 0]
        transform_ms = round((time.perf_counter() - transform_started_at) * 1000, 2)

        _debug_csv_sample("cit-net-loss", data)
        allowed = ["tin", "taxpayer_name", "net_loss"]
        columns = _parse_columns(["net_loss"], allowed, include_ids=True)

        csv_started_at = time.perf_counter()
        response = _build_csv_response(data, "net-loss.csv", columns)
        csv_generation_ms = round((time.perf_counter() - csv_started_at) * 1000, 2)
        _log_stage_timings(
            "download_net_loss",
            **timings,
            transform_ms=transform_ms,
            csv_generation_ms=csv_generation_ms,
            row_count=len(data),
        )
        return response
    finally:
        _log_timing("download_net_loss", started_at)


@download_bp.get("/segmentation")
@jwt_required()
def download_segmentation():
    date_filter, date_params = get_date_filter(column_year="pr.tax_period_year")
    rows = db.session.execute(
        text(f"""
            SELECT
                pr.tin AS tin,
                COALESCE(NULLIF(TRIM(sm.taxpayer_name), ''), pr.taxpayer_name, 'Unknown') AS taxpayer_name,
                COALESCE(sm.segmentation, 'Unknown') AS segmentation
            FROM (
                SELECT
                    CAST(pr.tin AS CHAR(50)) AS tin,
                    MAX(CONVERT(COALESCE(
                        NULLIF(TRIM(pr.taxpayer), ''),
                        NULLIF(TRIM(ac.taxpayer_name), ''),
                        NULLIF(TRIM(tr.taxpayername), ''),
                        NULLIF(TRIM(tr.maintradename), ''),
                        ''
                    ) USING utf8mb4)) AS taxpayer_name
                FROM cit_fraud_justification pr
                LEFT JOIN agg_cit ac
                    ON {_tin_join_sql("pr.tin", "ac.tin")}
                    AND pr.tax_period_year = ac.tax_period_year
                LEFT JOIN tin_registration_mst tr
                    ON {_tin_join_sql("TRIM(pr.tin)", "TRIM(tr.tin)")}
                WHERE ({date_filter})
                GROUP BY CAST(pr.tin AS CHAR(50))
            ) pr
            LEFT JOIN taxpayer_segmentation_master sm
                ON {_tin_join_sql("sm.tin", "pr.tin")}
            ORDER BY pr.tin
        """),
        date_params
    ).mappings().all()

    data = [{
        "tin": r.get("tin") or "",
        "taxpayer_name": r.get("taxpayer_name"),
        "segmentation": r.get("segmentation"),
    } for r in rows]

    _debug_csv_sample("cit-segmentation", data)
    allowed = ["tin", "taxpayer_name", "segmentation"]
    columns = _parse_columns(["segmentation"], allowed, include_ids=True)
    return _build_csv_response(data, "segmentation.csv", columns)


@download_bp.get("/risk-flagged")
@jwt_required()
def download_risk_flagged():
    date_filter, date_params = get_date_filter(column_year="pr.tax_period_year")
    risk_label_expr = _predicted_fraud_label_sql("pr.predicted_fraud")
    taxpayer_name_agg_sql = _cit_taxpayer_name_agg_sql()
    rows = db.session.execute(
        text(f"""
            SELECT 
                pr.tin AS tin,
                {taxpayer_name_agg_sql} AS taxpayer_name,
                {risk_label_expr} AS risk_flag,
                COUNT(*) AS total
            FROM cit_fraud_justification pr
            LEFT JOIN agg_cit ac
                ON {_tin_join_sql("pr.tin", "ac.tin")}
                AND pr.tax_period_year = ac.tax_period_year
            LEFT JOIN tin_registration_mst tr
                ON {_tin_join_sql("TRIM(pr.tin)", "TRIM(tr.tin)")}
            WHERE ({date_filter})
            GROUP BY pr.tin, {risk_label_expr}
            ORDER BY pr.tin
        """),
        date_params
    ).fetchall()

    data = [{
        "tin": r.tin or "",
        "taxpayer_name": r.taxpayer_name,
        "risk_flag": r.risk_flag or "Unknown",
        "total": int(r.total or 0)
    } for r in rows]

    _debug_csv_sample("cit-risk-flagged", data)
    allowed = ["tin", "taxpayer_name", "risk_flag", "total"]
    columns = _parse_columns(["risk_flag", "total"], allowed, include_ids=True)
    return _build_csv_response(data, "risk-flagged.csv", columns)


@download_bp.get("/superannuation")
@jwt_required()
def download_superannuation():
    date_filter, date_params = get_date_filter(column_year="pr.tax_period_year")
    taxpayer_name_agg_sql = _cit_taxpayer_name_agg_sql()
    rows = db.session.execute(
        text(f"""
            SELECT
                pr.tin AS tin,
                {taxpayer_name_agg_sql} AS taxpayer_name,
                SUM(COALESCE(pr.superannuation_png, 0)) AS png,
                SUM(COALESCE(pr.superannuation_foreign, 0)) AS foreign_amt
            FROM cit_fraud_justification pr
            LEFT JOIN agg_cit ac
                ON {_tin_join_sql("pr.tin", "ac.tin")}
                AND pr.tax_period_year = ac.tax_period_year
            LEFT JOIN tin_registration_mst tr
                ON {_tin_join_sql("TRIM(pr.tin)", "TRIM(tr.tin)")}
            WHERE ({date_filter})
            GROUP BY pr.tin
            ORDER BY pr.tin
        """),
        date_params
    ).mappings().all()

    data = []
    for r in rows:
        data.append({
            "tin": r.get("tin") or "",
            "taxpayer_name": r.get("taxpayer_name"),
            "superannuation_type": "PNG",
            "amount": float(r.get("png") or 0)
        })
        data.append({
            "tin": r.get("tin") or "",
            "taxpayer_name": r.get("taxpayer_name"),
            "superannuation_type": "Foreign",
            "amount": float(r.get("foreign_amt") or 0)
        })

    _debug_csv_sample("cit-superannuation", data)
    allowed = ["tin", "taxpayer_name", "superannuation_type", "amount"]
    columns = _parse_columns(["superannuation_type", "amount"], allowed, include_ids=True)
    return _build_csv_response(data, "superannuation.csv", columns)


@download_bp.get("/interest")
@jwt_required()
def download_interest():
    date_filter, date_params = get_date_filter(column_year="pr.tax_period_year")
    taxpayer_name_agg_sql = _cit_taxpayer_name_agg_sql()
    rows = db.session.execute(
        text(f"""
            SELECT
                pr.tin AS tin,
                {taxpayer_name_agg_sql} AS taxpayer_name,
                SUM(COALESCE(pr.interest_income, 0)) AS interest,
                SUM(COALESCE(pr.interest_expense_foreign, 0)) AS foreign_interest_expense
            FROM cit_fraud_justification pr
            LEFT JOIN agg_cit ac
                ON {_tin_join_sql("pr.tin", "ac.tin")}
                AND pr.tax_period_year = ac.tax_period_year
            LEFT JOIN tin_registration_mst tr
                ON {_tin_join_sql("TRIM(pr.tin)", "TRIM(tr.tin)")}
            WHERE ({date_filter})
            GROUP BY pr.tin
            ORDER BY pr.tin
        """),
        date_params
    ).mappings().all()

    data = []
    for r in rows:
        data.append({
            "tin": r.get("tin") or "",
            "taxpayer_name": r.get("taxpayer_name"),
            "interest_type": "Interest Income",
            "amount": float(r.get("interest") or 0)
        })
        data.append({
            "tin": r.get("tin") or "",
            "taxpayer_name": r.get("taxpayer_name"),
            "interest_type": "Foreign Interest Expense",
            "amount": float(r.get("foreign_interest_expense") or 0)
        })

    _debug_csv_sample("cit-interest", data)
    allowed = ["tin", "taxpayer_name", "interest_type", "amount"]
    columns = _parse_columns(["interest_type", "amount"], allowed, include_ids=True)
    return _build_csv_response(data, "interest.csv", columns)


@download_bp.get("/province")
@jwt_required()
def download_province():
    started_at = time.time()
    province_query = None
    date_params = None
    try:
        date_filter, date_params = get_date_filter(column_year="pr.tax_period_year")
        province_query = _build_province_download_query(date_filter)

        rows, sql_execution_ms, fetch_ms = _fetch_mappings_with_timing(
            province_query,
            date_params,
        )

        transform_started_at = time.perf_counter()
        data = [
            {
                "tin": row.get("tin") or "",
                "taxpayer_name": row.get("taxpayer_name") or "",
                "province": row.get("province") or "UNKNOWN",
                "predicted_fraud": row.get("predicted_fraud") or "Non-Fraud",
                "explanation": row.get("explanation") or ""
            }
            for row in rows
        ]
        transform_ms = round((time.perf_counter() - transform_started_at) * 1000, 2)

        columns = [
            "tin",
            "taxpayer_name",
            "province",
            "predicted_fraud",
            "explanation"
        ]
        _debug_csv_sample("cit-province", data)

        csv_started_at = time.perf_counter()
        response = _build_csv_response(data, "province.csv", columns)
        csv_generation_ms = round((time.perf_counter() - csv_started_at) * 1000, 2)
        _log_stage_timings(
            "download_province",
            sql_execution_ms=sql_execution_ms,
            fetch_ms=fetch_ms,
            transform_ms=transform_ms,
            csv_generation_ms=csv_generation_ms,
            row_count=len(data),
        )
        return response
    except Exception as exc:
        current_app.logger.exception(
            "download_province failed; sql=%s; params=%s; sqlalchemy_exception=%r; mysql_exception=%r",
            province_query.text if province_query is not None else None,
            date_params,
            exc,
            getattr(exc, "orig", None),
        )
        raise
    finally:
        _log_timing("download_province", started_at)



@download_bp.get("/latest-records")
@jwt_required()
def download_latest_records():
    _, date_filter, date_params = _get_year_filter_context(
        column_year="pr.tax_period_year"
    )
    limit = _get_request_limit(default=100, maximum=500)
    data = _build_latest_records_payload(date_filter, date_params, limit)

    _debug_csv_sample("cit-latest-records", data)
    columns = [
        "tin",
        "taxpayer_name",
        "tax_period_year",
        "gross_income",
        "gross_sales",
        "cogs",
        "net_profit",
        "predicted_fraud",
    ]
    return _build_csv_response(data, "latest-cit-records.csv", columns)


@download_bp.get("/gross-sales-cogs")
@jwt_required()
def download_gross_sales_cogs():
    started_at = time.time()
    try:
        date_filter, date_params = get_date_filter(column_year="pr.tax_period_year")
        rows, sql_execution_ms, fetch_ms = _fetch_mappings_with_timing(
            _build_gross_sales_cogs_query(date_filter),
            date_params,
        )

        transform_started_at = time.perf_counter()
        data = []
        for row in rows:
            sales = float(row.get("sales") or 0)
            cogs = float(row.get("cogs") or 0)
            percent = ((sales - cogs) / sales * 100) if sales else 0
            data.append({
                "tin": row.get("tin") or "",
                "taxpayer_name": row.get("taxpayer_name"),
                "period": str(row.get("tax_period_year")),
                "gross_sales": sales,
                "cogs": cogs,
                "sales_cogs_percent": round(percent, 2),
            })
        transform_ms = round((time.perf_counter() - transform_started_at) * 1000, 2)

        _debug_csv_sample("cit-gross-sales-cogs", data)
        allowed = ["tin", "taxpayer_name", "period", "gross_sales", "cogs", "sales_cogs_percent"]
        columns = _parse_columns(["period", "gross_sales", "cogs", "sales_cogs_percent"], allowed, include_ids=True)

        csv_started_at = time.perf_counter()
        response = _build_csv_response(data, "gross-sales-cogs.csv", columns)
        csv_generation_ms = round((time.perf_counter() - csv_started_at) * 1000, 2)
        _log_stage_timings(
            "download_gross_sales_cogs",
            sql_execution_ms=sql_execution_ms,
            fetch_ms=fetch_ms,
            transform_ms=transform_ms,
            csv_generation_ms=csv_generation_ms,
            row_count=len(data),
        )
        return response
    finally:
        _log_timing("download_gross_sales_cogs", started_at)


# ============================================================
# F) Fraud Province Distribution (CIT) - FIXED
# ============================================================
@bp.get("/fraud-province-distribution-cit")
@jwt_required()
def fraud_province_distribution_cit():
    started_at = time.time()
    province_sql = None
    date_params = None
    try:
        params = _get_period_bounds()
        try:
            _warn_if_cit_province_index_missing()
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
            "EAST SEPIK": "East Sepik",
            "EASTERN HIGHLANDS": "Eastern Highlands",
            "WESTERN HIGHLANDS": "Western Highlands",
            "SOUTHERN HIGHLANDS": "Southern Highlands",
            "NEW IRELAND": "New Ireland",
            "MANUS": "Manus",
            "MILNE BAY": "Milne Bay",
            "ORO": "Oro (Northern)",
            "NORTHERN": "Oro (Northern)",
            "BOUGAINVILLE": "Bougainville",
            "NORTH SOLOMONS": "Bougainville",
            "WEST NEW BRITAIN": "West New Britain",
            "EAST NEW BRITAIN": "East New Britain",
            "WESTERN": "Western (Fly)",
            "FLY": "Western (Fly)",
            "NATIONAL CAPITAL DISTRICT": "National Capital District",
            "PORT MORESBY": "National Capital District",
            "HELA": "Hela",
            "JIWAKA": "Jiwaka",
            "CENTRAL": "Central",
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

        date_filter, date_params = get_date_filter(column_year="pr.tax_period_year")
        start_year = params["start_year"]
        end_year = params["end_year"]
        if not _cit_rows_exist(date_filter, date_params):
            return jsonify({
                "success": True,
                "province_distribution": {},
                "date_range": {
                    "start": str(start_year),
                    "end": str(end_year),
                },
            })

        province_sql = text(f"""
            SELECT
                lookup.province AS province,
                COUNT(*) AS total_tins,
                SUM(filtered.is_fraud_flag) AS fraud_tins
            FROM (
                SELECT
                    CAST(pr.tin AS CHAR(50) CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci AS tin,
                    MAX(
                        CASE
                            WHEN UPPER(TRIM(COALESCE(pr.predicted_fraud, ''))) IN ('FRAUD','RISK','YES','Y','1','TRUE')
                            THEN 1
                            ELSE 0
                        END
                    ) AS is_fraud_flag
                FROM cit_fraud_justification pr
                WHERE ({date_filter})
                  AND pr.tin IS NOT NULL
                GROUP BY CAST(pr.tin AS CHAR(50) CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci
            ) AS filtered
            INNER JOIN tin_province_lookup lookup
                ON {_tin_join_sql("filtered.tin", "lookup.tin")}
            GROUP BY lookup.province
        """)

        payload = _cached_json(
            "fraud_province_distribution_cit",
            params,
            1800,
            lambda: _build_province_payload(
                province_sql,
                date_params,
                normalize_province,
                start_year,
                end_year,
            )
        )

        return jsonify(payload)
    except Exception as exc:
        current_app.logger.exception(
            "fraud_province_distribution_cit failed; original_exception=%r; sql=%s; params=%s",
            getattr(exc, "orig", exc),
            province_sql.text if province_sql is not None else None,
            date_params,
        )
        raise
    finally:
        _log_timing("fraud_province_distribution_cit", started_at)










