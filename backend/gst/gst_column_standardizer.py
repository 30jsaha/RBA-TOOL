# gst_column_standardizer.py
import pandas as pd

def standardize_gst_columns(df):
    """
    Standardize column names in GST dataset by converting to common naming convention
    
    Parameters:
        df (pd.DataFrame): Input dataframe with original column names
        
    Returns:
        pd.DataFrame: Dataframe with standardized column names
    """
    # Combined standardization mapping (2010-2019, 2020-2022, and new format)
    gst_column_standardization = {
        # Common columns
        'TIN': 'TIN',
        'Tax Payer': 'Taxpayer Name',
        'Registered Name': 'Registered Name',
        'Taxpayer Type': 'Taxpayer Type',
        'TaxpayerType': 'Taxpayer Type',
        'Tax Account No': 'Tax Account Number',
        'TaxAccountNo': 'Tax Account Number',
        'Assessment No': 'Assessment Number',
        'Assessment No.': 'Assessment Number',
        'AssessmentNo': 'Assessment Number',
        'Form Version': 'Form Version',
        'FormVersion': 'Form Version',
        'Tax Period Year': 'Tax Period Year',
        'TaxPeriodYear': 'Tax Period Year',
        'Tax Period Month': 'Tax Period Month',
        'TaxPeriodMonth': 'Tax Period Month',
        'Receive Date': 'Received Date',
        'ReceiveDate': 'Received Date',
        'Received Date': 'Received Date',
        'Entry Date': 'Entry Date',
        'EntryDate': 'Entry Date',
        
        # 2020-2022 specific
        'Due Date': 'Due Date',
        'DueDate': 'Due Date',
        '10 Total Sales': 'Total Sales Income',
        '10TotalSales': 'Total Sales Income',
        '20 Exempt Sales': 'Exempt Sales',
        '20ExemptSales': 'Exempt Sales',
        '30 Zero-rated Sales': 'Zero Rated Sales',
        '30Zero-ratedSales': 'Zero Rated Sales',
        '40 Add Lines 20 and 30': 'Add Exempt and Zero Rated Sales',
        '40AddLines20and30': 'Add Exempt and Zero Rated Sales',
        '50 GST Taxable Sales': 'GST Taxable Sales',
        '50GSTTaxableSales': 'GST Taxable Sales',
        '60 Output Debits': 'Output Debits',
        '60OutputDebits': 'Output Debits',
        '70 Deferred Import Liabil': 'Deferred Import Liabilities',
        '70DeferredImportLiabil': 'Deferred Import Liabilities',
        '80 GST Paid Bus.Input': 'GST Paid on Inputs',
        '80GSTPaidBus.Input': 'GST Paid on Inputs',
        '90 GST Paid Exempt Sales': 'GST Paid Exempt Sales',
        '90GSTPaidExemptSales': 'GST Paid Exempt Sales',
        '100 GST Paid Priv. Purpose': 'GST Paid Private',
        '100GSTPaidPriv.Purpose': 'GST Paid Private',
        '110 Add Lines 90 and 100': 'Add Private and Exempt GST Paid',
        '110AddLines90and100': 'Add Private and Exempt GST Paid',
        '120 Input Credits': 'Input Credits',
        '120InputCredits': 'Input Credits',
        '130 Output Debits': 'Output Debits',
        '130OutputDebits': 'Output Debits',
        '140 Deduct Input Credits': 'Deduct Input Credits',
        '140DeductInputCredits': 'Deduct Input Credits',
        '151 GST Payable': 'GST Payable',
        '151GSTPayable': 'GST Payable',
        '152 GST Refundable': 'GST Refundable',
        '152GSTRefundable': 'GST Refundable',
        '160 GST S64A Cr Allowable': 'GST Sec65A Credit Allowable',
        '160GSTS64ACrAllowable': 'GST Sec65A Credit Allowable',
        
        # 2010-2019 specific
        '1. Total Sales+Income ': 'Total Sales Income',
        '2. Less Exempt Sales': 'Exempt Sales',
        '3. Less Zero Rated Sales': 'Zero Rated Sales',
        '4. Add lines 2 and 3 ': 'Add Exempt and Zero Rated Sales',
        '5. GST Taxable Sales': 'GST Taxable Sales',
        '6.  Output Debits': 'Output Debits',
        '7. Deferred Import Liabilities': 'Deferred Import Liabilities',
        '8. GST paid on Inputs': 'GST Paid on Inputs',
        '9. Less GST paid exempt sales': 'GST Paid Exempt Sales',
        '10. Less GST paid Private...': 'GST Paid Private',
        '11. Add lines 9 and 10': 'Add Private and Exempt GST Paid',
        '12.  Input Credits': 'Input Credits',
        '14. Deduct Input Credits': 'Deduct Input Credits',
        '15.1 GST Payable ': 'GST Payable',
        '15.2 GST Refundable': 'GST Refundable',
        '16. GST Sec65A Cr Allowable ': 'GST Sec65A Credit Allowable',
        'Province': 'Province',
        'Sector Activity': 'Sector Activity',
        'Ent Activity Code': 'Enterprise Activity Code',
        'Enterprise Activity': 'Enterprise Activity'
    }
    
    # Apply standardization and then lowercase + replace spaces
    df = df.rename(columns=gst_column_standardization)
    df.columns = df.columns.str.lower().str.replace(' ', '_')
    
    # Remove trailing underscores from column names
    df.columns = df.columns.str.rstrip('_')
    
    # Remove duplicate columns (keeping first occurrence)
    df = df.loc[:, ~df.columns.duplicated()]
    
    return df

# Additional helper functions
def get_standardized_columns():
    """Get list of standardized column names"""
    return [
        'tin', 'taxpayer_name', 'registered_name', 'taxpayer_type',
        'tax_account_number', 'assessment_number', 'form_version',
        'tax_period_year', 'tax_period_month', 'received_date',
        'entry_date', 'due_date', 'total_sales_income', 'exempt_sales',
        'zero_rated_sales', 'add_exempt_and_zero_rated_sales',
        'gst_taxable_sales', 'output_debits', 'deferred_import_liabilities',
        'gst_paid_on_inputs', 'gst_paid_exempt_sales', 'gst_paid_private',
        'add_private_and_exempt_gst_paid', 'input_credits',
        'deduct_input_credits', 'gst_payable', 'gst_refundable',
        'gst_sec65a_credit_allowable', 'province', 'sector_activity',
        'enterprise_activity_code', 'enterprise_activity'
    ]

def save_standardized_data(df, output_path):
    """Save standardized dataframe to parquet"""
    df.to_parquet(output_path, index=False)
    return df