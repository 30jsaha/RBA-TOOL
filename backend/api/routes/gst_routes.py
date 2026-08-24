# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  api/routes/gst_routes.py
#  POST /api/gst/run
#  Accepts uploaded file + optional date range
#  Runs GST fraud pipeline and returns results as JSON
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

import os
import sys
import uuid
import time
import shutil
import threading
import tempfile
from datetime import datetime
from utils.upload_logger import log_gst_upload
from flask import Blueprint, request, jsonify, send_from_directory
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
from sqlalchemy import text
import pandas as pd


#  Allow imports from project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.db_config import get_mysql_engine
from utils.pipeline_logger import log_run_start, log_run_end, log_run_failed, log_step
from utils.auth_helper import get_authenticated_user_id, set_authenticated_user_id_for_context
from gst.gst_upload_hook import save_gst_justification_to_db

gst_bp = Blueprint('gst', __name__)

#  Store ongoing run statuses in memory
_run_status = {}


def _is_terminal_gst_status(status_value):
    return str(status_value or '').lower() in {'completed', 'failed'}


def _set_gst_run_status(run_id, updates, *, force=False):
    current = _run_status.get(run_id, {})
    if not force and _is_terminal_gst_status(current.get('status')):
        return current

    merged = {**current, **updates}
    if _is_terminal_gst_status(merged.get('status')):
        merged['progress'] = 100
        if str(merged.get('status', '')).lower() == 'completed':
            merged['step'] = 'Completed'
            total_rows = int(merged.get('total_rows') or 0)
            inserted_rows = int(merged.get('inserted_rows') or 0)
            if total_rows > 0 and inserted_rows <= 0:
                merged['inserted_rows'] = total_rows
            if total_rows > 0:
                merged['insert_percent'] = 100
        elif not merged.get('step'):
            merged['step'] = 'Failed'
    _run_status[run_id] = merged
    return merged

BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _save_validation_upload(file, tax_prefix: str):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = secure_filename(file.filename or "")
    saved_filename = f"{tax_prefix}_{timestamp}_{safe_name}"
    saved_path = os.path.join(UPLOAD_FOLDER, saved_filename)
    file.save(saved_path)

    ext = os.path.splitext(safe_name)[1].lower().lstrip(".")
    file_format = ext or None
    try:
        file_size_kb = round((os.path.getsize(saved_path) or 0) / 1024, 2)
    except Exception:
        file_size_kb = None

    return saved_filename, saved_path, file_format, file_size_kb


def _try_get_column_count_from_file(path: str) -> int:
    try:
        p = (path or "").lower()
        if p.endswith(".parquet"):
            df = pd.read_parquet(path)
            return int(len(df.columns))
        if p.endswith(".csv"):
            df = pd.read_csv(path, nrows=1, low_memory=False)
            return int(len(df.columns))
    except Exception:
        return 0
    return 0


def _try_insert_upload_history(engine, tax_type: str, filename: str, file_size_kb, file_format, row_count, column_count):
    try:
        with engine.begin() as conn:
            res = conn.execute(
                text(
                    """
                    INSERT INTO upload_history
                        (tax_type, filename, file_size_kb, file_format, row_count, column_count, uploaded_at,
                         status, error_message, pipeline_run, notes)
                    VALUES
                        (:tax_type, :filename, :file_size_kb, :file_format, :row_count, :column_count, NOW(),
                         'completed', NULL, 1, 'Validation upload')
                    """
                ),
                {
                    "tax_type": tax_type,
                    "filename": filename,
                    "file_size_kb": file_size_kb,
                    "file_format": file_format,
                    "row_count": row_count,
                    "column_count": column_count,
                },
            )
            return getattr(res, "lastrowid", None)
    except Exception as e:
        print(f"[GST_VALIDATE][DB] upload_history insert failed: {e}")
        return None


def _try_update_upload_history_counts(engine, upload_history_id, row_count, column_count):
    try:
        if not upload_history_id:
            return False
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE upload_history
                    SET row_count = :row_count,
                        column_count = :column_count
                    WHERE id = :id
                    """
                ),
                {"id": upload_history_id, "row_count": row_count, "column_count": column_count},
            )
        return True
    except Exception as e:
        print(f"[VALIDATE][DB] upload_history update failed: {e}")
        return False

def _try_insert_validation_summary(engine, upload_history_id, tax_type: str, payload: dict, user_id):
    try:
        with engine.begin() as conn:
            res = conn.execute(
                text(
                    """
                    INSERT INTO upload_validation_summary
                        (upload_history_id, file_type, total_rows, valid_records, invalid_records_count,
                         duplicate_records_count, db_financial_difference_fields_count, db_financial_differences_count,
                         db_duplicates_count, error_count, validation_status, missing_tin_count,
                         invalid_records_file, duplicate_records_file, created_at, user_id)
                    VALUES
                        (:upload_history_id, :file_type, :total_rows, :valid_records, :invalid_records_count,
                         :duplicate_records_count, :db_financial_difference_fields_count, :db_financial_differences_count,
                         :db_duplicates_count, :error_count, :validation_status, :missing_tin_count,
                         :invalid_records_file, :duplicate_records_file,
                         NOW(), :user_id)
                    """
                ),
                {
                    "upload_history_id": upload_history_id,
                    "file_type": tax_type,
                    "total_rows": payload.get("total_records", 0),
                    "valid_records": payload.get("valid_records", 0),
                    "invalid_records_count": payload.get("invalid_records", 0),
                    "duplicate_records_count": payload.get("db_duplicates_count", 0),
                    "db_financial_difference_fields_count": payload.get("db_financial_difference_fields_count", 0),
                    "db_financial_differences_count": payload.get("db_financial_differences_count", 0),
                    "db_duplicates_count": payload.get("db_duplicates_count", 0),
                    "error_count": len(payload.get("errors") or []),
                    "validation_status": "success" if bool(payload.get("valid")) else "failed",
                    "missing_tin_count": payload.get("tin_invalid_count", 0),
                    "invalid_records_file": payload.get("removed_data_file_path"),
                    "duplicate_records_file": payload.get("financial_difference_file_path"),
                    "user_id": user_id,
                },
            )
            return getattr(res, "lastrowid", None)
    except Exception as e:
        print(f"[GST_VALIDATE][DB] upload_validation_summary insert failed: {e}")
        return None


def _try_fetch_summary_counts(engine, upload_history_id, tax_type: str, user_id):
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT total_rows, valid_records, invalid_records_count, missing_tin_count,
                           duplicate_records_count,
                           db_financial_difference_fields_count, db_financial_differences_count, db_duplicates_count
                    FROM upload_validation_summary
                    WHERE upload_history_id = :upload_history_id
                      AND user_id = :user_id
                      AND file_type = :file_type
                    LIMIT 1
                    """
                ),
                {
                    "upload_history_id": upload_history_id,
                    "user_id": user_id,
                    "file_type": tax_type,
                },
            ).mappings().first()
        if not row:
            return None
        return {
            "total_records": row.get("total_rows"),
            "valid_records": row.get("valid_records"),
            "invalid_records": row.get("invalid_records_count"),
            "tin_invalid_count": row.get("missing_tin_count"),
            "db_duplicates_count": row.get("db_duplicates_count"),
            "db_financial_difference_fields_count": row.get("db_financial_difference_fields_count"),
            "db_financial_differences_count": row.get("db_financial_differences_count"),
        }
    except Exception as e:
        print(f"[GST_VALIDATE][DB] summary fetch failed: {e}")
        return None


def _try_insert_validation_errors(engine, upload_validation_summary_id, upload_history_id, tax_type: str, user_id, errors):
    try:
        if not upload_validation_summary_id:
            return False
        rows = []
        for e in (errors or []):
            rows.append({
                "upload_validation_summary_id": upload_validation_summary_id,
                "upload_history_id": upload_history_id,
                "user_id": user_id,
                "file_type": tax_type,
                "row_number": e.get("row") or 0,
                "tin": e.get("tin"),
                "column_name": e.get("column"),
                "reason": e.get("reason"),
            })
        if not rows:
            return True
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO upload_validation_errors
                        (upload_validation_summary_id, upload_history_id, user_id, file_type,
                         row_number, tin, column_name, reason, created_at)
                    VALUES
                        (:upload_validation_summary_id, :upload_history_id, :user_id, :file_type,
                         :row_number, :tin, :column_name, :reason, NOW())
                    """
                ),
                rows,
            )
        return True
    except Exception as ex:
        print(f"[GST_VALIDATE][DB] upload_validation_errors insert failed: {ex}")
        return False


def _try_fetch_validation_errors(engine, upload_validation_summary_id):
    try:
        if not upload_validation_summary_id:
            return []
        with engine.begin() as conn:
            res = conn.execute(
                text(
                    """
                    SELECT row_number, tin, column_name, reason
                    FROM upload_validation_errors
                    WHERE upload_validation_summary_id = :upload_validation_summary_id
                    ORDER BY id ASC
                    """
                ),
                {"upload_validation_summary_id": upload_validation_summary_id},
            ).mappings().all()
        out = []
        for r in res or []:
            out.append({
                "row": r.get("row_number"),
                "tin": r.get("tin") or "",
                "column": r.get("column_name") or "",
                "reason": r.get("reason") or "",
            })
        return out
    except Exception as ex:
        print(f"[GST_VALIDATE][DB] upload_validation_errors fetch failed: {ex}")
        return []


def _try_zero_db_counts_if_fraud_table_empty(engine, tax_type: str, user_id, payload: dict):
    """
    Correct false DB-duplicate/financial-difference counts when the corresponding
    fraud table is empty for the current user.

    This does NOT change validation logic; it only changes count sourcing to DB.
    """
    try:
        table_map = {
            "gst": "gst_fraud_justification",
            "swt": "swt_fraud_justification",
            "cit": "cit_fraud_justification",
        }
        table = table_map.get(str(tax_type or "").lower())
        if not table:
            return
        with engine.connect() as conn:
            cnt = conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE user_id = :user_id"),
                {"user_id": user_id},
            ).scalar()
        cnt = int(cnt or 0)
        if cnt == 0:
            payload["db_duplicates_count"] = 0
            payload["db_financial_differences_count"] = 0
            payload["db_financial_difference_fields_count"] = 0
            payload["financial_difference_count"] = 0
            payload["financial_difference_file"] = None
            payload["financial_difference_file_path"] = None
    except Exception as e:
        print(f"[VALIDATE][DB] fraud-table count check failed: {e}")


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

        from sqlalchemy import text as _text, bindparam
        from config.db_config import get_mysql_engine as _get_mysql_engine

        engine = None
        rows = []
        try:
            engine = _get_mysql_engine()
            with engine.connect() as conn:
                cols_res = conn.execute(_text(
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
                q = _text(
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


def _allowed_file(filename):
    return filename.lower().endswith(('.csv', '.parquet'))


def run_gst_preprocessing(saved_path, analyzer=None, on_step=None, make_timestamped_copies=False, upload_history_id=None):
    """
    Reusable GST preprocessing (single source of truth).
    Runs ONLY existing GST business flow:
      1) Column Standardization
      2) Data Validation (includes temp insert + CSV generation as implemented)

    Returns a dict with summary counts + row-level errors extracted from existing
    GST outputs (gst_removed_data.csv / gst_validation_log.txt). Does NOT delete
    the uploaded source file.
    """
    import re as _re
    import pandas as _pd

    original_dir = os.getcwd()
    gst_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'gst')
    gst_dir_abs = os.path.abspath(gst_dir)
    public_output_dir = os.path.abspath(os.path.join(gst_dir_abs, 'final_output'))

    sys.path.insert(0, gst_dir_abs)
    os.chdir(gst_dir_abs)
    try:
        from gst.gst_registration_merger import merge_taxpayer_names
        if analyzer is None:
            from gst.gst_fraud_pipeline_with_timer import GSTAnalysis
            analyzer = GSTAnalysis()
            # Force GSTAnalysis to process the exact uploaded file; prevents it from
            # accidentally selecting older/other files in gst/data via mtime scanning.
            analyzer.input_file = saved_path
            analyzer.data_dir = os.path.dirname(saved_path)
            analyzer.script_dir = gst_dir_abs
            analyzer.models_dir = os.path.join(analyzer.script_dir, 'models')
            analyzer.output_dir = os.path.join(analyzer.script_dir, 'final_output')
            # Use a per-request temp output dir to avoid concurrent overwrites of shared filenames.
            # Final (public) outputs are still copied into `<tax>/final_output/` with unique names.
            if upload_history_id:
                try:
                    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
                    tmp_root = os.path.join(backend_dir, 'uploads', '_validation_tmp')
                    os.makedirs(tmp_root, exist_ok=True)
                    analyzer.output_dir = os.path.join(tmp_root, f'gst_{int(upload_history_id)}')
                except Exception:
                    analyzer.output_dir = os.path.join(analyzer.output_dir, 'tmp_validation')
            os.makedirs(analyzer.output_dir, exist_ok=True)
        else:
            # If caller provided analyzer, still prefer explicit input.
            try:
                analyzer.input_file = saved_path
            except Exception:
                pass

        if callable(on_step):
            on_step('started', 1, 'Column Standardization', None)

        #  Delete stale output artifacts BEFORE this validation run starts.
        # NOTE: step1 generates `gst_standardized.csv` which step2 consumes, so cleanup
        # must run before step1 (not between step1 and step2).
        try:
            stale_files = [
                'gst_validation_log.txt',
                'gst_removed_data.csv',
                'gst_validated.csv',
                'gst_standardized.csv',
            ]
            for file_name in stale_files:
                file_path = os.path.join(analyzer.output_dir, file_name)
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        print(f"[GST_VALIDATE] Removed stale file: {file_name}")
                    except Exception as e:
                        print(f"[GST_VALIDATE] Failed removing {file_name}: {e}")
        except Exception as e:
            print(f"[GST_VALIDATE] Cleanup failed: {e}")

        def _parse_log_rows(path):
            items = []
            try:
                import re as _re
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        # Supports lines like:
                        # "2026-05-08 ... - Row 12: TIN '12345' has wrong length ..."
                        m = _re.search(r'Row\s+(\d+):\s*(.+)', line.strip())
                        if m:
                            items.append((int(m.group(1)), m.group(2)))
            except Exception:
                return []
            return items

        def _guess_column(message):
            import re as _re
            msg = (message or "").lower()
            patterns = [
                (r'tin', 'TIN'),
                (r'duplicate gst record already exists in gst_fraud_justification', 'DBValidation'),
                (r'taxpayer type', 'TaxpayerType'),
                (r'assessment number', 'AssessmentNumber'),
                (r'tax account number|tax_account_number|tax_account_no', 'TaxAccountNumber'),
                (r'tax period year|tax year', 'TaxPeriodYear'),
                (r'tax period month|tax month', 'TaxPeriodMonth'),
                (r'sum difference|tolerance', 'AddExemptAndZeroRatedSales'),
                (r'\bsales\b', 'SalesValidation'),
                (r'financial values differ from existing gst_fraud_justification record', 'DBValidation'),
                (r'financial differences found against gst_fraud_justification', 'DBValidation'),
            ]
            for pat, col in patterns:
                if _re.search(pat, msg):
                    return col
            return ''

        def _parse_log_counts(path):
            """
            Parse retained/removed counts from gst_validation_log.txt.
            Returns (retained:int|None, removed:int|None)
            """
            retained = None
            removed = None
            try:
                import re as _re
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        m1 = _re.search(r'Records retained:\s*(\d+)', line)
                        if m1:
                            retained = int(m1.group(1))
                        m2 = _re.search(r'Records removed:\s*(\d+)', line)
                        if m2:
                            removed = int(m2.group(1))
            except Exception:
                return None, None
            return retained, removed

        def _errors_from_log(output_dir):
            log_path = os.path.join(output_dir, 'gst_validation_log.txt')
            standardized_csv = os.path.join(output_dir, 'gst_standardized.csv')
            if not os.path.exists(log_path):
                return []

            std_df = None
            try:
                if os.path.exists(standardized_csv):
                    std_df = _pd.read_csv(standardized_csv)
            except Exception:
                std_df = None

            errors = []
            for row_num, msg in _parse_log_rows(log_path):
                # Clean reason: keep the exact message after "Row N:"
                reason = (msg or "").strip()

                # Prefer extracting TIN from the message itself
                tin_val = ''
                try:
                    import re as _re
                    m_tin = _re.search(r"\bTIN\s+'?(\d+)'?", reason, flags=_re.IGNORECASE)
                    if m_tin:
                        tin_val = m_tin.group(1)
                except Exception:
                    tin_val = ''
                if tin_val == '' and std_df is not None and 'tin' in std_df.columns:
                    try:
                        if 0 <= row_num < len(std_df):
                            v = std_df.iloc[row_num].get('tin')
                        elif 1 <= row_num <= len(std_df):
                            v = std_df.iloc[row_num - 1].get('tin')
                        else:
                            v = None
                        tin_val = '' if _pd.isna(v) else str(v)
                    except Exception:
                        tin_val = ''
                errors.append({
                    'row': int(row_num),
                    'tin': tin_val,
                    'column': _guess_column(msg),
                    'reason': reason,
                })
            return errors

        t0 = time.time()
        ok1 = analyzer.step1_column_standardization()
        step1_elapsed = round(time.time() - t0, 2)
        if callable(on_step):
            on_step('completed' if ok1 else 'failed', 1, 'Column Standardization', step1_elapsed)
        if not ok1:
            errors = _errors_from_log(analyzer.output_dir)
            return {
                'ok': False,
                'error': 'Column standardization failed',
                'analyzer': analyzer,
                'step1_ok': False,
                'step2_ok': False,
                'step1_elapsed': step1_elapsed,
                'step2_elapsed': 0,
                'errors': errors,
            }

        if callable(on_step):
            on_step('started', 2, 'Data Validation', None)
        t1 = time.time()

        # TEMP DEBUG (guarded): help diagnose false DB duplicates.
        # Does not change validation logic.
        try:
            if os.getenv("GST_DUP_DEBUG", "").strip() in ("1", "true", "TRUE", "yes", "YES"):
                engine_dbg = None
                try:
                    engine_dbg = get_mysql_engine()
                    with engine_dbg.connect() as conn_dbg:
                        dbn = conn_dbg.execute(text("SELECT DATABASE()")).scalar()
                        cnt = conn_dbg.execute(text("SELECT COUNT(*) FROM gst_fraud_justification")).scalar()
                        print(f"[GST_DUP_DEBUG][BEFORE step2] database={dbn} gst_fraud_justification_count={cnt}")
                finally:
                    try:
                        if engine_dbg:
                            engine_dbg.dispose()
                    except Exception:
                        pass
        except Exception:
            pass

        ok2 = analyzer.step2_data_validation()

        try:
            if os.getenv("GST_DUP_DEBUG", "").strip() in ("1", "true", "TRUE", "yes", "YES"):
                engine_dbg2 = None
                try:
                    engine_dbg2 = get_mysql_engine()
                    with engine_dbg2.connect() as conn_dbg2:
                        dbn2 = conn_dbg2.execute(text("SELECT DATABASE()")).scalar()
                        cnt2 = conn_dbg2.execute(text("SELECT COUNT(*) FROM gst_fraud_justification")).scalar()
                        print(f"[GST_DUP_DEBUG][AFTER step2] database={dbn2} gst_fraud_justification_count={cnt2}")
                finally:
                    try:
                        if engine_dbg2:
                            engine_dbg2.dispose()
                    except Exception:
                        pass
        except Exception:
            pass

        step2_elapsed = round(time.time() - t1, 2)
        if callable(on_step):
            on_step('completed' if ok2 else 'failed', 2, 'Data Validation', step2_elapsed)
        if not ok2:
            errors = _errors_from_log(analyzer.output_dir)
            return {
                'ok': False,
                'error': 'Data validation failed',
                'analyzer': analyzer,
                'step1_ok': True,
                'step2_ok': False,
                'step1_elapsed': step1_elapsed,
                'step2_elapsed': step2_elapsed,
                'errors': errors,
            }

        output_dir = analyzer.output_dir
        validated_csv = os.path.join(output_dir, 'gst_validated.csv')
        removed_csv = os.path.join(output_dir, 'gst_removed_data.csv')
        standardized_csv = os.path.join(output_dir, 'gst_standardized.csv')
        log_path = os.path.join(output_dir, 'gst_validation_log.txt')

        std_df = None
        try:
            if os.path.exists(standardized_csv):
                std_df = _pd.read_csv(standardized_csv)
        except Exception:
            std_df = None

        # NOTE: taxpayer-name merge is intentionally NOT applied to removed rows here.
        # The validator runs TIN-first validation and merges taxpayer names only for valid TIN rows.

        valid_records = 0
        try:
            if os.path.exists(validated_csv):
                valid_records = int(len(_pd.read_csv(validated_csv)))
        except Exception:
            valid_records = 0

        invalid_records = 0
        removed_df = None
        try:
            if os.path.exists(removed_csv):
                removed_df = _pd.read_csv(removed_csv)
                invalid_records = int(len(removed_df))
        except Exception:
            removed_df = None
            invalid_records = 0

        # Primary source of truth for counts: gst_validation_log.txt.
        # The pipeline does not overwrite gst_removed_data.csv when there are 0 removals,
        # so stale files can exist. Use log counts when available.
        if os.path.exists(log_path):
            retained_cnt, removed_cnt = _parse_log_counts(log_path)
            if retained_cnt is not None and removed_cnt is not None:
                valid_records = int(retained_cnt)
                invalid_records = int(removed_cnt)

        # Totals must always be consistent:
        total_records = int(valid_records) + int(invalid_records)

        # Copy log/CSV into unique filenames for this upload_history_id (optional, avoids any overwrites).
        try:
            if upload_history_id:
                for src_name, dst_name in [
                    ("gst_validation_log.txt", f"gst_validation_log_{upload_history_id}.txt"),
                    ("gst_removed_data.csv", f"gst_removed_data_{upload_history_id}.csv"),
                    ("gst_validated.csv", f"gst_validated_{upload_history_id}.csv"),
                ]:
                    src_path = os.path.join(analyzer.output_dir, src_name)
                    dst_path = os.path.join(analyzer.output_dir, dst_name)
                    if os.path.exists(src_path):
                        try:
                            shutil.copy2(src_path, dst_path)
                        except Exception:
                            pass
        except Exception:
            pass

        # Primary source of truth for validation reasons: gst_validation_log.txt
        errors = []
        if invalid_records > 0 and os.path.exists(log_path):
            errors = _errors_from_log(output_dir)
            try:
                if os.getenv("GST_DUP_DEBUG", "").strip() in ("1", "true", "TRUE", "yes", "YES"):
                    dup_like = [
                        e for e in (errors or [])
                        if "duplicate gst record already exists in gst_fraud_justification"
                        in str(e.get("reason") or "").lower()
                    ]
                    print("[GST_DUP_DEBUG] errors_total=", 0 if errors is None else len(errors))
                    print("[GST_DUP_DEBUG] dup_reason_rows=", len(dup_like))
                    if len(dup_like) > 0:
                        print("[GST_DUP_DEBUG] dup_reason_sample=", dup_like[:3])
            except Exception:
                pass

        # Fallback: structured reason column from removed CSV (if the validator emitted it)
        if len(errors) == 0 and removed_df is not None:
            reason_col = None
            for c in ['rejection_reason', 'reason', 'validation_reason', 'error_reason']:
                if c in removed_df.columns:
                    reason_col = c
                    break
            if reason_col is not None:
                for idx, row in removed_df.iterrows():
                    tin_val = ''
                    if 'tin' in removed_df.columns:
                        v = row.get('tin')
                        tin_val = '' if _pd.isna(v) else str(v)
                    msg = '' if _pd.isna(row.get(reason_col)) else str(row.get(reason_col))
                    errors.append({
                        'row': int(idx) + 1,
                        'tin': tin_val,
                        'column': _guess_column(msg),
                        'reason': msg,
                    })

        # If log parsing still produced nothing, keep errors as-is (may be empty).

        tin_invalid_count = 0
        if errors:
            # Count ONLY true invalid TIN *format* rows (strictly: 9 digits, first digit != 0).
            # Do not count other "TIN-related" reasons (e.g., sequence checks) per API contract.
            import re as _re

            _TIN_REGEX = _re.compile(r'^[1-9]\d{8}$')

            def _normalize_tin(v):
                if v is None:
                    return ''
                try:
                    s = str(v).strip()
                except Exception:
                    return ''
                if s.endswith('.0') and s[:-2].isdigit():
                    s = s[:-2]
                s = s.replace(' ', '')
                return s

            tin_rows = set()
            for e in errors:
                reason_l = str(e.get('reason') or '').lower()

                # Exclude DB-level validations explicitly
                if 'duplicate gst record already exists in gst_fraud_justification' in reason_l:
                    continue
                if 'financial values differ from existing gst_fraud_justification record' in reason_l:
                    continue
                if 'financial differences found against gst_fraud_justification' in reason_l:
                    continue

                tin_s = _normalize_tin(e.get('tin'))

                # Treat null/empty as invalid format.
                if tin_s == '':
                    # Only count when this error row is actually about TIN validity.
                    if 'tin' in reason_l:
                        tin_rows.add(e.get('row'))
                    continue

                # Strict format check
                if not _TIN_REGEX.match(tin_s):
                    tin_rows.add(e.get('row'))

            tin_invalid_count = len([r for r in tin_rows if isinstance(r, int)])

        # DB-validation counters (derived from row-level reasons)
        db_duplicates_count = 0
        db_financial_differences_count = 0
        db_financial_difference_fields_count = 0
        if errors:
            for e in errors:
                reason = str(e.get('reason') or '').lower()
                if 'duplicate gst record already exists in gst_fraud_justification' in reason:
                    db_duplicates_count += 1
                elif 'financial values differ from existing gst_fraud_justification record' in reason:
                    db_financial_differences_count += 1
                elif 'financial differences found against gst_fraud_justification' in reason:
                    db_financial_differences_count += 1

        # Total changed financial fields across ALL conflict records (optional; depends on validator output)
        try:
            if removed_df is not None and len(removed_df) > 0 and 'db_financial_difference_fields_count' in removed_df.columns:
                if 'reason' in removed_df.columns:
                    mask = removed_df['reason'].astype(str).str.contains(
                        'Financial differences found against gst_fraud_justification', case=False, na=False
                    )
                    db_financial_difference_fields_count = int(
                        _pd.to_numeric(removed_df.loc[mask, 'db_financial_difference_fields_count'], errors='coerce')
                        .fillna(0)
                        .sum()
                    )
                else:
                    db_financial_difference_fields_count = int(
                        _pd.to_numeric(removed_df['db_financial_difference_fields_count'], errors='coerce')
                        .fillna(0)
                        .sum()
                    )
        except Exception:
            db_financial_difference_fields_count = 0

        # Add "reason" column to removed CSV (derived from log errors; does not change removals)
        try:
            if removed_df is not None and invalid_records > 0:
                reason_map = {}
                for e in errors:
                    tin_key = str(e.get('tin') or '').strip()
                    if tin_key == '':
                        continue
                    reason_txt = str(e.get('reason') or '').strip()
                    if reason_txt == '':
                        continue
                    if tin_key in reason_map and reason_map[tin_key] != reason_txt:
                        reason_map[tin_key] = f"{reason_map[tin_key]}; {reason_txt}"
                    else:
                        reason_map[tin_key] = reason_txt

                if 'tin' in removed_df.columns:
                    mapped = removed_df['tin'].astype(str).map(reason_map)
                    if 'reason' in removed_df.columns:
                        removed_df['reason'] = removed_df['reason'].fillna(mapped)
                    else:
                        removed_df['reason'] = mapped
                else:
                    if 'reason' not in removed_df.columns:
                        removed_df['reason'] = None

                removed_df.to_csv(removed_csv, index=False)
        except Exception:
            pass

        # Timestamped copies for validation endpoint (avoid overwriting static filenames)
        validated_file_name = 'gst_validated.csv'
        removed_file_name = 'gst_removed_data.csv'

        # Always compute full absolute paths for API consumers (frontend/debug/download)
        validated_file_full_path = None
        removed_file_full_path = None

        try:
            os.makedirs(public_output_dir, exist_ok=True)

            if make_timestamped_copies:
                stamp = datetime.now().strftime('%Y%m%d_%H%M%S')

                if os.path.exists(validated_csv):
                    validated_file_name = f'gst_validated_{stamp}.csv'
                    validated_file_full_path = os.path.abspath(os.path.join(public_output_dir, validated_file_name))
                    shutil.copy2(validated_csv, validated_file_full_path)

                if os.path.exists(removed_csv):
                    removed_file_name = f'gst_removed_data_{stamp}.csv'
                    removed_file_full_path = os.path.abspath(os.path.join(public_output_dir, removed_file_name))
                    shutil.copy2(removed_csv, removed_file_full_path)

            # Fall back to static filenames when timestamped copies are not created.
            if validated_file_full_path is None:
                candidate = os.path.abspath(os.path.join(public_output_dir, validated_file_name))
                validated_file_full_path = candidate if os.path.exists(candidate) else None

            if removed_file_full_path is None:
                candidate = os.path.abspath(os.path.join(public_output_dir, removed_file_name))
                removed_file_full_path = candidate if os.path.exists(candidate) else None

        except Exception as e:
            print(f"[GST] Error creating timestamped copies: {e}")

        print(f"[GST] validated_file_full_path: {validated_file_full_path}")
        print(f"[GST] removed_file_full_path: {removed_file_full_path}")

        return {
            'ok': True,
            'analyzer': analyzer,
            'total_records': total_records,
            'valid_records': valid_records,
            'invalid_records': invalid_records,
            'tin_invalid_count': tin_invalid_count,
            'db_duplicates_count': int(db_duplicates_count),
            'db_financial_differences_count': int(db_financial_differences_count),
            'db_financial_difference_fields_count': int(db_financial_difference_fields_count),
            'errors': errors,
            'validated_file': validated_file_name,
            'validated_file_full_path': validated_file_full_path,
            'removed_data_file': removed_file_name,
            'removed_file_full_path': removed_file_full_path,
            'output_dir': os.path.abspath(public_output_dir),
        }

    finally:
        os.chdir(original_dir)
        try:
            if upload_history_id and analyzer is not None and getattr(analyzer, "output_dir", None):
                tmp_dir = os.path.abspath(str(analyzer.output_dir))
                if os.path.basename(tmp_dir).startswith("gst_") and os.path.sep + "_validation_tmp" + os.path.sep in (os.path.sep + tmp_dir + os.path.sep):
                    shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


@gst_bp.route('/api/gst/validate', methods=['POST'])
@jwt_required()
def validate_gst():
    user_id = get_jwt_identity()
    try:
        if os.getenv("GST_VALIDATE_DB_DEBUG", "").strip() in ("1", "true", "TRUE", "yes", "YES"):
            engine_dbg = None
            try:
                engine_dbg = get_mysql_engine()
                with engine_dbg.connect() as conn:
                    dbn = conn.execute(text("SELECT DATABASE()")).scalar()
                    cnt = conn.execute(text("SELECT COUNT(*) FROM gst_fraud_justification")).scalar()
                    print(f"[GST_VALIDATE_DB_DEBUG] database={dbn} gst_fraud_justification_count={cnt}")
            finally:
                try:
                    if engine_dbg:
                        engine_dbg.dispose()
                except Exception:
                    pass
    except Exception:
        pass

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'valid': False, 'error': 'No file uploaded'}), 400

    fname = file.filename.lower()
    if not (fname.endswith('.csv') or fname.endswith('.parquet')):
        return jsonify({'valid': False, 'error': 'Only .csv or .parquet files are accepted'}), 400

    saved_path_processing = None
    upload_saved_filename = None
    upload_saved_path = None
    file_format = None
    file_size_kb = None

    gst_data_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', 'gst', 'data')
    )
    os.makedirs(gst_data_dir, exist_ok=True)

    import werkzeug.utils
    processing_name = werkzeug.utils.secure_filename(file.filename)
    saved_path_processing = os.path.join(gst_data_dir, processing_name)

    try:
        upload_saved_filename, upload_saved_path, file_format, file_size_kb = _save_validation_upload(file, "gst")
        try:
            file.stream.seek(0)
        except Exception:
            pass

        try:
            shutil.copyfile(upload_saved_path, saved_path_processing)
        except Exception:
            file.save(saved_path_processing)

        # Insert upload_history first so we can isolate outputs by upload_history_id (concurrency-safe).
        upload_history_id = None
        engine_pre = None
        try:
            engine_pre = get_mysql_engine()
            column_count_pre = _try_get_column_count_from_file(upload_saved_path)
            upload_history_id = _try_insert_upload_history(
                engine_pre,
                "gst",
                upload_saved_filename,
                file_size_kb,
                file_format,
                0,
                column_count_pre,
            )
        except Exception as e:
            print(f"[GST_VALIDATE][DB] pre-validation upload_history insert failed: {e}")
        finally:
            try:
                if engine_pre:
                    engine_pre.dispose()
            except Exception:
                pass

        result = run_gst_preprocessing(saved_path_processing, make_timestamped_copies=True, upload_history_id=upload_history_id)
        if not result.get('ok'):
            errors = result.get('errors') or []
            if not errors:
                errors = [{
                    'row': '',
                    'tin': '',
                    'column': '',
                    'reason': result.get('error', 'Validation failed'),
                }]
            #return jsonify({'valid': False, 'error_count': len(errors), 'errors': errors}), 200
            return jsonify({
                'valid': False,
                'total_records': result.get('total_records', 0),
                'valid_records': result.get('valid_records', 0),
                'invalid_records': result.get('invalid_records', len(errors)),
                'tin_invalid_count': result.get('tin_invalid_count', 0),
                'db_duplicates_count': result.get('db_duplicates_count', 0),
                'db_financial_differences_count': result.get('db_financial_differences_count', 0),
                'db_financial_difference_fields_count': result.get('db_financial_difference_fields_count', 0),
                'error_count': len(errors),
                'errors': errors
            }), 200

        print("[GST VALIDATION RESULT]")
        print(result)
        
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
            'validated_file_path': result.get('validated_file_full_path'),
            'removed_data_file': result.get('removed_data_file', 'gst_removed_data.csv'),
            'removed_data_file_path': result.get('removed_file_full_path'),
            'output_dir': result.get('output_dir'),
            'errors': result.get('errors', []),
        }

        payload['financial_difference_count'] = int(payload.get('db_financial_differences_count') or 0)
        payload['financial_difference_file'] = None
        payload['financial_difference_file_path'] = None
        try:
            if payload.get('removed_data_file_path') and payload.get('output_dir'):
                removed_path = payload.get('removed_data_file_path')
                conflict_tins = []
                try:
                    use_cols = ["tin", "reason", "taxpayer_name"]
                    df_removed = pd.read_csv(removed_path, usecols=lambda c: c in use_cols, low_memory=False)
                    if "reason" in df_removed.columns:
                        mask = df_removed["reason"].astype(str).str.lower().str.contains(
                            "financial differences found against gst_fraud_justification", na=False
                        )
                        df_fin = df_removed.loc[mask]
                        if "tin" in df_fin.columns:
                            conflict_tins = df_fin["tin"].dropna().tolist()
                except Exception:
                    conflict_tins = []

                if payload['financial_difference_count'] > 0:
                    ts2 = datetime.now().strftime('%Y%m%d_%H%M%S')
                    payload['financial_difference_file'] = f'gst_financial_difference_{ts2}.csv'
                    payload['financial_difference_file_path'] = os.path.abspath(
                        os.path.join(payload.get('output_dir'), payload.get('financial_difference_file'))
                    )
                    _export_upload_conflicts_csv_from_db(
                        "GST",
                        conflict_tins,
                        payload['financial_difference_file_path'],
                    )
        except Exception:
            payload['financial_difference_file'] = None
            payload['financial_difference_file_path'] = None

        print("[VALIDATE API] validated_file_path =", result.get('validated_file_full_path'))

        errors = result.get('errors') or []
        if payload['invalid_records'] > 0:
            payload['errors'] = errors
        else:
            payload['errors'] = []

        upload_validation_summary_id = None
        engine = None
        try:
            engine = get_mysql_engine()
            column_count = _try_get_column_count_from_file(upload_saved_path)
            if upload_history_id:
                _try_update_upload_history_counts(
                    engine,
                    upload_history_id,
                    payload.get("total_records", 0),
                    column_count,
                )
                upload_validation_summary_id = _try_insert_validation_summary(engine, upload_history_id, "gst", payload, user_id)
                _try_insert_validation_errors(
                    engine,
                    upload_validation_summary_id,
                    upload_history_id,
                    "gst",
                    user_id,
                    payload.get("errors") or [],
                )

                # DB-driven response: overwrite count fields + errors from DB.
                db_counts = _try_fetch_summary_counts(engine, upload_history_id, "gst", user_id)
                if db_counts:
                    for k in (
                        "total_records",
                        "valid_records",
                        "invalid_records",
                        "tin_invalid_count",
                        "db_duplicates_count",
                        "db_financial_difference_fields_count",
                        "db_financial_differences_count",
                    ):
                        if db_counts.get(k) is not None:
                            payload[k] = db_counts.get(k)

                    # Keep parity field derived from db_financial_differences_count
                    payload["financial_difference_count"] = int(payload.get("db_financial_differences_count") or 0)

                payload["errors"] = _try_fetch_validation_errors(engine, upload_validation_summary_id)
        except Exception as e:
            print(f"[GST_VALIDATE][DB] post-validation DB operations failed: {e}")
        finally:
            try:
                if engine:
                    engine.dispose()
            except Exception:
                pass

        return jsonify(payload), 200

    except Exception as e:
        try:
            import traceback
            print("[GST_VALIDATE] Exception:\n" + traceback.format_exc())
            if os.getenv("AUTH_DEBUG", "").strip() == "1":
                try:
                    fsz = os.path.getsize(saved_path_processing) if saved_path_processing and os.path.exists(saved_path_processing) else None
                except Exception:
                    fsz = None
                print(f"[GST_VALIDATE] saved_path={saved_path_processing} size_bytes={fsz} content_type={request.content_type}")
        except Exception:
            pass
        if os.getenv("AUTH_DEBUG", "").strip() == "1":
            return jsonify({'valid': False, 'error': f'Could not read file: {str(e)}'}), 400
        return jsonify({'valid': False, 'error': 'Could not read file'}), 400

    finally:
        try:
            if saved_path_processing and os.path.exists(saved_path_processing):
                os.remove(saved_path_processing)
        except Exception:
            pass


@gst_bp.route('/api/gst/download/<path:filename>', methods=['GET'])
@jwt_required()
def download_gst_file(filename):
    """
    Secure download endpoint for files in backend/gst/final_output.
    """
    try:
        safe_name = secure_filename(filename)
        if not safe_name:
            return jsonify({"success": False, "message": "Invalid filename"}), 400

        allowed_extensions = {'.csv', '.txt', '.xlsx', '.parquet'}
        ext = os.path.splitext(safe_name)[1].lower()
        if ext not in allowed_extensions:
            return jsonify({"success": False, "message": "Invalid file type"}), 400

        if not safe_name.startswith("gst_"):
            return jsonify({"success": False, "message": "Invalid filename"}), 400

        # NOTE: This file lives under `backend/api/routes/`. We want the real outputs
        # folder at `backend/gst/final_output` (not `<repo_root>/gst/final_output`).
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        output_dir = os.path.abspath(os.path.join(backend_dir, 'gst', 'final_output'))
        os.makedirs(output_dir, exist_ok=True)

        candidate = os.path.abspath(os.path.join(output_dir, safe_name))
        print("[DOWNLOAD API] file_path =", candidate)

        if os.path.commonpath([candidate, output_dir]) != output_dir:
            return jsonify({"success": False, "message": "Invalid filename"}), 400

        if not os.path.exists(candidate):
            return jsonify({"success": False, "message": "File not found", "filename": safe_name}), 404

        return send_from_directory(output_dir, safe_name, as_attachment=True)

    except Exception as e:
        print("[DOWNLOAD ERROR]", str(e))
        return jsonify({"success": False, "message": str(e)}), 500


def _run_gst_pipeline(run_id, saved_path, date_from, date_to, current_user_id=None, is_validated_file=False):
    """
    Runs the GST pipeline in a background thread.
    Updates _run_status[run_id] at each step.
    """
    engine = None
    start_total = time.time()
    original_dir = os.getcwd()   # captured BEFORE try so finally can always restore it

    try:
        # Propagate authenticated user_id into this background thread (NULL-safe).
        set_authenticated_user_id_for_context(current_user_id)

        engine = get_mysql_engine()
        log_run_start(engine, run_id, 'GST', filename=os.path.basename(saved_path))
        log_gst_upload(engine, 
               filename=os.path.basename(saved_path),
               filepath=saved_path,
               status='Success',
               pipeline_run=True)
        _set_gst_run_status(run_id, {'status': 'running', 'step': 'Initialising', 'progress': 0})

        #  Shared preprocessing (same as /api/gst/validate)
        gst_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'gst')
        sys.path.insert(0, os.path.abspath(gst_dir))
        original_dir = os.getcwd()
        os.chdir(os.path.abspath(gst_dir))
        from gst.gst_fraud_pipeline_with_timer import GSTAnalysis
        analyzer = GSTAnalysis()
        analyzer.data_dir = os.path.dirname(saved_path)
        analyzer.input_file = saved_path
        analyzer.script_dir = os.path.abspath(gst_dir)
        analyzer.models_dir = os.path.join(analyzer.script_dir, 'models')
        analyzer.output_dir = tempfile.mkdtemp(prefix=f'gst_{run_id}_')
        analyzer.defer_db_insert = True
        os.makedirs(analyzer.output_dir, exist_ok=True)
    
        prev_records_out = None
        final_output_dir = os.path.abspath(os.path.join(gst_dir, 'final_output'))
        os.makedirs(final_output_dir, exist_ok=True)
        export_stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        justification_final_path = os.path.join(final_output_dir, f'gst_fraud_justification_{export_stamp}.csv')

        if is_validated_file:
            try:
                validated_df = analyzer._read_input_df(saved_path)
                prev_records_out = int(len(validated_df.index))
                analyzer.records_step2 = prev_records_out
            except Exception:
                prev_records_out = None
        else:
            # Shared preprocessing (single source of truth). Still logs step1/step2 to DB.
            def _on_pre_step(event, step_num, step_name, elapsed):
                nonlocal prev_records_out
                total_steps = 4
                if event == 'started':
                    _set_gst_run_status(run_id, {
                        'status': 'running',
                        'step': step_name,
                        'progress': int((step_num - 1) / total_steps * 100),
                    })
                    log_step(engine, run_id, 'GST', step_num, step_name, status='started', records_in=prev_records_out)
                    return

                records_out = getattr(analyzer, f'records_step{step_num}', None)
                if event == 'completed':
                    log_step(engine, run_id, 'GST', step_num, step_name, status='completed', elapsed_sec=elapsed, records_out=records_out)
                    prev_records_out = records_out
                else:
                    log_step(engine, run_id, 'GST', step_num, step_name, status='failed', elapsed_sec=elapsed, message='Step returned False')

            pre = run_gst_preprocessing(saved_path, analyzer=analyzer, on_step=_on_pre_step)
            if not pre.get('ok'):
                failed_step = 'Data Validation' if pre.get('step1_ok', True) else 'Column Standardization'
                _set_gst_run_status(run_id, {
                    'status': 'failed',
                    'step': failed_step,
                    'error': pre.get('error', 'Preprocessing failed'),
                }, force=True)
                log_run_failed(engine, run_id, 'GST', failed_step, pre.get('error', 'Preprocessing failed'))
                return

        steps = [
            ('Rules + Model Prediction',    analyzer.step3_parallel_rules_and_model, 3),
            ('Fraud Justification',         analyzer.step5_fraud_justification,     4),
        ]

        for step_name, step_func, step_num in steps:
            _set_gst_run_status(run_id, {
                'status': 'running',
                'step': step_name,
                'progress': int((step_num - 1) / 4 * 100),
            })

            log_step(engine, run_id, 'GST', step_num, step_name, status='started', records_in=prev_records_out)
            t0 = time.time()

            success = step_func()
            elapsed = round(time.time() - t0, 2)
            # Read record count stored by the step method
            records_out = getattr(analyzer, f'records_step{step_num}', None)

            if success:
                log_step(engine, run_id, 'GST', step_num, step_name,
                         status='completed', elapsed_sec=elapsed,records_out=records_out )
            else:
                log_step(engine, run_id, 'GST', step_num, step_name,
                         status='failed', elapsed_sec=elapsed,
                         message='Step returned False')
                _set_gst_run_status(run_id, {
                    'status': 'failed',
                    'step': step_name,
                    'error': f'{step_name} failed',
                }, force=True)
                log_run_failed(engine, run_id, 'GST', step_name, f'{step_name} returned False')
                return
            prev_records_out = records_out

        just_parquet = os.path.join(analyzer.output_dir, 'gst_fraud_justification.parquet')
        just_csv = os.path.join(analyzer.output_dir, 'gst_fraud_justification.csv')

        if os.path.exists(just_parquet):
            just_df = pd.read_parquet(just_parquet)
        elif os.path.exists(just_csv):
            just_df = pd.read_csv(just_csv, low_memory=False)
        else:
            raise FileNotFoundError('GST justification output not found for background DB insert')

        just_df.to_csv(justification_final_path, index=False)

        total_rows = int(len(just_df.index))
        _set_gst_run_status(run_id, {
            'status': 'inserting',
            'step': 'Prediction completed. Background database insertion in progress...',
            'progress': 85,
            'inserted_rows': 0,
            'total_rows': total_rows,
            'insert_percent': 0,
        })

        def _run_insert_phase():
            insert_engine = None
            try:
                insert_engine = get_mysql_engine()
                save_gst_justification_to_db(
                    df=just_df,
                    engine=insert_engine,
                    upload_batch_id=getattr(analyzer, 'upload_batch_id', None),
                    uploaded_at=getattr(analyzer, 'uploaded_at', None),
                    run_id=run_id,
                    status_store=_run_status,
                    user_id=current_user_id,
                )
                final_status = _run_status.get(run_id, {}).get('status')
                if final_status not in {'completed', 'failed'}:
                    raise RuntimeError('GST insert worker exited without terminal status update')
            except BaseException as insert_error:
                current_step = _run_status.get(run_id, {}).get('step', 'Database Insert')
                _set_gst_run_status(run_id, {
                    'status': 'failed',
                    'step': 'Database Insert Failed',
                    'error': str(insert_error),
                }, force=True)
                try:
                    log_run_failed(insert_engine or engine, run_id, 'GST', current_step, insert_error)
                except Exception:
                    pass
            finally:
                if insert_engine is not None:
                    try:
                        insert_engine.dispose()
                    except Exception:
                        pass

        insert_thread = threading.Thread(
            target=_run_insert_phase,
            daemon=False,
        )
        insert_thread.start()
        return

    except Exception as e:
        log_run_failed(engine, run_id, 'GST', _run_status[run_id].get('step', '?'), e)
        _set_gst_run_status(run_id, {
            'status': 'failed',
            'step': _run_status.get(run_id, {}).get('step', 'Failed'),
            'error': str(e),
        }, force=True)

    finally:
        os.chdir(original_dir)
        try:
            _analyzer = locals().get('analyzer')
            if _analyzer and getattr(_analyzer, 'output_dir', None):
                shutil.rmtree(getattr(_analyzer, 'output_dir'), ignore_errors=True)
        except Exception:
            pass
        if engine:
            engine.dispose()
        


#  POST /api/gst/run 

@gst_bp.route('/api/gst/run', methods=['POST'])
def run_gst():
    file = request.files.get('file')

    # Backward compatible input parsing:
    # - Frontend usually sends multipart/form-data
    # - Some clients may send JSON
    validated_file = request.form.get('validated_file', '').strip()
    if not validated_file:
        try:
            payload = request.get_json(silent=True) or {}
            validated_file = str(payload.get('validated_file') or '').strip()
        except Exception:
            validated_file = ''

    date_from = request.form.get('date_from', '')
    date_to = request.form.get('date_to', '')
    if (not date_from and not date_to) and request.is_json:
        try:
            payload = request.get_json(silent=True) or {}
            date_from = str(payload.get('date_from') or '')
            date_to = str(payload.get('date_to') or '')
        except Exception:
            pass

    saved_path = None
    saved_name = None

    if validated_file:
        import werkzeug.utils
        safe_name = werkzeug.utils.secure_filename(validated_file)
        if not safe_name:
            return jsonify({'error': 'Invalid validated_file'}), 400
        if not _allowed_file(safe_name):
            return jsonify({'error': 'Only .csv or .parquet files are accepted'}), 400

        # Absolute final_output directory (backend-rooted)
        # backend/api/routes/gst_routes.py -> parents[2] => backend/
        from pathlib import Path
        backend_root = Path(__file__).resolve().parents[2]
        print("[DEBUG] backend_root =", backend_root)

        output_dir = (backend_root / "gst" / "final_output").resolve()
        print("[DEBUG] output_dir =", output_dir)

        os.makedirs(str(output_dir), exist_ok=True)

        # If client accidentally sends a full path, use its basename.
        # Otherwise resolve under final_output.
        validated_file_path = (
            validated_file
            if os.path.isabs(validated_file)
            else os.path.join(str(output_dir), os.path.basename(safe_name))
        )
        candidate = os.path.abspath(validated_file_path)

        print("=" * 80)
        print("[GST RUN API DEBUG]")
        print("validated_file =", validated_file)
        print("safe_name =", safe_name)
        print("output_dir =", output_dir)
        print("validated_file_path =", candidate)
        print("file_exists =", os.path.exists(candidate))
        print("=" * 80)

        # Ensure no path traversal escapes final_output
        output_dir_str = str(output_dir)
        if os.path.commonpath([candidate, output_dir_str]) != output_dir_str:
            return jsonify({'error': 'Invalid validated_file path'}), 400
        if not os.path.exists(candidate):
            return jsonify({
                'success': False,
                'error': f'validated file not found: {safe_name}',
                'searched_path': candidate,
            }), 404

        saved_path = candidate
        saved_name = safe_name
    else:
        if not file or not file.filename:
            return jsonify({'error': 'No file uploaded'}), 400
        if not _allowed_file(file.filename):
            return jsonify({'error': 'Only .csv or .parquet files are accepted'}), 400

    run_id = str(uuid.uuid4())

    if saved_path is None:
        # Save uploaded file into gst/data/
        gst_data_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', '..', 'gst', 'data')
        )
        os.makedirs(gst_data_dir, exist_ok=True)

        import werkzeug.utils
        saved_name = werkzeug.utils.secure_filename(file.filename)
        saved_path = os.path.join(gst_data_dir, saved_name)
        file.save(saved_path)

    _set_gst_run_status(run_id, {'status': 'queued', 'step': 'Queued', 'progress': 0}, force=True)

    current_user_id = get_authenticated_user_id()
    thread = threading.Thread(
        target=_run_gst_pipeline,
        args=(run_id, saved_path, date_from, date_to, current_user_id, bool(validated_file)),
        daemon=False
    )
    thread.start()

    return jsonify({'run_id': run_id, 'status': 'queued', 'message': 'GST pipeline started'}), 202


def _get_gst_status_from_db(run_id):
    try:
        engine = get_mysql_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT user_id, step_number, step_name, status, records_in, records_out, message, error_detail, logged_at
                    FROM pipeline_log
                    WHERE run_id = :run_id AND UPPER(tax_type) = 'GST'
                    ORDER BY id ASC
                    """
                ),
                {"run_id": run_id},
            ).mappings().all()
        engine.dispose()
        if not rows:
            return None

        has_failed = any(r.get("status") == "failed" for r in rows)
        has_completed = any(r.get("step_number") == 99 and r.get("status") == "completed" for r in rows)
        latest_row = rows[-1]
        db_user_id = next((r.get("user_id") for r in reversed(rows) if r.get("user_id") is not None), None)

        if has_failed:
            fail_row = next((r for r in reversed(rows) if r.get("status") == "failed"), latest_row)
            return {
                "status": "failed",
                "step": fail_row.get("step_name") or "Failed",
                "error": fail_row.get("error_detail") or fail_row.get("message") or "Pipeline failed",
                "progress": 100,
                "user_id": db_user_id,
                "run_id": run_id,
            }

        if has_completed:
            end_row = next((r for r in rows if r.get("step_number") == 99 and r.get("status") == "completed"), latest_row)
            tot_rows = end_row.get("records_out") or 0
            return {
                "status": "completed",
                "step": "Completed",
                "progress": 100,
                "total_rows": tot_rows,
                "inserted_rows": tot_rows,
                "insert_percent": 100,
                "user_id": db_user_id,
                "run_id": run_id,
            }

        latest_by_step = {}
        for r in rows:
            step_num = int(r.get("step_number") or 0)
            latest_by_step[step_num] = r

        completed_steps = [n for n in range(1, 5) if latest_by_step.get(n, {}).get("status") == "completed"]
        failed_step = next((r for r in reversed(rows) if r.get("status") == "failed"), None)

        if failed_step:
            return {
                "status": "failed",
                "step": failed_step.get("step_name") or "Failed",
                "progress": int(len(completed_steps) / 4 * 100),
                "error": failed_step.get("error_detail") or "Run failed",
                "user_id": db_user_id,
                "run_id": run_id,
            }

        insert_entry = latest_by_step.get(4, {})
        is_inserting = bool(insert_entry) and insert_entry.get("status") in {"started", "completed"}
        current_step_name = ""
        for n in range(4, 0, -1):
            v = latest_by_step.get(n)
            if v and v.get("step_name"):
                current_step_name = v["step_name"]
                break
        if not current_step_name:
            current_step_name = latest_by_step.get(0, {}).get("step_name") or "Queued"

        tot_in = latest_row.get("records_in") or 0
        tot_out = latest_row.get("records_out") or 0

        return {
            "status": "inserting" if is_inserting else "running",
            "step": "Background database insertion in progress..." if is_inserting else current_step_name,
            "progress": 85 if is_inserting else int(len(completed_steps) / 4 * 100),
            "inserted_rows": tot_out,
            "total_rows": tot_in,
            "insert_percent": int((tot_out / tot_in) * 100) if tot_in > 0 else 0,
            "user_id": db_user_id,
            "run_id": run_id,
        }
    except Exception as e:
        print(f"[GST_STATUS_DB_FALLBACK] Error: {e}")
        return None


#  GET /api/gst/status/<run_id> 

@gst_bp.route('/api/gst/status/<run_id>', methods=['GET'])
def gst_status(run_id):
    status = _run_status.get(run_id)
    if not status:
        status = _get_gst_status_from_db(run_id)
        if not status:
            return jsonify({'error': 'Run ID not found'}), 404

    inserted_rows = int(status.get('inserted_rows') or 0)
    total_rows = int(status.get('total_rows') or 0)
    insert_percent = int(status.get('insert_percent') or 0)
    if not _is_terminal_gst_status(status.get('status')) and (
        insert_percent >= 100 or (total_rows > 0 and inserted_rows >= total_rows)
    ):
        status = _set_gst_run_status(run_id, {
            'status': 'completed',
            'step': 'Completed',
            'progress': 100,
            'inserted_rows': total_rows or inserted_rows,
            'total_rows': total_rows,
            'insert_percent': 100,
        }, force=True)

    return jsonify(status), 200


#  GET /api/gst/progress/<run_id>
@gst_bp.route('/api/gst/progress/<run_id>', methods=['GET'])
def gst_progress(run_id):
    """Lightweight progress endpoint — returns progress % and current step only."""
    status = _run_status.get(run_id)
    if not status:
        status = _get_gst_status_from_db(run_id)
        if not status:
            return jsonify({'error': 'Run ID not found'}), 404
    return jsonify({
        'run_id':   run_id,
        'status':   status.get('status',   'unknown'),
        'step':     status.get('step',     ''),
        'progress': status.get('progress', 0),
    }), 200


#  GET /api/gst/summary 

@gst_bp.route('/api/gst/summary', methods=['GET'])
def gst_summary():
    """Overall fraud stats across ALL records â€” for dashboard KPI cards."""
    try:
        import pandas as pd
        engine = get_mysql_engine()
        with engine.connect() as conn:
            df = pd.read_sql('''
                SELECT 
                    COUNT(*) as total_records,
                    SUM(predicted_fraud = 'Fraud') as fraud_count,
                    SUM(predicted_fraud = 'Non-Fraud') as non_fraud
                FROM gst_fraud_justification
            ''', conn)
        engine.dispose()

        return jsonify(df.iloc[0].to_dict()), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


#  GET /api/gst/results 

@gst_bp.route('/api/gst/results', methods=['GET'])
def gst_results():
    """Paginated GST results â€” for the data table view."""
    try:
        import pandas as pd

        page     = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 100))
        offset   = (page - 1) * per_page

        engine = get_mysql_engine()
        with engine.connect() as conn:
            df = pd.read_sql(
                f'SELECT * FROM gst_fraud_justification LIMIT {per_page} OFFSET {offset}',
                conn
            )
            total_df = pd.read_sql(
                'SELECT COUNT(*) as cnt FROM gst_fraud_justification', conn
            )
        engine.dispose()

        total_records = int(total_df.iloc[0]['cnt'])

        return jsonify({
            'page':          page,
            'per_page':      per_page,
            'total_records': total_records,
            'total_pages':   -(-total_records // per_page),
            'results':       df.to_dict(orient='records')
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


