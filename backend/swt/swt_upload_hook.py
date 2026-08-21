# ══════════════════════════════════════════════════════════════
#  swt/swt_upload_hook.py
#  Called by swt_full_pipe_line_with_timer.py
#  Handles SWT upload logging and saving justification to DB
# ══════════════════════════════════════════════════════════════

import sys
import os
import uuid
import threading
from datetime import datetime
from sqlalchemy import text
import traceback
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.db_config import get_mysql_engine
from utils.upload_logger import log_swt_upload, log_pipeline_start, log_pipeline_end
from utils.auth_helper import get_authenticated_user_id
import pandas as pd
from utils.bulk_insert_utils import (
    DEFAULT_INSERT_CHUNK_SIZE,
    chunked_multi_insert,
    get_table_columns,
    table_exists,
)
from utils.pipeline_logger import log_step


def save_swt_justification_to_db(
    df,
    engine=None,
    upload_batch_id=None,
    uploaded_at=None,
    run_id=None,
    status_store=None,
    user_id=None,
):
    own_engine = False
    try:
        print("=" * 100)
        print("ENTER save_swt_justification_to_db")
        print("Timestamp:", datetime.utcnow().isoformat())
        print("Run ID:", run_id)
        print("Upload Batch:", upload_batch_id)
        print("Thread ID:", threading.get_ident())
        print("Rows:", 0 if df is None else int(len(df.index)))
        print("DataFrame id():", id(df))
        traceback.print_stack()
        print("=" * 100)
        debug = os.environ.get("SWT_PIPELINE_DEBUG", "").strip() == "1"
        if df is None:
            raise ValueError("SWT justification dataframe is None before DB insert")
        if getattr(df, "empty", True):
            raise ValueError("SWT justification dataframe empty before DB insert")
        if debug:
            try:
                print("SWT DB insert dataframe shape:", df.shape)
                print("SWT DB insert columns:", df.columns.tolist())
                print(df.head(2))
            except Exception:
                pass

        if upload_batch_id is None:
            upload_batch_id = str(uuid.uuid4())
        if uploaded_at is None:
            uploaded_at = datetime.utcnow()
        if engine is None:
            engine = get_mysql_engine()
            own_engine = True
        if user_id is None:
            user_id = get_authenticated_user_id()

        df['upload_batch_id'] = upload_batch_id
        df['uploaded_at'] = uploaded_at
        df['user_id'] = user_id
        table_name = 'swt_fraud_justification'

        current_db = None
        pre_count = None
        if debug:
            try:
                with engine.connect() as conn:
                    current_db = conn.execute(text("SELECT DATABASE()")).scalar()
            except Exception:
                current_db = None

        db_table_exists = table_exists(engine, table_name)

        if db_table_exists and debug:
            try:
                with engine.connect() as conn:
                    pre_count = conn.execute(text(f"SELECT COUNT(*) FROM `{table_name}`")).scalar()
            except Exception:
                pre_count = None

        if db_table_exists:
            existing_cols = get_table_columns(engine, table_name)
            # If DB schema still uses legacy/raw SWT column names, map them at insert layer only.
            legacy_map = {
                "TIN": "tin",
                "TaxPeriodYear": "tax_period_year",
                "Tax Period Year": "tax_period_year",
                "TaxPeriodMonth": "tax_period_month",
                "Tax Period Month": "tax_period_month",
                "AssessmentNo": "assessment_number",
                "Assessment No": "assessment_number",
                "Assessment No.": "assessment_number",
                "EntryDate": "entry_date",
                "Entry Date": "entry_date",
                "AssessedDate": "assessed_date",
                "Assessed Date": "assessed_date",
                "DueDate": "due_date",
                "Due Date": "due_date",
                "10.No.EmployeesonPayroll": "employees_on_payroll",
                "10.No.Employees on Payroll": "employees_on_payroll",
                "20.TotalSalaryWagesPaid": "total_salary_wages_paid",
                "20.Total Salary Wages Paid": "total_salary_wages_paid",
                "30.No.SWTEmployees": "employees_paid_swt",
                "30.No.SWT Employees": "employees_paid_swt",
                "40.SWPaidForSWTDeduct": "sw_paid_for_swt_deduction",
                "40.SW Paid For SWT Deduct": "sw_paid_for_swt_deduction",
                "50.TotalSWTAXDeducted": "total_swt_tax_deducted",
                "50.Total SW TAX Deducted": "total_swt_tax_deducted",
            }
            for legacy_col, canonical_col in legacy_map.items():
                if legacy_col in existing_cols and legacy_col not in df.columns and canonical_col in df.columns:
                    df[legacy_col] = df[canonical_col]
            # Add any columns the DB has but DataFrame doesn't
            for c in existing_cols:
                if c not in df.columns:
                    df[c] = None
            df_to_insert = df[existing_cols]
        else:
            df_to_insert = df

        total_rows = int(len(df_to_insert.index))
        started_at = time.time()

        existing_batch_rows = 0
        if db_table_exists and upload_batch_id:
            with engine.connect() as conn:
                existing_batch_rows = int(
                    conn.execute(
                        text(
                            "SELECT COUNT(*) "
                            "FROM swt_fraud_justification "
                            "WHERE upload_batch_id = :upload_batch_id"
                        ),
                        {"upload_batch_id": upload_batch_id},
                    ).scalar() or 0
                )
            if existing_batch_rows >= total_rows and total_rows > 0:
                print(
                    f"[SWT DB INSERT] Skipping duplicate insert for upload_batch_id={upload_batch_id} "
                    f"(existing_rows={existing_batch_rows}, incoming_rows={total_rows})"
                )
                if run_id and status_store is not None:
                    elapsed_sec = round(time.time() - started_at, 2)
                    log_step(
                        engine, run_id, 'SWT', 5, 'Database Insert',
                        status='completed',
                        records_in=total_rows,
                        records_out=existing_batch_rows,
                        elapsed_sec=elapsed_sec,
                        message=f'Batch {upload_batch_id} already inserted; skipped duplicate insert',
                    )
                    log_step(
                        engine, run_id, 'SWT', 99, 'PIPELINE END',
                        status='completed',
                        records_out=existing_batch_rows,
                        elapsed_sec=elapsed_sec,
                        message=f'Total time: {elapsed_sec:.1f}s ({elapsed_sec/60:.1f} min)',
                    )
                    status_store[run_id] = {
                        **status_store.get(run_id, {}),
                        'status': 'completed',
                        'progress': 100,
                        'step': 'Upload completed successfully.',
                        'total_records': existing_batch_rows,
                        'fraud_count': status_store.get(run_id, {}).get('fraud_count', 0),
                        'non_fraud': status_store.get(run_id, {}).get('non_fraud', 0),
                        'elapsed_sec': elapsed_sec,
                        #'results': status_store.get(run_id, {}).get('results', []),
                        'inserted_rows': existing_batch_rows,
                        'total_rows': total_rows,
                        'insert_percent': 100,
                        'upload_batch_id': upload_batch_id,
                        'user_id': user_id,
                    }
                return
            if 0 < existing_batch_rows < total_rows:
                raise RuntimeError(
                    f"Partial SWT batch already exists for upload_batch_id={upload_batch_id} "
                    f"(existing_rows={existing_batch_rows}, incoming_rows={total_rows}); refusing duplicate append"
                )

        if run_id and status_store is not None:
            status_store[run_id] = {
                **status_store.get(run_id, {}),
                'status': 'inserting',
                'step': 'Prediction completed. Background database insertion in progress...',
                'progress': 85,
                'inserted_rows': 0,
                'total_rows': total_rows,
                'insert_percent': 0,
                'upload_batch_id': upload_batch_id,
                'user_id': user_id,
            }
            log_step(
                engine, run_id, 'SWT', 5, 'Database Insert',
                status='started',
                records_in=total_rows,
                message='Prediction completed. Background database insertion in progress...',
            )

        def _on_chunk(inserted_rows, all_rows, chunk_index, total_chunks):
            print(f"  Inserted {inserted_rows} / {all_rows} rows into {table_name}")
            if run_id and status_store is not None:
                insert_percent = int((inserted_rows / all_rows) * 100) if all_rows else 100
                status_store[run_id].update({
                    'status': 'inserting',
                    'step': f'Inserted {inserted_rows} / {all_rows} rows',
                    'progress': min(99, 85 + int(insert_percent * 0.14)),
                    'inserted_rows': inserted_rows,
                    'total_rows': all_rows,
                    'insert_percent': insert_percent,
                    'upload_batch_id': upload_batch_id,
                    'user_id': user_id,
                })
                log_step(
                    engine, run_id, 'SWT', 5, 'Database Insert',
                    status='started',
                    substep_name=f'Chunk {chunk_index}/{total_chunks}',
                    records_in=all_rows,
                    records_out=inserted_rows,
                    message=f'Inserted {inserted_rows} / {all_rows} rows',
                )

        inserted_rows = chunked_multi_insert(
            df_to_insert,
            table_name,
            engine,
            table_already_exists=db_table_exists,
            chunksize=DEFAULT_INSERT_CHUNK_SIZE,
            progress_callback=_on_chunk,
        )

        if not db_table_exists:
            print(f"  Created and populated MySQL table: {table_name}")
        else:
            print(f"  Appended to MySQL table: {table_name}")
        print("  Insert completed successfully")
        try:
            with engine.connect() as conn:
                batch_counts = pd.read_sql(
                    text(
                        "SELECT upload_batch_id, COUNT(*) AS cnt "
                        "FROM swt_fraud_justification "
                        "GROUP BY upload_batch_id "
                        "ORDER BY cnt DESC"
                    ),
                    conn,
                )
            print("[SWT DB INSERT] upload_batch_id counts:")
            print(batch_counts.head(20))
        except Exception as e:
            print(f"[SWT DB INSERT] Could not fetch upload_batch_id counts: {e}")

        if debug:
            try:
                with engine.connect() as conn:
                    post_count = conn.execute(text(f"SELECT COUNT(*) FROM `{table_name}`")).scalar()
                print("SWT DB insert database:", current_db)
                print("SWT DB insert table:", table_name)
                print("SWT DB rows before insert:", pre_count)
                print("SWT DB rows after insert:", post_count)
            except Exception:
                pass

        if run_id and status_store is not None:
            with engine.connect() as conn:
                count_df = pd.read_sql(f'SELECT COUNT(*) as cnt FROM {table_name}', conn)
                result_df = pd.read_sql(f'SELECT * FROM {table_name} LIMIT 1000', conn)
            total_records = int(count_df.iloc[0]['cnt']) if not count_df.empty else inserted_rows
            fraud_count = int((result_df['predicted_fraud'] == 'Fraud').sum()) if 'predicted_fraud' in result_df.columns else 0
            elapsed_sec = round(time.time() - started_at, 2)
            log_step(
                engine, run_id, 'SWT', 5, 'Database Insert',
                status='completed',
                records_in=total_rows,
                records_out=inserted_rows,
                elapsed_sec=elapsed_sec,
                message=f'Inserted {inserted_rows} rows into {table_name}',
            )
            log_step(
                engine, run_id, 'SWT', 99, 'PIPELINE END',
                status='completed',
                records_out=total_records,
                elapsed_sec=elapsed_sec,
                message=f'Total time: {elapsed_sec:.1f}s ({elapsed_sec/60:.1f} min)',
            )
            status_store[run_id] = {
                **status_store.get(run_id, {}),
                'status': 'completed',
                'progress': 100,
                'step': 'Upload completed successfully.',
                'total_records': total_records,
                'fraud_count': fraud_count,
                'non_fraud': total_records - fraud_count,
                'elapsed_sec': elapsed_sec,
                #'results': result_df.head(500).to_dict(orient='records'),
                'inserted_rows': inserted_rows,
                'total_rows': total_rows,
                'insert_percent': 100,
                'upload_batch_id': upload_batch_id,
                'user_id': user_id,
            }
    except Exception as e:
        print(f"  Warning: Could not save SWT justification to DB: {e}")
        print(traceback.format_exc())
        if run_id and status_store is not None:
            status_store[run_id] = {
                **status_store.get(run_id, {}),
                'status': 'failed',
                'step': 'Database Insert Failed',
                'error': str(e),
                'upload_batch_id': upload_batch_id,
                'user_id': user_id,
            }
            try:
                log_step(
                    engine, run_id, 'SWT', 5, 'Database Insert',
                    status='failed',
                    records_in=int(len(df.index)) if df is not None else None,
                    error=e,
                )
            except Exception:
                pass
        fallback = 'swt_fraud_with_justification.csv'
        try:
            df_fallback = df.copy() if df is not None else pd.DataFrame()
            for col in df_fallback.select_dtypes(include=["object", "string"]).columns.tolist():
                df_fallback[col] = df_fallback[col].astype(str)
            df_fallback.to_csv(fallback, index=False, encoding="utf-8-sig")
        except Exception:
            print("  Warning: Fallback CSV write failed:\n" + traceback.format_exc())
        print(f"  Fallback CSV saved: {fallback}")
    finally:
        if own_engine and engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass
                                
                                
   


def handle_swt_upload(input_file, df_loaded):
    """
    Call this right after SWT file is successfully loaded.
    """
    try:
        engine = get_mysql_engine()
        log_swt_upload(
            engine       = engine,
            filename     = os.path.basename(input_file),
            filepath     = input_file,
            status       = 'Success',
            pipeline_run = True,
            notes        = f"Shape: {df_loaded.shape}"
        )
        engine.dispose()
    except Exception as e:
        print(f"  Warning: SWT upload hook failed: {e}")


def handle_swt_upload_failure(input_file, error):
    """
    Call this in the except block if SWT file loading fails.
    """
    try:
        engine = get_mysql_engine()
        log_swt_upload(
            engine        = engine,
            filename      = os.path.basename(input_file),
            filepath      = input_file,
            status        = 'Failed',
            error_message = str(error),
            pipeline_run  = False
        )
        engine.dispose()
    except Exception as e:
        print(f"  Warning: SWT upload failure hook failed: {e}")
