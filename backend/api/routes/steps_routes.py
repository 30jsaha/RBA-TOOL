# ══════════════════════════════════════════════════════════════
#  api/routes/steps_routes.py
#  GET  /api/{tax}/steps          — static step definitions
#  GET  /api/{tax}/progress/<id>  — live per-step progress from DB
# ══════════════════════════════════════════════════════════════

import os
import sys
from flask import Blueprint, jsonify, request

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.db_config import get_mysql_engine

steps_bp = Blueprint('steps', __name__)

# ── Static step definitions (shown in the UI stepper BEFORE run starts) ──────

PIPELINE_STEPS = {
    'gst': [
        {
            'step_number': 1,
            'step_name':   'Column Standardization',
            'description': 'Maps raw column headers to standard names using the GST column standardizer',
            'substeps':    ['Load input file', 'Apply column mapping', 'Save standardized output'],
        },
        {
            'step_number': 2,
            'step_name':   'Data Validation & Cleaning',
            'description': 'Validates TINs, merges taxpayer names from registration data, removes invalid records',
            'substeps':    ['Merge taxpayer names', 'Validate TIN numbers', 'Remove invalid records', 'Save cleaned data'],
        },
        {
            'step_number': 3,
            'step_name':   'Rule Checking and Model Prediction',
            'description': 'Applies 11 GST fraud-detection business rules and runs the model in parallel',
            'substeps':    [
                'Apply rule: Deduct input credits violation',
                'Apply rule: Invalid GST refundable',
                'Apply rule: Fraud output debits / no tax',
                'Apply rule: Misreported zero-rated sales',
                'Apply rule: Overstated zero-rated sales',
                'Apply rule: Non-reported taxable sales',
                'Apply rule: Incomplete GST returns',
                'Apply rule: Non-filing GST',
                'Apply rule: Sales drop > 50%',
                'Apply rule: Multiple refund claims (6 months)',
                'Run XGBoost fraud probability model',
                'Merge rule flags with model predictions',
            ],
        },
        {
            'step_number': 4,
            'step_name':   'Fraud Justification Generation',
            'description': 'Creates human-readable justifications for each flagged record and saves to database',
            'substeps':    ['Load prediction results', 'Generate justifications', 'Save to MySQL'],
        },
    ],

    'cit': [
        {
            'step_number': 1,
            'step_name':   'Data Preprocessing',
            'description': 'Loads raw CIT data, standardizes column names, validates required columns, creates aggregated fields',
            'substeps':    [
                'Load and preprocess data',
                'Standardize column names',
                'Validate required columns (28 fields)',
                'Create aggregated columns',
                'Enrich taxpayer names',
                'Reorganize columns',
                'Save output',
            ],
        },
        {
            'step_number': 2,
            'step_name':   'Data Validation',
            'description': 'Validates TINs, assessment numbers, tax account numbers, gross sales figures and rental expenses',
            'substeps':    [
                'Validate TIN numbers (9-digit, non-null, non-sequential)',
                'Validate assessment numbers (numeric, non-duplicate)',
                'Validate tax account numbers (numeric)',
                'Validate gross sales data (non-negative)',
                'Check rental expenses',
            ],
        },
        {
            'step_number': 3,
            'step_name':   'Rule Checking and Model Prediction',
            'description': 'Applies 21 CIT business rules to flag suspicious patterns, then runs XGBoost fraud prediction',
            'substeps':    [
                'Apply 21 CIT business rules',
                'Calculate sum_of_rules score',
                'Run XGBoost fraud prediction',
                'Scale features',
                'Generate fraud probability scores',
            ],
        },
        {
            'step_number': 4,
            'step_name':   'Fraud Justification',
            'description': 'Generates per-record justifications based on rule violations and covariate analysis',
            'substeps':    ['Load prediction results', 'Analyse covariate violations', 'Generate justifications', 'Save to MySQL'],
        },
    ],

    'swt': [
        {
            'step_number': 1,
            'step_name':   'Data Preparation & Standardization',
            'description': 'Standardizes SWT column names and formats data for downstream processing',
            'substeps':    ['Load input file', 'Map column headers', 'Standardize data types', 'Save swt_standardized.parquet'],
        },
        {
            'step_number': 2,
            'step_name':   'Data Validation & Cleaning',
            'description': 'Validates TINs against the registration file, removes invalid records, maps taxpayer names',
            'substeps':    [
                'Load TIN registration data',
                'Validate TIN numbers',
                'Remove invalid records',
                'Map taxpayer names',
                'Save cleaned data',
            ],
        },
        {
            'step_number': 3,
            'step_name':   'Rule Checking and Model Prediction',
            'description': 'Engineers fraud-detection features and applies SWT-specific business rules',
            'substeps':    ['Engineer features', 'Apply business rule checks', 'Save rule-checked data'],
        },
        {
            'step_number': 4,
            'step_name':   'Fraud Justification Generation',
            'description': 'Runs XGBoost model, generates human-readable justifications, and saves to database',
            'substeps':    ['Run XGBoost prediction', 'Generate justifications', 'Save to MySQL'],
        },
    ],
}


# ── GET /api/<tax>/steps — static step list ───────────────────────────────────

@steps_bp.route('/api/<tax>/steps', methods=['GET'])
def get_steps(tax):
    tax = tax.lower()
    if tax not in PIPELINE_STEPS:
        return jsonify({'error': f'Unknown pipeline: {tax}. Use gst, cit, or swt'}), 404

    return jsonify({
        'pipeline':    tax.upper(),
        'total_steps': len(PIPELINE_STEPS[tax]),
        'steps':       PIPELINE_STEPS[tax],
    }), 200


# ── GET /api/<tax>/progress/<run_id> — live step progress from DB ─────────────

@steps_bp.route('/api/<tax>/progress/<run_id>', methods=['GET'])
def get_progress(tax, run_id):
    """
    Returns live per-step progress for a running pipeline run.
    Reads from pipeline_log table populated by log_step() in pipeline_logger.py.
    Also merges with the static step definitions so the frontend always has
    the full step list even before those steps have started.
    """
    tax = tax.lower()
    if tax not in PIPELINE_STEPS:
        return jsonify({'error': f'Unknown pipeline: {tax}. Use gst, cit, or swt'}), 404

    try:
        import pandas as pd
        engine = get_mysql_engine()

        with engine.connect() as conn:
            df = pd.read_sql(
                """
                SELECT step_number, step_name, status, elapsed_sec,
                       records_in, records_out, message, error_detail, logged_at
                FROM pipeline_log
                WHERE run_id   = %(run_id)s
                  AND tax_type = %(tax_type)s
                  AND step_number BETWEEN 1 AND 10
                ORDER BY step_number ASC, logged_at DESC
                """,
                conn,
                params={'run_id': run_id, 'tax_type': tax.upper()},
            )
        engine.dispose()

        # Keep the latest log entry per step number
        if not df.empty:
            df = df.drop_duplicates(subset=['step_number'], keep='first')

        # Build response: merge static definitions with live DB data
        logged_by_num = {}
        if not df.empty:
            for _, row in df.iterrows():
                logged_by_num[int(row['step_number'])] = {
                    'status':      row['status'],
                    'elapsed_sec': row['elapsed_sec'],
                    'records_in':  row['records_in'],
                    'records_out': row['records_out'],
                    'message':     row['message'],
                    'error':       row['error_detail'] if row['status'] == 'failed' else None,
                    'logged_at':   str(row['logged_at']),
                }

        steps_with_status = []
        completed = 0
        current_step = None

        for step_def in PIPELINE_STEPS[tax]:
            n = step_def['step_number']
            live = logged_by_num.get(n, {})
            status = live.get('status', 'pending')

            if status == 'completed':
                completed += 1
            elif status in ('started', 'running'):
                current_step = n

            steps_with_status.append({
                **step_def,
                'status':      status,
                'elapsed_sec': live.get('elapsed_sec'),
                'records_in':  live.get('records_in'),
                'records_out': live.get('records_out'),
                'message':     live.get('message'),
                'error':       live.get('error'),
                'logged_at':   live.get('logged_at'),
            })

        total = len(PIPELINE_STEPS[tax])
        overall_pct = round((completed / total) * 100) if total else 0

        return jsonify({
            'pipeline':      tax.upper(),
            'run_id':        run_id,
            'total_steps':   total,
            'completed':     completed,
            'current_step':  current_step,
            'progress_pct':  overall_pct,
            'steps':         steps_with_status,
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
