# ══════════════════════════════════════════════════════════════
#  api/routes/multi_tax_routes.py
# ══════════════════════════════════════════════════════════════

import os
import sys
import logging
import json
import threading
import time
import uuid
import numpy as np
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Blueprint, request, jsonify
from sqlalchemy import bindparam, text

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.db_config import get_mysql_engine
from utils.auth_helper import get_authenticated_user_id
from utils.database_locks import financial_data_lock

multi_tax_bp = Blueprint('multi_tax', __name__)
logger = logging.getLogger(__name__)

# Tracks background refresh jobs: {job_id: {status, ...}}
_refresh_status = {}
_refresh_status_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'uploads', '_multitax_refresh_status')
)
os.makedirs(_refresh_status_dir, exist_ok=True)


def _refresh_status_path(job_id):
    return os.path.join(_refresh_status_dir, f"{job_id}.json")


def _write_refresh_status(job_id, payload):
    os.makedirs(_refresh_status_dir, exist_ok=True)
    tmp_path = _refresh_status_path(job_id) + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=True)
    os.replace(tmp_path, _refresh_status_path(job_id))


def _set_refresh_status(job_id, **updates):
    current = dict(_refresh_status.get(job_id) or {})
    current.update(updates)
    current['job_id'] = job_id
    _refresh_status[job_id] = current
    try:
        _write_refresh_status(job_id, current)
    except Exception:
        logger.exception('Failed to persist refresh status for job %s', job_id)
    return current


def _get_refresh_status(job_id):
    current = _refresh_status.get(job_id)
    if current:
        return current

    status_path = _refresh_status_path(job_id)
    if not os.path.exists(status_path):
        return None

    try:
        with open(status_path, 'r', encoding='utf-8') as fh:
            current = json.load(fh)
        _refresh_status[job_id] = current
        return current
    except Exception:
        logger.exception('Failed to read persisted refresh status for job %s', job_id)
        return None


def _count_rows_if_exists(conn, table_name):
    exists = conn.execute(
        text(
            'SELECT COUNT(*) FROM information_schema.tables '
            'WHERE table_schema = DATABASE() AND table_name = :table_name'
        ),
        {'table_name': table_name},
    ).scalar()
    if not exists:
        return None
    return int(conn.execute(text(f'SELECT COUNT(*) FROM {table_name}')).scalar() or 0)


def _collect_multitax_counts(conn):
    return {
        'agg_cit': _count_rows_if_exists(conn, 'agg_cit'),
        'agg_gst': _count_rows_if_exists(conn, 'agg_gst'),
        'agg_swt': _count_rows_if_exists(conn, 'agg_swt'),
        'multi_tax_integration_results_new': _count_rows_if_exists(conn, 'multi_tax_integration_results_new'),
        'multi_tax_integration_results': _count_rows_if_exists(conn, 'multi_tax_integration_results'),
    }


def _log_multitax_counts(conn, label):
    counts = _collect_multitax_counts(conn)
    logger.info('[%s] row counts: %s', label, counts)
    return counts


def _get_connection_id(conn):
    try:
        return conn.execute(text("SELECT CONNECTION_ID()")).scalar()
    except Exception:
        logger.exception("Failed to fetch MySQL connection id for diagnostics.")
        return None


def _sql_preview(sql, max_len=240):
    compact = " ".join(str(sql).split())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3] + "..."


# ─────────────────────────────────────────────
#  AGG TABLE REFRESH  (also called daily at 01:00)
# ─────────────────────────────────────────────

def _table_exists(conn, table_name):
    return bool(
        conn.execute(
            text(
                'SELECT COUNT(*) FROM information_schema.tables '
                'WHERE table_schema = DATABASE() AND table_name = :table_name'
            ),
            {'table_name': table_name},
        ).scalar()
    )


def _table_columns(conn, table_name):
    rows = conn.execute(
        text(
            'SELECT COLUMN_NAME FROM information_schema.columns '
            'WHERE table_schema = DATABASE() AND table_name = :table_name'
        ),
        {'table_name': table_name},
    ).fetchall()
    return {row[0] for row in rows}


def _ensure_permanent_agg_tables_exist(conn):
    missing_tables = [
        table_name
        for table_name in ('agg_cit', 'agg_gst', 'agg_swt')
        if not _table_exists(conn, table_name)
    ]
    if missing_tables:
        raise RuntimeError(
            'Missing permanent aggregate table(s): '
            + ', '.join(missing_tables)
            + '. Create them once via a manual migration before running multi-tax refresh.'
        )


def _resolve_latest_uploaded_years(conn, table_name, user_id=None):
    columns = _table_columns(conn, table_name)
    if 'tax_period_year' not in columns:
        return []

    filters = ['tax_period_year IS NOT NULL']
    params = {}
    if user_id is not None and 'user_id' in columns:
        filters.append('user_id = :user_id')
        params['user_id'] = user_id
    where_sql = ' AND '.join(filters)

    if 'upload_batch_id' in columns:
        sql = f"""
            SELECT DISTINCT tax_period_year
            FROM {table_name}
            WHERE {where_sql}
              AND upload_batch_id = (
                  SELECT MAX(upload_batch_id)
                  FROM {table_name}
                  WHERE {where_sql}
              )
            ORDER BY tax_period_year
        """
    elif 'uploaded_at' in columns:
        sql = f"""
            SELECT DISTINCT tax_period_year
            FROM {table_name}
            WHERE {where_sql}
              AND uploaded_at = (
                  SELECT MAX(uploaded_at)
                  FROM {table_name}
                  WHERE {where_sql}
              )
            ORDER BY tax_period_year
        """
    else:
        sql = f"""
            SELECT DISTINCT tax_period_year
            FROM {table_name}
            WHERE {where_sql}
              AND tax_period_year = (
                  SELECT MAX(tax_period_year)
                  FROM {table_name}
                  WHERE {where_sql}
              )
            ORDER BY tax_period_year
        """

    rows = conn.execute(text(sql), params).fetchall()
    years = []
    for row in rows:
        year_value = row[0]
        if year_value is None:
            continue
        years.append(int(year_value))
    return years


def _resolve_refresh_years(conn, user_id=None):
    years = set()
    for source_table in (
        'cit_fraud_justification',
        'gst_fraud_justification',
        'swt_fraud_justification',
    ):
        years.update(_resolve_latest_uploaded_years(conn, source_table, user_id=user_id))
    return sorted(years)


def _agg_table_has_year_user_unique_key(conn, table_name):
    row = conn.execute(
        text(
            'SELECT GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ",") AS key_columns '
            'FROM information_schema.statistics '
            'WHERE table_schema = DATABASE() '
            '  AND table_name = :table_name '
            '  AND non_unique = 0 '
            'GROUP BY index_name '
            "HAVING key_columns = 'tin,tax_period_year,user_id' "
            'LIMIT 1'
        ),
        {'table_name': table_name},
    ).fetchone()
    return bool(row)


def _build_cit_agg_insert_sql(table_name, use_upsert=False):
    sql = f"""
        INSERT INTO {table_name} (
            tin, taxpayer_name, tax_account_number, assessment_number,
            tax_period_year, sector_activity, enterprise_activity,
            cit_total_gross_income, cit_gross_sales, cit_salaries_or_wages,
            cit_total_tax_payable, cit_net_tax_payable, cit_fraud_flag, user_id
        )
        SELECT
            CAST(tin AS CHAR(20)) AS tin,
            taxpayer AS taxpayer_name,
            tax_account_no AS tax_account_number,
            assessment_no AS assessment_number,
            tax_period_year,
            sector_activity,
            enterprise_activity,
            total_gross_income AS cit_total_gross_income,
            gross_sales_cash_or_credit AS cit_gross_sales,
            salaries_or_wages AS cit_salaries_or_wages,
            total_tax_payable AS cit_total_tax_payable,
            net_tax_payable_or_refunda AS cit_net_tax_payable,
            MAX(predicted_fraud = 'Fraud') AS cit_fraud_flag,
            :user_id AS user_id
        FROM cit_fraud_justification
        WHERE tax_period_year = :tax_period_year
        GROUP BY
            tin, taxpayer, tax_account_no, assessment_no,
            tax_period_year, sector_activity, enterprise_activity,
            total_gross_income, gross_sales_cash_or_credit,
            salaries_or_wages, total_tax_payable, net_tax_payable_or_refunda
    """
    if use_upsert:
        sql += """
        ON DUPLICATE KEY UPDATE
            taxpayer_name = VALUES(taxpayer_name),
            tax_account_number = VALUES(tax_account_number),
            assessment_number = VALUES(assessment_number),
            sector_activity = VALUES(sector_activity),
            enterprise_activity = VALUES(enterprise_activity),
            cit_total_gross_income = VALUES(cit_total_gross_income),
            cit_gross_sales = VALUES(cit_gross_sales),
            cit_salaries_or_wages = VALUES(cit_salaries_or_wages),
            cit_total_tax_payable = VALUES(cit_total_tax_payable),
            cit_net_tax_payable = VALUES(cit_net_tax_payable),
            cit_fraud_flag = VALUES(cit_fraud_flag),
            user_id = VALUES(user_id)
        """
    return sql


def _build_gst_agg_insert_sql(table_name, use_upsert=False):
    sql = f"""
        INSERT INTO {table_name} (
            tin, taxpayer_name, taxpayer_type, tax_account_number,
            assessment_number, tax_period_year, gst_total_sales_income,
            gst_taxable_sales, gst_output_debits, gst_input_credits,
            gst_payable, gst_refundable, gst_fraud_flag, user_id
        )
        SELECT
            CAST(tin AS CHAR(20)) AS tin,
            taxpayer_name,
            taxpayer_type,
            tax_account_number,
            assessment_number,
            tax_period_year,
            SUM(total_sales_income) AS gst_total_sales_income,
            SUM(gst_taxable_sales) AS gst_taxable_sales,
            SUM(output_debits) AS gst_output_debits,
            SUM(input_credits) AS gst_input_credits,
            SUM(gst_payable) AS gst_payable,
            SUM(gst_refundable) AS gst_refundable,
            MAX(predicted_fraud = 'Fraud') AS gst_fraud_flag,
            :user_id AS user_id
        FROM gst_fraud_justification
        WHERE tax_period_year = :tax_period_year
        GROUP BY
            tin, taxpayer_name, taxpayer_type,
            tax_account_number, assessment_number, tax_period_year
    """
    if use_upsert:
        sql += """
        ON DUPLICATE KEY UPDATE
            taxpayer_name = VALUES(taxpayer_name),
            taxpayer_type = VALUES(taxpayer_type),
            tax_account_number = VALUES(tax_account_number),
            assessment_number = VALUES(assessment_number),
            gst_total_sales_income = VALUES(gst_total_sales_income),
            gst_taxable_sales = VALUES(gst_taxable_sales),
            gst_output_debits = VALUES(gst_output_debits),
            gst_input_credits = VALUES(gst_input_credits),
            gst_payable = VALUES(gst_payable),
            gst_refundable = VALUES(gst_refundable),
            gst_fraud_flag = VALUES(gst_fraud_flag),
            user_id = VALUES(user_id)
        """
    return sql


def _build_swt_agg_insert_sql(table_name, use_upsert=False):
    sql = f"""
        INSERT INTO {table_name} (
            tin, taxpayer_name, tax_account_number, assessment_number,
            tax_period_year, swt_total_salary_wages_paid,
            swt_total_tax_deducted, swt_employees_on_payroll,
            swt_employees_paid_swt, swt_fraud_flag, user_id
        )
        SELECT
            CAST(tin AS CHAR(20)) AS tin,
            taxpayer_name,
            tax_account_number,
            assessment_number,
            tax_period_year,
            SUM(total_salary_wages_paid) AS swt_total_salary_wages_paid,
            SUM(total_swt_tax_deducted) AS swt_total_tax_deducted,
            SUM(employees_on_payroll) AS swt_employees_on_payroll,
            SUM(employees_paid_swt) AS swt_employees_paid_swt,
            MAX(predicted_fraud = 'Fraud') AS swt_fraud_flag,
            :user_id AS user_id
        FROM swt_fraud_justification
        WHERE tax_period_year = :tax_period_year
        GROUP BY
            tin, taxpayer_name, tax_account_number,
            assessment_number, tax_period_year
    """
    if use_upsert:
        sql += """
        ON DUPLICATE KEY UPDATE
            taxpayer_name = VALUES(taxpayer_name),
            tax_account_number = VALUES(tax_account_number),
            assessment_number = VALUES(assessment_number),
            swt_total_salary_wages_paid = VALUES(swt_total_salary_wages_paid),
            swt_total_tax_deducted = VALUES(swt_total_tax_deducted),
            swt_employees_on_payroll = VALUES(swt_employees_on_payroll),
            swt_employees_paid_swt = VALUES(swt_employees_paid_swt),
            swt_fraud_flag = VALUES(swt_fraud_flag),
            user_id = VALUES(user_id)
        """
    return sql


def _refresh_multi_tax_tables_unlocked(current_user_id=None, status_callback=None):
    logger.info('Starting multi-tax table refresh...')
    engine = get_mysql_engine()
    user_id = current_user_id
    if callable(status_callback):
        status_callback(status='running', stage='refresh_started', message='[REFRESH] Started')
    try:
        with engine.connect() as conn:
            _ensure_permanent_agg_tables_exist(conn)

            if user_id is None:
                try:
                    user_id = get_authenticated_user_id()
                except Exception:
                    user_id = None

            refresh_years = _resolve_refresh_years(conn, user_id=user_id)
            if not refresh_years:
                raise RuntimeError(
                    'Could not determine an uploaded financial year from the source tax tables.'
                )

            logger.info('Refreshing permanent agg tables for tax_period_year values: %s', refresh_years)

            agg_configs = [
                ('agg_cit', _build_cit_agg_insert_sql),
                ('agg_gst', _build_gst_agg_insert_sql),
                ('agg_swt', _build_swt_agg_insert_sql),
            ]
            agg_upsert_support = {
                table_name: _agg_table_has_year_user_unique_key(conn, table_name)
                for table_name, _ in agg_configs
            }

            for tax_year in refresh_years:
                params = {'tax_period_year': int(tax_year), 'user_id': user_id}
                logger.info('[REFRESH] Rebuilding aggregate slices for tax_period_year=%s', tax_year)
                try:
                    for table_name, insert_sql_builder in agg_configs:
                        use_upsert = agg_upsert_support[table_name]
                        if not use_upsert:
                            _execute_logged_sql(
                                conn,
                                f'delete_{table_name}_{tax_year}',
                                f'DELETE FROM {table_name} WHERE tax_period_year = :tax_period_year',
                                params={'tax_period_year': int(tax_year)},
                                success_message=f'{table_name} slice cleared for {tax_year}.',
                            )
                        _execute_logged_sql(
                            conn,
                            f'insert_{table_name}_{tax_year}',
                            insert_sql_builder(table_name, use_upsert=use_upsert),
                            params=params,
                            success_message=f'{table_name} slice refreshed for {tax_year}.',
                        )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

            if callable(status_callback):
                status_callback(
                    status='running',
                    stage='aggregation_complete',
                    message='[REFRESH] Aggregation complete',
                )

            _log_multitax_counts(conn, 'REFRESH Aggregation complete')
        logger.info('Multi-tax agg table refresh complete.')
    except Exception as e:
        logger.error(f'Multi-tax agg refresh failed: {e}')
        if callable(status_callback):
            status_callback(
                status='error',
                stage='aggregation_failed',
                message='[REFRESH] Aggregation failed',
                detail=str(e),
            )
        raise
    finally:
        engine.dispose()

    if callable(status_callback):
        status_callback(
            status='running',
            stage='integration_started',
            message='[REFRESH] Integration started',
        )
    integration_started_at = time.perf_counter()
    logger.info(
        '[REFRESH][thread=%s] BEFORE run_multi_tax_integration current_user_id=%s',
        threading.get_ident(),
        user_id,
    )
    run_multi_tax_integration(current_user_id=user_id, status_callback=status_callback)
    integration_elapsed = time.perf_counter() - integration_started_at
    logger.info(
        '[REFRESH][thread=%s] AFTER run_multi_tax_integration elapsed_sec=%.3f',
        threading.get_ident(),
        integration_elapsed,
    )


def refresh_multi_tax_tables(current_user_id=None, status_callback=None):
    """Refresh derived data without racing a reset or a source-table insert."""
    lock_engine = get_mysql_engine()
    try:
        with financial_data_lock(lock_engine, timeout_seconds=30):
            return _refresh_multi_tax_tables_unlocked(
                current_user_id=current_user_id,
                status_callback=status_callback,
            )
    finally:
        lock_engine.dispose()


scheduler = BackgroundScheduler()
scheduler.add_job(refresh_multi_tax_tables, 'cron', hour=1, minute=0)
if not scheduler.running:
    scheduler.start()


# ─────────────────────────────────────────────
#  INTEGRATION LOGIC
# ─────────────────────────────────────────────

def _ensure_permanent_integration_table(conn, table_name):
    if _table_exists(conn, table_name):
        return
    _execute_logged_sql(
        conn,
        'create_prod_table',
        _build_multitax_create_table_sql(table_name),
        success_message=f'{table_name} created.',
    )
    _execute_logged_sql(
        conn,
        'add_prod_generated_column',
        _build_multitax_generated_column_sql(table_name),
        success_message=f'{table_name} generated column added.',
    )
    _execute_logged_sql(
        conn,
        'create_prod_indexes',
        _build_multitax_index_sql(table_name),
        success_message=f'{table_name} indexes created.',
    )


def run_multi_tax_integration(current_user_id=None, status_callback=None):
    engine = get_mysql_engine()
    lock_name = "multi_tax_integration_lock"
    prod_table = "multi_tax_integration_results"
    lock_acquired = False
    conn = None
    try:
        conn = engine.connect()
        python_thread_id = threading.get_ident()
        connection_id = _get_connection_id(conn)
        logger.info("Starting multi-tax integration...")
        database_type, database_version = _get_database_details(conn)
        logger.info(f"Database: {database_type} {database_version}")
        _log_source_table_definitions(conn)
        _log_multitax_counts(conn, 'REFRESH Integration pre-lock')

        get_lock_started_at = time.perf_counter()
        logger.info(
            "[REFRESH][thread=%s][conn=%s] BEFORE GET_LOCK lock_name=%s timeout_sec=30",
            python_thread_id,
            connection_id,
            lock_name,
        )
        lock_result = conn.execute(
            text("SELECT GET_LOCK(:lock_name, 30)"),
            {"lock_name": lock_name},
        ).scalar()
        get_lock_elapsed = time.perf_counter() - get_lock_started_at
        logger.info(
            "[REFRESH][thread=%s][conn=%s] AFTER GET_LOCK elapsed_sec=%.3f result=%s",
            python_thread_id,
            connection_id,
            get_lock_elapsed,
            lock_result,
        )
        if lock_result != 1:
            raise RuntimeError("Could not obtain MySQL named lock for multi-tax integration.")
        lock_acquired = True
        logger.info("Named lock acquired.")

        user_id = current_user_id
        if user_id is None:
            try:
                user_id = get_authenticated_user_id()
            except Exception:
                user_id = None

        refresh_years = _resolve_refresh_years(conn, user_id=user_id)
        if not refresh_years:
            raise RuntimeError(
                'Could not determine an uploaded financial year from the source tax tables.'
            )

        _ensure_permanent_integration_table(conn, prod_table)
        conn.commit()

        delete_sql = text(
            f"DELETE FROM {prod_table} WHERE tax_period_year IN :refresh_years"
        ).bindparams(bindparam('refresh_years', expanding=True))
        insert_sql = _build_multitax_insert_sql(
            prod_table,
            year_filter=True,
            user_id_as_param=True,
        )

        try:
            conn.execute(delete_sql, {'refresh_years': [int(year) for year in refresh_years]})
            rows_inserted = 0
            for tax_year in refresh_years:
                rows_inserted += int(
                    conn.execute(
                        text(insert_sql),
                        {'tax_period_year': int(tax_year), 'user_id': user_id},
                    ).rowcount or 0
                )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.error("Integration insert failed; starting diagnostic stages.")
            _run_multitax_diagnostics(conn)
            raise

        logger.info(
            'Production integration table refreshed for tax_period_year values: %s rows_inserted=%s',
            refresh_years,
            rows_inserted,
        )
        _log_multitax_counts(conn, 'REFRESH Integration finished')

        logger.info("Finished successfully.")
        row_count = conn.execute(text("SELECT COUNT(*) FROM multi_tax_integration_results")).scalar()
        counts = _log_multitax_counts(conn, 'REFRESH Integration finished')
        if callable(status_callback):
            status_callback(
                status='completed',
                stage='integration_completed',
                message='[REFRESH] Integration finished',
                counts=counts,
                rows_saved=int(row_count or 0),
            )
        return {'rows_saved': row_count}

    except Exception as e:
        logger.exception(f"Integration failed: {e}")
        if callable(status_callback):
            detail = str(e)
            counts = None
            if conn is not None:
                try:
                    counts = _log_multitax_counts(conn, 'REFRESH Integration failed')
                except Exception:
                    counts = None
            status_callback(
                status='error',
                stage='integration_failed',
                message='[REFRESH] Integration failed',
                detail=detail,
                counts=counts,
            )
        raise
    finally:
        try:
            if lock_acquired and conn is not None:
                conn.execute(
                    text("SELECT RELEASE_LOCK(:lock_name)"),
                    {"lock_name": lock_name},
                )
                logger.info("Named lock released.")
        except Exception:
            logger.exception("Failed to release MySQL named lock.")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    logger.exception("Failed to close MySQL connection.")
            engine.dispose()


def _get_database_details(conn):
    version = conn.execute(text("SELECT VERSION()")).scalar() or "Unknown"
    version_lower = str(version).lower()
    database_type = "MariaDB" if "mariadb" in version_lower else "MySQL"
    return database_type, version


def _log_source_table_definitions(conn):
    for table_name in ("agg_cit", "agg_gst", "agg_swt"):
        try:
            create_row = conn.execute(text(f"SHOW CREATE TABLE {table_name}")).fetchone()
            logger.info(f"SHOW CREATE TABLE {table_name}: {create_row[1]}")
        except BaseException as exc:
            logger.exception(f"Failed to inspect {table_name}: {exc}")


def _execute_logged_sql(conn, stage, sql, params=None, success_message=None):
    try:
        python_thread_id = threading.get_ident()
        connection_id = _get_connection_id(conn)
        sql_started_at = time.perf_counter()
        logger.info(
            "[REFRESH][thread=%s][conn=%s] START %s sql=%s",
            python_thread_id,
            connection_id,
            stage,
            _sql_preview(sql),
        )
        result = conn.execute(text(sql), params or {})
        sql_elapsed = time.perf_counter() - sql_started_at
        logger.info(
            "[REFRESH][thread=%s][conn=%s] END %s elapsed_sec=%.3f affected_rows=%s",
            python_thread_id,
            connection_id,
            stage,
            sql_elapsed,
            result.rowcount,
        )
        if success_message:
            logger.info(success_message)
        return result.rowcount
    except Exception as exc:
        logger.exception(f"SQL failed at stage {stage}: {exc}")
        logger.error(f"Failing SQL ({stage}): {sql}")
        raise


def _build_multitax_create_table_sql(table_name):
    return f"""
        CREATE TABLE {table_name} (
            tin VARCHAR(20) DEFAULT NULL,
            taxpayer_name MEDIUMTEXT DEFAULT NULL,
            taxpayer_type TEXT DEFAULT NULL,
            tax_account_number BIGINT(20) DEFAULT NULL,
            assessment_number BIGINT(20) DEFAULT NULL,
            tax_period_year BIGINT(20) DEFAULT NULL,
            sector_activity TEXT DEFAULT NULL,
            enterprise_activity TEXT DEFAULT NULL,
            cit_gross_sales DOUBLE DEFAULT NULL,
            cit_total_gross_income DOUBLE DEFAULT NULL,
            cit_salaries_or_wages DOUBLE DEFAULT NULL,
            cit_total_tax_payable DOUBLE DEFAULT NULL,
            cit_net_tax_payable DOUBLE DEFAULT NULL,
            gst_total_sales_income DOUBLE DEFAULT NULL,
            gst_taxable_sales DOUBLE DEFAULT NULL,
            gst_output_debits DOUBLE DEFAULT NULL,
            gst_input_credits DOUBLE DEFAULT NULL,
            gst_payable DOUBLE DEFAULT NULL,
            gst_refundable DOUBLE DEFAULT NULL,
            swt_total_salary_wages_paid DOUBLE DEFAULT NULL,
            swt_total_tax_deducted DOUBLE DEFAULT NULL,
            swt_employees_on_payroll DOUBLE DEFAULT NULL,
            swt_employees_paid_swt DOUBLE DEFAULT NULL,
            gst_vs_cit_sales_diff DOUBLE DEFAULT NULL,
            gst_vs_cit_sales_diff_abs DOUBLE DEFAULT NULL,
            gst_vs_cit_sales_pct DOUBLE DEFAULT NULL,
            swt_vs_cit_salary_diff DOUBLE DEFAULT NULL,
            swt_vs_cit_salary_diff_abs DOUBLE DEFAULT NULL,
            swt_vs_cit_salary_pct DOUBLE DEFAULT NULL,
            gst_validation VARCHAR(50) DEFAULT NULL,
            swt_validation VARCHAR(50) DEFAULT NULL,
            cit_fraud_flag INT(11) DEFAULT NULL,
            gst_fraud_flag INT(11) DEFAULT NULL,
            swt_fraud_flag INT(11) DEFAULT NULL,
            flagged_in_tax_types BIGINT(20) DEFAULT NULL,
            user_id BIGINT(20) DEFAULT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
    """


def _build_multitax_insert_sql(table_name, year_filter=False, user_id_as_param=False):
    year_clause = 'WHERE c.tax_period_year = :tax_period_year' if year_filter else ''
    gst_not_exists_year_clause = ' AND g.tax_period_year = :tax_period_year' if year_filter else ''
    swt_not_exists_year_clause = ' AND s.tax_period_year = :tax_period_year' if year_filter else ''
    user_id_expr = 'CAST(:user_id AS SIGNED)' if user_id_as_param else 'CAST(NULL AS SIGNED)'
    return f"""
        INSERT INTO {table_name} (
            tin, taxpayer_name, taxpayer_type,
            tax_account_number, assessment_number, tax_period_year,
            sector_activity, enterprise_activity,
            cit_gross_sales, cit_total_gross_income,
            cit_salaries_or_wages, cit_total_tax_payable, cit_net_tax_payable,
            gst_total_sales_income, gst_taxable_sales,
            gst_output_debits, gst_input_credits,
            gst_payable, gst_refundable,
            swt_total_salary_wages_paid, swt_total_tax_deducted,
            swt_employees_on_payroll, swt_employees_paid_swt,
            gst_vs_cit_sales_diff, gst_vs_cit_sales_diff_abs, gst_vs_cit_sales_pct,
            swt_vs_cit_salary_diff, swt_vs_cit_salary_diff_abs, swt_vs_cit_salary_pct,
            gst_validation, swt_validation,
            cit_fraud_flag, gst_fraud_flag, swt_fraud_flag,
            flagged_in_tax_types, user_id
        )
        SELECT
            COALESCE(c.tin, g.tin, s.tin) COLLATE utf8mb4_general_ci AS tin,
            COALESCE(c.taxpayer_name, g.taxpayer_name, s.taxpayer_name) COLLATE utf8mb4_general_ci AS taxpayer_name,
            g.taxpayer_type COLLATE utf8mb4_general_ci AS taxpayer_type,
            COALESCE(c.tax_account_number, g.tax_account_number, s.tax_account_number) AS tax_account_number,
            COALESCE(c.assessment_number,  g.assessment_number,  s.assessment_number) AS assessment_number,
            COALESCE(c.tax_period_year, g.tax_period_year, s.tax_period_year) AS tax_period_year,
            c.sector_activity COLLATE utf8mb4_general_ci AS sector_activity,
            c.enterprise_activity COLLATE utf8mb4_general_ci AS enterprise_activity,
            c.cit_gross_sales, c.cit_total_gross_income,
            c.cit_salaries_or_wages, c.cit_total_tax_payable, c.cit_net_tax_payable,
            g.gst_total_sales_income, g.gst_taxable_sales,
            g.gst_output_debits, g.gst_input_credits,
            g.gst_payable, g.gst_refundable,
            s.swt_total_salary_wages_paid, s.swt_total_tax_deducted,
            s.swt_employees_on_payroll, s.swt_employees_paid_swt,
            (g.gst_total_sales_income - c.cit_gross_sales) AS gst_vs_cit_sales_diff,
            ABS(g.gst_total_sales_income - c.cit_gross_sales) AS gst_vs_cit_sales_diff_abs,
            ABS(g.gst_total_sales_income - c.cit_gross_sales)
                / NULLIF(ABS(c.cit_gross_sales), 0) * 100 AS gst_vs_cit_sales_pct,
            (s.swt_total_salary_wages_paid - c.cit_salaries_or_wages) AS swt_vs_cit_salary_diff,
            ABS(s.swt_total_salary_wages_paid - c.cit_salaries_or_wages) AS swt_vs_cit_salary_diff_abs,
            ABS(s.swt_total_salary_wages_paid - c.cit_salaries_or_wages)
                / NULLIF(ABS(c.cit_salaries_or_wages), 0) * 100 AS swt_vs_cit_salary_pct,
            (
                CASE
                    WHEN g.gst_total_sales_income IS NULL THEN 'No GST Record' COLLATE utf8mb4_general_ci
                    WHEN ABS(g.gst_total_sales_income - c.cit_gross_sales) > 10 THEN 'Sales Mismatch' COLLATE utf8mb4_general_ci
                    ELSE 'Valid' COLLATE utf8mb4_general_ci
                END
            ) COLLATE utf8mb4_general_ci AS gst_validation,
            (
                CASE
                    WHEN s.swt_total_salary_wages_paid IS NULL THEN 'No SWT Record' COLLATE utf8mb4_general_ci
                    WHEN ABS(s.swt_total_salary_wages_paid - c.cit_salaries_or_wages) > 5 THEN 'Salary Mismatch' COLLATE utf8mb4_general_ci
                    ELSE 'Valid' COLLATE utf8mb4_general_ci
                END
            ) COLLATE utf8mb4_general_ci AS swt_validation,
            COALESCE(c.cit_fraud_flag, 0) AS cit_fraud_flag,
            COALESCE(g.gst_fraud_flag, 0) AS gst_fraud_flag,
            COALESCE(s.swt_fraud_flag, 0) AS swt_fraud_flag,
            (COALESCE(c.cit_fraud_flag,0) + COALESCE(g.gst_fraud_flag,0) + COALESCE(s.swt_fraud_flag,0)) AS flagged_in_tax_types,
            {user_id_expr} AS user_id
        FROM agg_cit c
        LEFT JOIN agg_gst g ON c.tin = g.tin AND c.tax_period_year = g.tax_period_year
        LEFT JOIN agg_swt s ON c.tin = s.tin AND c.tax_period_year = s.tax_period_year
        {year_clause}

        UNION ALL

        SELECT
            g.tin COLLATE utf8mb4_general_ci AS tin,
            g.taxpayer_name COLLATE utf8mb4_general_ci AS taxpayer_name,
            g.taxpayer_type COLLATE utf8mb4_general_ci AS taxpayer_type,
            g.tax_account_number,
            g.assessment_number,
            g.tax_period_year,
            CAST(NULL AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_general_ci AS sector_activity,
            CAST(NULL AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_general_ci AS enterprise_activity,
            CAST(NULL AS DOUBLE) AS cit_gross_sales,
            CAST(NULL AS DOUBLE) AS cit_total_gross_income,
            CAST(NULL AS DOUBLE) AS cit_salaries_or_wages,
            CAST(NULL AS DOUBLE) AS cit_total_tax_payable,
            CAST(NULL AS DOUBLE) AS cit_net_tax_payable,
            g.gst_total_sales_income,
            g.gst_taxable_sales,
            g.gst_output_debits,
            g.gst_input_credits,
            g.gst_payable,
            g.gst_refundable,
            CAST(NULL AS DOUBLE) AS swt_total_salary_wages_paid,
            CAST(NULL AS DOUBLE) AS swt_total_tax_deducted,
            CAST(NULL AS DOUBLE) AS swt_employees_on_payroll,
            CAST(NULL AS DOUBLE) AS swt_employees_paid_swt,
            CAST(NULL AS DOUBLE) AS gst_vs_cit_sales_diff,
            CAST(NULL AS DOUBLE) AS gst_vs_cit_sales_diff_abs,
            CAST(NULL AS DOUBLE) AS gst_vs_cit_sales_pct,
            CAST(NULL AS DOUBLE) AS swt_vs_cit_salary_diff,
            CAST(NULL AS DOUBLE) AS swt_vs_cit_salary_diff_abs,
            CAST(NULL AS DOUBLE) AS swt_vs_cit_salary_pct,
            'No CIT Record' COLLATE utf8mb4_general_ci AS gst_validation,
            'No SWT Record' COLLATE utf8mb4_general_ci AS swt_validation,
            0 AS cit_fraud_flag,
            COALESCE(g.gst_fraud_flag,0) AS gst_fraud_flag,
            0 AS swt_fraud_flag,
            COALESCE(g.gst_fraud_flag,0) AS flagged_in_tax_types,
            {user_id_expr} AS user_id
        FROM agg_gst g
        WHERE 1 = 1{gst_not_exists_year_clause}
          AND NOT EXISTS (
            SELECT 1 FROM agg_cit c
            WHERE c.tin = g.tin AND c.tax_period_year = g.tax_period_year
        )

        UNION ALL

        SELECT
            s.tin COLLATE utf8mb4_general_ci AS tin,
            s.taxpayer_name COLLATE utf8mb4_general_ci AS taxpayer_name,
            CAST(NULL AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_general_ci AS taxpayer_type,
            s.tax_account_number,
            s.assessment_number,
            s.tax_period_year,
            CAST(NULL AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_general_ci AS sector_activity,
            CAST(NULL AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_general_ci AS enterprise_activity,
            CAST(NULL AS DOUBLE) AS cit_gross_sales,
            CAST(NULL AS DOUBLE) AS cit_total_gross_income,
            CAST(NULL AS DOUBLE) AS cit_salaries_or_wages,
            CAST(NULL AS DOUBLE) AS cit_total_tax_payable,
            CAST(NULL AS DOUBLE) AS cit_net_tax_payable,
            CAST(NULL AS DOUBLE) AS gst_total_sales_income,
            CAST(NULL AS DOUBLE) AS gst_taxable_sales,
            CAST(NULL AS DOUBLE) AS gst_output_debits,
            CAST(NULL AS DOUBLE) AS gst_input_credits,
            CAST(NULL AS DOUBLE) AS gst_payable,
            CAST(NULL AS DOUBLE) AS gst_refundable,
            s.swt_total_salary_wages_paid,
            s.swt_total_tax_deducted,
            s.swt_employees_on_payroll,
            s.swt_employees_paid_swt,
            CAST(NULL AS DOUBLE) AS gst_vs_cit_sales_diff,
            CAST(NULL AS DOUBLE) AS gst_vs_cit_sales_diff_abs,
            CAST(NULL AS DOUBLE) AS gst_vs_cit_sales_pct,
            CAST(NULL AS DOUBLE) AS swt_vs_cit_salary_diff,
            CAST(NULL AS DOUBLE) AS swt_vs_cit_salary_diff_abs,
            CAST(NULL AS DOUBLE) AS swt_vs_cit_salary_pct,
            'No CIT Record' COLLATE utf8mb4_general_ci AS gst_validation,
            'No SWT Record' COLLATE utf8mb4_general_ci AS swt_validation,
            0 AS cit_fraud_flag,
            0 AS gst_fraud_flag,
            COALESCE(s.swt_fraud_flag,0) AS swt_fraud_flag,
            COALESCE(s.swt_fraud_flag,0) AS flagged_in_tax_types,
            {user_id_expr} AS user_id
        FROM agg_swt s
        WHERE 1 = 1{swt_not_exists_year_clause}
          AND NOT EXISTS (
            SELECT 1 FROM agg_cit c
            WHERE c.tin = s.tin AND c.tax_period_year = s.tax_period_year
        )
    """


def _build_multitax_generated_column_sql(table_name):
    return f"""
        ALTER TABLE {table_name}
        ADD COLUMN multi_tax_issue VARCHAR(20) AS (
            CASE
                WHEN gst_validation IN ('Sales Mismatch','No GST Record')
                 AND swt_validation IN ('Salary Mismatch','No SWT Record') THEN 'Both'
                WHEN gst_validation IN ('Sales Mismatch','No GST Record') THEN 'GST'
                WHEN swt_validation IN ('Salary Mismatch','No SWT Record') THEN 'SWT'
                ELSE 'No Issue'
            END
        ) STORED
    """


def _build_multitax_index_sql(table_name):
    return (
        f"ALTER TABLE {table_name} "
        "ADD INDEX idx_tin_year (tin(20), tax_period_year), "
        "ADD INDEX idx_flags (flagged_in_tax_types), "
        "ADD INDEX idx_user_year_tin (user_id, tax_period_year, tin(20)), "
        "ADD INDEX idx_user_tin_year (user_id, tin(20), tax_period_year)"
    )


def _run_multitax_diagnostics(conn):
    stages = [
        ("stage_1", "SELECT c.tin FROM agg_cit c LIMIT 1"),
        ("stage_2", """
            SELECT c.tin, COALESCE(c.taxpayer_name, g.taxpayer_name, s.taxpayer_name) AS taxpayer_name
            FROM agg_cit c
            LEFT JOIN agg_gst g ON c.tin = g.tin AND c.tax_period_year = g.tax_period_year
            LEFT JOIN agg_swt s ON c.tin = s.tin AND c.tax_period_year = s.tax_period_year
            LIMIT 1
        """),
        ("stage_3", """
            SELECT
                COALESCE(c.tin, g.tin, s.tin) AS tin,
                COALESCE(c.taxpayer_name, g.taxpayer_name, s.taxpayer_name) AS taxpayer_name,
                g.taxpayer_type,
                COALESCE(c.tax_account_number, g.tax_account_number, s.tax_account_number) AS tax_account_number,
                COALESCE(c.assessment_number, g.assessment_number, s.assessment_number) AS assessment_number,
                COALESCE(c.tax_period_year, g.tax_period_year, s.tax_period_year) AS tax_period_year,
                c.sector_activity,
                c.enterprise_activity
            FROM agg_cit c
            LEFT JOIN agg_gst g ON c.tin = g.tin AND c.tax_period_year = g.tax_period_year
            LEFT JOIN agg_swt s ON c.tin = s.tin AND c.tax_period_year = s.tax_period_year
            LIMIT 1
        """),
        ("stage_4", """
            SELECT COALESCE(c.tin, g.tin, s.tin) AS tin, NULL AS user_id
            FROM agg_cit c
            LEFT JOIN agg_gst g ON c.tin = g.tin AND c.tax_period_year = g.tax_period_year
            LEFT JOIN agg_swt s ON c.tin = s.tin AND c.tax_period_year = s.tax_period_year
            UNION ALL
            SELECT g.tin, NULL
            FROM agg_gst g
            WHERE NOT EXISTS (
                SELECT 1 FROM agg_cit c WHERE c.tin = g.tin AND c.tax_period_year = g.tax_period_year
            )
            UNION ALL
            SELECT s.tin, NULL
            FROM agg_swt s
            WHERE NOT EXISTS (
                SELECT 1 FROM agg_cit c WHERE c.tin = s.tin AND c.tax_period_year = s.tax_period_year
            )
        """),
    ]

    for stage_name, select_sql in stages:
        diag_table = f"multitax_diag_{stage_name}"
        create_sql = f"CREATE TABLE {diag_table} AS {select_sql}"
        try:
            conn.execute(text(f"DROP TABLE IF EXISTS {diag_table}"))
            conn.execute(text(create_sql))
            logger.info(f"Diagnostic {stage_name} succeeded.")
        except Exception as exc:
            logger.exception(f"Diagnostic failed at {stage_name}: {exc}")
            logger.error(f"Diagnostic SQL ({stage_name}): {create_sql}")
            break
        finally:
            try:
                conn.execute(text(f"DROP TABLE IF EXISTS {diag_table}"))
            except Exception:
                logger.exception(f"Failed to drop diagnostic table {diag_table}")


def _integration_table_ready(engine) -> bool:
    """Return True if multi_tax_integration_results exists and has rows."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() "
                "AND table_name = 'multi_tax_integration_results'"
            ))
            if result.scalar() == 0:
                return False
            row_count = conn.execute(
                text("SELECT COUNT(*) FROM multi_tax_integration_results")
            ).scalar()
            return row_count > 0
    except Exception:
        return False


def _validate_integration_build(conn, table_name):
    table_exists = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = DATABASE() "
        "AND table_name = :table_name"
    ), {"table_name": table_name}).scalar()
    if table_exists == 0:
        raise RuntimeError(f"{table_name} was not created.")

    row_count = conn.execute(
        text(f"SELECT COUNT(*) FROM {table_name}")
    ).scalar()
    if not row_count or row_count <= 0:
        raise RuntimeError(f"{table_name} validation failed: row count must be greater than zero.")

    generated_column_exists = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = DATABASE() "
        "AND table_name = :table_name "
        "AND column_name = 'multi_tax_issue'"
    ), {"table_name": table_name}).scalar()
    if generated_column_exists == 0:
        raise RuntimeError(f"{table_name} validation failed: generated column multi_tax_issue is missing.")

    index_count = conn.execute(text(
        "SELECT COUNT(DISTINCT index_name) FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() "
        "AND table_name = :table_name "
        "AND index_name IN ('idx_tin_year', 'idx_flags', 'idx_user_year_tin', 'idx_user_tin_year')"
    ), {"table_name": table_name}).scalar()
    if index_count < 4:
        raise RuntimeError(f"{table_name} validation failed: required indexes are missing.")
# ─────────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────────

@multi_tax_bp.route('/api/multitax/results', methods=['GET'])
def get_multi_tax_results():
    """
    TIN+year combinations flagged as fraud in 2+ tax types.
    Params: min_flags (2|3), year, tin, limit
    """
    try:
        min_flags = int(request.args.get('min_flags', 2))
        year      = request.args.get('year',  None)
        tin       = request.args.get('tin',   None)
        limit     = int(request.args.get('limit', 500))

        if min_flags not in (2, 3):
            return jsonify({'error': 'min_flags must be 2 or 3'}), 400

        filters = ['flagged_in_tax_types >= :min_flags']
        params  = {'min_flags': min_flags, 'limit': limit}

        if year:
            filters.append('tax_period_year = :year');  params['year'] = int(year)
        if tin:
            filters.append('tin = :tin');               params['tin']  = str(tin)

        where = ' AND '.join(filters)
        sql = f"""
            SELECT
                tin, taxpayer_name, taxpayer_type,
                tax_account_number, assessment_number,
                tax_period_year, sector_activity, enterprise_activity,
                cit_gross_sales, gst_total_sales_income,
                cit_salaries_or_wages, swt_total_salary_wages_paid,
                gst_vs_cit_sales_diff_abs, gst_vs_cit_sales_pct,
                swt_vs_cit_salary_diff_abs, swt_vs_cit_salary_pct,
                gst_validation, swt_validation,
                cit_fraud_flag, gst_fraud_flag, swt_fraud_flag,
                flagged_in_tax_types
            FROM multi_tax_integration_results
            WHERE {where}
            ORDER BY flagged_in_tax_types DESC, tin, tax_period_year
            LIMIT :limit
        """
        engine = get_mysql_engine()
        if not _integration_table_ready(engine):
            engine.dispose()
            return jsonify({
                'count': 0,
                'filters': {'min_flags': min_flags, 'year': year, 'tin': tin},
                'results': [],
                'message': (
                    'Integration results are not available yet. '
                    'Run POST /api/multitax/refresh after all three pipelines '
                    '(GST, CIT, SWT) have completed successfully.'
                ),
            }), 200
        with engine.connect() as conn:
            df = pd.read_sql(text(sql), conn, params=params)
        engine.dispose()

        df = df.where(pd.notnull(df), None)
        return jsonify({
            'count':   len(df),
            'filters': {'min_flags': min_flags, 'year': year, 'tin': tin},
            'results': df.to_dict(orient='records'),
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@multi_tax_bp.route('/api/multitax/summary', methods=['GET'])
def get_multi_tax_summary():
    """Breakdown of TIN+year pairs flagged in 2 vs 3 tax types. Params: year"""
    try:
        year        = request.args.get('year', None)
        year_filter = 'AND tax_period_year = :year' if year else ''
        params      = {'year': int(year)} if year else {}

        sql = f"""
            SELECT flagged_in_tax_types, COUNT(*) AS tin_year_combinations
            FROM multi_tax_integration_results
            WHERE flagged_in_tax_types >= 2 {year_filter}
            GROUP BY flagged_in_tax_types
            ORDER BY flagged_in_tax_types DESC
        """
        engine = get_mysql_engine()
        if not _integration_table_ready(engine):
            engine.dispose()
            return jsonify({
                'year_filter': year,
                'breakdown': [],
                'message': (
                    'Integration results are not available yet. '
                    'Run POST /api/multitax/refresh after all three pipelines '
                    '(GST, CIT, SWT) have completed successfully.'
                ),
            }), 200
        with engine.connect() as conn:
            df = pd.read_sql(text(sql), conn, params=params)
        engine.dispose()

        return jsonify({'year_filter': year, 'breakdown': df.to_dict(orient='records')}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@multi_tax_bp.route('/api/multitax/refresh', methods=['POST'])
def manual_refresh():
    """Rebuild agg tables + run integration in the background.

    Returns 202 immediately and runs the heavy work in a daemon thread.
    Poll GET /api/multitax/refresh/status to check progress.
    """
    job_id = str(uuid.uuid4())
    current_user_id = get_authenticated_user_id()
    _set_refresh_status(
        job_id,
        status='running',
        stage='queued',
        message='[REFRESH] Started',
    )

    def _status_callback(**updates):
        _set_refresh_status(job_id, **updates)

    def _run():
        try:
            refresh_multi_tax_tables(
                current_user_id=current_user_id,
                status_callback=_status_callback,
            )
            _set_refresh_status(
                job_id,
                status='completed',
                stage='completed',
                message='[REFRESH] Status updated completed',
            )
        except BaseException as exc:
            _set_refresh_status(
                job_id,
                status='error',
                stage='failed',
                message='[REFRESH] Failed',
                detail=str(exc),
            )

    threading.Thread(target=_run, daemon=False).start()

    return jsonify({
        'status':  'accepted',
        'job_id':  job_id,
        'message': 'Multi-tax refresh started in the background. '
                   'Poll GET /api/multitax/refresh/status?job_id=<job_id> to check progress.',
    }), 202


@multi_tax_bp.route('/api/multitax/refresh/status', methods=['GET'])
def refresh_status():
    """Check the status of a background refresh job."""
    job_id = request.args.get('job_id')
    if not job_id:
        # Return all jobs if no id given
        return jsonify(list(_refresh_status.values())), 200
    info = _get_refresh_status(job_id)
    if not info:
        return jsonify({'error': 'Job ID not found'}), 404
    return jsonify(info), 200


@multi_tax_bp.route('/api/multitax/integrate', methods=['POST'])
def trigger_integration():
    """Run cross-validation without rebuilding agg tables — runs in background."""
    job_id = str(uuid.uuid4())
    current_user_id = get_authenticated_user_id()
    _set_refresh_status(
        job_id,
        status='running',
        stage='queued',
        message='[REFRESH] Integration started',
    )

    def _status_callback(**updates):
        _set_refresh_status(job_id, **updates)

    def _run():
        try:
            summary = run_multi_tax_integration(
                current_user_id=current_user_id,
                status_callback=_status_callback,
            )
            _set_refresh_status(
                job_id,
                status='completed',
                stage='completed',
                message='[REFRESH] Status updated completed',
                **summary,
            )
        except Exception as e:
            _set_refresh_status(
                job_id,
                status='error',
                stage='failed',
                message='[REFRESH] Failed',
                detail=str(e),
            )

    threading.Thread(target=_run, daemon=False).start()
    return jsonify({
        'status':  'accepted',
        'job_id':  job_id,
        'message': 'Integration started in background. '
                   'Poll GET /api/multitax/refresh/status?job_id=<job_id> to check progress.'
    }), 202


@multi_tax_bp.route('/api/multitax/integrate/results', methods=['GET'])
def get_integration_results():
    """
    Full integration results.
    Params: tin, year, issue (No Issue|GST|SWT|Both),
            gst_validation, swt_validation, limit
    """
    try:
        tin            = request.args.get('tin',            None)
        year           = request.args.get('year',           None)
        issue          = request.args.get('issue',          None)
        gst_validation = request.args.get('gst_validation', None)
        swt_validation = request.args.get('swt_validation', None)
        limit          = int(request.args.get('limit', 500))

        valid_issues = {'No Issue', 'GST', 'SWT', 'Both'}
        if issue and issue not in valid_issues:
            return jsonify({'error': f'issue must be one of {sorted(valid_issues)}'}), 400

        filters, params = [], {'limit': limit}
        if tin:            filters.append('tin = :tin');                  params['tin']   = str(tin)
        if year:           filters.append('tax_period_year = :year');     params['year']  = int(year)
        if issue:          filters.append('multi_tax_issue = :issue');    params['issue'] = issue
        if gst_validation: filters.append('gst_validation = :gst_v');    params['gst_v'] = gst_validation
        if swt_validation: filters.append('swt_validation = :swt_v');    params['swt_v'] = swt_validation

        where = ('WHERE ' + ' AND '.join(filters)) if filters else ''
        sql = f"""
            SELECT *
            FROM multi_tax_integration_results
            {where}
            ORDER BY multi_tax_issue, flagged_in_tax_types DESC, tin, tax_period_year
            LIMIT :limit
        """
        engine = get_mysql_engine()
        if not _integration_table_ready(engine):
            engine.dispose()
            return jsonify({
                'count': 0,
                'filters': {
                    'tin': tin, 'year': year, 'issue': issue,
                    'gst_validation': gst_validation,
                    'swt_validation': swt_validation,
                },
                'results': [],
                'message': (
                    'Integration results are not available yet. '
                    'Run POST /api/multitax/refresh after all three pipelines '
                    '(GST, CIT, SWT) have completed successfully.'
                ),
            }), 200
        with engine.connect() as conn:
            df = pd.read_sql(text(sql), conn, params=params)
        engine.dispose()

        df = df.where(pd.notnull(df), None)
        return jsonify({
            'count':   len(df),
            'filters': {
                'tin': tin, 'year': year, 'issue': issue,
                'gst_validation': gst_validation,
                'swt_validation': swt_validation,
            },
            'results': df.to_dict(orient='records'),
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
