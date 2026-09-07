from datetime import datetime
import uuid
import csv
import time
import traceback
from io import StringIO
import threading
import os
import socket
from flask import Blueprint, Response, current_app, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy import text
from ..extensions import db
from .multi_tax_routes import refresh_multi_tax_tables
from utils.auth_helper import get_authenticated_user_id

bp = Blueprint("dashboard_common", __name__, url_prefix="/api/common-dashboard")
download_bp = Blueprint("dashboard_common_download", __name__, url_prefix="/api/common/download-csv")
CSV_HEADERS = ["tin", "taxpayer_name", "year", "income", "profit", "tax", "sector", "taxpayers_count", "fraud_flag", "fraud_year", "risk_category", "province"]
CSV_HEADER_LABELS = {"tin": "TIN", "taxpayer_name": "Taxpayer Name", "year": "Year", "income": "Income", "profit": "Profit", "tax": "Tax", "sector": "Sector", "taxpayers": "Taxpayers", "risk_flag": "Risk Flag", "exposure": "Exposure", "fraud_cases": "Fraud Count", "tax_period_year": "Year", "total_income": "Income", "cit_tax": "Tax", "gst_diff": "GST Diff", "swt_diff": "SWT Diff", "predicted_fraud": "Fraud", "sector_activity": "Sector"}
COMMON_DASHBOARD_COLLATION = "utf8mb4_unicode_ci"
TIN_JOIN_COLLATION = "utf8mb4_general_ci"
SUMMARY_TABLE = "multitax_dashboard_summary"
SUMMARY_TMP_TABLE = "multitax_dashboard_summary_tmp"
SUMMARY_OLD_TABLE = "multitax_dashboard_summary_old"
SUMMARY_STATUS_TABLE = "multitax_dashboard_summary_status"
SUMMARY_REBUILD_LOCK_NAME = "multitax_dashboard_summary_rebuild_lock"
SUMMARY_REQUIRED_INDEXES = {
    "uq_multitax_dashboard_summary_tin_year": (True, ["tin", "tax_period_year"]),
    "idx_multitax_dashboard_summary_year": (False, ["tax_period_year"]),
    "idx_multitax_dashboard_summary_tin": (False, ["tin"]),
    "idx_multitax_dashboard_summary_sector": (False, ["sector_activity"]),
    "idx_multitax_dashboard_summary_predicted_fraud": (False, ["predicted_fraud"]),
    "idx_multitax_dashboard_summary_year_tin": (False, ["tax_period_year", "tin"]),
}
SUMMARY_OBSOLETE_INDEX_NAMES = {"uq_summ_uty", "idx_summ_uy", "idx_summ_ut", "idx_summ_us", "idx_summ_upf", "idx_summ_uyt", "uq_summ_ty", "idx_summ_y", "idx_summ_t", "idx_summ_s", "idx_summ_pf", "idx_summ_yt"}

def _table_exists(conn, table_name):
    return bool(conn.execute(text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = :table_name"), {"table_name": table_name}).scalar())

def _table_columns(conn, table_name):
    rows = conn.execute(text("SELECT COLUMN_NAME FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = :table_name"), {"table_name": table_name}).fetchall()
    return {row[0] for row in rows}

def _summary_table_ddl(table_name):
    # MySQL identifiers are capped at 64 chars, so temp rebuild tables need short index names.
    return f"CREATE TABLE IF NOT EXISTS {table_name} (id BIGINT NOT NULL AUTO_INCREMENT, tin VARCHAR(64) NOT NULL, taxpayer_name VARCHAR(255) NULL, taxpayer_type VARCHAR(100) NULL, tax_period_year INT NOT NULL, sector_activity VARCHAR(255) NULL, enterprise_activity VARCHAR(255) NULL, total_income DECIMAL(24,2) NOT NULL DEFAULT 0, profit DECIMAL(24,2) NOT NULL DEFAULT 0, cit_tax DECIMAL(24,2) NOT NULL DEFAULT 0, gst_sales DECIMAL(24,2) NOT NULL DEFAULT 0, salary_wages DECIMAL(24,2) NOT NULL DEFAULT 0, gst_sales_diff_abs DECIMAL(24,2) NOT NULL DEFAULT 0, swt_salary_diff_abs DECIMAL(24,2) NOT NULL DEFAULT 0, predicted_fraud VARCHAR(50) NOT NULL DEFAULT 'Non-Risk Flagged', fraud_flag TINYINT(1) NOT NULL DEFAULT 0, multi_tax_issue VARCHAR(255) NULL, province VARCHAR(255) NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (id), UNIQUE KEY uq_multitax_dashboard_summary_tin_year (tin, tax_period_year), KEY idx_multitax_dashboard_summary_year (tax_period_year), KEY idx_multitax_dashboard_summary_tin (tin), KEY idx_multitax_dashboard_summary_sector (sector_activity), KEY idx_multitax_dashboard_summary_predicted_fraud (predicted_fraud), KEY idx_multitax_dashboard_summary_year_tin (tax_period_year, tin)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"

def _table_index_columns(conn, table_name):
    rows = conn.execute(text("SELECT index_name, non_unique, seq_in_index, column_name FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = :table_name ORDER BY index_name, seq_in_index"), {"table_name": table_name}).fetchall()
    indexes = {}
    for index_name, non_unique, seq_in_index, column_name in rows:
        info = indexes.setdefault(index_name, {"non_unique": int(non_unique), "columns": []})
        info["columns"].append(column_name)
    return indexes

def _drop_summary_legacy_user_schema(conn, table_name=SUMMARY_TABLE):
    if not _table_exists(conn, table_name):
        return
    columns = _table_columns(conn, table_name)
    existing_indexes = _table_index_columns(conn, table_name)
    obsolete_indexes = [
        index_name
        for index_name, info in existing_indexes.items()
        if index_name != "PRIMARY" and (
            index_name in SUMMARY_OBSOLETE_INDEX_NAMES or "user_id" in info.get("columns", [])
        )
    ]
    for index_name in obsolete_indexes:
        conn.execute(text(f"ALTER TABLE {table_name} DROP INDEX {index_name}"))
    if "user_id" in columns:
        conn.execute(text(f"ALTER TABLE {table_name} DROP COLUMN user_id"))


def _ensure_summary_indexes(conn, table_name=SUMMARY_TABLE):
    existing = _table_index_columns(conn, table_name)
    for index_name, (is_unique, columns) in SUMMARY_REQUIRED_INDEXES.items():
        index_info = existing.get(index_name)
        if index_info and index_info.get("columns") == columns and bool(1 - index_info.get("non_unique", 1)) == is_unique:
            continue
        if index_info:
            conn.execute(text(f"ALTER TABLE {table_name} DROP INDEX {index_name}"))
        uniqueness = "UNIQUE " if is_unique else ""
        conn.execute(text(f"ALTER TABLE {table_name} ADD {uniqueness}INDEX {index_name} ({', '.join(columns)})"))

def _summary_status_table_ddl():
    return f"CREATE TABLE IF NOT EXISTS {SUMMARY_STATUS_TABLE} (id TINYINT NOT NULL PRIMARY KEY, job_id VARCHAR(36) NULL, status VARCHAR(20) NOT NULL DEFAULT 'idle', progress INT NOT NULL DEFAULT 0, current_step VARCHAR(255) NULL, last_updated DATETIME NULL, started_at DATETIME NULL, completed_at DATETIME NULL, error_message LONGTEXT NULL, last_sql LONGTEXT NULL, last_traceback LONGTEXT NULL, source_rows BIGINT NULL, temp_rows BIGINT NULL, live_rows BIGINT NULL, elapsed_ms BIGINT NULL, tmp_table_name VARCHAR(255) NULL, worker_running TINYINT(1) NOT NULL DEFAULT 0, updated_at DATETIME NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"

def _ensure_summary_status_columns(conn):
    columns = _table_columns(conn, SUMMARY_STATUS_TABLE) if _table_exists(conn, SUMMARY_STATUS_TABLE) else set()
    required_columns = {
        # Idempotent compatibility migration for deployed status tables that
        # predate job_id.  It never drops/recreates the table or status row.
        "job_id": "ALTER TABLE {table} ADD COLUMN job_id VARCHAR(36) NULL",
        "last_sql": "ALTER TABLE {table} ADD COLUMN last_sql LONGTEXT NULL",
        "last_traceback": "ALTER TABLE {table} ADD COLUMN last_traceback LONGTEXT NULL",
        "source_rows": "ALTER TABLE {table} ADD COLUMN source_rows BIGINT NULL",
        "temp_rows": "ALTER TABLE {table} ADD COLUMN temp_rows BIGINT NULL",
        "live_rows": "ALTER TABLE {table} ADD COLUMN live_rows BIGINT NULL",
        "elapsed_ms": "ALTER TABLE {table} ADD COLUMN elapsed_ms BIGINT NULL",
        "tmp_table_name": "ALTER TABLE {table} ADD COLUMN tmp_table_name VARCHAR(255) NULL",
        "worker_running": "ALTER TABLE {table} ADD COLUMN worker_running TINYINT(1) NOT NULL DEFAULT 0",
    }
    for column_name, ddl in required_columns.items():
        if column_name not in columns:
            conn.execute(text(ddl.format(table=SUMMARY_STATUS_TABLE)))

def _ensure_summary_status_schema(conn):
    conn.execute(text(_summary_status_table_ddl()))
    _ensure_summary_status_columns(conn)

def _ensure_summary_schema(conn):
    conn.execute(text(_summary_table_ddl(SUMMARY_TABLE)))
    _drop_summary_legacy_user_schema(conn, SUMMARY_TABLE)
    _ensure_summary_indexes(conn, SUMMARY_TABLE)
    _ensure_summary_status_schema(conn)

def _ensure_summary_status_row(conn):
    conn.execute(text(f"INSERT INTO {SUMMARY_STATUS_TABLE} (id, status, progress, current_step, last_updated, started_at, completed_at, error_message, updated_at) VALUES (1, 'idle', 0, NULL, NULL, NULL, NULL, NULL, NOW()) ON DUPLICATE KEY UPDATE id = id"))

def _ensure_summary_status_objects(conn):
    _ensure_summary_status_schema(conn)
    _ensure_summary_status_row(conn)

def _ensure_summary_objects(conn):
    _ensure_summary_schema(conn)
    _ensure_summary_status_row(conn)

def _acquire_named_lock(conn, lock_name, timeout_seconds=0):
    result = conn.execute(text("SELECT GET_LOCK(:lock_name, :timeout_seconds)"), {"lock_name": lock_name, "timeout_seconds": int(timeout_seconds)}).scalar()
    if result is None:
        raise RuntimeError("Unable to acquire dashboard rebuild lock.")
    return str(result) == "1"

def _release_named_lock(conn, lock_name):
    try:
        released = conn.execute(text("SELECT RELEASE_LOCK(:lock_name)"), {"lock_name": lock_name}).scalar()
        if str(released) != "1":
            conn.invalidate()
    except Exception:
        # Never return a possibly lock-owning session to the connection pool.
        conn.invalidate()

def _get_summary_status_row(conn):
    return conn.execute(text(f"SELECT * FROM {SUMMARY_STATUS_TABLE} WHERE id = 1 LIMIT 1")).mappings().first()

def _assert_summary_lock(conn):
    owned = conn.execute(text("SELECT IS_USED_LOCK(:name) = CONNECTION_ID()"), {"name": SUMMARY_REBUILD_LOCK_NAME}).scalar()
    if str(owned) != "1":
        raise RuntimeError("Dashboard refresh lost its database lock; stopping this worker.")


def _update_summary_status(conn, **fields):
    if not fields:
        return
    tracked_fields = [
        "job_id",
        "status",
        "progress",
        "current_step",
        "last_updated",
        "started_at",
        "completed_at",
        "error_message",
        "last_sql",
        "last_traceback",
        "source_rows",
        "temp_rows",
        "live_rows",
        "elapsed_ms",
        "tmp_table_name",
        "worker_running",
    ]
    if set(fields) - set(tracked_fields):
        raise ValueError("Unknown dashboard status field")
    missing_columns = set(fields) - _table_columns(conn, SUMMARY_STATUS_TABLE)
    if missing_columns:
        raise RuntimeError(
            "Dashboard status schema is missing required column(s): "
            + ", ".join(sorted(missing_columns))
        )
    _assert_summary_lock(conn)
    if not _get_summary_status_row(conn):
        raise RuntimeError("Dashboard summary status row is missing; initialization is required.")
    assignments = ", ".join(f"{key} = :{key}" for key in fields)
    conn.execute(text(f"UPDATE {SUMMARY_STATUS_TABLE} SET {assignments}, updated_at = NOW() WHERE id = 1"), fields)
    conn.commit()

def _format_status_datetime(value):
    if value is None:
        return None
    return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else str(value)

def _log_rebuild_step(message, **details):
    detail_str = ", ".join(f"{key}={value!r}" for key, value in details.items() if value is not None)
    if detail_str:
        current_app.logger.info("Common dashboard rebuild: %s | %s", message, detail_str)
    else:
        current_app.logger.info("Common dashboard rebuild: %s", message)

def _status_debug_snapshot(conn):
    row = _get_summary_status_row(conn) or {}
    return {
        "status": row.get("status"),
        "progress": int(row.get("progress") or 0),
        "current_step": row.get("current_step"),
        "last_updated": _format_status_datetime(row.get("last_updated") or row.get("completed_at")),
        "last_error": row.get("error_message"),
        "last_sql": row.get("last_sql"),
        "source_rows": int(row.get("source_rows") or 0),
        "temp_rows": int(row.get("temp_rows") or 0),
        "live_rows": int(row.get("live_rows") or 0),
        "elapsed_ms": int(row.get("elapsed_ms") or 0),
        "tmp_table_name": row.get("tmp_table_name"),
        "worker_running": bool(row.get("worker_running")),
        "last_traceback": row.get("last_traceback"),
    }

def _summary_status_payload():
    # Polling is read-only. A different Gunicorn worker must never alter the
    # status of the connection that owns the rebuild lock.
    with db.engine.begin() as conn:
        row = _get_summary_status_row(conn) or {}
        summary_last_updated = row.get("last_updated")
    status = str(row.get("status") or "idle").lower()
    if status in {"queued", "running"}:
        return {"job_id": row.get("job_id"), "status": status, "progress": int(row.get("progress") or 0), "current_step": row.get("current_step") or "Refreshing dashboard summary", "started_at": _format_status_datetime(row.get("started_at")), "last_updated": _format_status_datetime(row.get("last_updated")), "completed_at": None, "rows_saved": int(row.get("live_rows") or 0)}
    if status == "failed":
        return {"job_id": row.get("job_id"), "status": "failed", "progress": int(row.get("progress") or 0), "current_step": row.get("current_step") or "Failed", "error": row.get("error_message") or "Dashboard summary refresh failed.", "error_message": row.get("error_message"), "started_at": _format_status_datetime(row.get("started_at")), "last_updated": _format_status_datetime(summary_last_updated or row.get("last_updated")), "completed_at": _format_status_datetime(row.get("completed_at")), "rows_saved": int(row.get("live_rows") or 0)}
    last_updated = summary_last_updated or row.get("last_updated") or row.get("completed_at")
    return {"job_id": row.get("job_id"), "status": "completed", "last_updated": _format_status_datetime(last_updated), "started_at": _format_status_datetime(row.get("started_at")), "completed_at": _format_status_datetime(row.get("completed_at")), "progress": 100, "current_step": "Completed", "rows_saved": int(row.get("live_rows") or 0)} if last_updated else {"job_id": None, "status": "idle", "progress": 0, "current_step": "Not built yet", "last_updated": None, "started_at": None, "completed_at": None, "rows_saved": 0}

def _ensure_summary_ready():
    with db.engine.begin() as conn:
        _ensure_summary_schema(conn)
        _ensure_summary_status_row(conn)

def get_date_filter(column_year="tax_period_year"):
    start_year, end_year = get_date_range()
    if start_year is None or end_year is None:
        return "1=1", {}
    if start_year > end_year:
        start_year, end_year = end_year, start_year
    if start_year == end_year:
        return f"{column_year} = :year", {"year": start_year}
    return f"{column_year} BETWEEN :start_year AND :end_year", {"start_year": start_year, "end_year": end_year}

def get_date_range():
    now = datetime.now()
    range_type = request.args.get("range_type", "1y")
    start_date = request.args.get("start_date") or request.args.get("from_date")
    end_date = request.args.get("end_date") or request.args.get("to_date")
    def _parse_date(value):
        if not value:
            return None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None
    if range_type == "all":
        return None, None
    if range_type == "custom":
        start, end = _parse_date(start_date), _parse_date(end_date)
        if start and end:
            sy, ey = int(start.year), int(end.year)
            return (ey, sy) if sy > ey else (sy, ey)
        try:
            sy, ey = int(request.args.get("start_year")), int(request.args.get("end_year"))
            return (ey, sy) if sy > ey else (sy, ey)
        except (TypeError, ValueError):
            return int(now.year), int(now.year)
    current_year = int(now.year)
    if range_type in {"1m", "3m", "6m", "1y"}:
        return current_year, current_year
    if range_type == "3y":
        return current_year - 2, current_year
    if range_type == "5y":
        return current_year - 4, current_year
    if range_type == "10y":
        return current_year - 9, current_year
    return current_year, current_year

def _get_dashboard_tin():
    tin = (request.args.get("tin") or "").strip()
    return tin or None

def _dashboard_request_metadata():
    return {"tin": _get_dashboard_tin(), "range_type": request.args.get("range_type", "1y"), "start_date": request.args.get("start_date") or request.args.get("from_date"), "end_date": request.args.get("end_date") or request.args.get("to_date")}

def _summary_scope(include_tin=False):
    _ensure_summary_ready()
    date_filter, date_params = get_date_filter("tax_period_year")
    params = dict(date_params)
    filters = [f"({date_filter})"]
    if include_tin:
        tin = _get_dashboard_tin()
        if tin:
            filters.append(f"TRIM(tin) COLLATE {TIN_JOIN_COLLATION} = :tin COLLATE {TIN_JOIN_COLLATION}")
            params["tin"] = tin
    return " AND ".join(filters), params
def _log_dashboard_query_context(endpoint_name, params):
    meta = _dashboard_request_metadata()
    current_app.logger.info("Common dashboard %s request tin=%r range_type=%s start_date=%s end_date=%s start_year=%s end_year=%s", endpoint_name, meta["tin"], meta["range_type"], meta["start_date"], meta["end_date"], params.get("year", params.get("start_year")), params.get("year", params.get("end_year")))

def _log_dashboard_zero_row_count(endpoint_name, include_tin, params):
    where_clause, count_params = _summary_scope(include_tin=include_tin)
    total_rows = db.session.execute(text(f"SELECT COUNT(*) FROM {SUMMARY_TABLE} WHERE {where_clause}"), count_params).scalar() or 0
    current_app.logger.warning("Common dashboard %s returned no rows. filtered_row_count=%s tin=%r start_year=%s end_year=%s", endpoint_name, int(total_rows), params.get("tin"), params.get("year", params.get("start_year")), params.get("year", params.get("end_year")))

def _parse_columns(default_columns, allowed_columns, include_ids=True):
    raw = request.args.get("columns")
    cols = [c.strip() for c in raw.split(",") if c.strip()] if raw else list(default_columns)
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
    writer.writerow([CSV_HEADER_LABELS.get(col, col) for col in columns])
    for row in rows:
        writer.writerow([row.get(col, "") if row.get(col, "") is not None else "" for col in columns])
    response = Response(buffer.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

def _debug_csv_sample(label, data):
    try:
        print(f"[csv-debug] {label}: {data[:5]}")
    except Exception:
        pass

def _rebuild_summary_insert_sql(conn, target_table):
    source_columns = _table_columns(conn, "multi_tax_integration_results")
    has_registration = _table_exists(conn, "tin_registration_mst")
    has_sector_lookup = _table_exists(conn, "sector_mst")
    fraud_case_expr = "CASE WHEN COALESCE(pr.cit_fraud_flag, 0) = 1 OR COALESCE(pr.gst_fraud_flag, 0) = 1 OR COALESCE(pr.swt_fraud_flag, 0) = 1 THEN 1 ELSE 0 END"
    taxpayer_type_expr = "MAX(COALESCE(NULLIF(TRIM(pr.taxpayer_type), ''), 'Unknown'))" if "taxpayer_type" in source_columns else "'Unknown'"
    enterprise_activity_expr = "MAX(NULLIF(TRIM(pr.enterprise_activity), ''))" if "enterprise_activity" in source_columns else "NULL"
    province_source_expr = "MAX(NULLIF(TRIM(pr.province), ''))" if "province" in source_columns else "NULL"
    sector_source_expr = "MAX(NULLIF(TRIM(pr.sector_activity), ''))" if "sector_activity" in source_columns else "NULL"
    multi_tax_issue_expr = "COALESCE(MAX(NULLIF(TRIM(pr.multi_tax_issue), '')), CASE WHEN SUM(COALESCE(pr.gst_vs_cit_sales_diff_abs, 0)) > 0 OR SUM(COALESCE(pr.swt_vs_cit_salary_diff_abs, 0)) > 0 THEN 'Multi Tax Mismatch' ELSE NULL END)" if "multi_tax_issue" in source_columns else "CASE WHEN SUM(COALESCE(pr.gst_vs_cit_sales_diff_abs, 0)) > 0 OR SUM(COALESCE(pr.swt_vs_cit_salary_diff_abs, 0)) > 0 THEN 'Multi Tax Mismatch' ELSE NULL END"

    registration_cte = ""
    registration_join = ""
    sector_expr = "base.sector_activity"
    province_expr = "base.province"

    if has_registration:
        registration_cte = f"""
            , registration_lookup AS (
                SELECT
                    TRIM(tr.tin) COLLATE {COMMON_DASHBOARD_COLLATION} AS tin,
                    MAX(NULLIF(TRIM(tr.province), '')) AS province,
                    {"MAX(NULLIF(TRIM(sm.sector_name), '')) AS sector_name" if has_sector_lookup else "NULL AS sector_name"}
                FROM tin_registration_mst tr
                {"LEFT JOIN sector_mst sm ON tr.sector_id = sm.new_sector_id" if has_sector_lookup else ""}
                WHERE NULLIF(TRIM(tr.tin), '') IS NOT NULL
                GROUP BY TRIM(tr.tin) COLLATE {COMMON_DASHBOARD_COLLATION}
            )
        """
        registration_join = f"""
            LEFT JOIN registration_lookup rl
                ON base.tin COLLATE {COMMON_DASHBOARD_COLLATION} = rl.tin
        """
        province_expr = "COALESCE(rl.province, base.province, 'Unknown')"
        if has_sector_lookup:
            sector_expr = "COALESCE(rl.sector_name, base.sector_activity, 'Unknown')"
        else:
            sector_expr = "COALESCE(base.sector_activity, 'Unknown')"
    else:
        sector_expr = "COALESCE(base.sector_activity, 'Unknown')"
        province_expr = "COALESCE(base.province, 'Unknown')"

    return f"""
        INSERT INTO {target_table} (
            tin, taxpayer_name, taxpayer_type, tax_period_year,
            sector_activity, enterprise_activity, total_income, profit, cit_tax,
            gst_sales, salary_wages, gst_sales_diff_abs, swt_salary_diff_abs,
            predicted_fraud, fraud_flag, multi_tax_issue, province, created_at, updated_at
        )
        WITH base_summary AS (
            SELECT
                TRIM(pr.tin) AS tin,
                MAX(COALESCE(NULLIF(TRIM(pr.taxpayer_name), ''), 'Unknown')) AS taxpayer_name,
                {taxpayer_type_expr} AS taxpayer_type,
                pr.tax_period_year,
                COALESCE({sector_source_expr}, 'Unknown') AS sector_activity,
                {enterprise_activity_expr} AS enterprise_activity,
                SUM(COALESCE(pr.cit_total_gross_income, 0)) AS total_income,
                0 AS profit,
                SUM(COALESCE(pr.cit_total_tax_payable, 0)) AS cit_tax,
                SUM(COALESCE(pr.gst_total_sales_income, 0)) AS gst_sales,
                SUM(COALESCE(pr.swt_total_salary_wages_paid, 0)) AS salary_wages,
                SUM(COALESCE(pr.gst_vs_cit_sales_diff_abs, 0)) AS gst_sales_diff_abs,
                SUM(COALESCE(pr.swt_vs_cit_salary_diff_abs, 0)) AS swt_salary_diff_abs,
                CASE
                    WHEN MAX({fraud_case_expr}) = 1 THEN 'Risk Flagged'
                    ELSE 'Non-Risk Flagged'
                END AS predicted_fraud,
                MAX({fraud_case_expr}) AS fraud_flag,
                {multi_tax_issue_expr} AS multi_tax_issue,
                COALESCE({province_source_expr}, 'Unknown') AS province
            FROM multi_tax_integration_results pr
            WHERE pr.tax_period_year IS NOT NULL
              AND NULLIF(TRIM(pr.tin), '') IS NOT NULL
            GROUP BY TRIM(pr.tin), pr.tax_period_year
        )
        {registration_cte}
        SELECT
            base.tin,
            base.taxpayer_name,
            base.taxpayer_type,
            base.tax_period_year,
            {sector_expr} AS sector_activity,
            base.enterprise_activity,
            base.total_income,
            base.profit,
            base.cit_tax,
            base.gst_sales,
            base.salary_wages,
            base.gst_sales_diff_abs,
            base.swt_salary_diff_abs,
            base.predicted_fraud,
            base.fraud_flag,
            base.multi_tax_issue,
            {province_expr} AS province,
            NOW() AS created_at,
            NOW() AS updated_at
        FROM base_summary base
        {registration_join}
    """

def _run_summary_rebuild(lock_conn):
    engine = db.engine
    rebuild_token = uuid.uuid4().hex[:12]
    tmp_table_name = f"{SUMMARY_TMP_TABLE}_{rebuild_token}"
    old_table_name = f"{SUMMARY_OLD_TABLE}_{rebuild_token}"
    swap_completed = False
    generated_sql = None
    source_rows = 0
    temp_rows = 0
    live_rows = 0
    last_updated = None
    rebuild_started_at = time.perf_counter()

    _log_rebuild_step("Starting rebuild", tmp_table_name=tmp_table_name, old_table_name=old_table_name)
    _update_summary_status(lock_conn, status="running", progress=65, current_step="Rebuilding Dashboard Summary", completed_at=None, error_message=None, last_sql=None, last_traceback=None, source_rows=0, temp_rows=0, live_rows=0, elapsed_ms=0, tmp_table_name=tmp_table_name, worker_running=True)
    try:
        with engine.begin() as conn:
            _ensure_summary_schema(conn)
            _log_rebuild_step("Checking source table")
            source_rows = int(conn.execute(text("SELECT COUNT(*) FROM multi_tax_integration_results")).scalar() or 0)
            _log_rebuild_step("Source row count", source_rows=source_rows)
            if source_rows <= 0:
                raise RuntimeError("Summary rebuild failed. Source table multi_tax_integration_results has zero rows.")

            step_started_at = time.perf_counter()
            _log_rebuild_step("Creating temp table", tmp_table_name=tmp_table_name)
            conn.execute(text(f"DROP TABLE IF EXISTS {tmp_table_name}"))
            conn.execute(text(_summary_table_ddl(tmp_table_name)))
            show_create_row = conn.execute(text(f"SHOW CREATE TABLE {tmp_table_name}")).fetchone()
            _log_rebuild_step("Temp table created", elapsed_ms=int((time.perf_counter() - step_started_at) * 1000), show_create=show_create_row[1] if show_create_row and len(show_create_row) > 1 else None)
            _update_summary_status(lock_conn, status="running", progress=70, current_step="Creating temp table", source_rows=source_rows, tmp_table_name=tmp_table_name, worker_running=True)

        with engine.begin() as conn:
            _ensure_summary_schema(conn)
            _log_rebuild_step("Building INSERT SQL")
            generated_sql = _rebuild_summary_insert_sql(conn, tmp_table_name)
            _log_rebuild_step("Generated SQL", sql=generated_sql)
            _update_summary_status(lock_conn, status="running", progress=75, current_step="Executing INSERT", last_sql=generated_sql, source_rows=source_rows, tmp_table_name=tmp_table_name, worker_running=True)

            insert_started_at = time.perf_counter()
            _log_rebuild_step("Executing INSERT")
            insert_result = conn.execute(text(generated_sql))
            insert_elapsed_ms = int((time.perf_counter() - insert_started_at) * 1000)
            _log_rebuild_step("INSERT executed", elapsed_ms=insert_elapsed_ms, affected_row_count=getattr(insert_result, "rowcount", None))
            temp_rows = int(conn.execute(text(f"SELECT COUNT(*) FROM {tmp_table_name}")).scalar() or 0)
            _log_rebuild_step("Inserted temp rows", inserted_rows=temp_rows)
            if temp_rows <= 0:
                raise RuntimeError("Summary rebuild failed. No rows inserted into temp table.")
            _update_summary_status(lock_conn, status="running", progress=85, current_step="Temp table populated", source_rows=source_rows, temp_rows=temp_rows, elapsed_ms=int((time.perf_counter() - rebuild_started_at) * 1000), last_sql=generated_sql, tmp_table_name=tmp_table_name, worker_running=True)

        with engine.begin() as conn:
            before_live_rows = int(conn.execute(text(f"SELECT COUNT(*) FROM {SUMMARY_TABLE}")).scalar() or 0)
            _log_rebuild_step("Renaming temp table", temp_rows=temp_rows, live_summary_rows_before=before_live_rows)
            _update_summary_status(lock_conn, status="running", progress=95, current_step="Renaming temp table", source_rows=source_rows, temp_rows=temp_rows, live_rows=before_live_rows, last_sql=generated_sql, elapsed_ms=int((time.perf_counter() - rebuild_started_at) * 1000), tmp_table_name=tmp_table_name, worker_running=True)
            conn.execute(text(f"DROP TABLE IF EXISTS {old_table_name}"))
            conn.execute(text(f"RENAME TABLE {SUMMARY_TABLE} TO {old_table_name}, {tmp_table_name} TO {SUMMARY_TABLE}"))
            swap_completed = True
            live_rows = int(conn.execute(text(f"SELECT COUNT(*) FROM {SUMMARY_TABLE}")).scalar() or 0)
            last_updated = conn.execute(text(f"SELECT MAX(updated_at) FROM {SUMMARY_TABLE}")).scalar()
            _log_rebuild_step("Rename complete", live_summary_rows=live_rows)

        with engine.begin() as conn:
            _log_rebuild_step("Dropping old table", old_table_name=old_table_name)
            conn.execute(text(f"DROP TABLE IF EXISTS {old_table_name}"))

        expected_grouped_rows = None
        source_year_counts = []
        summary_year_counts = []
        with engine.begin() as conn:
            expected_grouped_rows = int(conn.execute(text("SELECT COUNT(*) FROM (SELECT TRIM(tin), tax_period_year FROM multi_tax_integration_results WHERE tax_period_year IS NOT NULL AND NULLIF(TRIM(tin), '') IS NOT NULL GROUP BY TRIM(tin), tax_period_year) grouped_rows")).scalar() or 0)
            source_year_counts = [dict(row._mapping) for row in conn.execute(text("SELECT tax_period_year, COUNT(*) AS row_count FROM multi_tax_integration_results WHERE tax_period_year IS NOT NULL AND NULLIF(TRIM(tin), '') IS NOT NULL GROUP BY tax_period_year ORDER BY tax_period_year")).fetchall()]
            summary_year_counts = [dict(row._mapping) for row in conn.execute(text(f"SELECT tax_period_year, COUNT(*) AS row_count FROM {SUMMARY_TABLE} GROUP BY tax_period_year ORDER BY tax_period_year")).fetchall()]
        _log_rebuild_step("Completed successfully", source_rows=source_rows, temp_rows=temp_rows, live_rows=live_rows, expected_grouped_rows=expected_grouped_rows, source_year_counts=source_year_counts, summary_year_counts=summary_year_counts, elapsed_ms=int((time.perf_counter() - rebuild_started_at) * 1000))
        if expected_grouped_rows != live_rows:
            current_app.logger.warning("Common dashboard rebuild row mismatch expected_grouped_rows=%s live_rows=%s", expected_grouped_rows, live_rows)

        _update_summary_status(lock_conn, status="completed", progress=100, current_step="Completed", last_updated=last_updated or datetime.now(), completed_at=datetime.now(), error_message=None, last_sql=generated_sql, last_traceback=None, source_rows=source_rows, temp_rows=temp_rows, live_rows=live_rows, elapsed_ms=int((time.perf_counter() - rebuild_started_at) * 1000), tmp_table_name=None, worker_running=False)
    except Exception as exc:
        tb = traceback.format_exc()
        current_app.logger.exception("Common dashboard rebuild failed tmp_table_name=%s old_table_name=%s", tmp_table_name, old_table_name)
        try:
            with engine.begin() as cleanup_conn:
                if not swap_completed:
                    cleanup_conn.execute(text(f"DROP TABLE IF EXISTS {tmp_table_name}"))
                cleanup_conn.execute(text(f"DROP TABLE IF EXISTS {old_table_name}"))
        except Exception:
            current_app.logger.exception("Summary cleanup failed; preserving the original rebuild error")
        _update_summary_status(lock_conn, status="failed", progress=0, current_step="Failed", completed_at=datetime.now(), error_message=str(exc), last_sql=generated_sql, last_traceback=tb, source_rows=source_rows, temp_rows=temp_rows, live_rows=live_rows, elapsed_ms=int((time.perf_counter() - rebuild_started_at) * 1000), tmp_table_name=None, worker_running=False)
        raise


def _background_summary_rebuild_worker(app, current_user_id, admission, admitted):
    # admission is only an HTTP startup handshake, never a source of job liveness.
    with app.app_context():
        lock_conn = None
        lock_acquired = False
        integration_completed = False
        operation_id = uuid.uuid4().hex
        try:
            engine = db.engine
            lock_conn = engine.connect()
            lock_acquired = _acquire_named_lock(lock_conn, SUMMARY_REBUILD_LOCK_NAME)
            if not lock_acquired:
                row = _get_summary_status_row(lock_conn) or {}
                admission.update(code=409, payload={"status": "running",
                    "message": "Dashboard refresh is already running.",
                    "progress": int(row.get("progress") or 0),
                    "current_step": row.get("current_step") or "Preparing refresh"})
                return
            if time.monotonic() > admission.get("deadline", float("inf")):
                admission.update(code=503, payload={"status": "unavailable",
                    "error": "Refresh startup took too long. Please check status and retry."})
                return
            # Acquire and retain the lock BEFORE publishing queued. No transfer
            # of a request connection, and no unlocked request/thread handoff.
            _update_summary_status(lock_conn, job_id=operation_id, status="queued", progress=0,
                current_step="Queued", started_at=datetime.now(), completed_at=None,
                error_message=None, last_sql=None, last_traceback=None,
                source_rows=None, temp_rows=None, live_rows=None, elapsed_ms=None,
                tmp_table_name=None, worker_running=True)
            admission.update(code=202, payload={"status": "started"})
            admitted.set()
            current_app.logger.info(
                "Common dashboard refresh operation_id=%s pid=%s hostname=%s thread=%s started",
                operation_id, os.getpid(), socket.gethostname(), threading.get_ident())

            def _multitax_status_callback(**updates):
                if updates.get("status") == "error":
                    raise RuntimeError(updates.get("detail") or "Multi-Tax Integration failed")
                if updates.get("stage") == "integration_completed" and updates.get("rows_saved") == 0:
                    raise RuntimeError("Multi-Tax Integration returned zero rows. Dashboard summary was not rebuilt.")
                stages = {
                    "refresh_started": (10, "Refreshing Multi-Tax aggregates"),
                    "aggregation_complete": (35, "Multi-Tax aggregation complete"),
                    "integration_started": (45, "Running Multi-Tax Integration"),
                    "integration_completed": (60, "Multi-Tax Integration complete"),
                }
                progress, step = stages.get(updates.get("stage"), (5, "Preparing Multi-Tax Integration"))
                _update_summary_status(lock_conn, status="running", progress=progress,
                    current_step=step, worker_running=True)
                current_app.logger.info("Common dashboard refresh operation_id=%s stage=%s",
                                        operation_id, updates.get("stage"))

            _update_summary_status(lock_conn, status="running", progress=5,
                current_step="Preparing Multi-Tax Integration", worker_running=True)
            refresh_multi_tax_tables(current_user_id=current_user_id,
                                     status_callback=_multitax_status_callback)
            _assert_summary_lock(lock_conn)
            integration_completed = True
            _run_summary_rebuild(lock_conn)
            current_app.logger.info("Common dashboard refresh operation_id=%s completed", operation_id)
        except BaseException as exc:
            tb = traceback.format_exc()
            current_app.logger.exception("Common dashboard refresh operation_id=%s failed", operation_id)
            message = str(exc)
            if not integration_completed:
                message = "Multi-Tax Integration failed. Dashboard summary was not rebuilt. " + message
            if lock_acquired:
                try:
                    _update_summary_status(lock_conn, status="failed", progress=0,
                        current_step="Failed" if integration_completed else "Multi-Tax Integration failed",
                        completed_at=datetime.now(), error_message=message,
                        last_traceback=tb, worker_running=False)
                except Exception:
                    # A disconnected owner must never overwrite a newer job.
                    # Shared lock recovery will mark the abandoned run failed.
                    current_app.logger.exception("Unable to persist failure for operation_id=%s", operation_id)
            if not admitted.is_set():
                admission.update(code=500, payload={"status": "failed", "error": message})
        finally:
            admitted.set()
            if lock_conn is not None:
                try:
                    if lock_acquired:
                        _release_named_lock(lock_conn, SUMMARY_REBUILD_LOCK_NAME)
                finally:
                    lock_conn.close()


def _summary_rows(query_sql, params):
    return db.session.execute(text(query_sql), params).mappings().all()


def _summary_data(rows, mapping):
    return [{key: fn(r) for key, fn in mapping.items()} for r in rows]


MULTITAX_RECORD_COLUMNS = (
    "tin", "tax_period_year", "tax_account_number", "assessment_number",
    "taxpayer_name", "taxpayer_type", "sector_activity", "enterprise_activity",
    "cit_gross_sales", "cit_total_gross_income", "cit_salaries_or_wages",
    "cit_total_tax_payable", "cit_net_tax_payable", "gst_total_sales_income",
    "gst_taxable_sales", "gst_output_debits", "gst_input_credits", "gst_payable",
    "gst_refundable", "swt_total_salary_wages_paid", "swt_total_tax_deducted",
    "swt_employees_on_payroll", "swt_employees_paid_swt", "gst_vs_cit_sales_diff",
    "gst_vs_cit_sales_diff_abs", "gst_vs_cit_sales_pct", "swt_vs_cit_salary_diff",
    "swt_vs_cit_salary_diff_abs", "swt_vs_cit_salary_pct", "gst_validation",
    "swt_validation", "cit_fraud_flag", "gst_fraud_flag", "swt_fraud_flag",
    "flagged_in_tax_types", "multi_tax_issue",
)


@bp.get("/multitax-records")
@jwt_required()
def multitax_records():
    try:
        page = int(request.args.get("page", "1"))
        page_size = int(request.args.get("page_size", "50"))
        if page < 1 or not 1 <= page_size <= 200:
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify({"error": "page must be positive and page_size must be between 1 and 200."}), 400
    date_filter, query_params = ("1=1", {})
    if any(key in request.args for key in ("range_type", "start_date", "from_date")):
        date_filter, query_params = get_date_filter()
    filters = [date_filter]
    tin = _get_dashboard_tin()
    if tin:
        filters.append("tin = :tin")
        query_params["tin"] = tin
    where = " AND ".join(f"({clause})" for clause in filters)
    columns = ", ".join(MULTITAX_RECORD_COLUMNS)
    # There is no primary key in the existing result table. Tie-break on all
    # returned values; exact duplicate records remain separate rows. No schema
    # change or grouping is introduced. Deep offsets still need profiling.
    ordering = ", ".join(MULTITAX_RECORD_COLUMNS)
    with db.engine.connect() as conn:
        total = int(conn.execute(text(f"SELECT COUNT(*) FROM multi_tax_integration_results WHERE {where}"), query_params).scalar() or 0)
        page = min(page, max(1, (total + page_size - 1) // page_size))
        rows = conn.execute(text(f"SELECT {columns} FROM multi_tax_integration_results WHERE {where} ORDER BY {ordering} LIMIT :limit OFFSET :offset"),
                            {**query_params, "limit": page_size, "offset": (page - 1) * page_size}).mappings().all()
    # BIGINT account/assessment numbers must not lose precision in JavaScript.
    records = [{key: str(row[key]) if key in {"tax_account_number", "assessment_number"} and row[key] is not None else row[key]
                for key in MULTITAX_RECORD_COLUMNS} for row in rows]
    if request.args.get("format") == "csv":
        return _build_csv_response(records, f"multitax-records-page-{page}.csv", MULTITAX_RECORD_COLUMNS)
    return jsonify({"records": records, "total": total, "page": page, "page_size": page_size})


@bp.post("/rebuild-summary")
@jwt_required()
def rebuild_summary():
    app = current_app._get_current_object()
    current_user_id = get_authenticated_user_id()
    admission = {"deadline": time.monotonic() + 10}
    admitted = threading.Event()
    try:
        # Run the idempotent status compatibility migration before the worker
        # can write job_id. Existing rows are retained unchanged.
        with db.engine.begin() as conn:
            _ensure_summary_status_schema(conn)
            _ensure_summary_status_row(conn)
        worker = threading.Thread(target=_background_summary_rebuild_worker,
            args=(app, current_user_id, admission, admitted), daemon=True,
            name="multitax-dashboard-summary-rebuild")
        worker.start()
        # Wait only for lock acquisition and queued persistence, not integration.
        # is_alive() is not a success test: a valid job may complete immediately.
        if not admitted.wait(timeout=10):
            return jsonify({"status": "unavailable", "error": "Refresh startup has not been confirmed. Check refresh status before retrying."}), 503
        return jsonify(admission["payload"]), admission["code"]
    except Exception as exc:
        current_app.logger.exception("Unable to start dashboard summary rebuild.")
        return jsonify({"status": "failed", "error": str(exc)}), 500


@bp.get("/rebuild-status")
@bp.get("/rebuild-summary/status")
@jwt_required()
def rebuild_summary_status():
    try:
        return jsonify(_summary_status_payload())
    except Exception as exc:
        current_app.logger.exception("Unable to fetch dashboard summary rebuild status.")
        return jsonify({"status": "failed", "error": str(exc)}), 500


@bp.get("/rebuild-summary/debug")
@jwt_required()
def rebuild_summary_debug():
    try:
        with db.engine.begin() as conn:
            snapshot = _status_debug_snapshot(conn)
            source_rows = int(conn.execute(text("SELECT COUNT(*) FROM multi_tax_integration_results")).scalar() or 0)
            summary_rows = int(conn.execute(text(f"SELECT COUNT(*) FROM {SUMMARY_TABLE}")).scalar() or 0)
            tmp_table_name = snapshot.get("tmp_table_name")
            temp_exists = bool(tmp_table_name and _table_exists(conn, tmp_table_name))
        return jsonify({
            "source_rows": source_rows,
            "summary_rows": summary_rows,
            "temp_exists": temp_exists,
            "temp_rows": snapshot.get("temp_rows"),
            "tmp_table_name": snapshot.get("tmp_table_name"),
            "status": snapshot.get("status"),
            "progress": snapshot.get("progress"),
            "current_step": snapshot.get("current_step"),
            "last_error": snapshot.get("last_error"),
            "last_sql": snapshot.get("last_sql"),
            "worker_running": snapshot.get("worker_running"),
        })
    except Exception as exc:
        current_app.logger.exception("Unable to fetch dashboard summary debug state.")
        return jsonify({"status": "failed", "error": str(exc)}), 500


@download_bp.get("/tax-flow")

@jwt_required()
def download_tax_flow():
    where_clause, params = _summary_scope(include_tin=True)
    rows = _summary_rows(f"SELECT tin, taxpayer_name, tax_period_year AS year, total_income AS income, profit, cit_tax AS tax, sector_activity AS sector FROM {SUMMARY_TABLE} WHERE {where_clause} ORDER BY tax_period_year, tin", params)
    data = _summary_data(rows, {"tin": lambda r: r.get("tin") or "", "taxpayer_name": lambda r: r.get("taxpayer_name") or "Unknown", "year": lambda r: int(r.get("year")) if r.get("year") is not None else "", "income": lambda r: float(r.get("income") or 0), "profit": lambda r: float(r.get("profit") or 0), "tax": lambda r: float(r.get("tax") or 0), "sector": lambda r: r.get("sector") or "Unknown"})
    _debug_csv_sample("common-tax-flow", data)
    return _build_csv_response(data, "tax-flow.csv", _parse_columns(["year", "income", "profit", "tax", "sector"], ["tin", "taxpayer_name", "year", "income", "profit", "tax", "sector"], include_ids=True))

@download_bp.get("/top-sectors")
@jwt_required()
def download_top_sectors():
    where_clause, params = _summary_scope(include_tin=True)
    rows = _summary_rows(f"SELECT tin, taxpayer_name, sector_activity AS sector, SUM(total_income) AS income, SUM(cit_tax) AS tax, COUNT(*) AS taxpayers FROM {SUMMARY_TABLE} WHERE {where_clause} GROUP BY tin, taxpayer_name, sector_activity ORDER BY income DESC, tin LIMIT 10", params)
    data = _summary_data(rows, {"tin": lambda r: r.get("tin") or "", "taxpayer_name": lambda r: r.get("taxpayer_name") or "Unknown", "sector": lambda r: r.get("sector") or "Unknown", "income": lambda r: float(r.get("income") or 0), "tax": lambda r: float(r.get("tax") or 0), "taxpayers": lambda r: int(r.get("taxpayers") or 0)})
    _debug_csv_sample("common-top-sectors", data)
    return _build_csv_response(data, "top-sectors.csv", _parse_columns(["sector", "income", "tax"], ["tin", "taxpayer_name", "sector", "income", "tax", "taxpayers"], include_ids=True))

@download_bp.get("/fraud-year")
@jwt_required()
def download_fraud_year():
    where_clause, params = _summary_scope(include_tin=True)
    rows = _summary_rows(f"SELECT tin, taxpayer_name, tax_period_year AS year, SUM(fraud_flag) AS fraud_cases FROM {SUMMARY_TABLE} WHERE {where_clause} GROUP BY tin, taxpayer_name, tax_period_year ORDER BY tax_period_year, tin", params)
    data = _summary_data(rows, {"tin": lambda r: r.get("tin") or "", "taxpayer_name": lambda r: r.get("taxpayer_name") or "Unknown", "year": lambda r: int(r.get("year")) if r.get("year") is not None else "", "fraud_cases": lambda r: int(r.get("fraud_cases") or 0)})
    _debug_csv_sample("common-fraud-year", data)
    return _build_csv_response(data, "fraud-year.csv", _parse_columns(["year", "fraud_cases"], ["tin", "taxpayer_name", "year", "fraud_cases"], include_ids=True))

@download_bp.get("/fraud-distribution")
@jwt_required()
def download_fraud_distribution():
    where_clause, params = _summary_scope(include_tin=True)
    rows = _summary_rows(f"SELECT tin, taxpayer_name, predicted_fraud AS risk_flag, SUM(total_income) AS income, SUM(cit_tax) AS exposure FROM {SUMMARY_TABLE} WHERE {where_clause} GROUP BY tin, taxpayer_name, predicted_fraud ORDER BY exposure DESC, tin", params)
    data = _summary_data(rows, {"tin": lambda r: r.get("tin") or "", "taxpayer_name": lambda r: r.get("taxpayer_name") or "Unknown", "risk_flag": lambda r: r.get("risk_flag") or "Non-Risk Flagged", "income": lambda r: float(r.get("income") or 0), "exposure": lambda r: float(r.get("exposure") or 0)})
    _debug_csv_sample("common-fraud-distribution", data)
    return _build_csv_response(data, "fraud-distribution.csv", _parse_columns(["risk_flag", "income", "exposure"], ["tin", "taxpayer_name", "risk_flag", "income", "exposure"], include_ids=True))

@download_bp.get("/top-tins")
@jwt_required()
def download_top_tins():
    where_clause, params = _summary_scope(include_tin=True)
    rows = _summary_rows(f"SELECT tin, MAX(taxpayer_name) AS taxpayer_name, SUM(total_income) AS income, 0 AS profit, SUM(cit_tax) AS tax FROM {SUMMARY_TABLE} WHERE {where_clause} GROUP BY tin ORDER BY income DESC, tin LIMIT 10", params)
    data = _summary_data(rows, {"tin": lambda r: r.get("tin") or "", "taxpayer_name": lambda r: r.get("taxpayer_name") or "Unknown", "income": lambda r: float(r.get("income") or 0), "profit": lambda r: float(r.get("profit") or 0), "tax": lambda r: float(r.get("tax") or 0)})
    _debug_csv_sample("common-top-tins", data)
    return _build_csv_response(data, "top-tins.csv", _parse_columns(["income", "tax", "profit"], ["tin", "taxpayer_name", "income", "profit", "tax"], include_ids=True))

@download_bp.get("/consolidated")
@jwt_required()
def download_consolidated():
    where_clause, params = _summary_scope(include_tin=True)
    rows = _summary_rows(f"SELECT tin, taxpayer_name, tax_period_year, total_income, profit, cit_tax, gst_sales_diff_abs AS gst_diff, swt_salary_diff_abs AS swt_diff, predicted_fraud, sector_activity FROM {SUMMARY_TABLE} WHERE {where_clause} ORDER BY total_income DESC, tin, tax_period_year LIMIT 500", params)
    data = _summary_data(rows, {"tin": lambda r: r.get("tin") or "", "taxpayer_name": lambda r: r.get("taxpayer_name") or "Unknown", "tax_period_year": lambda r: r.get("tax_period_year") or "", "total_income": lambda r: float(r.get("total_income") or 0), "profit": lambda r: float(r.get("profit") or 0), "cit_tax": lambda r: float(r.get("cit_tax") or 0), "gst_diff": lambda r: float(r.get("gst_diff") or 0), "swt_diff": lambda r: float(r.get("swt_diff") or 0), "predicted_fraud": lambda r: r.get("predicted_fraud") or "Non-Risk Flagged", "sector_activity": lambda r: r.get("sector_activity") or "Unknown"})
    _debug_csv_sample("common-consolidated", data)
    return _build_csv_response(data, "consolidated.csv", _parse_columns(["tax_period_year", "total_income", "profit", "cit_tax", "gst_diff", "swt_diff", "predicted_fraud", "sector_activity"], ["tin", "taxpayer_name", "tax_period_year", "total_income", "profit", "cit_tax", "gst_diff", "swt_diff", "predicted_fraud", "sector_activity"], include_ids=True))

@bp.get("/financial-overview")
@jwt_required()
def financial_overview():
    where_clause, params = _summary_scope(include_tin=True)
    _log_dashboard_query_context("financial-overview", params)
    row = db.session.execute(text(f"SELECT COALESCE(SUM(total_income), 0) AS total_income, COALESCE(SUM(profit), 0) AS total_profit, COALESCE(SUM(cit_tax), 0) AS total_cit_tax, COALESCE(ROUND((SUM(cit_tax) / NULLIF(SUM(total_income), 0)) * 100, 2), 0) AS effective_tax_rate FROM {SUMMARY_TABLE} WHERE {where_clause}"), params).mappings().first() or {}
    if not any([float(row.get("total_income") or 0), float(row.get("total_cit_tax") or 0), float(row.get("effective_tax_rate") or 0)]):
        _log_dashboard_zero_row_count("financial-overview", True, params)
    return jsonify({"total_income": float(row.get("total_income") or 0), "total_profit": float(row.get("total_profit") or 0), "total_cit_tax": float(row.get("total_cit_tax") or 0), "effective_tax_rate": float(row.get("effective_tax_rate") or 0)})

@bp.get("/tax-flow")
@jwt_required()
def tax_flow():
    where_clause, params = _summary_scope(include_tin=True)
    _log_dashboard_query_context("tax-flow", params)
    rows = _summary_rows(f"SELECT tax_period_year AS y, SUM(total_income) AS income, SUM(profit) AS profit, SUM(cit_tax) AS cit_tax FROM {SUMMARY_TABLE} WHERE {where_clause} GROUP BY tax_period_year ORDER BY tax_period_year", params)
    if not rows:
        _log_dashboard_zero_row_count("tax-flow", True, params)
    return jsonify({"categories": [str(r.get("y")) for r in rows], "series": [{"name": "Income", "data": [float(r.get("income") or 0) for r in rows]}, {"name": "Profit", "data": [float(r.get("profit") or 0) for r in rows]}, {"name": "CIT Tax", "data": [float(r.get("cit_tax") or 0) for r in rows]}]})

@bp.get("/risk-exposure")
@jwt_required()
def risk_exposure():
    where_clause, params = _summary_scope(include_tin=True)
    _log_dashboard_query_context("risk-exposure", params)
    rows = _summary_rows(f"SELECT predicted_fraud, SUM(total_income) AS income, SUM(cit_tax) AS tax_exposure, COUNT(DISTINCT tin) AS taxpayers FROM {SUMMARY_TABLE} WHERE {where_clause} GROUP BY predicted_fraud ORDER BY predicted_fraud", params)
    if not rows:
        _log_dashboard_zero_row_count("risk-exposure", True, params)
    return jsonify([{"predicted_fraud": r.get("predicted_fraud") or "Non-Risk Flagged", "income": float(r.get("income") or 0), "tax_exposure": float(r.get("tax_exposure") or 0), "taxpayers": int(r.get("taxpayers") or 0)} for r in rows])

@bp.get("/cross-tax-mismatch")
@jwt_required()
def cross_tax_mismatch():
    where_clause, params = _summary_scope(include_tin=True)
    rows = _summary_rows(f"SELECT tin, tax_period_year, gst_sales AS sales, salary_wages AS wages, profit, cit_tax, ROUND((salary_wages / NULLIF(gst_sales, 0)) * 100, 2) AS wage_ratio FROM {SUMMARY_TABLE} WHERE {where_clause} ORDER BY tax_period_year", params)
    return jsonify([dict(r) for r in rows])
@bp.get("/sector-analysis")
@jwt_required()
def sector_analysis():
    where_clause, params = _summary_scope(include_tin=True)
    _log_dashboard_query_context("sector-analysis", params)
    rows = _summary_rows(f"SELECT sector_activity AS sector, SUM(total_income) AS income, SUM(cit_tax) AS tax, COUNT(DISTINCT tin) AS taxpayers FROM {SUMMARY_TABLE} WHERE {where_clause} GROUP BY sector_activity ORDER BY income DESC, sector_activity LIMIT 10", params)
    if not rows:
        _log_dashboard_zero_row_count("sector-analysis", True, params)
    return jsonify([{"sector": r.get("sector") or "Unknown", "income": float(r.get("income") or 0), "tax": float(r.get("tax") or 0), "taxpayers": int(r.get("taxpayers") or 0)} for r in rows])

@bp.get("/top-financial-tins")
@jwt_required()
def top_financial_tins():
    where_clause, params = _summary_scope(include_tin=True)
    _log_dashboard_query_context("top-financial-tins", params)
    rows = _summary_rows(f"SELECT tin, MAX(taxpayer_name) AS taxpayer, SUM(total_income) AS income, SUM(profit) AS profit, SUM(cit_tax) AS tax FROM {SUMMARY_TABLE} WHERE {where_clause} GROUP BY tin ORDER BY income DESC, tin LIMIT 10", params)
    if not rows:
        _log_dashboard_zero_row_count("top-financial-tins", True, params)
    return jsonify([{"tin": r.get("tin") or "", "taxpayer": r.get("taxpayer") or "Unknown", "income": float(r.get("income") or 0), "profit": float(r.get("profit") or 0), "tax": float(r.get("tax") or 0)} for r in rows])

@bp.get("/consolidated-records")
@jwt_required()
def consolidated_records_multitax():
    where_clause, params = _summary_scope(include_tin=True)
    _log_dashboard_query_context("consolidated-records", params)
    rows = _summary_rows(f"SELECT tin, taxpayer_name AS taxpayer, tax_period_year, total_income, profit, NULL AS taxable_income, cit_tax, gst_sales AS total_sales_revenue, salary_wages AS total_salary_or_wages, predicted_fraud, gst_sales_diff_abs, swt_salary_diff_abs, multi_tax_issue, sector_activity FROM {SUMMARY_TABLE} WHERE {where_clause} ORDER BY total_income DESC, tin, tax_period_year LIMIT 500", params)
    if not rows:
        _log_dashboard_zero_row_count("consolidated-records", True, params)
    return jsonify([{"tin": r.get("tin") or "", "taxpayer": r.get("taxpayer") or "Unknown", "tax_period_year": r.get("tax_period_year"), "total_income": float(r.get("total_income") or 0), "profit": float(r.get("profit") or 0), "taxable_income": r.get("taxable_income"), "cit_tax": float(r.get("cit_tax") or 0), "total_sales_revenue": float(r.get("total_sales_revenue") or 0), "total_salary_or_wages": float(r.get("total_salary_or_wages") or 0), "predicted_fraud": r.get("predicted_fraud") or "Non-Risk Flagged", "gst_sales_diff_abs": float(r.get("gst_sales_diff_abs") or 0), "swt_salary_diff_abs": float(r.get("swt_salary_diff_abs") or 0), "multi_tax_issue": r.get("multi_tax_issue"), "sector_activity": r.get("sector_activity") or "Unknown"} for r in rows])

@bp.get("/fraud-consistency")
@jwt_required()
def fraud_consistency():
    where_clause, params = _summary_scope(include_tin=True)
    rows = _summary_rows(f"SELECT tin, CASE WHEN MAX(fraud_flag) = 1 THEN 'Risk Flagged' ELSE 'Non-Risk Flagged' END AS predicted_fraud FROM {SUMMARY_TABLE} WHERE {where_clause} GROUP BY tin ORDER BY tin", params)
    return jsonify([dict(r) for r in rows])

# @bp.get("/dropdown")
# @jwt_required()
# def taxpayer_dropdown():
#     _ensure_summary_ready()
#     search = (request.args.get("q") or "").strip()
#     params = {}
#     filters = ["1=1"]
#     if search:
#         params["search"] = f"%{search}%"
#         filters.append("(tin LIKE :search OR taxpayer_name LIKE :search)")
#     rows = _summary_rows(f"SELECT TRIM(tin) AS tin, MAX(COALESCE(NULLIF(TRIM(taxpayer_name), ''), 'Unknown')) AS name FROM {SUMMARY_TABLE} WHERE {' AND '.join(filters)} GROUP BY TRIM(tin) ORDER BY name, tin LIMIT 50", params)
#     return jsonify([dict(r) for r in rows])

# --------------------------------------------------------
#   API 1: GET DISTINCT TIN
# --------------------------------------------------------
@bp.route("/dropdown", methods=["OPTIONS"])
def taxpayer_dropdown_options():
    return ("", 200)


@bp.get("/dropdown")
@jwt_required()
def taxpayer_dropdown():
    try:
        search = (request.args.get("q") or "").strip()

        params = {}
        where = "WHERE trm.tin IS NOT NULL"
        if search:
            params["s"] = f"%{search}%"
            where += """
                AND (
                    CAST(trm.tin AS CHAR(30)) LIKE :s
                    OR trm.taxpayername LIKE :s
                    OR trm.maintradename LIKE :s
                )
            """

        query = f"""
            SELECT
                trm.tin AS tin,
                COALESCE(
                    NULLIF(TRIM(trm.taxpayername), ''),
                    NULLIF(TRIM(trm.maintradename), ''),
                    'Unknown'
                ) AS taxpayer_name
            FROM tin_registration_mst trm
            {where}
            ORDER BY taxpayer_name ASC
            LIMIT 100
        """

        rows = db.session.execute(text(query), params).fetchall()
        return jsonify(
            [
                {
                    "value": r._mapping["tin"],
                    "label": f'{r._mapping["tin"]} - {r._mapping["taxpayer_name"]}',
                    "name": r._mapping["taxpayer_name"],
                    "tin": r._mapping["tin"],
                    "taxpayer_name": r._mapping["taxpayer_name"],
                }
                for r in rows
                if r._mapping.get("tin") and r._mapping.get("taxpayer_name")
            ]
        ), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify([]), 200

@bp.get("/high-risk-tins")
@jwt_required()
def high_risk_tins():
    try:
        raw_sql = text("SELECT tin, tax_type, taxpayer, risk_type, SUM(flags) AS flags, ROUND(MAX(risk_score), 2) AS risk_score FROM ( SELECT TRIM(far.tin) COLLATE utf8mb4_unicode_ci AS tin, 'GST' COLLATE utf8mb4_unicode_ci AS tax_type, far.taxpayer_name COLLATE utf8mb4_unicode_ci AS taxpayer, far.risk_type COLLATE utf8mb4_unicode_ci AS risk_type, COALESCE(far.flag_count, 1) AS flags, COALESCE(far.flag_percentage, 0) AS risk_score FROM flagged_audit_records far WHERE far.is_flag = 1 UNION ALL SELECT TRIM(fars.tin) COLLATE utf8mb4_unicode_ci AS tin, 'SWT' COLLATE utf8mb4_unicode_ci AS tax_type, fars.taxpayer_name COLLATE utf8mb4_unicode_ci AS taxpayer, fars.risk_type COLLATE utf8mb4_unicode_ci AS risk_type, COALESCE(fars.flag_count, 1) AS flags, COALESCE(fars.flag_percentage, 0) AS risk_score FROM flagged_audit_records_swt fars WHERE fars.is_flag = 1 UNION ALL SELECT TRIM(farc.tin) COLLATE utf8mb4_unicode_ci AS tin, 'CIT' COLLATE utf8mb4_unicode_ci AS tax_type, farc.taxpayer COLLATE utf8mb4_unicode_ci AS taxpayer, farc.risk_type COLLATE utf8mb4_unicode_ci AS risk_type, COALESCE(farc.sum_of_rules, 1) AS flags, COALESCE(farc.flag_percentage, 0) AS risk_score FROM flagged_audit_records_cit farc WHERE farc.is_flag = 1 ) x GROUP BY tin, tax_type, taxpayer, risk_type ORDER BY risk_score DESC")
        rows = db.session.execute(raw_sql).fetchall()
        return jsonify([dict(r._mapping) for r in rows])
    except Exception as exc:
        current_app.logger.exception(exc)
        return jsonify({"success": False, "error": str(exc)}), 500

@bp.get("/fraud-trend")
@jwt_required()
def fraud_trend():
    try:
        where_clause, params = _summary_scope(include_tin=True)
        _log_dashboard_query_context("fraud-trend", params)
        rows = _summary_rows(f"SELECT tax_period_year AS year, SUM(fraud_flag) AS fraud_cases FROM {SUMMARY_TABLE} WHERE {where_clause} GROUP BY tax_period_year ORDER BY tax_period_year", params)
        if not rows:
            _log_dashboard_zero_row_count("fraud-trend", True, params)
        return jsonify([{"year": int(r.get("year")), "fraud_cases": int(r.get("fraud_cases") or 0)} for r in rows])
    except Exception as exc:
        current_app.logger.exception(exc)
        return jsonify({"success": False, "error": str(exc)}), 500
