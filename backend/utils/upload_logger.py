# ══════════════════════════════════════════════════════════════
#  utils/upload_logger.py
#  Shared upload history logger for CIT, GST, SWT
#  Writes to:
#    — MySQL table: upload_history
#    — File:        upload_history.log (project root)
# ══════════════════════════════════════════════════════════════

import os
import sys
import datetime
import logging
import pandas as pd

from utils.auth_helper import get_authenticated_user_id

# ── Point log file to project root regardless of which
#    subfolder the script is called from
PROJECT_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE_PATH = os.path.join(PROJECT_ROOT, 'logs', 'upload_history.log')


# ─────────────────────────────────────────────
#  Logger Setup
# ─────────────────────────────────────────────

def setup_upload_logger():
    logger = logging.getLogger('upload_history')

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    handler = logging.FileHandler(LOG_FILE_PATH, mode='a', encoding='utf-8')
    formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


# ─────────────────────────────────────────────
#  Core Upload Logger — used by all tax types
# ─────────────────────────────────────────────

def log_upload(engine, tax_type, filename, filepath,
               status='Success', error_message=None,
               pipeline_run=False, notes=None):
    """
    Logs a file upload event for any tax type.

    Parameters:
        engine        : SQLAlchemy engine (from get_mysql_engine())
        tax_type      : 'CIT', 'GST', or 'SWT'
        filename      : original filename as seen by user
        filepath      : path to file on disk
        status        : 'Success', 'Failed', or 'Partial'
        error_message : populated if status is Failed/Partial
        pipeline_run  : True if pipeline was triggered after upload
        notes         : any additional context
    """
    logger    = setup_upload_logger()
    tax_upper = tax_type.upper()
    user_id   = get_authenticated_user_id()

    def _table_has_column(_engine, table_name: str, column_name: str) -> bool:
        try:
            from sqlalchemy import text
            with _engine.connect() as conn:
                res = conn.execute(
                    text(
                        "SELECT COUNT(*) AS cnt "
                        "FROM INFORMATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() "
                        "  AND TABLE_NAME = :tbl "
                        "  AND COLUMN_NAME = :col"
                    ),
                    {"tbl": table_name, "col": column_name},
                )
                return int(res.scalar() or 0) > 0
        except Exception:
            return False

    try:
        # ── File metadata
        file_size_kb  = round(os.path.getsize(filepath) / 1024, 2) if os.path.exists(filepath) else None
        file_format   = 'parquet' if str(filepath).endswith('.parquet') else 'csv'

        # Null-safe filepath (never break uploads if it's missing/unexpected)
        try:
            filepath_value = str(filepath) if filepath else None
        except Exception:
            filepath_value = None

        # ── Row and column count
        if status == 'Success' and os.path.exists(filepath):
            if file_format == 'parquet':
                df_temp = pd.read_parquet(filepath)
                row_count    = len(df_temp)
                column_count = len(df_temp.columns)
                del df_temp
            else:
                df_temp      = pd.read_csv(filepath, nrows=0)
                column_count = len(df_temp.columns)
                del df_temp
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    row_count = sum(1 for _ in f) - 1
            
            
        else:
            row_count    = None
            column_count = None

        # ── Build record
        record = pd.DataFrame([{
            'tax_type':      tax_upper,
            'filename':      filename,
            'file_size_kb':  file_size_kb,
            'file_format':   file_format,
            'row_count':     row_count,
            'column_count':  column_count,
            'uploaded_at':   datetime.datetime.now(),
            'status':        status,
            'error_message': error_message,
            'pipeline_run':  pipeline_run,
            'notes':         notes
        }])

        # Inject authenticated user_id silently (NULL-safe) if the DB column exists.
        if _table_has_column(engine, "upload_log", "user_id"):
            record["user_id"] = user_id

        # ── Write to DB
        # Inject filepath safely (NULL-safe) if the DB column exists.
        # Backward-compatible: support both `filepath` and legacy `file_path` column names.
        if _table_has_column(engine, "upload_log", "filepath"):
            record["filepath"] = filepath_value
        elif _table_has_column(engine, "upload_log", "file_path"):
            record["file_path"] = filepath_value

        record.to_sql('upload_log', con=engine, if_exists='append', index=False)

        # ── Write to log file
        logger.info(
            f"TAX={tax_upper} | FILE={filename} | FORMAT={file_format} | "
            f"SIZE={file_size_kb}KB | ROWS={row_count} | COLS={column_count} | "
            f"STATUS={status} | PIPELINE_RUN={pipeline_run} | NOTES={notes}"
        )
        print(f"  Upload logged: {tax_upper} | {filename} | {status}")

    except Exception as e:
        # ── Even if DB write fails, always write to log file
        logger.error(
            f"TAX={tax_upper} | FILE={filename} | STATUS={status} | "
            f"ORIGINAL_ERROR={error_message} | LOG_ERROR={str(e)} | DB_WRITE=Failed"
        )
        print(f"  Warning: Could not write upload history to DB: {e}")


# ─────────────────────────────────────────────
#  Convenience wrappers per tax type
# ─────────────────────────────────────────────

def log_cit_upload(engine, filename, filepath, status='Success',
                   error_message=None, pipeline_run=False, notes=None):
    log_upload(engine, 'CIT', filename, filepath,
               status, error_message, pipeline_run, notes)


def log_gst_upload(engine, filename, filepath, status='Success',
                   error_message=None, pipeline_run=False, notes=None):
    log_upload(engine, 'GST', filename, filepath,
               status, error_message, pipeline_run, notes)


def log_swt_upload(engine, filename, filepath, status='Success',
                   error_message=None, pipeline_run=False, notes=None):
    log_upload(engine, 'SWT', filename, filepath,
               status, error_message, pipeline_run, notes)


# ─────────────────────────────────────────────
#  Pipeline Run Separators
# ─────────────────────────────────────────────

def log_pipeline_start(pipeline_name):
    logger = setup_upload_logger()
    logger.info("=" * 60)
    logger.info(
        f"PIPELINE STARTED | {pipeline_name} | "
        f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    logger.info("=" * 60)
    print(f"  Pipeline start logged: {pipeline_name}")


def log_pipeline_end(pipeline_name, total_seconds):
    logger = setup_upload_logger()
    logger.info("=" * 60)
    logger.info(
        f"PIPELINE FINISHED | {pipeline_name} | "
        f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
        f"Total time: {total_seconds:.2f}s ({total_seconds/60:.1f} min)"
    )
    logger.info("=" * 60)
    print(f"  Pipeline end logged: {pipeline_name}")
