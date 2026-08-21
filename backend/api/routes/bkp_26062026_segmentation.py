import os
import time
import json
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
def get_sample_files():
    return jsonify({
        ft: {
            "url": url_for("segmentation.download_sample", file_type=ft, _external=True),
            "filename": os.path.basename(path)
        }
        for ft, path in SAMPLE_FILES.items()
    })


@bp.get("/download/sample/<file_type>")
def download_sample(file_type):

    if file_type not in SAMPLE_FILES:
        return jsonify({"error": "Invalid sample type"}), 400

    relative_path = SAMPLE_FILES[file_type]

    # Go UP TWO levels: process → app → backend
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

@bp.route("/get-merge-gst-cit", methods=["GET", "POST"])
@jwt_required()
def merge_gst_cit():
    user_id = int(get_jwt_identity())

    try:
        engine = db.engine

        # -------------------------------------------------
        # 1. Get latest GST/CIT/SWT uploads (upload_log is source of truth)
        # -------------------------------------------------
        gst_upload = _get_latest_upload_log(engine, user_id, "GST")
        cit_upload = _get_latest_upload_log(engine, user_id, "CIT")
        swt_upload = _get_latest_upload_log(engine, user_id, "SWT")

        if not gst_upload or not cit_upload:
            return jsonify({
                "error": "GST or CIT upload not found for user"
            }), 404

        # Keep response contract: these IDs are now upload_log IDs
        gst_history_id = int(gst_upload.id)
        cit_history_id = int(cit_upload.id)
        swt_history_id = int(swt_upload.id) if swt_upload else None

        # -------------------------------------------------
        # 2. Fetch records directly from DB (never load from disk)
        # -------------------------------------------------
        gst_batch_id = getattr(gst_upload, "upload_batch_id", None)
        gst_batch_source = "gst_upload.upload_batch_id"

        print("========== GST MERGE DEBUG ==========")
        print("gst_upload.id =", getattr(gst_upload, "id", None))
        print("gst_upload.user_id =", getattr(gst_upload, "user_id", None))
        print("gst_upload.upload_batch_id =", getattr(gst_upload, "upload_batch_id", None))

        if not gst_batch_id:
            print("GST batch id missing on gst_upload, checking upload_log fallback")
            gst_upload_fallback = _get_upload_log_by_id(engine, user_id, "GST", gst_history_id)
            gst_batch_id = getattr(gst_upload_fallback, "upload_batch_id", None) if gst_upload_fallback else None
            gst_batch_source = "upload_log fallback"
        else:
            print("Using GST batch id from gst_upload.upload_batch_id")

        print(f"GST upload batch id: {gst_batch_id}")
        print(f"GST batch id source: {gst_batch_source}")

        gst_df = _fetch_fraud_df(
            engine,
            "gst_fraud_justification",
            ["tin", "tax_period_year", "total_sales_income", "upload_batch_id"],
            user_id,
            gst_upload,
            upload_batch_id=gst_batch_id
        )
        print("GST rows:", len(gst_df))
        print("Unique GST TINs:", gst_df["tin"].nunique())
        cit_df = _fetch_fraud_df(
            engine,
            "cit_fraud_justification",
            ["tin", "tax_period_year", "total_gross_income"],
            user_id,
            cit_upload,
        )
        print("CIT rows:", len(cit_df))
        print("Unique CIT TINs:", cit_df["tin"].nunique())

        if gst_df.empty or cit_df.empty:
            return jsonify({"error": "No GST/CIT records found for latest upload"}), 404

        print("GST DF ROWS:", len(gst_df))
        if not gst_df.empty and "upload_batch_id" in gst_df.columns:
            print(
                "GST batch ids found:",
                gst_df["upload_batch_id"].dropna().unique()[:10]
            )

        print("GST columns:", gst_df.columns.tolist())
        print("CIT columns:", cit_df.columns.tolist())
        print(gst_df[["tin", "tax_period_year"]].head())
        print(cit_df[["tin", "tax_period_year"]].head())

        gst_df["tin"] = gst_df["tin"].astype(str).str.strip()
        cit_df["tin"] = cit_df["tin"].astype(str).str.strip()
        gst_df["tax_period_year"] = gst_df["tax_period_year"].astype(str).str.strip()
        cit_df["tax_period_year"] = cit_df["tax_period_year"].astype(str).str.strip()

        gst_tins = set(gst_df["tin"].astype(str))
        cit_tins = set(cit_df["tin"].astype(str))
        common_tins = gst_tins.intersection(cit_tins)

        print("GST taxpayers:", len(gst_tins))
        print("CIT taxpayers:", len(cit_tins))
        print("Common taxpayers:", len(common_tins))
        print("Sample common taxpayers:", list(common_tins)[:20])

        print("GST unique tins:", gst_df["tin"].nunique())
        print("CIT unique tins:", cit_df["tin"].nunique())
        print("GST rows before merge:", len(gst_df))
        print("CIT rows before merge:", len(cit_df))

        # -------------------------------------------------
        # 3. Merge
        # -------------------------------------------------
        merged_df = pd.merge(
            cit_df,
            gst_df,
            on=["tin", "tax_period_year"],
            how="left"
        )
        print("Merged rows:", len(merged_df))
        print("Merged unique taxpayers:", merged_df["tin"].nunique())

        output_df = merged_df[
            ["tin", "tax_period_year", "total_gross_income", "total_sales_income"]
        ]

        # -------------------------------------------------
        # 4. Save output
        # -------------------------------------------------
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(
            SEGMENTED_FOLDER,
            f"gst_cit_merged_{timestamp}.csv"
        )

        output_df.to_csv(output_file, index=False)

        # -------------------------------------------------
        # 5. Log file process (best-effort)
        # -------------------------------------------------
        log_file_process(
            gst_history_id,
            output_file,
            f"merge_gst_cit_{gst_history_id}_{cit_history_id}_{swt_history_id}",
            user_id
        )

        return jsonify({
            "status": "success",
            "merged_file": output_file,
            "gst_history_id": gst_history_id,
            "cit_history_id": cit_history_id,
            "swt_history_id": swt_history_id
        }), 200

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


@bp.post("/get-overall-segmentation")
@jwt_required()
def overall_segmentation():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    merged_file = data.get("merged_file")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    gst_history_id = data.get("gst_history_id")
    swt_history_id = data.get("swt_history_id")
    cit_history_id = data.get("cit_history_id")

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
        return jsonify({
            "error": "Missing gst_history_id or cit_history_id"
        }), 400

    try:
        start_total = time.time()
        # -------------------------------------------------
        # 1. Load segmentation rule
        # -------------------------------------------------
        rule = get_segmentation_rule()

        df = pd.read_csv(merged_file)
        df = _normalize_tin_series(df)
        print("Input rows to segmentation:", len(df))
        print("Input taxpayers to segmentation:", df["tin"].nunique() if "tin" in df.columns else "tin column not found yet")

        # Rename columns
        df = df.rename(columns={
            rule['columns']['taxpayer_id']: 'tin',
            rule['columns']['year']: 'tax_period_year',
            rule['columns']['cit_gross_income']: 'total_gross_income',
            rule['columns']['gst_net_sales']: 'total_sales_income'
        })
        df = _normalize_tin_series(df)
        print("Input rows to segmentation:", len(df))
        print("Input taxpayers to segmentation:", df["tin"].nunique())
        print("df tin dtype", df["tin"].dtype)

        # -------------------------------------------------
        # 2. Strict 3-year eligibility + segmentation logic
        # -------------------------------------------------
        final_seg, eligibility_df, segmentation_stats = _calculate_segmentation_outputs(df)
        final_seg = _normalize_tin_series(final_seg)
        eligibility_df = _normalize_tin_series(eligibility_df)

        print("Total taxpayers loaded:", len(df))
        print("Distinct TIN count:", segmentation_stats["total_taxpayers"])
        print("Eligible taxpayers:", segmentation_stats["eligible_taxpayers"])
        print("Ineligible taxpayers:", segmentation_stats["ineligible_taxpayers"])
        print(
            "Reason: INSUFFICIENT_3_YEAR_HISTORY =",
            segmentation_stats["reason_summary"]["INSUFFICIENT_3_YEAR_HISTORY"]
        )

        print("final_seg rows:", len(final_seg))
        print("final_seg taxpayers:", final_seg["tin"].nunique() if not final_seg.empty else 0)
        if not final_seg.empty:
            print(
                final_seg[["tin", "segment"]]
                .head(50)
                .to_string()
            )

        merged_tins = set(df["tin"].astype(str))
        final_tins = set(final_seg["tin"].astype(str)) if not final_seg.empty else set()
        missing = merged_tins - final_tins

        print("Dropped taxpayers:", len(missing))
        print("Sample dropped taxpayers:", list(missing)[:50])

        print("Merged rows:", len(df))
        print("Rows to update:", len(final_seg))
        if not final_seg.empty:
            print("Segmentation updates sample:")
            print(final_seg.head(10).to_string(index=False))

         # -------------------------------------------------
        # Save Output File
        # -------------------------------------------------
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(
            SEGMENTED_FOLDER,
            f"segmentation_overall_{timestamp}.csv"
        )

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

        # -------------------------------------------------
        # Log Process 
        # -------------------------------------------------
        gst_history_id = data.get("gst_history_id")
        swt_history_id = data.get("swt_history_id")
        cit_history_id = data.get("cit_history_id")
        
        log_file_process(
            gst_history_id,
            output_file,
            "overall_segmentation",
            user_id
        )
        
        log_file_process(
            swt_history_id,
            output_file,
            "overall_segmentation",
            user_id
        )

        log_file_process(
            cit_history_id,
            output_file,
            "overall_segmentation",
            user_id
        )


        # -------------------------------------------------
        # 6️⃣ HIGH PERFORMANCE BULK UPDATE 
        # -------------------------------------------------
        engine = db.engine

        if final_seg.empty:
            total_time = round(time.time() - start_total, 2)
            return jsonify({
                "status": "success",
                "segmentation_file": output_file,
                "total_segmented": 0,
                "execution_time_seconds": total_time,
                **segmentation_stats,
                "segmentation_summary": {
                    "eligible": segmentation_stats["eligible_taxpayers"],
                    "ineligible": segmentation_stats["ineligible_taxpayers"],
                    "large": segmentation_stats["segmented_large"],
                    "medium": segmentation_stats["segmented_medium"],
                    "small": segmentation_stats["segmented_small"],
                    "micro": segmentation_stats["segmented_micro"],
                }
            }), 200

        # Validate upload ownership and fetch uploaded_at for safe scoping
        gst_upload = _get_upload_log_by_id(engine, user_id, "GST", gst_history_id)
        cit_upload = _get_upload_log_by_id(engine, user_id, "CIT", cit_history_id)
        swt_upload = (
            _get_upload_log_by_id(engine, user_id, "SWT", swt_history_id)
            if swt_history_id is not None
            else None
        )

        if not gst_upload or not cit_upload:
            return jsonify({"error": "GST or CIT upload not found for user"}), 404

        # Upload to temp table
        final_seg = _normalize_tin_series(final_seg)
        print("final_seg tin dtype", final_seg["tin"].dtype)
        final_seg.to_sql(
            "temp_segmentation",
            con=engine,
            if_exists="replace",
            index=False,
            method="multi",
            chunksize=10000
        )

        def _bulk_update_segmentation(conn, table_name: str, upload_row):
            cols = _get_table_columns(engine, table_name)
            if "segmentation" not in cols:
                raise RuntimeError(f"{table_name}.segmentation column does not exist")
            if "tin" not in cols:
                raise RuntimeError(f"{table_name}.tin column does not exist")

            where_clauses, params = _build_user_upload_filter(engine, table_name, "t", user_id, upload_row)
            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
            upload_batch_id = getattr(upload_row, "upload_batch_id", None)

            print(f"Preparing bulk update for {table_name}")
            print(f"Upload row id: {getattr(upload_row, 'id', None)}")
            print(f"Upload batch id: {upload_batch_id}")
            print(f"Update WHERE: {where_sql}")

            if not final_seg.empty:
                sample_updates = final_seg.head(10).to_dict(orient="records")
                for row in sample_updates:
                    print("TIN:", row.get("tin"))
                    print("SEGMENT:", row.get("segment"))
                    print("BATCH:", upload_batch_id)

                    tin_params = {"tin": row.get("tin")}
                    total_by_tin = conn.execute(
                        text(f"SELECT COUNT(*) FROM {table_name} WHERE tin = :tin"),
                        tin_params,
                    ).scalar()
                    print(f"Rows for tin={row.get('tin')}: {total_by_tin}")

                    if upload_batch_id and "upload_batch_id" in cols:
                        total_by_tin_batch = conn.execute(
                            text(
                                f"SELECT COUNT(*) FROM {table_name} "
                                f"WHERE tin = :tin AND upload_batch_id = :upload_batch_id"
                            ),
                            {**tin_params, "upload_batch_id": upload_batch_id},
                        ).scalar()
                        print(
                            f"Rows for tin={row.get('tin')} and upload_batch_id={upload_batch_id}: "
                            f"{total_by_tin_batch}"
                        )

            dialect = engine.dialect.name
            if dialect in ("mysql", "mariadb"):
                sql = f"""
                    UPDATE {table_name} t
                    JOIN temp_segmentation ts
                        ON t.tin = ts.tin
                    SET t.segmentation = ts.segment
                    WHERE {where_sql}
                """
                print(f"Update SQL: {sql}")
                result = conn.execute(text(sql), params)
                print("Rows affected:", result.rowcount)
            else:
                sql = f"""
                    UPDATE {table_name} t
                    SET t.segmentation = (
                        SELECT ts.segment FROM temp_segmentation ts WHERE ts.tin = t.tin
                    )
                    WHERE ({where_sql})
                      AND EXISTS (SELECT 1 FROM temp_segmentation ts WHERE ts.tin = t.tin)
                """
                print(f"Update SQL: {sql}")
                result = conn.execute(text(sql), params)
                print("Rows affected:", result.rowcount)

        with engine.begin() as conn:
            # Temp table index for join performance (best-effort)
            try:
                conn.execute(text("CREATE INDEX idx_temp_tin ON temp_segmentation(tin)"))
            except Exception:
                pass

            _bulk_update_segmentation(conn, "gst_fraud_justification", gst_upload)
            _bulk_update_segmentation(conn, "cit_fraud_justification", cit_upload)
            if swt_upload is not None:
                _bulk_update_segmentation(conn, "swt_fraud_justification", swt_upload)

            try:
                gst_seg_counts = conn.execute(
                    text(
                        """
                        SELECT
                            COUNT(*) AS total_rows,
                            SUM(CASE WHEN segmentation IS NOT NULL THEN 1 ELSE 0 END) AS segmented_rows
                        FROM gst_fraud_justification
                        """
                    )
                ).mappings().first()
                print(f"GST segmentation counts after update: {dict(gst_seg_counts) if gst_seg_counts else None}")
            except Exception as e:
                print(f"Warning: GST post-update validation failed: {e}")

            try:
                conn.execute(text("DROP TABLE temp_segmentation"))
            except Exception:
                pass

        total_time = round(time.time() - start_total, 2)

        return jsonify({
            "status": "success",
            "segmentation_file": output_file,
            "total_segmented": len(final_seg),
            "execution_time_seconds": total_time,
            **segmentation_stats,
            "segmentation_summary": {
                "eligible": segmentation_stats["eligible_taxpayers"],
                "ineligible": segmentation_stats["ineligible_taxpayers"],
                "large": segmentation_stats["segmented_large"],
                "medium": segmentation_stats["segmented_medium"],
                "small": segmentation_stats["segmented_small"],
                "micro": segmentation_stats["segmented_micro"],
            }
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
