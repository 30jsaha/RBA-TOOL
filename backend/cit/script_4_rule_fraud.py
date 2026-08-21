import os
import pandas as pd
import numpy as np
import joblib
from tqdm import tqdm
import warnings
warnings.filterwarnings("ignore")
from cit.runtime_context import get_artifact_path

# ── Resolve sibling directories relative to this script's location ──────────
_SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
_OUTPUT_DIR  = os.path.join(_SCRIPT_DIR, 'final_output')
_MODELS_DIR  = os.path.join(_SCRIPT_DIR, 'models')

def _out(filename):
    """Return absolute path inside final_output/, creating the dir if needed."""
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    return os.path.join(_OUTPUT_DIR, filename)


def _artifact_path(env_name, default_name):
    return get_artifact_path(env_name, default_name, _OUTPUT_DIR)

def _model(filename):
    """Return absolute path inside cit/models/."""
    return os.path.join(_MODELS_DIR, filename)


def apply_cit_flag_rules():
    """
    Apply CIT flag rules to the dataset
    """
    # Load CIT data
    cit_data = pd.read_csv(_artifact_path('CIT_CLEANED_FILE', 'cit_cleaned_data.csv'))
    
    # Initialize all rule flags to False
    for rule_num in range(1, 27):
        cit_data[f'rule_{rule_num}_valid'] = False
    
    # Define all rules
    rules = [
        (1, lambda df: df['gross_sales_cash_or_credit'] < (0.9 * df['total_gross_income']), 
         ['gross_sales_cash_or_credit', 'total_gross_income']),
        (2, lambda df: df['cost_of_goods_sold'] > (0.75 * df['gross_sales_cash_or_credit']), 
         ['cost_of_goods_sold', 'gross_sales_cash_or_credit']),
        (3, lambda df: df['property_or_equipment'] < df['leasehold_improvements'], 
         ['property_or_equipment', 'leasehold_improvements']),
        (4, lambda df: df['management_fees_foreign'] > (0.2 * df['total_operating_expenses']), 
         ['management_fees_foreign', 'total_operating_expenses']),
        (5, lambda df: df['royalties_foreign'] > (0.15 * df['total_gross_income']), 
         ['royalties_foreign', 'total_gross_income']),
        (6, lambda df: df['advertising_and_promotion'] > (0.1 * df['total_operating_expenses']), 
         ['advertising_and_promotion', 'total_operating_expenses']),
        (7, lambda df: df['bad_debts_written_off'] > (0.05 * df['accounts_receivable_trade']), 
         ['bad_debts_written_off', 'accounts_receivable_trade']),
        (8, lambda df: df['consultancy_fees'] > (0.1 * df['total_operating_expenses']), 
         ['consultancy_fees', 'total_operating_expenses']),
        (9, lambda df: df['legal_expenses'] > (0.05 * df['total_operating_expenses']), 
         ['legal_expenses', 'total_operating_expenses']),
        (10, lambda df: df['repairs_and_maintenance'] > (0.08 * df['property_or_equipment']), 
         ['repairs_and_maintenance', 'property_or_equipment']),
        (11, lambda df: df['travel_and_accommodation'] > (0.07 * df['total_operating_expenses']), 
         ['travel_and_accommodation', 'total_operating_expenses']),
        (12, lambda df: df['other_gross_income'] < (0.05 * df['total_gross_income']), 
         ['other_gross_income', 'total_gross_income']),
        (13, lambda df: df['prior_year_losses_utilised'] != 0, 
         ['prior_year_losses_utilised']),
        (14, lambda df: df['interest_expense_foreign'] > df['interest_income'], 
         ['interest_expense_foreign', 'interest_income']),
        (15, lambda df: df['management_fees_foreign'] > df['management_fees_png'], 
         ['management_fees_foreign', 'management_fees_png']),
        (16, lambda df: df['royalties_foreign'] > df['royalties_png'], 
         ['royalties_foreign', 'royalties_png']),
        (17, lambda df: df['dividend_income'] > (0.2 * df['total_gross_income']), 
         ['dividend_income', 'total_gross_income']),
        (18, lambda df: (df['interest_expense_png'] + df['interest_expense_foreign']) > (0.15 * (df['loans_from_directors'] + df['other_loans'])), 
         ['interest_expense_png', 'interest_expense_foreign', 'loans_from_directors', 'other_loans']),
        (19, lambda df: (df['total_gross_income'] - df['gross_sales_cash_or_credit']) > (0.25 * df['total_gross_income']), 
         ['gross_sales_cash_or_credit', 'total_gross_income']),
        (20, lambda df: df['bad_debts_written_off'] > (0.01 * df['accounts_receivable_trade']), 
         ['bad_debts_written_off', 'accounts_receivable_trade']),
        (21, lambda df: ((df['total_gross_income'] - df['total_operating_expenses'] + 
                         df['total_non_deductible_items'] - df['total_deductible_items_ex']) * 0.3) != df['gross_tax'], 
         ['total_gross_income', 'total_operating_expenses', 'total_non_deductible_items', 'total_deductible_items_ex', 'gross_tax'])
    ]
    
    # Apply each rule
    for rule_num, condition, required_columns in rules:
        missing_cols = [col for col in required_columns if col not in cit_data.columns]
        if not missing_cols:
            cit_data[f'rule_{rule_num}_valid'] = condition(cit_data)
    
    # Calculate total violations
    rule_columns = [col for col in cit_data.columns if col.startswith('rule_') and col.endswith('_valid')]
    cit_data['sum_of_rules'] = cit_data[rule_columns].sum(axis=1)
    
    # Save results
    cit_data.to_csv(_artifact_path('CIT_RULE_VIOLATIONS_FILE', 'cit_with_rule_violations.csv'), index=False)
    
    return cit_data

def process_and_predict_fraud_xgboost():
    """
    Process data and make fraud predictions using pre-trained XGBoost model
    """
    # Load the trained model, scaler, and feature columns
    model = joblib.load(_model('xgboost_fraud_model.pkl'))
    scaler = joblib.load(_model('scaler.pkl'))
    feature_columns = joblib.load(_model('feature_columns.pkl'))
    
    # Read the input file
    df = pd.read_csv(_artifact_path('CIT_RULE_VIOLATIONS_FILE', 'cit_with_rule_violations.csv'), low_memory=False)
    
    # Create a copy for processing
    df_processed = df.copy()
    
    # Check if all required feature columns exist
    missing_columns = [col for col in feature_columns if col not in df_processed.columns]
    for col in missing_columns:
        df_processed[col] = 0
    
    # Prepare features
    X = df_processed[feature_columns].copy()
    
    # Normalize features using the saved scaler
    X_scaled = scaler.transform(X)
    X_final = pd.DataFrame(X_scaled, columns=feature_columns, index=df_processed.index)
    X_final = X_final.fillna(0)
    
    # Make predictions
    fraud_probability = model.predict_proba(X_final)[:, 1]
    fraud_prediction = (fraud_probability > 0.5).astype(int)
    
    # Create output dataframe
    df_output = df.copy()
    df_output['predicted_fraud'] = np.where(fraud_prediction == 1, 'Fraud', 'Non-Fraud')
    
    # Save to output file
    df_output.to_csv(_artifact_path('CIT_PREDICTION_FILE', 'cit_final_fraud_prediction.csv'), index=False)
    
    return df_output

def main():
    """
    Main function to run the entire process
    """
    # Apply CIT flag rules
    apply_cit_flag_rules()
    
    # Process and predict fraud
    process_and_predict_fraud_xgboost()
    
    print("Fraud Prediction Done!")

if __name__ == "__main__":
    main()
