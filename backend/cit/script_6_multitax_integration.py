# ══════════════════════════════════════════════════════════════
#  CIT FRAUD INTEGRATION SCRIPT
#  Cross-validates CIT fraud results with GST and SWT data
#  Reads CIT data from MySQL, GST/SWT from file (any name/order)
#  Saves final output to MySQL table: cit_integration_results
# ══════════════════════════════════════════════════════════════

import os
import getpass
import warnings
import pandas as pd
import numpy as np
from sqlalchemy import create_engine

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
#  MySQL Connection
# ─────────────────────────────────────────────

def get_mysql_engine():
    print("\n── MySQL Database Connection ──")
    user     = input("  MySQL username: ")
    password = getpass.getpass("  MySQL password: ")
    host     = input("  Host [press Enter for localhost]: ").strip() or "localhost"
    port     = input("  Port [press Enter for 3306]: ").strip() or "3306"
    database = input("  Database name: ")

    url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
    return create_engine(url)


# ─────────────────────────────────────────────
#  File Detection
# ─────────────────────────────────────────────

def detect_file_by_columns(required_columns, search_extensions=['.csv', '.parquet']):
    """Scans working directory and returns the first file containing all required columns."""
    candidates = [f for f in os.listdir('.') if any(f.endswith(ext) for ext in search_extensions)]
    for filename in candidates:
        try:
            if filename.endswith('.parquet'):
                df = pd.read_parquet(filename)
            else:
                df = pd.read_csv(filename, nrows=5)
            if all(col in df.columns for col in required_columns):
                return filename
        except:
            continue
    return None


# ─────────────────────────────────────────────
#  Main Integration
# ─────────────────────────────────────────────

def run_integration():
    print("\n" + "█"*60)
    print("  CIT FRAUD INTEGRATION — GST & SWT CROSS VALIDATION")
    print("█"*60)

    # ── Step 1: Load CIT data from MySQL
    print("\n── Step 1: Loading CIT fraud data from MySQL ──")
    try:
        engine = get_mysql_engine()
        cit_data = pd.read_sql('SELECT * FROM cit_fraud_justification', con=engine)
        engine.dispose()
        print(f"Loaded CIT data from MySQL | shape: {cit_data.shape}")
    except Exception as e:
        print(f"❌ Could not load CIT data from MySQL: {e}")
        print("Aborting integration.")
        return

    # ── Step 2: Detect GST file
    print("\n── Step 2: GST Cross-Validation ──")
    gst_file = detect_file_by_columns(['tin', 'total_sales_income'])
    print(f"GST file: {gst_file if gst_file else 'Not found — skipping GST validation'}")

    try:
        if gst_file is None:
            raise FileNotFoundError("No GST file found in working directory.")

        if gst_file.endswith('.parquet'):
            gst = pd.read_parquet(gst_file)
        else:
            gst = pd.read_csv(gst_file)

        gst = gst[['tin', 'total_sales_income']].drop_duplicates('tin')
        cit_data = cit_data.merge(gst, on='tin', how='left', suffixes=('', '_gst'))

        mask = (
            cit_data['total_sales_income'].notna() &
            cit_data['gross_sales_cash_or_credit'].notna() &
            (cit_data['gross_sales_cash_or_credit'] > 0)
        )

        cit_data['gst_sales_diff_abs'] = np.nan
        cit_data.loc[mask, 'gst_sales_diff_abs'] = abs(
            cit_data.loc[mask, 'total_sales_income'] - cit_data.loc[mask, 'gross_sales_cash_or_credit']
        )

        cit_data['gst_validation'] = 'Valid'
        cit_data.loc[cit_data['total_sales_income'].isna(), 'gst_validation'] = 'No GST Record'
        cit_data.loc[cit_data['gst_sales_diff_abs'] > 10, 'gst_validation'] = 'Sales Diff >10'
        print("GST validation complete.")

    except Exception as e:
        print(f"GST validation skipped: {e}")
        cit_data['gst_validation'] = 'No GST Data'
        cit_data['gst_sales_diff_abs'] = 0

    # ── Step 3: Detect SWT file
    print("\n── Step 3: SWT Cross-Validation ──")
    swt_file = detect_file_by_columns(['TIN', 'total_salary_wages_paid'])
    print(f"SWT file: {swt_file if swt_file else 'Not found — skipping SWT validation'}")

    try:
        if swt_file is None:
            raise FileNotFoundError("No SWT file found in working directory.")

        if swt_file.endswith('.parquet'):
            swt = pd.read_parquet(swt_file)
        else:
            swt = pd.read_csv(swt_file)

        swt = swt[['TIN', 'total_salary_wages_paid']].drop_duplicates('TIN')
        swt.columns = ['tin', 'swt_salary']
        cit_data = cit_data.merge(swt, on='tin', how='left')

        mask = (
            cit_data['swt_salary'].notna() &
            cit_data['salaries_or_wages'].notna() &
            (cit_data['salaries_or_wages'] > 0)
        )

        cit_data['swt_salary_diff_abs'] = np.nan
        cit_data.loc[mask, 'swt_salary_diff_abs'] = abs(
            cit_data.loc[mask, 'swt_salary'] - cit_data.loc[mask, 'salaries_or_wages']
        )

        cit_data['swt_validation'] = 'Valid'
        cit_data.loc[cit_data['swt_salary'].isna(), 'swt_validation'] = 'No SWT Record'
        cit_data.loc[cit_data['swt_salary_diff_abs'] > 5, 'swt_validation'] = 'Salary Diff >5'
        print("SWT validation complete.")

    except Exception as e:
        print(f"SWT validation skipped: {e}")
        cit_data['swt_validation'] = 'No SWT Data'
        cit_data['swt_salary_diff_abs'] = 0

    # ── Step 4: Multi-tax issue tagging
    print("\n── Step 4: Multi-tax Issue Tagging ──")
    cit_data['multi_tax_issue'] = 'No Issue'

    gst_issue_mask = cit_data['gst_validation'].isin(['Sales Diff >10', 'No GST Record'])
    swt_issue_mask = cit_data['swt_validation'].isin(['Salary Diff >5', 'No SWT Record'])

    cit_data.loc[gst_issue_mask, 'multi_tax_issue'] = 'GST'
    cit_data.loc[swt_issue_mask & (~gst_issue_mask), 'multi_tax_issue'] = 'SWT'
    cit_data.loc[swt_issue_mask & gst_issue_mask, 'multi_tax_issue'] = 'Both'

    print("Multi-tax tagging complete.")
    print(f"\n  Issue summary:")
    print(cit_data['multi_tax_issue'].value_counts().to_string())

    # ── Step 5: Save to MySQL
    print("\n── Step 5: Saving to MySQL ──")
    try:
        engine = get_mysql_engine()
        cit_data.to_sql('cit_integration_results', con=engine, if_exists='replace', index=False)
        print("Saved to MySQL table: cit_integration_results")
        engine.dispose()
    except Exception as e:
        print(f"Warning: Could not write to MySQL: {e}")
        print("Falling back to CSV...")
        cit_data.to_csv('cit_finalfraud_integration.csv', index=False)
        print("Saved: cit_finalfraud_integration.csv")

    print("\n" + "█"*60)
    print("  INTEGRATION COMPLETE")
    print("█"*60)
    print(f"  Final shape : {cit_data.shape}")
    print(f"  MySQL table : cit_integration_results")
    print("█"*60 + "\n")


if __name__ == "__main__":
    run_integration()