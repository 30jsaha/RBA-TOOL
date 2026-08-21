"""
Simplified GST Analysis Pipeline using existing .pkl files
Flow: Standardization â†’ Validation â†’ Fraud Detection â†’ Fraud Prediction â†’ Fraud Justification
"""

import pickle
import shutil
import pandas as pd
import warnings
import os
import sys
import time
import uuid
from datetime import datetime
from datetime import timedelta
from dotenv import load_dotenv                          
from gst_registration_merger import merge_taxpayer_names
from sqlalchemy import create_engine
from pathlib import Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv(dotenv_path=os.path.join(                  
    os.path.dirname(os.path.abspath(__file__)), '..', '.env'))

from gst.gst_upload_hook import handle_gst_upload, handle_gst_upload_failure, save_gst_justification_to_db
from config.db_config import get_mysql_engine
from utils.upload_logger import log_pipeline_start, log_pipeline_end

TABLE_REGISTRATION  = "tin_registrations"
TABLE_JUSTIFICATION = "gst_fraud_justification"
DB_NAME = os.getenv("DB_NAME", "rba_tool_db")             
# Suppress warnings
warnings.filterwarnings("ignore")


class GSTAnalysis:
    """Complete GST analysis using pickle files"""
    
    def __init__(self):
        # Track intermediate files to delete at the end
        self.created_files = []
        # Track step execution times
        self.step_times = {}
        # Get script directory for path resolution
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_dir   = os.path.join(self.script_dir, 'data')
        self.models_dir = os.path.join(self.script_dir, 'models')
        self.public_output_dir = os.path.join(self.script_dir, 'final_output')
        self.logs_dir = os.path.join(self.script_dir, 'logs')
        self.output_dir = self.public_output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)
        # When set by API (e.g. /api/gst/validate), force the pipeline to use
        # a specific uploaded file rather than auto-discovering the "latest" file.
        self.input_file = None
        # Batch-tracking â€” set here so step5 is safe even when called
        # independently (e.g. via API) without run_complete_pipeline()
        self.upload_batch_id = str(uuid.uuid4())
        self.uploaded_at     = datetime.now()

    # ==
    # Helpers
    # ==

    def _out(self, filename):
        """Return absolute path inside final_output/."""
        return os.path.abspath(os.path.join(self.output_dir, filename))

    def _track(self, *filenames):
        """Register one or more output_dir filenames for end-of-run cleanup."""
        for f in filenames:
            path = self._out(f) if not os.path.isabs(f) else f
            if path not in self.created_files:
                self.created_files.append(path)

    def _move_to_output(self, filename, keep=False):
        """
        Move *filename* from cwd â†’ output_dir (if not already there).
        If keep=False, register the destination for cleanup.
        Returns the destination path.
        """
        src = os.path.join(os.getcwd(), filename)
        dst = self._out(filename)
        if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(dst):
            shutil.move(src, dst)
        if not keep and os.path.exists(dst):
            self._track(dst)
        return dst

    def find_input_file(self):
        """Find the GST input file dynamically in the data folder"""
        # If API provided an explicit path, always use it.
        if self.input_file and os.path.exists(self.input_file):
            self.log_message(f"Using explicit input file: {os.path.basename(self.input_file)}")
            return self.input_file

        all_files = []
        for ext in ["*.parquet", "*.csv"]:
            all_files.extend(
                [f for f in __import__('glob').glob(os.path.join(self.data_dir, ext))]
            )
        if not all_files:
            return None
        if len(all_files) == 1:
            self.log_message(f"Found input file: {os.path.basename(all_files[0])}")
            return all_files[0]
        gst_files = [f for f in all_files if 'gst' in os.path.basename(f).lower()]
        candidates = gst_files if gst_files else all_files
        latest = max(candidates, key=lambda f: os.path.getmtime(f))
        self.log_message(f"Multiple files found in data/ â€” using most recent: {os.path.basename(latest)}")
        for f in candidates:
            marker = 'â†’' if f == latest else ' '
            self.log_message(f"  {marker} {os.path.basename(f)}")
        return latest

    def log_message(self, message):
        """Simple logging"""
        print(f"  â†’ {message}")

    def _read_input_df(self, path: str):
        """
        Read an input file into a DataFrame.
        Preserves existing behavior but adds safe fallbacks for common CSV encoding issues.
        """
        if (path or "").endswith(".parquet"):
            return pd.read_parquet(path)

        try:
            return pd.read_csv(path)
        except Exception as first_err:
            # Fallbacks for common CSV issues (encoding quirks / parser edge cases).
            # Keep default behavior for good files; only fallback on error.
            for enc in ("utf-8-sig", "utf-8", "latin1"):
                try:
                    return pd.read_csv(path, encoding=enc)
                except Exception:
                    continue
            # Last resort: try the python engine (more tolerant for some malformed CSVs).
            try:
                return pd.read_csv(path, engine="python")
            except Exception:
                raise first_err
    def get_data_path(self, filename):
        """Get full path for data files"""
        data_path = os.path.join(self.data_dir, filename)
        if os.path.exists(data_path):
            return data_path
        return filename

    def get_model_path(self, filename):
        """
        Resolve a pkl / model file.

        Search order
        ====
        Pipeline pkl files (standardizer, validator, detector, justification)
        live in  gst/  (script_dir).

        Heavy model artifacts (xgboost_selected_model.pkl,
        feature_info_selected.pkl, gst_fraud_predictor.pkl)
        live in  gst/models/  (models_dir).

        We try models_dir first so model artifacts are found immediately;
        pipeline pkls fall back to script_dir automatically.
        """
        model_path = os.path.join(self.models_dir, filename)
        if os.path.exists(model_path):
            return model_path
        script_root_path = os.path.join(self.script_dir, filename)
        if os.path.exists(script_root_path):
            return script_root_path
        return model_path  # return original so the error message is meaningful

    def load_pickle(self, pickle_file, description=""):
        """Load a pickle file"""
        try:
            pickle_path = self.get_model_path(pickle_file)
            with open(pickle_path, 'rb') as f:
                data = pickle.load(f)
            self.log_message(f"Loaded {pickle_file} {description}")
            return data
        except Exception as e:
            self.log_message(f"Error loading {pickle_file}: {str(e)}")
            return None

    # =====================
    # Data loading
    # ===============

    def load_and_preprocess_data(self):
        """Load GST data with upload hook integration"""
        print("\n" + "="*60)
        print("DATA LOADING")
        print("="*60)

        input_file = None
        gst_df = None

        try:
            input_file = self.find_input_file()
            if not input_file:
                raise FileNotFoundError(f"No GST input file found in {self.data_dir}")

            gst_df = self._read_input_df(input_file)

            self.log_message(f"Loaded: {os.path.basename(input_file)} | shape: {gst_df.shape}")
            handle_gst_upload(os.path.basename(input_file), gst_df)
            return gst_df

        except Exception as e:
            handle_gst_upload_failure(
                os.path.basename(input_file) if input_file else None, e
            )
            raise

    # ============================================================================================================================================
    # Step 1 â€“ Column standardisation
    # ============================================================================================================================================

    def step1_column_standardization(self):
        """Step 1: Standardize column names"""
        print("\n" + "="*60)
        print("STEP 1: COLUMN STANDARDIZATION")
        print("="*60)

        start_time = time.time()

        try:
            input_path = self.find_input_file()
            if not input_path:
                self.log_message(f"No GST input file found in {self.data_dir}")
                return False

            std_funcs = self.load_pickle("gst_column_standardizer.pkl",
                                         "(standardization functions)")
            if not std_funcs:
                return False

            gst_df = self._read_input_df(input_path)

            if 'standardize_gst_columns' in std_funcs:
                standardized_df = std_funcs['standardize_gst_columns'](gst_df)

                # Save intermediate to final_output/ and register for cleanup
                out_path = self._out("gst_standardized.csv")
                standardized_df.to_csv(out_path, index=False)
                self._track("gst_standardized.csv")
                self.log_message("Saved to final_output/gst_standardized.csv")
                self.log_message(f"Standardized columns: {len(standardized_df):,} records")

                self.step_times['step1'] = time.time() - start_time
                self.log_message(f"Time taken: {self.step_times['step1']:.2f} seconds")
                self.records_step1 = len(standardized_df)
                return True
            else:
                self.log_message("Function 'standardize_gst_columns' not found in pickle")
                return False

        except Exception as e:
            self.log_message(f"Error in standardization: {str(e)}")
            return False

    # ============================================================================================================================================
    # Step 2 - Validation & cleaning
    # ============================================================================================================================================

    def step2_data_validation(self):
        """Step 2: Validate and clean data with taxpayer name merging"""
        print("\n" + "="*60)
        print("STEP 2: DATA VALIDATION & CLEANING")
        print("="*60)

        start_time = time.time()

        try:
            val_funcs = self.load_pickle("gst_validation_pipeline.pkl",
                                         "(validation functions)")
            if not val_funcs:
                return False

            # Load standardised data from final_output/
            if os.path.exists(self._out("gst_standardized.parquet")):
                gst_df = pd.read_parquet(self._out("gst_standardized.parquet"))
            elif os.path.exists(self._out("gst_standardized.csv")):
                gst_df = pd.read_csv(self._out("gst_standardized.csv"))
            else:
                self.log_message("Input file not found: gst_standardized (.parquet or .csv)")
                return False

            # Merge taxpayer names
            try:
                if 'tin' in gst_df.columns:
                    gst_df['tin'] = gst_df['tin'].astype(str)
                    self.log_message("Merging taxpayer names from registration data...")
                    gst_df = merge_taxpayer_names(gst_df)
                    self.log_message("Taxpayer names merged successfully")
                else:
                    self.log_message(
                        "Warning: 'tin' column not found â€” cannot merge taxpayer names"
                    )
            except Exception as e:
                self.log_message(f"Warning: Could not merge taxpayer names: {str(e)}")

            # ==== Validate & clean ======================================================================================
            # NOTE: validate_and_clean_gst_data() internally saves
            #   gst_cleaned_data.parquet  â†’  cwd  (intermediate)
            #   gst_removed_data.parquet  â†’  cwd  (intermediate â€“ we re-save as CSV below)
            #   gst_validation_log.txt        â†’  cwd  (kept permanently)
            # We move all three into final_output/ immediately after the call.

            cleaned_df = None
            removed_df = pd.DataFrame()

            if 'validate_and_clean_gst_data' in val_funcs:
                cleaned_df, removed_df = val_funcs['validate_and_clean_gst_data'](gst_df)
                self.log_message(
                    f"Cleaned data: {len(cleaned_df):,} records kept, "
                    f"{len(removed_df):,} removed"
                )

            elif 'run_full_validation_pipeline' in val_funcs:
                cleaned_df, removed_df, message = val_funcs['run_full_validation_pipeline'](gst_df)
                self.log_message(f"Cleaned data: {len(cleaned_df):,} records kept")

            else:
                for func_name, func in val_funcs.items():
                    if callable(func) and 'validate' in func_name.lower():
                        result = func(gst_df)
                        if isinstance(result, tuple) and len(result) >= 2:
                            cleaned_df = result[0]
                            self.log_message(f"Used '{func_name}' for validation")
                            break

            # ==== Relocate files the pkl wrote to cwd â†’ final_output/ ================
            # gst_cleaned_data.parquet  â€“ intermediate, will be deleted at end
            self._move_to_output("gst_cleaned_data.parquet", keep=False)
            # gst_removed_data.parquet  â€“ intermediate (we keep the CSV version)
            self._move_to_output("gst_removed_data.parquet", keep=False)
            # gst_validation_log.txt        â€“ permanently kept
            self._move_to_output("gst_validation_log.txt", keep=True)

            if cleaned_df is not None:
                # Save validated data to final_output/ (intermediate â†’ deleted at end)
                out_csv = self._out("gst_validated.csv")
                cleaned_df.to_csv(out_csv, index=False)
                self._track("gst_validated.csv")
                self.log_message("Saved to final_output/gst_validated.csv")

                # Permanently kept: removed-data CSV
                if removed_df is not None and len(removed_df) > 0:
                    removed_df.to_csv(self._out("gst_removed_data.csv"), index=False)
                    self.log_message(
                        "Saved to final_output/gst_removed_data.csv (kept permanently)"
                    )

                self.step_times['step2'] = time.time() - start_time
                self.log_message(f"Time taken: {self.step_times['step2']:.2f} seconds")
                self.records_step2 = len(cleaned_df)
                return True
            else:
                self.log_message("No validation function found or no data returned")
                return False

        except Exception as e:
            self.log_message(f"Error in validation: {str(e)}")
            return False

    # ============================================================================================================================================
    # Step 3 : Rules + Model prediction (parallel)
    # ============================================================================================================================================

    def step3_parallel_rules_and_model(self):
        """Step 3: Run rule-based features AND model prediction in parallel"""
        print("\n" + "="*60)
        print("STEP 3: RULE CHECKING + MODEL PREDICTION (PARALLEL)")
        print("="*60)

        import concurrent.futures

        start_time = time.time()

        # Load validated data from final_output/
        input_path = self.find_input_file()
        if not input_path:
            self.log_message("No GST input file found.")
            return False
        gst_df = self._read_input_df(input_path)
        self.log_message(f"Loaded raw input data: {len(gst_df):,} records")         

        rule_result = {}
        model_result = {}
        errors = {}

        # ==== Thread: rule-based flags ==============================================================================
        def run_rules():
            try:
                fraud_funcs = self.load_pickle("gst_fraud_detector.pkl")
                if not fraud_funcs:
                    errors['rules'] = "Could not load gst_fraud_detector.pkl"
                    return
                fraud_df = fraud_funcs['add_fraud_detection_features'](gst_df.copy())
                rule_result['df'] = fraud_df
                self.log_message(f"Rules done: {len(fraud_df):,} records with rule flags")
            except Exception as e:
                errors['rules'] = str(e)

        # ==== Thread: XGBoost model prediction ============================================================
        def run_model():
            try:
                for f in ['xgboost_selected_model.pkl', 'feature_info_selected.pkl']:
                    if not os.path.exists(self.get_model_path(f)):
                        errors['model'] = f"Missing model file: {f}"
                        return

                pred_funcs = self.load_pickle("gst_fraud_predictor.pkl")
                if not pred_funcs:
                    errors['model'] = "Could not load gst_fraud_predictor.pkl"
                    return

                # Save a temp parquet in final_output/ so the predictor function
                # can read it via file path.  Tracked for end-of-run cleanup.
                validated_temp = self._out("gst_validated_temp.parquet")
                gst_df.copy().to_parquet(validated_temp, index=False)

                # Point output_base into final_output/ so ANY file the pkl
                # function writes stays there (not cwd).
                pred_output_base = self._out("gst_fraud_prediction_model_temp")

                result_df = pred_funcs['run_fraud_prediction_pipeline'](
                    new_data_path  = validated_temp,
                    model_path     = self.get_model_path('xgboost_selected_model.pkl'),
                    features_path  = self.get_model_path('feature_info_selected.pkl'),
                    output_base    = pred_output_base,
                )
                model_result['df'] = result_df
                self.log_message(f"Model done: {len(result_df):,} records with predictions")
            except Exception as e:
                errors['model'] = str(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(run_rules)
            f2 = executor.submit(run_model)
            concurrent.futures.wait([f1, f2])

        # Register temp files written by the two threads for cleanup
        self._track(
            "gst_validated_temp.parquet",
            "gst_fraud_prediction_model_temp.csv",
            "gst_fraud_prediction_model_temp.parquet",
        )

        if 'rules' in errors:
            self.log_message(f"Rules error: {errors['rules']}")
            return False
        if 'model' in errors:
            self.log_message(f"Model error: {errors['model']}")
            return False

        # ==== Merge rule flags INTO model prediction dataframe ==============================
        rule_cols = [
            'deduct_input_credits_violation', 'invalid_gst_refundable',
            'fraud_output_debits_no_tax', 'misreported_zero_rated_sales',
            'overstated_zero_rated_sales', 'non_reported_taxable_sales',
            'fraud_incomplete_gst_returns', 'non_filing_gst',
            'sales_drop_more_than_50_percent', 'fraud_multiple_refund_claims_6_months',
            'is_fraud',
        ]
        rule_df  = rule_result['df']
        model_df = model_result['df']

        existing     = set(model_df.columns)
        cols_to_add  = [c for c in rule_cols if c in rule_df.columns and c not in existing]
        model_df[cols_to_add] = rule_df[cols_to_add].values

        # Save merged prediction â€” both formats in final_output/ (intermediate)
        model_df.to_csv(    self._out("gst_fraud_prediction.csv"),     index=False)
        model_df.to_parquet(self._out("gst_fraud_prediction.parquet"), index=False)
        self._track("gst_fraud_prediction.csv", "gst_fraud_prediction.parquet")
        self.log_message("Saved to final_output/gst_fraud_prediction.csv and .parquet")

        self.step_times['step3'] = time.time() - start_time
        self.log_message(f"Combined output saved. Time: {self.step_times['step3']:.2f}s")
        try:
            _df3 = pd.read_csv(self._out("gst_fraud_prediction.csv"))
            self.records_step3 = len(_df3)
        except Exception:
            self.records_step3 = None    
        return True

    # ============================================================================================================================================
    # Step 5 : Fraud justification
    # ============================================================================================================================================

    def step5_fraud_justification(self):
        """Step 5: Create fraud justifications"""
        print("\n" + "="*60)
        print("STEP 5: FRAUD JUSTIFICATION")
        print("="*60)

        start_time = time.time()

        try:
            justify_funcs = self.load_pickle("gst_fraud_justification.pkl",
                                             "(justification functions)")
            if not justify_funcs:
                return False

            self.log_message("Loaded prediction data for justification")

            if 'create_gst_fraud_justification_file' not in justify_funcs:
                self.log_message("Function 'create_gst_fraud_justification_file' not found")
                return False

            justify_func   = justify_funcs['create_gst_fraud_justification_file']
            just_base      = self._out('gst_fraud_justification')   # â†’ final_output/gst_fraud_justification
            just_parquet   = just_base + ".parquet"
            just_csv       = just_base + ".csv"

            try:
                result = justify_func(
                    input_file  = self._out('gst_fraud_prediction.parquet'),
                    output_file = just_base,
                )
            except TypeError:
                try:
                    result = justify_func(input_file=self._out('gst_fraud_prediction.parquet'))
                except TypeError:
                    try:
                        result = justify_func()
                    except Exception as e:
                        self.log_message(f"All calling patterns failed: {str(e)}")
                        return False

            # Both files written by the justification function live in
            # final_output/ because we passed just_base as output_file.
            # Register both for end-of-run cleanup.
            self._track("gst_fraud_justification.csv", "gst_fraud_justification.parquet")

            # Push justification to MySQL unless the caller wants DB insert to run later.
            db_saved = False
            if os.path.exists(just_parquet):
                just_df = pd.read_parquet(just_parquet)
                if getattr(self, "defer_db_insert", False):
                    self.log_message("Deferred MySQL insert for background chunked DB save")
                else:
                    engine = get_mysql_engine()
                    save_gst_justification_to_db(
                        just_df, engine,
                        upload_batch_id=self.upload_batch_id,
                        uploaded_at=self.uploaded_at,
                    )
                    engine.dispose()
                    self.log_message("Saved justification to MySQL via save_gst_justification_to_db()")
                    db_saved = True

            self._db_saved = db_saved    
            

            self.step_times['step5'] = time.time() - start_time
            self.log_message(f"Time taken: {self.step_times['step5']:.2f} seconds")
            try:
                _df5 = pd.read_sql('SELECT COUNT(*) as cnt FROM gst_fraud_justification',
                                   get_mysql_engine().connect())
                self.records_step5 = int(_df5.iloc[0]['cnt'])
            except Exception:
                self.records_step5 = None    
            return True

        except Exception as e:
            self.log_message(f"Error in justification: {str(e)}")
            return False

    # ============================================================================================================================================
    # Main pipeline runner
    # ============================================================================================================================================

    def run_complete_pipeline(self):
        """Run the complete GST analysis pipeline"""
        print("="*70)
        print("GST ANALYSIS PIPELINE")
        print("="*70)

        pipeline_start_time = time.time()

        log_pipeline_start('GST Fraud Detection Pipeline')
        self.upload_batch_id = str(uuid.uuid4())
        self.uploaded_at     = datetime.now()
        print(f"  Upload Batch ID: {self.upload_batch_id}")

        # ==== Verify required pkl files exist ==============================================================
        # Pipeline pkls  â†’ gst/  (script_dir)
        # Model pkls     â†’ gst/models/  (models_dir)
        required_pickles = [
           # 'gst_column_standardizer.pkl',
           # 'gst_validation_pipeline.pkl',
            'gst_fraud_detector.pkl',
            'gst_fraud_justification.pkl',   # script_dir
            'gst_fraud_predictor.pkl',        # models_dir
        ]
        missing_pickles = [
            p for p in required_pickles
            if not os.path.exists(self.get_model_path(p))
        ]
        if missing_pickles:
            print(f"\nERROR: Missing required .pkl files:")
            for p in missing_pickles:
                print(f"  - {p}")
            print(
                f"\nPipeline pkls should be in : {self.script_dir}\n"
                f"Model pkls should be in    : {self.models_dir}"
            )
            return

        # ==== Load data ==========================================================================================================
        try:
            gst_df = self.load_and_preprocess_data()
        except Exception as e:
            print(f"\nâŒ Pipeline aborted: Failed to load data - {str(e)}")
            return

        steps = [
          #  ("Column Standardization",       self.step1_column_standardization),
           # ("Data Validation",              self.step2_data_validation),
            ("Rules + Model (Parallel)",     self.step3_parallel_rules_and_model),
            ("Fraud Justification",          self.step5_fraud_justification),
        ]

        completed_steps = 0

        for step_name, step_func in steps:
            print(f"\nRunning: {step_name}")
            print("-" * 40)
            if step_func():
                print(f"âœ“ {step_name} completed successfully")
                completed_steps += 1
            else:
                print(f"âœ— {step_name} failed")
                print("Stopping pipeline due to step failure.")
                break

        total_time = time.time() - pipeline_start_time

        log_pipeline_end('GST Fraud Detection Pipeline', total_time)

        # ==== Cleanup: delete all intermediates from final_output/ ====================
        # Only these two files (plus gst_validation_log.txt) are permanently kept.
        #KEEP_FILES = {"gst_removed_data.csv", "gst_validation_log.txt"}
        # If DB write failed, the fallback CSV from save_gst_justification_to_db
        # (gst_fraud_with_justification.csv) is the only output â€” keep it
        KEEP_FILES = set()
        if not getattr(self, '_db_saved', True):
          KEEP_FILES.add("gst_fraud_with_justification.csv")

        print("\nCleaning up intermediate files from final_output/ ...")
        for fname in os.listdir(self.output_dir):
            if fname in KEEP_FILES:
                print(f"  Kept:    {fname}")
                continue
            full_path = os.path.join(self.output_dir, fname)
            try:
                os.remove(full_path)
                print(f"  Deleted: {fname}")
            except Exception as e:
                print(f"  Warning: could not delete {fname}: {e}")

        # ==== Summary ==============================================================================================================
        print("\n" + "="*70)
        print("PIPELINE EXECUTION SUMMARY")
        print("="*70)
        print(f"Steps completed: {completed_steps}/{len(steps)}")

        print(f"\nStep-wise Execution Times:")
        step_key_map = {
           # "Column Standardization":   'step1',
           # "Data Validation":          'step2',
            "Rules + Model (Parallel)": 'step3',
            "Fraud Justification":      'step5',
        }
        for i, (step_name, _) in enumerate(steps, 1):
            key = step_key_map.get(step_name, f'step{i}')
            if key in self.step_times:
                print(f"  Step {i}: {step_name:<35} {self.step_times[key]:.2f} seconds")

        print(f"\nTotal pipeline execution time: {total_time:.2f} seconds")
        print(f"Total pipeline execution time: {str(timedelta(seconds=int(total_time)))} (HH:MM:SS)")

        db_name = os.getenv("DB_NAME", "RBA_tool_database")
        print(f"\nOutput Table in MySQL ({db_name}):")
        print(f"  â€¢ {TABLE_JUSTIFICATION:<35} Final: Fraud justifications")

        print(f"\nFiles retained in final_output/:")
        for f in KEEP_FILES:
            p = os.path.join(self.output_dir, f)
            status = "present" if os.path.exists(p) else "not generated"
            print(f"  â€¢ {f:<35} [{status}]")

        print(f"\nPerformance Summary:")
        print(f"  Average time per step: {total_time/len(steps):.2f} seconds")
        if completed_steps > 0:
            print(f"  Efficiency: {completed_steps/len(steps)*100:.1f}% steps completed")

        print("\n" + "="*70)
        print("gst analysis done!")
        print("="*70)


# ==== Entry point ======================================================================================================================
if __name__ == "__main__":
    analyzer = GSTAnalysis()
    analyzer.run_complete_pipeline()


