# ══════════════════════════════════════════════════════════════
#  gst/gst_upload_hook.py
#  Called by gst_full_pipe_line_with_timer.py
#  Handles GST upload logging and saving justification to DB
# ══════════════════════════════════════════════════════════════

import sys
import os
import uuid
from datetime import datetime
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.db_config import get_mysql_engine
from utils.upload_logger import log_gst_upload, log_pipeline_start, log_pipeline_end
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


def _update_latest_gst_upload_batch_references(engine, upload_batch_id, user_id):
    """Best-effort backfill for GST upload tracking tables."""
    if not upload_batch_id:
        return

    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE upload_log
                    SET upload_batch_id = :upload_batch_id
                    WHERE id = (
                        SELECT latest_id FROM (
                            SELECT id AS latest_id
                            FROM upload_log
                            WHERE tax_type = 'GST'
                              AND user_id = :user_id
                              AND upload_batch_id IS NULL
                            ORDER BY uploaded_at DESC
                            LIMIT 1
                        ) x
                    )
                    """
                ),
                {"upload_batch_id": upload_batch_id, "user_id": user_id},
            )
        print(f"GST upload_log updated with batch id: {upload_batch_id}")
    except Exception as e:
        print(f"Warning: upload_log update failed: {e}")

    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE upload_history
                    SET upload_batch_id = :upload_batch_id
                    WHERE id = (
                        SELECT latest_id FROM (
                            SELECT id AS latest_id
                            FROM upload_history
                            WHERE tax_type = 'gst'
                              AND upload_batch_id IS NULL
                            ORDER BY uploaded_at DESC
                            LIMIT 1
                        ) x
                    )
                    """
                ),
                {"upload_batch_id": upload_batch_id},
            )
        print(f"GST upload_history updated with batch id: {upload_batch_id}")
    except Exception as e:
        print(f"Warning: upload_history update failed: {e}")


def save_gst_justification_to_db(
    df,
    engine=None,
    upload_batch_id=None,
    uploaded_at=None,
    run_id=None,
    status_store=None,
    user_id=None,
):
    """
    Saves GST fraud justification dataframe to MySQL table: gst_fraud_justification
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
        table_name = 'gst_fraud_justification'

        db_table_exists = table_exists(engine, table_name)
        if db_table_exists:
            existing_cols = get_table_columns(engine, table_name)
            missing_cols = {c: None for c in existing_cols if c not in df.columns}
            if missing_cols:
                df = df.assign(**missing_cols)
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
            }
            log_step(
                engine, run_id, 'GST', 5, 'Database Insert',
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
                    engine, run_id, 'GST', 5, 'Database Insert',
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
            atomic=True,
        )

        if not db_table_exists:
            print(f"  Created and populated MySQL table: {table_name}")
        else:
            print(f"  Appended to MySQL table: {table_name}")
        print("  Insert completed successfully")

        if run_id and status_store is not None:
            status_store[run_id].update({
                'status': 'completed',
                'progress': 100,
                'step': 'Upload completed successfully.',
                'inserted_rows': inserted_rows,
                'total_rows': total_rows,
                'insert_percent': 100,
                'upload_batch_id': upload_batch_id,
                'user_id': user_id,
            })

        _update_latest_gst_upload_batch_references(engine, upload_batch_id, user_id)

        if run_id and status_store is not None:
            try:
                total_records = inserted_rows
                result_df = df.head(500)
                if 'predicted_fraud' in df.columns:
                    fraud_count = int((df['predicted_fraud'] == 'Fraud').sum())
                elif 'is_fraud' in df.columns:
                    fraud_count = int((df['is_fraud'] == 1).sum())
                else:
                    fraud_count = 0
                elapsed_sec = round(time.time() - started_at, 2)
                log_step(
                    engine, run_id, 'GST', 5, 'Database Insert',
                    status='completed',
                    records_in=total_rows,
                    records_out=inserted_rows,
                    elapsed_sec=elapsed_sec,
                    message=f'Inserted {inserted_rows} rows into {table_name}',
                )
                log_step(
                    engine, run_id, 'GST', 99, 'PIPELINE END',
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
                    #'results': status_store.get(run_id, {}).get('results', []),
                    'inserted_rows': inserted_rows,
                    'total_rows': total_rows,
                    'insert_percent': 100,
                    'upload_batch_id': upload_batch_id,
                    'user_id': user_id,
                }
            except Exception as e:
                print(f"  Warning: GST upload summary update failed: {e}")
    except Exception as e:
        print(f"  Warning: Could not save GST justification to DB: {e}")
        if run_id and status_store is not None:
            status_store[run_id] = {
                **status_store.get(run_id, {}),
                'status': 'failed',
                'progress': 100,
                'step': 'Database Insert Failed',
                'error': str(e),
                'upload_batch_id': upload_batch_id,
                'user_id': user_id,
            }
            try:
                log_step(
                    engine, run_id, 'GST', 5, 'Database Insert',
                    status='failed',
                    records_in=int(len(df.index)) if df is not None else None,
                    error=e,
                )
            except Exception:
                pass
        fallback = 'gst_fraud_with_justification.csv'
        df.to_csv(fallback, index=False)
        print(f"  Fallback CSV saved: {fallback}")
    finally:
        if own_engine and engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass


def handle_gst_upload(input_file, df_loaded):
    """
    Call this right after GST file is successfully loaded.
    """
    try:
        engine = get_mysql_engine()
        log_gst_upload(
            engine       = engine,
            filename     = os.path.basename(input_file),
            filepath     = input_file,
            status       = 'Success',
            pipeline_run = True,
            notes        = f"Shape: {df_loaded.shape}"
        )
        engine.dispose()
    except Exception as e:
        print(f"  Warning: GST upload hook failed: {e}")


def handle_gst_upload_failure(input_file, error):
    """
    Call this in the except block if GST file loading fails.
    """
    try:
        engine = get_mysql_engine()
        log_gst_upload(
            engine        = engine,
            filename      = os.path.basename(input_file),
            filepath      = input_file,
            status        = 'Failed',
            error_message = str(error),
            pipeline_run  = False
        )
        engine.dispose()
    except Exception as e:
        print(f"  Warning: GST upload failure hook failed: {e}")
