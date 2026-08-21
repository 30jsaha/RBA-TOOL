"""
cit/cit_fraud_pipeline_with_timer.py

Compatibility wrapper for the CIT pipeline.

Some API routes import these module-level callables:
  - run_script_1
  - run_script_2
  - run_script_3
  - run_script_4
  - run_script_5

The underlying CIT logic lives in the individual ML developer scripts under `cit/`.
This module intentionally delegates to those scripts without duplicating business rules.
"""

from __future__ import annotations

import os

import pandas as pd
from cit.runtime_context import (
    get_artifact_path as get_runtime_artifact_path,
    get_output_dir as get_runtime_output_dir,
    get_runtime_value,
)


def get_output_dir() -> str:
    """Absolute path to the current CIT output directory (created if needed)."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return get_output_dir_from_context(script_dir)


def get_output_dir_from_context(script_dir: str) -> str:
    return get_runtime_output_dir(os.path.join(script_dir, "final_output"))


def _cit_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _cit_data_dir() -> str:
    data_dir = os.path.join(_cit_dir(), "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def _debug_exports():
    if os.environ.get("CIT_PIPELINE_DEBUG") == "1":
        print("Available CIT exports:", [n for n in dir() if not n.startswith("_")])


def _current_input_file() -> str | None:
    path = get_runtime_value("current_input_file", "")
    return os.path.abspath(path) if path else None


def _artifact_path(env_name: str, default_name: str) -> str:
    return get_runtime_artifact_path(env_name, default_name, os.path.join(_cit_dir(), "final_output"))


def _latest_uploaded_file() -> str | None:
    """
    Best-effort: pick the most recently modified file in `cit/data/` with a supported extension.
    """
    data_dir = _cit_data_dir()
    supported = (".csv", ".parquet")
    candidates = []
    try:
        for name in os.listdir(data_dir):
            if not name.lower().endswith(supported):
                continue
            path = os.path.join(data_dir, name)
            try:
                candidates.append((os.path.getmtime(path), path))
            except Exception:
                pass
    except Exception:
        return None

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def run_script_1():
    """
    Script 1 - Data preprocessing.
    Delegates to `cit/script_1_data_preprocessing.py` functions.
    Writes a run-scoped preprocessed artifact.
    """
    _debug_exports()
    from cit import script_1_data_preprocessing as s1

    input_path = _current_input_file() or _latest_uploaded_file()
    if not input_path:
        raise FileNotFoundError(f"No .csv/.parquet found in: {_cit_data_dir()}")

    if input_path.lower().endswith(".parquet"):
        df = pd.read_parquet(input_path)
    else:
        df = pd.read_csv(input_path)

    cit = s1.standardize_columns(df)
    is_valid, _message = s1.validate_required_columns(cit)
    if not is_valid:
        return None

    cit = s1.create_aggregated_columns(cit)
    cit = s1.reorganize_columns(cit)

    out_csv = _artifact_path("CIT_PREPROCESSED_FILE", "cit_preprocessed_data.csv")
    out_parquet = _artifact_path("CIT_PREPROCESSED_PARQUET_FILE", "cit_preprocessed_data.parquet")
    cit.to_csv(out_csv, index=False)
    try:
        cit.to_parquet(out_parquet, index=False)
    except Exception:
        pass

    return cit


def run_script_2():
    """
    Script 2 - Data validation.
    Delegates to `cit/script_2_data_validation.py`.

    Returns cleaned_df (to preserve existing pipeline expectations).
    """
    _debug_exports()
    from cit.script_2_data_validation import validate_and_clean_cit_data

    preprocessed_path = _artifact_path("CIT_PREPROCESSED_FILE", "cit_preprocessed_data.csv")
    if not os.path.exists(preprocessed_path):
        raise FileNotFoundError(f"Missing preprocessed file: {preprocessed_path}")

    df = pd.read_csv(preprocessed_path)

    original_dir = os.getcwd()
    os.chdir(get_output_dir())
    try:
        cleaned_df, _removed_df, _removal_details = validate_and_clean_cit_data(df)
    finally:
        os.chdir(original_dir)

    return cleaned_df


def run_script_3():
    """
    Script 3 - Rule engine.
    Delegates to `cit/script_4_rule_fraud.py`.
    """
    _debug_exports()
    from cit.script_4_rule_fraud import apply_cit_flag_rules

    return apply_cit_flag_rules()


def run_script_4():
    """
    Script 4 - XGBoost fraud prediction.
    Delegates to `cit/script_4_rule_fraud.py`.
    """
    _debug_exports()
    from cit.script_4_rule_fraud import process_and_predict_fraud_xgboost

    return process_and_predict_fraud_xgboost()


def run_script_5():
    """
    Script 5 - Fraud justification.
    Delegates to `cit/script_5_justification.py`.
    """
    _debug_exports()
    from cit.script_5_justification import process_cit_fraud_data

    process_cit_fraud_data()

    out_path = _artifact_path("CIT_JUSTIFICATION_FILE", "cit_fraud_with_justification.csv")
    if not os.path.exists(out_path):
        return pd.DataFrame()

    return pd.read_csv(out_path)
