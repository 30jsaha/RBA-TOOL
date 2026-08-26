# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  utils/pipeline_logger.py
#  Step-by-step logger for GST, SWT, CIT pipelines
#  Writes to MySQL table: pipeline_logs
#  and to file: pipeline_steps.log
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

import os
import sys
import datetime
import logging
import traceback
import pandas as pd

from utils.auth_helper import get_authenticated_user_id

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE_PATH  = os.path.join(PROJECT_ROOT, 'logs', 'pipeline_steps.log')

_UNICODE_REPLACEMENTS = {
    # Preferred (actual unicode symbols)
    "▶": "[START]",
    "✓": "[OK]",
    "✔": "[OK]",
    "✗": "[ERROR]",
    "✘": "[ERROR]",
    "⏳": "[WAIT]",
    "⏭": "[SKIP]",
    "›": ">",
    "—": "-",
    # Common mojibake forms if this file was saved/loaded with the wrong encoding
    "â–¶": "[START]",
    "âœ”": "[OK]",
    "âœ—": "[ERROR]",
    "â­": "[SKIP]",
    "â€º": ">",
    "â€”": "-",
}


def _sanitize_for_console(message: object) -> str:
    text = str(message)
    for src, dst in _UNICODE_REPLACEMENTS.items():
        text = text.replace(src, dst)
    return text


def safe_console_print(message: object) -> None:
    """Windows-safe console print (cp1252-safe)."""
    msg = _sanitize_for_console(message)
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "cp1252"
        safe = msg.encode(enc, errors="replace").decode(enc, errors="replace")
        print(safe)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  File Logger Setup
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _get_file_logger():
    logger = logging.getLogger('pipeline_steps')
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    try:
        os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)
        handler = logging.FileHandler(LOG_FILE_PATH, mode='a', encoding='utf-8')
        formatter = logging.Formatter(
            fmt='%(asctime)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    except Exception as exc:
        safe_console_print(f"[PIPELINE_LOGGER] Warning: FileHandler creation failed: {exc}")
    return logger


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  DB Table DDL â€” run once
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

PIPELINE_LOG_DDL = """
CREATE TABLE IF NOT EXISTS pipeline_log (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         BIGINT NULL,
    run_id          VARCHAR(40)  NOT NULL,
    tax_type        VARCHAR(10)  NOT NULL,
    step_number     INT,
    step_name       VARCHAR(100),
    substep_name    VARCHAR(100),
    status          VARCHAR(20)  NOT NULL,
    records_in      INT,
    records_out     INT,
    elapsed_sec     FLOAT,
    message         TEXT,
    error_detail    TEXT,
    logged_at       DATETIME     NOT NULL
)
"""

def ensure_pipeline_log_table(engine):
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text(PIPELINE_LOG_DDL))
        conn.commit()


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Core log function
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def log_step(engine, run_id, tax_type, step_number, step_name,
             status, substep_name=None, records_in=None,
             records_out=None, elapsed_sec=None,
             message=None, error=None):
    """
    Log a single pipeline step or substep.

    Parameters:
        engine       : SQLAlchemy engine
        run_id       : unique ID for this pipeline run (e.g. uuid or timestamp)
        tax_type     : 'CIT', 'GST', or 'SWT'
        step_number  : integer step number (1, 2, 3 ...)
        step_name    : e.g. 'Column Standardization'
        substep_name : optional sub-step label e.g. 'TIN Validation'
        status       : 'started' | 'completed' | 'failed' | 'skipped'
        records_in   : row count going into this step
        records_out  : row count coming out of this step
        elapsed_sec  : time taken in seconds (float)
        message      : any plain-text note
        error        : exception object or string (only on failure)
    """
    logger     = _get_file_logger()
    tax_upper  = tax_type.upper()
    now        = datetime.datetime.now()
    error_str  = None
    user_id    = get_authenticated_user_id()

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

    if error is not None:
        if isinstance(error, Exception):
            error_str = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        else:
            error_str = str(error)

    label = f"[{tax_upper}] Step {step_number}"
    if substep_name:
        label += f" > {substep_name}"
    else:
        label += f" > {step_name}"

    # â”€â”€ Console print
    icon = {'started': '[START]', 'completed': '[OK]', 'failed': '[ERROR]', 'skipped': '[SKIP]'}.get(status, '·')
    parts = [f"{icon}  {label} - {status.upper()}"]
    if records_in  is not None: parts.append(f"in={records_in:,}")
    if records_out is not None: parts.append(f"out={records_out:,}")
    if elapsed_sec is not None: parts.append(f"{elapsed_sec:.2f}s")
    if message:                 parts.append(message)
    safe_console_print("  " + " | ".join(parts))

    # â”€â”€ File log
    logger.info(" | ".join([
        f"RUN={run_id}", f"TAX={tax_upper}",
        f"STEP={step_number}", f"NAME={step_name}",
        f"SUB={substep_name or '-'}", f"STATUS={status.upper()}",
        f"IN={records_in}", f"OUT={records_out}",
        f"SEC={elapsed_sec}", f"MSG={message}",
    ]))
    if error_str:
        logger.error(f"RUN={run_id} | ERROR:\n{error_str}")

    # â”€â”€ DB log
    try:
        from config.db_config import get_mysql_engine
        log_engine = get_mysql_engine()
        ensure_pipeline_log_table(log_engine)
        record = pd.DataFrame([{
            'user_id':      user_id,
            'run_id':       run_id,
            'tax_type':     tax_upper,
            'step_number':  step_number,
            'step_name':    step_name,
            'substep_name': substep_name,
            'status':       status,
            'records_in':   records_in,
            'records_out':  records_out,
            'elapsed_sec':  elapsed_sec,
            'message':      message,
            'error_detail': error_str,
            'logged_at':    now,
        }])
        # If the DB schema doesn't have user_id yet, drop it to avoid breaking logging.
        if not _table_has_column(log_engine, "pipeline_log", "user_id"):
            record = record.drop(columns=["user_id"], errors="ignore")
        record.to_sql('pipeline_log', con=log_engine, if_exists='append', index=False)
        log_engine.dispose()
    except Exception as e:
        logger.error(f"RUN={run_id} | Could not write step log to DB: {e}") 
        safe_console_print(f"  [PIPELINE LOG ERROR] {e}")

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Convenience: run-level markers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def log_run_start(engine, run_id, tax_type, filename=None):
    log_step(engine, run_id, tax_type,
             step_number=0, step_name='PIPELINE START',
             status='started',
             message=f"File: {filename or '-'}")

def log_run_end(engine, run_id, tax_type, total_sec, total_records=None):
    log_step(engine, run_id, tax_type,
             step_number=99, step_name='PIPELINE END',
             status='completed',
             elapsed_sec=total_sec,
             records_out=total_records,
             message=f"Total time: {total_sec:.1f}s ({total_sec/60:.1f} min)")

def log_run_failed(engine, run_id, tax_type, step_name, error):
    log_step(engine, run_id, tax_type,
             step_number=99, step_name='PIPELINE FAILED',
             status='failed',
             message=f"Failed at: {step_name}",
             error=error)

