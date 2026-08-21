import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
pd.options.display.max_columns = None
pd.options.display.float_format = "{:.2f}".format

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.environ.get("SWT_OUTPUT_DIR", SCRIPT_DIR)
os.makedirs(OUTPUT_DIR, exist_ok=True)
MODULE_NAME = "3_swt_feature_engineering.py"


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
    import traceback
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


def _get_year_distribution(df):
    for candidate in ["tax_period_year", "Tax Period Year", "TaxPeriodYear"]:
        if candidate in df.columns:
            return df[candidate].value_counts(dropna=False).sort_index().to_dict()
    return "tax_period_year column not found"


def load_validated_swt_input(input_file=None):
    resolved_input = _normalize_path(input_file or os.environ.get("SWT_CURRENT_INPUT_FILE", ""))
    expected_input = _normalize_path(os.environ.get("SWT_EXPECTED_VALIDATED_FILE", resolved_input))

    if not resolved_input:
        raise FileNotFoundError("SWT_CURRENT_INPUT_FILE was not provided to Step 3.")
    if not os.path.exists(resolved_input):
        raise FileNotFoundError(f"Validated SWT input not found: {resolved_input}")

    return _read_dataframe(resolved_input, "load_validated_swt_input", expected_input)


def add_fraud_detection_features(df):
    # Feature-1: No. SWT Employees > 0, but Total SW TAX Deducted = 0 - indicates non-compliance or error
    df["swt_employees_without_tax_deduction"] = (
        (df["employees_paid_swt"] > 0) & (df["total_swt_tax_deducted"] == 0)
    ).astype(int)

    # Feature-2: SWT Paid for SWT Deduction > Total Salary/Wages Paid - indicates potential overstatement of deductions.
    df["excess_swt_deduction_vs_salary"] = (
        df["sw_paid_for_swt_deduction"] > df["total_salary_wages_paid"]
    ).astype(int)

    # Feature-3: Total SWT Tax Deducted > SWT Paid for SWT Deduction - suggests incorrect tax calculation or possible fraud.
    df["tax_deduction_exceeds_swt_paid"] = (
        df["total_swt_tax_deducted"] > df["sw_paid_for_swt_deduction"]
    ).astype(int)

    # Feature-4: Employees on Payroll < Employees Paid SWT - indicates more SWT-paid employees than actual payroll.
    df["swt_employees_exceed_payroll"] = (
        df["employees_paid_swt"] > df["employees_on_payroll"]
    ).astype(int)

    # Feature-5: Total Salary/Wages Paid = 0 but Employees on Payroll > 0.
    df["employees_without_salary"] = (
        (df["total_salary_wages_paid"] == 0) & (df["employees_on_payroll"] > 0)
    ).astype(int)

    # Feature-6: Employees Paid SWT = 0 but SWT Paid for SWT Deduction > 0.
    df["swt_deduction_without_employees"] = (
        (df["employees_paid_swt"] == 0) & (df["sw_paid_for_swt_deduction"] > 0)
    ).astype(int)

    # Feature-7: SWT Paid for SWT Deduction = 0 but Total SWT Tax Deducted > 0.
    df["tax_deducted_without_swt_payment"] = (
        (df["sw_paid_for_swt_deduction"] == 0) & (df["total_swt_tax_deducted"] > 0)
    ).astype(int)

    # Feature-8: Employees on Payroll = 0 but Employees Paid SWT > 0.
    df["swt_paid_for_nonexistent_employees"] = (
        (df["employees_on_payroll"] == 0) & (df["employees_paid_swt"] > 0)
    ).astype(int)

    # Feature-9: Total Salary/Wages Paid > 0 but Employees on Payroll = 0.
    df["salary_paid_without_employees"] = (
        (df["total_salary_wages_paid"] > 0) & (df["employees_on_payroll"] == 0)
    ).astype(int)

    # Feature-10: Employees Paid SWT > Employees on Payroll by a large margin (e.g., >10%).
    df["excess_swt_paid_employees"] = (
        df["employees_paid_swt"] > df["employees_on_payroll"] * 1.1
    ).astype(int)

    # Feature-11: SWT Paid for SWT Deduction / Total Salary/Wages Paid > 1.
    df["excessive_swt_deduction"] = (
        (df["sw_paid_for_swt_deduction"] / df["total_salary_wages_paid"]) > 1
    ).astype(int)

    # Feature-12: Large fluctuations in Total Salary/Wages Paid without corresponding changes in Employees on Payroll.
    salary_pct = df["total_salary_wages_paid"].pct_change().abs()
    emp_pct = df["employees_on_payroll"].pct_change().abs()
    df["irregular_salary_fluctuation"] = ((salary_pct > 0.3) & (emp_pct < 0.1)).astype(int)

    df["sum_of_rules"] = (
        df["swt_employees_without_tax_deduction"]
        + df["excess_swt_deduction_vs_salary"]
        + df["tax_deduction_exceeds_swt_paid"]
        + df["employees_without_salary"]
        + df["swt_deduction_without_employees"]
        + df["tax_deducted_without_swt_payment"]
        + df["salary_paid_without_employees"]
        + df["excessive_swt_deduction"]
        + df["irregular_salary_fluctuation"]
    )

    df["is_fraud"] = np.where(df["sum_of_rules"] >= 1, 1, 0)

    rule_cols = [
        "swt_employees_without_tax_deduction",
        "excess_swt_deduction_vs_salary",
        "tax_deduction_exceeds_swt_paid",
        "employees_without_salary",
        "swt_deduction_without_employees",
        "tax_deducted_without_swt_payment",
        "salary_paid_without_employees",
        "excessive_swt_deduction",
        "irregular_salary_fluctuation",
    ]
    rule_labels = {
        "swt_employees_without_tax_deduction": "SWT employees but no tax deducted",
        "excess_swt_deduction_vs_salary": "SWT deduction exceeds salary paid",
        "tax_deduction_exceeds_swt_paid": "Tax deducted exceeds SWT paid",
        "employees_without_salary": "Employees on payroll but zero salary",
        "swt_deduction_without_employees": "SWT deduction with zero SWT employees",
        "tax_deducted_without_swt_payment": "Tax deducted without SWT payment",
        "salary_paid_without_employees": "Salary paid but no employees",
        "excessive_swt_deduction": "SWT deduction ratio > 1",
        "irregular_salary_fluctuation": "Irregular salary fluctuation",
    }

    def get_violated_rules(row):
        triggered = [rule_labels[col] for col in rule_cols if row[col] == 1]
        return "; ".join(triggered) if triggered else "None"

    df["rules_violated"] = df.apply(get_violated_rules, axis=1)

    df.drop(
        columns=[
            "swt_employees_without_tax_deduction",
            "excess_swt_deduction_vs_salary",
            "tax_deduction_exceeds_swt_paid",
            "swt_employees_exceed_payroll",
            "employees_without_salary",
            "swt_deduction_without_employees",
            "tax_deducted_without_swt_payment",
            "swt_paid_for_nonexistent_employees",
            "salary_paid_without_employees",
            "excess_swt_paid_employees",
            "excessive_swt_deduction",
            "irregular_salary_fluctuation",
            "sum_of_rules",
        ],
        inplace=True,
    )

    return df


swt_df = load_validated_swt_input()
swt_df1 = swt_df.copy()
swt_df_ML = add_fraud_detection_features(swt_df1)
swt_df_ML.to_parquet(
    os.path.join(OUTPUT_DIR, "swt_data_after_rule_checking.parquet"),
    compression="snappy",
    index=False,
    engine="pyarrow",
)
print("Success: Saved after Feature Engineering")
