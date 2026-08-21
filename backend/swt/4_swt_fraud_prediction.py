import joblib
import pandas as pd
import numpy as np
import os
import sys
# Resolve dirs from env vars (set by orchestrator) or fall back to script location
script_dir  = os.path.dirname(os.path.abspath(__file__))
output_dir  = os.environ.get('SWT_OUTPUT_DIR', script_dir)
models_dir  = os.environ.get('SWT_MODELS_DIR', os.path.join(script_dir, 'models'))
os.makedirs(output_dir, exist_ok=True)
loaded_model = joblib.load(os.path.join(models_dir, 'xgboost_model.pkl'))
MODULE_NAME = "4_swt_fraud_prediction.py"


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

def predict_fraud_and_save(new_data, output_csv='predictions.csv', output_parquet='predictions.parquet'):
    """
    Predict fraud probability for new data and save results to CSV and Parquet.
    
    Parameters:
    new_data: DataFrame with columns:
        - total_salary_wages_paid
        - employees_paid_swt
        - sw_paid_for_swt_deduction
        - total_swt_tax_deducted
        - employees_on_payroll
    output_csv: Name of output CSV file
    output_parquet: Name of output Parquet file
    """
    # Create a copy of the original data to avoid modifying it
    new_data_copy = new_data.copy()
    
    # Handle missing values in the required columns for prediction
    required_cols = ["total_salary_wages_paid", "employees_paid_swt",
                     "sw_paid_for_swt_deduction", "total_swt_tax_deducted",
                     "employees_on_payroll"]
    
    # Check if all required columns are present
    missing_cols = [col for col in required_cols if col not in new_data_copy.columns]
    if missing_cols:
        raise ValueError(f"Missing columns: {missing_cols}")
    
    # Fill missing values only in the required prediction columns
    for col in required_cols:
        if col in new_data_copy.columns:
            new_data_copy[col] = new_data_copy[col].fillna(0)
    
    # Make predictions using only the required columns
    prediction_data = new_data_copy[required_cols]
    probabilities = loaded_model.predict_proba(prediction_data)[:, 1]
    
    # Create predictions based on 0.2 threshold (as requested)
    predictions = (probabilities > 0.2).astype(int)
    
    # Map 1/0 to "Fraud"/"Non-Fraud"
    predicted_labels = ["Fraud" if pred == 1 else "Non-Fraud" for pred in predictions]
    
    # Add only predicted_fraud column to the original data (with all columns)
    new_data_copy['predicted_fraud'] = predicted_labels
    new_data_copy['fraud_probability'] = probabilities  # keep this for justification
    
    # Save to CSV with ALL columns plus predicted_fraud (no fraud_probability)
    new_data_copy.to_csv(output_csv, index=False)
    
    # Save to Parquet with ALL columns plus predicted_fraud (no fraud_probability)
    new_data_copy.to_parquet(output_parquet, index=False)
    
    # Return the results for further use if needed
    return {
        'predictions': predictions,
        'probabilities': probabilities,
        'predicted_labels': predicted_labels,
        'full_data_with_predictions': new_data_copy
    }

# ============ EXAMPLE USAGE ============
# Load the example data
try:
    input_path = _normalize_path(os.environ.get('SWT_CURRENT_INPUT_FILE', ''))
    if not input_path:
        raise FileNotFoundError("SWT_CURRENT_INPUT_FILE was not provided to Step 4.")
    expected_input_path = _normalize_path(os.environ.get('SWT_EXPECTED_STEP_INPUT_FILE', input_path))
    new_data = _read_dataframe(input_path, "module_load_step_4", expected_input_path)
    
    # Check if we have the required columns
    required_cols = ["total_salary_wages_paid", "employees_paid_swt",
                     "sw_paid_for_swt_deduction", "total_swt_tax_deducted",
                     "employees_on_payroll"]
    
    missing_in_data = [col for col in required_cols if col not in new_data.columns]
    
    if not missing_in_data:
        # Make predictions and save results
        results = predict_fraud_and_save(
            new_data,
            output_csv=os.path.join(output_dir, 'fraud_predictions_full.csv'),
            output_parquet=os.path.join(output_dir, 'fraud_predictions_full.parquet')
        )
            
except FileNotFoundError:
    print("ERROR: Input file not found")
except Exception as e:
    print(f"ERROR: {str(e)}")
