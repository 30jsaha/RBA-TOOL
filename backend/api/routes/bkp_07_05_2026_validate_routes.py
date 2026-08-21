# ══════════════════════════════════════════════════════════════
#  api/routes/validate_routes.py
#
#  POST /api/gst/validate
#  POST /api/cit/validate
#  POST /api/swt/validate
#
#  Pre-flight file validation — runs BEFORE the full pipeline.
#  Accepts an uploaded file, checks column presence and basic
#  data quality, returns pass/fail + issue list instantly.
#  Does NOT write to DB, does NOT run the pipeline.
#
#  Column matching is FUZZY — uploaded files don't need to use
#  the exact canonical names; close matches are accepted and
#  reported as informational mappings in the response.
# ══════════════════════════════════════════════════════════════

import io
import re
from difflib import SequenceMatcher

import pandas as pd
from flask import Blueprint, request, jsonify

validate_bp = Blueprint('validate', __name__)


# ─────────────────────────────────────────────────────────────
#  Shared helpers
# ─────────────────────────────────────────────────────────────

def _load_uploaded_file(file_storage):
    """Read a werkzeug FileStorage into a DataFrame."""
    filename = file_storage.filename.lower()
    data = file_storage.read()
    if filename.endswith('.parquet'):
        return pd.read_parquet(io.BytesIO(data))
    elif filename.endswith('.csv'):
        return pd.read_csv(io.BytesIO(data))
    else:
        raise ValueError('Only .csv or .parquet files are accepted')


def _normalise_cols(df):
    """Return a lowercase-stripped set of column names."""
    return {c.strip().lower() for c in df.columns}


def _add(issues, issue_type, detail, count=None):
    entry = {'type': issue_type, 'detail': detail}
    if count is not None:
        entry['count'] = int(count)
    issues.append(entry)


# ─────────────────────────────────────────────────────────────
#  Fuzzy column matching
# ─────────────────────────────────────────────────────────────

# Minimum similarity score (0–1) to accept a fuzzy match.
# 0.70 catches abbreviations and minor typos without false positives.
FUZZY_THRESHOLD = 0.70


def _tokenise(name: str) -> set:
    """
    Split a column name into a bag of lowercase tokens.
    'total_gross_salary' → {'total', 'gross', 'salary'}
    'TotalGrossSalary'   → {'total', 'gross', 'salary'}
    """
    # Insert underscore before uppercase letters (CamelCase → snake_case)
    name = re.sub(r'(?<=[a-z])(?=[A-Z])', '_', name)
    # Replace any non-alphanumeric run with a single space
    name = re.sub(r'[^a-z0-9]+', ' ', name.lower())
    return set(name.split())


def _similarity(canonical: str, actual: str) -> float:
    """
    Combined similarity: sequence ratio + Jaccard token overlap.
    Returns a value in [0, 1].
    """
    seq_score = SequenceMatcher(None, canonical, actual).ratio()
    t_can = _tokenise(canonical)
    t_act = _tokenise(actual)
    if t_can and t_act:
        union = t_can | t_act
        jaccard = len(t_can & t_act) / len(union)
    else:
        jaccard = 0.0
    # Weight token overlap slightly higher — catches reordered words
    return 0.4 * seq_score + 0.6 * jaccard


def _fuzzy_map_columns(required_cols: list, df_cols: list, threshold: float = FUZZY_THRESHOLD):
    """
    Match each required canonical column name to the best actual column.

    Returns
    -------
    mapped   : dict  {canonical_name: actual_col_name}   — successful matches
    missing  : list  [canonical_name]                    — no match found
    mappings : list  of info dicts for the response      — all fuzzy remaps
    """
    actual_normalised = {c.strip().lower(): c for c in df_cols}  # norm → original
    used = set()        # avoid mapping two canonical cols to the same actual col
    mapped = {}
    missing = []
    mappings = []       # informational: what was remapped

    for canon in required_cols:
        canon_norm = canon.strip().lower()

        # 1. Exact match (case-insensitive)
        if canon_norm in actual_normalised:
            actual = actual_normalised[canon_norm]
            mapped[canon_norm] = actual
            used.add(actual)
            continue

        # 2. Fuzzy match
        best_score = 0.0
        best_actual = None
        for norm, original in actual_normalised.items():
            if original in used:
                continue
            score = _similarity(canon_norm, norm)
            if score > best_score:
                best_score = score
                best_actual = original

        if best_score >= threshold and best_actual is not None:
            mapped[canon_norm] = best_actual
            used.add(best_actual)
            if best_actual.strip().lower() != canon_norm:
                mappings.append({
                    'type': 'column_remapped',
                    'canonical': canon,
                    'found_as': best_actual,
                    'score': round(best_score, 3),
                    'detail': (
                        f'Column "{best_actual}" was matched to '
                        f'expected column "{canon}" '
                        f'(similarity {best_score:.0%})'
                    ),
                })
        else:
            missing.append(canon_norm)

    return mapped, missing, mappings


def _remap_df(df: pd.DataFrame, mapped: dict) -> pd.DataFrame:
    """
    Return a copy of df with columns renamed to their canonical names.
    Only the columns present in `mapped` are renamed; others are untouched.
    """
    rename = {v: k for k, v in mapped.items()}   # actual → canonical
    return df.rename(columns=rename)


# ─────────────────────────────────────────────────────────────
#  CIT Validation
# ─────────────────────────────────────────────────────────────

CIT_REQUIRED_COLUMNS = [
    'gross_sales_cash_or_credit', 'total_gross_income', 'cost_of_goods_sold',
    'property_or_equipment', 'leasehold_improvements', 'management_fees_foreign',
    'total_operating_expenses', 'royalties_foreign', 'advertising_and_promotion',
    'bad_debts_written_off', 'accounts_receivable_trade', 'consultancy_fees',
    'legal_expenses', 'repairs_and_maintenance', 'travel_and_accommodation',
    'other_gross_income', 'total_current_assets', 'prior_year_losses_utilised',
    'interest_expense_foreign', 'interest_income', 'management_fees_png',
    'royalties_png', 'dividend_income', 'interest_expense_png', 'loans_from_directors',
    'other_loans', 'total_non_deductible_items', 'total_deductible_items_ex', 'gross_tax',
]


def _validate_cit(df):
    issues = []

    mapped, missing, mappings = _fuzzy_map_columns(CIT_REQUIRED_COLUMNS, list(df.columns))
    issues.extend(mappings)

    for col in missing:
        _add(issues, 'missing_column', col)

    if missing:          # column errors are fatal — skip row checks
        return issues

    df = _remap_df(df, mapped)
    df.columns = [c.strip().lower() for c in df.columns]

    # 2 — TIN validation
    if 'tin' in df.columns:
        tin = pd.to_numeric(df['tin'], errors='coerce')
        null_count = tin.isna().sum()
        if null_count:
            _add(issues, 'tin_null', 'TIN is null or non-numeric', null_count)

        tin_str = tin.dropna().astype('Int64').astype(str)

        wrong_len = (tin_str.str.len() != 9).sum()
        if wrong_len:
            _add(issues, 'tin_wrong_length', 'TIN must be exactly 9 digits', wrong_len)

        starts_zero = tin_str.str.startswith('0').sum()
        if starts_zero:
            _add(issues, 'tin_starts_with_zero', 'TIN starts with 0', starts_zero)

        all_same = tin_str.apply(lambda s: len(set(s)) == 1).sum()
        if all_same:
            _add(issues, 'tin_all_same_digits', 'TIN contains all identical digits', all_same)

        def _is_sequential(s):
            if len(s) != 9:
                return False
            digits = [int(d) for d in s]
            diffs  = [digits[i + 1] - digits[i] for i in range(len(digits) - 1)]
            return all(d == diffs[0] for d in diffs) and abs(diffs[0]) == 1

        sequential = tin_str.apply(_is_sequential).sum()
        if sequential:
            _add(issues, 'tin_sequential', 'TIN is a sequential number pattern', sequential)

    # 3 — Assessment number
    if 'assessment_no' in df.columns:
        a_str = df['assessment_no'].astype(str)
        non_num = (~a_str.str.match(r'^\d+$')).sum()
        if non_num:
            _add(issues, 'assessment_non_numeric',
                 'assessment_no contains non-numeric values', non_num)

        dupes = df.duplicated(subset=['assessment_no'], keep=False).sum()
        if dupes:
            _add(issues, 'assessment_duplicate',
                 'Duplicate assessment_no values found', dupes)

    # 4 — Tax account number
    if 'tax_account_no' in df.columns:
        non_num = (~df['tax_account_no'].astype(str).str.match(r'^\d+$')).sum()
        if non_num:
            _add(issues, 'tax_account_non_numeric',
                 'tax_account_no contains non-numeric values', non_num)

    # 5 — Gross sales
    if 'gross_sales_cash_or_credit' in df.columns:
        neg = (pd.to_numeric(df['gross_sales_cash_or_credit'],
                              errors='coerce').fillna(0) < 0).sum()
        if neg:
            _add(issues, 'gross_sales_negative',
                 'gross_sales_cash_or_credit contains negative values', neg)

    return issues


# ─────────────────────────────────────────────────────────────
#  GST Validation
# ─────────────────────────────────────────────────────────────

GST_EXPECTED_COLUMNS = [
    'tin', 'tax_period_year', 'tax_period_month',
    'output_tax_payable', 'input_tax_credits', 'net_gst_payable',
    'total_sales', 'zero_rated_sales', 'taxable_sales',
]

GST_CRITICAL_COLUMNS = ['tin']


def _validate_gst(df):
    issues = []

    # Map ALL expected columns (critical + non-critical) via fuzzy matching
    mapped, missing, mappings = _fuzzy_map_columns(GST_EXPECTED_COLUMNS, list(df.columns))
    issues.extend(mappings)

    # Critical check: hard-fail if tin is completely absent
    critical_missing = [c for c in GST_CRITICAL_COLUMNS if c not in mapped]
    for col in critical_missing:
        _add(issues, 'missing_critical_column',
             f'"{col}" is required and could not be matched to any column. '
             f'Available columns: {list(df.columns)[:10]}')

    # Non-critical missing: warn
    non_critical_missing = [c for c in missing if c not in GST_CRITICAL_COLUMNS]
    for col in non_critical_missing:
        _add(issues, 'missing_expected_column',
             f'"{col}" is expected but not found — '
             f'column standardizer may map it automatically')

    if critical_missing:
        return issues

    df = _remap_df(df, mapped)
    df.columns = [c.strip().lower() for c in df.columns]

    # 3 — TIN checks
    tin_raw = df['tin'].astype(str).str.strip()
    null_count = tin_raw.isin(['', 'nan', 'none', 'null']).sum()
    if null_count:
        _add(issues, 'tin_null', 'TIN is empty or null', null_count)

    tin_digits = tin_raw[~tin_raw.isin(['', 'nan', 'none', 'null'])]
    wrong_len = (tin_digits.str.replace(r'\D', '', regex=True).str.len() != 9).sum()
    if wrong_len:
        _add(issues, 'tin_wrong_length', 'TIN does not have exactly 9 digits', wrong_len)

    # 4 — Numeric range checks
    for col in ['output_tax_payable', 'input_tax_credits', 'net_gst_payable',
                'total_sales', 'taxable_sales']:
        if col in df.columns:
            neg = (pd.to_numeric(df[col], errors='coerce').fillna(0) < 0).sum()
            if neg:
                _add(issues, 'negative_value', f'"{col}" contains negative values', neg)

    # 5 — Duplicate TIN + period
    if 'tax_period_year' in df.columns and 'tax_period_month' in df.columns:
        dupes = df.duplicated(
            subset=['tin', 'tax_period_year', 'tax_period_month'], keep=False
        ).sum()
        if dupes:
            _add(issues, 'duplicate_tin_period',
                 'Duplicate records found for the same TIN + year + month', dupes)

    return issues


# ─────────────────────────────────────────────────────────────
#  SWT Validation
# ─────────────────────────────────────────────────────────────

SWT_EXPECTED_COLUMNS = [
    'tin', 'tax_period_year', 'employer_name',
    'total_swt_withheld', 'total_gross_salary',
    'number_of_employees',
]

SWT_CRITICAL_COLUMNS = ['tin']


def _validate_swt(df):
    issues = []

    mapped, missing, mappings = _fuzzy_map_columns(SWT_EXPECTED_COLUMNS, list(df.columns))
    issues.extend(mappings)

    critical_missing = [c for c in SWT_CRITICAL_COLUMNS if c not in mapped]
    for col in critical_missing:
        _add(issues, 'missing_critical_column',
             f'"{col}" is required but could not be matched. '
             f'Available columns: {list(df.columns)[:10]}')

    non_critical_missing = [c for c in missing if c not in SWT_CRITICAL_COLUMNS]
    for col in non_critical_missing:
        _add(issues, 'missing_expected_column',
             f'"{col}" is expected but not found — '
             f'column standardizer may map it automatically')

    if critical_missing:
        return issues

    df = _remap_df(df, mapped)
    df.columns = [c.strip().lower() for c in df.columns]

    # 3 — TIN checks
    tin_raw = df['tin'].astype(str).str.strip()
    null_count = tin_raw.isin(['', 'nan', 'none', 'null']).sum()
    if null_count:
        _add(issues, 'tin_null', 'TIN is empty or null', null_count)

    tin_digits = tin_raw[~tin_raw.isin(['', 'nan', 'none', 'null'])]
    cleaned    = tin_digits.str.replace(r'\D', '', regex=True)

    wrong_len = (cleaned.str.len() != 9).sum()
    if wrong_len:
        _add(issues, 'tin_wrong_length', 'TIN does not have exactly 9 digits', wrong_len)

    starts_zero = cleaned.str.startswith('0').sum()
    if starts_zero:
        _add(issues, 'tin_starts_with_zero', 'TIN starts with 0', starts_zero)

    all_same = cleaned.apply(lambda s: len(s) > 0 and len(set(s)) == 1).sum()
    if all_same:
        _add(issues, 'tin_all_same_digits', 'TIN contains all identical digits', all_same)

    # 4 — SWT amount checks
    if 'total_swt_withheld' in df.columns:
        neg = (pd.to_numeric(df['total_swt_withheld'], errors='coerce').fillna(0) < 0).sum()
        if neg:
            _add(issues, 'negative_value',
                 '"total_swt_withheld" contains negative values', neg)

    if 'total_gross_salary' in df.columns:
        neg = (pd.to_numeric(df['total_gross_salary'], errors='coerce').fillna(0) < 0).sum()
        if neg:
            _add(issues, 'negative_value',
                 '"total_gross_salary" contains negative values', neg)

    # 5 — SWT rate sanity: withheld should not exceed gross salary
    if 'total_swt_withheld' in df.columns and 'total_gross_salary' in df.columns:
        withheld = pd.to_numeric(df['total_swt_withheld'], errors='coerce').fillna(0)
        salary   = pd.to_numeric(df['total_gross_salary'],   errors='coerce').fillna(0)
        exceeds  = ((withheld > salary) & (salary > 0)).sum()
        if exceeds:
            _add(issues, 'swt_exceeds_salary',
                 'total_swt_withheld exceeds total_gross_salary (rate > 100%)', exceeds)

    # 6 — Duplicate TIN + year
    if 'tax_period_year' in df.columns:
        dupes = df.duplicated(subset=['tin', 'tax_period_year'], keep=False).sum()
        if dupes:
            _add(issues, 'duplicate_tin_year',
                 'Duplicate records found for the same TIN + year', dupes)

    return issues


# ─────────────────────────────────────────────────────────────
#  Shared route logic
# ─────────────────────────────────────────────────────────────

VALIDATORS = {
    'gst': _validate_gst,
    'cit': _validate_cit,
    'swt': _validate_swt,
}


def _run_validation(tax):
    # ── Check 1: no file at all ──────────────────────────────
    if 'file' not in request.files or request.files['file'].filename == '':
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']

    # ── Check 2: wrong file type ─────────────────────────────
    fname = file.filename.lower()
    if not (fname.endswith('.csv') or fname.endswith('.parquet')):
        return jsonify({'error': 'Invalid file type. Only .csv or .parquet accepted'}), 400

    try:
        df = _load_uploaded_file(file)
    except Exception as e:
        return jsonify({'error': f'Could not read file: {str(e)}'}), 400

    row_count    = len(df)
    column_count = len(df.columns)

    if row_count == 0:
        return jsonify({
            'valid':         False,
            'row_count':     0,
            'column_count':  column_count,
            'columns_found': list(df.columns),
            'issues':        [{'type': 'empty_file',
                               'detail': 'Uploaded file contains no data rows'}],
        }), 200

    issues = VALIDATORS[tax](df)

    # Severity classification
    # missing_column / missing_critical_column → error (blocks pipeline)
    # missing_expected_column → warning (pipeline may still work)
    # column_remapped → info (fuzzy match happened, just FYI)
    # everything else → warning
    INFO_TYPES  = {'column_remapped'}
    ERROR_TYPES = {'missing_column', 'missing_critical_column'}
    WARN_TYPES  = {'missing_expected_column'}

    errors   = [i for i in issues if i['type'] in ERROR_TYPES]
    warnings = [i for i in issues if i['type'] in WARN_TYPES
                or (i['type'] not in ERROR_TYPES and i['type'] not in INFO_TYPES
                    and i not in errors)]
    infos    = [i for i in issues if i['type'] in INFO_TYPES]

    return jsonify({
        'valid':          len(errors) == 0,
        'pipeline':       tax.upper(),
        'filename':       file.filename,
        'row_count':      row_count,
        'column_count':   column_count,
        'columns_found':  list(df.columns),
        'error_count':    len(errors),
        'warning_count':  len(warnings),
        'info_count':     len(infos),
        'issues':         issues,       
        'errors':         errors,
        'warnings':       warnings,
        'infos':          infos,        
        'summary': (
            'File passed all validation checks — ready to process.'
            if len(errors) == 0 and len(warnings) == 0
            else f'{len(errors)} error(s) and {len(warnings)} warning(s) found.'
        ),
    }), 200


# ─────────────────────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────────────────────

@validate_bp.route('/api/gst/validate', methods=['POST'])
def validate_gst():
    return _run_validation('gst')


@validate_bp.route('/api/cit/validate', methods=['POST'])
def validate_cit():
    return _run_validation('cit')


@validate_bp.route('/api/swt/validate', methods=['POST'])
def validate_swt():
    return _run_validation('swt')