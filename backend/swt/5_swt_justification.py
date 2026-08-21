import pandas as pd
import numpy as np
import joblib
import os
import sys
import traceback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.environ.get('SWT_OUTPUT_DIR', SCRIPT_DIR)
MODELS_DIR = os.environ.get('SWT_MODELS_DIR', os.path.join(SCRIPT_DIR, 'models'))
os.makedirs(OUTPUT_DIR, exist_ok=True)
MODULE_NAME = "5_swt_justification.py"

loaded_model = joblib.load(os.path.join(MODELS_DIR, 'xgboost_model.pkl'))

REQUIRED_COLS = [
    "total_salary_wages_paid", "employees_paid_swt",
    "sw_paid_for_swt_deduction", "total_swt_tax_deducted",
    "employees_on_payroll"
]

RULE_PLAIN_ENGLISH = {
    'SWT employees but no tax deducted':        'This taxpayer reported staff receiving SWT wages, but no tax was deducted and remitted.',
    'SWT deduction exceeds salary paid':         'The amount reported for SWT deductions (PGK) is higher than the total salary paid, which is not possible.',
    'Tax deducted exceeds SWT paid':             'The tax amount deducted is greater than the wages on which SWT applies.',
    'Employees on payroll but zero salary':      'Employees are listed on payroll but no salary has been recorded as paid.',
    'SWT deduction with zero SWT employees':     'SWT deductions have been reported even though no employees are listed as receiving SWT wages.',
    'Tax deducted without SWT payment':          'Tax has been deducted but there are no corresponding SWT wages recorded.',
    'Salary paid but no employees':              'Salary payments are recorded but there are no employees listed on payroll.',
    'SWT deduction ratio > 1':                   'The SWT deduction amount exceeds the total salary paid, which is mathematically inconsistent.',
}


def _normalize_path(path):
    return os.path.abspath(os.path.expanduser(str(path))) if path else ""


def _print_df_debug(function_name, file_path, df):
    print("======================================================")
    print(f"MODULE: {MODULE_NAME}")
    print(f"FUNCTION: {function_name}")
    print(f"FILE OPENED: {os.path.basename(file_path)}")
    print(f"ABSOLUTE PATH: {_normalize_path(file_path)}")
    print(f"FILE EXISTS: {os.path.exists(file_path)}")
    print(f"ROWS: {len(df)}")
    print(f"COLUMNS: {len(df.columns)}")
    print(f"tax_period_year distribution: {_get_year_distribution(df)}")
    print("======================================================")


def _fail_unexpected_file(expected_path, actual_path):
    print("ERROR")
    print("Unexpected file source")
    print(f"EXPECTED: {_normalize_path(expected_path)}")
    print(f"ACTUAL: {_normalize_path(actual_path)}")
    print("CALL STACK:")
    print("".join(traceback.format_stack()))
    raise RuntimeError(
        f"Unexpected file source. Expected {_normalize_path(expected_path)}, got {_normalize_path(actual_path)}"
    )


def _read_dataframe(file_path, function_name, expected_path=None):
    actual_path = _normalize_path(file_path)
    normalized_expected = _normalize_path(expected_path) if expected_path else ""
    if normalized_expected and actual_path != normalized_expected:
        _fail_unexpected_file(normalized_expected, actual_path)

    if actual_path.lower().endswith(".parquet"):
        df = pd.read_parquet(actual_path)
    else:
        df = pd.read_csv(actual_path)

    _print_df_debug(function_name, actual_path, df)
    return df


def _get_year_distribution(df: pd.DataFrame):
    for candidate in ["tax_period_year", "Tax Period Year", "TaxPeriodYear"]:
        if candidate in df.columns:
            return df[candidate].value_counts(dropna=False).sort_index().to_dict()
    return "tax_period_year column not found"


def _load_merge_taxpayer_names_func():
    """
    Load `merge_taxpayer_names(cleaned_df)` from 2_swt_validation.py without
    executing that module's top-level script behavior.
    """
    import ast as _ast

    validation_path = os.path.join(SCRIPT_DIR, "2_swt_validation.py")
    if not os.path.exists(validation_path):
        raise FileNotFoundError(f"Validation script not found: {validation_path}")

    with open(validation_path, "r", encoding="utf-8", errors="replace") as f:
        src = f.read()

    tree = _ast.parse(src, filename=validation_path)
    func_node = None
    for node in tree.body:
        if isinstance(node, _ast.FunctionDef) and node.name == "merge_taxpayer_names":
            func_node = node
            break
    if func_node is None:
        raise RuntimeError("Could not find `merge_taxpayer_names` in 2_swt_validation.py")

    mod = _ast.Module(body=[func_node], type_ignores=[])
    code = compile(mod, validation_path, "exec")
    ns = {"pd": pd, "np": np, "os": os}
    exec(code, ns, ns)
    return ns["merge_taxpayer_names"]


def _ensure_taxpayer_name(df: pd.DataFrame, validated_input_file: str = None) -> pd.DataFrame:
    """
    Ensure `taxpayer_name` is present for downstream output/DB persistence.
    Uses existing SWT merge_taxpayer_names() logic when needed.
    """
    if df is None or getattr(df, "empty", True):
        return df

    try:
        df.columns = df.columns.astype(str).str.strip()
    except Exception:
        pass

    if "taxpayer_name" in df.columns:
        return df

    for alt in ["taxpayername", "taxpayer", "TaxpayerName", "Taxpayer_Name", "Taxpayer Name", "NAME", "name"]:
        if alt in df.columns:
            out = df.copy()
            out["taxpayer_name"] = out[alt]
            return out

    # Try to map from the explicit validated pipeline input first.
    try:
        validated_path = _normalize_path(validated_input_file)
        if validated_path:
            expected_validated_path = _normalize_path(
                os.environ.get("SWT_EXPECTED_VALIDATED_FILE", validated_path)
            )
            vdf = _read_dataframe(validated_path, "_ensure_taxpayer_name", expected_validated_path)
            try:
                vdf.columns = vdf.columns.astype(str).str.strip()
            except Exception:
                pass
            if "tin" in vdf.columns and "taxpayer_name" in vdf.columns and "tin" in df.columns:
                tin_series = (
                    vdf["tin"]
                    .fillna("")
                    .astype(str)
                    .str.replace(r"\.0$", "", regex=True)
                    .str.strip()
                )
                name_series = vdf["taxpayer_name"]
                name_map = dict(zip(tin_series.tolist(), name_series.tolist()))

                out = df.copy()
                out["tin"] = (
                    out["tin"]
                    .fillna("")
                    .astype(str)
                    .str.replace(r"\.0$", "", regex=True)
                    .str.strip()
                )
                out["taxpayer_name"] = out["tin"].map(name_map)
                if os.environ.get("SWT_PIPELINE_DEBUG", "").strip() == "1":
                    try:
                        print("[SWT] taxpayer_name mapped from validated file:", os.path.basename(validated_path))
                        print("[SWT] taxpayer_name non-null:", int(out["taxpayer_name"].notna().sum()))
                    except Exception:
                        pass
                return out
    except Exception:
        pass

    try:
        merge_taxpayer_names = _load_merge_taxpayer_names_func()
        # Ensure project root is importable for DB-backed mapping.
        try:
            import sys as _sys
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if root_dir not in _sys.path:
                _sys.path.append(root_dir)
        except Exception:
            pass
        out = merge_taxpayer_names(df)
        if out is not None and "taxpayer_name" in getattr(out, "columns", []):
            return out
    except Exception:
        pass

    return df


# ── Vectorized rule engine (whole dataframe) ─────────────────────────────────
def apply_rules_vectorized(df):
    """
    Apply all 8 business rules vectorized across the full dataframe.
    Captures ALL violated rules per row (not just the last one).
    """
    df = df.copy()

    # Define all 8 masks — identical conditions to the rule definitions
    mask1 = (df['employees_paid_swt'] > 0) & (df['total_swt_tax_deducted'] == 0)
    mask2 = df['sw_paid_for_swt_deduction'] > df['total_salary_wages_paid']
    mask3 = df['total_swt_tax_deducted'] > df['sw_paid_for_swt_deduction']
    mask4 = (df['total_salary_wages_paid'] == 0) & (df['employees_on_payroll'] > 0)
    mask5 = (df['employees_paid_swt'] == 0) & (df['sw_paid_for_swt_deduction'] > 0)
    mask6 = (df['sw_paid_for_swt_deduction'] == 0) & (df['total_swt_tax_deducted'] > 0)
    mask7 = (df['total_salary_wages_paid'] > 0) & (df['employees_on_payroll'] == 0)
    mask8 = (df['total_salary_wages_paid'] > 0) & (
                df['sw_paid_for_swt_deduction'] / df['total_salary_wages_paid'] > 1)

    rule_map = [
        (mask1, 'SWT employees but no tax deducted'),
        (mask2, 'SWT deduction exceeds salary paid'),
        (mask3, 'Tax deducted exceeds SWT paid'),
        (mask4, 'Employees on payroll but zero salary'),
        (mask5, 'SWT deduction with zero SWT employees'),
        (mask6, 'Tax deducted without SWT payment'),
        (mask7, 'Salary paid but no employees'),
        (mask8, 'SWT deduction ratio > 1'),
    ]

    # Build per-row list of all violated rule labels
    violated_series = pd.Series([[] for _ in range(len(df))], index=df.index)
    for mask, label in rule_map:
        violated_series[mask] = violated_series[mask].apply(lambda lst: lst + [label])

    # Semicolon-join all violated labels per row
    df['rules_violated'] = violated_series.apply(
        lambda lst: '; '.join(lst) if lst else 'None'
    )
    df['is_fraud_rule'] = (df['rules_violated'] != 'None').astype(int)

    return df


# ── Row-level rule engine (single observation) ───────────────────────────────
def run_rules(obs: pd.Series) -> dict:
    """
    Apply the same 8 business rules to a single row.
    Mirrors apply_rules_vectorized exactly — all violated rules captured.
    """
    try:
        ep  = float(obs.get('employees_paid_swt', 0) or 0)
        tsd = float(obs.get('total_swt_tax_deducted', 0) or 0)
        swd = float(obs.get('sw_paid_for_swt_deduction', 0) or 0)
        tsp = float(obs.get('total_salary_wages_paid', 0) or 0)
        eop = float(obs.get('employees_on_payroll', 0) or 0)

        violated = []

        if ep > 0 and tsd == 0:         # mask1
            violated.append('SWT employees but no tax deducted')
        if swd > tsp:                   # mask2
            violated.append('SWT deduction exceeds salary paid')
        if tsd > swd:                   # mask3
            violated.append('Tax deducted exceeds SWT paid')
        if tsp == 0 and eop > 0:        # mask4
            violated.append('Employees on payroll but zero salary')
        if ep == 0 and swd > 0:         # mask5
            violated.append('SWT deduction with zero SWT employees')
        if swd == 0 and tsd > 0:        # mask6
            violated.append('Tax deducted without SWT payment')
        if tsp > 0 and eop == 0:        # mask7
            violated.append('Salary paid but no employees')
        if tsp > 0 and swd / tsp > 1:  # mask8
            violated.append('SWT deduction ratio > 1')

        return {
            'is_fraud_rule':  1 if violated else 0,
            'rules_violated': '; '.join(violated) if violated else 'None'
        }
    except Exception:
        return {'is_fraud_rule': 0, 'rules_violated': 'None'}


# ── Justification builder ────────────────────────────────────────────────────
def build_justification_vectorized(row) -> str:
    """
    Combines model probability + all violated business rules into one
    human-readable explanation string.

    Cases:
      Model=Fraud  & Rules fired  → probability sentence + all rule plain-English
      Model=Fraud  & No rules     → probability sentence only
      Model=Non-Fraud & Rules fired → rule plain-English only
      Model=Non-Fraud & No rules  → no irregularities
    """
    model_fraud = row['predicted_fraud'] == 'Fraud'
    rules_fired = row['rules_violated'] != 'None'

    parts = []

    # Model signal
    if model_fraud:
        prob_pct = int(row['fraud_probability'] * 100)
        parts.append(
            f"Our automated analysis has assessed this taxpayer as high-risk "
            f"with a {prob_pct}% likelihood of non-compliance or fraudulent reporting."
        )

    # Rule signals — expand each label into plain English
    if rules_fired:
        violated_labels = [r.strip() for r in row['rules_violated'].split(';')]
        plain = [RULE_PLAIN_ENGLISH.get(label, label) for label in violated_labels]
        parts.append(
            "The following inconsistencies were detected in the submitted data: "
            + " | ".join(plain)
        )

    if not parts:
        return "No irregularities were detected. The submission appears consistent with expected payroll patterns."

    return " ".join(parts)


# ── Main pipeline function ───────────────────────────────────────────────────
def create_fraud_justification_file(input_file=None, output_file=None, validated_input_file=None):
    if input_file is None:
        input_file = os.environ.get('SWT_CURRENT_INPUT_FILE')
    if output_file is None:
        output_file = os.path.join(OUTPUT_DIR, 'swt_fraud_justification')
    if validated_input_file is None:
        validated_input_file = os.environ.get('SWT_VALIDATED_INPUT_FILE', '')

    if not input_file:
        raise FileNotFoundError("SWT_CURRENT_INPUT_FILE was not provided to Step 5.")

    if not os.path.exists(input_file):
        print(f"ERROR: Input file '{input_file}' not found!")
        return None

    print("Loading data...")
    expected_step_input = _normalize_path(os.environ.get('SWT_EXPECTED_STEP_INPUT_FILE', input_file))
    df = _read_dataframe(input_file, "create_fraud_justification_file", expected_step_input)
    debug = os.environ.get("SWT_PIPELINE_DEBUG", "").strip() == "1"

    # Ensure taxpayer_name is present so the final justification output contains it.
    # This does not change fraud logic; it only enriches record identity fields.
    df = _ensure_taxpayer_name(df, validated_input_file=validated_input_file)

    # Step 1 — Business rules (vectorized, all rules captured per row)
    print("Applying rules (vectorized)...")
    df = apply_rules_vectorized(df)

    # Step 2 — ML model prediction (vectorized)
    print("Running ML predictions (vectorized)...")
    X = df[REQUIRED_COLS].fillna(0).astype(float)
    probabilities = loaded_model.predict_proba(X)[:, 1]
    df['fraud_probability'] = probabilities.round(4)
    df['predicted_fraud'] = np.where(probabilities > 0.2, 'Fraud', 'Non-Fraud')

    # Step 3 — Build explanation combining model + rules for every row
    print("Generating explanations...")
    df['explanation'] = df.apply(build_justification_vectorized, axis=1)

    # Step 4 — Save files
    print("Saving results...")
    out_parquet = output_file if output_file.endswith(".parquet") else f"{output_file}.parquet"
    out_csv     = out_parquet.replace(".parquet", ".csv")

    if df is None:
        raise ValueError("SWT justification dataframe is None")
    if len(df) == 0:
        raise ValueError("SWT justification dataframe has no rows")

    out_dir = os.path.dirname(out_parquet) or OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    dup_list = df.columns[df.columns.duplicated()].tolist()
    if debug:
        print("SWT justification columns:", df.columns.tolist(), file=sys.stderr, flush=True)
        print("Duplicate columns:", dup_list, file=sys.stderr, flush=True)
        print("Dtypes:", df.dtypes, file=sys.stderr, flush=True)
        print("Shape:", df.shape, file=sys.stderr, flush=True)
    if dup_list:
        raise ValueError(f"Duplicate SWT columns detected before CSV export: {dup_list}")

    # Detect/handle unserializable object columns (lists/dicts/sets/tuples/custom objects)
    # - In debug mode: fail fast with readable error.
    # - In normal mode: convert offending columns to string to allow pipeline completion.
    # Include pandas string dtype explicitly to avoid Pandas4Warning.
    obj_cols = df.select_dtypes(include=["object", "string"]).columns.tolist()
    offending = []  # (col, type_name)
    for col in obj_cols:
        s = df[col]
        non_null = s.dropna()
        if non_null.empty:
            continue
        for v in non_null.head(200).tolist():
            if isinstance(v, (list, dict, set, tuple)):
                offending.append((col, type(v).__name__))
                break
            if not isinstance(v, str) and type(v).__module__ not in ("builtins", "numpy", "pandas"):
                offending.append((col, type(v).__name__))
                break

    if offending:
        if debug:
            raise ValueError(
                "Unserializable values detected before CSV export: "
                + ", ".join([f"{c}={t}" for c, t in offending])
            )
        for col, _t in offending:
            df[col] = df[col].astype(str)

    df.to_parquet(out_parquet, index=False)
    try:
        df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    except BaseException as e:
        # Keep stderr short so the orchestrator (which logs only first 10 lines)
        # shows the real root cause.
        print(
            f"[SWT_JUSTIFICATION] CSV export failed: {type(e).__name__}: {e}",
            file=sys.stderr,
            flush=True,
        )
        from datetime import datetime

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback_csv = out_csv.replace(".csv", f"_{stamp}.csv")
        try:
            df_retry = df.copy()
            for col in df_retry.select_dtypes(include=["object", "string"]).columns.tolist():
                df_retry[col] = df_retry[col].astype(str)
            df_retry.to_csv(fallback_csv, index=False, encoding="utf-8-sig")
            out_csv = fallback_csv
        except BaseException as e2:
            print(
                f"[SWT_JUSTIFICATION] Fallback CSV export failed: {type(e2).__name__}: {e2}",
                file=sys.stderr,
                flush=True,
            )
            # Continue without CSV so pipeline can complete (parquet is already written).
            out_csv = ""
    print(f"Saved parquet: {out_parquet}")
    if out_csv:
        print(f"Saved CSV:     {out_csv}")
    else:
        print("Saved CSV:     (skipped due to export failure)")

    # Step 5 — Write to MySQL unless the caller wants the insert deferred.
    db_saved = False
    if os.environ.get("SWT_SKIP_DB_SAVE", "").strip() == "1":
        print("Deferred MySQL insert for background chunked DB save")
    else:
        try:
            import sys as _sys
            _sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from swt.swt_upload_hook import save_swt_justification_to_db
            from config.db_config import get_mysql_engine
            engine = get_mysql_engine()
            save_swt_justification_to_db(df, engine)
            engine.dispose()
            db_saved = True
            print("Saved justification to MySQL via save_swt_justification_to_db()")
        except Exception as e:
            print(f"  Warning: DB write failed: {e}")

    print("Success: Justification done (optimized)")
    return df


if __name__ == "__main__":
    create_fraud_justification_file()
