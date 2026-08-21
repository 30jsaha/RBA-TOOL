import numpy as np
import pandas as pd

import os 
import warnings
warnings.filterwarnings("ignore")
pd.options.display.max_columns=None
pd.options.display.float_format = '{:.2f}'.format
output_dir = os.environ.get('SWT_OUTPUT_DIR', os.path.dirname(os.path.abspath(__file__)))
models_dir = os.environ.get('SWT_MODELS_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models'))
os.makedirs(output_dir, exist_ok=True)


def _resolve_output_dir(output_dir_override=None):
    resolved = output_dir_override or output_dir
    os.makedirs(resolved, exist_ok=True)
    return resolved

def validate_swt_columns(df):
    """
    Validates that all required columns for SWT 2022 fraud detection are present in the dataset.
    
    Args:
        df (pd.DataFrame): The SWT dataset to validate
        
    Returns:
        tuple: (bool indicating if all columns are present, 
               str message listing missing columns if any)
    """
    required_columns = [
        'total_salary_wages_paid', 'employees_paid_swt',
       'sw_paid_for_swt_deduction', 'total_swt_tax_deducted',
       'employees_on_payroll'
    ]
    
    # Convert all column names to lowercase for case-insensitive comparison
    existing_columns = [col.lower() for col in df.columns]
    required_columns_lower = [col.lower() for col in required_columns]
    
    missing_columns = [
        col for col in required_columns_lower 
        if col not in existing_columns
    ]
    
    if missing_columns:
        # Map back to original case for display
        original_case_mapping = {col.lower(): col for col in required_columns}
        missing_columns_original_case = [
            original_case_mapping[col] for col in missing_columns
        ]
        
        message = (
            "ERROR: The following required columns are missing from the SWT dataset:\n"
            f"{', '.join(missing_columns_original_case)}\n\n"
            "These columns are essential for fraud detection. "
            "Please ensure your dataset contains all required columns before proceeding."
        )
        return False, message
    
    return True, "All required columns are present. You may proceed with fraud detection."

import logging
from datetime import datetime
import pandas as pd


def _normalize_assessment_number_column(df: pd.DataFrame, column: str = "assessment_number") -> pd.DataFrame:
    if column not in df.columns:
        return df

    df[column] = (
        pd.to_numeric(df[column], errors="coerce")
        .fillna(0)
        .astype("Int64")
    )
    return df


def merge_taxpayer_names(cleaned_df: pd.DataFrame) -> pd.DataFrame:
    if cleaned_df is None or cleaned_df.empty:
        return cleaned_df

    if "tin" not in cleaned_df.columns:
        return cleaned_df
    try:
        from config.db_config import get_mysql_engine
        from sqlalchemy import text, bindparam
    except Exception:
        return cleaned_df

    def _normalize_tin_series(s: pd.Series) -> pd.Series:
        # Match finalized GST-style join behavior: treat TIN as normalized string key.
        # Do NOT pad/alter length here; validation already enforces 9-digit TINs.
        return (
            s.fillna('')
            .astype(str)
            .str.replace(r'\.0$', '', regex=True)
            .str.strip()
        )

    def _fetch_taxpayer_names_from_db(normalized_tins):
        normalized_tins = [t for t in normalized_tins if isinstance(t, str) and t.strip() != ""]
        if not normalized_tins:
            return {}

        engine = get_mysql_engine()
        try:
            mapping = {}
            with engine.connect() as conn:
                # Detect available name column (some DBs use `taxpayername` only).
                cols = conn.execute(text("SHOW COLUMNS FROM tin_registration_mst")).fetchall()
                col_names = {str(r[0]).strip().lower() for r in cols}  # Field is first column
                if "taxpayer_name" in col_names:
                    name_col = "taxpayer_name"
                elif "taxpayername" in col_names:
                    name_col = "taxpayername"
                else:
                    return {}

                q = text(f"""
                    SELECT normalized_tin, {name_col} AS taxpayer_name
                    FROM tin_registration_mst
                    WHERE normalized_tin IN :tins
                """).bindparams(bindparam("tins", expanding=True))
                rows = conn.execute(q, {"tins": normalized_tins}).fetchall()
                for norm_tin, taxpayer_name in rows:
                    if norm_tin is None or taxpayer_name is None:
                        continue
                    mapping[str(norm_tin)] = taxpayer_name
            return mapping
        finally:
            engine.dispose()

    try:
        out = cleaned_df.copy()

        existing_taxpayer_cols = [
            col for col in out.columns
            if col.lower().replace('_', '') in ['taxpayer', 'taxpayername', 'taxpayer_name', 'tax_payer', 'tax_payer_name']
        ]

        if "_normalized_tin" in out.columns:
            out.drop(columns=["_normalized_tin"], inplace=True, errors="ignore")
        out["_normalized_tin"] = _normalize_tin_series(out["tin"])

        uniq = out["_normalized_tin"].dropna().astype(str).unique().tolist()

        global _TIN_NAME_CACHE
        try:
            _TIN_NAME_CACHE
        except NameError:
            _TIN_NAME_CACHE = {}

        missing = [t for t in uniq if t not in _TIN_NAME_CACHE]
        if missing:
            fetched = _fetch_taxpayer_names_from_db(missing)
            _TIN_NAME_CACHE.update(fetched or {})

        name_map = {t: _TIN_NAME_CACHE.get(t) for t in uniq if _TIN_NAME_CACHE.get(t) is not None}
        if name_map:
            out["_reg_taxpayer_name"] = out["_normalized_tin"].map(name_map)
            if existing_taxpayer_cols:
                existing_col = existing_taxpayer_cols[0]
                # Treat empty strings as missing so DB-backed names can populate consistently.
                try:
                    out[existing_col] = out[existing_col].replace('', pd.NA)
                except Exception:
                    pass
                out[existing_col] = out[existing_col].fillna(out["_reg_taxpayer_name"])
            else:
                out["taxpayer_name"] = out["_reg_taxpayer_name"]
            out.drop(columns=["_reg_taxpayer_name"], inplace=True, errors="ignore")
        elif not existing_taxpayer_cols and "taxpayer_name" not in out.columns:
            # Ensure stable output schema for downstream consumers.
            out["taxpayer_name"] = pd.NA

        out.drop(columns=["_normalized_tin"], inplace=True, errors="ignore")
        return out
    except Exception:
        return cleaned_df


def validate_and_clean_swt_data(df, output_dir_override=None):
    """
    Cleans and validates an SWT dataset based on predefined rules.
    Saves the cleaned data and removed invalid data into separate Parquet files.
    Displays the shape of each dataframe before saving.
    """
    # Configure logging
    current_output_dir = _resolve_output_dir(output_dir_override)
    logger = logging.getLogger("swt_validation")
    logger.setLevel(logging.INFO)
    log_path = os.path.join(current_output_dir, "swt_validation_log.txt")
    has_expected_file_handler = False
    for h in list(logger.handlers):
        if isinstance(h, logging.FileHandler):
            try:
                if os.path.abspath(getattr(h, "baseFilename", "")) == os.path.abspath(log_path):
                    has_expected_file_handler = True
            except Exception:
                pass
    if not has_expected_file_handler:
        fh = logging.FileHandler(log_path)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        logger.addHandler(fh)

    invalid_records = {}  # Dictionary to store invalid records
    removal_details = []
    removal_stats = {
    "TIN_NULL": 0,
    "TIN_NON_NUMERIC": 0,
    "TIN_WRONG_LENGTH": 0,
    "TIN_STARTS_WITH_ZERO": 0,
    "TIN_ALL_DIGITS_SAME": 0,
    "TIN_CONTINUOUS_SEQUENCE": 0,
    "SWT_EMPLOYEES_EXCEED_PAYROLL": 0,
    "INVALID_HEAD_OFFICE": 0,
    "INVALID_TAX_PERIOD_MONTH": 0,
    "FUTURE_ENTRY_DATE": 0,
    "DUPLICATE_ASSESSMENT": 0,
    "NEGATIVE_NUMERIC_VALUES": 0,
    "FRACTIONAL_EMPLOYEE_VALUES": 0,
    "HIGH_VALUE_EMPLOYEES": 0
    }

    if "_row" not in df.columns:
        df = df.copy()
        df["_row"] = np.arange(1, len(df) + 1)

    # Rule 1: Enhanced TIN Validation with comprehensive checks
    tin_column = "tin"
    if tin_column in df.columns:
        tin_series = (
            df[tin_column]
            .fillna('')
            .astype(str)
            .str.replace(r'\.0$', '', regex=True)
            .str.strip()
        )
        df[tin_column] = tin_series
        
        # Define validation conditions
        is_empty = tin_series.eq('')
        is_digits = tin_series.str.match(r'^\d+$', na=False)
        non_numeric = (~is_empty) & (~is_digits)
        wrong_length = is_digits & (tin_series.str.len() != 9)
        starts_with_zero = is_digits & (tin_series.str.len() == 9) & tin_series.str.startswith('0')
        all_same_digits = is_digits & (tin_series.str.len() == 9) & tin_series.apply(lambda x: len(set(x)) == 1)  # All digits identical

        # Check for continuous sequences (both increasing and decreasing)
        def is_continuous_sequence(s):
            if len(s) != 9 or not s.isdigit():
                return False
            diffs = [int(b) - int(a) for a, b in zip(s[:-1], s[1:])]
            return all(d == diffs[0] for d in diffs) and abs(diffs[0]) == 1
        
        is_continuous = tin_series.apply(is_continuous_sequence)
        
        # Combine all invalid conditions
        invalid_tin_mask = (
            is_empty |
            non_numeric |
            wrong_length |
            starts_with_zero |
            all_same_digits |
            is_continuous
        )
        
        # Separate records for different violation types
        invalid_tin_rows = df[invalid_tin_mask].copy()
        
        # Count different types of TIN violations
        removal_stats["TIN_NULL"] = is_empty.sum()
        removal_stats["TIN_NON_NUMERIC"] = non_numeric.sum()
        removal_stats["TIN_WRONG_LENGTH"] = wrong_length.sum()
        removal_stats["TIN_STARTS_WITH_ZERO"] = starts_with_zero.sum()
        removal_stats["TIN_ALL_DIGITS_SAME"] = all_same_digits.sum()
        removal_stats["TIN_CONTINUOUS_SEQUENCE"] = is_continuous.sum()
        
        # Keep only valid TINs
        df = df[~invalid_tin_mask]
        
        # Log invalid records
        if not invalid_tin_rows.empty:
            invalid_tin_rows["reason"] = ""
            invalid_tin_rows.loc[is_empty[invalid_tin_rows.index], "reason"] = "TIN is null/empty"
            invalid_tin_rows.loc[non_numeric[invalid_tin_rows.index], "reason"] = "TIN must contain only numeric digits"
            invalid_tin_rows.loc[wrong_length[invalid_tin_rows.index], "reason"] = invalid_tin_rows[tin_column].apply(
                lambda s: f"TIN '{s}' has wrong length (must be 9 digits)"
            )
            invalid_tin_rows.loc[starts_with_zero[invalid_tin_rows.index], "reason"] = "TIN cannot start with 0"
            invalid_records["invalid_tin"] = invalid_tin_rows
            for _, r in invalid_tin_rows.iterrows():
                row_num = int(r.get("_row")) if pd.notna(r.get("_row")) else None
                s = '' if pd.isna(r.get(tin_column)) else str(r.get(tin_column)).strip()
                if s == '':
                    logger.info(f"Row {row_num}: TIN is null/empty")
                elif not s.isdigit():
                    logger.info(f"Row {row_num}: TIN must contain only numeric digits")
                elif len(s) != 9:
                    logger.info(f"Row {row_num}: TIN '{s}' has wrong length (must be 9 digits)")
                elif s.startswith('0'):
                    logger.info(f"Row {row_num}: TIN cannot start with 0")
                else:
                    logger.info(f"Row {row_num}: TIN '{s}' is invalid")
            logger.info(f"Removed {len(invalid_tin_rows)} rows due to invalid TINs. Breakdown: {removal_stats}")

    # Rule 2: Validate Employees Paid SWT does not exceed Employees on Payroll
    if "employees_paid_swt" in df.columns and "employees_on_payroll" in df.columns:
        swt_violations = df[df["employees_paid_swt"].notna() & 
                            df["employees_on_payroll"].notna() & 
                            (df["employees_paid_swt"] > df["employees_on_payroll"])]
        df = df[df["employees_paid_swt"].isna() | df["employees_on_payroll"].isna() | 
                (df["employees_paid_swt"] <= df["employees_on_payroll"])]
        if not swt_violations.empty:
            invalid_records["Invalid_SWT_Employees"] = swt_violations
            for row_num in swt_violations.get("_row", pd.Series([], dtype="Int64")).tolist():
                if pd.notna(row_num):
                    logger.info(f"Row {int(row_num)}: Employees Paid SWT exceeds Employees on Payroll")
            logger.info(f"Removed {len(swt_violations)} rows due to SWT employees exceeding payroll employees.")
            removal_stats["SWT_EMPLOYEES_EXCEED_PAYROLL"] += len(swt_violations)

    # Rule 3: Validate Head Office column (should contain only 'Y' or 'N')
    head_office_column = "head_office"
    if head_office_column in df.columns:
        head_office_series = (
            df[head_office_column]
            .astype("string")
            .str.strip()
            .str.upper()
            .replace({"": pd.NA})
        )
        df[head_office_column] = head_office_series

        valid_head_office_values = ["Y", "N", "NA"]
        invalid_head_office_rows = df[head_office_series.notna() & ~head_office_series.isin(valid_head_office_values)]
        df = df[head_office_series.isna() | head_office_series.isin(valid_head_office_values)]
        if not invalid_head_office_rows.empty:
            invalid_records["Invalid_Head_Office"] = invalid_head_office_rows
            for row_num in invalid_head_office_rows.get("_row", pd.Series([], dtype="Int64")).tolist():
                if pd.notna(row_num):
                    logger.info(f"Row {int(row_num)}: Invalid head_office value")
            logger.info(f"Removed {len(invalid_head_office_rows)} rows due to invalid Head Office values.")
            removal_stats["INVALID_HEAD_OFFICE"] += len(invalid_head_office_rows)

    # Rule 4: Validate Tax Period Month (should be between 1-12)
    if "tax_period_month" in df.columns:
        invalid_tax_period_rows = df[df["tax_period_month"].notna() & ~df["tax_period_month"].between(1, 12)]
        df = df[df["tax_period_month"].isna() | df["tax_period_month"].between(1, 12)]
        if not invalid_tax_period_rows.empty:
            invalid_records["Invalid_Tax_Period"] = invalid_tax_period_rows
            for row_num in invalid_tax_period_rows.get("_row", pd.Series([], dtype="Int64")).tolist():
                if pd.notna(row_num):
                    logger.info(f"Row {int(row_num)}: Invalid tax_period_month")
            logger.info(f"Removed {len(invalid_tax_period_rows)} rows due to invalid tax period month.")
            removal_stats["INVALID_TAX_PERIOD_MONTH"] += len(invalid_tax_period_rows)

    if "tax_period_year" in df.columns:
        current_year = datetime.now().year
        invalid_tax_period_year_rows = df[
            df["tax_period_year"].notna()
            & ~df["tax_period_year"].between(2010, current_year)
        ].copy()
        df = df[df["tax_period_year"].isna() | df["tax_period_year"].between(2010, current_year)]
        if not invalid_tax_period_year_rows.empty:
            invalid_records["Invalid_Tax_Period_Year"] = invalid_tax_period_year_rows
            for row_num in invalid_tax_period_year_rows.get("_row", pd.Series([], dtype="Int64")).tolist():
                if pd.notna(row_num):
                    logger.info(f"Row {int(row_num)}: Invalid tax_period_year")

    # Duplicate business-record validation: remove ALL duplicates for same (tin, year, month)
    if all(c in df.columns for c in ["tin", "tax_period_year", "tax_period_month"]):
        duplicate_mask = df.duplicated(
            subset=["tin", "tax_period_year", "tax_period_month"],
            keep=False
        )
        duplicate_swt_rows = df[duplicate_mask].copy()
        duplicate_reason = "Duplicate SWT record found in upload file for same tax_period_year and tax_period_month"
        duplicate_swt_rows["reason"] = duplicate_reason
        df = df[~duplicate_mask]
        if not duplicate_swt_rows.empty:
            invalid_records["Duplicate_SWT_Record"] = duplicate_swt_rows
            for row_num in duplicate_swt_rows.get("_row", pd.Series([], dtype="Int64")).tolist():
                if pd.notna(row_num):
                    removal_details.append(f"Row {int(row_num)}: {duplicate_reason}")
                    logger.info(f"Row {int(row_num)}: {duplicate_reason}")

    # Rule 5: Validate Entry Date (should not be in the future)
    date_columns = ["entry_date", "assessed_date", "due_date"]
    for col in date_columns:
        if col in df.columns:
            original_series = df[col].astype("string").str.strip().replace({"": pd.NA})
            parsed_series = pd.to_datetime(original_series, errors="coerce")

            invalid_date_format_rows = df[original_series.notna() & parsed_series.isna()].copy()
            if not invalid_date_format_rows.empty:
                invalid_records[f"Invalid_{col}_Format"] = invalid_date_format_rows
                for row_num in invalid_date_format_rows.get("_row", pd.Series([], dtype="Int64")).tolist():
                    if pd.notna(row_num):
                        logger.info(f"Row {int(row_num)}: Invalid {col} format")

            df[col] = parsed_series
            df = df[original_series.isna() | df[col].notna()]

            # For entry_date specifically, check future dates
            if col == "entry_date":
                invalid_entry_date_rows = df[df[col].notna() & (df[col] > datetime.now())]
                df = df[df[col].isna() | (df[col] <= datetime.now())]
                if not invalid_entry_date_rows.empty:
                    invalid_records[f"Invalid_{col}"] = invalid_entry_date_rows
                    for row_num in invalid_entry_date_rows.get("_row", pd.Series([], dtype="Int64")).tolist():
                        if pd.notna(row_num):
                            logger.info(f"Row {int(row_num)}: Future {col}")
                    logger.info(f"Removed {len(invalid_entry_date_rows)} rows due to future {col}.")
                    removal_stats["FUTURE_ENTRY_DATE"] += len(invalid_entry_date_rows)

    # Rule 6: Validate Assessment Number (should not have duplicates)
    assessment_column = "assessment_number"
    if assessment_column in df.columns:
        assessment_series = (
            df[assessment_column]
            .astype("string")
            .str.strip()
            .str.upper()
            .replace({"": pd.NA, "NA": pd.NA})
        )
        df[assessment_column] = assessment_series
        duplicate_assessment_rows = df[df[assessment_column].notna() & 
                                       df.duplicated(subset=[assessment_column], keep=False)]
        df = df[~df.duplicated(subset=[assessment_column], keep="first")]
        if not duplicate_assessment_rows.empty:
            invalid_records["Duplicate_Assessment"] = duplicate_assessment_rows
            for row_num in duplicate_assessment_rows.get("_row", pd.Series([], dtype="Int64")).tolist():
                if pd.notna(row_num):
                    logger.info(f"Row {int(row_num)}: Duplicate assessment_number")
            logger.info(f"Removed {len(duplicate_assessment_rows)} duplicate assessment numbers.")
            removal_stats["DUPLICATE_ASSESSMENT"] += len(duplicate_assessment_rows)
        df = _normalize_assessment_number_column(df, assessment_column)

    # Rule 7: Validate Numeric Columns (should not contain negative values)
    numeric_columns = ["employees_on_payroll", "total_salary_wages_paid", 
                       "employees_paid_swt", "sw_paid_for_swt_deduction", "total_swt_tax_deducted"]
    for col in numeric_columns:
        if col in df.columns:
            invalid_numeric_rows = df[df[col].notna() & (df[col] < 0)]
            df = df[df[col].isna() | (df[col] >= 0)]
            if not invalid_numeric_rows.empty:
                invalid_records[f"Invalid_{col}"] = invalid_numeric_rows
                for row_num in invalid_numeric_rows.get("_row", pd.Series([], dtype="Int64")).tolist():
                    if pd.notna(row_num):
                        logger.info(f"Row {int(row_num)}: Negative value in {col}")
                logger.info(f"Removed {len(invalid_numeric_rows)} rows due to negative values in {col}.")
                removal_stats["NEGATIVE_NUMERIC_VALUES"] += len(invalid_numeric_rows)

    # Rule 8: Validate Fractional Values and check for values > 5000 with user interaction
    integer_columns = ["employees_on_payroll", "employees_paid_swt"]
    for col in integer_columns:
        if col in df.columns:
            # Check for fractional values first
            fractional_rows = df[df[col].notna() & (df[col] % 1 != 0)]
            df = df[df[col].isna() | (df[col] % 1 == 0)]
            if not fractional_rows.empty:
                invalid_records[f"Invalid_{col}_Fractional"] = fractional_rows
                for row_num in fractional_rows.get("_row", pd.Series([], dtype="Int64")).tolist():
                    if pd.notna(row_num):
                        logger.info(f"Row {int(row_num)}: Fractional value in {col}")
                logger.info(f"Removed {len(fractional_rows)} rows due to fractional values in {col}.")
                removal_stats["FRACTIONAL_EMPLOYEE_VALUES"] += len(fractional_rows)
            
           # Check for values > 5000 â€” remove automatically, no prompt
            high_value_rows = df[df[col].notna() & (df[col] > 5000)]
            if not high_value_rows.empty:
                print(f"\nWarning: Found {len(high_value_rows)} records with {col} > 5000 â€” removing automatically.")
                df = df[~df.index.isin(high_value_rows.index)]
                invalid_records[f"High_Value_{col}"] = high_value_rows
                for row_num in high_value_rows.get("_row", pd.Series([], dtype="Int64")).tolist():
                    if pd.notna(row_num):
                        logger.info(f"Row {int(row_num)}: {col} > 5000 (auto-removed)")
                logger.info(f"Removed {len(high_value_rows)} rows due to {col} > 5000 (auto-removed).")
                removal_stats["HIGH_VALUE_EMPLOYEES"] += len(high_value_rows)

    # Rule 9: Validate Date Columns Format (already handled in Rule 5)
    # All date columns are already converted to datetime in Rule 5

    # Store cleaned and removed data in dataframes
    cleaned_data_df = df
    removed_data_df = pd.concat(invalid_records.values(), ignore_index=True) if invalid_records else pd.DataFrame()
    cleaned_data_df = _normalize_assessment_number_column(cleaned_data_df, assessment_column)
    removed_data_df = _normalize_assessment_number_column(removed_data_df, assessment_column)

    # Display dataframe shapes
    print(f"\nCleaned Data Shape: {cleaned_data_df.shape}")
    print(f"Removed Data Shape: {removed_data_df.shape}")

    # Convert datetime columns to proper format for Parquet
    for col in date_columns:
        if col in cleaned_data_df.columns:
            cleaned_data_df[col] = cleaned_data_df[col].astype('datetime64[ns]')
        if col in removed_data_df.columns:
            removed_data_df[col] = removed_data_df[col].astype('datetime64[ns]')

    # Save cleaned data to Parquet
    cleaned_data_df.to_parquet(os.path.join(current_output_dir, "swt_cleaned_data.parquet"), index=False)
    
    # Save invalid data to another Parquet file
    if not removed_data_df.empty:
        removed_data_df.to_csv(os.path.join(current_output_dir, "swt_removed_data.csv"), index=False)
        logger.info(f"Removed records saved to swt_removed_data.csv")
    # Write validation summary to log
    logger.info("=== SWT Validation Summary ===")
    logger.info(f"Total records removed: {sum(removal_stats.values())}")
    for rule, count in removal_stats.items():
        if count > 0:
            logger.info(f"  {rule}: {count} records removed")
    logger.info("=== Validation Complete ===")
    logger.info(f"Records retained: {len(cleaned_data_df)}")
    logger.info(f"Records removed: {len(removed_data_df)}")         
    return cleaned_data_df, removed_data_df, removal_details

if __name__ == "__main__":
    df = pd.read_parquet(os.path.join(output_dir, "swt_standardized.parquet"))

    is_valid, message = validate_swt_columns(df)
    if not is_valid:
        print(message)
    else:
        print(message)
        cleaned_df, removed_df, _ = validate_and_clean_swt_data(df)

        swt_df = merge_taxpayer_names(cleaned_df)

        swt_df.to_parquet(
            os.path.join(output_dir, "swt_data_after_taxpayer_name_mapping.parquet"),
            compression='snappy',
            index=False,
            engine='pyarrow'
        )
        print("Success: Saved after taxpayer name mapping (DB-backed)")

