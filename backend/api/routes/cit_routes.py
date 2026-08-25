# ══════════════════════════════════════════════════════════════
#  api/routes/cit_routes.py
#  POST /api/cit/run
#  Accepts uploaded file + optional date range
#  Runs CIT fraud pipeline and returns results as JSON
# ══════════════════════════════════════════════════════════════

import os
import shutil
import sys
import uuid
import time
import threading
import tempfile
from datetime import datetime
from pathlib import Path
from utils.upload_logger import log_cit_upload
from flask import Blueprint, request, jsonify


sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.db_config import get_mysql_engine
from utils.pipeline_logger import log_run_start, log_run_end, log_run_failed, log_step
from utils.auth_helper import get_authenticated_user_id, set_authenticated_user_id_for_context
from cit.cit_upload_hook import save_cit_justification_to_db
from cit.runtime_context import set_runtime_context, clear_runtime_context
from utils.file_security import (
    FinalOutputSecurityError,
    materialize_output_to_tempfile,
    output_exists,
    sanitize_file_reference,
    sanitize_output_filename,
    secure_download_response,
    write_encrypted_output_dataframe,
    write_encrypted_output_file,
)
from utils.upload_security import UploadSecurityError, validate_upload_file
from werkzeug.utils import secure_filename
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import text
import pandas as pd

cit_bp = Blueprint('cit', __name__)
_run_status = {}

BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _save_validation_upload(file, tax_prefix: str):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    validated_name = validate_upload_file(file, allowed_extensions={'.csv', '.parquet'})
    saved_filename = f"{tax_prefix}_{timestamp}_{validated_name}"
    saved_path = os.path.join(UPLOAD_FOLDER, saved_filename)
    file.save(saved_path)

    ext = os.path.splitext(validated_name)[1].lower().lstrip(".")
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
        print(f"[CIT_VALIDATE][DB] upload_history insert failed: {e}")
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
        print(f"[CIT_VALIDATE][DB] upload_validation_summary insert failed: {e}")
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
        print(f"[CIT_VALIDATE][DB] summary fetch failed: {e}")
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
        print(f"[CIT_VALIDATE][DB] upload_validation_errors insert failed: {ex}")
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
        print(f"[CIT_VALIDATE][DB] upload_validation_errors fetch failed: {ex}")
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


def _allowed_file(filename):
    return filename.lower().endswith(('.csv', '.parquet'))


def _normalize_authenticated_user_id(user_id):
    """
    CIT-only normalization: ensure we never propagate NaN/None user_id into
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


def _build_cit_run_files(base_dir: str, run_id: str):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"{timestamp}_{str(run_id).replace('-', '')[:8]}"
    return {
        "output_dir": os.path.abspath(base_dir),
        "preprocessed_file": os.path.abspath(os.path.join(base_dir, f"cit_preprocessed_data_{suffix}.csv")),
        "preprocessed_parquet_file": os.path.abspath(os.path.join(base_dir, f"cit_preprocessed_data_{suffix}.parquet")),
        "cleaned_file": os.path.abspath(os.path.join(base_dir, f"cit_cleaned_data_{suffix}.csv")),
        "removed_file": os.path.abspath(os.path.join(base_dir, f"cit_removed_data_{suffix}.csv")),
        "stamp_duty_file": os.path.abspath(os.path.join(base_dir, f"cit_stamp_duty_data_{suffix}.csv")),
        "validation_summary_file": os.path.abspath(os.path.join(base_dir, f"cit_validation_summary_{suffix}.txt")),
        "rule_violations_file": os.path.abspath(os.path.join(base_dir, f"cit_with_rule_violations_{suffix}.csv")),
        "prediction_file": os.path.abspath(os.path.join(base_dir, f"cit_final_fraud_prediction_{suffix}.csv")),
        "justification_file": os.path.abspath(os.path.join(base_dir, f"cit_fraud_with_justification_{suffix}.csv")),
    }


@cit_bp.route('/api/cit/validate', methods=['POST'])
@jwt_required()
def validate_cit():
    user_id = get_jwt_identity()

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'valid': False, 'error': 'No file uploaded'}), 400

    try:
        validate_upload_file(file, allowed_extensions={'.csv', '.parquet'})
        file.stream.seek(0)
    except UploadSecurityError as exc:
        return jsonify({'valid': False, 'error': str(exc)}), 400
    except Exception:
        pass

    upload_saved_filename = None
    upload_saved_path = None
    file_format = None
    file_size_kb = None

    try:
        if os.getenv("CIT_DUP_DEBUG", "").strip() in ("1", "true", "TRUE", "yes", "YES"):
            eng_dbg = None
            try:
                eng_dbg = get_mysql_engine()
                with eng_dbg.connect() as conn_dbg:
                    dbn = conn_dbg.execute(text("SELECT DATABASE()")).scalar()
                    cnt = conn_dbg.execute(text("SELECT COUNT(*) FROM cit_fraud_justification")).scalar()
                    print(f"[CIT_DUP_DEBUG][BEFORE validate] database={dbn} cit_fraud_justification_count={cnt}")
            finally:
                try:
                    if eng_dbg:
                        eng_dbg.dispose()
                except Exception:
                    pass
    except Exception:
        pass

    try:
        upload_saved_filename, upload_saved_path, file_format, file_size_kb = _save_validation_upload(file, "cit")
        try:
            file.stream.seek(0)
        except Exception:
            pass
    except Exception as e:
        print(f"[CIT_VALIDATE] upload save failed: {e}")

    try:
        upload_history_id = None
        engine_pre = None
        try:
            if upload_saved_filename:
                engine_pre = get_mysql_engine()
                column_count_pre = _try_get_column_count_from_file(upload_saved_path)
                upload_history_id = _try_insert_upload_history(
                    engine_pre,
                    "cit",
                    upload_saved_filename,
                    file_size_kb,
                    file_format,
                    0,
                    column_count_pre,
                )
        except Exception as e:
            print(f"[CIT_VALIDATE][DB] pre-validation upload_history insert failed: {e}")
        finally:
            try:
                if engine_pre:
                    engine_pre.dispose()
            except Exception:
                pass

        # Isolate CIT validation outputs by upload_history_id to avoid concurrent overwrite of shared filenames.
        output_dir_override = None
        try:
            if upload_history_id:
                cit_dir_abs = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'cit'))
                backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
                tmp_root = os.path.join(backend_dir, 'uploads', '_validation_tmp')
                os.makedirs(tmp_root, exist_ok=True)
                output_dir_override = os.path.join(tmp_root, f"cit_{int(upload_history_id)}")
        except Exception:
            output_dir_override = None

        from api.routes.validate_routes import _run_cit_validation as _existing_run_cit_validation
        out = _existing_run_cit_validation(output_dir_override=output_dir_override)

        if isinstance(out, tuple):
            base_resp, status_code = out[0], out[1]
        else:
            base_resp, status_code = out, getattr(out, "status_code", 200)

        payload = {}
        try:
            payload = base_resp.get_json(silent=True) or {}
        except Exception:
            payload = {}

        try:
            if os.getenv("CIT_DUP_DEBUG", "").strip() in ("1", "true", "TRUE", "yes", "YES"):
                eng_dbg2 = None
                try:
                    eng_dbg2 = get_mysql_engine()
                    with eng_dbg2.connect() as conn_dbg2:
                        dbn2 = conn_dbg2.execute(text("SELECT DATABASE()")).scalar()
                        cnt2 = conn_dbg2.execute(text("SELECT COUNT(*) FROM cit_fraud_justification")).scalar()
                        print(f"[CIT_DUP_DEBUG][AFTER validate] database={dbn2} cit_fraud_justification_count={cnt2}")
                        if isinstance(payload, dict):
                            print("[CIT_DUP_DEBUG] payload_counts=",
                                  {
                                      "total_records": payload.get("total_records"),
                                      "valid_records": payload.get("valid_records"),
                                      "invalid_records": payload.get("invalid_records"),
                                      "db_duplicates_count": payload.get("db_duplicates_count"),
                                  })
                finally:
                    try:
                        if eng_dbg2:
                            eng_dbg2.dispose()
                    except Exception:
                        pass
        except Exception:
            pass

        upload_validation_summary_id = None
        engine = None
        try:
            if status_code == 200 and isinstance(payload, dict) and "total_records" in payload and upload_saved_filename:
                engine = get_mysql_engine()
                column_count = _try_get_column_count_from_file(upload_saved_path)
                if upload_history_id:
                    _try_update_upload_history_counts(
                        engine,
                        upload_history_id,
                        payload.get("total_records", 0),
                        column_count,
                    )
                    upload_validation_summary_id = _try_insert_validation_summary(engine, upload_history_id, "cit", payload, user_id)
                    _try_insert_validation_errors(
                        engine,
                        upload_validation_summary_id,
                        upload_history_id,
                        "cit",
                        user_id,
                        payload.get("errors") or [],
                    )

                    db_counts = _try_fetch_summary_counts(engine, upload_history_id, "cit", user_id)
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
            print(f"[CIT_VALIDATE][DB] post-validation DB operations failed: {e}")
        finally:
            try:
                if engine:
                    engine.dispose()
            except Exception:
                pass

        if status_code == 200 and isinstance(payload, dict) and payload:
            payload['validated_file_path'] = payload.get('validated_file') if payload.get('validated_file') else None
            payload['removed_data_file_path'] = payload.get('removed_data_file') if payload.get('removed_data_file') else None
            payload['financial_difference_file_path'] = payload.get('financial_difference_file') if payload.get('financial_difference_file') else None
            payload['output_dir'] = None
            return jsonify(payload), status_code
        return base_resp, status_code

    except Exception as e:
        print(f"[CIT_VALIDATE] wrapper failed: {e}")
        return jsonify({'valid': False, 'error': 'Could not read file'}), 400


@cit_bp.route('/api/cit/download/<path:filename>', methods=['GET'])
@jwt_required()
def download_cit_file(filename):
    """
    Secure download endpoint for files in backend/cit/final_output.
    """
    try:
        logical_name = sanitize_output_filename(filename, expected_prefix='cit_')
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        output_dir = os.path.abspath(os.path.join(backend_dir, 'cit', 'final_output'))
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

def _run_cit_pipeline(run_id, saved_path, date_from, date_to, current_user_id=None, is_prevalidated: bool = False):
    engine = None
    original_dir = os.getcwd()

    try:
        if is_prevalidated:
            cit_output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'cit', 'final_output'))
            logical_name = os.path.basename(str(saved_path or ''))
            with materialize_output_to_tempfile(cit_output_dir, logical_name) as decrypted_input_path:
                return _run_cit_pipeline(run_id, decrypted_input_path, date_from, date_to, current_user_id, False)

        # Propagate authenticated user_id into this background thread (NULL-safe).
        current_user_id = _normalize_authenticated_user_id(current_user_id)
        set_authenticated_user_id_for_context(current_user_id)

        engine = get_mysql_engine()
        log_run_start(engine, run_id, 'CIT', filename=os.path.basename(saved_path))
        log_cit_upload(engine, 
               filename=os.path.basename(saved_path),
               filepath=saved_path,
               status='Success',
               pipeline_run=True)
        _run_status[run_id] = {
            'status': 'running',
            'step': 'Initialising',
            'progress': 0,
            'user_id': current_user_id,
            'run_id': run_id,
        }

        cit_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', '..', 'cit')
        )
        sys.path.insert(0, cit_dir)
        final_output_dir = os.path.abspath(os.path.join(cit_dir, 'final_output'))
        os.makedirs(final_output_dir, exist_ok=True)
        runtime_output_dir = tempfile.mkdtemp(prefix=f'cit_{run_id}_')
        run_files = _build_cit_run_files(str(runtime_output_dir), run_id)
        export_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        validated_final_name = f'cit_validated_{export_stamp}.csv'
        removed_final_name = f'cit_removed_data_{export_stamp}.csv'
        justification_final_name = f'cit_fraud_with_justification_{export_stamp}.csv'
        validated_final_path = os.path.join(final_output_dir, validated_final_name)
        removed_final_path = os.path.join(final_output_dir, removed_final_name)
        justification_final_path = os.path.join(final_output_dir, justification_final_name)
        set_runtime_context(
            current_input_file=os.path.abspath(saved_path),
            output_dir=run_files["output_dir"],
            CIT_PREPROCESSED_FILE=run_files["preprocessed_file"],
            CIT_PREPROCESSED_PARQUET_FILE=run_files["preprocessed_parquet_file"],
            CIT_CLEANED_FILE=run_files["cleaned_file"],
            CIT_REMOVED_FILE=run_files["removed_file"],
            CIT_STAMP_DUTY_FILE=run_files["stamp_duty_file"],
            CIT_VALIDATION_SUMMARY_FILE=run_files["validation_summary_file"],
            CIT_RULE_VIOLATIONS_FILE=run_files["rule_violations_file"],
            CIT_PREDICTION_FILE=run_files["prediction_file"],
            CIT_JUSTIFICATION_FILE=run_files["justification_file"],
        )
        from cit_fraud_pipeline_with_timer import (  # type: ignore
            run_script_1,
            run_script_2,
            run_script_3,
            run_script_4,
            run_script_5,
        )

        if is_prevalidated:
            cleaned_file_path = os.path.abspath(run_files["cleaned_file"])
            if not os.path.exists(cleaned_file_path):
                os.makedirs(os.path.dirname(cleaned_file_path), exist_ok=True)
                shutil.copy2(os.path.abspath(saved_path), cleaned_file_path)
            steps = [
                ('Rule Engine',               run_script_3, 3),
                ('Prediction',                run_script_4, 4),
                ('Generating Justification',  run_script_5, 5),
            ]
        else:
            steps = [
                ('Data Preprocessing',         run_script_1, 1),
                ('Data Validation',            run_script_2, 2),
                ('Rule Engine',                run_script_3, 3),
                ('Prediction',                 run_script_4, 4),
                ('Generating Justification',   run_script_5, 5),
            ]

        insert_batch_id = str(uuid.uuid4())
        insert_uploaded_at = datetime.utcnow()
        prev_records_out = None
        final_df = None
        total_pipeline_steps = 6
        for idx, (step_name, step_func, step_num) in enumerate(steps, start=1):
            _run_status[run_id]['step']     = step_name
            if is_prevalidated:
                _run_status[run_id]['progress'] = int(((step_num - 1) / total_pipeline_steps) * 100)
            else:
                _run_status[run_id]['progress'] = int(((step_num - 1) / total_pipeline_steps) * 100)

            log_step(engine, run_id, 'CIT', step_num, step_name, status='started', records_in=prev_records_out)
            t0 = time.time()

            try:
                result = step_func()
                elapsed = round(time.time() - t0, 2)

                # run_script_1 returns None on column validation failure
                if step_num == 1 and result is None:
                    log_step(engine, run_id, 'CIT', step_num, step_name,
                             status='failed', elapsed_sec=elapsed,
                             message='Missing required columns in dataset')
                    _run_status[run_id] = {
                        'status': 'failed',
                        'step':   step_name,
                        'error':  'Missing required columns in dataset'
                    }
                    log_run_failed(engine, run_id, 'CIT', step_name,
                                   'Missing required columns')
                    return

                records_out = len(result) if hasattr(result, '__len__') else None
                if step_num == 2 and not is_prevalidated and result is not None:
                    write_encrypted_output_dataframe(result, final_output_dir, validated_final_name)
                    if os.path.exists(run_files["removed_file"]):
                        write_encrypted_output_file(run_files["removed_file"], final_output_dir, removed_final_name)
                if step_num == 5:
                    final_df = result
                log_step(engine, run_id, 'CIT', step_num, step_name,
                         status='completed', elapsed_sec=elapsed,
                         records_out=records_out)
                prev_records_out = records_out

            except Exception as step_err:
                elapsed = round(time.time() - t0, 2)
                log_step(engine, run_id, 'CIT', step_num, step_name,
                         status='failed', elapsed_sec=elapsed, error=step_err)
                _run_status[run_id] = {
                    'status': 'failed', 'step': step_name, 'error': str(step_err)
                }
                log_run_failed(engine, run_id, 'CIT', step_name, step_err)
                return

        os.chdir(original_dir)
        if final_df is None:
            raise RuntimeError('CIT justification dataframe missing before background DB insert')

        write_encrypted_output_dataframe(final_df, final_output_dir, justification_final_name)

        total_rows = int(len(final_df.index))
        _run_status[run_id] = {
            **_run_status.get(run_id, {}),
            'status': 'inserting',
            'step': 'Prediction completed. Background database insertion in progress...',
            'progress': 85,
            'user_id': current_user_id,
            'inserted_rows': 0,
            'total_rows': total_rows,
            'insert_percent': 0,
            'upload_batch_id': insert_batch_id,
            'run_id': run_id,
        }

        insert_thread = threading.Thread(
            target=save_cit_justification_to_db,
            kwargs={
                'df': final_df,
                'engine': None,
                'upload_batch_id': insert_batch_id,
                'uploaded_at': insert_uploaded_at,
                'run_id': run_id,
                'status_store': _run_status,
                'user_id': current_user_id,
                'fallback_output_path': justification_final_path,
            },
            daemon=True,
        )
        insert_thread.start()
        return

    except Exception as e:
        log_run_failed(engine, run_id, 'CIT', _run_status[run_id].get('step', '?'), e)
        _run_status[run_id] = {
            'status': 'failed',
            'error': str(e),
            'user_id': current_user_id,
            'run_id': run_id,
        }

    finally:
        clear_runtime_context()
        try:
            runtime_dir = locals().get('runtime_output_dir')
            if runtime_dir:
                shutil.rmtree(runtime_dir, ignore_errors=True)
        except Exception:
            pass
        os.chdir(original_dir)
        if engine:
            engine.dispose()
        


@cit_bp.route('/api/cit/run', methods=['POST'])
@jwt_required()
def run_cit():
    file           = request.files.get('file')
    validated_file = request.form.get('validated_file', '').strip()
    is_prevalidated = bool(validated_file)
    date_from      = request.form.get('date_from', '')
    date_to        = request.form.get('date_to', '')

    saved_path = None
    saved_name = None

    if validated_file:
        try:
            safe_name = sanitize_file_reference(validated_file)
            backend_root = Path(__file__).resolve().parents[2]
            output_dir = (backend_root / "cit" / "final_output").resolve()
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
        cit_data_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', '..', 'cit', 'data')
        )
        os.makedirs(cit_data_dir, exist_ok=True)

        saved_name = validate_upload_file(file, allowed_extensions={'.csv', '.parquet'})
        saved_path = os.path.join(cit_data_dir, saved_name)
        file.save(saved_path)

    print("[CIT RUN] prevalidated =", is_prevalidated)
    print("[CIT RUN] saved_path =", saved_path)

    current_user_id = _normalize_authenticated_user_id(get_authenticated_user_id())
    _run_status[run_id] = {'status': 'queued', 'step': 'Queued', 'progress': 0, 'user_id': current_user_id, 'run_id': run_id}

    thread = threading.Thread(
        target=_run_cit_pipeline,
        args=(run_id, saved_path, date_from, date_to, current_user_id, is_prevalidated),
        daemon=True
    )
    thread.start()

    return jsonify({'run_id': run_id, 'status': 'queued', 'message': 'CIT pipeline started'}), 202


@cit_bp.route('/api/cit/status/<run_id>', methods=['GET'])
def cit_status(run_id):
    status = _run_status.get(run_id)
    if status:
        if status.get("user_id") is None:
            maybe_user_id = _normalize_authenticated_user_id(get_authenticated_user_id())
            if maybe_user_id is not None:
                status["user_id"] = maybe_user_id
        return jsonify(status), 200

    # Fallback for multi-process deployments: reconstruct minimal state from DB
    # pipeline_log when the in-memory dict doesn't contain this run_id.
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
                          AND tax_type = 'CIT'
                          AND step_number IN (0, 1, 2, 3, 4, 5, 6, 99)
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

            total_steps = 6
            completed_steps = {
                n
                for n in range(1, total_steps + 1)
                if latest_by_step.get(n, {}).get("status") == "completed"
            }
            has_failed = any(v.get("status") == "failed" for v in latest_by_step.values())
            insert_completed = latest_by_step.get(6, {}).get("status") == "completed"
            ended_ok = latest_by_step.get(99, {}).get("status") == "completed" or insert_completed

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
                        "run_id": run_id,
                    }
                ), 200

            if ended_ok:
                maybe_user_id = db_user_id if db_user_id is not None else _normalize_authenticated_user_id(get_authenticated_user_id())
                return jsonify({"status": "completed", "step": "Done", "progress": 100, "user_id": maybe_user_id, "run_id": run_id}), 200

            insert_entry = latest_by_step.get(6, {})
            is_inserting = bool(insert_entry) and insert_entry.get("status") == "started"
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
                    "run_id": run_id,
                }
            ), 200

    except Exception:
        pass

    return jsonify({"error": "Run ID not found"}), 404


# ── GET /api/cit/progress/<run_id> ───────────────────────────

@cit_bp.route('/api/cit/progress/<run_id>', methods=['GET'])
def cit_progress(run_id):
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


# ── GET /api/cit/summary ──────────────────────────────────────

@cit_bp.route('/api/cit/summary', methods=['GET'])
def cit_summary():
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
                FROM cit_fraud_justification
            ''', conn)
        engine.dispose()

        return jsonify(df.iloc[0].to_dict()), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── GET /api/cit/results ──────────────────────────────────────

@cit_bp.route('/api/cit/results', methods=['GET'])
def cit_results():
    """Paginated CIT results — for the data table view."""
    try:
        import pandas as pd

        page     = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 100))
        offset   = (page - 1) * per_page

        engine = get_mysql_engine()
        with engine.connect() as conn:
            df = pd.read_sql(
                f'SELECT * FROM cit_fraud_justification LIMIT {per_page} OFFSET {offset}',
                conn
            )
            total_df = pd.read_sql(
                'SELECT COUNT(*) as cnt FROM cit_fraud_justification', conn
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


