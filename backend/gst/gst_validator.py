# gst_validator.py
import pandas as pd
import logging
from collections import defaultdict

def validate_gst_columns(df):
    """
    Validates that all required columns for GST 2022 fraud detection are present in the dataset.
    
    Args:
        df (pd.DataFrame): The GST dataset to validate
        
    Returns:
        tuple: (bool indicating if all columns are present, 
               str message listing missing columns if any)
    """
    required_columns = [
        'total_sales_income', 'taxpayer_type', 'exempt_sales', 'zero_rated_sales',
       'add_exempt_and_zero_rated_sales', 'gst_taxable_sales', 'output_debits',
       'deferred_import_liabilities', 'gst_paid_on_inputs',
       'gst_paid_exempt_sales', 'gst_paid_private',
       'add_private_and_exempt_gst_paid', 'input_credits',
       'deduct_input_credits', 'gst_payable', 'gst_refundable',
       'gst_sec65a_credit_allowable'
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
            "ERROR: The following required columns are missing from the GST dataset:\n"
            f"{', '.join(missing_columns_original_case)}\n\n"
            "These columns are essential for fraud detection. "
            "Please ensure your dataset contains all required columns before proceeding."
        )
        return False, message
    
    return True, "All required columns are present. You may proceed with fraud detection."


def validate_tin_only(df):
    """
    Lightweight TIN-only validation.
    Validates:
      - null/empty
      - non-numeric
      - not exactly 9 digits
      - starts with zero
      - all identical digits
      - continuous sequence

    Returns:
      valid_tin_df, invalid_tin_df, tin_errors(list[dict])
    """
    tin_column = "tin"
    if tin_column not in df.columns:
        return df.copy(), pd.DataFrame(), []

    tin_original = (
        df[tin_column]
        .astype(str)
        .str.strip()
        .str.replace(".0", "", regex=False)
    )

    # Numeric check only
    tin_num = pd.to_numeric(tin_original, errors='coerce')
    non_numeric = tin_num.isna()

    # Keep TIN as string always
    tin_series = tin_original

    is_null = (
        tin_series.str.lower()
        .isin(['', 'nan', 'none', 'null', '<na>'])
    )
    wrong_length = ~tin_series.str.match(r'^\d{9}$')
    starts_with_zero = tin_series.str.match(r'^0')
    all_same_digits = tin_series.apply(lambda x: isinstance(x, str) and len(x) > 0 and len(set(x)) == 1)

    def is_continuous_sequence(s):
        if not isinstance(s, str) or len(s) != 9 or not s.isdigit():
            return False
        diffs = [int(b) - int(a) for a, b in zip(s[:-1], s[1:])]
        return all(d == diffs[0] for d in diffs) and abs(diffs[0]) == 1

    is_continuous = tin_series.apply(is_continuous_sequence)

    invalid_tin_mask = (
        is_null |
        non_numeric |
        wrong_length |
        starts_with_zero |
        all_same_digits |
        is_continuous
    )

    valid_tin_df = df[~invalid_tin_mask].copy()
    invalid_tin_df = df[invalid_tin_mask].copy()
    # Preserve original TIN values for invalid rows (do not affect removal rules)
    try:
        invalid_tin_df[tin_column] = tin_original[invalid_tin_mask].values
    except Exception:
        pass

    tin_errors = []
    for idx, row in invalid_tin_df.iterrows():
        val = row.get(tin_column)
        if pd.isna(val) or str(val).strip().lower() in ['', 'nan', 'none', 'null', '<na>']:
            reason = "TIN is null/empty"
            rule_key = "TIN_NULL"
        elif non_numeric.get(idx, False):
            reason = f"TIN '{val}' is not numeric"
            rule_key = "TIN_NON_NUMERIC"
        elif wrong_length.get(idx, False):
            reason = f"TIN '{val}' has wrong length (must be 9 digits)"
            rule_key = "TIN_WRONG_LENGTH"
        elif starts_with_zero.get(idx, False):
            reason = f"TIN '{val}' starts with zero"
            rule_key = "TIN_STARTS_WITH_ZERO"
        elif all_same_digits.get(idx, False):
            reason = f"TIN '{val}' has all identical digits"
            rule_key = "TIN_ALL_DIGITS_SAME"
        elif is_continuous.get(idx, False):
            reason = f"TIN '{val}' is a continuous sequence"
            rule_key = "TIN_CONTINUOUS_SEQUENCE"
        else:
            reason = "Invalid TIN"
            rule_key = "TIN_INVALID"

        tin_errors.append({
            'row': int(idx),
            'tin': '' if pd.isna(val) else str(val),
            'column': 'TIN',
            'reason': reason,
            'rule_key': rule_key,
        })

    # Add a reason column for invalid TIN rows so removed output keeps the exact reason
    if tin_errors:
        try:
            invalid_tin_df['reason'] = invalid_tin_df.index.map(
                {e['row']: e['reason'] for e in tin_errors}
            )
        except Exception:
            pass

    return valid_tin_df, invalid_tin_df, tin_errors


def validate_and_clean_gst_data(df, allowed_taxpayer_types={"individual", "enterprise"}):
    """
    Cleans and validates a GST dataset based on predefined rules.
    Returns cleaned and removed dataframes.
    """
    # Configure logging
    # Remove any existing handlers so basicConfig can re-open the file cleanly
    # and the file handle is fully released when this function returns.
    root_logger = logging.getLogger()
    for _h in root_logger.handlers[:]:
        root_logger.removeHandler(_h)
        _h.close()
    # Start a fresh log for each validation run (avoid stale reasons from older runs)
    try:
        open("gst_validation_log.txt", "w", encoding="utf-8").close()
    except Exception:
        pass
    logging.basicConfig(
        filename="gst_validation_log.txt",
        filemode="a",
        level=logging.INFO,
        format='%(asctime)s - %(message)s'
    )
    
    # Dictionary to store removal statistics and reasons
    removal_stats = defaultdict(int)
    removal_details = defaultdict(list)
    
    # Convert column names to lowercase and replace spaces with underscores
    df.columns = df.columns.str.lower().str.replace(' ', '_')

    invalid_records = {}

    # Rule 1: BASIC TIN validation first (so invalid TIN rows never hit taxpayer merge)
    valid_tin_df, invalid_tin_df, tin_errors = validate_tin_only(df)
    if not invalid_tin_df.empty:
        invalid_records["invalid_tin"] = invalid_tin_df
        for e in tin_errors:
            key = e.get('rule_key') or "TIN_INVALID"
            removal_stats[key] += 1
            removal_details[key].append(f"Row {e['row']}: {e['reason']}")

    df = valid_tin_df

    # New Rule: Duplicate records inside upload file (TIN + year + month)
    dup_subset = ['tin', 'tax_period_year', 'tax_period_month']
    if all(c in df.columns for c in dup_subset) and len(df) > 0:
        duplicate_mask = df.duplicated(subset=dup_subset, keep=False)
        duplicate_rows = df[duplicate_mask].copy()
        if not duplicate_rows.empty:
            duplicate_rows['reason'] = (
                "Duplicate TIN record found in upload file for same tax_period_year and tax_period_month"
            )
            invalid_records["duplicate_tin_period_upload"] = duplicate_rows
            removal_stats["DUPLICATE_TIN_PERIOD_UPLOAD"] += int(len(duplicate_rows))
            for idx, row in duplicate_rows.iterrows():
                removal_details["DUPLICATE_TIN_PERIOD_UPLOAD"].append(
                    f"Row {idx}: Duplicate TIN record found in upload file for same tax_period_year and tax_period_month"
                )
            df = df[~duplicate_mask]

    # NOTE: taxpayer-name merge is performed AFTER full validation on cleaned data.
    
    # Rule 2: Validate Taxpayer Type (Non-nullable)
    taxpayer_column = "taxpayer_type"
    if taxpayer_column in df.columns:
        # Identify invalid records (null or not in allowed types)
        invalid_taxpayer_mask = (
            df[taxpayer_column].isna() |
            ~df[taxpayer_column].str.lower().isin(allowed_taxpayer_types)
        )
        invalid_taxpayer_rows = df[invalid_taxpayer_mask]
    
        # Count null vs invalid type
        null_count = invalid_taxpayer_rows[taxpayer_column].isna().sum()
        invalid_type_count = len(invalid_taxpayer_rows) - null_count
        
        if null_count > 0:
            removal_stats["TAXPAYER_TYPE_NULL"] += null_count
            for idx, row in invalid_taxpayer_rows[invalid_taxpayer_rows[taxpayer_column].isna()].iterrows():
                removal_details["TAXPAYER_TYPE_NULL"].append(f"Row {idx}: Taxpayer type is null")
        if invalid_type_count > 0:
            removal_stats["TAXPAYER_TYPE_INVALID"] += invalid_type_count
            for idx, row in invalid_taxpayer_rows[~invalid_taxpayer_rows[taxpayer_column].isna()].iterrows():
                removal_details["TAXPAYER_TYPE_INVALID"].append(
                    f"Row {idx}: Taxpayer type '{row[taxpayer_column]}' not in allowed types {allowed_taxpayer_types}"
                )
    
        # Keep only valid records
        df = df[~invalid_taxpayer_mask]
    
        # Log invalid records
        if not invalid_taxpayer_rows.empty:
            invalid_records["invalid_taxpayer_type"] = invalid_taxpayer_rows
    
    # Rule 3: Validate Assessment Number
    assessment_column = "assessment_number"
    if assessment_column in df.columns:
        # Non-numeric assessment numbers
        non_numeric_mask = df[assessment_column].notna() & ~df[assessment_column].astype(str).str.isnumeric()
        non_numeric_assessment_rows = df[non_numeric_mask]
        if not non_numeric_assessment_rows.empty:
            removal_stats["ASSESSMENT_NON_NUMERIC"] += len(non_numeric_assessment_rows)
            for idx, row in non_numeric_assessment_rows.iterrows():
                removal_details["ASSESSMENT_NON_NUMERIC"].append(
                    f"Row {idx}: Assessment number '{row[assessment_column]}' is not numeric"
                )
            invalid_records["non_numeric_assessment"] = non_numeric_assessment_rows
        
        # Duplicate assessment numbers
        duplicate_mask = df[assessment_column].notna() & df.duplicated([assessment_column], keep=False)
        duplicate_assessment_rows = df[duplicate_mask]
        if not duplicate_assessment_rows.empty:
            removal_stats["ASSESSMENT_DUPLICATE"] += len(duplicate_assessment_rows)
            for idx, row in duplicate_assessment_rows.iterrows():
                removal_details["ASSESSMENT_DUPLICATE"].append(
                    f"Row {idx}: Duplicate assessment number '{row[assessment_column]}'"
                )
            invalid_records["duplicate_assessment"] = duplicate_assessment_rows
        
        # Keep only valid assessment numbers
        df = df[~non_numeric_mask & ~duplicate_mask]
    
    # Rule 4: Validate Tax Account Number
    tax_account_column = "tax_account_number"

    if tax_account_column in df.columns:

        # Normalize first
        tax_account_series = (
            df[tax_account_column]
            .astype(str)
            .str.strip()
            .str.replace(".0", "", regex=False)
        )

        # Invalid if non-numeric
        non_numeric_mask = (
            df[tax_account_column].notna()
            & ~tax_account_series.str.match(r'^\d+$')
        )

        non_numeric_tax_account_rows = df[non_numeric_mask].copy()

        if not non_numeric_tax_account_rows.empty:

            non_numeric_tax_account_rows["reason"] = (
                "Tax account number contains non-numeric value"
            )

            removal_stats["TAX_ACCOUNT_NON_NUMERIC"] += len(
                non_numeric_tax_account_rows
            )

            for idx, row in non_numeric_tax_account_rows.iterrows():
                removal_details["TAX_ACCOUNT_NON_NUMERIC"].append(
                    f"Row {idx}: Tax account number "
                    f"'{row[tax_account_column]}' is not numeric"
                )

            invalid_records[
                "non_numeric_tax_account"
            ] = non_numeric_tax_account_rows

        # Remove invalid rows
        df = df[~non_numeric_mask]

        # Convert ONLY valid rows safely
        # Keep as normalized string (business identifier)
        df[tax_account_column] = (
            df[tax_account_column]
            .astype(str)
            .str.strip()
            .str.replace(".0", "", regex=False)
        )

        # Remove fake null strings
        df.loc[
            df[tax_account_column]
            .str.lower()
            .isin(["nan", "none", "null", "<na>", ""]),
            tax_account_column
        ] = pd.NA
    
    # Rule 5: Validate Sales Columns with absolute tolerance of 2
    sales_columns = ["total_sales_income", "exempt_sales", "zero_rated_sales", "add_exempt_and_zero_rated_sales"]
    for col in sales_columns:
        if col in df.columns:
            # Basic validation - must be numeric and non-negative
            # Validation-safe examples:
            #   100 -> valid
            #   100.5 -> valid
            #   numpy.int64(100) -> valid
            #   -100 -> invalid
            #   ABC -> invalid
            numeric_col = pd.to_numeric(
                df[col],
                errors='coerce'
            )

            is_valid = (
                numeric_col.notna() &
                (numeric_col >= 0)
            )
            invalid_sales_rows = df[df[col].notna() & ~is_valid]
        
            if not invalid_sales_rows.empty:
                removal_stats[f"SALES_INVALID_{col.upper()}"] += len(invalid_sales_rows)
                for idx, row in invalid_sales_rows.iterrows():
                    reason = ""
                    numeric_value = numeric_col.get(idx, pd.NA)
                    if pd.isna(numeric_value):
                        reason = f"Row {idx}: {col} value '{row[col]}' is not numeric (type: {type(row[col])})"
                    elif numeric_value < 0:
                        reason = f"Row {idx}: {col} value {row[col]} is negative"
                    removal_details[f"SALES_INVALID_{col.upper()}"].append(reason)
                
                invalid_records[f"invalid_{col}"] = invalid_sales_rows
            
            # Keep valid rows
            df = df[df[col].isna() | is_valid]

    # Additional validation for sum columns with absolute tolerance of 2
    if all(col in df.columns for col in ["exempt_sales", "zero_rated_sales", "add_exempt_and_zero_rated_sales"]):
        # Calculate the sum difference (absolute value)
        sum_diff = (df["exempt_sales"].fillna(0) + df["zero_rated_sales"].fillna(0) - 
                   df["add_exempt_and_zero_rated_sales"].fillna(0)).abs()
    
        # Find rows where absolute difference exceeds tolerance of 2
        invalid_sum_rows = df[sum_diff > 2]
    
        if not invalid_sum_rows.empty:
            # Automatically remove records where tolerance is exceeded
            removal_stats["SALES_SUM_TOLERANCE_EXCEEDED"] += len(invalid_sum_rows)
            for idx, row in invalid_sum_rows.iterrows():
                diff = abs((row['exempt_sales'] + row['zero_rated_sales']) - row['add_exempt_and_zero_rated_sales'])
                removal_details["SALES_SUM_TOLERANCE_EXCEEDED"].append(
                    f"Row {idx}: Sum difference exceeds tolerance (difference={diff})"
                )
            invalid_records["invalid_sum_tolerance"] = invalid_sum_rows
            
            # Remove the records
            df = df[sum_diff <= 2]

    # New DB-level validation (bulk): match gst_fraud_justification AFTER all other rules
    # Keys: tin + tax_account_number + tax_period_year + tax_period_month
    # Case 1: TRUE DB duplicate  → remove + error + count db_duplicates_count
    # Case 2: Financial difference → insert into upload_differences, remove + error + count db_financial_differences_count
    #
    # NOTE: This must run BEFORE the final cleaned_df output is generated.
    db_key_cols = ["tin", "tax_account_number", "tax_period_year", "tax_period_month"]
    gst_financial_cols = [
        "total_sales_income",
        "exempt_sales",
        "zero_rated_sales",
        "add_exempt_and_zero_rated_sales",
        "gst_taxable_sales",
        "output_debits",
        "deferred_import_liabilities",
        "gst_paid_on_inputs",
        "gst_paid_exempt_sales",
        "gst_paid_private",
        "add_private_and_exempt_gst_paid",
        "input_credits",
        "deduct_input_credits",
        "gst_payable",
        "gst_refundable",
        "gst_sec65a_credit_allowable",
    ]

    def _norm_key_series(s: pd.Series) -> pd.Series:
        # Keep comparisons stable across int/float/string representations
        return s.astype(str).str.strip()

    def _normalize_merge_keys_inplace(frame: pd.DataFrame) -> None:
        """
        Apply identical key normalization to BOTH upload and DB frames.
        Matches the required rules:
          - tin / tax_account_number: str, remove trailing '.0', strip
          - tax_period_year/month: numeric -> int (NaN -> 0)
        """
        if frame is None or len(frame) == 0:
            return
        for col in ("tin", "tax_account_number"):
            if col in frame.columns:
                s = (
                    frame[col]
                    .astype(str)
                    .str.replace(".0", "", regex=False)
                    .str.strip()
                )
                # Treat common "missing" string forms as NA
                s_lower = s.str.lower()
                s = s.mask(s_lower.isin(["", "nan", "none", "null", "<na>"]), pd.NA)
                frame[col] = s
        for col in ("tax_period_year", "tax_period_month"):
            if col in frame.columns:
                frame[col] = (
                    pd.to_numeric(frame[col], errors="coerce")
                    .fillna(0)
                    .astype(int)
                )

    def _to_float_series(s: pd.Series) -> pd.Series:
        """
        Robust numeric coercion for uploaded/DB values.
        Handles strings with commas, surrounding whitespace, and parentheses negatives.
        """
        if s is None:
            return pd.Series(dtype="float64")
        if pd.api.types.is_numeric_dtype(s):
            return pd.to_numeric(s, errors="coerce")
        # Normalise common numeric formats: "1,234.50", "(123.4)"
        ss = s.astype(str).str.strip()
        ss = ss.str.replace(",", "", regex=False)
        ss = ss.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
        ss = ss.replace({"": pd.NA, "nan": pd.NA, "none": pd.NA, "null": pd.NA, "<na>": pd.NA})
        return pd.to_numeric(ss, errors="coerce")

    def _norm_fin_series(s: pd.Series) -> pd.Series:
        """
        Mandatory normalization for financial comparisons:
          - numeric coercion (errors -> NaN)
          - NaN -> 0
          - float
          - round(2)
        """
        return _to_float_series(s).fillna(0.0).astype(float).round(2)

    def _chunked(seq, size: int):
        for i in range(0, len(seq), size):
            yield seq[i : i + size]

    def _align_and_append_df(engine, table_name: str, df_to_insert: pd.DataFrame, debug_ctx=None):
        """
        Append df_to_insert to an existing MySQL table, aligning columns to DB order.
        Does not create the table.
        """
        from sqlalchemy import text
        if df_to_insert is None or len(df_to_insert) == 0:
            return
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :tbl "
                    "ORDER BY ORDINAL_POSITION"
                ),
                {"tbl": table_name},
            )
            existing_cols = [row[0] for row in result]

        # Debug prints must never crash validation
        try:
            import os as _os
            if _os.getenv("GST_DB_VALIDATION_DEBUG", "0").strip() in ("1", "true", "TRUE", "yes", "YES"):
                print("\n[GST_DB_VALIDATION_DEBUG] _align_and_append_df()")
                print(f"  table_name={table_name}")
                print(f"  df_to_insert_cols={list(df_to_insert.columns)}")
                print(f"  db_table_cols={existing_cols}")
                if isinstance(debug_ctx, dict) and debug_ctx:
                    for k in [
                        "fin_cols_upload_present",
                        "fin_cols_db_present",
                        "fin_cols_compare",
                        "upload_columns",
                        "db_columns",
                        "first_matched_key",
                        "first_mismatch_key",
                        "mismatch_column",
                        "upload_value",
                        "db_value",
                    ]:
                        if k in debug_ctx:
                            print(f"  {k}={debug_ctx.get(k)}")
        except Exception:
            pass

        # Add missing columns as NULLs and drop extras (safety)
        df_work = df_to_insert.copy()

        # Inject authenticated user_id silently (NULL-safe) for target transactional tables.
        try:
            if table_name in ("upload_conflicts", "upload_differences"):
                from utils.auth_helper import get_authenticated_user_id
                current_user_id = get_authenticated_user_id()
                if "user_id" in existing_cols:
                    df_work["user_id"] = current_user_id
        except Exception:
            pass

        # Numeric cleanup for known conflict table (avoid Decimal/string/scientific notation persistence issues)
        # This does NOT affect validation/classification logic; it only normalizes values being persisted.
        try:
            if table_name == "upload_conflicts":
                for _c in ("previous_value", "current_value"):
                    if _c in df_work.columns:
                        df_work[_c] = pd.to_numeric(df_work[_c], errors="coerce").fillna(0.0).astype(float).round(2)
        except Exception:
            pass

        # Prevent duplicate insertions (within-batch + already-existing in DB) for upload_conflicts.
        # Keyed by: tax_type, tin, tax_period_year, tax_period_month, field_name, source_table
        try:
            if table_name == "upload_conflicts" and len(df_work) > 0:
                dedup_cols = [c for c in ["tax_type", "tin", "tax_period_year", "tax_period_month", "field_name", "source_table"] if c in df_work.columns]
                if dedup_cols:
                    df_work = df_work.drop_duplicates(subset=dedup_cols, keep="first")

                # Bulk anti-join against existing rows in DB to avoid repeated inserts across runs/uploads
                from sqlalchemy import text, bindparam
                tins = df_work["tin"].dropna().astype(str).str.strip().unique().tolist() if "tin" in df_work.columns else []
                years = df_work["tax_period_year"].dropna().unique().tolist() if "tax_period_year" in df_work.columns else []
                months = df_work["tax_period_month"].dropna().unique().tolist() if "tax_period_month" in df_work.columns else []
                fields = df_work["field_name"].dropna().astype(str).unique().tolist() if "field_name" in df_work.columns else []
                tax_types = df_work["tax_type"].dropna().astype(str).unique().tolist() if "tax_type" in df_work.columns else []
                src_tables = df_work["source_table"].dropna().astype(str).unique().tolist() if "source_table" in df_work.columns else []

                if tins and years and months and fields and tax_types and src_tables:
                    q = text(
                        """
                        SELECT tax_type, tin, tax_period_year, tax_period_month, field_name, source_table
                        FROM upload_conflicts
                        WHERE tax_type IN :tax_types
                          AND tin IN :tins
                          AND tax_period_year IN :years
                          AND tax_period_month IN :months
                          AND field_name IN :fields
                          AND source_table IN :source_tables
                        """
                    ).bindparams(
                        bindparam("tax_types", expanding=True),
                        bindparam("tins", expanding=True),
                        bindparam("years", expanding=True),
                        bindparam("months", expanding=True),
                        bindparam("fields", expanding=True),
                        bindparam("source_tables", expanding=True),
                    )
                    with engine.connect() as conn:
                        existing = pd.read_sql(
                            q,
                            conn,
                            params={
                                "tax_types": tax_types,
                                "tins": tins,
                                "years": years,
                                "months": months,
                                "fields": fields,
                                "source_tables": src_tables,
                            },
                        )
                    if existing is not None and len(existing) > 0 and dedup_cols:
                        existing["_dedup_key"] = existing[dedup_cols].astype(str).agg("|".join, axis=1)
                        df_work["_dedup_key"] = df_work[dedup_cols].astype(str).agg("|".join, axis=1)
                        df_work = df_work[~df_work["_dedup_key"].isin(set(existing["_dedup_key"]))]
                        df_work = df_work.drop(columns=["_dedup_key"], errors="ignore")
        except Exception:
            # Never block validation if de-dup fails
            df_work = df_work.drop(columns=["_dedup_key"], errors="ignore")

        for c in existing_cols:
            if c not in df_work.columns:
                df_work[c] = None
        df_work = df_work[[c for c in existing_cols if c in df_work.columns]]
        df_work.to_sql(table_name, con=engine, if_exists="append", index=False)

    if all(c in df.columns for c in db_key_cols) and len(df) > 0:
        try:
            from config.db_config import get_mysql_engine
            from sqlalchemy import text, bindparam

            # Normalize upload keys BEFORE generating any DB lookup keys
            _normalize_merge_keys_inplace(df)

            df["_upload_row_id"] = df.index.astype("int64")
            df["_dbk_tin"] = _norm_key_series(df["tin"])
            df["_dbk_tan"] = _norm_key_series(df["tax_account_number"])
            # After normalization, year/month are ints; keep them as canonical strings
            df["_dbk_yr"] = df["tax_period_year"].astype(int).astype(str)
            df["_dbk_mo"] = df["tax_period_month"].astype(int).astype(str)
            df["_db_key"] = df["_dbk_tin"] + "|" + df["_dbk_tan"] + "|" + df["_dbk_yr"] + "|" + df["_dbk_mo"]

            keys = df["_db_key"].dropna().unique().tolist()
            if keys:
                # Debug: what financial columns are actually present in the standardized upload df?
                # (do this BEFORE we add missing cols as NA so we can see true coverage)
                try:
                    import os as _os
                    if _os.getenv("GST_DB_VALIDATION_DEBUG", "0").strip() in ("1", "true", "TRUE", "yes", "YES"):
                        missing_in_upload = [c for c in gst_financial_cols if c not in df.columns]
                        print("\n[GST_DB_VALIDATION_DEBUG] missing_in_upload_financial_cols=")
                        print(missing_in_upload)
                except Exception:
                    pass

                # Ensure all financial columns exist for consistent comparison.
                # NOTE: We still detect/compare only the intersection later; this prevents KeyError.
                for c in gst_financial_cols:
                    if c not in df.columns:
                        df[c] = pd.NA

                select_cols = db_key_cols + gst_financial_cols
                select_sql = ", ".join(select_cols)

                engine = get_mysql_engine()
                try:
                    db_frames = []
                    # Bulk fetch by IN filters (old backend style): fetch superset, then normalize+match in pandas.
                    tins = df["_dbk_tin"].dropna().unique().tolist()
                    tans = df["_dbk_tan"].dropna().unique().tolist()
                    years = df["tax_period_year"].dropna().unique().tolist()
                    months = df["tax_period_month"].dropna().unique().tolist()

                    if tins and tans and years and months:
                        q = text(f"""
                            SELECT {select_sql}
                            FROM gst_fraud_justification
                            WHERE tin IN :tins
                              AND tax_account_number IN :tans
                              AND tax_period_year IN :years
                              AND tax_period_month IN :months
                        """).bindparams(
                            bindparam("tins", expanding=True),
                            bindparam("tans", expanding=True),
                            bindparam("years", expanding=True),
                            bindparam("months", expanding=True),
                        )

                        with engine.connect() as conn:
                            # Chunk tins to avoid huge IN lists
                            for tins_chunk in _chunked(tins, 1000):
                                db_frames.append(
                                    pd.read_sql(
                                        q,
                                        conn,
                                        params={
                                            "tins": tins_chunk,
                                            "tans": tans,
                                            "years": years,
                                            "months": months,
                                        },
                                    )
                                )
                    db_df = pd.concat(db_frames, ignore_index=True) if db_frames else pd.DataFrame()
                finally:
                    engine.dispose()

                if not db_df.empty:
                    # Standardize DB dataframe column names to match standardized upload dataframe
                    # (lowercase, spaces->underscore, strip trailing underscores).
                    try:
                        db_df.columns = (
                            db_df.columns.astype(str)
                            .str.lower()
                            .str.replace(" ", "_")
                            .str.rstrip("_")
                        )
                    except Exception:
                        pass

                    # Normalize DB keys using EXACT same logic as upload
                    _normalize_merge_keys_inplace(db_df)

                    # Determine which financial columns are actually present on BOTH sides (standardized names).
                    fin_cols_upload_present = [c for c in gst_financial_cols if c in df.columns]
                    fin_cols_db_present = [c for c in gst_financial_cols if c in db_df.columns]
                    fin_cols_compare = [c for c in gst_financial_cols if c in df.columns and c in db_df.columns]

                    # Debug: confirm coverage + ensure deduct_input_credits participates in comparison
                    try:
                        import os as _os
                        if _os.getenv("GST_DB_VALIDATION_DEBUG", "0").strip() in ("1", "true", "TRUE", "yes", "YES"):
                            missing_in_db = [c for c in gst_financial_cols if c not in db_df.columns]
                            print("\n[GST_DB_VALIDATION_DEBUG] missing_in_db_financial_cols=")
                            print(missing_in_db)
                            print("\n[GST_DB_VALIDATION_DEBUG] fin_cols_compare=")
                            print(fin_cols_compare)
                            if "deduct_input_credits" not in fin_cols_compare:
                                print("[GST_DB_VALIDATION_DEBUG] WARNING: deduct_input_credits not in fin_cols_compare")
                    except Exception:
                        pass

                    # STEP 1: Merge ONLY on business keys (can produce multiple DB matches per upload row)
                    db_df["_db_exists"] = 1
                    db_fin = db_df[gst_financial_cols].copy()
                    db_fin.columns = [f"{c}__db" for c in gst_financial_cols]
                    db_join = pd.concat([db_df[db_key_cols + ["_db_exists"]].copy(), db_fin], axis=1)

                    # Optional debug prints (guarded so API output isn't noisy)
                    try:
                        import os as _os
                        if _os.getenv("GST_DB_VALIDATION_DEBUG", "").strip() in ("1", "true", "TRUE", "yes", "YES"):
                            print("\n[GST_DB_VALIDATION_DEBUG] upload merge_keys head:")
                            print(df[db_key_cols].head())
                            print("\n[GST_DB_VALIDATION_DEBUG] db merge_keys head:")
                            print(db_df[db_key_cols].head())
                            print("\n[GST_DB_VALIDATION_DEBUG] fin cols (upload present):")
                            print(fin_cols_upload_present)
                            print("\n[GST_DB_VALIDATION_DEBUG] fin cols (db present):")
                            print(fin_cols_db_present)
                            print("\n[GST_DB_VALIDATION_DEBUG] fin cols (compared):")
                            print(fin_cols_compare)
                            if len(fin_cols_compare) == 0:
                                print("[GST_DB_VALIDATION_DEBUG] WARNING: fin_cols_compare is empty; DB duplicate/conflict classification will be skipped.")
                            print("\n[GST_DB_VALIDATION_DEBUG] upload keys (concat) sample:")
                            print(df["_db_key"].head())
                            try:
                                db_df["_dbg_key"] = (
                                    db_df["tin"].astype(str).str.strip()
                                    + "|"
                                    + db_df["tax_account_number"].astype(str).str.strip()
                                    + "|"
                                    + db_df["tax_period_year"].astype(int).astype(str)
                                    + "|"
                                    + db_df["tax_period_month"].astype(int).astype(str)
                                )
                                print("\n[GST_DB_VALIDATION_DEBUG] db keys (concat) sample:")
                                print(db_df["_dbg_key"].head())
                            except Exception:
                                pass
                            print("\n[GST_DB_VALIDATION_DEBUG] upload dtypes:")
                            print(df[db_key_cols].dtypes)
                            print("\n[GST_DB_VALIDATION_DEBUG] db dtypes:")
                            print(db_df[db_key_cols].dtypes)
                    except Exception:
                        pass

                    merged = df.merge(db_join, on=db_key_cols, how="left")

                    matched_mask = merged["_db_exists"].notna()

                    # STEP 2: For matched rows ONLY, compare ALL financial columns AFTER normalization
                    # (coerce -> fillna(0) -> float -> round(2)).
                    # If we have no comparable financial columns, do NOT classify anything as duplicate/conflict
                    # (prevents `all([])==True` style bugs).
                    if len(fin_cols_compare) == 0:
                        merged["_has_fin_diff"] = False
                        merged["_no_fin_diff"] = False
                        dup_ids = []
                        diff_ids = []
                    else:
                        fin_diff_pair = pd.Series(False, index=merged.index)
                        for c in fin_cols_compare:
                            left = _norm_fin_series(merged[c])
                            right = _norm_fin_series(merged[f"{c}__db"])
                            fin_diff_pair = fin_diff_pair | (left != right)

                        merged["_has_fin_diff"] = matched_mask & fin_diff_pair
                        merged["_no_fin_diff"] = matched_mask & ~fin_diff_pair

                    # Debug: if everything is classified as "no diff", print one key + one column comparison
                    try:
                        import os as _os
                        if _os.getenv("GST_DB_VALIDATION_DEBUG", "").strip() in ("1", "true", "TRUE", "yes", "YES"):
                            mcnt = int(matched_mask.sum())
                            dcnt = int((merged["_has_fin_diff"]).sum())
                            ndcnt = int((merged["_no_fin_diff"]).sum())
                            print(f"\n[GST_DB_VALIDATION_DEBUG] matched_pairs={mcnt} fin_diff_pairs={dcnt} no_diff_pairs={ndcnt}")
                            if mcnt > 0 and dcnt == 0 and len(fin_cols_compare) > 0:
                                c0 = fin_cols_compare[0]
                                r0 = merged[matched_mask].head(1).iloc[0]
                                ul0 = float(_norm_fin_series(pd.Series([r0.get(c0)])).iloc[0])
                                db0 = float(_norm_fin_series(pd.Series([r0.get(f"{c0}__db")])).iloc[0])
                                print(f"[GST_DB_VALIDATION_DEBUG] sample compare {c0}: upload={ul0} db={db0}")
                    except Exception:
                        pass

                    # Optional deep diff debug: prints first differing key with per-column values
                    try:
                        import os as _os
                        if _os.getenv("GST_DB_VALIDATION_DEBUG", "").strip() in ("1", "true", "TRUE", "yes", "YES"):
                            sample = merged[merged["_has_fin_diff"]].head(1)
                            if len(sample) > 0:
                                r = sample.iloc[0]
                                print("\n[GST_DB_VALIDATION_DEBUG] first fin-diff key:")
                                print({k: r.get(k) for k in db_key_cols})
                                for c in fin_cols_compare:
                                    ul = float(_norm_fin_series(pd.Series([r.get(c)])).iloc[0])
                                    dbv = float(_norm_fin_series(pd.Series([r.get(f"{c}__db")])).iloc[0])
                                    if ul != dbv:
                                        print(f"  {c}: upload={ul} db={dbv} diff={ul-dbv}")
                            else:
                                sample2 = merged[matched_mask].head(1)
                                if len(sample2) > 0:
                                    r = sample2.iloc[0]
                                    print("\n[GST_DB_VALIDATION_DEBUG] first matched key has NO fin diff after normalization:")
                                    print({k: r.get(k) for k in db_key_cols})
                    except Exception:
                        pass

                    # Aggregate back to one decision per upload row (handles multiple DB rows per key)
                    # only when we had comparable financial columns.
                    if len(fin_cols_compare) > 0:
                        agg = (
                            merged.groupby("_upload_row_id", dropna=False)
                            .agg(
                                _any_db_match=("_db_exists", lambda s: s.notna().any()),
                                _any_no_fin_diff=("_no_fin_diff", "any"),
                                _any_fin_diff=("_has_fin_diff", "any"),
                            )
                            .reset_index()
                        )
                        # Conflict takes precedence: if ANY matched DB row differs financially, classify as conflict.
                        diff_ids = agg.loc[agg["_any_db_match"] & agg["_any_fin_diff"], "_upload_row_id"].tolist()
                        dup_ids = agg.loc[agg["_any_db_match"] & ~agg["_any_fin_diff"] & agg["_any_no_fin_diff"], "_upload_row_id"].tolist()

                    if dup_ids:
                        dup_rows = df[df["_upload_row_id"].isin(dup_ids)].copy()
                        dup_rows["reason"] = "Duplicate GST record already exists in gst_fraud_justification"
                        invalid_records["db_duplicates"] = dup_rows.drop(
                            columns=["_upload_row_id", "_dbk_tin", "_dbk_tan", "_dbk_yr", "_dbk_mo", "_db_key"],
                            errors="ignore",
                        )
                        removal_stats["DB_DUPLICATE"] += int(len(dup_rows))
                        for idx, _ in dup_rows.iterrows():
                            removal_details["DB_DUPLICATE"].append(
                                f"Row {idx}: Duplicate GST record already exists in gst_fraud_justification"
                            )
                        df = df[~df["_upload_row_id"].isin(dup_ids)]

                    if diff_ids:
                        diff_upload_rows = df[df["_upload_row_id"].isin(diff_ids)].copy()
                        diff_upload_rows["reason"] = "Financial differences found against gst_fraud_justification"
                        invalid_records["db_financial_differences"] = diff_upload_rows.drop(
                            columns=["_upload_row_id", "_dbk_tin", "_dbk_tan", "_dbk_yr", "_dbk_mo", "_db_key"],
                            errors="ignore",
                        )
                        removal_stats["DB_FINANCIAL_DIFFERENCE"] += int(len(diff_upload_rows))
                        for idx, _ in diff_upload_rows.iterrows():
                            removal_details["DB_FINANCIAL_DIFFERENCE"].append(
                                f"Row {idx}: Financial differences found against gst_fraud_justification"
                            )

                        # Insert comparison rows into upload_differences (one row per upload row)
                        try:
                            # Pick a representative DB row per upload row (first matched row)
                            rep = (
                                merged[merged["_upload_row_id"].isin(diff_ids) & matched_mask]
                                .sort_values(["_upload_row_id"])
                                .groupby("_upload_row_id", as_index=False)
                                .first()
                            )
                            # Compute changed columns + change_summary using abs(diff) > 10 (old behavior)
                            try:
                                summaries = []
                                changed_cols = []
                                totals_changed = []
                                total_pos = []
                                total_neg = []
                                for _, rr in rep.iterrows():
                                    summary = {}
                                    cols = []
                                    pos = 0.0
                                    neg = 0.0
                                    for c in gst_financial_cols:
                                        new_val = float(_norm_fin_series(pd.Series([rr.get(c)])).iloc[0])
                                        old_val = float(_norm_fin_series(pd.Series([rr.get(f"{c}__db")])).iloc[0])
                                        diff = new_val - old_val
                                        if diff != 0:
                                            summary[c] = {"old": old_val, "new": new_val, "difference": diff}
                                            cols.append(c)
                                            if diff > 0:
                                                pos += diff
                                            else:
                                                neg += diff
                                    summaries.append(summary)
                                    changed_cols.append(",".join(cols))
                                    totals_changed.append(len(cols))
                                    total_pos.append(pos)
                                    total_neg.append(neg)

                                rep["changed_columns"] = changed_cols
                                rep["change_json"] = summaries
                                rep["total_fields_changed"] = totals_changed
                                rep["total_positive_difference"] = total_pos
                                rep["total_negative_difference"] = total_neg
                            except Exception:
                                rep["changed_columns"] = None

                            # Persist per-record changed-field count into removed rows (for API summary)
                            try:
                                if "total_fields_changed" in rep.columns:
                                    fields_map = dict(zip(rep["_upload_row_id"].tolist(), rep["total_fields_changed"].tolist()))
                                    diff_upload_rows["db_financial_difference_fields_count"] = (
                                        diff_upload_rows["_upload_row_id"].map(fields_map).fillna(0).astype(int)
                                    )
                                    invalid_records["db_financial_differences"] = diff_upload_rows.drop(
                                        columns=["_upload_row_id", "_dbk_tin", "_dbk_tan", "_dbk_yr", "_dbk_mo", "_db_key"],
                                        errors="ignore",
                                    )
                            except Exception:
                                pass
                            # Persist to legacy/production table: upload_conflicts
                            # One row per differing field (matches old backend behavior).
                            conflicts_rows = []
                            for _, rr in rep.iterrows():
                                try:
                                    changes = rr.get("change_json") or {}
                                    if not isinstance(changes, dict):
                                        changes = {}
                                except Exception:
                                    changes = {}

                                for field_name, meta in (changes or {}).items():
                                    try:
                                        prev_val = meta.get("old")
                                        curr_val = meta.get("new")
                                    except Exception:
                                        prev_val = None
                                        curr_val = None

                                    conflicts_rows.append({
                                        "tax_type": "GST",
                                        "tin": str(rr.get("tin") if rr.get("tin") is not None else "").strip(),
                                        "tax_account_number": rr.get("tax_account_number", None),
                                        "taxpayer_name": rr.get("taxpayer_name", None),
                                        "tax_period_year": rr.get("tax_period_year", None),
                                        "tax_period_month": rr.get("tax_period_month", None),
                                        "assessment_number": rr.get("assessment_number", None),
                                        "field_name": _sanitize_field_name(field_name),
                                        "previous_value": prev_val,
                                        "current_value": curr_val,
                                        "status": 0,
                                        "source_table": "gst_fraud_justification",
                                        "source_record_id": rr.get("id__db", None),
                                        "upload_batch_id": rr.get("upload_batch_id__db", None),
                                    })

                            to_ins = pd.DataFrame(conflicts_rows)
                            engine2 = get_mysql_engine()
                            try:
                                debug_ctx = None
                                try:
                                    import os as _os
                                    if _os.getenv("GST_DB_VALIDATION_DEBUG", "0").strip() in ("1", "true", "TRUE", "yes", "YES"):
                                        # Build the exact requested debug items
                                        debug_ctx = {
                                            "fin_cols_upload_present": fin_cols_upload_present,
                                            "fin_cols_db_present": fin_cols_db_present,
                                            "fin_cols_compare": fin_cols_compare,
                                            "upload_columns": list(df.columns),
                                            "db_columns": list(db_df.columns),
                                        }
                                        # First matched composite key
                                        try:
                                            m0 = merged[matched_mask].head(1)
                                            if len(m0) > 0:
                                                r0 = m0.iloc[0]
                                                debug_ctx["first_matched_key"] = {k: r0.get(k) for k in db_key_cols}
                                        except Exception:
                                            pass
                                        # First mismatch key + column/value
                                        try:
                                            m1 = merged[merged["_has_fin_diff"]].head(1)
                                            if len(m1) > 0:
                                                r1 = m1.iloc[0]
                                                debug_ctx["first_mismatch_key"] = {k: r1.get(k) for k in db_key_cols}
                                                for c in fin_cols_compare:
                                                    uv = float(_norm_fin_series(pd.Series([r1.get(c)])).iloc[0])
                                                    dv = float(_norm_fin_series(pd.Series([r1.get(f"{c}__db")])).iloc[0])
                                                    if uv != dv:
                                                        debug_ctx["mismatch_column"] = c
                                                        debug_ctx["upload_value"] = uv
                                                        debug_ctx["db_value"] = dv
                                                        break
                                        except Exception:
                                            pass
                                except Exception:
                                    debug_ctx = None

                                # Explicit pre-insert debug (never crash)
                                try:
                                    import os as _os
                                    if _os.getenv("GST_DB_VALIDATION_DEBUG", "0").strip() in ("1", "true", "TRUE", "yes", "YES"):
                                        try:
                                            # Required: target table + composite key + differing column/value
                                            key_out = None
                                            if isinstance(debug_ctx, dict):
                                                key_out = debug_ctx.get("first_mismatch_key") or debug_ctx.get("first_matched_key")
                                            print("\n[GST_DB_VALIDATION_DEBUG] inserting financial-difference rows")
                                            print("  target_table=upload_conflicts")
                                            print(f"  key={key_out}")
                                            if isinstance(debug_ctx, dict):
                                                print(f"  mismatch_column={debug_ctx.get('mismatch_column')}")
                                                print(f"  upload_value={debug_ctx.get('upload_value')}")
                                                print(f"  db_value={debug_ctx.get('db_value')}")
                                            try:
                                                print("  payload_preview=")
                                                print(to_ins[["tax_type","tin","tax_period_year","tax_period_month","field_name","previous_value","current_value","source_table"]].head(10))
                                            except Exception:
                                                pass
                                        except Exception:
                                            pass
                                except Exception:
                                    pass

                                # Populate source_record_id + upload_batch_id by resolving the matched
                                # gst_fraud_justification row (approval workflow integrity).
                                try:
                                    def _is_ignored_conflict_field(_fn: object) -> bool:
                                        try:
                                            _n = str(_fn or "").strip().lower().replace(" ", "")
                                        except Exception:
                                            return False
                                        return _n in ("unnamed:_0", "unnamed:0", "unnamed_0")

                                    def _sanitize_field_name(_fn: object):
                                        if _fn is None:
                                            return _fn
                                        try:
                                            _s = str(_fn).strip()
                                        except Exception:
                                            return _fn
                                        if not _s:
                                            return _s
                                        _s = _s.replace("'", "")
                                        _s = _s.replace(" ", "_")
                                        while "__" in _s:
                                            _s = _s.replace("__", "_")
                                        return _s.strip("_")

                                    def _resolve_source_meta_for_conflict_row(_row: dict):
                                        try:
                                            fn = _sanitize_field_name("" if _row.get("field_name") is None else str(_row.get("field_name")).strip())
                                            if not fn or _is_ignored_conflict_field(fn):
                                                return (None, None, None)

                                            tin_s = "" if _row.get("tin") is None else str(_row.get("tin")).strip()
                                            if tin_s.endswith(".0") and tin_s[:-2].isdigit():
                                                tin_s = tin_s[:-2]
                                            try:
                                                yr_i = int(float(_row.get("tax_period_year"))) if _row.get("tax_period_year") is not None else None
                                            except Exception:
                                                yr_i = None
                                            try:
                                                mo_i = int(float(_row.get("tax_period_month"))) if _row.get("tax_period_month") is not None else None
                                            except Exception:
                                                mo_i = None
                                            assess_s = "" if _row.get("assessment_number") is None else str(_row.get("assessment_number")).strip()
                                            if assess_s.endswith(".0") and assess_s[:-2].isdigit():
                                                assess_s = assess_s[:-2]
                                            try:
                                                prev_f = float(_row.get("previous_value")) if _row.get("previous_value") is not None else None
                                            except Exception:
                                                try:
                                                    prev_f = float(str(_row.get("previous_value")).strip())
                                                except Exception:
                                                    prev_f = None

                                            from sqlalchemy import text as _text
                                            with engine2.connect() as _conn:
                                                cols_res = _conn.execute(
                                                    _text(
                                                        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                                                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
                                                    ),
                                                    {"t": "gst_fraud_justification"},
                                                )
                                                cols = set((r[0] or "").lower() for r in cols_res.fetchall())
                                                if fn.lower() not in cols:
                                                    return (None, None, None)

                                                sel_cols = ["id"]
                                                has_batch = "upload_batch_id" in cols
                                                if has_batch:
                                                    sel_cols.append("upload_batch_id")
                                                # Resolve taxpayer name (GST/SWT use taxpayer_name; CIT uses taxpayer)
                                                has_name = ("taxpayer_name" in cols) or ("taxpayer" in cols)
                                                if "taxpayer_name" in cols:
                                                    sel_cols.append("taxpayer_name")
                                                elif "taxpayer" in cols:
                                                    sel_cols.append("taxpayer")
                                                # Select dynamic field value for python-side comparison (do not compare in SQL).
                                                sel_cols.append(f"`{fn}` AS _db_val")

                                                fn_q = f"`{fn}`"
                                                q = _text(
                                                    f"SELECT {', '.join(sel_cols)} FROM `gst_fraud_justification` "
                                                    f"WHERE tin = :tin AND tax_period_year = :yr AND tax_period_month = :mo "
                                                    f"AND assessment_number = :assess "
                                                    f"ORDER BY id DESC LIMIT 5"
                                                )
                                                rows = _conn.execute(
                                                    q,
                                                    {"tin": tin_s, "yr": yr_i, "mo": mo_i, "assess": assess_s},
                                                ).fetchall()
                                                if not rows:
                                                    return (None, None, None)
                                                def _normalize(v):
                                                    try:
                                                        if v is None or (isinstance(v, str) and v.strip() == ""):
                                                            v = 0
                                                        return round(float(v), 2)
                                                    except Exception:
                                                        try:
                                                            return str(v).strip()
                                                        except Exception:
                                                            return ""
                                                want = _normalize(prev_f)
                                                has_batch = "upload_batch_id" in cols
                                                for row in rows:
                                                    try:
                                                        db_val = row[-1] if len(row) >= 2 else None
                                                        if _normalize(db_val) == want:
                                                            src_id = row[0] if len(row) > 0 else None
                                                            batch_id = row[1] if (has_batch and len(row) >= 3) else None
                                                            tp_name = None
                                                            if has_name:
                                                                try:
                                                                    tp_name = row[-2]
                                                                except Exception:
                                                                    tp_name = None
                                                            return (src_id, batch_id, tp_name)
                                                    except Exception:
                                                        continue
                                                return (None, None, None)
                                        except Exception:
                                            return (None, None, None)

                                    if "source_record_id" in to_ins.columns or "upload_batch_id" in to_ins.columns:
                                        src_ids = []
                                        batch_ids = []
                                        tp_names = []
                                        for _ in to_ins.to_dict(orient="records"):
                                            sid, bid, tpn = _resolve_source_meta_for_conflict_row(_)
                                            src_ids.append(sid)
                                            batch_ids.append(bid)
                                            tp_names.append(tpn)
                                        if "source_record_id" in to_ins.columns:
                                            to_ins["source_record_id"] = src_ids
                                        if "upload_batch_id" in to_ins.columns:
                                            to_ins["upload_batch_id"] = batch_ids
                                        if "taxpayer_name" in to_ins.columns:
                                            # Prefer resolved name, otherwise keep existing value.
                                            try:
                                                existing = to_ins.get("taxpayer_name")
                                                to_ins["taxpayer_name"] = [
                                                    (tp_names[i] if tp_names[i] not in (None, "") else (existing.iloc[i] if existing is not None else None))
                                                    for i in range(len(tp_names))
                                                ]
                                            except Exception:
                                                to_ins["taxpayer_name"] = tp_names
                                except Exception:
                                    pass

                                _align_and_append_df(engine2, "upload_conflicts", to_ins, debug_ctx=debug_ctx)
                            finally:
                                engine2.dispose()
                        except Exception:
                            pass

                        df = df[~df["_upload_row_id"].isin(diff_ids)]

            df.drop(
                columns=["_upload_row_id", "_dbk_tin", "_dbk_tan", "_dbk_yr", "_dbk_mo", "_db_key"],
                inplace=True,
                errors="ignore",
            )

        except Exception:
            df.drop(
                columns=["_upload_row_id", "_dbk_tin", "_dbk_tan", "_dbk_yr", "_dbk_mo", "_db_key"],
                inplace=True,
                errors="ignore",
            )
            pass
    
    # Store cleaned and removed data in dataframes
    cleaned_data_df = df
    removed_data_df = pd.concat(invalid_records.values(), ignore_index=True) if invalid_records else pd.DataFrame()
    
    # Log summary statistics
    logging.info("=== GST Validation Summary ===")
    logging.info(f"Total records removed: {sum(removal_stats.values())}")
    for rule, count in removal_stats.items():
        logging.info(f"  {rule}: {count} records removed")

    # Log detailed removal reasons
    logging.info("=== Detailed Removal Log ===")
    for rule, details in removal_details.items():
        logging.info(f"--- {rule} ---")
        for detail in details:
            logging.info(detail)

    logging.info("=== Validation Complete ===")
    logging.info(f"Records retained: {len(cleaned_data_df)}")
    logging.info(f"Records removed: {len(removed_data_df)}")
    # Bug 2 fix: normalize nullable integer columns to avoid PyArrow threading errors
    for col in cleaned_data_df.columns:
        if pd.api.types.is_extension_array_dtype(cleaned_data_df[col]):
            cleaned_data_df[col] = cleaned_data_df[col].astype(object)

    # Force identifier columns to string
    identifier_cols = [
        "tin",
        "tax_account_number",
        "assessment_number"
    ]

    def _normalize_identifier_columns(dataframe):
        if dataframe is None or dataframe.empty:
            return dataframe
        for col in identifier_cols:
            if col in dataframe.columns:
                dataframe[col] = (
                    dataframe[col]
                    .astype(str)
                    .str.strip()
                    .str.replace(".0", "", regex=False)
                    .replace(
                        {
                            "nan": pd.NA,
                            "none": pd.NA,
                            "null": pd.NA,
                            "<na>": pd.NA,
                            "": pd.NA,
                        }
                    )
                )
        return dataframe

    # Validation-safe examples:
    #   TIN: 123456789 -> valid
    #   TIN: ABC123456 -> invalid
    #   TIN: 111111111 -> invalid
    #   TIN: 012345678 -> invalid
    #   TIN: 1234567890 -> invalid
    #   tax_account_number: 123456 -> valid
    #   tax_account_number: 123.0 -> normalize to 123
    #   tax_account_number: ABC123 -> invalid
    cleaned_data_df = _normalize_identifier_columns(cleaned_data_df)

    if not removed_data_df.empty:
        for col in removed_data_df.columns:
            if pd.api.types.is_extension_array_dtype(removed_data_df[col]):
                removed_data_df[col] = removed_data_df[col].astype(object)
        removed_data_df = _normalize_identifier_columns(removed_data_df)

    # Save cleaned data
    cleaned_data_df.to_parquet("gst_cleaned_data.parquet", index=False)

    for col in identifier_cols:
        if col in cleaned_data_df.columns:
            cleaned_data_df[col] = (
                cleaned_data_df[col]
                .astype(str)
                .replace("nan", pd.NA)
            )

    # Save invalid data
    if not removed_data_df.empty:
        removed_data_df.to_parquet("gst_removed_data.parquet", index=False)
        for col in identifier_cols:
            if col in removed_data_df.columns:
                removed_data_df[col] = (
                    removed_data_df[col]
                    .astype(str)
                    .replace("nan", pd.NA)
                )

    # Release the file handle so Windows can move gst_validation_log.txt
    # to final_output/ without hitting WinError 32 (file in use).
    _root = logging.getLogger()
    for _h in _root.handlers[:]:
        _root.removeHandler(_h)
        _h.close()

    return cleaned_data_df, removed_data_df

# Helper functions for registration data
def clean_columns(df):
    """Convert column names to lowercase and replace spaces with underscores"""
    df.columns = df.columns.str.lower().str.replace(' ', '_')
    return df

def get_taxpayer_name_col(df):
    """Identify the taxpayer name column in a dataframe"""
    possible_names = ['taxpayer', 'taxpayername', 'taxpayer_name', 'tax_payer', 'tax_payer_name', 'taxpayername']
    for col in df.columns:
        if col.lower().replace('_', '') in [name.lower().replace('_', '') for name in possible_names]:
            return col
    return None

def load_and_clean_registration_data(filepath, sheet_names=None):
    """Load and clean registration data from single or multiple sheets"""
    if sheet_names:  # For multi-sheet files
        dfs = []
        for sheet in sheet_names:
            df = pd.read_excel(filepath, sheet_name=sheet)
            dfs.append(clean_columns(df))
        df = pd.concat(dfs, ignore_index=True)
    else:  # For single-sheet files
        df = pd.read_excel(filepath)
        df = clean_columns(df)
    #print(f"  [DEBUG] Registration columns after clean_columns: {list(df.columns)}")  # ← ADD THIS
    # Identify and standardize taxpayer name column
    taxpayer_col = get_taxpayer_name_col(df)
    #print(f"  [DEBUG] get_taxpayer_name_col returned: {taxpayer_col}")  # ← ADD THIS
    if taxpayer_col and taxpayer_col != 'taxpayer_name':
        df = df.rename(columns={taxpayer_col: 'taxpayer_name'})
    
    return df
