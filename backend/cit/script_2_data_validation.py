    # script_2_data_validation
import pandas as pd
import numpy as np
import warnings
import os
from collections import defaultdict
import logging
from tqdm import tqdm
import time
import multiprocessing as mp
from functools import partial
from cit.runtime_context import get_artifact_path

warnings.filterwarnings("ignore")
pd.options.display.max_columns=None
pd.options.display.float_format = '{:.2f}'.format


def _artifact_path(env_name, default_name):
        return get_artifact_path(env_name, default_name, os.getcwd())

def parallel_validate_tin(tin_series_chunk):
        """Parallel processing function for TIN validation"""
        results = []
        for tin_str in tin_series_chunk:
            if pd.isna(tin_str):
                results.append(('NULL', 'TIN is null/empty'))
            elif not isinstance(tin_str, str):
                results.append(('INVALID', 'TIN is not string type'))
            elif len(tin_str) != 9:
                results.append(('WRONG_LENGTH', f'TIN has wrong length ({len(tin_str)} digits, must be 9)'))
            elif tin_str.startswith('0'):
                results.append(('STARTS_ZERO', 'TIN starts with zero'))
            elif len(set(tin_str)) == 1:
                results.append(('ALL_SAME', 'TIN has all identical digits'))
            else:
                # Check for continuous sequences more efficiently
                digits = list(map(int, tin_str))
                diffs = [digits[i+1] - digits[i] for i in range(len(digits)-1)]
                if all(abs(d) == 1 for d in diffs) and len(set(diffs)) == 1:
                    direction = "increasing" if diffs[0] > 0 else "decreasing"
                    results.append(('CONTINUOUS', f'TIN is a continuous {direction} sequence'))
                else:
                    results.append(('VALID', None))
        return results

def validate_and_clean_cit_data(df):
        """
        Cleans and validates a CIT dataset based on predefined rules.
        Saves the cleaned data and removed invalid data into separate files.
        Prints detailed summary of removed records with counts and reasons.
        
        Args:
            df (pd.DataFrame): Preprocessed CIT data
            
        Returns:
            tuple:
              cleaned_df (pd.DataFrame): validated rows
              removed_data_df (pd.DataFrame): removed/invalid rows with `reason`
              removal_details (list[dict]): row-level error objects for API
        """
        print("--- Step 1: Validating and cleaning CIT data ---")
        
        # Configure logging
        logging.basicConfig(filename="cit_validation_log.txt", level=logging.INFO, format='%(asctime)s - %(message)s')
        
        # Dictionary to store removal statistics and reasons
        removal_stats = defaultdict(int)
        removal_details = []
        invalid_records_list = []  # Store invalid records in list for faster concatenation
        
        original_shape = df.shape
        print(f"Starting with {original_shape[0]:,} records")
        
        # Make a copy for modifications
        df = df.copy()
        
        def _row_number(idx, row):
            try:
                if isinstance(row, dict):
                    v = row.get('_row')
                else:
                    v = row.get('_row') if hasattr(row, 'get') else None
                if v is not None and not pd.isna(v):
                    return int(v)
            except Exception:
                pass
            try:
                return int(idx) + 1
            except Exception:
                return ''

        def _tin_str(v):
            if v is None or pd.isna(v):
                return ''
            s = str(v).strip()
            if s.endswith('.0'):
                s = s[:-2]
            return s

        # Rule 1: Validate TIN with comprehensive checks
        tin_column = "tin"
        if tin_column in df.columns:
            print("\n1. Validating TIN numbers...")

            # Preserve original TIN values for reason construction
            tin_raw = df[tin_column].copy()
            tin_str_series = (
                tin_raw
                .astype(str)
                .str.replace(r'\.0$', '', regex=True)
                .str.strip()
            )
            tin_str_series = tin_str_series.replace({'nan': pd.NA, 'NaN': pd.NA, 'None': pd.NA, '': pd.NA})
            
            # Create progress bar for TIN validation
            with tqdm(total=df.shape[0], desc="Processing TINs", unit="record", leave=False) as pbar:
                # Convert TIN to numeric first for efficiency
                df[tin_column] = pd.to_numeric(df[tin_column], errors='coerce')
                
                # Pre-allocate result arrays for better performance
                is_null = df[tin_column].isna()
                wrong_length = pd.Series(False, index=df.index)
                starts_with_zero = pd.Series(False, index=df.index)
                all_same_digits = pd.Series(False, index=df.index)
                is_continuous = pd.Series(False, index=df.index)
                
                # Process non-null TINs
                valid_mask = df[tin_column].notna()
                valid_indices = df[valid_mask].index
                tin_ints = df.loc[valid_mask, tin_column].astype('Int64')
                tin_strings = tin_ints.astype(str)
                
                # Vectorized operations where possible
                # Check length
                length_check = tin_strings.str.len() != 9
                wrong_length.loc[valid_indices[length_check]] = True
                
                # Check if starts with zero
                starts_zero = tin_strings.str.startswith('0')
                starts_with_zero.loc[valid_indices[starts_zero]] = True
                
                # Check for all same digits (using set operations)
                def check_all_same(s):
                    return len(set(s)) == 1
                
                # Apply in batches for better memory usage
                batch_size = 10000
                for i in tqdm(range(0, len(tin_strings), batch_size), 
                            desc="Checking digit patterns", 
                            unit="batch",
                            leave=False):
                    batch = tin_strings.iloc[i:i+batch_size]
                    mask = batch.apply(check_all_same)
                    all_same_digits.loc[valid_indices[i:i+batch_size][mask]] = True
                    pbar.update(len(batch))
                
                # Check for continuous sequences (optimized)
                def check_continuous(s):
                    if len(s) != 9:
                        return False
                    digits = [int(d) for d in s]
                    diffs = [digits[i+1] - digits[i] for i in range(len(digits)-1)]
                    return all(d == diffs[0] for d in diffs) and abs(diffs[0]) == 1
                
                for i in tqdm(range(0, len(tin_strings), batch_size), 
                            desc="Checking sequences", 
                            unit="batch",
                            leave=False):
                    batch = tin_strings.iloc[i:i+batch_size]
                    mask = batch.apply(check_continuous)
                    is_continuous.loc[valid_indices[i:i+batch_size][mask]] = True
                    pbar.update(len(batch))
            
            # Combine all invalid conditions
            invalid_tin_mask = (is_null | wrong_length | starts_with_zero | 
                            all_same_digits | is_continuous)
            
            # Count different types of TIN violations
            invalid_indices = df[invalid_tin_mask].index
            
            print(f"  Valid TINs: {df.shape[0] - invalid_tin_mask.sum():,}")
            print(f"  Invalid TINs: {invalid_tin_mask.sum():,}")
            
            # Create detailed removal information
            if invalid_tin_mask.any():
                invalid_rows = df[invalid_tin_mask].copy()

                # Exact ML reason strings from parallel_validate_tin()
                try:
                    codes_msgs = parallel_validate_tin(tin_str_series.tolist())
                    if isinstance(codes_msgs, list) and len(codes_msgs) == len(df):
                        msg_map = {}
                        for _idx, (code, msg) in zip(df.index, codes_msgs):
                            if msg is None or (isinstance(msg, float) and pd.isna(msg)):
                                continue
                            if code is None:
                                continue
                            if str(code).upper() == 'VALID':
                                continue
                            msg_map[_idx] = str(msg).strip()

                        invalid_rows['reason'] = invalid_rows.index.map(lambda i: msg_map.get(i, '')).astype(str)
                except Exception:
                    pass

                if 'reason' not in invalid_rows.columns:
                    invalid_rows['reason'] = ''

                for _idx, _row in invalid_rows.iterrows():
                    reason_txt = '' if pd.isna(_row.get('reason')) else str(_row.get('reason')).strip()
                    removal_details.append({
                        'row': _row_number(_idx, _row),
                        'tin': _tin_str(_row.get('tin')),
                        'column': 'TIN',
                        'reason': reason_txt if reason_txt else 'TIN validation failed',
                    })

                invalid_records_list.append(invalid_rows)
                
                # Count by violation type
                removal_stats["TIN_NULL"] = is_null.sum()
                removal_stats["TIN_WRONG_LENGTH"] = wrong_length.sum()
                removal_stats["TIN_STARTS_WITH_ZERO"] = starts_with_zero.sum()
                removal_stats["TIN_ALL_DIGITS_SAME"] = all_same_digits.sum()
                removal_stats["TIN_CONTINUOUS_SEQUENCE"] = is_continuous.sum()
                
                # Keep only valid TINs
                df = df[~invalid_tin_mask]
        
        # Rule 2: Validate Assessment Number
        assessment_column = "assessment_no"
        if assessment_column in df.columns:
            print("\n2. Validating assessment numbers...")
            
            # Check for non-numeric values
            with tqdm(total=df.shape[0], desc="Checking assessment numbers", unit="record", leave=False) as pbar:
                # Use vectorized string check
                assessment_str = df[assessment_column].astype(str)
                non_numeric_mask = assessment_str.str.match(r'^\d+$') == False
                
                # Update progress
                pbar.update(df.shape[0])
            
            # Check for duplicates
            with tqdm(total=df.shape[0], desc="Checking duplicates", unit="record", leave=False) as pbar:
                duplicate_mask = df.duplicated(subset=[assessment_column], keep=False)
                pbar.update(df.shape[0])
            
            # Combine masks
            invalid_assessment_mask = non_numeric_mask | duplicate_mask
            
            if invalid_assessment_mask.any():
                invalid_rows = df[invalid_assessment_mask].copy()

                invalid_rows = invalid_rows.copy()
                invalid_rows['reason'] = ''
                # Non-numeric assessment
                try:
                    for _idx, _row in invalid_rows[non_numeric_mask.loc[invalid_rows.index]].iterrows():
                        v = '' if pd.isna(_row.get(assessment_column)) else str(_row.get(assessment_column))
                        reason_txt = f"Assessment number '{v}' is not numeric"
                        invalid_rows.at[_idx, 'reason'] = reason_txt
                        removal_details.append({
                            'row': _row_number(_idx, _row),
                            'tin': _tin_str(_row.get('tin')),
                            'column': 'AssessmentNumber',
                            'reason': reason_txt,
                        })
                except Exception:
                    pass

                # Duplicate assessment
                try:
                    dup_idxs = invalid_rows[duplicate_mask.loc[invalid_rows.index]].index
                    for _idx in dup_idxs:
                        _row = invalid_rows.loc[_idx]
                        v = '' if pd.isna(_row.get(assessment_column)) else str(_row.get(assessment_column))
                        reason_txt = "Duplicate assessment number found"
                        prev = str(invalid_rows.at[_idx, 'reason']).strip()
                        invalid_rows.at[_idx, 'reason'] = (prev + '; ' + reason_txt).strip('; ').strip()
                        removal_details.append({
                            'row': _row_number(_idx, _row),
                            'tin': _tin_str(_row.get('tin')),
                            'column': 'AssessmentNumber',
                            'reason': reason_txt if v == '' else reason_txt,
                        })
                except Exception:
                    pass

                invalid_records_list.append(invalid_rows)
                
                removal_stats["ASSESSMENT_NON_NUMERIC"] = non_numeric_mask.sum()
                removal_stats["ASSESSMENT_DUPLICATE"] = duplicate_mask.sum()
                
                df = df[~invalid_assessment_mask]
            
            print(f"  Valid assessments: {df.shape[0]:,}")
            print(f"  Invalid assessments: {invalid_assessment_mask.sum():,}")
        
        # Rule 3: Validate Tax Account Number
        tax_account_column = "tax_account_no"
        if tax_account_column in df.columns:
            print("\n3. Validating tax account numbers...")
            
            with tqdm(total=df.shape[0], desc="Checking tax account numbers", unit="record", leave=False) as pbar:
                tax_account_str = df[tax_account_column].astype(str)
                non_numeric_mask = tax_account_str.str.match(r'^\d+$') == False
                pbar.update(df.shape[0])
            
            if non_numeric_mask.any():
                invalid_rows = df[non_numeric_mask].copy()
                invalid_rows = invalid_rows.copy()
                invalid_rows['reason'] = ''
                try:
                    for _idx, _row in invalid_rows.iterrows():
                        v = '' if pd.isna(_row.get(tax_account_column)) else str(_row.get(tax_account_column))
                        reason_txt = f"Tax account number '{v}' is not numeric"
                        invalid_rows.at[_idx, 'reason'] = reason_txt
                        removal_details.append({
                            'row': _row_number(_idx, _row),
                            'tin': _tin_str(_row.get('tin')),
                            'column': 'TaxAccountNumber',
                            'reason': reason_txt,
                        })
                except Exception:
                    pass

                invalid_records_list.append(invalid_rows)
                
                removal_stats["TAX_ACCOUNT_NON_NUMERIC"] = non_numeric_mask.sum()
                df = df[~non_numeric_mask]
            
            print(f"  Valid tax account numbers: {df.shape[0]:,}")
            print(f"  Invalid tax account numbers: {non_numeric_mask.sum():,}")
        
        # Rule 4: Validate Gross Sales
        sales_column = "gross_sales_cash_or_credit"
        total_income_column = "total_gross_income"
        
        if sales_column in df.columns and total_income_column in df.columns:
            print("\n4. Validating gross sales data...")
            
            with tqdm(total=3, desc="Sales validation steps", unit="step", leave=False) as pbar:
                # Step 1: Check for numeric and non-negative values
                is_valid_sales = (pd.to_numeric(df[sales_column], errors='coerce').notna() & 
                                (df[sales_column] >= 0))
                is_valid_total = (pd.to_numeric(df[total_income_column], errors='coerce').notna() & 
                                (df[total_income_column] >= 0))
                pbar.update(1)
                
                # Step 2: Check that sales don't exceed total income by more than 1%
                # Only check where both columns have valid numbers
                valid_mask = is_valid_sales & is_valid_total
                excessive_mask = pd.Series(False, index=df.index)
                
                if valid_mask.any():
                    excessive_mask.loc[valid_mask] = (
                        df.loc[valid_mask, sales_column] > 
                        df.loc[valid_mask, total_income_column] * 1.01
                    )
                pbar.update(1)
                
                # Step 3: Combine all violations
                invalid_mask = ~is_valid_sales | ~is_valid_total | excessive_mask
                pbar.update(1)
            
            if invalid_mask.any():
                invalid_rows = df[invalid_mask].copy()
                invalid_rows = invalid_rows.copy()
                invalid_rows['reason'] = ''
                try:
                    for _idx, _row in invalid_rows.iterrows():
                        parts = []
                        if not bool(is_valid_sales.get(_idx, True)):
                            parts.append("Gross sales is invalid or negative")
                            removal_details.append({
                                'row': _row_number(_idx, _row),
                                'tin': _tin_str(_row.get('tin')),
                                'column': 'GrossSales',
                                'reason': "Gross sales is invalid or negative",
                            })
                        if not bool(is_valid_total.get(_idx, True)):
                            parts.append("Total gross income is invalid or negative")
                            removal_details.append({
                                'row': _row_number(_idx, _row),
                                'tin': _tin_str(_row.get('tin')),
                                'column': 'TotalGrossIncome',
                                'reason': "Total gross income is invalid or negative",
                            })
                        if bool(excessive_mask.get(_idx, False)):
                            parts.append("Gross sales exceeds total gross income")
                            removal_details.append({
                                'row': _row_number(_idx, _row),
                                'tin': _tin_str(_row.get('tin')),
                                'column': 'GrossSales',
                                'reason': "Gross sales exceeds total gross income",
                            })
                        invalid_rows.at[_idx, 'reason'] = '; '.join(parts).strip()
                except Exception:
                    pass

                invalid_records_list.append(invalid_rows)
                
                # Count violations
                removal_stats["INVALID_GROSS_SALES"] = (~is_valid_sales).sum()
                removal_stats["INVALID_TOTAL_INCOME"] = (~is_valid_total).sum()
                removal_stats["EXCESSIVE_SALES"] = excessive_mask.sum()
                
                df = df[~invalid_mask]
            
            print(f"  Valid sales records: {df.shape[0]:,}")
            print(f"  Invalid sales records: {invalid_mask.sum():,}")
        
        # Rule 5: Check Rental Expenses for Stamp Duty
        rental_expenses_column = "rental_expenses"
        positive_rental_rows = pd.DataFrame()
        
        if rental_expenses_column in df.columns:
            print("\n5. Checking rental expenses for stamp duty requirements...")
            
            with tqdm(total=df.shape[0], desc="Checking rental expenses", unit="record", leave=False) as pbar:
                # Convert to numeric for comparison
                rental_numeric = pd.to_numeric(df[rental_expenses_column], errors='coerce')
                positive_rental_mask = rental_numeric > 0
                pbar.update(df.shape[0])
            
            if positive_rental_mask.any():
                positive_rental_rows = df[positive_rental_mask].copy()

                # These rows are not removed; they are flagged for review only.
                
                # Save stamp duty check file
                stamp_duty_columns = [
                    'tin', 'assessment_no', 'tax_account_no', 
                    rental_expenses_column, 
                    'gross_sales_cash_or_credit', 
                    'total_gross_income'
                ]
                
                available_columns = [col for col in stamp_duty_columns if col in positive_rental_rows.columns]
                if available_columns:
                    stamp_duty_data = positive_rental_rows[available_columns].copy()
                    stamp_duty_data['stamp_duty_check_needed'] = True
                    
                    # Save with progress indicator
                    print("  Saving stamp duty check file...")
                    stamp_duty_data.to_csv(_artifact_path("CIT_STAMP_DUTY_FILE", "cit_stamp_duty_data.csv"), index=False)
                    
                    
                    removal_stats["RENTAL_EXPENSES_POSITIVE"] = len(positive_rental_rows)
                    
                    print(f"\n  Stamp Duty Check Results:")
                    print(f"  * {len(positive_rental_rows):,} records with positive rental expenses")
                    print(f"  * Saved to cit_stamp_duty_data.csv for further review")
        
        # Combine all invalid records
        removed_data_df = pd.concat(invalid_records_list, ignore_index=True) if invalid_records_list else pd.DataFrame()
        if removed_data_df is None:
            removed_data_df = pd.DataFrame()
        if not removed_data_df.empty and 'reason' not in removed_data_df.columns:
            removed_data_df['reason'] = ''
        
        # Print detailed removal summary
        print("\n" + "="*60)
        print("DATA VALIDATION AND CLEANING SUMMARY")
        print("="*60)
        print(f"Total records processed: {original_shape[0]:,}")
        print(f"Valid records kept: {len(df):,}")
        print(f"Invalid records removed: {len(removed_data_df):,}")
        print(f"Clean rate: {(len(df)/original_shape[0])*100:.1f}%")
        
        if removal_stats:
            print("\nDetailed removal reasons:")
            print("-"*40)
            with tqdm(total=len(removal_stats), desc="Generating report", unit="category", leave=False) as pbar:
                for reason, count in sorted(removal_stats.items()):
                    if count > 0:
                        print(f"\n- {reason.replace('_', ' ').title()}: {count:,} records")
                    pbar.update(1)
        
        # Save cleaned data in both formats
        print("\nSaving cleaned data...")
        cleaned_path = _artifact_path("CIT_CLEANED_FILE", "cit_cleaned_data.csv")
        df.to_csv(cleaned_path, index=False)
        print(f"Cleaned data saved to: {cleaned_path}")
        
        # Save invalid data in both formats
        if not removed_data_df.empty:
            print("Saving removed records...")
            removed_path = _artifact_path("CIT_REMOVED_FILE", "cit_removed_data.csv")
            removed_data_df.to_csv(removed_path, index=False)
            print(f"Removed data saved to: {removed_path}")
        
        # Save validation log
        print("Saving validation summary...")
        with open(_artifact_path("CIT_VALIDATION_SUMMARY_FILE", "validation_summary.txt"), "w") as f:
            f.write("CIT Data Validation Summary\n")
            f.write("="*40 + "\n")
            f.write(f"Total records processed: {original_shape[0]:,}\n")
            f.write(f"Valid records kept: {len(df):,}\n")
            f.write(f"Invalid records removed: {len(removed_data_df):,}\n")
            f.write(f"Clean rate: {(len(df)/original_shape[0])*100:.1f}%\n\n")
            
            f.write("Removal Details:\n")
            for reason, count in removal_stats.items():
                if count > 0:
                    f.write(f"{reason}: {count:,}\n")
        
        return df, removed_data_df, removal_details

def main():
        """
        Main function to execute data validation pipeline
        """
        print("="*60)
        print("Starting CIT Data Validation Pipeline")
        print("="*60)
        
        start_time = time.time()
        
        try:
            # Load the preprocessed data from Script 1
            print("Loading preprocessed data...")
            with tqdm(desc="Loading data", unit="file") as pbar:
                cit_data = pd.read_csv(_artifact_path("CIT_PREPROCESSED_FILE", "cit_preprocessed_data.csv"))
                pbar.update(1)
            
            print(f"Loaded preprocessed data with shape: {cit_data.shape}")
            
            # Create overall progress tracker for validation steps
            steps = [
                "Validating TIN numbers",
                "Validating assessment numbers", 
                "Validating tax account numbers",
                "Validating gross sales data",
                "Checking rental expenses",
                "Saving results"
            ]
            
            print("\nStarting validation process...")
            with tqdm(total=len(steps), desc="Overall Progress", unit="step") as pbar:
                # Validate and clean the data
                cleaned_data, _removed_df, _removal_details = validate_and_clean_cit_data(cit_data)
                pbar.update(5)
                
                pbar.set_postfix_str("Saving final results...")
                pbar.update(1)
        
        except FileNotFoundError:
            print(f"Error: {_artifact_path('CIT_PREPROCESSED_FILE', 'cit_preprocessed_data.csv')} not found.")
            print("Please run script_1_data_preprocessing.py first.")
            return None
        except Exception as e:
            print(f"Error during data validation: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
        
        end_time = time.time()
        
        print("\n" + "="*60)
        print("DATA VALIDATION COMPLETE")
        print("="*60)
        print(f"Output files: {_artifact_path('CIT_CLEANED_FILE', 'cit_cleaned_data.csv')}")
        print(f"Shape: {cleaned_data.shape}")
        print(f"Processing time: {end_time - start_time:.2f} seconds")
        
        # Show memory usage if psutil is available
        try:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            print(f"Memory usage: {process.memory_info().rss / 1024 ** 2:.2f} MB")
        except ImportError:
            pass
        
        return cleaned_data

if __name__ == "__main__":
        validated_data = main()
