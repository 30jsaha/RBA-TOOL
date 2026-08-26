import os
import time
import json
import threading
import uuid
import pandas as pd
from flask import Blueprint, request, jsonify, send_from_directory, url_for, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..extensions import db
from datetime import datetime, date, timedelta
import traceback
from sqlalchemy import text, tuple_, or_, inspect
import pickle
from typing import List, Set, Dict, Tuple

import math
import numpy as np

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# NOTE: Must be unique across the app. "process" was too generic and could
# conflict with other blueprints, causing routes to not register as expected.
bp = Blueprint("segmentation", __name__)

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
SEGMENTED_FOLDER = "segmented"
SEGMENTATION_BATCH_SIZE = 5000
SEGMENTATION_JOB_TABLE = "segmentation_jobs"
SEGMENTATION_LOCK_NAME = "segmentation_background_job_lock"
_SEGMENTATION_JOB_TABLE_READY = False
_SEGMENTATION_JOB_TABLE_LOCK = threading.Lock()
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(SEGMENTED_FOLDER, exist_ok=True)

def get_file_ext(path):
    return os.path.splitext(path)[1].lower()

def _load_dataframe(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()

    if ext == ".csv":
        return pd.read_csv(path, low_memory=False)
    if ext in (".xls", ".xlsx"):
        return pd.read_excel(path)
    if ext == ".parquet":
        return pd.read_parquet(path)

    raise ValueError(f"Unsupported file format: {ext}")



def save_output(df, base_name, source_file):
    """
    Saves dataframe in same format as source_file (csv/xlsx/parquet)
    """
    ext = get_file_ext(source_file)
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    if ext == ".csv":
        output = os.path.join(OUTPUT_FOLDER, f"{base_name}_{timestamp}.csv")
        df.to_csv(output, index=False)

    elif ext in [".xls", ".xlsx"]:
        output = os.path.join(OUTPUT_FOLDER, f"{base_name}_{timestamp}.xlsx")
        df.to_excel(output, index=False)

    else:  # parquet fallback
        output = os.path.join(OUTPUT_FOLDER, f"{base_name}_{timestamp}.parquet")
        df.to_parquet(output, index=False)

    return output


# =====================================================================
# Helper: Insert record in file_process table
# =====================================================================

def safe(val):
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    if isinstance(val, np.floating) and np.isnan(val):
        return None
    return val

def log_file_process(file_upload_history_id, output_path, process_name, user_id):
    """
    Best-effort logger.

    Older code referenced ORM models that may not exist anymore. This keeps the
    call sites intact without breaking APIs:
    - Inserts into `file_process` only if that table exists.
    - Never raises on logging failures.
    """
    try:
        engine = db.engine
        inspector = inspect(engine)
        if not inspector.has_table("file_process"):
            return

        cols = {c["name"] for c in inspector.get_columns("file_process")}
        payload = {
            "file_upload_history_id": file_upload_history_id,
            "file_output_path": output_path,
            "process_name": process_name,
            "process_by": user_id,
        }
        insert_cols = [c for c in payload.keys() if c in cols]
        if not insert_cols:
            return

        sql = (
            f"INSERT INTO file_process ({', '.join(insert_cols)}) "
            f"VALUES ({', '.join([f':{c}' for c in insert_cols])})"
        )
        with engine.begin() as conn:
            conn.execute(text(sql), {c: payload[c] for c in insert_cols})
    except Exception as e:
        print(f"[WARN] Could not insert file_process record: {e}")


# =====================================================================
# Helpers: upload_log + fraud table access (current DB structure)
# =====================================================================

def _get_table_columns(engine, table_name: str) -> Set[str]:
    # Do not cache schema: production DB schema can evolve while the server is running
    # (e.g., adding `segmentation` column). Caching can cause false "column missing"
    # errors until restart.
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns(table_name)}
    return cols


def _upload_log_has_user_id(engine) -> bool:
    cols = _get_table_columns(engine, "upload_log")
    return "user_id" in cols


def _get_latest_upload_log(engine, user_id: int, tax_type: str):
    tax_type = str(tax_type).upper()
    has_user_id = _upload_log_has_user_id(engine)
    upload_log_cols = _get_table_columns(engine, "upload_log")
    batch_select = "upload_batch_id" if "upload_batch_id" in upload_log_cols else "NULL AS upload_batch_id"
    if has_user_id:
        sql = """
            SELECT id, uploaded_at, user_id, {batch_select}
            FROM upload_log
            WHERE user_id = :user_id
              AND UPPER(COALESCE(tax_type, '')) = :tax_type
            ORDER BY uploaded_at DESC, id DESC
            LIMIT 1
        """.format(batch_select=batch_select)
        params = {"user_id": user_id, "tax_type": tax_type}
    else:
        # Backward-compatible DBs: upload_log has no user_id, so we can only select latest overall.
        sql = """
            SELECT id, uploaded_at, NULL AS user_id, {batch_select}
            FROM upload_log
            WHERE UPPER(COALESCE(tax_type, '')) = :tax_type
            ORDER BY uploaded_at DESC, id DESC
            LIMIT 1
        """.format(batch_select=batch_select)
        params = {"tax_type": tax_type}

    return db.session.execute(text(sql), params).fetchone()


def _get_upload_log_by_id(engine, user_id: int, tax_type: str, upload_id: int):
    tax_type = str(tax_type).upper()
    has_user_id = _upload_log_has_user_id(engine)
    upload_log_cols = _get_table_columns(engine, "upload_log")
    batch_select = "upload_batch_id" if "upload_batch_id" in upload_log_cols else "NULL AS upload_batch_id"
    if has_user_id:
        sql = """
            SELECT id, uploaded_at, user_id, {batch_select}
            FROM upload_log
            WHERE id = :upload_id
              AND user_id = :user_id
              AND UPPER(COALESCE(tax_type, '')) = :tax_type
            LIMIT 1
        """.format(batch_select=batch_select)
        params = {"upload_id": int(upload_id), "user_id": user_id, "tax_type": tax_type}
    else:
        sql = """
            SELECT id, uploaded_at, NULL AS user_id, {batch_select}
            FROM upload_log
            WHERE id = :upload_id
              AND UPPER(COALESCE(tax_type, '')) = :tax_type
            LIMIT 1
        """.format(batch_select=batch_select)
        params = {"upload_id": int(upload_id), "tax_type": tax_type}

    return db.session.execute(text(sql), params).fetchone()


def _build_user_upload_filter(engine, table_name: str, alias: str, user_id: int, upload_row):
    cols = _get_table_columns(engine, table_name)
    clauses = []
    params = {"user_id": user_id}

    # Prefer user scoping when the schema supports it.
    # Some deployed DBs (per db-backup) do not include `user_id` on these tables.
    if "user_id" in cols:
        clauses.append(f"{alias}.user_id = :user_id")

    upload_id = int(upload_row.id)
    upload_ts = upload_row.uploaded_at

    upload_fk_col = None
    for candidate in ("upload_log_id", "upload_id", "file_upload_history_id"):
        if candidate in cols:
            upload_fk_col = candidate
            break

    if upload_fk_col:
        clauses.append(f"{alias}.{upload_fk_col} = :upload_id")
        params["upload_id"] = upload_id
        return clauses, params

    if "uploaded_at" in cols and upload_ts is not None:
        # uploaded_at values may differ between upload_log and fraud tables (upload time vs insert time).
        # Use a practical window to find the latest inserted batch for that upload.
        window = timedelta(hours=6)
        clauses.append(f"{alias}.uploaded_at BETWEEN :uploaded_at_start AND :uploaded_at_end")
        params["uploaded_at_start"] = upload_ts - window
        params["uploaded_at_end"] = upload_ts + window
        return clauses, params

    raise RuntimeError(
        f"Cannot safely scope {table_name} to a single upload (missing upload reference columns)"
    )


def _fetch_fraud_df(
    engine,
    table_name: str,
    select_cols: List[str],
    user_id: int,
    upload_row=None,
    upload_batch_id=None
) -> pd.DataFrame:
    cols = _get_table_columns(engine, table_name)
    missing = [c for c in select_cols if c not in cols]
    if missing:
        raise RuntimeError(f"{table_name} missing required columns: {', '.join(missing)}")

    where_clauses = []
    params = {}
    use_batch_filter = bool(upload_batch_id and "upload_batch_id" in cols)

    if use_batch_filter:
        if "user_id" in cols:
            where_clauses = ["t.user_id = :user_id"]
            params = {"user_id": user_id}
    elif upload_row is not None:
        where_clauses, params = _build_user_upload_filter(engine, table_name, "t", user_id, upload_row)
    elif "user_id" in cols:
        where_clauses = ["t.user_id = :user_id"]
        params = {"user_id": user_id}

    if use_batch_filter:
        where_clauses.append("t.upload_batch_id = :upload_batch_id")
        params["upload_batch_id"] = upload_batch_id

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    sql = text(f"SELECT {', '.join(select_cols)} FROM {table_name} t WHERE {where_sql}")
    print("TABLE:", table_name)
    print("USER:", user_id)
    print("UPLOAD_BATCH_ID:", upload_batch_id)
    print("WHERE:", where_sql)
    if use_batch_filter:
        print("Batch filter ENABLED")
    else:
        print("Batch filter DISABLED")
    print(
        f"Fetching {table_name} "
        f"for user_id={user_id}, "
        f"upload_batch_id={upload_batch_id}"
    )
    print(f"SQL Query: SELECT {', '.join(select_cols)} FROM {table_name} t WHERE {where_sql}")
    df = pd.read_sql(sql, con=engine, params=params)
    print(f"{table_name} row count = {len(df)}")
    print(f"Fetched {len(df)} rows from {table_name}")
    return df

# ==============================================================
# Helper: Load DataFrame based on file extension
# ==============================================================
def load_dataframe(file_path):
    """
    Load dataframe based on file extension.
    Supports: CSV, XLSX, XLS, PARQUET
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".csv":
        return pd.read_csv(file_path, low_memory=False)

    if ext in (".xlsx", ".xls"):
        return pd.read_excel(file_path, engine="openpyxl")

    if ext == ".parquet":
        return pd.read_parquet(file_path)

    raise ValueError(f"Unsupported file format: {ext}")

from datetime import datetime, date
from werkzeug.utils import secure_filename
import os

def extract_year(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").year
    except Exception:
        raise ValueError("Invalid date format. Expected YYYY-MM-DD")

    
#========================================================
#  SAMPLE FILE
#========================================================

from flask import send_from_directory, jsonify, url_for
import os

# Go UP from process/ to backend/
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

SAMPLE_FILES = {
    "gst": os.path.join("download", "sample", "sample_gst.csv"),
    "swt": os.path.join("download", "sample", "sample_swt.csv"),
    "cit": os.path.join("download", "sample", "sample_cit.csv"),
}


@bp.get("/get-sample-files")
@jwt_required()
def get_sample_files():
    return jsonify({
        ft: {
            "url": url_for("segmentation.download_sample", file_type=ft, _external=True),
            "filename": os.path.basename(path)
        }
        for ft, path in SAMPLE_FILES.items()
    })


@bp.get("/download/sample/<file_type>")
@jwt_required()
def download_sample(file_type):

    if file_type not in SAMPLE_FILES:
        return jsonify({"error": "Invalid sample type"}), 400

    relative_path = SAMPLE_FILES[file_type]

    # Go UP TWO levels: process Ã¢â€ â€™ app Ã¢â€ â€™ backend
    BACKEND_ROOT = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../")
    )

    directory = os.path.join(BACKEND_ROOT, os.path.dirname(relative_path))
    filename = os.path.basename(relative_path)

    full_path = os.path.join(directory, filename)

    print("\n================ DEBUG ================")
    print("BACKEND_ROOT:", BACKEND_ROOT)
    print("DIRECTORY:", directory)
    print("FILE:", filename)
    print("FULL PATH:", full_path)
    print("EXISTS:", os.path.exists(full_path))
    print("======================================\n")

    return send_from_directory(directory, filename, as_attachment=True)

# =====================================================================
#  SEGMENTATION HANDLER (EXAMPLE OF NEW FIELD ADDITION)
# =====================================================================
def get_segmentation_rule():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.abspath(
        os.path.join(current_dir, "..", "models", "segmentation_rule.pkl")
    )

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Segmentation rule not found: {model_path}")

    with open(model_path, "rb") as f:
        return pickle.load(f)

import re

def normalize_columns_merge(df):
    def clean(col):
        col = col.strip().lower()
        col = re.sub(r'[^a-z0-9]', '', col)
        return col

    df.columns = [clean(col) for col in df.columns]

    rename_map = {
        "tin": "tin",
        "taxperiodyear": "tax_period_year",
        "taxperiodyear": "tax_period_year",
        "10totalsales": "total_sales_income",
        "totalgrossincome": "total_gross_income"
    }

    df.rename(columns=rename_map, inplace=True)

    return df


def _normalize_tin_series(df: pd.DataFrame, column_name: str = "tin") -> pd.DataFrame:
    """Ensure taxpayer ids are consistently comparable across all joins and updates."""
    if column_name in df.columns:
        df[column_name] = df[column_name].astype(str).str.strip()
    return df


def _validate_mysql_identifier(identifier: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", str(identifier or "")):
        raise RuntimeError(f"Invalid {label}: {identifier}")
    return identifier


def _get_table_text_collation_spec(conn, table_name: str, column_name: str = "tin") -> Tuple[str, str]:
    """
    Resolve the charset/collation used by a destination table's text column so
    temp tables can be aligned with the permanent fraud tables on both MySQL 8
    and MariaDB.
    """
    schema_name = conn.execute(text("SELECT DATABASE()")).scalar()
    if not schema_name:
        raise RuntimeError("Unable to determine active database schema")

    column_spec = conn.execute(
        text(
            """
            SELECT CHARACTER_SET_NAME, COLLATION_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = :schema_name
              AND TABLE_NAME = :table_name
              AND COLUMN_NAME = :column_name
            """
        ),
        {
            "schema_name": schema_name,
            "table_name": table_name,
            "column_name": column_name,
        },
    ).mappings().first()

    if column_spec and column_spec["CHARACTER_SET_NAME"] and column_spec["COLLATION_NAME"]:
        return (
            column_spec["CHARACTER_SET_NAME"],
            column_spec["COLLATION_NAME"],
        )

    table_spec = conn.execute(
        text(
            """
            SELECT
                t.TABLE_COLLATION,
                cca.CHARACTER_SET_NAME
            FROM information_schema.TABLES t
            LEFT JOIN information_schema.COLLATION_CHARACTER_SET_APPLICABILITY cca
                ON cca.COLLATION_NAME = t.TABLE_COLLATION
            WHERE t.TABLE_SCHEMA = :schema_name
              AND t.TABLE_NAME = :table_name
            """
        ),
        {
            "schema_name": schema_name,
            "table_name": table_name,
        },
    ).mappings().first()

    if not table_spec or not table_spec["TABLE_COLLATION"] or not table_spec["CHARACTER_SET_NAME"]:
        raise RuntimeError(f"Unable to determine text collation for {table_name}")

    return table_spec["CHARACTER_SET_NAME"], table_spec["TABLE_COLLATION"]


def _align_temp_segmentation_collation(conn, table_names: List[str]) -> None:
    """
    pandas.to_sql(..., if_exists="replace") recreates temp tables using the
    server/database defaults. On MySQL 8 that can differ from the permanent
    fraud tables and break the bulk join with an illegal collation mix. Align
    the temp table once so the existing indexed join remains unchanged.
    """
    specs = {}
    for table_name in table_names:
        specs[table_name] = _get_table_text_collation_spec(conn, table_name, "tin")

    unique_specs = set(specs.values())
    if len(unique_specs) != 1:
        raise RuntimeError(
            "Segmentation target tables use inconsistent TIN collations: "
            + ", ".join(
                f"{table_name}={charset}/{collation}"
                for table_name, (charset, collation) in specs.items()
            )
        )

    charset_name, collation_name = unique_specs.pop()
    charset_name = _validate_mysql_identifier(charset_name, "character set")
    collation_name = _validate_mysql_identifier(collation_name, "collation")

    conn.execute(
        text(
            f"""
            ALTER TABLE temp_segmentation
            CONVERT TO CHARACTER SET {charset_name}
            COLLATE {collation_name}
            """
        )
    )


# Segmentation thresholds are fixed here to match the current ML rule exactly.
SEGMENTATION_THRESHOLDS = {
    "micro_max": 250000,
    "small_min": 250000,
    "small_max": 5000000,
    "medium_min": 5000000,
    "medium_max": 100000000,
    "large_min": 100000000,
}

HISTORY_VALIDATION_TABLES = {
    "GST": "gst_fraud_justification",
    "SWT": "swt_fraud_justification",
    "CIT": "cit_fraud_justification",
}


def _classify_taxpayer_segment(annual_turnover_3yr_sum):
    """Map a 3-year turnover sum to the required taxpayer segment."""
    if annual_turnover_3yr_sum >= SEGMENTATION_THRESHOLDS["large_min"]:
        return "Large"
    if annual_turnover_3yr_sum >= SEGMENTATION_THRESHOLDS["medium_min"]:
        return "Medium"
    if annual_turnover_3yr_sum >= SEGMENTATION_THRESHOLDS["small_min"]:
        return "Small"
    return "Micro"


def _parse_iso_date(date_str: str, field_name: str):
    try:
        return datetime.strptime(str(date_str), "%Y-%m-%d").date()
    except Exception as exc:
        raise ValueError(f"Invalid {field_name}. Expected YYYY-MM-DD.") from exc


def _get_required_history_years(start_date: str, end_date: str) -> List[int]:
    if not start_date or not end_date:
        raise ValueError("Both start_date and end_date are required.")

    parsed_start = _parse_iso_date(start_date, "start_date")
    parsed_end = _parse_iso_date(end_date, "end_date")

    if parsed_end < parsed_start:
        raise ValueError("end_date must be on or after start_date.")

    assessment_year = parsed_end.year
    return [assessment_year - 2, assessment_year - 1, assessment_year]


def _fetch_available_history_years(engine, table_name: str) -> Set[int]:
    cols = _get_table_columns(engine, table_name)
    if "tax_period_year" not in cols:
        raise RuntimeError(f"{table_name}.tax_period_year column does not exist")

    rows = db.session.execute(
        text(
            f"""
            SELECT DISTINCT tax_period_year
            FROM {table_name}
            WHERE tax_period_year IS NOT NULL
            """
        )
    ).fetchall()

    available_years = set()
    for row in rows:
        raw_year = row[0]
        try:
            available_years.add(int(str(raw_year).strip()))
        except (TypeError, ValueError):
            continue
    return available_years


def _calculate_segmentation_outputs(segmentation_input_df: pd.DataFrame):
    """
    Apply the strict 3-year segmentation rule and build:
    - `final_seg`: eligible taxpayers only, used by the existing DB update flow
    - `eligibility_df`: taxpayer-level eligibility status for output/reporting
    - `stats`: summary counts for the API/dashboard
    """
    working_df = segmentation_input_df.copy()
    working_df = _normalize_tin_series(working_df)
    working_df["tax_period_year"] = pd.to_numeric(working_df["tax_period_year"], errors="coerce")
    working_df["total_gross_income"] = pd.to_numeric(working_df["total_gross_income"], errors="coerce")
    working_df["total_sales_income"] = pd.to_numeric(working_df["total_sales_income"], errors="coerce")

    # A taxpayer-year should contribute one annual figure; use the maximum
    # derived annual turnover within that year if duplicate rows exist.
    working_df["annual_turnover_single_year"] = working_df[
        ["total_gross_income", "total_sales_income"]
    ].max(axis=1).fillna(0)

    working_df = working_df.dropna(subset=["tax_period_year"])
    working_df["year_int"] = working_df["tax_period_year"].astype(int)

    taxpayer_year_df = (
        working_df.groupby(["tin", "year_int"], as_index=False)["annual_turnover_single_year"]
        .max()
    )
    taxpayer_year_df = _normalize_tin_series(taxpayer_year_df)
    print("df tin dtype", working_df["tin"].dtype)

    unique_years = sorted(taxpayer_year_df["year_int"].unique())
    segmentation_results = []

    for year in unique_years:
        required_years = {year - 2, year - 1, year}
        period_data = taxpayer_year_df[taxpayer_year_df["year_int"].isin(required_years)].copy()
        period_data = _normalize_tin_series(period_data)
        if period_data.empty:
            continue

        year_counts = (
            period_data.groupby("tin")["year_int"]
            .nunique()
            .reset_index(name="distinct_years")
        )
        year_counts = _normalize_tin_series(year_counts)
        eligible_tins_year = year_counts[year_counts["distinct_years"] == 3]["tin"]
        if eligible_tins_year.empty:
            continue

        eligible_period = period_data[period_data["tin"].isin(eligible_tins_year)].copy()
        eligible_period = _normalize_tin_series(eligible_period)
        turnover = (
            eligible_period.groupby("tin", as_index=False)["annual_turnover_single_year"]
            .sum()
            .rename(columns={"annual_turnover_single_year": "annual_turnover_3yr_sum"})
        )
        turnover = _normalize_tin_series(turnover)
        turnover["segment"] = turnover["annual_turnover_3yr_sum"].apply(_classify_taxpayer_segment)
        turnover["year_for_segmentation"] = year
        turnover["eligibility_status"] = "Eligible"
        turnover["reason"] = None
        segmentation_results.append(
            turnover[
                [
                    "tin",
                    "segment",
                    "year_for_segmentation",
                    "annual_turnover_3yr_sum",
                    "eligibility_status",
                    "reason",
                ]
            ]
        )

    if segmentation_results:
        final_seg = pd.concat(segmentation_results, ignore_index=True)
        final_seg = _normalize_tin_series(final_seg)
        final_seg = final_seg.sort_values(["tin", "year_for_segmentation"])
        final_seg = final_seg.drop_duplicates("tin", keep="last")
    else:
        final_seg = pd.DataFrame(
            columns=[
                "tin",
                "segment",
                "year_for_segmentation",
                "annual_turnover_3yr_sum",
                "eligibility_status",
                "reason",
            ]
        )
        final_seg = _normalize_tin_series(final_seg)
    print("final_seg tin dtype", final_seg["tin"].dtype)

    all_tins = set(taxpayer_year_df["tin"].astype(str))
    eligible_tins = set(final_seg["tin"].astype(str)) if not final_seg.empty else set()
    missing_tins = sorted(all_tins - eligible_tins)

    ineligible_tins = pd.DataFrame(
        {
            "tin": missing_tins,
            "segment": [None] * len(missing_tins),
            "eligibility_status": ["Ineligible"] * len(missing_tins),
            "reason": ["INSUFFICIENT_3_YEAR_HISTORY"] * len(missing_tins),
        }
    )
    ineligible_tins = _normalize_tin_series(ineligible_tins)

    eligible_summary = (
        final_seg[["tin", "segment", "eligibility_status", "reason"]]
        if not final_seg.empty
        else pd.DataFrame(columns=["tin", "segment", "eligibility_status", "reason"])
    )
    eligible_summary = _normalize_tin_series(eligible_summary)
    eligibility_df = pd.concat([eligible_summary, ineligible_tins], ignore_index=True)
    eligibility_df = _normalize_tin_series(eligibility_df)

    stats = {
        "total_taxpayers": len(all_tins),
        "eligible_taxpayers": len(eligible_tins),
        "ineligible_taxpayers": len(missing_tins),
        "segmented_large": int((final_seg["segment"] == "Large").sum()) if not final_seg.empty else 0,
        "segmented_medium": int((final_seg["segment"] == "Medium").sum()) if not final_seg.empty else 0,
        "segmented_small": int((final_seg["segment"] == "Small").sum()) if not final_seg.empty else 0,
        "segmented_micro": int((final_seg["segment"] == "Micro").sum()) if not final_seg.empty else 0,
        "reason_summary": {
            "INSUFFICIENT_3_YEAR_HISTORY": len(missing_tins)
        },
    }

    return final_seg, eligibility_df, stats



def _ensure_segmentation_job_table(engine) -> None:
    global _SEGMENTATION_JOB_TABLE_READY

    if _SEGMENTATION_JOB_TABLE_READY:
        return

    with _SEGMENTATION_JOB_TABLE_LOCK:
        if _SEGMENTATION_JOB_TABLE_READY:
            return

        inspector = inspect(engine)
        if not inspector.has_table(SEGMENTATION_JOB_TABLE):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"""
                        CREATE TABLE IF NOT EXISTS {SEGMENTATION_JOB_TABLE} (
                            job_id VARCHAR(36) NOT NULL PRIMARY KEY,
                            user_id BIGINT NOT NULL,
                            status VARCHAR(20) NOT NULL,
                            current_step VARCHAR(255) NULL,
                            total_rows BIGINT NOT NULL DEFAULT 0,
                            processed_rows BIGINT NOT NULL DEFAULT 0,
                            percentage DOUBLE NOT NULL DEFAULT 0,
                            request_payload LONGTEXT NULL,
                            merged_file TEXT NULL,
                            output_file TEXT NULL,
                            gst_history_id BIGINT NULL,
                            swt_history_id BIGINT NULL,
                            cit_history_id BIGINT NULL,
                            result_json LONGTEXT NULL,
                            error_message LONGTEXT NULL,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL
                        )
                        """
                    )
                )
                try:
                    conn.execute(
                        text(
                            f"CREATE INDEX idx_{SEGMENTATION_JOB_TABLE}_status "
                            f"ON {SEGMENTATION_JOB_TABLE}(status)"
                        )
                    )
                except Exception:
                    pass

        _SEGMENTATION_JOB_TABLE_READY = True


def _acquire_named_lock(conn, lock_name: str, timeout_seconds: int = 10) -> bool:
    try:
        result = conn.execute(
            text("SELECT GET_LOCK(:lock_name, :timeout_seconds)"),
            {"lock_name": lock_name, "timeout_seconds": int(timeout_seconds)},
        ).scalar()
        return str(result) == "1"
    except Exception:
        return False


def _release_named_lock(conn, lock_name: str) -> None:
    try:
        conn.execute(text("SELECT RELEASE_LOCK(:lock_name)"), {"lock_name": lock_name})
    except Exception:
        pass


def _create_segmentation_job(engine, user_id: int, payload: Dict[str, str]) -> str:
    _ensure_segmentation_job_table(engine)
    job_id = str(uuid.uuid4())
    now = datetime.utcnow()

    with engine.begin() as conn:
        if not _acquire_named_lock(conn, SEGMENTATION_LOCK_NAME, timeout_seconds=10):
            raise RuntimeError("Unable to acquire segmentation job lock. Please try again.")

        try:
            active_job = conn.execute(
                text(
                    f"""
                    SELECT job_id
                    FROM {SEGMENTATION_JOB_TABLE}
                    WHERE status IN ('Queued', 'Running')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
            ).mappings().first()
            if active_job:
                raise RuntimeError("Segmentation is already running. Please wait until it completes.")

            conn.execute(
                text(
                    f"""
                    INSERT INTO {SEGMENTATION_JOB_TABLE} (
                        job_id, user_id, status, current_step, total_rows,
                        processed_rows, percentage, request_payload, created_at, updated_at
                    ) VALUES (
                        :job_id, :user_id, :status, :current_step, :total_rows,
                        :processed_rows, :percentage, :request_payload, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "job_id": job_id,
                    "user_id": int(user_id),
                    "status": "Queued",
                    "current_step": "Queued",
                    "total_rows": 0,
                    "processed_rows": 0,
                    "percentage": 0,
                    "request_payload": json.dumps(payload),
                    "created_at": now,
                    "updated_at": now,
                },
            )
        finally:
            _release_named_lock(conn, SEGMENTATION_LOCK_NAME)

    return job_id


def _update_segmentation_job(engine, job_id: str, **fields) -> None:
    if not fields:
        return

    _ensure_segmentation_job_table(engine)
    fields = dict(fields)
    fields["updated_at"] = datetime.utcnow()

    if "result_json" in fields and fields["result_json"] is not None and not isinstance(fields["result_json"], str):
        fields["result_json"] = json.dumps(fields["result_json"], default=str)
    if "request_payload" in fields and fields["request_payload"] is not None and not isinstance(fields["request_payload"], str):
        fields["request_payload"] = json.dumps(fields["request_payload"], default=str)

    set_clause = ", ".join(f"{column} = :{column}" for column in fields.keys())
    params = {**fields, "job_id": job_id}

    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE {SEGMENTATION_JOB_TABLE} SET {set_clause} WHERE job_id = :job_id"),
            params,
        )


def _get_segmentation_job(engine, job_id: str):
    _ensure_segmentation_job_table(engine)
    with engine.begin() as conn:
        return conn.execute(
            text(f"SELECT * FROM {SEGMENTATION_JOB_TABLE} WHERE job_id = :job_id LIMIT 1"),
            {"job_id": job_id},
        ).mappings().first()



def _merge_gst_cit_internal(user_id: int) -> Dict[str, object]:
    engine = db.engine

    gst_upload = _get_latest_upload_log(engine, user_id, "GST")
    cit_upload = _get_latest_upload_log(engine, user_id, "CIT")
    swt_upload = _get_latest_upload_log(engine, user_id, "SWT")

    if not gst_upload and not cit_upload and not swt_upload:
        raise RuntimeError("GST, SWT, or CIT upload not found for user")

    gst_history_id = int(gst_upload.id) if gst_upload else None
    cit_history_id = int(cit_upload.id) if cit_upload else None
    swt_history_id = int(swt_upload.id) if swt_upload else None

    gst_batch_id = getattr(gst_upload, "upload_batch_id", None) if gst_upload else None
    gst_batch_source = "gst_upload.upload_batch_id"

    print("========== GST MERGE DEBUG ==========")
    print("gst_upload.id =", getattr(gst_upload, "id", None) if gst_upload else None)
    print("gst_upload.user_id =", getattr(gst_upload, "user_id", None) if gst_upload else None)
    print("gst_upload.upload_batch_id =", getattr(gst_upload, "upload_batch_id", None) if gst_upload else None)

    if gst_upload and not gst_batch_id:
        print("GST batch id missing on gst_upload, checking upload_log fallback")
        gst_upload_fallback = _get_upload_log_by_id(engine, user_id, "GST", gst_history_id)
        gst_batch_id = getattr(gst_upload_fallback, "upload_batch_id", None) if gst_upload_fallback else None
        gst_batch_source = "upload_log fallback"
    elif gst_upload:
        print("Using GST batch id from gst_upload.upload_batch_id")

    print(f"GST upload batch id: {gst_batch_id}")
    print(f"GST batch id source: {gst_batch_source}")

    gst_df = pd.DataFrame(columns=["tin", "tax_period_year", "total_sales_income", "upload_batch_id", "taxpayer_name"])
    if gst_upload:
        gst_df = _fetch_fraud_df(
            engine,
            "gst_fraud_justification",
            ["tin", "tax_period_year", "total_sales_income", "upload_batch_id", "taxpayer_name"],
            user_id,
            gst_upload,
            upload_batch_id=gst_batch_id
        )
    print("GST rows:", len(gst_df))
    print("Unique GST TINs:", gst_df["tin"].nunique())

    cit_df = pd.DataFrame(columns=["tin", "tax_period_year", "total_gross_income", "taxpayer"])
    if cit_upload:
        cit_df = _fetch_fraud_df(
            engine,
            "cit_fraud_justification",
            ["tin", "tax_period_year", "total_gross_income", "taxpayer"],
            user_id,
            cit_upload,
        )
    print("CIT rows:", len(cit_df))
    print("Unique CIT TINs:", cit_df["tin"].nunique())

    swt_df = pd.DataFrame(columns=["tin", "tax_period_year", "total_salary_wages_paid", "taxpayer_name"])
    if swt_upload:
        swt_df = _fetch_fraud_df(
            engine,
            "swt_fraud_justification",
            ["tin", "tax_period_year", "total_salary_wages_paid", "taxpayer_name"],
            user_id,
            swt_upload,
        )
    print("SWT rows:", len(swt_df))
    print("Unique SWT TINs:", swt_df["tin"].nunique())

    if gst_df.empty and cit_df.empty and swt_df.empty:
        raise RuntimeError("No GST/SWT/CIT records found for latest upload")

    print("GST DF ROWS:", len(gst_df))
    if not gst_df.empty and "upload_batch_id" in gst_df.columns:
        print("GST batch ids found:", gst_df["upload_batch_id"].dropna().unique()[:10])

    print("GST columns:", gst_df.columns.tolist())
    print("CIT columns:", cit_df.columns.tolist())
    print("SWT columns:", swt_df.columns.tolist())
    if not gst_df.empty:
        print(gst_df[["tin", "tax_period_year"]].head())
    if not cit_df.empty:
        print(cit_df[["tin", "tax_period_year"]].head())
    if not swt_df.empty:
        print(swt_df[["tin", "tax_period_year"]].head())

    gst_df["tin"] = gst_df["tin"].astype(str).str.strip()
    cit_df["tin"] = cit_df["tin"].astype(str).str.strip()
    swt_df["tin"] = swt_df["tin"].astype(str).str.strip()
    gst_df["tax_period_year"] = gst_df["tax_period_year"].astype(str).str.strip()
    cit_df["tax_period_year"] = cit_df["tax_period_year"].astype(str).str.strip()
    swt_df["tax_period_year"] = swt_df["tax_period_year"].astype(str).str.strip()

    gst_tins = set(gst_df["tin"].astype(str))
    cit_tins = set(cit_df["tin"].astype(str))
    swt_tins = set(swt_df["tin"].astype(str))
    combined_tins = gst_tins.union(cit_tins).union(swt_tins)
    common_tins = gst_tins.intersection(cit_tins)

    print("GST taxpayers:", len(gst_tins))
    print("CIT taxpayers:", len(cit_tins))
    print("SWT taxpayers:", len(swt_tins))
    print("Common taxpayers:", len(common_tins))
    print("Combined taxpayers:", len(combined_tins))
    print("Sample common taxpayers:", list(common_tins)[:20])

    print("GST unique tins:", gst_df["tin"].nunique())
    print("CIT unique tins:", cit_df["tin"].nunique())
    print("SWT unique tins:", swt_df["tin"].nunique())
    print("GST rows before merge:", len(gst_df))
    print("CIT rows before merge:", len(cit_df))
    print("SWT rows before merge:", len(swt_df))

    merged_df = _combine_segmentation_source_frames(
        [
            _prepare_segmentation_source_frame(gst_df, "total_sales_income", "total_sales_income", "taxpayer_name"),
            _prepare_segmentation_source_frame(cit_df, "total_gross_income", "total_gross_income", "taxpayer"),
            _prepare_segmentation_source_frame(swt_df, "total_salary_wages_paid", "total_sales_income", "taxpayer_name"),
        ]
    )
    print("Merged rows:", len(merged_df))
    print("Merged unique taxpayers:", merged_df["tin"].nunique())

    output_df = merged_df[["tin", "tax_period_year", "total_gross_income", "total_sales_income", "taxpayer_name"]]

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(
        SEGMENTED_FOLDER,
        f"segmentation_source_merged_{timestamp}.csv"
    )

    output_df.to_csv(output_file, index=False)

    log_file_process(
        gst_history_id,
        output_file,
        f"merge_gst_cit_{gst_history_id}_{cit_history_id}_{swt_history_id}",
        user_id
    )

    return {
        "merged_file": output_file,
        "gst_history_id": gst_history_id,
        "cit_history_id": cit_history_id,
        "swt_history_id": swt_history_id,
    }

def _build_segmentation_response(output_file: str, total_segmented: int, total_time: float, segmentation_stats: Dict[str, object]) -> Dict[str, object]:
    return {
        "status": "success",
        "segmentation_file": output_file,
        "total_segmented": total_segmented,
        "execution_time_seconds": total_time,
        **segmentation_stats,
        "segmentation_summary": {
            "eligible": segmentation_stats["eligible_taxpayers"],
            "ineligible": segmentation_stats["ineligible_taxpayers"],
            "large": segmentation_stats["segmented_large"],
            "medium": segmentation_stats["segmented_medium"],
            "small": segmentation_stats["segmented_small"],
            "micro": segmentation_stats["segmented_micro"],
        },
    }



def _first_non_empty_value(series: pd.Series) -> str:
    for value in series:
        if pd.notna(value):
            text_value = str(value).strip()
            if text_value:
                return text_value
    return ""



def _prepare_segmentation_source_frame(
    source_df: pd.DataFrame,
    value_column: str,
    target_column: str,
    taxpayer_name_column: str = None,
) -> pd.DataFrame:
    base_columns = ["tin", "tax_period_year", "total_gross_income", "total_sales_income", "taxpayer_name"]
    if source_df is None or source_df.empty:
        return pd.DataFrame(columns=base_columns)

    prepared_df = source_df.copy()
    prepared_df = _normalize_tin_series(prepared_df)
    prepared_df["tax_period_year"] = pd.to_numeric(prepared_df["tax_period_year"], errors="coerce")
    prepared_df = prepared_df.dropna(subset=["tin", "tax_period_year"])
    prepared_df["tax_period_year"] = prepared_df["tax_period_year"].astype(int)
    prepared_df["total_gross_income"] = 0.0
    prepared_df["total_sales_income"] = 0.0
    prepared_df[target_column] = pd.to_numeric(prepared_df[value_column], errors="coerce").fillna(0)

    if taxpayer_name_column and taxpayer_name_column in prepared_df.columns:
        prepared_df["taxpayer_name"] = (
            prepared_df[taxpayer_name_column]
            .fillna("")
            .astype(str)
            .str.strip()
        )
    else:
        prepared_df["taxpayer_name"] = ""

    return prepared_df[base_columns]



def _combine_segmentation_source_frames(source_frames: List[pd.DataFrame]) -> pd.DataFrame:
    base_columns = ["tin", "tax_period_year", "total_gross_income", "total_sales_income", "taxpayer_name"]
    non_empty_frames = [frame for frame in source_frames if frame is not None and not frame.empty]
    if not non_empty_frames:
        return pd.DataFrame(columns=base_columns)

    combined_df = pd.concat(non_empty_frames, ignore_index=True)
    combined_df = _normalize_tin_series(combined_df)
    combined_df["tax_period_year"] = pd.to_numeric(combined_df["tax_period_year"], errors="coerce")
    combined_df = combined_df.dropna(subset=["tin", "tax_period_year"])
    combined_df["tax_period_year"] = combined_df["tax_period_year"].astype(int)
    combined_df["total_gross_income"] = pd.to_numeric(combined_df["total_gross_income"], errors="coerce").fillna(0)
    combined_df["total_sales_income"] = pd.to_numeric(combined_df["total_sales_income"], errors="coerce").fillna(0)
    combined_df["taxpayer_name"] = combined_df["taxpayer_name"].fillna("").astype(str).str.strip()

    combined_df = (
        combined_df.groupby(["tin", "tax_period_year"], as_index=False)
        .agg(
            {
                "total_gross_income": "max",
                "total_sales_income": "max",
                "taxpayer_name": _first_non_empty_value,
            }
        )
    )
    return _normalize_tin_series(combined_df)

def _extract_taxpayer_name_lookup(segmentation_input_df: pd.DataFrame) -> pd.DataFrame:
    candidate_columns = [
        "taxpayer_name",
        "taxpayer",
        "taxpayername",
        "maintradename",
        "registered_name",
        "business_name",
        "name",
    ]

    available_name_col = next(
        (column for column in candidate_columns if column in segmentation_input_df.columns),
        None,
    )
    if not available_name_col or "tin" not in segmentation_input_df.columns:
        return pd.DataFrame(columns=["tin", "taxpayer_name"])

    lookup_df = segmentation_input_df[["tin", available_name_col]].copy()
    lookup_df = _normalize_tin_series(lookup_df)
    lookup_df["taxpayer_name"] = (
        lookup_df[available_name_col]
        .fillna("")
        .astype(str)
        .str.strip()
    )
    lookup_df = lookup_df[lookup_df["taxpayer_name"] != ""]
    if lookup_df.empty:
        return pd.DataFrame(columns=["tin", "taxpayer_name"])

    lookup_df = lookup_df.drop_duplicates(subset=["tin"], keep="first")
    return lookup_df[["tin", "taxpayer_name"]]



def _build_segmentation_master_frame(
    final_seg: pd.DataFrame,
    eligibility_df: pd.DataFrame,
    segmentation_input_df: pd.DataFrame,
    job_id: str = None,
) -> pd.DataFrame:
    base_columns = [
        "tin",
        "taxpayer_name",
        "segmentation",
        "eligibility_status",
        "annual_turnover_3yr_sum",
        "assessment_year",
        "last_run_id",
        "created_at",
        "updated_at",
    ]

    if eligibility_df.empty:
        return pd.DataFrame(columns=base_columns)

    master_df = eligibility_df.copy()
    master_df = _normalize_tin_series(master_df)
    final_seg_details = (
        final_seg[["tin", "year_for_segmentation", "annual_turnover_3yr_sum"]].copy()
        if not final_seg.empty
        else pd.DataFrame(columns=["tin", "year_for_segmentation", "annual_turnover_3yr_sum"])
    )
    final_seg_details = _normalize_tin_series(final_seg_details)
    master_df = master_df.merge(final_seg_details, on="tin", how="left")

    latest_year_lookup = pd.DataFrame(columns=["tin", "latest_assessment_year"])
    if not segmentation_input_df.empty and {"tin", "tax_period_year"}.issubset(segmentation_input_df.columns):
        latest_year_lookup = segmentation_input_df[["tin", "tax_period_year"]].copy()
        latest_year_lookup = _normalize_tin_series(latest_year_lookup)
        latest_year_lookup["tax_period_year"] = pd.to_numeric(
            latest_year_lookup["tax_period_year"], errors="coerce"
        )
        latest_year_lookup = latest_year_lookup.dropna(subset=["tax_period_year"])
        latest_year_lookup["tax_period_year"] = latest_year_lookup["tax_period_year"].astype(int)
        latest_year_lookup = (
            latest_year_lookup.groupby("tin", as_index=False)["tax_period_year"]
            .max()
            .rename(columns={"tax_period_year": "latest_assessment_year"})
        )
        latest_year_lookup = _normalize_tin_series(latest_year_lookup)

    if not latest_year_lookup.empty:
        master_df = master_df.merge(latest_year_lookup, on="tin", how="left")
    else:
        master_df["latest_assessment_year"] = pd.NA

    taxpayer_name_lookup = _extract_taxpayer_name_lookup(segmentation_input_df)
    if not taxpayer_name_lookup.empty:
        master_df = master_df.merge(taxpayer_name_lookup, on="tin", how="left")
    else:
        master_df["taxpayer_name"] = ""

    now_utc = datetime.utcnow()
    master_df["taxpayer_name"] = master_df["taxpayer_name"].fillna("").astype(str).str.strip()
    master_df["segmentation"] = master_df["segment"]
    master_df["annual_turnover_3yr_sum"] = pd.to_numeric(
        master_df["annual_turnover_3yr_sum"], errors="coerce"
    ).fillna(0)
    master_df["assessment_year"] = master_df["year_for_segmentation"].where(
        master_df["year_for_segmentation"].notna(),
        master_df["latest_assessment_year"],
    )
    master_df["assessment_year"] = pd.to_numeric(master_df["assessment_year"], errors="coerce")
    ineligible_mask = master_df["eligibility_status"].astype(str).str.strip().eq("Ineligible")
    master_df.loc[ineligible_mask, "segmentation"] = None
    master_df.loc[ineligible_mask, "annual_turnover_3yr_sum"] = 0
    master_df["last_run_id"] = job_id
    master_df["created_at"] = now_utc
    master_df["updated_at"] = now_utc

    master_df = master_df.sort_values(["tin", "assessment_year"], na_position="last")
    master_df = master_df.drop_duplicates(subset=["tin"], keep="last")
    return master_df[base_columns]



def _execute_segmentation_updates(
    engine,
    final_seg: pd.DataFrame,
    eligibility_df: pd.DataFrame,
    user_id: int,
    gst_upload,
    cit_upload,
    swt_upload,
    segmentation_input_df: pd.DataFrame = None,
    job_id: str = None,
) -> int:
    segmentation_input_df = (
        segmentation_input_df
        if segmentation_input_df is not None
        else pd.DataFrame(columns=["tin"])
    )
    eligibility_df = (
        eligibility_df
        if eligibility_df is not None
        else pd.DataFrame(columns=["tin", "segment", "eligibility_status", "reason"])
    )
    master_df = _build_segmentation_master_frame(
        final_seg,
        eligibility_df,
        segmentation_input_df,
        job_id=job_id,
    )
    total_rows = len(master_df)

    if job_id:
        _update_segmentation_job(
            engine,
            job_id,
            status="Running",
            current_step="Refreshing segmentation master",
            total_rows=total_rows,
            processed_rows=0,
            percentage=0,
        )

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE taxpayer_segmentation_master"))

    if job_id:
        _update_segmentation_job(
            engine,
            job_id,
            status="Running",
            current_step="Loading segmentation master rows",
            total_rows=total_rows,
            processed_rows=0,
            percentage=50 if total_rows else 100,
        )

    if not master_df.empty:
        master_df.to_sql(
            "taxpayer_segmentation_master",
            con=engine,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=10000,
        )

    if job_id:
        _update_segmentation_job(
            engine,
            job_id,
            status="Running",
            current_step="Segmentation master refreshed",
            total_rows=total_rows,
            processed_rows=total_rows,
            percentage=100,
        )

    return total_rows



def _run_overall_segmentation_internal(user_id: int, data: Dict[str, object], job_id: str = None) -> Dict[str, object]:
    merged_file = data.get("merged_file")

    # Path traversal validation (SEC-007)
    if merged_file:
        resolved = os.path.abspath(merged_file)
        allowed = False
        for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, SEGMENTED_FOLDER]:
            abs_folder = os.path.abspath(folder)
            if resolved.startswith(abs_folder + os.sep) or resolved == abs_folder:
                allowed = True
                break
        if not allowed:
            raise ValueError("Path traversal or unauthorized file path detected")

    gst_history_id = data.get("gst_history_id")
    swt_history_id = data.get("swt_history_id")
    cit_history_id = data.get("cit_history_id")

    start_total = time.time()
    rule = get_segmentation_rule()

    if job_id:
        _update_segmentation_job(db.engine, job_id, status="Running", current_step="Loading merged data", percentage=5)

    df = pd.read_csv(merged_file)
    df = _normalize_tin_series(df)
    print("Input rows to segmentation:", len(df))
    print("Input taxpayers to segmentation:", df["tin"].nunique() if "tin" in df.columns else "tin column not found yet")

    df = df.rename(columns={
        rule['columns']['taxpayer_id']: 'tin',
        rule['columns']['year']: 'tax_period_year',
        rule['columns']['cit_gross_income']: 'total_gross_income',
        rule['columns']['gst_net_sales']: 'total_sales_income'
    })
    df = _normalize_tin_series(df)

    if job_id:
        _update_segmentation_job(db.engine, job_id, status="Running", current_step="Calculating segmentation", percentage=15)

    final_seg, eligibility_df, segmentation_stats = _calculate_segmentation_outputs(df)
    final_seg = _normalize_tin_series(final_seg)
    eligibility_df = _normalize_tin_series(eligibility_df)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(SEGMENTED_FOLDER, f"segmentation_overall_{timestamp}.csv")

    df_with_segment = df.merge(
        eligibility_df[["tin", "segment", "eligibility_status", "reason"]],
        on='tin',
        how='left'
    )
    df_with_segment = _normalize_tin_series(df_with_segment)
    missing_eligibility_mask = df_with_segment['eligibility_status'].isna()
    df_with_segment.loc[missing_eligibility_mask, 'eligibility_status'] = 'Ineligible'
    df_with_segment.loc[missing_eligibility_mask, 'reason'] = 'INSUFFICIENT_3_YEAR_HISTORY'
    df_with_segment.to_csv(output_file, index=False)

    log_file_process(gst_history_id, output_file, "overall_segmentation", user_id)
    log_file_process(swt_history_id, output_file, "overall_segmentation", user_id)
    log_file_process(cit_history_id, output_file, "overall_segmentation", user_id)

    engine = db.engine
    if job_id:
        _update_segmentation_job(engine, job_id, status="Running", current_step="Preparing segmentation master", percentage=30)

    _execute_segmentation_updates(
        engine,
        final_seg,
        eligibility_df,
        user_id,
        None,
        None,
        None,
        segmentation_input_df=df,
        job_id=job_id,
    )

    total_time = round(time.time() - start_total, 2)
    return _build_segmentation_response(output_file, len(final_seg), total_time, segmentation_stats)


def _background_segmentation_worker(app, job_id: str) -> None:
    with app.app_context():
        engine = db.engine
        try:
            job = _get_segmentation_job(engine, job_id)
            if not job:
                return

            payload = json.loads(job["request_payload"] or "{}")
            user_id = int(job["user_id"])

            _update_segmentation_job(
                engine,
                job_id,
                status="Running",
                current_step="Merging GST and CIT data",
                percentage=0,
                error_message=None,
            )

            merge_result = _merge_gst_cit_internal(user_id)
            payload.update(merge_result)
            _update_segmentation_job(
                engine,
                job_id,
                request_payload=payload,
                merged_file=merge_result["merged_file"],
                gst_history_id=merge_result["gst_history_id"],
                swt_history_id=merge_result["swt_history_id"],
                cit_history_id=merge_result["cit_history_id"],
                current_step="Merged GST and CIT data",
                percentage=10,
            )

            result = _run_overall_segmentation_internal(user_id, payload, job_id=job_id)
            _update_segmentation_job(
                engine,
                job_id,
                status="Completed",
                current_step="Completed",
                percentage=100,
                output_file=result.get("segmentation_file"),
                result_json=result,
                error_message=None,
            )
        except Exception as exc:
            current_app.logger.exception("Segmentation background job failed for job_id=%s", job_id)
            try:
                _update_segmentation_job(
                    engine,
                    job_id,
                    status="Failed",
                    current_step="Failed",
                    error_message=str(exc),
                )
            except Exception:
                current_app.logger.exception("Unable to update failed segmentation job state for job_id=%s", job_id)
        finally:
            db.session.remove()

@bp.route("/get-merge-gst-cit", methods=["GET", "POST"])
@jwt_required()
def merge_gst_cit():
    user_id = int(get_jwt_identity())

    try:
        result = _merge_gst_cit_internal(user_id)
        return jsonify({"status": "success", **result}), 200
    except RuntimeError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() or "no gst/cit records" in message.lower() else 400
        return jsonify({"error": message}), status_code
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@bp.post("/validate-history")
@jwt_required()
def validate_history():
    data = request.get_json() or {}
    tax_type = str(data.get("tax_type") or "").strip().upper()
    start_date = data.get("start_date")
    end_date = data.get("end_date")

    if tax_type not in HISTORY_VALIDATION_TABLES:
        return jsonify({
            "status": "error",
            "valid": False,
            "message": "Invalid tax type. Expected GST, SWT, or CIT."
        }), 400

    try:
        required_years = _get_required_history_years(start_date, end_date)
    except ValueError as exc:
        return jsonify({
            "status": "error",
            "valid": False,
            "message": str(exc)
        }), 400

    table_name = HISTORY_VALIDATION_TABLES[tax_type]

    try:
        engine = db.engine
        available_years = _fetch_available_history_years(engine, table_name)
        missing_years = [year for year in required_years if year not in available_years]

        if missing_years:
            return jsonify({
                "status": "error",
                "valid": False,
                "message": "Past 3 years data not available.",
                "missing_years": missing_years,
            }), 400

        return jsonify({
            "status": "success",
            "valid": True,
        }), 200
    except Exception:
        current_app.logger.exception(
            "Historical data validation failed for tax_type=%s, table=%s",
            tax_type,
            table_name,
        )
        return jsonify({
            "status": "error",
            "valid": False,
            "message": "Unable to validate historical data."
        }), 500


@bp.post("/start")
@jwt_required()
def start_segmentation_job():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    start_date = data.get("start_date")
    end_date = data.get("end_date")

    if start_date or end_date:
        if not start_date or not end_date:
            return jsonify({
                "status": "error",
                "message": "Invalid date input. Please use proper format."
            }), 400
        try:
            _ = extract_year(start_date)
            _ = extract_year(end_date)
        except ValueError:
            return jsonify({
                "status": "error",
                "message": "Invalid date input. Please use proper format."
            }), 400

    engine = db.engine
    job_id = None
    try:
        job_id = _create_segmentation_job(
            engine,
            user_id,
            {"start_date": start_date, "end_date": end_date},
        )
        worker = threading.Thread(
            target=_background_segmentation_worker,
            args=(current_app._get_current_object(), job_id),
            daemon=True,
            name=f"segmentation-job-{job_id}",
        )
        worker.start()
        return jsonify({"job_id": job_id, "status": "Queued"}), 202
    except RuntimeError as exc:
        message = str(exc)
        status_code = 409 if "already running" in message.lower() else 400
        return jsonify({"error": message, "status": "Failed"}), status_code
    except Exception as e:
        if job_id:
            try:
                _update_segmentation_job(engine, job_id, status="Failed", current_step="Failed", error_message=str(e))
            except Exception:
                traceback.print_exc()
        traceback.print_exc()
        return jsonify({"error": str(e), "status": "Failed"}), 500


@bp.get("/status/<job_id>")
@jwt_required()
def segmentation_job_status(job_id):
    user_id = int(get_jwt_identity())
    engine = db.engine

    try:
        job = _get_segmentation_job(engine, job_id)
        if not job or int(job["user_id"]) != user_id:
            return jsonify({"error": "Segmentation job not found."}), 404

        response = {
            "job_id": job["job_id"],
            "status": job["status"],
            "current_step": job["current_step"],
            "total_rows": int(job["total_rows"] or 0),
            "processed_rows": int(job["processed_rows"] or 0),
            "percentage": float(job["percentage"] or 0),
            "merged_file": job["merged_file"],
            "segmentation_file": job["output_file"],
            "gst_history_id": job["gst_history_id"],
            "swt_history_id": job["swt_history_id"],
            "cit_history_id": job["cit_history_id"],
            "error": job["error_message"],
        }

        if job["result_json"]:
            try:
                result_payload = json.loads(job["result_json"])
                response["result"] = result_payload
                for key, value in result_payload.items():
                    if key != "status":
                        response[key] = value
            except Exception:
                response["result"] = job["result_json"]

        return jsonify(response), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@bp.post("/get-overall-segmentation")
@jwt_required()
def overall_segmentation():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    merged_file = data.get("merged_file")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    gst_history_id = data.get("gst_history_id")
    cit_history_id = data.get("cit_history_id")

    # Path traversal validation (SEC-007)
    if merged_file:
        resolved = os.path.abspath(merged_file)
        allowed = False
        for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, SEGMENTED_FOLDER]:
            abs_folder = os.path.abspath(folder)
            if resolved.startswith(abs_folder + os.sep) or resolved == abs_folder:
                allowed = True
                break
        if not allowed:
            return jsonify({"error": "Path traversal or unauthorized file path detected"}), 400

    if not merged_file or not os.path.exists(merged_file):
        return jsonify({"error": "Merged file not found"}), 400

    if start_date or end_date:
        if not start_date or not end_date:
            return jsonify({
                "status": "error",
                "message": "Invalid date input. Please use proper format."
            }), 400
        try:
            _ = extract_year(start_date)
            _ = extract_year(end_date)
        except ValueError:
            return jsonify({
                "status": "error",
                "message": "Invalid date input. Please use proper format."
            }), 400

    if gst_history_id is None or cit_history_id is None:
        return jsonify({"error": "Missing gst_history_id or cit_history_id"}), 400

    try:
        result = _run_overall_segmentation_internal(user_id, data)
        return jsonify(result), 200
    except RuntimeError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        return jsonify({"error": message}), status_code
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500



