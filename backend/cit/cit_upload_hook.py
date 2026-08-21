# ══════════════════════════════════════════════════════════════
#  cit/cit_upload_hook.py
#  Called by cit_full_pipeline_with_timer.py
#  Handles CIT upload logging and saving justification to DB
# ══════════════════════════════════════════════════════════════

import sys
import os
import uuid
from datetime import datetime
import time

# ── Allow imports from project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.db_config import get_mysql_engine
from utils.upload_logger import log_cit_upload, log_pipeline_start, log_pipeline_end
from utils.auth_helper import get_authenticated_user_id
from sqlalchemy import text  # ← Fix: required for SQLAlchemy 2.x
import pandas as pd
from utils.bulk_insert_utils import (
    DEFAULT_INSERT_CHUNK_SIZE,
    chunked_multi_insert,
    get_table_columns,
    table_exists,
)
from utils.pipeline_logger import log_step


def save_cit_justification_to_db(
    df,
    engine=None,
    upload_batch_id=None,
    uploaded_at=None,
    run_id=None,
    status_store=None,
    user_id=None,
    fallback_output_path=None,
):
    """
    Saves CIT fraud justification dataframe to MySQL table: cit_fraud_justification
    Appends rows tagged with upload_batch_id and uploaded_at for full auditability.
    """
    own_engine = False
    try:
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
        table_name = 'cit_fraud_justification'

        db_table_exists = table_exists(engine, table_name)
        if db_table_exists:
            if 'taxpayer_name' in df.columns and 'taxpayer' not in df.columns:
                df = df.rename(columns={'taxpayer_name': 'taxpayer'})
            existing_cols = get_table_columns(engine, table_name)
            for c in existing_cols:
                if c not in df.columns:
                    df[c] = None
            df_to_insert = df[existing_cols]
        else:
            df_to_insert = df

        total_rows = int(len(df_to_insert.index))
        started_at = time.time()

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
                'run_id': run_id,
            }
            log_step(
                engine, run_id, 'CIT', 6, 'Database Insert',
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
                    'run_id': run_id,
                })
                log_step(
                    engine, run_id, 'CIT', 6, 'Database Insert',
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

        if run_id and status_store is not None:
            elapsed_sec = round(time.time() - started_at, 2)
            total_records = inserted_rows
            fraud_count = 0
            result_rows = []

            try:
                with engine.connect() as conn:
                    count_df = pd.read_sql(
                        text(
                            f"SELECT COUNT(*) as cnt "
                            f"FROM {table_name} "
                            f"WHERE upload_batch_id = :upload_batch_id"
                        ),
                        conn,
                        params={"upload_batch_id": upload_batch_id},
                    )
                    result_df = pd.read_sql(
                        text(
                            f"SELECT * FROM {table_name} "
                            f"WHERE upload_batch_id = :upload_batch_id "
                            f"LIMIT 1000"
                        ),
                        conn,
                        params={"upload_batch_id": upload_batch_id},
                    )
                total_records = int(count_df.iloc[0]['cnt']) if not count_df.empty else inserted_rows
                fraud_count = int((result_df['predicted_fraud'] == 'Fraud').sum()) if 'predicted_fraud' in result_df.columns else 0
                result_rows = result_df.head(500).to_dict(orient='records')
            except Exception as summary_err:
                print(f"  Warning: CIT post-insert summary query failed: {summary_err}")

            if total_rows and total_records < total_rows:
                raise RuntimeError(
                    f"CIT insert incomplete for batch {upload_batch_id}: "
                    f"expected {total_rows}, inserted {total_records}"
                )

            log_step(
                engine, run_id, 'CIT', 6, 'Database Insert',
                status='completed',
                records_in=total_rows,
                records_out=inserted_rows,
                elapsed_sec=elapsed_sec,
                message=f'Inserted {inserted_rows} rows into {table_name}',
            )
            log_step(
                engine, run_id, 'CIT', 99, 'PIPELINE END',
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
                #'results': result_rows,
                'inserted_rows': inserted_rows,
                'total_rows': total_rows,
                'insert_percent': 100,
                'upload_batch_id': upload_batch_id,
                'user_id': user_id,
                'run_id': run_id,
            }
    except Exception as e:
        print(f"  Warning: Could not save CIT justification to DB: {e}")
        if run_id and status_store is not None:
            status_store[run_id] = {
                **status_store.get(run_id, {}),
                'status': 'failed',
                'step': 'Database Insert Failed',
                'error': str(e),
                'upload_batch_id': upload_batch_id,
                'user_id': user_id,
                'run_id': run_id,
            }
            try:
                log_step(
                    engine, run_id, 'CIT', 6, 'Database Insert',
                    status='failed',
                    records_in=int(len(df.index)) if df is not None else None,
                    error=e,
                )
            except Exception:
                pass
        script_dir   = os.path.dirname(os.path.abspath(__file__))
        fallback = fallback_output_path or os.path.join(script_dir, 'final_output', 'cit_fraud_with_justification.csv')
        os.makedirs(os.path.dirname(fallback), exist_ok=True)
        df.to_csv(fallback, index=False)
        print(f"  Fallback CSV saved: {fallback}")
    finally:
        if own_engine and engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass


def handle_cit_upload(input_file, df_loaded):
    """
    Call this right after CIT file is successfully loaded.
    Logs the upload to DB and log file.

    Parameters:
        input_file  : filename/path of the uploaded file
        df_loaded   : the loaded dataframe (used for shape info)
    """
    try:
        engine = get_mysql_engine()
        log_cit_upload(
            engine       = engine,
            filename     = os.path.basename(input_file),
            filepath     = input_file,
            status       = 'Success',
            pipeline_run = True,
            notes        = f"Shape: {df_loaded.shape}"
        )
        engine.dispose()
    except Exception as e:
        print(f"  Warning: CIT upload hook failed: {e}")


def handle_cit_upload_failure(input_file, error):
    """
    Call this in the except block if CIT file loading fails.
    """
    try:
        engine = get_mysql_engine()
        log_cit_upload(
            engine        = engine,
            filename      = os.path.basename(input_file),
            filepath      = input_file,
            status        = 'Failed',
            error_message = str(error),
            pipeline_run  = False
        )
        engine.dispose()
    except Exception as e:
        print(f"  Warning: CIT upload failure hook failed: {e}")

