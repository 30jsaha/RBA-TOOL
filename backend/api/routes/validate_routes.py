# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  api/routes/validate_routes.py
#
#  POST /api/gst/validate
#  POST /api/cit/validate
#  POST /api/swt/validate
#
#  Pre-flight file validation â€” runs BEFORE the full pipeline.
#  Accepts an uploaded file, checks column presence and basic
#  data quality, returns pass/fail + issue list instantly.
#  Does NOT write to DB, does NOT run the pipeline.
#
#  Column matching is FUZZY â€” uploaded files don't need to use
#  the exact canonical names; close matches are accepted and
#  reported as informational mappings in the response.
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

import io
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from difflib import SequenceMatcher
from datetime import datetime
import pandas as pd
from flask import Blueprint, request, jsonify

from api.routes.gst_routes import run_gst_preprocessing
from api.routes.swt_routes import run_swt_preprocessing
from utils.auth_helper import get_authenticated_user_id
from utils.file_security import write_encrypted_output_file
from utils.upload_security import UploadSecurityError, validate_upload_file

validate_bp = Blueprint('validate', __name__)


def _store_encrypted_csv_bytes(output_dir: str, logical_name: str, payload: bytes) -> None:
    fd, temp_path = tempfile.mkstemp(prefix="validate_", suffix=Path(logical_name).suffix or ".csv")
    os.close(fd)
    try:
        with open(temp_path, "wb") as handle:
            handle.write(payload)
        write_encrypted_output_file(temp_path, output_dir, logical_name)
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass


def _store_encrypted_dataframe(output_dir: str, logical_name: str, dataframe: pd.DataFrame) -> None:
    payload = dataframe.to_csv(index=False).encode("utf-8")
    _store_encrypted_csv_bytes(output_dir, logical_name, payload)


def _save_validated_upload_copy(file_storage, target_dir: str, *, allowed_extensions) -> tuple[str, str]:
    safe_name = validate_upload_file(file_storage, allowed_extensions=allowed_extensions)
    os.makedirs(target_dir, exist_ok=True)

    saved_path = os.path.join(target_dir, safe_name)
    try:
        file_storage.stream.seek(0)
    except Exception:
        pass
    file_storage.save(saved_path)
    try:
        file_storage.stream.seek(0)
    except Exception:
        pass

    return saved_path, safe_name


def _logical_output_name(path_value):
    try:
        return os.path.basename(str(path_value or "").replace('\\', '/')) or None
    except Exception:
        return None


def _normalize_field_name_for_schema(field_name: object) -> str:
    try:
        return str(field_name or "").strip()
    except Exception:
        return ""


def _sanitize_field_name(field_name: object):
    """
    Normalizes field names before storing in `upload_conflicts` and before dynamic
    schema-based matching queries.

    - removes apostrophes
    - replaces spaces with underscores
    - collapses duplicate underscores
    - trims leading/trailing underscores
    """
    if field_name is None:
        return field_name
    try:
        s = str(field_name).strip()
    except Exception:
        return field_name
    if not s:
        return s
    s = s.replace("'", "")
    s = s.replace(" ", "_")
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_")


def _is_ignored_conflict_field(field_name: object) -> bool:
    """
    Exclude import-generated columns like `Unnamed: 0` / `unnamed:_0`.
    (Used for conflict insertion and exports; CIT-only requirement initially, but safe globally.)
    """
    try:
        n = str(field_name or "").strip().lower().replace(" ", "")
    except Exception:
        return False
    return n in ("unnamed:_0", "unnamed:0", "unnamed_0")


def _resolve_source_meta_for_conflict(
    *,
    engine,
    source_table: str,
    assessment_column: str,
    tin: object,
    tax_period_year: object,
    assessment_number: object,
    field_name: object,
    previous_value: object,
):
    """
    Resolve (source_record_id, upload_batch_id, taxpayer_name) for a conflict row by looking up the
    matched fraud-justification record.

    Security: validates `field_name` exists in the table schema before using it in SQL.
    Returns (None, None, None) on any failure.
    """
    try:
        if engine is None:
            return (None, None, None)
        st = (source_table or "").strip()
        if not st:
            return (None, None, None)

        fn = _sanitize_field_name(_normalize_field_name_for_schema(field_name))
        if not fn or _is_ignored_conflict_field(fn):
            return (None, None, None)

        assess_col = (assessment_column or "").strip()
        if not assess_col:
            return (None, None, None)

        tin_s = "" if tin is None else str(tin).strip()
        if tin_s.endswith(".0") and tin_s[:-2].isdigit():
            tin_s = tin_s[:-2]

        try:
            yr_i = int(float(tax_period_year)) if tax_period_year is not None else None
        except Exception:
            yr_i = None

        assess_s = "" if assessment_number is None else str(assessment_number).strip()
        if assess_s.endswith(".0") and assess_s[:-2].isdigit():
            assess_s = assess_s[:-2]

        try:
            prev_f = float(previous_value) if previous_value is not None else None
        except Exception:
            try:
                prev_f = float(str(previous_value).strip())
            except Exception:
                prev_f = None

        from sqlalchemy import text

        def _normalize(v):
            try:
                if v is None or (isinstance(v, str) and v.strip() == ""):
                    v = 0
                return round(float(v), 2)
            except Exception:
                try:
                    return str(v).strip()
                except Exception:
                    return ""

        with engine.connect() as conn:
            cols_res = conn.execute(
                text(
                    "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
                ),
                {"t": st},
            )
            cols = set((r[0] or "").lower() for r in cols_res.fetchall())

            if fn.lower() not in cols:
                return (None, None, None)
            if assess_col.lower() not in cols:
                return (None, None, None)
            if "tin" not in cols or "tax_period_year" not in cols:
                return (None, None, None)

            sel_cols = ["id"]
            if "upload_batch_id" in cols:
                sel_cols.append("upload_batch_id")
            # Pull a consistent taxpayer name (GST/SWT use `taxpayer_name`, CIT often uses `taxpayer`)
            if "taxpayer_name" in cols:
                sel_cols.append("taxpayer_name")
            elif "taxpayer" in cols:
                sel_cols.append("taxpayer")
            # Pull the dynamic field value for python-side comparison (do NOT compare in SQL).
            sel_cols.append(f"`{fn}` AS _db_val")

            # Safe identifiers: validated against information_schema, then backtick-quoted.
            assess_q = f"`{assess_col}`"
            st_q = f"`{st}`"

            q = text(
                f"SELECT {', '.join(sel_cols)} "
                f"FROM {st_q} "
                f"WHERE tin = :tin "
                f"  AND tax_period_year = :yr "
                f"  AND {assess_q} = :assess "
                f"ORDER BY id DESC "
                f"LIMIT 5"
            )

            rows = conn.execute(
                q,
                {"tin": tin_s, "yr": yr_i, "assess": assess_s},
            ).fetchall()

            if not rows:
                return (None, None, None)

            want = _normalize(prev_f)
            has_batch = "upload_batch_id" in cols
            has_name = ("taxpayer_name" in cols) or ("taxpayer" in cols)
            for row in rows:
                try:
                    # row shape:
                    # - when upload_batch_id exists: (id, upload_batch_id, _db_val)
                    # - otherwise: (id, _db_val)
                    db_val = row[-1] if len(row) >= 2 else None
                    if _normalize(db_val) == want:
                        src_id = row[0] if len(row) > 0 else None
                        batch_id = row[1] if (has_batch and len(row) >= 3) else None
                        taxpayer_name = None
                        try:
                            # When present, name is the last non-_db_val selected col.
                            if has_name:
                                taxpayer_name = row[-2]
                        except Exception:
                            taxpayer_name = None
                        return (src_id, batch_id, taxpayer_name)
                except Exception:
                    continue

            return (None, None, None)

    except Exception:
        return (None, None, None)

def _financial_diff_fields_for_tax(tax: str):
    """
    Map each module to the two primary "financial difference" fields we expose in the
    downloadable CSV.

    NOTE: We keep this small and explicit to avoid unintended columns.
    """
    t = (tax or "").strip().lower()
    if t == "swt":
        return ("total_salary_wages_paid", "total_swt_tax_deducted")
    if t == "cit":
        return ("salaries_or_wages", "total_tax_payable")
    if t == "gst":
        return ("gst_taxable_sales", "gst_payable")
    return (None, None)


def _reason_for_financial_difference(has_salary_diff: bool, has_tax_diff: bool, diff_amount: float):
    """
    Create a readable reason for the financial-difference CSV.

    Optional tolerance can be configured via env var `FINANCIAL_DIFF_TOLERANCE`.
    When set (>0) and the absolute difference exceeds the tolerance, we use the
    "threshold" reason as requested.
    """
    try:
        tol = float(os.getenv("FINANCIAL_DIFF_TOLERANCE", "0") or 0)
    except Exception:
        tol = 0.0

    if tol > 0 and float(diff_amount or 0) > tol:
        return "Financial difference exceeds allowed threshold"

    if has_salary_diff and has_tax_diff:
        return "Salary and tax mismatch"
    if has_salary_diff:
        return "Salary mismatch between uploaded and system values"
    if has_tax_diff:
        return "Tax mismatch between uploaded and system values"
    return "Financial difference"


def _generate_financial_difference_csv(tax: str, output_dir: str, conflict_tins, tin_to_name=None):
    """
    Generates `{tax}_financial_difference_YYYYMMDD_HHMMSS.csv` in the module's
    `final_output` folder, using rows already inserted into `upload_conflicts`.

    Returns: (file_name, file_full_path) or (None, None).
    """
    try:
        if not output_dir or not conflict_tins:
            return (None, None)

        salary_field, tax_field = _financial_diff_fields_for_tax(tax)
        if not salary_field or not tax_field:
            return (None, None)

        user_id = get_authenticated_user_id()
        tax_type_db = (tax or "").strip().upper()

        def _norm_tin(v) -> str:
            try:
                s0 = "" if v is None else str(v).strip()
            except Exception:
                s0 = ""
            if not s0:
                return ""
            s_lower = s0.lower()
            if s_lower in ("nan", "none", "null", "<na>"):
                return ""
            # Common pandas artifact: `500000161.0`
            if s0.endswith(".0"):
                head = s0[:-2]
                if head.isdigit():
                    return head
            # Scientific notation or float-ish values
            try:
                if any(ch in s0 for ch in (".", "e", "E")):
                    f = float(s0)
                    if f.is_integer():
                        return str(int(f))
            except Exception:
                pass
            # Digits only (keep)
            if s0.isdigit():
                return s0
            # Fallback: keep raw
            return s0

        # Normalize tins to strings for SQL IN matching.
        tins = []
        for t in conflict_tins or []:
            s = _norm_tin(t)
            if s and s.lower() not in ("nan", "none", "null", "<na>"):
                tins.append(s)
        tins = list(dict.fromkeys(tins))
        if not tins:
            return (None, None)

        from sqlalchemy import text, bindparam
        from config.db_config import get_mysql_engine

        engine = None
        try:
            engine = get_mysql_engine()
            with engine.connect() as conn:
                # Detect optional columns (some DBs may not have `user_id` or `taxpayer_name`)
                cols_res = conn.execute(text(
                    "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'upload_conflicts'"
                ))
                cols = set((r[0] or "").lower() for r in cols_res.fetchall())

                has_user_id = "user_id" in cols
                has_taxpayer_name = "taxpayer_name" in cols

                select_taxpayer = ", taxpayer_name" if has_taxpayer_name else ""
                where_user = " AND user_id = :user_id " if (has_user_id and user_id is not None) else ""

                q = text(
                    "SELECT tin"
                    f"{select_taxpayer}"
                    ", field_name, previous_value, current_value "
                    "FROM upload_conflicts "
                    "WHERE tax_type = :tax_type "
                    "  AND status = 0 "
                    f"{where_user}"
                    "  AND tin IN :tins"
                ).bindparams(bindparam("tins", expanding=True))

                params = {"tax_type": tax_type_db, "tins": tins}
                if has_user_id and user_id is not None:
                    params["user_id"] = user_id

                rows = conn.execute(q, params).fetchall()
        finally:
            try:
                if engine is not None:
                    engine.dispose()
            except Exception:
                pass

        if not rows:
            return (None, None)

        # Build per-TIN aggregation of the two financial fields.
        by_tin = {}
        for r in rows:
            try:
                # Row shape can be (tin, taxpayer_name?, field_name, previous_value, current_value)
                tin = str(r[0] if len(r) > 0 else "").strip()
                idx = 1
                taxpayer_name = None
                # Heuristic: if second column is not `field_name`, treat it as taxpayer_name
                # (works with both query shapes built above).
                if len(r) == 5:
                    taxpayer_name = r[1]
                    idx = 2
                field_name = r[idx] if len(r) > idx else None
                prev_val = r[idx + 1] if len(r) > (idx + 1) else None
                curr_val = r[idx + 2] if len(r) > (idx + 2) else None
            except Exception:
                continue

            if not tin:
                continue

            d = by_tin.setdefault(tin, {"taxpayer_name": None, "fields": {}})
            if taxpayer_name and not d.get("taxpayer_name"):
                d["taxpayer_name"] = str(taxpayer_name)

            fn = str(field_name or "").strip()
            if not fn:
                continue

            d["fields"][fn.lower()] = {"previous_value": prev_val, "current_value": curr_val}

        def _to_float(v):
            try:
                if v is None:
                    return 0.0
                return float(v)
            except Exception:
                try:
                    return float(str(v).strip())
                except Exception:
                    return 0.0

        out_rows = []
        for tin, meta in by_tin.items():
            fields = meta.get("fields") or {}
            sal = fields.get(salary_field.lower())
            taxv = fields.get(tax_field.lower())

            uploaded_salary = _to_float((sal or {}).get("current_value"))
            system_salary = _to_float((sal or {}).get("previous_value"))
            uploaded_tax = _to_float((taxv or {}).get("current_value"))
            system_tax = _to_float((taxv or {}).get("previous_value"))

            has_salary_diff = sal is not None and uploaded_salary != system_salary
            has_tax_diff = taxv is not None and uploaded_tax != system_tax
            if not (has_salary_diff or has_tax_diff):
                continue

            diff_amount = (abs(uploaded_salary - system_salary) if has_salary_diff else 0.0) + (
                abs(uploaded_tax - system_tax) if has_tax_diff else 0.0
            )
            diff_type = "both" if (has_salary_diff and has_tax_diff) else ("salary" if has_salary_diff else "tax")

            employee_name = ""
            try:
                employee_name = str(meta.get("taxpayer_name") or "").strip()
            except Exception:
                employee_name = ""
            if not employee_name and isinstance(tin_to_name, dict):
                try:
                    employee_name = str(tin_to_name.get(tin) or "").strip()
                except Exception:
                    employee_name = ""

            out_rows.append({
                "tin": tin,
                "employee_name": employee_name,
                "uploaded_salary": uploaded_salary if has_salary_diff or sal is not None else None,
                "system_salary": system_salary if has_salary_diff or sal is not None else None,
                "uploaded_tax": uploaded_tax if has_tax_diff or taxv is not None else None,
                "system_tax": system_tax if has_tax_diff or taxv is not None else None,
                "difference_amount": diff_amount,
                "difference_type": diff_type,
                "reason": _reason_for_financial_difference(has_salary_diff, has_tax_diff, diff_amount),
            })

        if not out_rows:
            return (None, None)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{tax.lower()}_financial_difference_{ts}.csv"
        full_path = os.path.abspath(os.path.join(output_dir, fname))
        os.makedirs(output_dir, exist_ok=True)
        pd.DataFrame(out_rows, columns=[
            "tin",
            "employee_name",
            "uploaded_salary",
            "system_salary",
            "uploaded_tax",
            "system_tax",
            "difference_amount",
            "difference_type",
            "reason",
        ]).to_csv(full_path, index=False)

        return (fname, full_path)

    except Exception:
        # Never block validation on CSV generation failures.
        return (None, None)


def _count_financial_difference_records(tax: str, conflict_tins) -> int:
    """
    Counts distinct TINs in `upload_conflicts` (status=0) that have differences in the
    two primary financial fields for the given tax type.

    Falls back to 0 on any error.
    """
    try:
        salary_field, tax_field = _financial_diff_fields_for_tax(tax)
        if not salary_field or not tax_field:
            return 0

        def _norm(v):
            try:
                s = "" if v is None else str(v).strip()
            except Exception:
                s = ""
            if not s:
                return ""
            if s.endswith(".0") and s[:-2].isdigit():
                return s[:-2]
            try:
                if any(ch in s for ch in (".", "e", "E")):
                    f = float(s)
                    if f.is_integer():
                        return str(int(f))
            except Exception:
                pass
            return s

        tins = [_norm(t) for t in (conflict_tins or [])]
        tins = [t for t in tins if t and t.lower() not in ("nan", "none", "null", "<na>")]
        tins = list(dict.fromkeys(tins))
        if not tins:
            return 0

        from sqlalchemy import text, bindparam
        from config.db_config import get_mysql_engine

        user_id = get_authenticated_user_id()
        tax_type_db = (tax or "").strip().upper()

        engine = None
        try:
            engine = get_mysql_engine()
            with engine.connect() as conn:
                cols_res = conn.execute(text(
                    "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'upload_conflicts'"
                ))
                cols = set((r[0] or "").lower() for r in cols_res.fetchall())
                has_user_id = "user_id" in cols

                where_user = " AND user_id = :user_id " if (has_user_id and user_id is not None) else ""
                q = text(
                    "SELECT COUNT(DISTINCT tin) AS cnt "
                    "FROM upload_conflicts "
                    "WHERE tax_type = :tax_type "
                    "  AND status = 0 "
                    f"{where_user}"
                    "  AND tin IN :tins "
                    "  AND LOWER(field_name) IN :fields"
                ).bindparams(
                    bindparam("tins", expanding=True),
                    bindparam("fields", expanding=True),
                )

                params = {"tax_type": tax_type_db, "tins": tins, "fields": [salary_field.lower(), tax_field.lower()]}
                if has_user_id and user_id is not None:
                    params["user_id"] = user_id
                row = conn.execute(q, params).fetchone()
                return int(row[0] or 0) if row else 0
        finally:
            try:
                if engine is not None:
                    engine.dispose()
            except Exception:
                pass
    except Exception:
        return 0


def _export_upload_conflicts_csv_from_db(tax_type: str, conflict_tins, output_path: str) -> bool:
    """
    Export rows from `upload_conflicts` into a CSV with column names matching the DB.

    Scope is limited to:
      - `tax_type = <tax_type>`
      - `status = 0`
      - `user_id = current_user_id` (only when column exists and user_id is not None)
      - `tin IN (conflict_tins)` (prevents dumping entire table)

    Returns True when a file is written.
    """
    try:
        if not output_path:
            return False

        def _norm_tin(v) -> str:
            try:
                s = "" if v is None else str(v).strip()
            except Exception:
                s = ""
            if not s:
                return ""
            if s.endswith(".0") and s[:-2].isdigit():
                return s[:-2]
            return s

        tins = [_norm_tin(t) for t in (conflict_tins or [])]
        tins = [t for t in tins if t and t.lower() not in ("nan", "none", "null", "<na>")]
        tins = list(dict.fromkeys(tins))
        if not tins:
            return False

        from sqlalchemy import text, bindparam
        from config.db_config import get_mysql_engine

        engine = None
        rows = []
        try:
            engine = get_mysql_engine()
            with engine.connect() as conn:
                cols_res = conn.execute(text(
                    "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'upload_conflicts' "
                    "ORDER BY ORDINAL_POSITION"
                ))
                conf_cols = [row[0] for row in cols_res]
                conf_cols_l = set(str(c or "").lower() for c in conf_cols)

                current_user_id = get_authenticated_user_id()
                has_user_id = "user_id" in conf_cols_l

                base_select = [
                    "tax_type",
                    "tin",
                    "taxpayer_name",
                    "tax_period_year",
                    "tax_period_month",
                    "assessment_number",
                    "field_name",
                    "previous_value",
                    "current_value",
                    "status",
                    "user_id",
                    "id",
                ]
                select_cols = [c for c in base_select if c in conf_cols]
                if not select_cols:
                    select_cols = [c for c in conf_cols if c in base_select]

                where_user = " AND user_id = :user_id " if (has_user_id and current_user_id is not None) else ""
                q = text(
                    f"SELECT {', '.join(select_cols)} "
                    "FROM upload_conflicts "
                    "WHERE tax_type = :tax_type "
                    "  AND status = 0 "
                    f"{where_user}"
                    "  AND tin IN :tins "
                    "ORDER BY id DESC"
                ).bindparams(bindparam("tins", expanding=True))

                params = {"tax_type": str(tax_type or "").strip().upper(), "tins": tins}
                if has_user_id and current_user_id is not None:
                    params["user_id"] = current_user_id

                res = conn.execute(q, params)
                rows = [dict(r._mapping) for r in res.fetchall()]
        finally:
            try:
                if engine is not None:
                    engine.dispose()
            except Exception:
                pass

        if not rows:
            return False

        df_db = pd.DataFrame(rows)
        try:
            df_db["difference"] = (
                pd.to_numeric(df_db.get("current_value"), errors="coerce").fillna(0.0)
                - pd.to_numeric(df_db.get("previous_value"), errors="coerce").fillna(0.0)
            )
        except Exception:
            df_db["difference"] = None

        def _mk_reason(fn):
            s = str(fn or "").lower()
            has_sal = ("salary" in s) or ("wage" in s)
            has_tax = ("tax" in s)
            if has_sal and has_tax:
                return "Salary and tax mismatch"
            if has_sal:
                return "Salary mismatch between uploaded and system values"
            if has_tax:
                return "Tax mismatch between uploaded and system values"
            return "Financial difference"

        try:
            df_db["reason"] = df_db.get("field_name").apply(_mk_reason)
        except Exception:
            df_db["reason"] = "Financial difference"

        out_cols = [
            "tax_type",
            "tin",
            "taxpayer_name",
            "tax_period_year",
            "tax_period_month",
            "assessment_number",
            "field_name",
            "previous_value",
            "current_value",
            "difference",
            "reason",
        ]
        for c in out_cols:
            if c not in df_db.columns:
                df_db[c] = None

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        df_db[out_cols].to_csv(output_path, index=False)
        return os.path.exists(output_path)

    except Exception:
        return False


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Shared helpers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load_uploaded_file(file_storage):
    """Read a werkzeug FileStorage into a DataFrame."""
    filename = file_storage.filename.lower()
    data = file_storage.read()
    if filename.endswith('.parquet'):
        return pd.read_parquet(io.BytesIO(data))
    elif filename.endswith('.csv'):
        return pd.read_csv(io.BytesIO(data))
    else:
        raise ValueError('Only .csv or .parquet files are accepted')


def _normalise_cols(df):
    """Return a lowercase-stripped set of column names."""
    return {c.strip().lower() for c in df.columns}


def _add(issues, issue_type, detail, count=None):
    entry = {'type': issue_type, 'detail': detail}
    if count is not None:
        entry['count'] = int(count)
    issues.append(entry)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Fuzzy column matching
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# Minimum similarity score (0â€“1) to accept a fuzzy match.
# 0.70 catches abbreviations and minor typos without false positives.
FUZZY_THRESHOLD = 0.70


def _tokenise(name: str) -> set:
    """
    Split a column name into a bag of lowercase tokens.
    'total_gross_salary' â†’ {'total', 'gross', 'salary'}
    'TotalGrossSalary'   â†’ {'total', 'gross', 'salary'}
    """
    # Insert underscore before uppercase letters (CamelCase â†’ snake_case)
    name = re.sub(r'(?<=[a-z])(?=[A-Z])', '_', name)
    # Replace any non-alphanumeric run with a single space
    name = re.sub(r'[^a-z0-9]+', ' ', name.lower())
    return set(name.split())


def _similarity(canonical: str, actual: str) -> float:
    """
    Combined similarity: sequence ratio + Jaccard token overlap.
    Returns a value in [0, 1].
    """
    seq_score = SequenceMatcher(None, canonical, actual).ratio()
    t_can = _tokenise(canonical)
    t_act = _tokenise(actual)
    if t_can and t_act:
        union = t_can | t_act
        jaccard = len(t_can & t_act) / len(union)
    else:
        jaccard = 0.0
    # Weight token overlap slightly higher â€” catches reordered words
    return 0.4 * seq_score + 0.6 * jaccard


def _fuzzy_map_columns(required_cols: list, df_cols: list, threshold: float = FUZZY_THRESHOLD):
    """
    Match each required canonical column name to the best actual column.

    Returns
    -------
    mapped   : dict  {canonical_name: actual_col_name}   â€” successful matches
    missing  : list  [canonical_name]                    â€” no match found
    mappings : list  of info dicts for the response      â€” all fuzzy remaps
    """
    actual_normalised = {c.strip().lower(): c for c in df_cols}  # norm â†’ original
    used = set()        # avoid mapping two canonical cols to the same actual col
    mapped = {}
    missing = []
    mappings = []       # informational: what was remapped

    for canon in required_cols:
        canon_norm = canon.strip().lower()

        # 1. Exact match (case-insensitive)
        if canon_norm in actual_normalised:
            actual = actual_normalised[canon_norm]
            mapped[canon_norm] = actual
            used.add(actual)
            continue

        # 2. Fuzzy match
        best_score = 0.0
        best_actual = None
        for norm, original in actual_normalised.items():
            if original in used:
                continue
            score = _similarity(canon_norm, norm)
            if score > best_score:
                best_score = score
                best_actual = original

        if best_score >= threshold and best_actual is not None:
            mapped[canon_norm] = best_actual
            used.add(best_actual)
            if best_actual.strip().lower() != canon_norm:
                mappings.append({
                    'type': 'column_remapped',
                    'canonical': canon,
                    'found_as': best_actual,
                    'score': round(best_score, 3),
                    'detail': (
                        f'Column "{best_actual}" was matched to '
                        f'expected column "{canon}" '
                        f'(similarity {best_score:.0%})'
                    ),
                })
        else:
            missing.append(canon_norm)

    return mapped, missing, mappings


def _remap_df(df: pd.DataFrame, mapped: dict) -> pd.DataFrame:
    """
    Return a copy of df with columns renamed to their canonical names.
    Only the columns present in `mapped` are renamed; others are untouched.
    """
    rename = {v: k for k, v in mapped.items()}   # actual â†’ canonical
    return df.rename(columns=rename)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  CIT Validation
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

CIT_REQUIRED_COLUMNS = [
    'gross_sales_cash_or_credit', 'total_gross_income', 'cost_of_goods_sold',
    'property_or_equipment', 'leasehold_improvements', 'management_fees_foreign',
    'total_operating_expenses', 'royalties_foreign', 'advertising_and_promotion',
    'bad_debts_written_off', 'accounts_receivable_trade', 'consultancy_fees',
    'legal_expenses', 'repairs_and_maintenance', 'travel_and_accommodation',
    'other_gross_income', 'total_current_assets', 'prior_year_losses_utilised',
    'interest_expense_foreign', 'interest_income', 'management_fees_png',
    'royalties_png', 'dividend_income', 'interest_expense_png', 'loans_from_directors',
    'other_loans', 'total_non_deductible_items', 'total_deductible_items_ex', 'gross_tax',
]


def _validate_cit(df):
    issues = []

    mapped, missing, mappings = _fuzzy_map_columns(CIT_REQUIRED_COLUMNS, list(df.columns))
    issues.extend(mappings)

    for col in missing:
        _add(issues, 'missing_column', col)

    if missing:          # column errors are fatal â€” skip row checks
        return issues

    df = _remap_df(df, mapped)
    df.columns = [c.strip().lower() for c in df.columns]

    # 2 â€” TIN validation
    if 'tin' in df.columns:
        tin = pd.to_numeric(df['tin'], errors='coerce')
        null_count = tin.isna().sum()
        if null_count:
            _add(issues, 'tin_null', 'TIN is null or non-numeric', null_count)

        tin_str = tin.dropna().astype('Int64').astype(str)

        wrong_len = (tin_str.str.len() != 9).sum()
        if wrong_len:
            _add(issues, 'tin_wrong_length', 'TIN must be exactly 9 digits', wrong_len)

        starts_zero = tin_str.str.startswith('0').sum()
        if starts_zero:
            _add(issues, 'tin_starts_with_zero', 'TIN starts with 0', starts_zero)

        all_same = tin_str.apply(lambda s: len(set(s)) == 1).sum()
        if all_same:
            _add(issues, 'tin_all_same_digits', 'TIN contains all identical digits', all_same)

        def _is_sequential(s):
            if len(s) != 9:
                return False
            digits = [int(d) for d in s]
            diffs  = [digits[i + 1] - digits[i] for i in range(len(digits) - 1)]
            return all(d == diffs[0] for d in diffs) and abs(diffs[0]) == 1

        sequential = tin_str.apply(_is_sequential).sum()
        if sequential:
            _add(issues, 'tin_sequential', 'TIN is a sequential number pattern', sequential)

    # 3 â€” Assessment number
    if 'assessment_no' in df.columns:
        a_str = df['assessment_no'].astype(str)
        non_num = (~a_str.str.match(r'^\d+$')).sum()
        if non_num:
            _add(issues, 'assessment_non_numeric',
                 'assessment_no contains non-numeric values', non_num)

        dupes = df.duplicated(subset=['assessment_no'], keep=False).sum()
        if dupes:
            _add(issues, 'assessment_duplicate',
                 'Duplicate assessment_no values found', dupes)

    # 4 â€” Tax account number
    if 'tax_account_no' in df.columns:
        non_num = (~df['tax_account_no'].astype(str).str.match(r'^\d+$')).sum()
        if non_num:
            _add(issues, 'tax_account_non_numeric',
                 'tax_account_no contains non-numeric values', non_num)

    # 5 â€” Gross sales
    if 'gross_sales_cash_or_credit' in df.columns:
        neg = (pd.to_numeric(df['gross_sales_cash_or_credit'],
                              errors='coerce').fillna(0) < 0).sum()
        if neg:
            _add(issues, 'gross_sales_negative',
                 'gross_sales_cash_or_credit contains negative values', neg)

    return issues


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  GST Validation
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _validate_gst(df):
    # GST validation is executed via gst_routes.run_gst_preprocessing().
    # This function is intentionally unused.
    return []


    # Non-critical missing: warn
    non_critical_missing = [c for c in missing if c not in GST_CRITICAL_COLUMNS]
    for col in non_critical_missing:
        _add(issues, 'missing_expected_column',
             f'"{col}" is expected but not found â€” '
             f'column standardizer may map it automatically')

    if critical_missing:
        return issues

    df = _remap_df(df, mapped)
    df.columns = [c.strip().lower() for c in df.columns]

    # 3 â€” TIN checks
    tin_raw = df['tin'].astype(str).str.strip()
    null_count = tin_raw.isin(['', 'nan', 'none', 'null']).sum()
    if null_count:
        _add(issues, 'tin_null', 'TIN is empty or null', null_count)

    tin_digits = tin_raw[~tin_raw.isin(['', 'nan', 'none', 'null'])]
    wrong_len = (tin_digits.str.replace(r'\D', '', regex=True).str.len() != 9).sum()
    if wrong_len:
        _add(issues, 'tin_wrong_length', 'TIN does not have exactly 9 digits', wrong_len)

    # 4 â€” Numeric range checks
    for col in ['output_tax_payable', 'input_tax_credits', 'net_gst_payable',
                'total_sales', 'taxable_sales']:
        if col in df.columns:
            neg = (pd.to_numeric(df[col], errors='coerce').fillna(0) < 0).sum()
            if neg:
                _add(issues, 'negative_value', f'"{col}" contains negative values', neg)

    # 5 â€” Duplicate TIN + period
    if 'tax_period_year' in df.columns and 'tax_period_month' in df.columns:
        dupes = df.duplicated(
            subset=['tin', 'tax_period_year', 'tax_period_month'], keep=False
        ).sum()
        if dupes:
            _add(issues, 'duplicate_tin_period',
                 'Duplicate records found for the same TIN + year + month', dupes)

    return issues


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  SWT Validation
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _validate_swt(df):
    return []

    mapped, missing, mappings = _fuzzy_map_columns(SWT_EXPECTED_COLUMNS, list(df.columns))
    issues.extend(mappings)

    critical_missing = [c for c in SWT_CRITICAL_COLUMNS if c not in mapped]
    for col in critical_missing:
        _add(issues, 'missing_critical_column',
             f'"{col}" is required but could not be matched. '
             f'Available columns: {list(df.columns)[:10]}')

    non_critical_missing = [c for c in missing if c not in SWT_CRITICAL_COLUMNS]
    for col in non_critical_missing:
        _add(issues, 'missing_expected_column',
             f'"{col}" is expected but not found â€” '
             f'column standardizer may map it automatically')

    if critical_missing:
        return issues

    df = _remap_df(df, mapped)
    df.columns = [c.strip().lower() for c in df.columns]

    # 3 â€” TIN checks
    tin_raw = df['tin'].astype(str).str.strip()
    null_count = tin_raw.isin(['', 'nan', 'none', 'null']).sum()
    if null_count:
        _add(issues, 'tin_null', 'TIN is empty or null', null_count)

    tin_digits = tin_raw[~tin_raw.isin(['', 'nan', 'none', 'null'])]
    cleaned    = tin_digits.str.replace(r'\D', '', regex=True)

    wrong_len = (cleaned.str.len() != 9).sum()
    if wrong_len:
        _add(issues, 'tin_wrong_length', 'TIN does not have exactly 9 digits', wrong_len)

    starts_zero = cleaned.str.startswith('0').sum()
    if starts_zero:
        _add(issues, 'tin_starts_with_zero', 'TIN starts with 0', starts_zero)

    all_same = cleaned.apply(lambda s: len(s) > 0 and len(set(s)) == 1).sum()
    if all_same:
        _add(issues, 'tin_all_same_digits', 'TIN contains all identical digits', all_same)

    # 4 â€” SWT amount checks
    if 'total_swt_withheld' in df.columns:
        neg = (pd.to_numeric(df['total_swt_withheld'], errors='coerce').fillna(0) < 0).sum()
        if neg:
            _add(issues, 'negative_value',
                 '"total_swt_withheld" contains negative values', neg)

    if 'total_gross_salary' in df.columns:
        neg = (pd.to_numeric(df['total_gross_salary'], errors='coerce').fillna(0) < 0).sum()
        if neg:
            _add(issues, 'negative_value',
                 '"total_gross_salary" contains negative values', neg)

    # 5 â€” SWT rate sanity: withheld should not exceed gross salary
    if 'total_swt_withheld' in df.columns and 'total_gross_salary' in df.columns:
        withheld = pd.to_numeric(df['total_swt_withheld'], errors='coerce').fillna(0)
        salary   = pd.to_numeric(df['total_gross_salary'],   errors='coerce').fillna(0)
        exceeds  = ((withheld > salary) & (salary > 0)).sum()
        if exceeds:
            _add(issues, 'swt_exceeds_salary',
                 'total_swt_withheld exceeds total_gross_salary (rate > 100%)', exceeds)

    # 6 â€” Duplicate TIN + year
    if 'tax_period_year' in df.columns:
        dupes = df.duplicated(subset=['tin', 'tax_period_year'], keep=False).sum()
        if dupes:
            _add(issues, 'duplicate_tin_year',
                 'Duplicate records found for the same TIN + year', dupes)

    return issues


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Shared route logic
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _run_gst_real_validation():
    return _run_gst_validation()


VALIDATORS = {
    'gst': _validate_gst,
    'cit': _validate_cit,
}


def _run_gst_validation():
    output_dir_override = None
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'valid': False, 'error': 'No file uploaded'}), 400

    gst_data_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', 'gst', 'data')
    )
    os.makedirs(gst_data_dir, exist_ok=True)

    try:
        saved_path, _saved_name = validate_upload_file(file, gst_data_dir, tax_type='GST')
    except UploadSecurityError as exc:
        return jsonify({'valid': False, 'error': str(exc)}), 400

    try:
        result = run_gst_preprocessing(saved_path, make_timestamped_copies=True)
        if not result.get('ok'):
            errors = result.get('errors') or []
            if not errors:
                errors = [{
                    'row': '',
                    'tin': '',
                    'column': '',
                    'reason': result.get('error', 'Validation failed'),
                }]
            return jsonify({'valid': False, 'error_count': len(errors), 'errors': errors}), 200

        # Success (even if invalid_records > 0): valid=true as long as preprocessing ran.
        # In your validate endpoint
        payload = {
            'valid': True,
            'total_records': result.get('total_records', 0),
            'valid_records': result.get('valid_records', 0),
            'invalid_records': result.get('invalid_records', 0),
            'tin_invalid_count': result.get('tin_invalid_count', 0),
            'db_duplicates_count': result.get('db_duplicates_count', 0),
            'db_financial_differences_count': result.get('db_financial_differences_count', 0),
            'db_financial_difference_fields_count': result.get('db_financial_difference_fields_count', 0),
            'validated_file': result.get('validated_file', 'gst_validated.csv'),
            'validated_file_path': _logical_output_name(result.get('validated_file_full_path') or result.get('validated_file')),
            'removed_data_file': result.get('removed_data_file', 'gst_removed_data.csv'),
            'removed_data_file_path': _logical_output_name(result.get('removed_file_full_path') or result.get('removed_data_file')),
            'output_dir': None,
            'errors': result.get('errors', []),
        }

        # Generate financial difference CSV (only when financial differences exist)
        payload['financial_difference_count'] = int(
            payload.get('db_financial_difference_fields_count')
            or payload.get('db_financial_differences_count')
            or 0
        )
        payload['financial_difference_file'] = None
        payload['financial_difference_file_path'] = None
        try:
            if payload['financial_difference_count'] > 0:
                conflict_tins = []
                for err in result.get('errors') or []:
                    reason = str((err or {}).get('reason') or '').lower()
                    if (
                        'financial differences found against gst_fraud_justification' in reason
                        or 'financial values differ from existing gst_fraud_justification record' in reason
                    ):
                        tin = str((err or {}).get('tin') or '').strip()
                        if tin:
                            conflict_tins.append(tin)
                conflict_tins = list(dict.fromkeys(conflict_tins))

                if conflict_tins:
                    ts2 = datetime.now().strftime('%Y%m%d_%H%M%S')
                    logical_name = f'gst_financial_difference_{ts2}.csv'
                    fd, temp_csv_path = tempfile.mkstemp(prefix='gst_financial_difference_', suffix='.csv')
                    os.close(fd)
                    try:
                        wrote_csv = _export_upload_conflicts_csv_from_db(
                            "GST",
                            conflict_tins,
                            temp_csv_path,
                        )
                        if wrote_csv and os.path.exists(temp_csv_path) and os.path.getsize(temp_csv_path) > 0:
                            write_encrypted_output_file(temp_csv_path, result.get('output_dir'), logical_name)
                            if output_exists(result.get('output_dir'), logical_name):
                                payload['financial_difference_file'] = logical_name
                                payload['financial_difference_file_path'] = logical_name
                    finally:
                        try:
                            if os.path.exists(temp_csv_path):
                                os.remove(temp_csv_path)
                        except Exception:
                            pass
        except Exception:
            payload['financial_difference_file'] = None
            payload['financial_difference_file_path'] = None

        print("[VALIDATE API] validated_file_path =", payload.get('validated_file_path'))

        errors = result.get('errors') or []
        if payload['invalid_records'] > 0:
            payload['errors'] = errors
        else:
            payload['errors'] = []

        return jsonify(payload), 200

    except Exception as e:
        try:
            import traceback
            print("[GST_VALIDATE] Exception:\n" + traceback.format_exc())
            if os.getenv("AUTH_DEBUG", "").strip() == "1":
                # Do not print file contents; only safe metadata.
                try:
                    fsz = os.path.getsize(saved_path) if saved_path and os.path.exists(saved_path) else None
                except Exception:
                    fsz = None
                print(f"[GST_VALIDATE] saved_path={saved_path} size_bytes={fsz} content_type={request.content_type}")
        except Exception:
            pass
        # Keep existing response structure; expose details only in debug mode.
        if os.getenv("AUTH_DEBUG", "").strip() == "1":
            return jsonify({'valid': False, 'error': f'Could not read file: {str(e)}'}), 400
        return jsonify({'valid': False, 'error': 'Could not read file'}), 400

    finally:
        try:
            if os.path.exists(saved_path):
                os.remove(saved_path)
        except Exception:
            pass
        try:
            if output_dir_override and os.path.isdir(output_dir_override) and ("_validation_tmp" in output_dir_override):
                shutil.rmtree(output_dir_override, ignore_errors=True)
        except Exception:
            pass


def _run_swt_validation():
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'valid': False, 'error': 'No file uploaded'}), 400

    swt_data_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', 'swt', 'Data')
    )
    os.makedirs(swt_data_dir, exist_ok=True)

    try:
        saved_path, _saved_name = validate_upload_file(file, swt_data_dir, tax_type='SWT')
    except UploadSecurityError as exc:
        return jsonify({'valid': False, 'error': str(exc)}), 400

    try:
        result = run_swt_preprocessing(saved_path, make_timestamped_copies=True)
        if not result.get('ok'):
            errors = result.get('errors') or []
            if not errors:
                errors = [{
                    'row': '',
                    'tin': '',
                    'column': '',
                    'reason': result.get('error', 'Validation failed'),
                }]
            return jsonify({
                'valid': False,
                'errors': errors,
                'total_records': 0,
                'valid_records': 0,
                'invalid_records': 0,
                'tin_invalid_count': 0,
                'db_duplicates_count': 0,
                'db_financial_differences_count': 0,
                'db_financial_difference_fields_count': 0,
                'financial_difference_count': 0,
                'financial_difference_file': None,
                'financial_difference_file_path': None,
                'validated_file': '',
                'removed_data_file': '',
            }), 200

        payload = {
            'valid': True,
            'errors': result.get('errors') or [],
            'total_records': result.get('total_records', 0),
            'valid_records': result.get('valid_records', 0),
            'invalid_records': result.get('invalid_records', 0),
            'tin_invalid_count': result.get('tin_invalid_count', 0),
            'db_duplicates_count': result.get('db_duplicates_count', 0),
            'db_financial_differences_count': result.get('db_financial_differences_count', 0),
            # SWT does not currently compute per-field totals (kept for GST parity / UI expectation)
            'db_financial_difference_fields_count': result.get('db_financial_difference_fields_count', 0),
            'validated_file': result.get('validated_file', 'swt_validated.csv'),
            'removed_data_file': result.get('removed_data_file', 'swt_removed_data.csv'),
        }

        # Provide GST-parity paths for UI + processing.
        try:
            output_dir = result.get('output_dir') or os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', '..', 'swt', 'final_output')
            )
            payload['output_dir'] = None

            validated_file_path = _logical_output_name(
                result.get('validated_file_full_path') or payload.get('validated_file')
            )
            removed_data_file_path = _logical_output_name(
                result.get('removed_file_full_path') or payload.get('removed_data_file')
            )

            payload['validated_file_path'] = validated_file_path
            payload['removed_data_file_path'] = removed_data_file_path

            print("[SWT VALIDATE] validated_file_path =", validated_file_path)
            print("[SWT VALIDATE] removed_data_file_path =", removed_data_file_path)
        except Exception:
            payload['validated_file_path'] = None
            payload['removed_data_file_path'] = None
            payload['output_dir'] = None

        if payload['invalid_records'] <= 0:
            payload['errors'] = []

        # Generate financial difference CSV (only when financial differences exist)
        payload['financial_difference_count'] = int(
            payload.get('db_financial_difference_fields_count')
            or payload.get('db_financial_differences_count')
            or 0
        )
        payload['financial_difference_file'] = None
        payload['financial_difference_file_path'] = None
        try:
            if payload['financial_difference_count'] > 0:
                conflict_tins = []
                for err in result.get('errors') or []:
                    reason = str((err or {}).get('reason') or '').lower()
                    if 'financial values differ from existing swt_fraud_justification record' in reason:
                        tin = str((err or {}).get('tin') or '').strip()
                        if tin:
                            conflict_tins.append(tin)
                conflict_tins = list(dict.fromkeys(conflict_tins))

                if conflict_tins:
                    ts2 = datetime.now().strftime('%Y%m%d_%H%M%S')
                    logical_name = f'swt_financial_difference_{ts2}.csv'
                    fd, temp_csv_path = tempfile.mkstemp(prefix='swt_financial_difference_', suffix='.csv')
                    os.close(fd)
                    try:
                        wrote_csv = _export_upload_conflicts_csv_from_db(
                            "SWT",
                            conflict_tins,
                            temp_csv_path,
                        )
                        if wrote_csv and os.path.exists(temp_csv_path) and os.path.getsize(temp_csv_path) > 0:
                            write_encrypted_output_file(temp_csv_path, result.get('output_dir'), logical_name)
                            if output_exists(result.get('output_dir'), logical_name):
                                payload['financial_difference_file'] = logical_name
                                payload['financial_difference_file_path'] = logical_name
                    finally:
                        try:
                            if os.path.exists(temp_csv_path):
                                os.remove(temp_csv_path)
                        except Exception:
                            pass
        except Exception:
            payload['financial_difference_file'] = None
            payload['financial_difference_file_path'] = None

        return jsonify(payload), 200

    except Exception:
        return jsonify({'valid': False, 'error': 'Could not read file'}), 400

    finally:
        try:
            if os.path.exists(saved_path):
                os.remove(saved_path)
        except Exception:
            pass


def _run_cit_validation(output_dir_override=None):
    """
    Finalized CIT validation flow (modeled after GST/SWT):
      Upload -> Column Standardization -> Full Validation -> Split valid/invalid
      -> Merge taxpayer names ONLY into cleaned_df -> Write timestamped CSVs
      -> Return GST/SWT-style response structure.

    IMPORTANT:
    - Do NOT run fraud pipeline or ML models.
    - Do NOT merge taxpayer names into removed rows.
    """
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'valid': False, 'error': 'No file uploaded'}), 400

    import importlib.util as _importlib_util
    from datetime import datetime

    cit_dir_abs = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'cit'))
    cit_data_dir = os.path.join(cit_dir_abs, 'data')
    output_dir = output_dir_override or os.path.join(cit_dir_abs, 'final_output')
    public_output_dir = os.path.join(cit_dir_abs, 'final_output')
    os.makedirs(cit_data_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(public_output_dir, exist_ok=True)

    try:
        saved_path, _saved_name = _save_validated_upload_copy(
            file,
            cit_data_dir,
            allowed_extensions={'.csv', '.parquet'},
        )
    except UploadSecurityError as exc:
        return jsonify({'valid': False, 'error': str(exc)}), 400

    # Captured during DB validation (used for financial-difference CSV export)
    _financial_diff_export_rows = []

    def _load_input(path: str) -> pd.DataFrame:
        p = (path or '').lower()
        if p.endswith('.parquet'):
            return pd.read_parquet(path)
        if p.endswith('.csv'):
            return pd.read_csv(path)
        raise ValueError('Only .csv or .parquet files are accepted')

    def _normalize_tin_series_for_db(s: pd.Series) -> pd.Series:
        return (
            s.fillna('')
            .astype(str)
            .str.replace(r'\.0$', '', regex=True)
            .str.strip()
        )

    def _fetch_taxpayer_names_from_db(unique_tins):
        try:
            from config.db_config import get_mysql_engine
            from sqlalchemy import text, bindparam
        except Exception:
            return {}

        unique_tins = [t for t in unique_tins if isinstance(t, str) and t.strip() != '']
        if not unique_tins:
            return {}

        engine = get_mysql_engine()
        try:
            mapping = {}
            with engine.connect() as conn:
                cols = conn.execute(
                    text("SHOW COLUMNS FROM tin_registration_mst")
                ).fetchall()
                col_names = {str(row[0]).lower().strip() for row in cols}

                if "taxpayer_name" in col_names:
                    name_col = "taxpayer_name"
                elif "taxpayername" in col_names:
                    name_col = "taxpayername"
                else:
                    return {}

                q = text(f"""
                    SELECT normalized_tin,
                           {name_col} AS taxpayer_name
                    FROM tin_registration_mst
                    WHERE normalized_tin IN :tins
                """).bindparams(bindparam("tins", expanding=True))

                chunk_size = 1000
                for i in range(0, len(unique_tins), chunk_size):
                    chunk = unique_tins[i:i + chunk_size]
                    rows = conn.execute(q, {"tins": chunk}).fetchall()
                    for norm_tin, taxpayer_name in rows:
                        if norm_tin is None or taxpayer_name is None:
                            continue
                        mapping[str(norm_tin)] = taxpayer_name
            return mapping
        finally:
            try:
                engine.dispose()
            except Exception:
                pass

    def _merge_taxpayer_names_db_only(cleaned_df: pd.DataFrame) -> pd.DataFrame:
        if cleaned_df is None or cleaned_df.empty or 'tin' not in cleaned_df.columns:
            return cleaned_df

        out = cleaned_df.copy()

        existing_taxpayer_cols = [
            col for col in out.columns
            if col.lower().replace('_', '') in ['taxpayer', 'taxpayername', 'taxpayer_name', 'tax_payer', 'tax_payer_name']
        ]

        out['tin'] = _normalize_tin_series_for_db(out['tin'])
        out['_normalized_tin'] = _normalize_tin_series_for_db(out['tin'])
        unique_tins = out['_normalized_tin'].dropna().astype(str).unique().tolist()

        global _CIT_TIN_NAME_CACHE
        try:
            _CIT_TIN_NAME_CACHE
        except NameError:
            _CIT_TIN_NAME_CACHE = {}

        missing = [t for t in unique_tins if t not in _CIT_TIN_NAME_CACHE]
        if missing:
            try:
                fetched = _fetch_taxpayer_names_from_db(missing)
                _CIT_TIN_NAME_CACHE.update(fetched)
            except Exception:
                pass

        db_map = {t: _CIT_TIN_NAME_CACHE.get(t) for t in unique_tins if _CIT_TIN_NAME_CACHE.get(t) is not None}
        if db_map:
            out['_reg_taxpayer_name'] = out['_normalized_tin'].map(db_map)
            if existing_taxpayer_cols:
                existing_col = existing_taxpayer_cols[0]
                out[existing_col] = out[existing_col].replace('', pd.NA).fillna(out['_reg_taxpayer_name'])
                out['taxpayer_name'] = out[existing_col]
            else:
                out['taxpayer_name'] = out['_reg_taxpayer_name']
            out.drop(columns=['_reg_taxpayer_name'], inplace=True, errors='ignore')

        if 'taxpayer_name' not in out.columns and not existing_taxpayer_cols:
            out['taxpayer_name'] = pd.NA

        if 'taxpayer_name' in out.columns:
            duplicate_taxpayer_cols = [
                col for col in existing_taxpayer_cols
                if col != 'taxpayer_name'
            ]
            if duplicate_taxpayer_cols:
                out.drop(columns=duplicate_taxpayer_cols, inplace=True, errors='ignore')

        out.drop(columns=['_normalized_tin'], inplace=True, errors='ignore')

        try:
            cols = out.columns.tolist()
            taxpayer_col = 'taxpayer_name' if 'taxpayer_name' in cols else None
            if taxpayer_col and 'tin' in cols and taxpayer_col in cols and taxpayer_col != 'tin':
                cols.remove(taxpayer_col)
                tin_index = cols.index('tin')
                cols.insert(tin_index + 1, taxpayer_col)
                out = out[cols]
        except Exception:
            pass

        return out

    def _guess_column(reason: str) -> str:
        msg = (reason or '').lower()
        patterns = [
            (r'\btin\b', 'TIN'),
            (r'assessment', 'AssessmentNo'),
            (r'tax account', 'TaxAccountNo'),
            (r'gross sales', 'GrossSalesCashOrCredit'),
            (r'total gross income', 'TotalGrossIncome'),
        ]
        for pat, col in patterns:
            if re.search(pat, msg):
                return col
        return ''

    try:
        for f in ['cit_standardized.parquet', 'cit_standardized.csv', 'cit_cleaned_data.csv',
                  'cit_removed_data.csv', 'cit_validated.csv', 'cit_validation_log.txt']:
            try:
                fp = os.path.join(output_dir, f)
                if os.path.exists(fp):
                    os.remove(fp)
            except Exception:
                pass

        df_in = _load_input(saved_path)
        if df_in is None or len(df_in) <= 0:
            return jsonify({
                'valid': False,
                'errors': [{'row': '', 'tin': '', 'column': '', 'reason': 'Uploaded file contains no data rows'}],
                'total_records': 0,
                'valid_records': 0,
                'invalid_records': 0,
                'tin_invalid_count': 0,
                'validated_file': '',
                'removed_data_file': '',
            }), 200

        # Step 1: Column Standardization (reuse CIT preprocessing logic)
        preproc_path = os.path.join(cit_dir_abs, 'script_1_data_preprocessing.py')
        spec1 = _importlib_util.spec_from_file_location('cit_preprocessing_module', preproc_path)
        mod1 = _importlib_util.module_from_spec(spec1)
        spec1.loader.exec_module(mod1)

        std_df = mod1.standardize_columns(df_in.copy())
        std_df = std_df.copy()
        if '_row' not in std_df.columns:
            std_df['_row'] = pd.RangeIndex(start=1, stop=len(std_df) + 1, step=1)

        # Step 2: Full Validation (reuse ML developer validation logic directly; no duplicated rules)
        validation_path = os.path.join(cit_dir_abs, 'script_2_data_validation.py')
        spec2 = _importlib_util.spec_from_file_location('cit_validation_module', validation_path)
        mod2 = _importlib_util.module_from_spec(spec2)
        spec2.loader.exec_module(mod2)

        original_dir = os.getcwd()
        os.chdir(output_dir)
        try:
            cleaned_df, removed_df, removal_details = mod2.validate_and_clean_cit_data(std_df)
        finally:
            os.chdir(original_dir)

        if cleaned_df is None:
            cleaned_df = pd.DataFrame()
        if removed_df is None:
            removed_df = pd.DataFrame()
        if removal_details is None:
            removal_details = []

        # GST/SWT-style DB duplicate + financial difference validation (against cit_fraud_justification)
        # Runs AFTER full CIT validation and BEFORE taxpayer merge / CSV export.
        db_duplicates_count = 0
        db_financial_differences_count = 0
        db_financial_difference_fields_count = 0
        try:
            # Mirror GST composite key strategy as closely as CIT schema allows.
            # CIT table (db_init) includes: tin, tax_account_no, tax_period_year, assessment_no (no month).
            key_cols = ['tin', 'tax_account_no', 'tax_period_year', 'assessment_no']

            exclude_cols = set([
                'tin',
                'tax_account_no',
                'tax_period_year',
                'tax_period_month',
                'tax_type',
                'taxpayer',
                'taxpayer_name',
                'taxpayer_type',
                'assessment_number',
                'assessment_no',
                'entry_date',
                'assessed_date',
                'due_date',
                '_row',
                'reason',
            ])

            if cleaned_df is None:
                cleaned_df = pd.DataFrame()
            if removed_df is None:
                removed_df = pd.DataFrame()

            if not cleaned_df.empty and all(c in cleaned_df.columns for c in key_cols):
                cleaned_df = cleaned_df.copy()

                # GST-equivalent key normalization
                for col in ('tin', 'tax_account_no', 'assessment_no'):
                    s = (
                        cleaned_df[col]
                        .astype(str)
                        .str.replace(".0", "", regex=False)
                        .str.strip()
                    )
                    s_lower = s.str.lower()
                    s = s.mask(s_lower.isin(["", "nan", "none", "null", "<na>"]), pd.NA)
                    cleaned_df[col] = s

                cleaned_df['tax_period_year'] = (
                    pd.to_numeric(cleaned_df['tax_period_year'], errors='coerce')
                    .fillna(0)
                    .astype(int)
                )

                def _is_unnamed_tmp_col(col_name: str) -> bool:
                    try:
                        n = str(col_name or "").strip().lower().replace(" ", "")
                    except Exception:
                        return False
                    return n in ("unnamed:_0", "unnamed:0", "unnamed_0")

                # Auto-detect numeric financial columns (exclude keys + non-fin fields)
                fin_cols = []
                for c in cleaned_df.columns:
                    if c in exclude_cols:
                        continue
                    if _is_unnamed_tmp_col(c):
                        continue
                    # Only compare columns that behave numerically
                    try:
                        s = pd.to_numeric(cleaned_df[c], errors='coerce')
                        # Keep when at least some numeric values exist
                        if s.notna().any():
                            cleaned_df[c] = s.fillna(0.0)
                            fin_cols.append(c)
                    except Exception:
                        continue

                unique_tins = cleaned_df['tin'].dropna().astype(str).str.strip()
                unique_tins = [t for t in unique_tins.unique().tolist() if t != '']

                debug_db = os.environ.get('CIT_DB_VALIDATION_DEBUG') == '1'
                if debug_db:
                    try:
                        print('[CIT_DB_VALIDATION] db compare keys:', key_cols)
                        print('[CIT_DB_VALIDATION] financial compare columns:', fin_cols)
                    except Exception:
                        pass

                if unique_tins:
                    # Pull only relevant DB rows for these tins (filter keys in pandas afterwards)
                    engine_db = None
                    try:
                        from config.db_config import get_mysql_engine
                        from sqlalchemy import text, bindparam

                        engine_db = get_mysql_engine()
                        # Select only columns that exist in the DB table
                        with engine_db.connect() as conn:
                            cols_res = conn.execute(text(
                                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'cit_fraud_justification' "
                                "ORDER BY ORDINAL_POSITION"
                            ))
                            db_cols_all = [row[0] for row in cols_res]

                        db_select_cols = []
                        for c in key_cols:
                            if c in db_cols_all:
                                db_select_cols.append(c)
                        db_fin_cols = [c for c in fin_cols if c in db_cols_all]
                        if len(db_select_cols) == len(key_cols):
                            sel = ', '.join(db_select_cols + db_fin_cols) if db_fin_cols else ', '.join(db_select_cols)
                            # Use an explicit connection for expanding bind params; some pandas/SQLAlchemy
                            # combinations fail to expand correctly when passing an Engine directly.
                            tins_param = []
                            for t in unique_tins:
                                try:
                                    tins_param.append(int(str(t).strip()))
                                except Exception:
                                    continue
                            with engine_db.connect() as conn:
                                db_df = pd.read_sql(
                                    text(f"""
                                        SELECT {sel}
                                        FROM cit_fraud_justification
                                        WHERE tin IN :tins
                                    """).bindparams(bindparam("tins", expanding=True)),
                                    conn,
                                    params={"tins": tins_param},
                                )
                        else:
                            db_df = pd.DataFrame()
                    finally:
                        try:
                            if engine_db is not None:
                                engine_db.dispose()
                        except Exception:
                            pass

                    print("=" * 80)
                    print("[CIT VALIDATE]")
                    print("table = cit_fraud_justification")
                    print("keys =", key_cols)
                    print("sql = WHERE tin IN :tins")
                    print("tins =", len(unique_tins))
                    print("records_found =", 0 if db_df is None else int(len(db_df)))
                    print("=" * 80)

                    if db_df is not None and not db_df.empty:
                        db_df = db_df.copy()
                        # Ensure we have `id` and `upload_batch_id` from the source table so we can
                        # populate `source_record_id` / `upload_batch_id` in `upload_conflicts` rows.
                        # This does NOT change matching logic; it only enriches the already-fetched DB rows.
                        try:
                            if 'id' not in db_df.columns or 'upload_batch_id' not in db_df.columns:
                                try:
                                    from sqlalchemy import text, bindparam
                                    engine_ids = None
                                    engine_ids = get_mysql_engine()
                                    with engine_ids.connect() as conn:
                                        cols_res2 = conn.execute(text(
                                            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                                            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'cit_fraud_justification'"
                                        ))
                                        cols2 = set((r[0] or "").lower() for r in cols_res2.fetchall())

                                        select_cols = []
                                        if 'id' in cols2:
                                            select_cols.append('id')
                                        if 'upload_batch_id' in cols2:
                                            select_cols.append('upload_batch_id')
                                        select_cols.extend(['tin', 'tax_account_no', 'tax_period_year', 'assessment_no'])
                                        select_cols = [c for c in select_cols if c in cols2]

                                        if select_cols and all(c in cols2 for c in ['tin', 'tax_account_no', 'tax_period_year', 'assessment_no']):
                                            q2 = text(
                                                f"SELECT {', '.join(select_cols)} FROM cit_fraud_justification WHERE tin IN :tins"
                                            ).bindparams(bindparam("tins", expanding=True))
                                            db2 = pd.read_sql(q2, conn, params={"tins": unique_tins})
                                            if db2 is not None and not db2.empty:
                                                # Merge back onto db_df using the same keys already used in validation.
                                                for col in ('tin', 'tax_account_no', 'assessment_no'):
                                                    if col in db2.columns:
                                                        s = (
                                                            db2[col]
                                                            .astype(str)
                                                            .str.replace(".0", "", regex=False)
                                                            .str.strip()
                                                        )
                                                        s_lower = s.str.lower()
                                                        s = s.mask(s_lower.isin(["", "nan", "none", "null", "<na>"]), pd.NA)
                                                        db2[col] = s
                                                if 'tax_period_year' in db2.columns:
                                                    db2['tax_period_year'] = (
                                                        pd.to_numeric(db2['tax_period_year'], errors='coerce')
                                                        .fillna(0)
                                                        .astype(int)
                                                    )
                                                # Only bring in missing cols
                                                add_cols = [c for c in ['id', 'upload_batch_id'] if c in db2.columns and c not in db_df.columns]
                                                if add_cols:
                                                    db_df = db_df.merge(db2[key_cols + add_cols], on=key_cols, how='left')
                                finally:
                                    try:
                                        if engine_ids is not None:
                                            engine_ids.dispose()
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                        for col in ('tin', 'tax_account_no', 'assessment_no'):
                            s = (
                                db_df[col]
                                .astype(str)
                                .str.replace(".0", "", regex=False)
                                .str.strip()
                            )
                            s_lower = s.str.lower()
                            s = s.mask(s_lower.isin(["", "nan", "none", "null", "<na>"]), pd.NA)
                            db_df[col] = s

                        db_df['tax_period_year'] = (
                            pd.to_numeric(db_df['tax_period_year'], errors='coerce')
                            .fillna(0)
                            .astype(int)
                        )
                        for c in fin_cols:
                            if c in db_df.columns:
                                db_df[c] = pd.to_numeric(db_df[c], errors='coerce').fillna(0.0)

                        # Enrich the already-matched DB frame with `id` and `upload_batch_id` (if present on
                        # `cit_fraud_justification`) so we can populate `source_record_id` / `upload_batch_id`
                        # in `upload_conflicts`. This does NOT change matching logic.
                        try:
                            need_id = 'id' not in db_df.columns
                            need_batch = 'upload_batch_id' not in db_df.columns
                            if need_id or need_batch:
                                from sqlalchemy import text, bindparam
                                engine_more = None
                                try:
                                    engine_more = get_mysql_engine()
                                    with engine_more.connect() as conn:
                                        cols_res_more = conn.execute(text(
                                            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                                            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'cit_fraud_justification'"
                                        ))
                                        tbl_cols = set((r[0] or "").lower() for r in cols_res_more.fetchall())

                                        select_cols = []
                                        if need_id and 'id' in tbl_cols:
                                            select_cols.append('id')
                                        if need_batch and 'upload_batch_id' in tbl_cols:
                                            select_cols.append('upload_batch_id')
                                        for k in key_cols:
                                            if k in tbl_cols and k not in select_cols:
                                                select_cols.append(k)

                                        if select_cols and all((k in tbl_cols) for k in key_cols):
                                            q_more = text(
                                                "SELECT " + ", ".join(select_cols) +
                                                " FROM cit_fraud_justification WHERE tin IN :tins"
                                            ).bindparams(bindparam("tins", expanding=True))
                                            db_more = pd.read_sql(q_more, conn, params={"tins": unique_tins})
                                            if db_more is not None and not db_more.empty:
                                                # Normalize keys same way as main db_df
                                                for col in ('tin', 'tax_account_no', 'assessment_no'):
                                                    if col in db_more.columns:
                                                        s = (
                                                            db_more[col]
                                                            .astype(str)
                                                            .str.replace(".0", "", regex=False)
                                                            .str.strip()
                                                        )
                                                        s_lower = s.str.lower()
                                                        s = s.mask(s_lower.isin(["", "nan", "none", "null", "<na>"]), pd.NA)
                                                        db_more[col] = s
                                                if 'tax_period_year' in db_more.columns:
                                                    db_more['tax_period_year'] = (
                                                        pd.to_numeric(db_more['tax_period_year'], errors='coerce')
                                                        .fillna(0)
                                                        .astype(int)
                                                    )
                                                add_cols = [c for c in ('id', 'upload_batch_id') if c in db_more.columns and c not in db_df.columns]
                                                if add_cols:
                                                    db_df = db_df.merge(db_more[key_cols + add_cols], on=key_cols, how='left')
                                finally:
                                    try:
                                        if engine_more is not None:
                                            engine_more.dispose()
                                    except Exception:
                                        pass
                        except Exception:
                            pass

                        if '_upload_row_id' not in cleaned_df.columns:
                            cleaned_df['_upload_row_id'] = cleaned_df.index.astype('int64')

                        merged = cleaned_df.merge(
                            db_df,
                            on=key_cols,
                            how='left',
                            suffixes=('', '__db'),
                            indicator=True,
                        )

                        matched = merged['_merge'].eq('both')
                        diff_upload_ids = []
                        dup_upload_ids = []
                        diff_rows = pd.DataFrame()
                        if matched.any():
                            eq_mask = pd.Series(True, index=merged.index)
                            for c in fin_cols:
                                if c in merged.columns and f"{c}__db" in merged.columns:
                                    eq_mask &= (merged[c].fillna(0.0) == merged[f"{c}__db"].fillna(0.0))

                            merged['_no_fin_diff'] = matched & eq_mask
                            merged['_has_fin_diff'] = matched & (~eq_mask)

                            agg = (
                                merged.groupby('_upload_row_id', dropna=False)
                                .agg(
                                    _any_db_match=('_merge', lambda s: s.eq('both').any()),
                                    _any_no_fin_diff=('_no_fin_diff', 'any'),
                                    _any_fin_diff=('_has_fin_diff', 'any'),
                                )
                                .reset_index()
                            )

                            dup_upload_ids = agg.loc[
                                agg['_any_db_match'] & agg['_any_no_fin_diff'],
                                '_upload_row_id'
                            ].tolist()
                            diff_upload_ids = agg.loc[
                                agg['_any_db_match'] & ~agg['_any_no_fin_diff'] & agg['_any_fin_diff'],
                                '_upload_row_id'
                            ].tolist()
                            remove_ids = set(dup_upload_ids) | set(diff_upload_ids)

                            diff_rows = (
                                merged.loc[matched & merged['_upload_row_id'].isin(diff_upload_ids)]
                                .sort_values(['_upload_row_id'])
                                .groupby('_upload_row_id', as_index=False)
                                .first()
                            )

                            if debug_db:
                                try:
                                    print('[CIT_DB_VALIDATION] matched keys:', int(matched.sum()))
                                    print('[CIT_DB_VALIDATION] duplicate count:', int(len(dup_upload_ids)))
                                    print('[CIT_DB_VALIDATION] financial difference count:', int(len(diff_upload_ids)))
                                except Exception:
                                    pass

                            if remove_ids:
                                removed_rows = cleaned_df.loc[cleaned_df['_upload_row_id'].isin(remove_ids)].copy()
                                removed_rows['reason'] = [
                                    "Duplicate CIT record already exists in cit_fraud_justification" if rid in set(dup_upload_ids)
                                    else "Financial values differ from existing cit_fraud_justification record"
                                    for rid in removed_rows['_upload_row_id'].tolist()
                                ]

                                for _, rr in removed_rows.iterrows():
                                    row_num = rr.get('_row')
                                    try:
                                        row_num = int(row_num) if pd.notna(row_num) else ''
                                    except Exception:
                                        row_num = ''
                                    tin_val = '' if pd.isna(rr.get('tin')) else str(rr.get('tin')).strip()

                                    if rr.get('_upload_row_id') in set(dup_upload_ids):
                                        db_duplicates_count += 1
                                        reason = "Duplicate CIT record already exists in cit_fraud_justification"
                                    else:
                                        db_financial_differences_count += 1
                                        reason = "Financial values differ from existing cit_fraud_justification record"

                                    removal_details.append({
                                        'row': row_num,
                                        'tin': tin_val,
                                        'column': 'TIN',
                                        'reason': reason,
                                    })

                                # Persist conflicts to upload_conflicts (one row per differing field), GST-style
                                try:
                                    diff_rows = diff_rows.copy()
                                    if not diff_rows.empty:
                                        # Build in-memory export rows for the required financial-difference CSV.
                                        # We do NOT rely on `upload_conflicts` for CIT because many installs have
                                        # tax_type enum limited to GST/SWT, causing inserts to fail silently.
                                        try:
                                            def _pick_col(cands):
                                                for c in (cands or []):
                                                    if c in diff_rows.columns and f"{c}__db" in diff_rows.columns:
                                                        return c
                                                return None

                                            # "Salary" and "Tax" are labels for the CSV; we map them to the
                                            # best-available CIT numeric fields present in this dataset.
                                            sal_col = _pick_col([
                                                "total_salary_or_wages",
                                                "salaries_or_wages",
                                                "accrued_salary_or_wages",
                                                "total_directors_salary_related",
                                            ])
                                            tax_col = _pick_col([
                                                "total_tax_payable",
                                                "net_tax_payable_or_refunda",
                                                "total_taxable_income_tax_payable",
                                                "gross_tax",
                                                "gross_tax_net_of_other_cre",
                                                "total_tax_to_pay_after_in",
                                                "total_tax_to_pay_after_in_",
                                            ])

                                        except Exception:
                                            sal_col = None
                                            tax_col = None

                                        if sal_col or tax_col:
                                            for _, rr in diff_rows.iterrows():
                                                tin_val = "" if pd.isna(rr.get("tin")) else str(rr.get("tin")).strip()
                                                # Normalize common pandas artifact: `500000161.0`
                                                if tin_val.endswith(".0") and tin_val[:-2].isdigit():
                                                    tin_val = tin_val[:-2]
                                                if not tin_val:
                                                    continue
                                                name_val = ""
                                                for nc in ["taxpayer_name", "taxpayer", "taxpayername"]:
                                                    if nc in rr and pd.notna(rr.get(nc)):
                                                        name_val = str(rr.get(nc)).strip()
                                                        break

                                                def _f(v):
                                                    try:
                                                        return float(v) if pd.notna(v) else 0.0
                                                    except Exception:
                                                        try:
                                                            return float(str(v).strip())
                                                        except Exception:
                                                            return 0.0

                                                uploaded_salary = system_salary = None
                                                uploaded_tax = system_tax = None
                                                has_sal = False
                                                has_tax = False
                                                if sal_col is not None:
                                                    uploaded_salary = _f(rr.get(sal_col))
                                                    system_salary = _f(rr.get(f"{sal_col}__db"))
                                                    has_sal = uploaded_salary != system_salary
                                                if tax_col is not None:
                                                    uploaded_tax = _f(rr.get(tax_col))
                                                    system_tax = _f(rr.get(f"{tax_col}__db"))
                                                    has_tax = uploaded_tax != system_tax
                                                if not (has_sal or has_tax):
                                                    continue

                                                diff_amount = (abs((uploaded_salary or 0.0) - (system_salary or 0.0)) if has_sal else 0.0) + (
                                                    abs((uploaded_tax or 0.0) - (system_tax or 0.0)) if has_tax else 0.0
                                                )
                                                diff_type = "both" if (has_sal and has_tax) else ("salary" if has_sal else "tax")

                                                _financial_diff_export_rows.append({
                                                    "tin": tin_val,
                                                    "employee_name": name_val,
                                                    "uploaded_salary": uploaded_salary,
                                                    "system_salary": system_salary,
                                                    "uploaded_tax": uploaded_tax,
                                                    "system_tax": system_tax,
                                                    "difference_amount": diff_amount,
                                                    "difference_type": diff_type,
                                                    "reason": _reason_for_financial_difference(has_sal, has_tax, diff_amount),
                                                })

                                        conflicts_rows = []
                                        # Optional fields, if present
                                        assess_val_col = 'assessment_number' if 'assessment_number' in diff_rows.columns else ('assessment_no' if 'assessment_no' in diff_rows.columns else None)
                                        for _, rr in diff_rows.iterrows():
                                            for field_name in fin_cols:
                                                try:
                                                    if _is_unnamed_tmp_col(field_name):
                                                        continue
                                                except Exception:
                                                    pass
                                                new_val = rr.get(field_name)
                                                old_val = rr.get(f"{field_name}__db")
                                                try:
                                                    new_v = float(new_val) if pd.notna(new_val) else 0.0
                                                except Exception:
                                                    new_v = 0.0
                                                try:
                                                    old_v = float(old_val) if pd.notna(old_val) else 0.0
                                                except Exception:
                                                    old_v = 0.0
                                                if new_v != old_v:
                                                    db_financial_difference_fields_count += 1
                                                    conflicts_rows.append({
                                                        "tax_type": "CIT",
                                                        "tin": str(rr.get("tin") if rr.get("tin") is not None else "").strip(),
                                                        "taxpayer_name": rr.get("taxpayer_name", None),
                                                        "tax_period_year": rr.get("tax_period_year", None),
                                                        "tax_period_month": rr.get("tax_period_month", None) if 'tax_period_month' in key_cols else None,
                                                        "assessment_number": rr.get(assess_val_col, None) if assess_val_col else None,
                                                        "field_name": _sanitize_field_name(field_name),
                                                        "previous_value": old_v,
                                                        "current_value": new_v,
                                                        "status": 0,
                                                        "source_table": "cit_fraud_justification",
                                                        # Capture id of the matched DB record when available (requires DB query to include `id`).
                                                        "source_record_id": rr.get("id__db", None),
                                                        # Reuse DB upload batch id when present on the matched record.
                                                        "upload_batch_id": rr.get("upload_batch_id__db", None),
                                                    })
                                        if conflicts_rows:
                                            to_ins = pd.DataFrame(conflicts_rows)
                                            engine2 = None
                                            try:
                                                from config.db_config import get_mysql_engine
                                                from sqlalchemy import text

                                                engine2 = get_mysql_engine()
                                                with engine2.connect() as conn:
                                                    cols_res = conn.execute(text(
                                                        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                                                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'upload_conflicts' "
                                                        "ORDER BY ORDINAL_POSITION"
                                                    ))
                                                    conf_cols = [row[0] for row in cols_res]
                                                current_user_id = get_authenticated_user_id()
                                                for c in conf_cols:
                                                    if c not in to_ins.columns:
                                                        to_ins[c] = None
                                                if "user_id" in conf_cols:
                                                    to_ins["user_id"] = current_user_id

                                                # Populate source_record_id + upload_batch_id by resolving the matched
                                                # fraud-justification row (required for approval workflow integrity).
                                                try:
                                                    if "source_record_id" in conf_cols or "upload_batch_id" in conf_cols:
                                                        src_ids = []
                                                        batch_ids = []
                                                        tp_names = []
                                                        for _, r in to_ins.iterrows():
                                                            try:
                                                                src_id, batch_id, tp_name = _resolve_source_meta_for_conflict(
                                                                    engine=engine2,
                                                                    source_table="cit_fraud_justification",
                                                                    assessment_column="assessment_no",
                                                                    tin=r.get("tin"),
                                                                    tax_period_year=r.get("tax_period_year"),
                                                                    assessment_number=r.get("assessment_number"),
                                                                    field_name=_sanitize_field_name(r.get("field_name")),
                                                                    previous_value=r.get("previous_value"),
                                                                )
                                                            except Exception:
                                                                src_id, batch_id, tp_name = (None, None, None)
                                                            src_ids.append(src_id)
                                                            batch_ids.append(batch_id)
                                                            # Fill taxpayer_name from matched row when possible
                                                            try:
                                                                resolved = tp_name
                                                                if resolved is None or (isinstance(resolved, str) and resolved.strip() == ""):
                                                                    resolved = r.get("taxpayer_name")
                                                                tp_names.append(resolved)
                                                            except Exception:
                                                                tp_names.append(None)

                                                        if "source_record_id" in conf_cols:
                                                            to_ins["source_record_id"] = src_ids
                                                        if "upload_batch_id" in conf_cols:
                                                            to_ins["upload_batch_id"] = batch_ids
                                                        if "taxpayer_name" in conf_cols:
                                                            # Ensure non-null where possible (CIT uses `taxpayer` on source table)
                                                            to_ins["taxpayer_name"] = tp_names

                                                        if os.getenv("AUTH_DEBUG", "").strip() == "1":
                                                            try:
                                                                miss = sum(1 for x in src_ids if x is None)
                                                                print(f"[CIT_CONFLICT_META] resolved source_record_id missing={miss} total={len(src_ids)}")
                                                            except Exception:
                                                                pass
                                                except Exception:
                                                    pass

                                                to_ins = to_ins[conf_cols]
                                                with engine2.begin() as conn:
                                                    to_ins.to_sql("upload_conflicts", con=conn, if_exists="append", index=False)
                                            finally:
                                                try:
                                                    if engine2 is not None:
                                                        engine2.dispose()
                                                except Exception:
                                                    pass
                                except Exception:
                                    pass

                                # Append removed rows (drop db helper cols)
                                drop_db_cols = [c for c in removed_rows.columns if c.endswith('__db') or c in ['_merge', '_upload_row_id', '_db_key']]
                                removed_rows.drop(columns=drop_db_cols, inplace=True, errors='ignore')
                                base_cols = [c for c in cleaned_df.columns if c in removed_rows.columns]
                                cols_out = base_cols + (['reason'] if 'reason' in removed_rows.columns else [])
                                removed_df = pd.concat([removed_df, removed_rows[cols_out]], ignore_index=True)

                                # Keep only non-removed in cleaned_df (for taxpayer merge + validated output)
                                cleaned_df = cleaned_df.loc[~cleaned_df['_upload_row_id'].isin(remove_ids), [c for c in cleaned_df.columns if c not in ['_upload_row_id', '_db_key']]].copy()
        except Exception:
            # Do not fail CIT validation on DB issues
            if os.environ.get('CIT_DB_VALIDATION_DEBUG') == '1':
                try:
                    import traceback
                    print('[CIT_DB_VALIDATION] Exception:\n' + traceback.format_exc())
                except Exception:
                    pass
            pass

        # Step 4: Merge taxpayer names ONLY into cleaned_df (DB-only) AFTER DB duplicate/conflict filtering
        cleaned_df = _merge_taxpayer_names_db_only(cleaned_df)

        # Step 6/7: Write timestamped outputs
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        validated_file = f'cit_validated_{ts}.csv'
        removed_file = f'cit_removed_data_{ts}.csv'

        try:
            _store_encrypted_dataframe(public_output_dir, validated_file, cleaned_df)
        except Exception:
            _store_encrypted_dataframe(public_output_dir, validated_file, pd.DataFrame())

        try:
            _store_encrypted_dataframe(public_output_dir, removed_file, removed_df)
        except Exception:
            _store_encrypted_dataframe(public_output_dir, removed_file, pd.DataFrame())

        total_records = int(len(cleaned_df)) + int(len(removed_df))
        valid_records = int(len(cleaned_df))
        invalid_records = int(len(removed_df))

        errors = []
        try:
            if isinstance(removal_details, list):
                errors = removal_details
        except Exception:
            errors = []

        # Derive tin_invalid_count from structured rule-level errors (TIN validation only; exclude DB duplicate/conflict rows)
        tin_invalid_count = 0
        try:
            tin_msgs = [
                'tin is null/empty',
                'tin has wrong length',
                'tin starts with zero',
                'tin has all identical digits',
                'tin is a continuous',
            ]
            tin_invalid_count = int(sum(
                1
                for e in errors
                if str(e.get('column', '')).strip().upper() == 'TIN'
                and any(m in str(e.get('reason', '')).lower() for m in tin_msgs)
            ))
        except Exception:
            tin_invalid_count = 0

        validated_file_path = None
        removed_data_file_path = None
        try:
            validated_file_path = validated_file if validated_file else None
            print("[CIT VALIDATE] validated_file_path =", validated_file_path)
        except Exception:
            validated_file_path = None

        try:
            removed_data_file_path = removed_file if removed_file else None
            print("[CIT VALIDATE] removed_data_file_path =", removed_data_file_path)
        except Exception:
            removed_data_file_path = None

        # Generate financial difference CSV (only when financial differences exist)
        financial_difference_count = int(
            db_financial_difference_fields_count
            or db_financial_differences_count
            or 0
        )
        financial_difference_file = None
        financial_difference_file_path = None
        try:
            if financial_difference_count > 0 and public_output_dir:
                ts2 = datetime.now().strftime('%Y%m%d_%H%M%S')
                financial_difference_file = f'cit_financial_difference_{ts2}.csv'
                financial_difference_file_path = financial_difference_file

                # Preferred: write from in-memory diff rows (when available)
                if _financial_diff_export_rows:
                    _store_encrypted_dataframe(
                        public_output_dir,
                        financial_difference_file,
                        pd.DataFrame(
                            _financial_diff_export_rows,
                            columns=[
                                "tin",
                                "employee_name",
                                "uploaded_salary",
                                "system_salary",
                                "uploaded_tax",
                                "system_tax",
                                "difference_amount",
                                "difference_type",
                                "reason",
                            ],
                        ),
                    )

                # Fallback: if the file wasn't created but DB conflicts exist, export from DB.
                if not os.path.exists(os.path.join(public_output_dir, f"{financial_difference_file}.enc")):
                    try:
                        # Reuse current-upload scope: limit to TINs that were flagged as financial differences
                        # during this validation run (do not dump the entire table).
                        conflict_tins = []
                        try:
                            if 'reason' in removed_df.columns and 'tin' in removed_df.columns:
                                mask = removed_df['reason'].astype(str).str.lower().str.contains(
                                    "financial values differ from existing cit_fraud_justification record", na=False
                                )
                                fin_df = removed_df.loc[mask]
                                conflict_tins = fin_df['tin'].dropna().tolist()
                        except Exception:
                            conflict_tins = []

                        def _norm_tin(v) -> str:
                            try:
                                s = "" if v is None else str(v).strip()
                            except Exception:
                                s = ""
                            if not s:
                                return ""
                            if s.endswith(".0") and s[:-2].isdigit():
                                return s[:-2]
                            return s

                        tins = [_norm_tin(t) for t in conflict_tins]
                        tins = [t for t in tins if t and t.lower() not in ("nan", "none", "null", "<na>")]
                        tins = list(dict.fromkeys(tins))
                        if tins:
                            from sqlalchemy import text, bindparam
                            from config.db_config import get_mysql_engine

                            engine2 = None
                            rows = []
                            try:
                                engine2 = get_mysql_engine()
                                with engine2.connect() as conn:
                                    cols_res = conn.execute(text(
                                        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'upload_conflicts' "
                                        "ORDER BY ORDINAL_POSITION"
                                    ))
                                    conf_cols = [row[0] for row in cols_res]
                                    conf_cols_l = set(str(c or "").lower() for c in conf_cols)

                                    current_user_id = get_authenticated_user_id()
                                    has_user_id = "user_id" in conf_cols_l

                                    # Use the exact column names as stored in DB; do not alias/rename here.
                                    base_select = [
                                        "tax_type",
                                        "tin",
                                        "taxpayer_name",
                                        "tax_period_year",
                                        "tax_period_month",
                                        "assessment_number",
                                        "field_name",
                                        "previous_value",
                                        "current_value",
                                        "status",
                                        "user_id",
                                        "id",
                                    ]
                                    select_cols = [c for c in base_select if c in conf_cols]
                                    if not select_cols:
                                        select_cols = [c for c in conf_cols if c in base_select]  # best-effort

                                    where_user = " AND user_id = :user_id " if (has_user_id and current_user_id is not None) else ""
                                    q = text(
                                        f"SELECT {', '.join(select_cols)} "
                                        "FROM upload_conflicts "
                                        "WHERE tax_type = :tax_type "
                                        "  AND status = 0 "
                                        f"{where_user}"
                                        "  AND tin IN :tins "
                                        "ORDER BY id DESC"
                                    ).bindparams(bindparam("tins", expanding=True))

                                    params = {"tax_type": "CIT", "tins": tins}
                                    if has_user_id and current_user_id is not None:
                                        params["user_id"] = current_user_id

                                    res = conn.execute(q, params)
                                    rows = [dict(r._mapping) for r in res.fetchall()]
                            finally:
                                try:
                                    if engine2 is not None:
                                        engine2.dispose()
                                except Exception:
                                    pass

                            if rows:
                                df_db = pd.DataFrame(rows)
                                # CIT-only: exclude import-generated temp columns like `Unnamed: 0`
                                try:
                                    if "field_name" in df_db.columns:
                                        _n = (
                                            df_db["field_name"]
                                            .astype(str)
                                            .str.strip()
                                            .str.lower()
                                            .str.replace(" ", "", regex=False)
                                        )
                                        df_db = df_db[~_n.isin(["unnamed:_0", "unnamed:0", "unnamed_0"])].copy()
                                except Exception:
                                    pass
                                # Add required computed columns (still using required names).
                                try:
                                    df_db["difference"] = pd.to_numeric(df_db.get("current_value"), errors="coerce").fillna(0.0) - pd.to_numeric(df_db.get("previous_value"), errors="coerce").fillna(0.0)
                                except Exception:
                                    df_db["difference"] = None

                                def _mk_reason(fn):
                                    s = str(fn or "").lower()
                                    has_sal = ("salary" in s) or ("wage" in s)
                                    has_tax = ("tax" in s)
                                    if has_sal and has_tax:
                                        return "Salary and tax mismatch"
                                    if has_sal:
                                        return "Salary mismatch between uploaded and system values"
                                    if has_tax:
                                        return "Tax mismatch between uploaded and system values"
                                    return "Financial difference"

                                try:
                                    df_db["reason"] = df_db.get("field_name").apply(_mk_reason)
                                except Exception:
                                    df_db["reason"] = "Financial difference"

                                # Keep only the required output columns (no renames)
                                out_cols = [
                                    "tax_type",
                                    "tin",
                                    "taxpayer_name",
                                    "tax_period_year",
                                    "tax_period_month",
                                    "assessment_number",
                                    "field_name",
                                    "previous_value",
                                    "current_value",
                                    "difference",
                                    "reason",
                                ]
                                for c in out_cols:
                                    if c not in df_db.columns:
                                        df_db[c] = None
                                _store_encrypted_dataframe(public_output_dir, financial_difference_file, df_db[out_cols])
                    except Exception:
                        pass
        except Exception:
            financial_difference_file = None
            financial_difference_file_path = None

        return jsonify({
            'valid': True,
            'errors': errors if invalid_records > 0 else [],
            'total_records': total_records,
            'valid_records': valid_records,
            'invalid_records': invalid_records,
            'tin_invalid_count': tin_invalid_count,
            'db_duplicates_count': db_duplicates_count,
            'db_financial_differences_count': db_financial_differences_count,
            'db_financial_difference_fields_count': db_financial_difference_fields_count,
            'financial_difference_count': financial_difference_count,
            'financial_difference_file': financial_difference_file,
            'financial_difference_file_path': financial_difference_file_path,
            'validated_file': validated_file,
            'validated_file_path': validated_file_path,
            'removed_data_file': removed_file,
            'removed_data_file_path': removed_data_file_path,
            'output_dir': None,
        }), 200

    except Exception:
            return jsonify({
                'valid': False,
                'errors': [{'row': '', 'tin': '', 'column': '', 'reason': 'Validation failed'}],
                'total_records': 0,
                'valid_records': 0,
                'invalid_records': 0,
                'tin_invalid_count': 0,
                'validated_file': '',
                'removed_data_file': '',
                'validated_file_path': None,
                'removed_data_file_path': None,
                'financial_difference_count': 0,
                'financial_difference_file': None,
                'financial_difference_file_path': None,
            }), 200

    finally:
        try:
            if os.path.exists(saved_path):
                os.remove(saved_path)
        except Exception:
            pass


def _run_validation(tax):
    # GST must reuse the REAL GST preprocessing validation (no fuzzy mapping / no metadata)
    if tax == 'gst':
        return _run_gst_validation()

    if tax == 'swt':
        return _run_swt_validation()

    if tax == 'cit':
        return _run_cit_validation()

    # â”€â”€ Check 1: no file at all â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if 'file' not in request.files or request.files['file'].filename == '':
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']

    # â”€â”€ Check 2: wrong file type â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    fname = file.filename.lower()
    if not (fname.endswith('.csv') or fname.endswith('.parquet')):
        return jsonify({'error': 'Invalid file type. Only .csv or .parquet accepted'}), 400

    try:
        df = _load_uploaded_file(file)
    except Exception as e:
        return jsonify({'error': f'Could not read file: {str(e)}'}), 400

    row_count    = len(df)
    column_count = len(df.columns)

    if row_count == 0:
        return jsonify({
            'valid':         False,
            'row_count':     0,
            'column_count':  column_count,
            'columns_found': list(df.columns),
            'issues':        [{'type': 'empty_file',
                               'detail': 'Uploaded file contains no data rows'}],
        }), 200

    issues = VALIDATORS[tax](df)

    # Severity classification
    # missing_column / missing_critical_column â†’ error (blocks pipeline)
    # missing_expected_column â†’ warning (pipeline may still work)
    # column_remapped â†’ info (fuzzy match happened, just FYI)
    # everything else â†’ warning
    INFO_TYPES  = {'column_remapped'}
    ERROR_TYPES = {'missing_column', 'missing_critical_column'}
    WARN_TYPES  = {'missing_expected_column'}

    errors   = [i for i in issues if i['type'] in ERROR_TYPES]
    warnings = [i for i in issues if i['type'] in WARN_TYPES
                or (i['type'] not in ERROR_TYPES and i['type'] not in INFO_TYPES
                    and i not in errors)]
    infos    = [i for i in issues if i['type'] in INFO_TYPES]

    return jsonify({
        'valid':          len(errors) == 0,
        'pipeline':       tax.upper(),
        'filename':       file.filename,
        'row_count':      row_count,
        'column_count':   column_count,
        'columns_found':  list(df.columns),
        'error_count':    len(errors),
        'warning_count':  len(warnings),
        'info_count':     len(infos),
        'issues':         issues,       
        'errors':         errors,
        'warnings':       warnings,
        'infos':          infos,        
        'summary': (
            'File passed all validation checks â€” ready to process.'
            if len(errors) == 0 and len(warnings) == 0
            else f'{len(errors)} error(s) and {len(warnings)} warning(s) found.'
        ),
    }), 200


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Routes
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@validate_bp.route('/api/gst/validate', methods=['POST'])
def validate_gst():
    return _run_validation('gst')


@validate_bp.route('/api/cit/validate', methods=['POST'])
def validate_cit():
    return _run_validation('cit')


@validate_bp.route('/api/swt/validate', methods=['POST'])
def validate_swt():
    return _run_validation('swt')

