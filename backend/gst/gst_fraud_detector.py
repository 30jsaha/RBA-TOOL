# gst_fraud_detector.py
import numpy as np
import pandas as pd

def add_fraud_detection_features(df):
    """
    Adds fraud detection features to GST dataset.
    
    Args:
        df (pd.DataFrame): GST dataset with required columns
        
    Returns:
        pd.DataFrame: Dataset with fraud detection features added
    """
    df = df.copy()
    
    # Feature-1: 140 Deduct Input Credits should always be less than or equal to 120 Input Credits.   
    df['deduct_input_credits_violation'] = (df['deduct_input_credits'] > df['input_credits']).astype(int)

    # Feature-2 152 GST Refundable should only exist when 140 Deduct Input Credits exceeds 130 Output Debits.
    df['invalid_gst_refundable'] = ((df['gst_refundable'] > 0) & (df['deduct_input_credits'] <= df['output_debits'])).astype(int)

    # Feature-3: TINs having output debits even after deducting input credit but paid zero tax.
    df['fraud_output_debits_no_tax'] = ((df['output_debits'] - df['deduct_input_credits'] > 0) & (df['gst_payable'] == 0)).astype(int)

    # Feature-4: If exempt_sales > total_sales_income, it suggests misreporting of tax-exempt transactions.
    df['misreported_zero_rated_sales'] = (df['zero_rated_sales'] > df['total_sales_income']).astype(int)    

    # Feature-5: If zero_rated_sales > total_sales_income, it may indicate overstatement of zero-rated sales.
    df['overstated_zero_rated_sales'] = (df['zero_rated_sales'] > df['total_sales_income']).astype(int)

    # Feature-6: If gst_taxable_sales = (total_sales_income - (exempt_sales + zero_rated_sales)), possible non-reporting of taxable sales.
    df['non_reported_taxable_sales'] = (df['gst_taxable_sales'] == (df['total_sales_income'] - (df['exempt_sales'] + df['zero_rated_sales']))).astype(int)

    # Feature-7: Ensure exactly one GST return per month (1-12)
    if 'tax_period_year' in df.columns and 'tax_period_month' in df.columns:
        gst_returns_count = df.groupby(['tin', 'tax_period_year'])['tax_period_month'].nunique().reset_index()
        gst_returns_count['fraud_incomplete_gst_returns'] = (gst_returns_count['tax_period_month'] < 12).astype(int)
        df = df.merge(gst_returns_count[['tin', 'tax_period_year', 'fraud_incomplete_gst_returns']], 
                     on=['tin', 'tax_period_year'], how='left')
    else:
        df['fraud_incomplete_gst_returns'] = 0

    # Feature-8: Identify non-filing GST cases
    if 'tax_period_year' in df.columns and 'tax_period_month' in df.columns:
        gst_returns_missing = df.groupby(['tin', 'tax_period_year'])['tax_period_month'].nunique().reset_index()
        gst_returns_missing['non_filing_gst'] = (gst_returns_missing['tax_period_month'] == 0).astype(int)
        df = df.merge(gst_returns_missing[['tin', 'tax_period_year', 'non_filing_gst']], 
                     on=['tin', 'tax_period_year'], how='left')
    else:
        df['non_filing_gst'] = 0

    # Feature-9: Drop in sales by more than 50% but input credits remain same or increase
    df['sales_drop_more_than_50_percent'] = ((df['gst_taxable_sales'] < df.groupby('tin')['gst_taxable_sales'].shift(1) * 0.5) & 
                                             (df['input_credits'] >= df.groupby('tin')['input_credits'].shift(1))).astype(int)

    # Feature-10: Consecutive refund claims for 6 or more months and total_sales<250000
    df['fraud_multiple_refund_claims_6_months'] = ((df.groupby('tin')['gst_refundable']
                                                 .rolling(window=6, min_periods=1).sum()
                                                 .reset_index(level=0, drop=True) > 0) & 
                                                (df['total_sales_income'] < 250000)).astype(int)

    # Calculate sum of rules (Note: sales_drop_more_than_50_percent appears twice in original code)
    df["sum_of_rules"] = (df['misreported_zero_rated_sales'] + 
                         df['overstated_zero_rated_sales'] + 
                         df['fraud_incomplete_gst_returns'] + 
                         df['sales_drop_more_than_50_percent'] * 2 +  # Fixed: appears twice
                         df['fraud_multiple_refund_claims_6_months'])
    
    # Mark as fraud if sum_of_rules >= 1
    df["is_fraud"] = np.where(df["sum_of_rules"] >= 1, 1, 0)

    # Drop intermediate columns
    df.drop(columns=['sum_of_rules'], inplace=True, errors='ignore')
    
    return df

# Optional: Add more fraud detection functions if needed
def get_required_columns():
    """Returns list of columns required for fraud detection"""
    return [
        'total_sales_income', 'taxpayer_type', 'exempt_sales', 'zero_rated_sales',
        'add_exempt_and_zero_rated_sales', 'gst_taxable_sales', 'output_debits',
        'deferred_import_liabilities', 'gst_paid_on_inputs', 'gst_paid_exempt_sales',
        'gst_paid_private', 'add_private_and_exempt_gst_paid', 'input_credits',
        'deduct_input_credits', 'gst_payable', 'gst_refundable', 'gst_sec65a_credit_allowable',
        'tin'
    ]