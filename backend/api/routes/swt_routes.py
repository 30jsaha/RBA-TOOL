# ══════════════════════════════════════════════════════════════
#  api/routes/swt_routes.py
#  POST /api/swt/run
#  Accepts uploaded file + optional date range
#  Runs SWT fraud pipeline and returns results as JSON
# ══════════════════════════════════════════════════════════════

import os
import sys
import uuid
import time
import threading
import shutil
import tempfile
from pathlib import Path
from datetime import datetime
from utils.upload_logger import log_swt_upload
from flask import Blueprint, request, jsonify


sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.db_config import get_mysql_engine
from utils.pipeline_logger import log_run_start, log_run_end, log_run_failed, log_step
from utils.auth_helper import get_authenticated_user_id
from utils.auth_helper import set_authenticated_user_id_for_context
from utils.file_security import FinalOutputSecurityError, materialize_output_to_tempfile, output_exists, sanitize_file_reference, sanitize_output_filename, secure_download_response, write_encrypted_output_file, write_encrypted_output_dataframe
from utils.upload_security import UploadSecurityError, validate_upload_file
from swt.swt_upload_hook import save_swt_justification_to_db
from flask import Response
from werkzeug.utils import secure_filename
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import text
import pandas as pd

swt_bp = Blueprint('swt', __name__)
_run_status = {}

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
        print(f"[SWT_VALIDATE][DB] upload_history insert failed: {e}")
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
        print(f"[SWT_VALIDATE][DB] upload_validation_summary insert failed: {e}")
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
        print(f"[SWT_VALIDATE][DB] summary fetch failed: {e}")
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
        print(f"[SWT_VALIDATE][DB] upload_validation_errors insert failed: {ex}")
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
        print(f"[SWT_VALIDATE][DB] upload_validation_errors fetch failed: {ex}")
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


@swt_bp.route('/api/swt/validate', methods=['POST'])
@jwt_required()
def validate_swt():
    user_id = get_jwt_identity()

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'valid': False, 'error': 'No file uploaded'}), 400

    try:
        saved_name = validate_upload_file(file, allowed_extensions={'.csv', '.parquet'})
    except UploadSecurityError as exc:
        return jsonify({'valid': False, 'error': str(exc)}), 400


    swt_data_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', 'swt', 'Data')
    )
    os.makedirs(swt_data_dir, exist_ok=True)

    saved_path_processing = os.path.join(swt_data_dir, saved_name)

    upload_saved_filename = None
    upload_saved_path = None
    file_format = None
    file_size_kb = None

    try:
        upload_saved_filename, upload_saved_path, file_format, file_size_kb = _save_validation_upload(file, "swt")
        try:
            file.stream.seek(0)
        except Exception:
            pass

        try:
            shutil.copyfile(upload_saved_path, saved_path_processing)
        except Exception:
            file.save(saved_path_processing)

        upload_history_id = None
        engine_pre = None
        try:
            engine_pre = get_mysql_engine()
            column_count_pre = _try_get_column_count_from_file(upload_saved_path)
            upload_history_id = _try_insert_upload_history(
                engine_pre,
                "swt",
                upload_saved_filename,
                file_size_kb,
                file_format,
                0,
                column_count_pre,
            )
        except Exception as e:
            print(f"[SWT_VALIDATE][DB] pre-validation upload_history insert failed: {e}")
        finally:
            try:
                if engine_pre:
                    engine_pre.dispose()
            except Exception:
                pass

        swt_dir_abs = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'swt'))
        output_dir_run = None
        if upload_history_id:
            try:
                backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
                tmp_root = os.path.join(backend_dir, 'uploads', '_validation_tmp')
                os.makedirs(tmp_root, exist_ok=True)
                output_dir_run = os.path.join(tmp_root, f'swt_{int(upload_history_id)}')
            except Exception:
                output_dir_run = None

        result = run_swt_preprocessing(
            saved_path_processing,
            make_timestamped_copies=True,
            output_dir_override=output_dir_run,
            upload_history_id=upload_history_id,
        )
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
            'db_financial_difference_fields_count': result.get('db_financial_difference_fields_count', 0),
            'validated_file': result.get('validated_file', 'swt_validated.csv'),
            'removed_data_file': result.get('removed_data_file', 'swt_removed_data.csv'),
        }

        try:
            output_dir = result.get('output_dir') or os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', '..', 'swt', 'final_output')
            )
            payload['output_dir'] = output_dir

            validated_file_path = (
                result.get('validated_file_full_path')
                or (os.path.abspath(os.path.join(output_dir, payload.get('validated_file') or '')) if payload.get('validated_file') else None)
            )
            removed_data_file_path = (
                result.get('removed_file_full_path')
                or (os.path.abspath(os.path.join(output_dir, payload.get('removed_data_file') or '')) if payload.get('removed_data_file') else None)
            )

            payload['validated_file_path'] = validated_file_path
            payload['removed_data_file_path'] = removed_data_file_path

            print("[SWT VALIDATE] output_dir =", output_dir)
            print("[SWT VALIDATE] validated_file_path =", validated_file_path)
            print("[SWT VALIDATE] removed_data_file_path =", removed_data_file_path)
        except Exception:
            payload['validated_file_path'] = None
            payload['removed_data_file_path'] = None
            payload['output_dir'] = None

        if payload['invalid_records'] <= 0:
            payload['errors'] = []

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
                            "financial values differ from existing swt_fraud_justification record", na=False
                        )
                        df_fin = df_removed.loc[mask]
                        if "tin" in df_fin.columns:
                            conflict_tins = df_fin["tin"].dropna().tolist()
                except Exception:
                    conflict_tins = []

                if payload['financial_difference_count'] > 0:
                    ts2 = datetime.now().strftime('%Y%m%d_%H%M%S')
                    payload['financial_difference_file'] = f'swt_financial_difference_{ts2}.csv'
                    payload['financial_difference_file_path'] = os.path.abspath(
                        os.path.join(payload.get('output_dir'), payload.get('financial_difference_file'))
                    )
                    _export_upload_conflicts_csv_from_db(
                        "SWT",
                        conflict_tins,
                        payload['financial_difference_file_path'],
                    )
        except Exception:
            payload['financial_difference_file'] = None
            payload['financial_difference_file_path'] = None

        payload['validated_file_path'] = payload.get('validated_file') if payload.get('validated_file') else None
        payload['removed_data_file_path'] = payload.get('removed_data_file') if payload.get('removed_data_file') else None
        payload['financial_difference_file_path'] = payload.get('financial_difference_file') if payload.get('financial_difference_file') else None
        payload['output_dir'] = None

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
                upload_validation_summary_id = _try_insert_validation_summary(engine, upload_history_id, "swt", payload, user_id)
                _try_insert_validation_errors(
                    engine,
                    upload_validation_summary_id,
                    upload_history_id,
                    "swt",
                    user_id,
                    payload.get("errors") or [],
                )

                db_counts = _try_fetch_summary_counts(engine, upload_history_id, "swt", user_id)
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

                    payload["financial_difference_count"] = int(payload.get("db_financial_differences_count") or 0)

                payload["errors"] = _try_fetch_validation_errors(engine, upload_validation_summary_id)
        except Exception as e:
            print(f"[SWT_VALIDATE][DB] post-validation DB operations failed: {e}")
        finally:
            try:
                if engine:
                    engine.dispose()
            except Exception:
                pass

        return jsonify(payload), 200

    except Exception:
        return jsonify({'valid': False, 'error': 'Could not read file'}), 400

    finally:
        try:
            if os.path.exists(saved_path_processing):
                os.remove(saved_path_processing)
        except Exception:
            pass


def _normalize_authenticated_user_id(user_id):
    """
    SWT-only normalization: ensure we never propagate NaN/None user_id into
    background threads or status payloads. Mirrors GST behavior expectations
    without changing shared auth helpers.
    """
    if user_id is None:
        return None
    try:
        # Handle pandas/numpy NaN
        if isinstance(user_id, float) and user_id != user_id:
            return None
    except Exception:
        pass
    try:
        # Handle "123.0" coming from JSON/JWT coercion
        if isinstance(user_id, str):
            s = user_id.strip()
            if s == "":
                return None
            if s.endswith(".0") and s[:-2].isdigit():
                return int(s[:-2])
            if s.isdigit():
                return int(s)
            return user_id
        if isinstance(user_id, bool):
            return int(user_id)
        if isinstance(user_id, (int,)):
            return user_id
        if isinstance(user_id, float):
            return int(user_id)
    except Exception:
        return user_id
    return user_id

def _is_ignored_conflict_field(field_name: object) -> bool:
    try:
        n = str(field_name or "").strip().lower().replace(" ", "")
    except Exception:
        return False
    return n in ("unnamed:_0", "unnamed:0", "unnamed_0")


def _sanitize_field_name(field_name: object):
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


def _resolve_source_meta_for_conflict(
    *,
    engine,
    source_table: str,
    assessment_column: str,
    tin: object,
    tax_period_year: object,
    tax_period_month: object,
    assessment_number: object,
    field_name: object,
    previous_value: object,
):
    """
    Resolve (source_record_id, upload_batch_id, taxpayer_name) by selecting the matched record from
    the fraud justification table. Validates `field_name` exists before using it.
    Returns (None, None, None) on any failure.
    """
    try:
        if engine is None:
            return (None, None, None)
        st = (source_table or "").strip()
        if not st:
            return (None, None, None)
        fn = _sanitize_field_name("" if field_name is None else str(field_name).strip())
        if not fn or _is_ignored_conflict_field(fn):
            return (None, None, None)

        tin_s = "" if tin is None else str(tin).strip()
        if tin_s.endswith(".0") and tin_s[:-2].isdigit():
            tin_s = tin_s[:-2]
        try:
            yr_i = int(float(tax_period_year)) if tax_period_year is not None else None
        except Exception:
            yr_i = None
        try:
            mo_i = int(float(tax_period_month)) if tax_period_month is not None else None
        except Exception:
            mo_i = None

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

        from sqlalchemy import text
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
            if assessment_column.lower() not in cols:
                return (None, None, None)
            if "tin" not in cols or "tax_period_year" not in cols:
                return (None, None, None)

            sel_cols = ["id"]
            if "upload_batch_id" in cols:
                sel_cols.append("upload_batch_id")
            if "taxpayer_name" in cols:
                sel_cols.append("taxpayer_name")
            elif "taxpayer" in cols:
                sel_cols.append("taxpayer")
            sel_cols.append(f"`{fn}` AS _db_val")

            assess_q = f"`{assessment_column}`"
            st_q = f"`{st}`"

            # Include month when the table has it and a value is present (SWT does).
            month_clause = ""
            params = {"tin": tin_s, "yr": yr_i, "assess": assess_s, "prev": prev_f}
            if "tax_period_month" in cols and mo_i is not None:
                month_clause = " AND tax_period_month = :mo "
                params["mo"] = mo_i

            q = text(
                f"SELECT {', '.join(sel_cols)} "
                f"FROM {st_q} "
                f"WHERE tin = :tin "
                f"  AND tax_period_year = :yr "
                f"{month_clause}"
                f"  AND {assess_q} = :assess "
                f"ORDER BY id DESC "
                f"LIMIT 5"
            )
            rows = conn.execute(q, params).fetchall()
            if not rows:
                return (None, None, None)

            want = _normalize(prev_f)
            has_batch = "upload_batch_id" in cols
            has_name = ("taxpayer_name" in cols) or ("taxpayer" in cols)
            for row in rows:
                try:
                    db_val = row[-1] if len(row) >= 2 else None
                    if _normalize(db_val) == want:
                        src_id = row[0] if len(row) > 0 else None
                        batch_id = row[1] if (has_batch and len(row) >= 3) else None
                        tp_name = None
                        if has_name:
                            try:
                                tp_name = row[-2]
                            except Exception:
                                tp_name = None
                        return (src_id, batch_id, tp_name)
                except Exception:
                    continue
            return (None, None, None)
    except Exception:
        return (None, None, None)


def _allowed_file(filename):
    return filename.lower().endswith(('.csv', '.parquet'))


@swt_bp.route('/api/swt/download/<path:filename>', methods=['GET'])
@jwt_required()
def download_swt_file(filename):
    """
    Secure download endpoint for files in backend/swt/final_output.
    """
    try:
        logical_name = sanitize_output_filename(filename, expected_prefix='swt_')
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        output_dir = os.path.abspath(os.path.join(backend_dir, 'swt', 'final_output'))
        os.makedirs(output_dir, exist_ok=True)
        if not output_exists(output_dir, logical_name):
            return jsonify({"success": False, "message": "File not found"}), 404
        return secure_download_response(output_dir, logical_name)
    except ValueError:
        return jsonify({"success": False, "message": "Invalid filename"}), 400
    except FinalOutputSecurityError as exc:
        if str(exc) in {"Invalid filename", "Invalid file type"}:
            return jsonify({"success": False, "message": str(exc)}), 400
        return jsonify({"success": False, "message": "Secure file handling is not configured"}), 500
    except Exception:
        return jsonify({"success": False, "message": "Unable to download file"}), 500

def run_swt_preprocessing(saved_path, on_step=None, make_timestamped_copies=False, output_dir_override=None, upload_history_id=None):
    """
    SWT preprocessing for validation-only use.

    Runs ONLY:
      1) Column standardization
      2) SWT validation/cleaning (rules in swt/2_swt_validation.py)

    Returns dict with counts + row-level errors parsed from swt_validation_log.txt.
    Does NOT run fraud pipeline steps or ML models.
    """
    import re as _re
    import shutil
    import importlib.util as _importlib_util
    from datetime import datetime
    import pandas as _pd
    from sqlalchemy import bindparam, text

    original_dir = os.getcwd()
    swt_dir_abs = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'swt'))
    public_output_dir = os.path.abspath(os.path.join(swt_dir_abs, 'final_output'))
    output_dir = output_dir_override or public_output_dir
    os.makedirs(output_dir, exist_ok=True)

    _SWT_PIPELINE_DEBUG = os.environ.get('SWT_PIPELINE_DEBUG', '').strip() == '1'

    def _load_input(path):
        p = path.lower()
        if p.endswith('.parquet'):
            return _pd.read_parquet(path)
        if p.endswith('.csv'):
            return _pd.read_csv(path)
        raise ValueError('Only .csv or .parquet files are accepted')

    def _load_standardize_swt_columns():
        """
        Load `standardize_swt_columns(df)` from swt/1_swt_preparation.py without
        executing that module's top-level side effects (file I/O).
        """
        import ast as _ast

        prep_path = os.path.join(swt_dir_abs, '1_swt_preparation.py')
        with open(prep_path, 'r', encoding='utf-8', errors='replace') as f:
            src = f.read()

        tree = _ast.parse(src, filename=prep_path)
        func_node = None
        for node in tree.body:
            if isinstance(node, _ast.FunctionDef) and node.name == 'standardize_swt_columns':
                func_node = node
                break
        if func_node is None:
            raise RuntimeError("Could not find `standardize_swt_columns` in swt/1_swt_preparation.py")

        mod = _ast.Module(body=[func_node], type_ignores=[])
        code = compile(mod, prep_path, 'exec')
        ns = {'pd': _pd}
        exec(code, ns, ns)
        return ns['standardize_swt_columns']

    def _parse_log_rows(log_file_path: str):
        items = []
        try:
            with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    m = _re.search(r'Row\s+(\d+):\s*(.+)', line.strip())
                    if m:
                        items.append((int(m.group(1)), m.group(2)))
        except Exception:
            return []
        return items

    def _guess_column(message: str) -> str:
        msg = '' if message is None or _pd.isna(message) else str(message)
        msg = msg.lower()
        patterns = [
            (r'\btin\b', 'TIN'),
            (r'employees\s+paid\s+swt', 'EmployeesPaidSWT'),
            (r'employees\s+on\s+payroll', 'EmployeesOnPayroll'),
            (r'head[_\s-]*office', 'HeadOfficeIndicator'),
            (r'tax_period_year|tax period year', 'TaxPeriodYear'),
            (r'tax_period_month|tax period month', 'TaxPeriodMonth'),
            (r'entry[_\s-]*date', 'EntryDate'),
            (r'assessed[_\s-]*date', 'AssessedDate'),
            (r'due[_\s-]*date', 'DueDate'),
            (r'assessment[_\s-]*number', 'AssessmentNumber'),
            (r'total[_\s-]*salary|salary[_\s-]*wages', 'TotalSalaryWagesPaid'),
            (r'total[_\s-]*swt[_\s-]*tax|swt[_\s-]*tax[_\s-]*deducted', 'TotalSWTTaxDeducted'),
        ]
        for pat, col in patterns:
            if _re.search(pat, msg):
                return col
        return ''

    def _normalize_tin(v):
        if v is None or _pd.isna(v):
            return ''
        s = str(v).strip()
        if s.endswith('.0'):
            s = s[:-2]
        return s

    try:
        if callable(on_step):
            on_step('started', 1, 'Column Standardization', None)

        for f in ['swt_standardized.parquet', 'swt_standardized.csv', 'swt_cleaned_data.parquet', 'swt_removed_data.parquet',
                  'swt_removed_data.csv', 'swt_validated.csv', 'swt_validation_log.txt']:
            try:
                fp = os.path.join(output_dir, f)
                if os.path.exists(fp):
                    os.remove(fp)
            except Exception:
                pass

        df_in = _load_input(saved_path)
        # Normalize raw headers (common issue: trailing/leading spaces break mapping hits)
        try:
            df_in.columns = df_in.columns.astype(str).str.strip()
        except Exception:
            pass
        if _SWT_PIPELINE_DEBUG:
            try:
                print("Columns BEFORE standardization:", df_in.columns.tolist())
            except Exception:
                pass

        standardize_swt_columns = _load_standardize_swt_columns()
        df_std = standardize_swt_columns(df_in)

        if _SWT_PIPELINE_DEBUG:
            try:
                print("RAW upload columns:", df_in.columns.tolist())
                print("After standardization:", df_std.columns.tolist())
                print("Before validation:", df_std.columns.tolist())
            except Exception:
                pass

        if '_row' not in df_std.columns:
            df_std['_row'] = _pd.RangeIndex(start=1, stop=len(df_std) + 1, step=1)

        standardized_parquet = os.path.join(output_dir, 'swt_standardized.parquet')
        df_std.to_parquet(standardized_parquet, index=False)

        if callable(on_step):
            on_step('completed', 1, 'Column Standardization', 0)

        if callable(on_step):
            on_step('started', 2, 'Data Validation', None)

        os.chdir(output_dir)

        validation_path = os.path.join(swt_dir_abs, '2_swt_validation.py')
        spec = _importlib_util.spec_from_file_location('swt_validation_module', validation_path)
        module = _importlib_util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cleaned_df, removed_df, _removal_details = module.validate_and_clean_swt_data(
            df_std,
            output_dir_override=output_dir,
        )

        cleaned_parquet = os.path.join(output_dir, 'swt_cleaned_data.parquet')
        removed_csv = os.path.join(output_dir, 'swt_removed_data.csv')
        validated_csv = os.path.join(output_dir, 'swt_validated.csv')
        log_path = os.path.join(output_dir, 'swt_validation_log.txt')

        try:
            if cleaned_df is None:
                cleaned_df = _pd.DataFrame()
            valid_records = int(len(cleaned_df))
        except Exception:
            valid_records = 0

        try:
            if removed_df is None:
                removed_df = _pd.DataFrame()
            invalid_records = int(len(removed_df))
        except Exception:
            invalid_records = 0

        errors = []
        if invalid_records > 0 and os.path.exists(log_path):
            for row_num, reason in _parse_log_rows(log_path):
                reason_txt = '' if reason is None or _pd.isna(reason) else str(reason)
                tin_val = ''
                try:
                    if 1 <= row_num <= len(df_std):
                        v = df_std.iloc[row_num - 1].get('tin')
                        tin_val = _normalize_tin(v)
                except Exception:
                    tin_val = ''
                errors.append({
                    'row': int(row_num),
                    'tin': tin_val,
                    'column': _guess_column(reason_txt),
                    'reason': reason_txt,
                })

        # Copy log/CSV into unique filenames for this upload_history_id (optional, avoids any overwrites).
        try:
            if upload_history_id:
                for src_name, dst_name in [
                    ("swt_validation_log.txt", f"swt_validation_log_{upload_history_id}.txt"),
                    ("swt_removed_data.csv", f"swt_removed_data_{upload_history_id}.csv"),
                    ("swt_validated.csv", f"swt_validated_{upload_history_id}.csv"),
                ]:
                    src_path = os.path.join(output_dir, src_name)
                    dst_path = os.path.join(output_dir, dst_name)
                    if os.path.exists(src_path):
                        try:
                            shutil.copy2(src_path, dst_path)
                        except Exception:
                            pass
        except Exception:
            pass

        tin_invalid_count = 0
        if errors:
            tin_rows = set()
            for e in errors:
                col_txt = e.get('column', '')
                col_txt = '' if col_txt is None or _pd.isna(col_txt) else str(col_txt)
                reason_txt = e.get('reason', '')
                reason_txt = '' if reason_txt is None or _pd.isna(reason_txt) else str(reason_txt)
                txt = f"{col_txt} {reason_txt}".lower()
                # Exclude DB-level validations from TIN invalid counter
                if 'duplicate swt record already exists in swt_fraud_justification' in txt:
                    continue
                if 'financial values differ from existing swt_fraud_justification record' in txt:
                    continue
                if 'tin' in txt:
                    tin_rows.add(e.get('row'))
            tin_invalid_count = len([r for r in tin_rows if isinstance(r, int)])

        # Add reason column to removed CSV (keyed by _row when present)
        try:
            if removed_df is not None and invalid_records > 0:
                reason_map = {}
                for e in errors:
                    r = e.get('row')
                    if isinstance(r, int):
                        raw_reason = e.get('reason')
                        reason_txt = '' if raw_reason is None or _pd.isna(raw_reason) else str(raw_reason)
                        reason_map[r] = reason_txt.strip()

                if '_row' in removed_df.columns:
                    mapped = removed_df['_row'].map(reason_map)
                    if 'reason' in removed_df.columns:
                        removed_df['reason'] = removed_df['reason'].fillna(mapped)
                    else:
                        removed_df['reason'] = mapped
                else:
                    if 'reason' not in removed_df.columns:
                        removed_df['reason'] = None

                if 'reason' in removed_df.columns:
                    removed_df['reason'] = removed_df['reason'].fillna('').astype(str)
        except Exception:
            pass

        # GST-style DB duplicate + financial difference validation (against swt_fraud_justification)
        # Runs AFTER full SWT validation and BEFORE taxpayer merge / CSV export.
        db_duplicates_count = 0
        db_financial_differences_count = 0
        db_financial_difference_fields_count = 0
        try:
            if cleaned_df is None:
                cleaned_df = _pd.DataFrame()
            if removed_df is None:
                removed_df = _pd.DataFrame()

            # Mirror GST composite key strategy: tin + tax_account_number + tax_period_year + tax_period_month
            key_cols = ['tin', 'tax_account_number', 'tax_period_year', 'tax_period_month']
            fin_cols = [
                'total_salary_wages_paid',
                'employees_paid_swt',
                'sw_paid_for_swt_deduction',
                'total_swt_tax_deducted',
            ]

            if not cleaned_df.empty:
                # SWT input columns can arrive in different naming conventions (raw CSV headers vs pipeline-normalized).
                # For DB duplicate/diff detection we need the canonical GST-style key/financial column names.
                cleaned_df = cleaned_df.copy()

                alt_map = {
                    # Composite key
                    'tin': ['TIN', 'Tin', 'tin'],
                    'tax_account_number': ['tax_account_number', 'TaxAccountNo', 'TaxAccountNo.', 'taxaccountno'],
                    'tax_period_year': ['tax_period_year', 'TaxPeriodYear', 'taxperiodyear'],
                    'tax_period_month': ['tax_period_month', 'TaxPeriodMonth', 'taxperiodmonth'],
                    # Financials (raw SWT CSV headers)
                    'total_salary_wages_paid': ['total_salary_wages_paid', '20.TotalSalaryWagesPaid'],
                    'employees_paid_swt': ['employees_paid_swt', '30.No.SWTEmployees'],
                    'sw_paid_for_swt_deduction': ['sw_paid_for_swt_deduction', '40.SWPaidForSWTDeduct'],
                    'total_swt_tax_deducted': ['total_swt_tax_deducted', '50.TotalSWTAXDeducted'],
                }

                for target, candidates in alt_map.items():
                    if target in cleaned_df.columns:
                        continue
                    found = next((c for c in candidates if c in cleaned_df.columns), None)
                    if found:
                        cleaned_df.rename(columns={found: target}, inplace=True)

            # Always print basic debug so we can see why the DB block may be skipped.
            try:
                print("=" * 80)
                print("[SWT DB DEBUG]")
                print("table = swt_fraud_justification")
                print("upload columns =", [] if cleaned_df is None else cleaned_df.columns.tolist())
                missing = [c for c in key_cols if cleaned_df is None or c not in cleaned_df.columns]
                print("missing key cols =", missing)
                print("=" * 80)
            except Exception:
                pass

            if not cleaned_df.empty and all(c in cleaned_df.columns for c in key_cols):
                # Normalize key columns (GST-equivalent normalization)
                for col in ('tin', 'tax_account_number'):
                    s = (
                        cleaned_df[col]
                        .astype(str)
                        .str.replace(".0", "", regex=False)
                        .str.strip()
                    )
                    s_lower = s.str.lower()
                    s = s.mask(s_lower.isin(["", "nan", "none", "null", "<na>"]), _pd.NA)
                    cleaned_df[col] = s

                for col in ('tax_period_year', 'tax_period_month'):
                    cleaned_df[col] = (
                        _pd.to_numeric(cleaned_df[col], errors='coerce')
                        .fillna(0)
                        .astype(int)
                    )

                # Normalize financial columns (GST-equivalent: numeric -> 0 -> float -> round(2))
                for c in fin_cols:
                    if c in cleaned_df.columns:
                        cleaned_df[c] = (
                            _pd.to_numeric(cleaned_df[c], errors='coerce')
                            .fillna(0.0)
                            .astype(float)
                            .round(2)
                        )

                unique_tins = cleaned_df['tin'].dropna().astype(str).str.strip()
                unique_tins = [t for t in unique_tins.unique().tolist() if t != '']

                if unique_tins:
                    engine_db = None
                    try:
                        engine_db = get_mysql_engine()
                        try:
                            if os.getenv("SWT_DUP_DEBUG", "").strip() in ("1", "true", "TRUE", "yes", "YES"):
                                with engine_db.connect() as conn_dbg:
                                    dbn = conn_dbg.execute(text("SELECT DATABASE()")).scalar()
                                    cnt = conn_dbg.execute(text("SELECT COUNT(*) FROM swt_fraud_justification")).scalar()
                                    print(f"[SWT_DUP_DEBUG] database={dbn} swt_fraud_justification_count={cnt}")
                        except Exception:
                            pass
                        # Pull only relevant DB rows for these tins (filter keys in pandas afterwards)
                        # IMPORTANT: for SQLAlchemy expanding binds, do NOT wrap `:tins` in parentheses here.
                        # SQLAlchemy will generate the needed `(?, ?, ...)` list. Wrapping would produce
                        # double-parens `IN ((?, ?, ...))` which MySQL treats as a ROW constructor and
                        # can error with: "Illegal parameter data types blob and row for operation '='".
                        db_df = _pd.read_sql(
                            text("""
                                SELECT id, upload_batch_id, tin, tax_account_number, tax_period_year, tax_period_month,
                                       total_salary_wages_paid, employees_paid_swt,
                                       sw_paid_for_swt_deduction, total_swt_tax_deducted
                                FROM swt_fraud_justification
                                WHERE tin IN :tins
                            """).bindparams(bindparam("tins", expanding=True)),
                            engine_db,
                            params={"tins": unique_tins},
                        )
                    finally:
                        try:
                            if engine_db is not None:
                                engine_db.dispose()
                        except Exception:
                            pass

                    print("=" * 80)
                    print("[SWT DB DEBUG]")
                    print("table = swt_fraud_justification")
                    print("upload columns =", cleaned_df.columns.tolist())
                    print("sql = WHERE tin IN :tins")
                    print("tins =", len(unique_tins))
                    print("db rows fetched =", 0 if db_df is None else int(len(db_df)))
                    print("=" * 80)

                    if db_df is not None and not db_df.empty:
                        db_df = db_df.copy()
                        for col in ('tin', 'tax_account_number'):
                            s = (
                                db_df[col]
                                .astype(str)
                                .str.replace(".0", "", regex=False)
                                .str.strip()
                            )
                            s_lower = s.str.lower()
                            s = s.mask(s_lower.isin(["", "nan", "none", "null", "<na>"]), _pd.NA)
                            db_df[col] = s

                        for col in ('tax_period_year', 'tax_period_month'):
                            db_df[col] = (
                                _pd.to_numeric(db_df[col], errors='coerce')
                                .fillna(0)
                                .astype(int)
                            )
                        for c in fin_cols:
                            if c in db_df.columns:
                                db_df[c] = (
                                    _pd.to_numeric(db_df[c], errors='coerce')
                                    .fillna(0.0)
                                    .astype(float)
                                    .round(2)
                                )

                        # Build normalized composite keys for debugging + match validation
                        def _mk_key(df):
                            return (
                                df['tin'].fillna('')
                                .astype(str).str.strip()
                                + "|"
                                + df['tax_account_number'].fillna('')
                                .astype(str).str.strip()
                                + "|"
                                + df['tax_period_year'].fillna(0).astype(int).astype(str)
                                + "|"
                                + df['tax_period_month'].fillna(0).astype(int).astype(str)
                            )

                        cleaned_df['_db_key'] = _mk_key(cleaned_df)
                        db_df['_db_key'] = _mk_key(db_df)

                        print("=" * 80)
                        print("[SWT DB DEBUG] Normalized key samples")
                        print("UPLOAD _db_key head =", cleaned_df['_db_key'].head(5).tolist())
                        print("DB     _db_key head =", db_df['_db_key'].head(5).tolist())
                        try:
                            upload_keys = set(cleaned_df['_db_key'].dropna().astype(str).tolist())
                            db_keys = set(db_df['_db_key'].dropna().astype(str).tolist())
                            common = upload_keys.intersection(db_keys)
                            print("[SWT DB DEBUG] upload keys =", len(upload_keys))
                            print("[SWT DB DEBUG] db keys     =", len(db_keys))
                            print("[SWT DB DEBUG] common keys =", len(common))
                            if len(common) == 0:
                                sample_upload = list(upload_keys)[:5]
                                print("[SWT DB DEBUG] upload key sample (no matches) =", sample_upload)
                                # also show db key sample for the same TINs to highlight mismatches
                                tins_sample = cleaned_df['tin'].dropna().astype(str).head(3).tolist()
                                if tins_sample:
                                    db_key_sample = db_df.loc[db_df['tin'].isin(tins_sample), '_db_key'].head(5).tolist()
                                    print("[SWT DB DEBUG] db keys for upload tins sample =", db_key_sample)
                                    try:
                                        yrs = (
                                            db_df.loc[db_df['tin'].isin(tins_sample), 'tax_period_year']
                                            .dropna().astype(int).unique().tolist()
                                        )
                                        mos = (
                                            db_df.loc[db_df['tin'].isin(tins_sample), 'tax_period_month']
                                            .dropna().astype(int).unique().tolist()
                                        )
                                        print("[SWT DB DEBUG] db years for upload tins sample =", sorted(yrs)[:20])
                                        print("[SWT DB DEBUG] db months for upload tins sample =", sorted(mos)[:20])
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                        print("=" * 80)

                        merged = cleaned_df.merge(
                            db_df,
                            on=key_cols,
                            how='left',
                            suffixes=('', '__db'),
                            indicator=True,
                        )

                        matched = merged['_merge'].eq('both')
                        if matched.any():
                            # Determine per-row financial equality against matched DB record
                            eq_mask = _pd.Series(True, index=merged.index)
                            for c in fin_cols:
                                if c in merged.columns and f"{c}__db" in merged.columns:
                                    eq_mask &= (merged[c].fillna(0.0) == merged[f"{c}__db"].fillna(0.0))

                            dup_mask = matched & eq_mask
                            diff_mask = matched & (~eq_mask)

                            # Count number of differing fields across all diff rows
                            try:
                                diff_fields = 0
                                for c in fin_cols:
                                    if c in merged.columns and f"{c}__db" in merged.columns:
                                        diff_fields += int(
                                            (merged.loc[diff_mask, c].fillna(0.0) != merged.loc[diff_mask, f"{c}__db"].fillna(0.0)).sum()
                                        )
                                db_financial_difference_fields_count = int(diff_fields)
                            except Exception:
                                db_financial_difference_fields_count = 0

                            print("=" * 80)
                            print("[SWT DB DEBUG] Match summary")
                            print("matched keys =", int(matched.sum()))
                            print("duplicate ids =", int(dup_mask.sum()))
                            print("financial diff ids =", int(diff_mask.sum()))
                            print("financial diff fields =", int(db_financial_difference_fields_count))
                            print("=" * 80)

                            # Remove ALL duplicates/conflicts from validated insert set
                            to_remove = dup_mask | diff_mask
                            if to_remove.any():
                                removed_rows = merged.loc[to_remove].copy()
                                # Keep original upload row index if present
                                if '_row' in removed_rows.columns:
                                    removed_rows['_row'] = removed_rows['_row']

                                # Build reasons + errors
                                for _, rr in removed_rows.iterrows():
                                    row_num = rr.get('_row')
                                    try:
                                        row_num = int(row_num) if _pd.notna(row_num) else None
                                    except Exception:
                                        row_num = None
                                    tin_val = '' if _pd.isna(rr.get('tin')) else str(rr.get('tin')).strip()

                                    if bool(dup_mask.loc[rr.name]):
                                        db_duplicates_count += 1
                                        reason = "Duplicate SWT record already exists in swt_fraud_justification"
                                    else:
                                        db_financial_differences_count += 1
                                        reason = "Financial values differ from existing swt_fraud_justification record"

                                    if row_num is not None:
                                        errors.append({
                                            'row': row_num,
                                            'tin': tin_val,
                                            'column': 'TIN',
                                            'reason': reason,
                                        })

                                # Append to removed_df with reason column (do not merge taxpayer_name into these)
                                drop_db_cols = [c for c in removed_rows.columns if c.endswith('__db') or c in ['_merge', '_db_key']]
                                removed_rows.drop(columns=drop_db_cols, inplace=True, errors='ignore')

                                # Set reason column
                                removed_rows['reason'] = [
                                    "Duplicate SWT record already exists in swt_fraud_justification" if bool(dup_mask.loc[idx])
                                    else "Financial values differ from existing swt_fraud_justification record"
                                    for idx in removed_rows.index
                                ]

                                removed_df = _pd.concat([removed_df, removed_rows], ignore_index=True)

                                # Keep only non-removed in cleaned_df
                                keep_cols = [c for c in cleaned_df.columns if c != '_db_key']
                                cleaned_df = merged.loc[~to_remove, keep_cols].copy()

                                # Update counts
                                valid_records = int(len(cleaned_df))
                                invalid_records = int(len(removed_df))

                                # Persist conflicts to upload_conflicts (one row per differing field), GST-style
                                try:
                                    diff_rows = merged.loc[diff_mask].copy()
                                    if not diff_rows.empty:
                                        conflicts_rows = []
                                        for _, rr in diff_rows.iterrows():
                                            for field_name in fin_cols:
                                                new_val = rr.get(field_name)
                                                old_val = rr.get(f"{field_name}__db")
                                                try:
                                                    new_v = float(new_val) if _pd.notna(new_val) else 0.0
                                                except Exception:
                                                    new_v = 0.0
                                                try:
                                                    old_v = float(old_val) if _pd.notna(old_val) else 0.0
                                                except Exception:
                                                    old_v = 0.0
                                                if new_v != old_v:
                                                    db_financial_difference_fields_count += 1
                                                    conflicts_rows.append({
                                                        "tax_type": "SWT",
                                                        "tin": str(rr.get("tin") if rr.get("tin") is not None else "").strip(),
                                                        "tax_account_number": rr.get("tax_account_number", None),
                                                        "taxpayer_name": rr.get("taxpayer_name", None),
                                                        "tax_period_year": rr.get("tax_period_year", None),
                                                        "tax_period_month": rr.get("tax_period_month", None),
                                                        "assessment_number": rr.get("assessment_number", None),
                                                        "field_name": _sanitize_field_name(field_name),
                                                        "previous_value": old_v,
                                                        "current_value": new_v,
                                                        "status": 0,
                                                        "source_table": "swt_fraud_justification",
                                                        "source_record_id": rr.get("id__db", None),
                                                        "upload_batch_id": rr.get("upload_batch_id__db", None),
                                                    })
                                        if conflicts_rows:
                                            to_ins = _pd.DataFrame(conflicts_rows)
                                            engine2 = None
                                            try:
                                                engine2 = get_mysql_engine()
                                                # Reuse GST-style alignment: align to existing table schema if it exists.
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

                                                # Populate source_record_id + upload_batch_id for approval flow.
                                                try:
                                                    if "source_record_id" in conf_cols or "upload_batch_id" in conf_cols:
                                                        src_ids = []
                                                        batch_ids = []
                                                        tp_names = []
                                                        for _, r in to_ins.iterrows():
                                                            try:
                                                                src_id, batch_id, tp_name = _resolve_source_meta_for_conflict(
                                                                    engine=engine2,
                                                                    source_table="swt_fraud_justification",
                                                                    assessment_column="assessment_number",
                                                                    tin=r.get("tin"),
                                                                    tax_period_year=r.get("tax_period_year"),
                                                                    tax_period_month=r.get("tax_period_month"),
                                                                    assessment_number=r.get("assessment_number"),
                                                                    field_name=_sanitize_field_name(r.get("field_name")),
                                                                    previous_value=r.get("previous_value"),
                                                                )
                                                            except Exception:
                                                                src_id, batch_id, tp_name = (None, None, None)
                                                            src_ids.append(src_id)
                                                            batch_ids.append(batch_id)
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
                                                            to_ins["taxpayer_name"] = tp_names
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
                            print("[SWT FINANCIAL DIFF]")
                            print("difference_count =", int(db_financial_differences_count))
                            print("difference_fields =", int(db_financial_difference_fields_count))
                            print("=" * 80)
        except Exception:
            # Do not fail SWT validation flow on DB connectivity/schema issues,
            # but always print a concise traceback for debugging duplicate checks.
            try:
                import traceback as _traceback
                print("=" * 80)
                print("[SWT DB DEBUG] Exception in DB duplicate/diff block:")
                print(_traceback.format_exc())
                print("=" * 80)
            except Exception:
                pass
            pass

        # Drop internal helper columns from finalized outputs (keep only business columns)
        try:
            internal_cols = ['_row']
            if cleaned_df is not None:
                cleaned_df = cleaned_df.drop(
                    columns=[c for c in internal_cols if c in cleaned_df.columns],
                    errors='ignore'
                )
            if removed_df is not None:
                removed_df = removed_df.drop(
                    columns=[c for c in internal_cols if c in removed_df.columns],
                    errors='ignore'
                )
        except Exception:
            pass

        # Step 4: merge taxpayer names ONLY after validation + DB duplicate/conflict filtering (valid rows only)
        try:
            if cleaned_df is not None and not cleaned_df.empty and hasattr(module, 'merge_taxpayer_names'):
                # Normalize tin before merge
                if 'tin' in cleaned_df.columns:
                    cleaned_df = cleaned_df.copy()
                    cleaned_df['tin'] = (
                        cleaned_df['tin']
                        .fillna('')
                        .astype(str)
                        .str.replace('.0', '', regex=False)
                        .str.strip()
                    )
                cleaned_df = module.merge_taxpayer_names(cleaned_df)
                if _SWT_PIPELINE_DEBUG and cleaned_df is not None and 'tin' in cleaned_df.columns:
                    try:
                        print("TIN sample before merge:", cleaned_df['tin'].head().tolist())
                        if 'taxpayer_name' in cleaned_df.columns:
                            print("Matched taxpayer names:", int(cleaned_df['taxpayer_name'].notna().sum()))
                        print("Columns after taxpayer merge:", cleaned_df.columns.tolist())
                    except Exception:
                        pass
        except Exception:
            pass

        if _SWT_PIPELINE_DEBUG:
            try:
                print("Validated cleaned_df columns:", [] if cleaned_df is None else cleaned_df.columns.tolist())
                print("Removed_df columns:", [] if removed_df is None else removed_df.columns.tolist())
            except Exception:
                pass

        # Step 6: ensure taxpayer_name follows tin in validated output
        try:
            if cleaned_df is not None and not cleaned_df.empty and 'tin' in cleaned_df.columns:
                if 'taxpayer_name' in cleaned_df.columns:
                    other_cols = [c for c in cleaned_df.columns if c not in ['tin', 'taxpayer_name']]
                    cleaned_df = cleaned_df[['tin', 'taxpayer_name'] + other_cols]
                else:
                    other_cols = [c for c in cleaned_df.columns if c != 'tin']
                    cleaned_df = cleaned_df[['tin'] + other_cols]
        except Exception:
            pass

        if os.environ.get('SWT_DEBUG', '').strip() == '1':
            try:
                print(cleaned_df.columns.tolist())
                if cleaned_df is not None and 'tin' in cleaned_df.columns and 'taxpayer_name' in cleaned_df.columns:
                    print(cleaned_df[['tin', 'taxpayer_name']].head())
            except Exception as e:
                print(str(e))

        # Persist outputs (static filenames in final_output)
        # If file writing fails (e.g., locked by Excel), do not silently keep stale files.
        try:
            if cleaned_df is not None:
                if _SWT_PIPELINE_DEBUG:
                    try:
                        print("Before validated CSV export:", cleaned_df.columns.tolist())
                        print("Validated rows being written:", int(len(cleaned_df)))
                    except Exception:
                        pass
                cleaned_df.to_parquet(cleaned_parquet, index=False)
                cleaned_df.to_csv(validated_csv, index=False)
        except Exception as _write_e:
            if _SWT_PIPELINE_DEBUG:
                try:
                    import traceback as _traceback
                    print("[SWT_VALIDATE_EXPORT] Failed to write validated outputs:\n" + _traceback.format_exc())
                except Exception:
                    pass
            # Re-raise so API doesn't report mismatched counts vs. stale files.
            raise

        try:
            if removed_df is not None and invalid_records > 0:
                if 'reason' not in removed_df.columns:
                    removed_df['reason'] = ''
                removed_df['reason'] = removed_df['reason'].fillna('').astype(str)
                if _SWT_PIPELINE_DEBUG:
                    try:
                        print("Columns BEFORE removed CSV export:", removed_df.columns.tolist())
                        print("Removed rows being written:", int(len(removed_df)))
                    except Exception:
                        pass
                removed_df.to_csv(removed_csv, index=False)
        except Exception:
            if _SWT_PIPELINE_DEBUG:
                try:
                    import traceback as _traceback
                    print("[SWT_VALIDATE_EXPORT] Failed to write removed outputs:\n" + _traceback.format_exc())
                except Exception:
                    pass
            raise

        total_records = int(valid_records) + int(invalid_records)

        validated_file_name = 'swt_validated.csv'
        removed_file_name = 'swt_removed_data.csv'
        validated_file_full_path = None
        removed_file_full_path = None
        if make_timestamped_copies:
            try:
                stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                if os.path.exists(validated_csv):
                    validated_file_name = f'swt_validated_{stamp}.csv'
                    os.makedirs(public_output_dir, exist_ok=True)
                    validated_file_full_path = os.path.abspath(os.path.join(public_output_dir, validated_file_name))
                    write_encrypted_output_file(validated_csv, public_output_dir, validated_file_name)
                if os.path.exists(removed_csv) and invalid_records > 0:
                    removed_file_name = f'swt_removed_data_{stamp}.csv'
                    os.makedirs(public_output_dir, exist_ok=True)
                    removed_file_full_path = os.path.abspath(os.path.join(public_output_dir, removed_file_name))
                    write_encrypted_output_file(removed_csv, public_output_dir, removed_file_name)
            except Exception:
                validated_file_name = 'swt_validated.csv'
                removed_file_name = 'swt_removed_data.csv'
                validated_file_full_path = None
                removed_file_full_path = None

        # Fall back to static paths if timestamped copies weren't created.
        if validated_file_full_path is None:
            candidate = os.path.abspath(os.path.join(public_output_dir, validated_file_name))
            validated_file_full_path = candidate if output_exists(public_output_dir, validated_file_name) else None
        if removed_file_full_path is None:
            candidate = os.path.abspath(os.path.join(public_output_dir, removed_file_name))
            removed_file_full_path = candidate if output_exists(public_output_dir, removed_file_name) else None

        print("[SWT] validated_file_full_path:", validated_file_full_path)
        print("[SWT] removed_file_full_path:", removed_file_full_path)

        if callable(on_step):
            on_step('completed', 2, 'Data Validation', 0)

        return {
            'ok': True,
            'total_records': total_records,
            'valid_records': valid_records,
            'invalid_records': invalid_records,
            'tin_invalid_count': tin_invalid_count,
            'db_duplicates_count': int(db_duplicates_count),
            'db_financial_differences_count': int(db_financial_differences_count),
            'db_financial_difference_fields_count': int(db_financial_difference_fields_count),
            'errors': errors,
            'validated_file': validated_file_name,
            'removed_data_file': removed_file_name,
            'validated_file_full_path': validated_file_full_path,
            'removed_file_full_path': removed_file_full_path,
            'output_dir': os.path.abspath(public_output_dir),
        }

    except Exception as e:
        return {
            'ok': False,
            'error': str(e),
            'errors': [],
        }

    finally:
        os.chdir(original_dir)
        try:
            if upload_history_id and output_dir_override:
                tmp_dir = os.path.abspath(str(output_dir_override))
                if os.path.basename(tmp_dir).startswith("swt_") and os.path.sep + "_validation_tmp" + os.path.sep in (os.path.sep + tmp_dir + os.path.sep):
                    shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def _run_swt_pipeline(run_id, saved_path, date_from, date_to, current_user_id=None, is_validated_file=False):
    engine = None
    start_total = time.time()
    original_dir = os.getcwd()

    try:
        if is_validated_file:
            swt_output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'swt', 'final_output'))
            logical_name = os.path.basename(str(saved_path or ''))
            if output_exists(swt_output_dir, logical_name):
                with materialize_output_to_tempfile(swt_output_dir, logical_name) as decrypted_input_path:
                    return _run_swt_pipeline(run_id, decrypted_input_path, date_from, date_to, current_user_id, is_validated_file=True)

        print("=" * 100)
        print("PIPELINE START")
        print("Timestamp:", datetime.now().isoformat())
        print("Run ID:", run_id)
        print("Thread ID:", threading.get_ident())
        print("Input file:", os.path.abspath(saved_path) if saved_path else saved_path)
        print("Current user ID:", current_user_id)
        print("=" * 100)
        # Propagate authenticated user_id into this background thread (NULL-safe).
        current_user_id = _normalize_authenticated_user_id(current_user_id)
        set_authenticated_user_id_for_context(current_user_id)

        engine = get_mysql_engine()
        log_run_start(engine, run_id, 'SWT', filename=os.path.basename(saved_path))
        log_swt_upload(engine, 
               filename=os.path.basename(saved_path),
               filepath=saved_path,
               status='Success',
               pipeline_run=True)
        _run_status[run_id] = {
            'status': 'running',
            'step': 'Initialising',
            'progress': 0,
            'user_id': current_user_id,
        }

        swt_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', '..', 'swt')
        )
        sys.path.insert(0, swt_dir)
        original_dir = os.getcwd()
        os.chdir(swt_dir)
        from swt.swt_fraud_pipeline_with_timer import SWTPipelineOrchestrator

        orchestrator = SWTPipelineOrchestrator(
            input_file  = saved_path,
            output_dir  = tempfile.mkdtemp(prefix=f'swt_{run_id}_'),
            keep_temp   = False,
            verbose     = False
        )
        print("[SWT PIPELINE] Orchestrator upload_batch_id:", getattr(orchestrator, "upload_batch_id", None))
        print("[SWT PIPELINE] Orchestrator uploaded_at:", getattr(orchestrator, "uploaded_at", None))

        # Map SWT internal steps to our step numbers
        swt_steps = [
            ('Data Preparation & Standardization', 1),
            ('Data Validation & Cleaning',         2),
            ('Feature Engineering & Rule Checking',3),
            ('Fraud Justification Generation',     4),
        ]

        # ── Step progress callback: fired by orchestrator for each step ──────
        # The orchestrator runs all steps internally; we inject a callback so
        # log_step is called at the START of each step (not all at once).
        step_start_times = {}

        def _on_step_start(step_name, step_num):
            step_start_times[step_num] = time.time()
            _run_status[run_id]['step']     = step_name
            _run_status[run_id]['progress'] = int((step_num - 1) / len(swt_steps) * 100)
            log_step(engine, run_id, 'SWT', step_num, step_name, status='started')

        def _on_step_end(step_name, step_num, success_flag):
            elapsed = round(time.time() - step_start_times.get(step_num, time.time()), 2)
            status  = 'completed' if success_flag else 'failed'
            log_step(engine, run_id, 'SWT', step_num, step_name,
                     status=status, elapsed_sec=elapsed)

        # Attach callbacks if the orchestrator supports them;
        # fall back to manual logging after run() if not.
        if hasattr(orchestrator, 'on_step_start'):
            orchestrator.on_step_start = _on_step_start
        if hasattr(orchestrator, 'on_step_end'):
            orchestrator.on_step_end   = _on_step_end

        # Fire step-1 started now (always safe — it's the first thing that runs)
        _on_step_start('Data Preparation & Standardization', 1)

        # Run the full orchestrator (it runs all steps internally)
        t0      = time.time()
        success = orchestrator.run()

        os.chdir(original_dir)
        elapsed = round(time.time() - t0, 2)
        _run_status[run_id]['step'] = 'Fetching Results'

        if not success:
            current_step = _run_status[run_id].get('step', 'SWT Orchestrator')
            current_num  = next(
                (n for name, n in swt_steps if name == current_step), 1
            )
            log_step(engine, run_id, 'SWT', current_num, current_step,
                     status='failed', elapsed_sec=elapsed,
                     message='Orchestrator reported failure')
            _run_status[run_id] = {
                'status': 'failed',
                'step':   current_step,
                'error':  'Pipeline did not complete successfully'
            }
            log_run_failed(engine, run_id, 'SWT', current_step,
                           'Pipeline returned False')
            return

        # If the orchestrator has no callback support, mark remaining steps completed
        for step_name, step_num in swt_steps:
            if step_num not in step_start_times:
                # Was never individually started — log as completed with split time
                log_step(engine, run_id, 'SWT', step_num, step_name,
                         status='completed',
                         elapsed_sec=round(elapsed / len(swt_steps), 2))

        just_df = getattr(orchestrator, 'justification_df', None)
        if just_df is None:
            raise RuntimeError('SWT current-run justification dataframe missing before background DB insert')

        final_output_dir = os.path.abspath(os.path.join(swt_dir, 'final_output'))
        os.makedirs(final_output_dir, exist_ok=True)
        export_stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        logical_justification_name = f'swt_fraud_justification_{export_stamp}.csv'
        write_encrypted_output_dataframe(just_df, final_output_dir, logical_justification_name)
        justification_final_path = os.path.join(final_output_dir, logical_justification_name)

        total_rows = int(len(just_df.index))
        _run_status[run_id] = {
            **_run_status.get(run_id, {}),
            'status': 'inserting',
            'step': 'Prediction completed. Background database insertion in progress...',
            'progress': 85,
            'user_id': current_user_id,
            'inserted_rows': 0,
            'total_rows': total_rows,
            'insert_percent': 0,
            'upload_batch_id': getattr(orchestrator, 'upload_batch_id', None),
        }

        insert_thread = threading.Thread(
            target=save_swt_justification_to_db,
            kwargs={
                'df': just_df,
                'engine': None,
                'upload_batch_id': getattr(orchestrator, 'upload_batch_id', None),
                'uploaded_at': getattr(orchestrator, 'uploaded_at', None),
                'run_id': run_id,
                'status_store': _run_status,
                'user_id': current_user_id,
                'fallback_output_path': justification_final_path,
            },
            daemon=True,
        )
        print("[SWT PIPELINE] Starting insert thread")
        print("[SWT PIPELINE] Insert thread object id:", id(insert_thread))
        print("[SWT PIPELINE] Upload Batch:", getattr(orchestrator, 'upload_batch_id', None))
        insert_thread.start()
        return

    except Exception as e:
        log_run_failed(engine, run_id, 'SWT', _run_status[run_id].get('step', '?'), e)
        _run_status[run_id] = {
            'status': 'failed',
            'error': str(e),
            'user_id': current_user_id,
        }

    finally:
        os.chdir(original_dir)
        try:
            _orchestrator = locals().get('orchestrator')
            if _orchestrator and getattr(_orchestrator, 'output_dir', None):
                shutil.rmtree(str(getattr(_orchestrator, 'output_dir')), ignore_errors=True)
        except Exception:
            pass
        if engine:
            engine.dispose()
         
        

@swt_bp.route('/api/swt/run', methods=['POST'])
def run_swt():
    file           = request.files.get('file')
    validated_file = request.form.get('validated_file', '').strip()
    date_from      = request.form.get('date_from', '')
    date_to        = request.form.get('date_to', '')

    saved_path = None
    saved_name = None

    if validated_file:
        try:
            safe_name = sanitize_file_reference(validated_file)
            backend_root = Path(__file__).resolve().parents[2]
            output_dir = (backend_root / "swt" / "final_output").resolve()
            os.makedirs(str(output_dir), exist_ok=True)
            if not output_exists(str(output_dir), safe_name):
                return jsonify({'success': False, 'error': 'validated file not found'}), 404
            saved_path = os.path.join(str(output_dir), safe_name)
            saved_name = safe_name
        except ValueError:
            return jsonify({'error': 'Invalid validated_file'}), 400
    else:
        if not file or not file.filename:
            return jsonify({'error': 'No file uploaded'}), 400
        try:
            validate_upload_file(file, allowed_extensions={'.csv', '.parquet'})
            file.stream.seek(0)
        except UploadSecurityError as exc:
            return jsonify({'error': str(exc)}), 400

    run_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    if saved_path is None:
        swt_data_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', '..', 'swt', 'Data')
        )
        os.makedirs(swt_data_dir, exist_ok=True)

        saved_name = validate_upload_file(file, allowed_extensions={'.csv', '.parquet'})
        saved_path = os.path.join(swt_data_dir, saved_name)
        file.save(saved_path)

    current_user_id = _normalize_authenticated_user_id(get_authenticated_user_id())
    _run_status[run_id] = {'status': 'queued', 'step': 'Queued', 'progress': 0, 'user_id': current_user_id}

    print("=" * 100)
    print("RUN START")
    print("Timestamp:", datetime.now().isoformat())
    print("Thread ID:", threading.get_ident())
    print("Run ID:", run_id)
    print("Validated file:", validated_file)
    print("Saved path:", os.path.abspath(saved_path) if saved_path else saved_path)
    print("User ID:", current_user_id)
    print("=" * 100)

    thread = threading.Thread(
        target=_run_swt_pipeline,
        args=(run_id, saved_path, date_from, date_to, current_user_id, bool(validated_file)),
        daemon=True
    )
    print("[SWT RUN] Starting pipeline thread")
    print("[SWT RUN] Pipeline thread object id:", id(thread))
    thread.start()

    return jsonify({'run_id': run_id, 'status': 'queued', 'message': 'SWT pipeline started'}), 202


@swt_bp.route('/api/swt/status/<run_id>', methods=['GET'])
def swt_status(run_id):
    status = _run_status.get(run_id)
    if status:
        if status.get("user_id") is None:
            maybe_user_id = _normalize_authenticated_user_id(get_authenticated_user_id())
            if maybe_user_id is not None:
                status["user_id"] = maybe_user_id
        return jsonify(status), 200

    # Fallback: if the app is running with multiple processes/workers, the in-memory
    # `_run_status` dict may not contain a run created by another worker. SWT writes
    # progress markers to `pipeline_log`, so reconstruct a minimal status view from DB.
    try:
        from sqlalchemy import text

        engine = get_mysql_engine()
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT user_id, step_number, step_name, status, error_detail, logged_at
                        FROM pipeline_log
                        WHERE run_id = :run_id
                          AND tax_type = 'SWT'
                          AND step_number IN (0, 1, 2, 3, 4, 5, 99)
                        ORDER BY logged_at DESC
                        """
                    ),
                    {"run_id": run_id},
                ).fetchall()
        finally:
            engine.dispose()

        if rows:
            latest_by_step = {}
            db_user_id = None
            for r in rows:
                if db_user_id is None and r[0] is not None:
                    db_user_id = _normalize_authenticated_user_id(r[0])
                step_num = int(r[1]) if r[1] is not None else None
                if step_num is None:
                    continue
                if step_num not in latest_by_step:
                    latest_by_step[step_num] = {
                        "step_number": step_num,
                        "step_name": r[2] or "",
                        "status": (r[3] or "").lower(),
                        "error_detail": r[4],
                        "logged_at": r[5],
                    }

            total_steps = 5
            completed_steps = {
                n
                for n in range(1, total_steps + 1)
                if latest_by_step.get(n, {}).get("status") == "completed"
            }
            has_failed = any(v.get("status") == "failed" for v in latest_by_step.values())
            ended_ok = latest_by_step.get(99, {}).get("status") == "completed"

            if has_failed:
                failed_step = next(
                    (v for v in latest_by_step.values() if v.get("status") == "failed"),
                    None,
                )
                maybe_user_id = db_user_id if db_user_id is not None else _normalize_authenticated_user_id(get_authenticated_user_id())
                return jsonify(
                    {
                        "status": "failed",
                        "step": (failed_step or {}).get("step_name") or "Failed",
                        "progress": int(len(completed_steps) / total_steps * 100),
                        "error": (failed_step or {}).get("error_detail") or "Run failed",
                        "user_id": maybe_user_id,
                    }
                ), 200

            if ended_ok:
                maybe_user_id = db_user_id if db_user_id is not None else _normalize_authenticated_user_id(get_authenticated_user_id())
                return jsonify({"status": "completed", "step": "Done", "progress": 100, "user_id": maybe_user_id}), 200

            # Running/queued: pick the most recent non-terminal step name if present.
            insert_entry = latest_by_step.get(5, {})
            is_inserting = bool(insert_entry) and insert_entry.get("status") in {"started", "completed"}
            current_step_name = ""
            for n in range(total_steps, 0, -1):
                v = latest_by_step.get(n)
                if v and v.get("step_name"):
                    current_step_name = v["step_name"]
                    break
            if not current_step_name:
                current_step_name = latest_by_step.get(0, {}).get("step_name") or "Queued"

            maybe_user_id = db_user_id if db_user_id is not None else _normalize_authenticated_user_id(get_authenticated_user_id())
            return jsonify(
                {
                    "status": "inserting" if is_inserting else "running",
                    "step": "Database Insert" if is_inserting else current_step_name,
                    "progress": int(len(completed_steps) / total_steps * 100),
                    "user_id": maybe_user_id,
                }
            ), 200

    except Exception:
        # If DB is unavailable or schema differs, keep legacy behavior.
        pass

    return jsonify({"error": "Run ID not found"}), 404


# ── GET /api/swt/progress/<run_id> ───────────────────────────

@swt_bp.route('/api/swt/progress/<run_id>', methods=['GET'])
def swt_progress(run_id):
    """Lightweight progress endpoint — returns progress % and current step only."""
    status = _run_status.get(run_id)
    if not status:
        return jsonify({'error': 'Run ID not found'}), 404
    return jsonify({
        'run_id':   run_id,
        'status':   status.get('status',   'unknown'),
        'step':     status.get('step',     ''),
        'progress': status.get('progress', 0),
    }), 200


# ── GET /api/swt/summary ──────────────────────────────────────

@swt_bp.route('/api/swt/summary', methods=['GET'])
def swt_summary():
    """Overall fraud stats across ALL records — for dashboard KPI cards."""
    try:
        import pandas as pd
        engine = get_mysql_engine()
        with engine.connect() as conn:
            df = pd.read_sql('''
                SELECT 
                    COUNT(*) as total_records,
                    SUM(predicted_fraud = 'Fraud') as fraud_count,
                    SUM(predicted_fraud = 'Non-Fraud') as non_fraud
                FROM swt_fraud_justification
            ''', conn)
        engine.dispose()

        return jsonify(df.iloc[0].to_dict()), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── GET /api/swt/results ──────────────────────────────────────

@swt_bp.route('/api/swt/results', methods=['GET'])
def swt_results():
    """Paginated SWT results — for the data table view."""
    try:
        import pandas as pd

        page     = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 100))
        offset   = (page - 1) * per_page

        engine = get_mysql_engine()
        with engine.connect() as conn:
            df = pd.read_sql(
                f'SELECT * FROM swt_fraud_justification LIMIT {per_page} OFFSET {offset}',
                conn
            )
            total_df = pd.read_sql(
                'SELECT COUNT(*) as cnt FROM swt_fraud_justification', conn
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







