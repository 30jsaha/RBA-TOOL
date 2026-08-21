import os
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")
from cit.runtime_context import get_artifact_path

# ── Resolve sibling directories relative to this script's location ──────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_OUTPUT_DIR = os.path.join(_SCRIPT_DIR, 'final_output')

def _out(filename):
    """Return absolute path inside final_output/, creating the dir if needed."""
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    return os.path.join(_OUTPUT_DIR, filename)


def _artifact_path(env_name, default_name):
    return get_artifact_path(env_name, default_name, _OUTPUT_DIR)

class FraudDetectionSystem:
    def __init__(self):
        self.rules = {}
        self._initialize_rules()
        self.covariates_to_check = [
            'total_gross_income', 'cost_of_goods_sold', 'total_operating_expenses',
            'travel_and_accommodation', 'salaries_or_wages', 'rental_expenses',
            'management_fees_foreign', 'advertising_and_promotion', 
            'bad_debts_written_off', 'legal_expenses', 'repairs_and_maintenance',
            'dividend_income'
        ]
    
    def _get_value(self, row, column_name, default=0):
        """Safely get value from row"""
        try:
            value = row.get(column_name, default)
            if pd.isna(value):
                return default
            return float(value)
        except:
            return default
    
    def _initialize_rules(self):
        """Initialize all 20 business rules"""
        self.rules = {
            1: {'condition': lambda row: self._get_value(row, 'gross_sales_cash_or_credit') > 0.9 * self._get_value(row, 'total_gross_income', 1),
                'message': 'Gross Sales (Cash/Credit) is not greater than 90% of Total Gross Income'},
            2: {'condition': lambda row: self._get_value(row, 'cost_of_goods_sold') <= self._get_value(row, 'gross_sales_cash_or_credit', 1),
                'message': 'Cost of Goods Sold exceeds Gross Sales (Cash/Credit)'},
            3: {'condition': lambda row: self._get_value(row, 'property_or_equipment') >= self._get_value(row, 'leasehold_improvements'),
                'message': 'Property/Equipment is not greater than or equal to Leasehold Improvements'},
            4: {'condition': lambda row: self._get_value(row, 'management_fees_foreign') <= 0.2 * self._get_value(row, 'total_operating_expenses', 1),
                'message': 'Foreign Management Fees exceed 20% of Total Operating Expenses'},
            5: {'condition': lambda row: self._get_value(row, 'royalties_foreign') <= 0.15 * self._get_value(row, 'total_gross_income', 1),
                'message': 'Foreign Royalties exceed 15% of Total Gross Income'},
            6: {'condition': lambda row: self._get_value(row, 'advertising_and_promotion') <= 0.1 * self._get_value(row, 'total_operating_expenses', 1),
                'message': 'Advertising and Promotion expenses exceed 10% of Total Operating Expenses'},
            7: {'condition': lambda row: self._get_value(row, 'bad_debts_written_off') <= 0.05 * self._get_value(row, 'accounts_receivable_trade', 1),
                'message': 'Bad Debts Written Off exceed 5% of Accounts Receivable (Trade)'},
            8: {'condition': lambda row: self._get_value(row, 'commissions') <= 0.15 * self._get_value(row, 'gross_sales_cash_or_credit', 1),
                'message': 'Commissions exceed 15% of Gross Sales (Cash/Credit)'},
            9: {'condition': lambda row: self._get_value(row, 'consultancy_fees') <= 0.1 * self._get_value(row, 'total_operating_expenses', 1),
                'message': 'Consultancy Fees exceed 10% of Total Operating Expenses'},
            10: {'condition': lambda row: self._get_value(row, 'legal_expenses') <= 0.05 * self._get_value(row, 'total_operating_expenses', 1),
                 'message': 'Legal Expenses exceed 5% of Total Operating Expenses'},
            11: {'condition': lambda row: self._get_value(row, 'repairs_and_maintenance') <= 0.08 * self._get_value(row, 'property_or_equipment', 1),
                 'message': 'Repairs and Maintenance expenses exceed 8% of Property/Equipment'},
            12: {'condition': lambda row: self._get_value(row, 'travel_and_accommodation') <= 0.07 * self._get_value(row, 'total_operating_expenses', 1),
                 'message': 'Travel and Accommodation expenses exceed 7% of Total Operating Expenses'},
            13: {'condition': lambda row: self._get_value(row, 'other_gross_income') >= 0.05 * self._get_value(row, 'total_gross_income', 1),
                 'message': 'Other Gross Income is less than 5% of Total Gross Income'},
            14: {'condition': lambda row: self._get_value(row, 'other') <= 0.2 * self._get_value(row, 'total_current_assets', 1),
                 'message': 'Other Current Assets exceed 20% of Total Current Assets'},
            15: {'condition': lambda row: self._get_value(row, 'gross_sales_cash_or_credit') <= self._get_value(row, 'total_gross_income'),
                 'message': 'Gross Sales (Cash/Credit) exceeds Total Gross Income'},
            16: {'condition': lambda row: self._get_value(row, 'cost_of_goods_sold') <= self._get_value(row, 'gross_sales_cash_or_credit', 1),
                 'message': 'Cost of Goods Sold exceeds Gross Sales (Cash/Credit)'},
            17: {'condition': lambda row: self._get_value(row, 'interest_expense_foreign') <= self._get_value(row, 'interest_income'),
                 'message': 'Foreign Interest Expense exceeds Interest Income'},
            18: {'condition': lambda row: self._get_value(row, 'management_fees_foreign') <= self._get_value(row, 'management_fees_png'),
                 'message': 'Foreign Management Fees exceed PNG Management Fees'},
            19: {'condition': lambda row: self._get_value(row, 'royalties_foreign') <= self._get_value(row, 'royalties_png'),
                 'message': 'Foreign Royalties exceed PNG Royalties'},
            20: {'condition': lambda row: self._get_value(row, 'advertising_and_promotion') <= 0.1 * self._get_value(row, 'gross_sales_cash_or_credit', 1),
                 'message': 'Advertising and Promotion expenses exceed 10% of Gross Sales (Cash/Credit)'}
        }
    
    def get_justification(self, row_data, is_fraud):
        """
        Get justification based on fraud status
        
        Args:
            row_data: Dictionary with case data
            is_fraud: Boolean indicating if predicted_fraud = Fraud
            
        Returns:
            str: Justification text
        """
        # If not fraud, return blank
        if not is_fraud:
            return ""
        
        # Check rules for fraud cases
        violated_rules = []
        for rule_id, rule in self.rules.items():
            try:
                if not rule['condition'](row_data):
                    violated_rules.append(f"• Rule {rule_id}: {rule['message']}")
            except:
                violated_rules.append(f"• Rule {rule_id}: Error checking rule")
        
        # If rules violated, show them
        if violated_rules:
            return "Violated business rules:\n" + "\n".join(violated_rules)
        # If no rules violated but is fraud, show covariates to check
        else:
            covariate_list = "\n".join([f"• {cov}" for cov in self.covariates_to_check])
            return "No business rules violated. Check these covariates:\n" + covariate_list


def process_cit_fraud_data():
    """
    Process CIT fraud prediction data
    
    Input: cit_final_fraud_prediction.csv
    Output: cit_fraud_with_justification.csv
    
    Adds one column: Justification
    """
    # File paths
    input_file  = _artifact_path('CIT_PREDICTION_FILE', 'cit_final_fraud_prediction.csv')
    output_file = _artifact_path('CIT_JUSTIFICATION_FILE', 'cit_fraud_with_justification.csv')
    
    try:
        # Load data
        df = pd.read_csv(input_file)
        
        # Check if predicted_fraud column exists
        if 'predicted_fraud' not in df.columns:
            return
        
        # Initialize fraud detection system
        detector = FraudDetectionSystem()
        
        # Process each case
        justifications = []
        
        for idx, row in df.iterrows():
            # Get fraud status
            fraud_value = row['predicted_fraud']
            
            # Convert to boolean
            if isinstance(fraud_value, str):
                is_fraud = fraud_value.lower() in ['fraud', 'true', '1', 'yes']
            else:
                is_fraud = bool(fraud_value)
            
            # Get justification
            justification = detector.get_justification(row.to_dict(), is_fraud)
            justifications.append(justification)
        
        # Add justification column
        df['Justification'] = justifications
        
        # Save output
        df.to_csv(output_file, index=False)
        
        print("Fraud justification Done.")
        
    except Exception:
        # Silent error handling as requested
        pass


if __name__ == "__main__":
    process_cit_fraud_data()
