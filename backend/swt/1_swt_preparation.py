import numpy as np
import pandas as pd

import os 
import warnings
warnings.filterwarnings("ignore")
pd.options.display.max_columns=None
pd.options.display.float_format = '{:.2f}'.format

import glob

script_dir  = os.path.dirname(os.path.abspath(__file__))
data_dir    = os.path.join(script_dir, 'data')
output_dir  = os.environ.get('SWT_OUTPUT_DIR', script_dir)
os.makedirs(output_dir, exist_ok=True)

# Find input file dynamically
all_files = glob.glob(os.path.join(data_dir, "*.parquet")) + \
            glob.glob(os.path.join(data_dir, "*.csv"))

if not all_files:
    raise FileNotFoundError(f"No input file found in {data_dir}")

swt_files  = [f for f in all_files if 'swt' in os.path.basename(f).lower()]
candidates = swt_files if swt_files else all_files
input_path = max(candidates, key=os.path.getmtime)

print(f"Using input file: {os.path.basename(input_path)}")

if input_path.endswith('.parquet'):
    swt_df = pd.read_parquet(input_path)
else:
    swt_df = pd.read_csv(input_path)

def standardize_swt_columns(df):
    """
    Standardize column names in SWT dataset by converting to common naming convention
    
    Parameters:
        df (pd.DataFrame): Input dataframe with original column names
        
    Returns:
        pd.DataFrame: Dataframe with standardized column names
    """
    # Normalize incoming raw headers first so mapping does not depend on exact matches
    df = df.copy()
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.replace(r'\s+', ' ', regex=True)
    )

    # Combined standardization mapping (all formats)
    swt_column_standardization = {
        # Common columns
        'TIN': 'TIN',
        'Tax Period Year': 'Tax Period Year', 
        'TaxPeriodYear': 'Tax Period Year',
        'Tax Period Month': 'Tax Period Month',
        'TaxPeriodMonth': 'Tax Period Month',
        'Assessment No': 'Assessment Number',
        'Assessment No.': 'Assessment Number',
        'AssessmentNo': 'Assessment Number',
        'Entry Date': 'Entry Date',
        'EntryDate': 'Entry Date',
        'Assessed Date': 'Assessed Date',
        'AssessedDate': 'Assessed Date',
        
        # Establishment/account related
        'Estab No.': 'Establishment Number',
        'EstabNo.': 'Establishment Number',
        'Head Office': 'Head Office',
        'HeadOffice': 'Head Office',
        'Tax Account No': 'Tax Account Number',
        'TaxAccountNo': 'Tax Account Number',
        
        # Date related
        'Due Date': 'Due Date',
        'DueDate': 'Due Date',
        'Received Date': 'Received Date',
        
        # Employee/SWT related
        '10.No.Employees on Payroll': 'Employees on Payroll',
        '10.No.EmployeesonPayroll': 'Employees on Payroll',
        '1.No. Employees on Payroll': 'Employees on Payroll',
        '20.Total Salary Wages Paid': 'Total Salary Wages Paid',
        '20.TotalSalaryWagesPaid': 'Total Salary Wages Paid',
        '2.Tot.Mthly Salary/Wages Paid': 'Total Salary Wages Paid',
        '30.No.SWT Employees': 'Employees Paid SWT',
        '30.No.SWTEmployees': 'Employees Paid SWT',
        '3.No. Employees Paid S/W Tax': 'Employees Paid SWT',
        '40.SW Paid For SWT Deduct': 'SW Paid for SWT Deduction',
        '40.SWPaidForSWTDeduct': 'SW Paid for SWT Deduction',
        '4.Tot.Mthly Sal/Wages Tax Paid': 'SW Paid for SWT Deduction',
        '50.Total SW TAX Deducted': 'Total SWT Tax Deducted',
        '50.TotalSWTAXDeducted': 'Total SWT Tax Deducted',
        '5.Total Amt S/W Tax Deductions': 'Total SWT Tax Deducted',
        
        # 2013-2019 specific  
        'Taxpayer_No': 'Taxpayer Number',
        'Taxpayer Type': 'Taxpayer Type',
        'Tax Payer': 'Tax Payer',
        'FormVersion': 'Form Version',
        'Form Version': 'Form Version',
        'Province': 'Province',
        'Sector Activity': 'Sector Activity',
        'Ent Activity Code': 'Enterprise Activity Code',
        'Enterprise Activity': 'Enterprise Activity'
    }
    
    def _norm_header(s: str) -> str:
        # Keep punctuation, but normalize whitespace + case to make mapping robust.
        return ' '.join(str(s).strip().split()).lower()

    normalized_mapping = {
        _norm_header(k): v for k, v in swt_column_standardization.items()
    }

    rename = {}
    for col in df.columns:
        key = _norm_header(col)
        if key in normalized_mapping:
            rename[col] = normalized_mapping[key]

    # Apply standardization and then lowercase + replace spaces
    df = df.rename(columns=rename)
    df.columns = df.columns.str.lower().str.replace(' ', '_')
    
    # Remove trailing underscores from column names
    df.columns = df.columns.str.rstrip('_')
    
    # Remove duplicate columns (keeping first occurrence)
    df = df.loc[:, ~df.columns.duplicated()]
    
    return df
swt_df = standardize_swt_columns(swt_df)

# Save with specific settings
swt_df.to_parquet(
    os.path.join(output_dir, "swt_standardized.parquet"),
    engine='pyarrow',  # or 'fastparquet'
    index=False,       # Don't save row indices
    compression='snappy'
)
print("Success: Saved after standardization")
