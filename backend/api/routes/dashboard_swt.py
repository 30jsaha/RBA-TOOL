# app/blueprints/dashboard_swt.py

from flask import Blueprint, jsonify, request, Response, current_app
from flask_jwt_extended import jwt_required
from sqlalchemy import text
from datetime import datetime
from dateutil.relativedelta import relativedelta
from ..extensions import cache, db
import pandas as pd
import os
import csv
from itertools import chain
from io import StringIO
import time

bp = Blueprint("dashboard_swt", __name__, url_prefix="/api/swt/dashboard")
download_bp = Blueprint("dashboard_swt_download", __name__, url_prefix="/api/swt/download-csv")

CSV_HEADERS = [
    "tin",
    "taxpayer_name",
    "salary_wages_paid",
    "swt_deducted",
    "fraud_flag",
    "risk_flag",
    "month",
    "province",
    "segmentation",
]




# ============================================================
# Helper: Determine date range (same as GST dashboard)
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

    return {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month,
    }


def get_date_range():
    """
    Handles '1m', '3m', '6m', '1y', and 'custom'
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

    return {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month,
    }


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


def _get_period_filter(column_year="tax_period_year", column_month="tax_period_month"):
    return _period_filter_sql(column_year=column_year, column_month=column_month), _get_period_bounds()

def _log_timing(endpoint_name, started_at):
    try:
        elapsed = round(time.time() - started_at, 2)
        current_app.logger.info(
            f"dashboard_swt.py :: {endpoint_name} took {elapsed}s"
        )
    except Exception:
        pass


def _cache_key(endpoint_name, params, extra=""):
    key = (
        f"swt_dashboard:{endpoint_name}:"
        f"{params['start_year']}-{int(params['start_month']):02d}:"
        f"{params['end_year']}-{int(params['end_month']):02d}"
    )
    if extra:
        key = f"{key}:{extra}"
    return key


def _cached_json(endpoint_name, params, timeout, builder, extra=""):
    _warn_missing_dashboard_indexes()
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


def _format_month_label(month, year):
    if month is None or year is None:
        return ""

    try:
        return f"{int(month):02d}-{int(year)}"
    except (TypeError, ValueError):
        return f"{month}-{year}"


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


def _stream_mappings(statement, params):
    return db.session.execute(
        statement.execution_options(stream_results=True),
        params,
    ).mappings()

def _debug_csv_sample(label, data):
    try:
        print(f"[csv-debug] {label}: {data[:5]}")
    except Exception:
        pass


_INDEX_WARNINGS_LOGGED = False


def _warn_missing_dashboard_indexes():
    global _INDEX_WARNINGS_LOGGED
    if _INDEX_WARNINGS_LOGGED:
        return

    required_indexes = {
        "swt_fraud_justification": {
            "idx_swt_period",
            "idx_swt_period_tin",
            "idx_swt_period_fraud_tin",
            "idx_swt_uploaded_at",
            "idx_swt_period_uploaded",
        },
        "tin_province_lookup": {
            "PRIMARY",
            "idx_lookup_province",
        },
    }

    try:
        missing = []
        for table_name, expected_indexes in required_indexes.items():
            result = db.session.execute(text(f"SHOW INDEX FROM {table_name}"))
            existing_indexes = set()
            for row in result:
                mapping = row._mapping if hasattr(row, "_mapping") else row
                index_name = mapping.get("Key_name")
                if index_name:
                    existing_indexes.add(index_name)
            for index_name in sorted(expected_indexes - existing_indexes):
                missing.append(f"{table_name}.{index_name}")

        if missing:
            current_app.logger.warning(
                "dashboard_swt.py :: missing recommended indexes: %s",
                ", ".join(missing),
            )
    except Exception:
        current_app.logger.exception("dashboard_swt.py :: failed to verify indexes")
    finally:
        _INDEX_WARNINGS_LOGGED = True
# ============================================================
# A) SWT Summary Cards
# ============================================================
@bp.get("/data")
@jwt_required()
def swt_summary_cards():
    started_at = time.time()
    try:
        date_params = _get_period_bounds()
        start_year = date_params["start_year"]
        start_month = date_params["start_month"]
        end_year = date_params["end_year"]
        end_month = date_params["end_month"]

        query = text(f"""
            SELECT 
                COUNT(DISTINCT pr.tin) AS total_employers,
                SUM(COALESCE(pr.employees_on_payroll, 0)) AS employees_on_payroll,
                SUM(COALESCE(pr.employees_paid_swt, 0)) AS employees_paid_swt,
                SUM(COALESCE(pr.total_swt_tax_deducted, 0)) AS total_swt_tax_deducted,
                SUM(COALESCE(pr.total_salary_wages_paid, 0)) AS total_salary_wages_paid
            FROM swt_fraud_justification pr
            WHERE {_period_filter_sql("pr.tax_period_year", "pr.tax_period_month")}
        """)

        payload = _cached_json(
            "summary_cards",
            date_params,
            900,
            lambda: (
                lambda row: {
                    "period_range": f"{start_month:02d}-{start_year} to {end_month:02d}-{end_year}",
                    "total_employers": row.total_employers or 0,
                    "employees_on_payroll": row.employees_on_payroll or 0,
                    "employees_paid_swt": row.employees_paid_swt or 0,
                    "total_swt_tax_deducted": row.total_swt_tax_deducted or 0,
                    "total_salary_wages_paid": row.total_salary_wages_paid or 0,
                    "effective_rate": round(
                        ((row.total_swt_tax_deducted or 0) / (row.total_salary_wages_paid or 0)),
                        4,
                    ) if (row.total_salary_wages_paid or 0) else 0,
                }
            )(db.session.execute(query, date_params).fetchone())
        )

        return jsonify(payload)
    except Exception as e:
        print("[SWT DASHBOARD ERROR]", str(e))
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        _log_timing("swt_summary_cards", started_at)


# ============================================================
# B) SWT vs Salary (Dual Line Graph)
# ============================================================
@bp.get("/swt-vs-salary")
@jwt_required()
def swt_vs_salary():
    started_at = time.time()
    try:
        date_params = _get_period_bounds()
        requested_tin = (request.args.get("tin") or "").strip()

        tin_query = text(f"""
            SELECT
                pr.tin AS tin,
                COUNT(*) AS record_count,
                MAX(pr.tax_period_year) AS latest_year,
                MAX(pr.tax_period_month) AS latest_month
            FROM swt_fraud_justification pr
            WHERE {_period_filter_sql("pr.tax_period_year", "pr.tax_period_month")}
              AND pr.tin IS NOT NULL
              AND pr.tin <> ''
              AND pr.tax_period_year IS NOT NULL
              AND pr.tax_period_month IS NOT NULL
              AND pr.total_salary_wages_paid !=0
              AND pr.total_swt_tax_deducted !=0
            GROUP BY pr.tin
            ORDER BY record_count DESC, latest_year DESC, latest_month DESC, tin DESC
        """)

        tin_rows = db.session.execute(tin_query, date_params).fetchall()
        available_tins = [
            {
                "tin": str(row.tin).strip(),
                "label": str(row.tin).strip(),
            }
            for row in tin_rows
            if row.tin is not None and str(row.tin).strip()
        ]

        selected_tin = None
        available_tin_values = {item["tin"] for item in available_tins}

        if requested_tin and requested_tin in available_tin_values:
            selected_tin = requested_tin
        elif available_tins:
            selected_tin = available_tins[0]["tin"]

        if not selected_tin:
            return jsonify({
                "selected_tin": None,
                "available_tins": [],
                "chart_data": [],
                "categories": [],
                "series": [
                    {"name": "SWT Deducted", "data": []},
                    {"name": "Total Salary Wages Paid", "data": []}
                ]
            })

        chart_params = {**date_params, "selected_tin": selected_tin}
        chart_query = text(f"""
            SELECT
                pr.tax_period_year,
                pr.tax_period_month,
                SUM(COALESCE(pr.total_salary_wages_paid, 0)) AS salary_wages_paid,
                SUM(COALESCE(pr.total_swt_tax_deducted, 0)) AS swt_paid
            FROM swt_fraud_justification pr
            WHERE {_period_filter_sql("pr.tax_period_year", "pr.tax_period_month")}
              AND pr.tin IS NOT NULL
              AND pr.tin <> ''
              AND pr.tax_period_year IS NOT NULL
              AND pr.tax_period_month IS NOT NULL
              AND pr.tin = :selected_tin
            GROUP BY pr.tax_period_year, pr.tax_period_month
            ORDER BY pr.tax_period_year DESC, pr.tax_period_month DESC
        """)

        payload = _cached_json(
            "swt_vs_salary",
            date_params,
            900,
            lambda: (
                lambda rows: {
                    "selected_tin": selected_tin,
                    "available_tins": available_tins,
                    "chart_data": [
                        {
                            "period": f"{int(r.tax_period_year):04d}-{int(r.tax_period_month):02d}",
                            "salary_wages_paid": float(r.salary_wages_paid or 0),
                            "swt_paid": float(r.swt_paid or 0),
                        }
                        for r in rows
                        if r.tax_period_year is not None and r.tax_period_month is not None
                    ],
                    "categories": [
                        f"{int(r.tax_period_year):04d}-{int(r.tax_period_month):02d}"
                        for r in rows
                        if r.tax_period_year is not None and r.tax_period_month is not None
                    ],
                    "series": [
                        {
                            "name": "SWT Deducted",
                            "data": [
                                float(r.swt_paid or 0)
                                for r in rows
                                if r.tax_period_year is not None and r.tax_period_month is not None
                            ],
                        },
                        {
                            "name": "Total Salary Wages Paid",
                            "data": [
                                float(r.salary_wages_paid or 0)
                                for r in rows
                                if r.tax_period_year is not None and r.tax_period_month is not None
                            ],
                        }
                    ],
                }
            )(db.session.execute(chart_query, chart_params).fetchall()),
            extra=selected_tin or "all",
        )

        return jsonify(payload)
    except Exception as e:
        print("[SWT DASHBOARD ERROR]", str(e))
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        _log_timing("swt_vs_salary", started_at)


# ============================================================
# C) SWT Salary Eligibility FIXED
# ============================================================
@bp.get("/swt-salary-eligibility")
@jwt_required()
def swt_salary_eligibility():
    try:
        date_filter, date_params = _get_period_filter(column_year="pr.tax_period_year", column_month="pr.tax_period_month")

        query = text(f"""
            SELECT 
                pr.tax_period_year AS tax_year,
                pr.tax_period_month AS tax_month,
                SUM(COALESCE(pr.total_salary_wages_paid, 0)) AS sw_eligible_salary,
                SUM(COALESCE(pr.total_swt_tax_deducted, 0)) AS swt_tax
            FROM swt_fraud_justification pr
            WHERE ({date_filter})
            GROUP BY pr.tax_period_year, pr.tax_period_month
            ORDER BY pr.tax_period_year, pr.tax_period_month
        """)

        rows = db.session.execute(query, date_params).fetchall()

        categories, sw_salary, sw_tax = [], [], []

        for r in rows:
            label = f"{int(r.tax_month):02d}-{int(r.tax_year)}"
            categories.append(label)
            sw_salary.append(float(r.sw_eligible_salary or 0))
            sw_tax.append(float(r.swt_tax or 0))

        return jsonify({
            "categories": categories,
            "series": [
                {"name": "SWT Eligible Salary", "data": sw_salary},
                {"name": "SWT Deducted", "data": sw_tax}
            ]
        })

    except Exception as e:
        # ✅ Show the exact DB error message
        print("[SWT DASHBOARD ERROR]", str(e))
        return jsonify({"error": str(e)}), 500

# ============================================================
# D) Segmentation Distribution (Pie Chart)
# ============================================================
@bp.get("/segmentation-distribution")
@jwt_required()
def segmentation_distribution():
    started_at = time.time()
    query = None
    date_params = None
    try:
        date_params = _get_period_bounds()
        query = text(f"""
            SELECT
                COALESCE(sm.segmentation, 'Unknown') AS segmentation,
                COUNT(*) AS total
            FROM (
                SELECT DISTINCT
                    CAST(pr.tin AS CHAR(50) CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci AS tin
                FROM swt_fraud_justification pr
                WHERE {_period_filter_sql("pr.tax_period_year", "pr.tax_period_month")}
            ) pr
            LEFT JOIN taxpayer_segmentation_master sm
                ON pr.tin = CONVERT(sm.tin USING utf8mb4) COLLATE utf8mb4_unicode_ci
            GROUP BY COALESCE(sm.segmentation, 'Unknown')
        """)

        payload = _cached_json(
            "segmentation_distribution",
            date_params,
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
    except Exception as exc:
        current_app.logger.exception(
            "segmentation_distribution failed; original_exception=%r; sqlalchemy_exception=%r; sql=%s; params=%s",
            getattr(exc, "orig", exc),
            exc,
            query.text if query is not None else None,
            date_params,
        )
        raise
    finally:
        _log_timing("segmentation_distribution", started_at)


@bp.get("/latest-records")
@jwt_required()
def latest_swt_records():
    started_at = time.time()
    query = None
    date_params = None
    try:
        date_params = _get_period_bounds()
        query = text(f"""
            SELECT 
                p.tin,
                p.taxpayer_name,
                COALESCE(sm.segmentation, 'Unknown') AS segmentation,
                p.tax_period_month,
                p.tax_period_year,
                COALESCE(p.total_salary_wages_paid, 0) AS total_salary_wages_paid,
                COALESCE(p.total_swt_tax_deducted, 0) AS total_swt_tax_deducted,
                COALESCE(p.employees_on_payroll, 0) AS employees_on_payroll,
                COALESCE(p.employees_paid_swt, 0) AS employees_paid_swt,
                p.uploaded_at AS created_at
            FROM swt_fraud_justification p
            LEFT JOIN taxpayer_segmentation_master sm
                ON CAST(p.tin AS CHAR(50) CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci =
                   CONVERT(sm.tin USING utf8mb4) COLLATE utf8mb4_unicode_ci
            WHERE {_period_filter_sql("p.tax_period_year", "p.tax_period_month")}
            ORDER BY p.uploaded_at DESC
            LIMIT 20
        """)

        def build_payload():
            rows = db.session.execute(query, date_params).fetchall()
            data = [
                {
                    "tin": r.tin,
                    "taxpayer_name": r.taxpayer_name,
                    "segmentation": _normalize_unknown_label(r.segmentation, ""),
                    "period": f"{r.tax_period_month}-{r.tax_period_year}",
                    "salary": float(r.total_salary_wages_paid or 0),
                    "swt_tax": float(r.total_swt_tax_deducted or 0),
                    "employees_on_payroll": int(r.employees_on_payroll or 0),
                    "employees_paid_swt": int(r.employees_paid_swt or 0),
                    "created_at": str(r.created_at),
                }
                for r in rows
            ]

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = "outputs"
            os.makedirs(output_dir, exist_ok=True)
            file_path = f"{output_dir}/latest_swt_records_{timestamp}.xlsx"
            pd.DataFrame(data).to_excel(file_path, index=False)

            return {
                "status": "success",
                "total_records": len(data),
                "excel_download": file_path.replace("\\", "/"),
                "records": data,
            }

        payload = _cached_json(
            "latest_records",
            date_params,
            900,
            build_payload,
        )
        return jsonify(payload)
    except Exception as exc:
        current_app.logger.exception(
            "latest_swt_records failed; original_exception=%r; sqlalchemy_exception=%r; sql=%s; params=%s",
            getattr(exc, "orig", exc),
            exc,
            query.text if query is not None else None,
            date_params,
        )
        raise
    finally:
        _log_timing("latest_swt_records", started_at)
    
# ============================================================
# F) SWT Heatmap (SWT Deducted vs SWT Eligible Salary)
# ============================================================
@bp.get("/swt-heatmap")
@jwt_required()
def swt_heatmap():
    date_filter, date_params = _get_period_filter(column_year="pr.tax_period_year", column_month="pr.tax_period_month")

    query = text(f"""
        SELECT 
            pr.tax_period_year AS tax_year,
            pr.tax_period_month AS tax_month,
            SUM(COALESCE(pr.sw_paid_for_swt_deduction, 0)) AS sw_eligible_salary,
            SUM(COALESCE(pr.total_swt_tax_deducted, 0)) AS swt_tax
        FROM swt_fraud_justification pr
        WHERE ({date_filter})
        GROUP BY pr.tax_period_year, pr.tax_period_month
        ORDER BY pr.tax_period_year, pr.tax_period_month
    """)

    rows = db.session.execute(query, date_params).fetchall()

    categories = []
    swt_salary_heat = []
    swt_tax_heat = []

    for r in rows:
        period = f"{int(r.tax_month):02d}-{int(r.tax_year)}"
        categories.append(period)

        swt_salary_heat.append({"x": period, "y": float(r.sw_eligible_salary or 0)})
        swt_tax_heat.append({"x": period, "y": float(r.swt_tax or 0)})

    return jsonify({
        "categories": categories,
        "series": [
            {"name": "SWT Eligible Salary (Kina)", "data": swt_salary_heat},
            {"name": "SWT Tax Deducted (Kina)", "data": swt_tax_heat}
        ]
    })
    
# ============================================================
# F) Fraud / Red-Flag Cases (Monthly)  — uses ONLY predicted_swt_records
# ============================================================
@bp.get("/fraud-monthly")
@jwt_required()
def fraud_monthly():
    started_at = time.time()
    try:
        date_params = _get_period_bounds()

        # Count monthly frauds using year/month columns (no date casts, MySQL-safe)
        query = text(f"""
            SELECT
                tax_period_year  AS yr,
                tax_period_month AS mn,
                COUNT(*)         AS fraud_cases
            FROM swt_fraud_justification
            WHERE predicted_fraud = 'Fraud'
              AND {_period_filter_sql("tax_period_year", "tax_period_month")}
            GROUP BY tax_period_year, tax_period_month
            ORDER BY tax_period_year, tax_period_month
        """)

        payload = _cached_json(
            "fraud_monthly",
            date_params,
            900,
            lambda: (
                lambda rows: {
                    "categories": [f"{int(r.mn):02d}-{int(r.yr)}" for r in rows],
                    "series": [
                        {
                            "name": "Fraud / Red-Flag Cases",
                            "data": [int(r.fraud_cases or 0) for r in rows],
                        }
                    ],
                }
            )(db.session.execute(query, date_params).fetchall())
        )
        return jsonify(payload)
    except Exception as e:
        print("[SWT DASHBOARD ERROR]", str(e))
        return jsonify({"error": str(e)}), 500
    finally:
        _log_timing("fraud_monthly", started_at)

## ============================================================
# F) Fraud Province Distribution (SWT) - FIXED
# ============================================================
@bp.get("/fraud-province-distribution-swt")
@jwt_required()
def fraud_province_distribution_swt():
    started_at = time.time()
    try:
        params = _get_period_bounds()
        try:
            _warn_missing_dashboard_indexes()
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

        start_year = params["start_year"]
        start_month = params["start_month"]
        end_year = params["end_year"]
        end_month = params["end_month"]

        province_sql = text(f"""
            SELECT
                lookup.province AS province,
                COUNT(DISTINCT pr.tin) AS total_tins,
                COUNT(DISTINCT CASE
                    WHEN predicted_fraud = 'Fraud' THEN pr.tin
                END) AS fraud_tins
            FROM swt_fraud_justification pr
            INNER JOIN tin_province_lookup lookup
                ON pr.tin = lookup.tin
            WHERE {_period_filter_sql("pr.tax_period_year", "pr.tax_period_month")}
              AND pr.tin IS NOT NULL
              AND pr.tin <> ''
            GROUP BY lookup.province
        """)

        payload = _cached_json(
            "fraud_province_distribution_swt",
            params,
            1800,
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
        print("[SWT DASHBOARD ERROR]", str(e))
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        _log_timing("fraud_province_distribution_swt", started_at)


@download_bp.get("/salary-vs-swt")
@jwt_required()
def download_salary_vs_swt():
    date_filter, date_params = _get_period_filter(column_year="pr.tax_period_year", column_month="pr.tax_period_month")
    query = text(f"""
        SELECT 
            pr.tin AS tin,
            pr.taxpayer_name AS taxpayer_name,
            pr.tax_period_year,
            pr.tax_period_month,
            SUM(COALESCE(pr.total_swt_tax_deducted, 0)) AS swt_tax,
            SUM(COALESCE(pr.total_salary_wages_paid, 0)) AS salary
        FROM swt_fraud_justification pr
        WHERE ({date_filter})
        GROUP BY pr.tin, pr.taxpayer_name, pr.tax_period_year, pr.tax_period_month
        ORDER BY pr.tax_period_year, pr.tax_period_month, pr.tin
    """)

    rows = db.session.execute(query, date_params).fetchall()

    data = [{
        "tin": r.tin or "",
        "taxpayer_name": r.taxpayer_name or None,
        "month": f"{int(r.tax_period_month):02d}-{int(r.tax_period_year)}",
        "swt_deducted": float(r.swt_tax or 0),
        "salary_wages_paid": float(r.salary or 0),
    } for r in rows]

    _debug_csv_sample("swt-salary-vs-swt", data)
    allowed = ["tin", "taxpayer_name", "month", "swt_deducted", "salary_wages_paid"]
    columns = _parse_columns(["month", "swt_deducted", "salary_wages_paid"], allowed, include_ids=True)
    return _build_csv_response(data, "salary-vs-swt.csv", columns)


@download_bp.get("/fraud-monthly")
@jwt_required()
def download_fraud_monthly():
    date_filter, date_params = _get_period_filter(column_year="tax_period_year", column_month="tax_period_month")
    query = text(f"""
        SELECT
            pr.tin AS tin,
            pr.taxpayer_name AS taxpayer_name,
            tax_period_year  AS yr,
            tax_period_month AS mn,
            COUNT(*)         AS fraud_cases
        FROM swt_fraud_justification pr
        WHERE predicted_fraud = 'Fraud'
          AND ({date_filter})
        GROUP BY pr.tin, pr.taxpayer_name, tax_period_year, tax_period_month
        ORDER BY tax_period_year, tax_period_month, pr.tin
    """)

    rows = db.session.execute(query, date_params).fetchall()

    data = [{
        "tin": r.tin or "",
        "taxpayer_name": r.taxpayer_name or None,
        "month": f"{int(r.mn):02d}-{int(r.yr)}",
        "fraud_cases": int(r.fraud_cases or 0),
    } for r in rows]

    _debug_csv_sample("swt-fraud-monthly", data)
    allowed = ["tin", "taxpayer_name", "month", "fraud_cases"]
    columns = _parse_columns(["month", "fraud_cases"], allowed, include_ids=True)
    return _build_csv_response(data, "fraud-monthly.csv", columns)


@download_bp.get("/segmentation")
@jwt_required()
def download_segmentation():
    date_filter, date_params = _get_period_filter(column_year="pr.tax_period_year", column_month="pr.tax_period_month")
    query = text(f"""
        SELECT
            pr.tin AS tin,
            COALESCE(NULLIF(TRIM(sm.taxpayer_name), ''), pr.taxpayer_name, 'Unknown') AS taxpayer_name,
            COALESCE(sm.segmentation, 'Unknown') AS segmentation
        FROM (
            SELECT
                CAST(pr.tin AS CHAR(50) CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci AS tin,
                MAX(NULLIF(TRIM(pr.taxpayer_name), '')) AS taxpayer_name
            FROM swt_fraud_justification pr
            WHERE ({date_filter})
            GROUP BY CAST(pr.tin AS CHAR(50) CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci
        ) pr
        LEFT JOIN taxpayer_segmentation_master sm
            ON pr.tin = CONVERT(sm.tin USING utf8mb4) COLLATE utf8mb4_unicode_ci
        ORDER BY pr.tin
    """)

    rows = db.session.execute(query, date_params).fetchall()

    data = [{
        "tin": r.tin or "",
        "taxpayer_name": r.taxpayer_name or None,
        "segmentation": r.segmentation or None,
    } for r in rows]

    _debug_csv_sample("swt-segmentation", data)
    allowed = ["tin", "taxpayer_name", "segmentation"]
    columns = _parse_columns(["segmentation"], allowed, include_ids=True)
    return _build_csv_response(data, "segmentation.csv", columns)


@download_bp.get("/province")
@jwt_required()
def download_province():
    params = _get_period_bounds()

    sql = text(f"""
        SELECT
            pr.tin,
            MAX(pr.taxpayer_name) AS taxpayer_name,
            COALESCE(lookup.province, 'UNKNOWN') AS province,
            MAX(pr.predicted_fraud) AS predicted_fraud,
            MAX(pr.explanation) AS explanation
        FROM swt_fraud_justification pr
        INNER JOIN tin_province_lookup lookup
            ON lookup.tin = pr.tin
        WHERE {_period_filter_sql("pr.tax_period_year", "pr.tax_period_month")}
        GROUP BY
            pr.tin,
            COALESCE(lookup.province, 'UNKNOWN')
        ORDER BY
            COALESCE(lookup.province, 'UNKNOWN'),
            taxpayer_name
    """)

    rows = iter(_stream_mappings(sql, params))

    def build_row(row):
        return {
            "tin": row["tin"],
            "taxpayer_name": row["taxpayer_name"],
            "province": row["province"],
            "predicted_fraud": row["predicted_fraud"] or "",
            "explanation": row["explanation"] or "",
        }

    sample = []
    for _ in range(5):
        try:
            sample.append(build_row(next(rows)))
        except StopIteration:
            break

    data = chain(sample, (build_row(row) for row in rows))
    columns = [
        "tin",
        "taxpayer_name",
        "province",
        "predicted_fraud",
        "explanation",
    ]

    _debug_csv_sample("swt-province", sample)
    return _build_csv_response(data, "province.csv", columns)




