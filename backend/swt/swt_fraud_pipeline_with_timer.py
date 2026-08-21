#!/usr/bin/env python3
"""
SWT Fraud Detection Pipeline Orchestrator with Detailed Timing
==============================================================
This master script orchestrates the execution of all SWT fraud detection scripts
in the correct order with comprehensive timing for each step.

Usage:
    python run_swt_pipeline.py [--skip-validation] [--skip-prediction] [--keep-temp]
    
Options:
    --skip-validation    Skip data validation steps (if data is pre-validated)
    --skip-prediction    Skip ML prediction (run only rule-based checks)
    --keep-temp          Keep temporary files (don't auto-cleanup)
    --input FILE         Specify input file (default: swt_merged_data_2015_2024.parquet)
    --output-dir DIR     Specify output directory (default: final_output)
    --output-format FMT   Specify output format: csv or parquet (default: csv)
    --verbose            Show detailed output from each script
"""

import os
import sys
# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import subprocess
import argparse
import time
import shutil
import json
import uuid
from datetime import datetime
from pathlib import Path

from datetime import datetime, timedelta
from contextlib import contextmanager
import pandas as pd
import warnings
import getpass
from sqlalchemy import create_engine

warnings.filterwarnings("ignore")
MODULE_NAME = "swt_fraud_pipeline_with_timer.py"


def _normalize_path(path):
    return str(Path(path).expanduser().resolve()) if path else ""


def _get_year_distribution(df):
    for candidate in ["tax_period_year", "Tax Period Year", "TaxPeriodYear"]:
        if candidate in df.columns:
            return df[candidate].value_counts(dropna=False).sort_index().to_dict()
    return "tax_period_year column not found"


def _print_df_debug(function_name, file_path, df):
    print("======================================================")
    print(f"MODULE: {MODULE_NAME}")
    print(f"FUNCTION: {function_name}")
    print(f"FILE OPENED: {os.path.basename(file_path)}")
    print(f"ABSOLUTE PATH: {_normalize_path(file_path)}")
    print(f"FILE EXISTS: {os.path.exists(file_path)}")
    print(f"ROWS: {len(df)}")
    print(f"COLUMNS: {len(df.columns)}")
    print(f"tax_period_year distribution: {_get_year_distribution(df)}")
    print("======================================================")


def _read_dataframe(file_path, function_name):
    actual_path = _normalize_path(file_path)
    if actual_path.lower().endswith(".parquet"):
        df = pd.read_parquet(actual_path)
    else:
        df = pd.read_csv(actual_path, low_memory=False)
    _print_df_debug(function_name, actual_path, df)
    return df

# ============================================================================
# TIMING UTILITIES
# ============================================================================

class Timer:
    """Simple context manager for timing a named code block"""

    def __init__(self, label=""):
        self.label = label
        self.elapsed = None

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.end_time = time.perf_counter()
        self.elapsed = self.end_time - self.start_time

    @property
    def elapsed_formatted(self):
        if self.elapsed is None:
            return "N/A"
        if self.elapsed < 1:
            return f"{self.elapsed * 1000:.2f} ms"
        elif self.elapsed < 60:
            return f"{self.elapsed:.2f} sec"
        else:
            minutes = int(self.elapsed // 60)
            seconds = self.elapsed % 60
            return f"{minutes} min {seconds:.1f} sec"


class PipelineTimer:
    """Tracks timing for the entire pipeline"""
    
    def __init__(self):
        self.start_time = None
        self.end_time = None
        self.steps = {}
        self.substeps = {}
        self.current_step = None
        self.start_datetime = None
        self.end_datetime   = None 
    
    def start_pipeline(self):
        self.start_time = time.perf_counter()
        self.start_datetime = datetime.now()
        return datetime.now()
    
    def end_pipeline(self):
        self.end_time = time.perf_counter()
        self.end_datetime = datetime.now()
    
    def start_step(self, step_name):
        self.current_step = step_name
        if step_name not in self.steps:
            self.steps[step_name] = {
                'start': time.perf_counter(),
                'end': None,
                'elapsed': None,
                'substeps': {}
            }
    
    def end_step(self, step_name):
        if step_name in self.steps:
            self.steps[step_name]['end'] = time.perf_counter()
            self.steps[step_name]['elapsed'] = (
                self.steps[step_name]['end'] - self.steps[step_name]['start']
            )
    
    def time_substep(self, step_name, substep_name, func, *args, **kwargs):
        """Time a sub-step within a step"""
        if step_name not in self.substeps:
            self.substeps[step_name] = {}
        
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        
        self.substeps[step_name][substep_name] = elapsed
        return result
    
    @property
    def total_elapsed(self):
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None
    
    @property
    def total_elapsed_formatted(self):
        elapsed = self.total_elapsed
        if elapsed is None:
            return "N/A"
        
        if elapsed < 60:
            return f"{elapsed:.2f} seconds"
        elif elapsed < 3600:
            minutes = int(elapsed // 60)
            seconds = elapsed % 60
            return f"{minutes} min {seconds:.1f} sec"
        else:
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            return f"{hours} hr {minutes} min"
    
    def get_step_elapsed(self, step_name):
        if step_name in self.steps:
            return self.steps[step_name].get('elapsed')
        return None
    
    def format_time(self, elapsed):
        """Format time in a readable way"""
        if elapsed is None:
            return "N/A"
        if elapsed < 1:
            return f"{elapsed * 1000:.0f} ms"
        elif elapsed < 60:
            return f"{elapsed:.2f} sec"
        else:
            minutes = int(elapsed // 60)
            seconds = elapsed % 60
            return f"{minutes} min {seconds:.1f} sec"
    
    def generate_timing_report(self):
        """Generate a detailed timing report"""
        lines = []
        lines.append("=" * 80)
        lines.append("PIPELINE EXECUTION TIMING REPORT")
        lines.append("=" * 80)
        lines.append("")
        
        # Overall timing
        lines.append(f"Total Pipeline Execution Time: {self.total_elapsed_formatted}")
        lines.append(f"Started: {self.start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Ended:   {self.end_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        
        # Step-by-step timing
        lines.append("-" * 80)
        lines.append("STEP EXECUTION TIMES")
        lines.append("-" * 80)
        lines.append(f"{'Step':<40} {'Time':<15} {'% of Total':<10}")
        lines.append("-" * 80)
        
        total = self.total_elapsed or 1
        
        for step_name, step_data in self.steps.items():
            elapsed = step_data.get('elapsed', 0)
            percentage = (elapsed / total * 100) if total > 0 else 0
            time_str = self.format_time(elapsed)
            lines.append(f"{step_name:<40} {time_str:<15} {percentage:.1f}%")
        
        # Substep details
        lines.append("")
        lines.append("-" * 80)
        lines.append("DETAILED SUB-STEP TIMING")
        lines.append("-" * 80)
        
        for step_name, substeps in self.substeps.items():
            if substeps:
                lines.append(f"\n[{step_name}]")
                for substep_name, elapsed in substeps.items():
                    time_str = self.format_time(elapsed)
                    lines.append(f"  - {substep_name}: {time_str}")
        
        lines.append("")
        lines.append("=" * 80)
        
        return "\n".join(lines)
    
    def save_report(self, filepath):
        """Save timing report to file"""
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self.generate_timing_report())


# ============================================================================
# CONFIGURATION
# ============================================================================

class PipelineConfig:
    """Configuration for the SWT fraud detection pipeline"""
    
    # Script execution order with descriptions
    PIPELINE_STEPS = [
        # {
        #     'name': 'Data Preparation & Standardization',
        #     'script': '1_swt_preparation.py',
        #     'required': True,
        #     'description': 'Standardizes column names and formats data',
        #     'input_files': [],
        #     'output_files': ['swt_standardized.parquet']
        # },
        # {
        #     'name': 'Data Validation & Cleaning',
        #     'script': '2_swt_validation.py',
        #     'required': True,
        #     'description': 'Validates TINs, removes invalid records, maps taxpayer names',
        #     'input_files': ['swt_standardized.parquet', 'data/25.05.21.05 TIN Registrations.xlsx'],
        #     'output_files': [
        #         'swt_cleaned_data.parquet', 
        #         'swt_removed_data.parquet',
        #         'swt_data_after_taxpayer_name_mapping.parquet'
        #     ]
        # },
        {
            'name': 'Feature Engineering & Rule Checking',
            'script': '3_swt_feature_engineering.py',
            'required': True,
            'description': 'Creates fraud detection features and applies rule-based checks',
            'input_files': [],
            'output_files': ['swt_data_after_rule_checking.parquet']
        },
        {
            'name': 'ML Fraud Prediction',
            'script': '4_swt_fraud_prediction.py',
            'required': False,
            'description': 'Runs XGBoost model to predict fraud probability',
            'input_files': ['swt_data_after_rule_checking.parquet', 'models/xgboost_model.pkl'],
            'output_files': ['fraud_predictions_full.parquet', 'fraud_predictions_full.csv']
        },
        {
            'name': 'Fraud Justification Generation',
            'script': '5_swt_justification.py',
            'required': True,
            'description': 'Generates human-readable justifications for flagged records',
            'input_files': ['swt_data_after_rule_checking.parquet', 'models/xgboost_model.pkl'],
            'output_files': ['swt_fraud_justification.parquet', 'swt_fraud_justification.csv']
        }
    ]


# ============================================================================
# PIPELINE ORCHESTRATOR
# ============================================================================

class SWTPipelineOrchestrator:
    """Orchestrates the execution of all SWT fraud detection scripts"""
    
    def __init__(self, input_file=None, output_dir="final_output", 
                 output_format="csv", skip_validation=False, 
                 skip_prediction=False, keep_temp=False, verbose=False):
        self.input_file = input_file or "data/swt_merged_data_2015_2024.parquet"
        self.output_dir = Path(output_dir)
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.output_format = output_format
        self.skip_validation = skip_validation
        self.skip_prediction = skip_prediction
        self.keep_temp = keep_temp
        self.verbose = verbose
        self.timer = PipelineTimer()
        self.temp_files_created = []
        self.script_outputs = {}
        self.justification_df = None
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.public_output_dir = Path(self.script_dir) / 'final_output'
        self.public_output_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup logging outside final_output so runtime artifacts remain download-safe.
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.logs_dir = Path(self.script_dir) / 'logs'
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.logs_dir / f"pipeline_log_{timestamp}.txt"
        self.timing_report_file = self.logs_dir / f"timing_report_{timestamp}.txt"

        self.db_engine = None
        # Batch-tracking â€” initialized here so copy_final_outputs() is safe
        # even when called independently (e.g. via API) without run_pipeline()
        self.upload_batch_id = str(uuid.uuid4())
        self.uploaded_at     = datetime.now()

    def find_input_file(self):
        """Find the SWT input file dynamically in the data folder"""
        data_dir = Path("data")
        # Check for explicitly provided file first
        if self.input_file:
            provided_path = Path(self.input_file).expanduser().resolve()
            if provided_path.exists():
                return str(provided_path)
        # Scan data folder for any parquet or csv file
        all_files = []
        for ext in ["*.parquet", "*.csv"]:
            all_files.extend(list(data_dir.glob(ext)))
        if not all_files:
            return None
        if len(all_files) == 1:
            self.log(f"  Found input file: {all_files[0].name}")
            return str(all_files[0])
        # Multiple files â€” prefer files with 'swt' in the name
        swt_files = [f for f in all_files if 'swt' in f.name.lower()]
        candidates = swt_files if swt_files else all_files
        # Among candidates pick most recently modified
        latest = max(candidates, key=lambda f: f.stat().st_mtime)
        self.log(f"  Multiple files found in data/ â€” using most recent: {latest.name}")
        for f in candidates:
            marker = 'â†’' if f == latest else ' '
            self.log(f"    {marker} {f.name}")
        return str(latest)    
            

    def stage_pipeline_input(self):
        """Deprecated: the pipeline now propagates the real input path end-to-end."""
        return None

    def log(self, message, level="INFO", include_in_console=True):
        """Log message to console and file"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] [{level}] {message}"
        
        if include_in_console:
            print(formatted)
        
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(formatted + '\n')
    
    def print_header(self, text, char="=", width=80):
        """Print formatted header"""
        print("\n" + char * width)
        print(f"  {text}")
        print(char * width)
    
    def print_step_header(self, step_num, total_steps, step_name, description=""):
        """Print step header with timing info"""
        print("\n" + "-" * 80)
        # ASCII-only output to avoid Windows console encoding crashes (cp1252)
        print(f"  Step {step_num}/{total_steps}: {step_name}")
        if description:
            print(f"     {description}")
        print("-" * 80)
    
    def print_timing_summary(self):
        """Print current timing summary"""
        # ASCII-only output to avoid Windows console encoding crashes (cp1252)
        print("\n" + "-" * 40)
        print("CURRENT TIMING SUMMARY")
        print("-" * 40)
        
        total_so_far = time.perf_counter() - self.timer.start_time
        
        for step_name, step_data in self.timer.steps.items():
            elapsed = step_data.get('elapsed')
            if elapsed is not None:
                time_str = self.timer.format_time(elapsed)
                print(f"  [OK] {step_name:<35} {time_str:>10}")
        
        print("-" * 40)
        print(f"  Elapsed so far: {self.timer.format_time(total_so_far):>35}")
        print("-" * 40)
    
    def check_file_exists(self, filepath):
        """Check if a file exists and return its size"""
        if Path(filepath).is_absolute():
            path = Path(filepath)
        elif filepath.startswith('models/') or filepath.startswith('data/'):
            path = Path(self.script_dir) / filepath
        else:
            path = self.output_dir / filepath
        if path.exists():
            size = path.stat().st_size
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / 1024 / 1024:.2f} MB"
            self.log(f"    [OK] Found: {filepath} ({size_str})")
            return True, size_str
        else:
            self.log(f"    [MISSING] {filepath}", "WARNING")
            return False, None
    
    def check_prerequisites(self, step):
        """Check if all input files for a step exist"""
        self.log(f"  Checking prerequisites...")
        all_exist = True
        for file in step['input_files']:
            exists, _ = self.check_file_exists(file)
            if not exists:
                all_exist = False
        return all_exist
    
    def verify_outputs(self, step):
        """Verify that output files were created"""
        self.log(f"  Verifying outputs...")
        all_exist = True
        for file in step['output_files']:
            exists, size = self.check_file_exists(file)
            if exists:
                self.temp_files_created.append(file)
            else:
                all_exist = False
        return all_exist
    
    def run_python_script(self, script_path, current_input_file=None):
        """Execute a Python script and capture its output"""
        try:
            self.log(f"  Executing: {script_path}")
            
            # Build command
            cmd = [sys.executable, script_path]
            
            # Pass output and models dirs so scripts save to the right places
            import copy
            sub_env = copy.copy(os.environ)
            sub_env['SWT_OUTPUT_DIR'] = str(self.output_dir.resolve())
            sub_env['SWT_MODELS_DIR'] = str(Path(self.script_dir) / 'models')
            sub_env['SWT_VALIDATED_INPUT_FILE'] = str(Path(self.input_file).expanduser().resolve())
            if current_input_file:
                sub_env['SWT_CURRENT_INPUT_FILE'] = str(Path(current_input_file).expanduser().resolve())
                sub_env['SWT_EXPECTED_STEP_INPUT_FILE'] = sub_env['SWT_CURRENT_INPUT_FILE']
            sub_env['SWT_EXPECTED_VALIDATED_FILE'] = sub_env['SWT_VALIDATED_INPUT_FILE']
            if os.path.basename(str(script_path)).startswith("5_swt_justification"):
                sub_env['SWT_SKIP_DB_SAVE'] = '1'

            # Run with or without output capture based on verbose flag
            if self.verbose:
                result = subprocess.run(
                    cmd,
                    cwd=self.script_dir,
                    env=sub_env,
                    timeout=1800  # 30 minute timeout
                )
                success = result.returncode == 0
                stdout = stderr = ""
            else:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=1800,
                    cwd=self.script_dir,
                    env=sub_env
                )
                success = result.returncode == 0
                stdout = result.stdout
                stderr = result.stderr
            
            # Store output
            self.script_outputs[script_path] = {
                'stdout': stdout,
                'stderr': stderr,
                'returncode': result.returncode
            }
            
            # Log output if verbose or if there's an error
            if self.verbose and stdout:
                for line in stdout.strip().split('\n'):
                    if line.strip():
                        self.log(f"    {line}")
            
            if not success:
                self.log(f"  [ERROR] Script failed with exit code {result.returncode}", "ERROR")
                if stderr and not self.verbose:
                    # Print full stderr so root causes (e.g., pandas export errors)
                    # are not truncated by wrapper stack traces.
                    for line in stderr.strip().split('\n'):
                        if line.strip():
                            self.log(f"    {line}", "ERROR")
                return False
            
            # Log success message if found in output
            for line in stdout.strip().split('\n'):
                # Avoid unicode glyph markers; keep stable ASCII markers.
                if 'Saved' in line or '[OK]' in line:
                    self.log(f"    {line.strip()}")
            
            return True
            
        except subprocess.TimeoutExpired:
            self.log(f"  [ERROR] Script timed out after 30 minutes", "ERROR")
            return False
        except Exception as e:
            self.log(f"  [ERROR] Failed to execute script: {str(e)}", "ERROR")
            return False
    
    def patch_validation_script(self):
        """Temporarily patch validation script to run non-interactively.

        The patched file is written to the system temp directory (not the swt/
        source folder) so Flask's debug reloader never detects a new .py file
        and does NOT restart the server â€” which was wiping _run_status and
        causing all SWT run_ids to return 404.
        """
        import tempfile
        script_path = Path(self.script_dir) / "2_swt_validation.py"
        if not script_path.exists():
            self.log(f"  âš  Validation script not found: {script_path}", "WARNING")
            return None

        with open(script_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Create patched version that auto-answers prompts
        patched_content = content.replace(
            'response = input("Do you want to proceed with these records? (yes/no): ").strip().lower()',
            'response = "yes"  # Auto-answered by pipeline orchestrator'
        )
        patched_content = patched_content.replace(
            'remove_response = input("Do you want to remove these records and proceed? (yes/no): ").strip().lower()',
            'remove_response = "no"  # Auto-answered by pipeline orchestrator'
        )

        # Fix the typo in numeric columns validation
        patched_content = patched_content.replace(
            '"total_sswt_tax_deducted"',
            '"total_swt_tax_deducted"'
        )

        # Write to temp dir â€” outside Flask's watched source tree
        tmp_dir = Path(tempfile.gettempdir())
        patched_path = tmp_dir / "2_swt_validation_patched.py"
        with open(patched_path, 'w', encoding='utf-8') as f:
            f.write(patched_content)

        self.log(f"  [OK] Created patched validation script (in temp dir)")
        return patched_path

    def patch_justification_script(self):
        """Patch justification script to use PGK currency.

        Same as patch_validation_script: written to temp dir to avoid
        triggering Flask's debug reloader.
        """
        import tempfile
        script_path = Path(self.script_dir) / "5_swt_justification.py"
        if not script_path.exists():
            self.log(f"  âš  Justification script not found: {script_path}", "WARNING")
            return script_path

        with open(script_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Update currency symbol
        content = content.replace('(Rs.', '(PGK')
        content = content.replace('Rs.', 'PGK')

        tmp_dir = Path(tempfile.gettempdir())
        patched_path = tmp_dir / "5_swt_justification_patched.py"
        with open(patched_path, 'w', encoding='utf-8') as f:
            f.write(content)

        self.log(f"  [OK] Created patched justification script (PGK currency, in temp dir)")
        return patched_path
    
     
    def analyze_output_files(self):
        """Analyze and summarize output files"""
        self.log("\n Analyzing output files...")
        
        analysis = {}
        
        # Analyze main justification file
        justification_file = self.output_dir / "swt_fraud_justification.parquet"
        if justification_file.exists():
            with Timer("Load justification data") as t:
                df = _read_dataframe(justification_file, "analyze_output_files")
            self.log(f"  Loaded justification data in {t.elapsed_formatted}")
            
            total_records = len(df)
            fraud_count = (df['predicted_fraud'] == 'Fraud').sum()
            non_fraud_count = total_records - fraud_count
            
            analysis['justification'] = {
                'total_records': total_records,
                'fraud_count': fraud_count,
                'non_fraud_count': non_fraud_count,
                'fraud_percentage': fraud_count / total_records * 100
            }
            
            self.log(f"    Total Records: {total_records:,}")
            self.log(f"    Fraud Detected: {fraud_count:,} ({fraud_count/total_records*100:.2f}%)")
            self.log(f"    Non-Fraud: {non_fraud_count:,} ({non_fraud_count/total_records*100:.2f}%)")
            
            # Year distribution
            if 'tax_period_year' in df.columns:
                year_counts = df['tax_period_year'].value_counts().sort_index()
                self.log(f"    Year Distribution:")
                for year, count in year_counts.items():
                    fraud_in_year = ((df['tax_period_year'] == year) & (df['predicted_fraud'] == 'Fraud')).sum()
                    self.log(f"      {year}: {count:,} records ({fraud_in_year:,} fraud)")
        
        # Analyze cleaned data
        cleaned_file = self.output_dir / "swt_cleaned_data.parquet"
        removed_file = self.output_dir / "swt_removed_data.parquet"
        
        if cleaned_file.exists():
            df_cleaned = _read_dataframe(cleaned_file, "analyze_output_files")
            analysis['cleaned'] = {'records': len(df_cleaned)}
            
            if removed_file.exists():
                df_removed = _read_dataframe(removed_file, "analyze_output_files")
                analysis['removed'] = {'records': len(df_removed)}
                self.log(f"    Records Kept: {len(df_cleaned):,}")
                self.log(f"    Records Removed: {len(df_removed):,}")
        
        return analysis
    
    def print_final_output_table(self):
        """Print a summary table of fraud justification results in terminal"""
        justification_file = self.output_dir / "swt_fraud_justification.parquet"
        if not justification_file.exists():
            self.log("  âš  Justification file not found, skipping table print", "WARNING")
            return

        df = _read_dataframe(justification_file, "print_final_output_table")

        print("\n" + "=" * 80)
        print("  FINAL FRAUD JUSTIFICATION OUTPUT - PREVIEW (first 20 rows)")
        print("=" * 80)

        display_cols = [col for col in [
            'tin', 'taxpayer_name', 'tax_period_year', 'tax_period_month',
            'predicted_fraud', 'fraud_probability', 'rules_violated', 'explanation'
        ] if col in df.columns]

        preview = df[display_cols].head(20)

       # Print each row clearly
        for idx, row in preview.iterrows():
            print(f"\n  Row {idx + 1}:")
            for col in display_cols:
                val = str(row[col])
                if len(val) > 80:
                   val = val[:77] + "..."
                print(f"    {col:<25}: {val}")
            print("  " + "-" * 78)

        print(f"\n  Total records in output: {len(df):,}")
        fraud_total = (df['predicted_fraud'] == 'Fraud').sum()
        print(f"  Fraud: {fraud_total:,}  |  Non-Fraud: {len(df) - fraud_total:,}")
        print("=" * 80)

    def copy_final_outputs(self):
        """Copy final outputs to the output directory"""
        self.log("\n Copying final outputs to destination...")
 
        final_files = [
        #"swt_removed_data.csv",
       # "swt_validation_log.txt"
        ]

        copied = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for file in final_files:
          src = Path(file)
          if src.exists():
            dst = self.output_dir / src.name
            shutil.copy2(src, dst)
            size = src.stat().st_size / 1024 / 1024
            self.log(f"  [OK] Copied: {src.name} ({size:.2f} MB)")
            copied.append(str(dst))

        # Create timestamped public CSV artifacts for the retention policy.
        try:
          artifact_bases = [
            ("swt_fraud_justification.csv", f"swt_fraud_justification_{timestamp}.csv"),
            ("swt_validated.csv", f"swt_validated_{timestamp}.csv"),
            ("swt_removed_data.csv", f"swt_removed_data_{timestamp}.csv"),
          ]
          for base, final_name in artifact_bases:
            src = self.output_dir / base
            if not src.exists():
              continue
            dst = self.public_output_dir / final_name
            shutil.copy2(src, dst)
            copied.append(str(dst))
            self.log(f"  [OK] Timestamped copy: {dst.name}")
        except Exception as _e:
          self.log(f"  [WARN] Could not create timestamped copies: {_e}", "WARNING")

        # Preserve the current-run justification dataframe for the route-level
        # background insert thread. The route is the only production insert owner.
        justification_src = self.output_dir / "swt_fraud_justification.parquet"
        if justification_src.exists():
           try:
              just_df = _read_dataframe(justification_src, "copy_final_outputs")
              self.justification_df = just_df.copy(deep=True)

              # Defensive: strip column whitespace to avoid schema mismatch issues.
              try:
                self.justification_df.columns = self.justification_df.columns.astype(str).str.strip()
              except Exception:
                pass

              # Add batch tracking metadata to the in-memory dataframe that will be
              # handed to save_swt_justification_to_db() exactly once by the route.
              if hasattr(self, 'upload_batch_id') and self.upload_batch_id:
                self.justification_df['upload_batch_id'] = self.upload_batch_id
              if hasattr(self, 'uploaded_at') and self.uploaded_at:
                self.justification_df['uploaded_at'] = self.uploaded_at
              self.log("  Prepared current-run justification dataframe for background DB insert")
           except Exception as e:
            self.log(f"  [WARN] Could not prepare justification dataframe for DB insert: {e}", "WARNING")
            try:
              import traceback as _traceback
              self.log(_traceback.format_exc(), "WARNING")
            except Exception:
              pass            

        return copied
    
    def generate_summary_report(self, analysis):
        """Generate a comprehensive summary report"""
        report_path = self.logs_dir / "pipeline_summary_report.txt"
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("SWT FRAUD DETECTION PIPELINE - EXECUTION SUMMARY\n")
            f.write("=" * 80 + "\n\n")
            
            f.write(f"Execution Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total Execution Time: {self.timer.total_elapsed_formatted}\n\n")
            
            # Pipeline results
            f.write("-" * 80 + "\n")
            f.write("PIPELINE RESULTS\n")
            f.write("-" * 80 + "\n\n")
            
            if 'justification' in analysis:
                j = analysis['justification']
                f.write(f"Total Records Processed: {j['total_records']:,}\n")
                f.write(f"Fraud Detected: {j['fraud_count']:,} ({j['fraud_percentage']:.2f}%)\n")
                f.write(f"Non-Fraud: {j['non_fraud_count']:,}\n\n")
            
            if 'cleaned' in analysis and 'removed' in analysis:
                f.write(f"Records After Cleaning: {analysis['cleaned']['records']:,}\n")
                f.write(f"Records Removed During Validation: {analysis['removed']['records']:,}\n\n")
            
            # Step execution times
            f.write("-" * 80 + "\n")
            f.write("STEP EXECUTION TIMES\n")
            f.write("-" * 80 + "\n")
            f.write(f"{'Step':<45} {'Time':<15} {'%':<10}\n")
            f.write("-" * 80 + "\n")
            
            total = self.timer.total_elapsed or 1
            for step_name, step_data in self.timer.steps.items():
                elapsed = step_data.get('elapsed', 0)
                percentage = (elapsed / total * 100) if total > 0 else 0
                time_str = self.timer.format_time(elapsed)
                f.write(f"{step_name:<45} {time_str:<15} {percentage:.1f}%\n")
            
            # Output files
            f.write("\n" + "-" * 80 + "\n")
            f.write("OUTPUT FILES GENERATED\n")
            f.write("-" * 80 + "\n")
            for file in sorted(self.output_dir.glob("*")):
                if file.is_file():
                    size = file.stat().st_size / 1024 / 1024
                    f.write(f"  {file.name}: {size:.2f} MB\n")
        
        self.log(f"\n Summary report saved to: {report_path}")
    
    def cleanup_temp_files(self):
        if self.keep_temp:
            self.log("\n Keeping temporary files (--keep-temp flag used)")
            return
        self.log("\n Cleaning up temporary files...")
        # Protect the input file from deletion
        protected = set()
        if self.input_file:
            protected.add(os.path.abspath(self.input_file))
        if self.keep_temp:
            self.log("\n Keeping temporary files (--keep-temp flag used)")
            return
        
        self.log("\n Cleaning up temporary files...")
        # Delete timestamped log and timing report files from output dir FIRST
        for pattern in ["pipeline_log_*.txt", "timing_report_*.txt"]:
            for file in self.output_dir.glob(pattern):
                try:
                    file.unlink()
                    self.log(f"  Removed: {file.name}")
                except Exception as e:
                    self.log(f"  Could not remove {file.name}: {e}", "WARNING")
    
        
        # Then delete intermediate working files
        temp_patterns = [
         "*_patched.py",
         "filtering_auto.py",
         #"swt_standardized.parquet",
         #"swt_removed_data.parquet",    
         "swt_removed_data.parquet",
          #"swt_data_after_taxpayer_name_mapping.parquet",
          "swt_data_after_rule_checking.parquet",
          #"swt_cleaned_data.parquet",
          "fraud_predictions_full.parquet",
          "fraud_predictions_full.csv",
          "filtered_2015_2019.csv",
          "filtered_2020_2025.csv",
            #"swt_validation_log.txt"
        ]
        
        data_dir_abs = os.path.abspath(str(Path(self.script_dir) / "data"))
        # Also clean patched scripts from script_dir
        for pat in ["*_patched.py", "filtering_auto.py"]:
            for file in Path(self.script_dir).glob(pat):
                try:
                    file.unlink()
                    self.log(f"  Removed: {file.name}")
                except Exception:
                    pass
        for pattern in temp_patterns:
            for file in self.output_dir.glob(pattern):
                if os.path.abspath(file) in protected:
                    self.log(f"  Skipped (input file): {file.name}")
                    continue
                # Never delete anything inside the data/ folder
                if os.path.abspath(file).startswith(data_dir_abs):
                    self.log(f"  Skipped (data folder): {file.name}")
                    continue
                try:
                    file.unlink()
                    self.log(f"  Removed: {file.name}")
                except Exception as e:
                    self.log(f"  Could not remove {file.name}: {e}", "WARNING")


    def run(self):
        """Execute the complete pipeline with detailed timing"""
        
        # Start pipeline timer
        start_datetime = self.timer.start_pipeline()
        self.upload_batch_id = str(uuid.uuid4())
        self.uploaded_at     = datetime.now()
        self.log(f"Upload Batch ID: {self.upload_batch_id}")
        self.print_header("SWT FRAUD DETECTION PIPELINE", "=", 80)
        print(f"Starting pipeline execution...")
        print(f" Started at: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        provided_input = self.input_file
        resolved_input = None
        if self.input_file:
            candidate = Path(self.input_file).expanduser().resolve()
            if candidate.exists():
                resolved_input = str(candidate)

        print("=" * 50)
        print("[SWT PIPELINE INPUT]")
        print(f"Provided input : {provided_input}")
        print(f"Exists         : {bool(resolved_input)}")
        print(f"Resolved path  : {resolved_input}")
        print("=" * 50)
        self.log("=" * 50)
        self.log("[SWT PIPELINE INPUT]")
        self.log(f"Provided input : {provided_input}")
        self.log(f"Exists         : {bool(resolved_input)}")
        self.log(f"Resolved path  : {resolved_input}")
        self.log("=" * 50)

        # Resolve input file dynamically only when no valid input was supplied
        self.input_file = resolved_input or self.find_input_file()
        if not self.input_file:
            print(" No input file found in data/ folder. Aborting.")
            return False
        self.input_file = str(Path(self.input_file).expanduser().resolve())
        print(f" Input file: {self.input_file}")
        print(f" Output directory: {self.output_dir.absolute()}")
        print(f" Log file: {self.log_file.absolute()}")
        
        self.log(f"Pipeline started at: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        self.log(f"Input file: {self.input_file}")
        self.log(f"Output directory: {self.output_dir.absolute()}")
        
        # Patch scripts for non-interactive execution
        print("\n Preparing scripts for automated execution...")
        with Timer("Script Patching") as t:
            #validation_script = self.patch_validation_script()
            justification_script = self.patch_justification_script()
        print(f"   Scripts patched in {t.elapsed_formatted}")
        
        # if validation_script:
        #     for step in PipelineConfig.PIPELINE_STEPS:
        #         if step['script'] == '2_swt_validation.py':
        #             step['script'] = str(validation_script)
        
        if justification_script:
            for step in PipelineConfig.PIPELINE_STEPS:
                if step['script'] == '5_swt_justification.py':
                    step['script'] = str(justification_script)
        
        # Determine which steps to run
        steps_to_run = []
        for step in PipelineConfig.PIPELINE_STEPS:
            if step['script'] == '4_swt_fraud_prediction.py':
                print(f"\n[SKIP] Skipping: {step['name']} (not required - step 5 handles prediction)")
                self.log(f"[SKIP] Skipping step: {step['name']} (redundant with step 5)")
                continue
            steps_to_run.append(step)
        
        # Execute pipeline steps
        total_steps = len(steps_to_run)
        pipeline_success = True
        step_input_map = {
            '3_swt_feature_engineering.py': self.input_file,
            '4_swt_fraud_prediction.py': str((self.output_dir / 'swt_data_after_rule_checking.parquet').resolve()),
            '5_swt_justification.py': str((self.output_dir / 'swt_data_after_rule_checking.parquet').resolve()),
        }
        
        for i, step in enumerate(steps_to_run, 1):
            self.print_step_header(i, total_steps, step['name'], step.get('description', ''))
            
            # Start timing this step
            self.timer.start_step(step['name'])
            
            # Check prerequisites
            if not self.check_prerequisites(step):
                self.log(f"   Prerequisites not met for: {step['name']}", "ERROR")
                if step['required']:
                    pipeline_success = False
                    break
                else:
                    self.log("  [SKIP] Skipping optional step", "WARNING")
                    self.timer.end_step(step['name'])
                    continue
            
            # Execute the step
            step_start = time.perf_counter()
            script_path = Path(step['script'])
            step_input_file = step_input_map.get(script_path.name, self.input_file)

            print(f"  [START] {datetime.now().strftime('%H:%M:%S')} - running {script_path.name} ...")
            print(f"  Step input file: {step_input_file}")
            self.log(f"Step input file for {script_path.name}: {step_input_file}")

            if script_path.suffix == '.py':
                 success = self.run_python_script(str(script_path), current_input_file=step_input_file)
            else:
                 self.log(f"   Unknown script type: {step['script']}", "ERROR")
                 success = False
            
            # End timing this step
            self.timer.end_step(step['name'])
            step_time = time.perf_counter() - step_start
            
            if success:
                self.log(f"   Step completed in {self.timer.format_time(step_time)}")
            else:
                self.log(f"   Step failed: {step['name']}", "ERROR")
                if step['required']:
                    pipeline_success = False
                    break
            
            # Verify outputs
            self.verify_outputs(step)
            
            # Print current timing summary
            self.print_timing_summary()
        if pipeline_success:
            # Analyze output files
         analysis = self.analyze_output_files()
            
            # Print final output table in terminal
         self.print_final_output_table()

            # Copy final outputs
         self.copy_final_outputs()
            
            # Generate summary report
         self.generate_summary_report(analysis)
        
        # End pipeline timer
        self.timer.end_pipeline()
        
        # Save detailed timing report
        self.timer.save_report(self.timing_report_file)
        
        # Cleanup temporary files
        self.cleanup_temp_files()
        
        # Final status
        self.print_header("PIPELINE EXECUTION COMPLETE", "=", 80)
        
        if pipeline_success:
            print(f"\n SUCCESS - All steps completed successfully")
            print(f"\n TOTAL EXECUTION TIME: {self.timer.total_elapsed_formatted}")
            print(f"\n Final outputs saved to: {self.output_dir.absolute()}")
            print(f" Timing report saved to: {self.timing_report_file.absolute()}")
            
            # Display timing summary
            print("\n" + self.timer.generate_timing_report())
            
            # Display final file listing
            print("\n Final Output Files:")
            for file in sorted(self.output_dir.glob("*")):
                if file.is_file():
                    size = file.stat().st_size
                    if size < 1024 * 1024:
                        size_str = f"{size / 1024:.1f} KB"
                    else:
                        size_str = f"{size / 1024 / 1024:.2f} MB"
                    print(f"   - {file.name} ({size_str})")
        else:
            print(f"\n FAILED - Pipeline did not complete successfully")
            print(f"   Check log file for details: {self.log_file.absolute()}")
        
        return pipeline_success


# ============================================================================
# COMMAND LINE INTERFACE
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="SWT Fraud Detection Pipeline Orchestrator with Detailed Timing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_swt_pipeline.py
  python run_swt_pipeline.py --skip-prediction --keep-temp
  python run_swt_pipeline.py --input my_data.parquet --output-dir results
  python run_swt_pipeline.py --output-format parquet --verbose
  python run_swt_pipeline.py --list-steps
        """
    )
    
    parser.add_argument(
        '--input', '-i',
        type=str,
        default='data/swt_merged_data_2015_2024.parquet',
        help='Input parquet file path'
    )
    
    parser.add_argument(
        '--output-dir', '-o',
        type=str,
        default='final_output',
        help='Output directory for final results'
    )
    
    parser.add_argument(
        '--output-format', '-f',
        type=str,
        choices=['csv', 'parquet'],
        default='csv',
        help='Output format for final results'
    )
    
    parser.add_argument(
        '--skip-validation',
        action='store_true',
        help='Skip data validation steps'
    )
    
    parser.add_argument(
        '--skip-prediction',
        action='store_true',
        help='Skip ML prediction step'
    )
    
    parser.add_argument(
        '--keep-temp',
        action='store_true',
        help='Keep temporary files'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed output from each script'
    )
    
    parser.add_argument(
        '--list-steps',
        action='store_true',
        help='List all pipeline steps and exit'
    )
    
    args = parser.parse_args()
    
    # List steps if requested
    if args.list_steps:
        print("\n" + "=" * 80)
        print("  SWT Fraud Detection Pipeline Steps")
        print("=" * 80)
        print()
        for i, step in enumerate(PipelineConfig.PIPELINE_STEPS, 1):
            required = "[REQUIRED]" if step['required'] else "[OPTIONAL]"
            print(f"  {i}. {step['name']} {required}")
            print(f"     Script: {step['script']}")
            print(f"     Description: {step.get('description', 'N/A')}")
            print(f"     Inputs: {', '.join(step['input_files'])}")
            print(f"     Outputs: {', '.join(step['output_files'])}")
            print()
        return 0
    
    # Run the pipeline
    print()
    print("â•”" + "â•" * 78 + "â•—")
    print("â•‘" + "SWT FRAUD DETECTION PIPELINE - WITH DETAILED TIMING".center(78) + "â•‘")
    print("â•š" + "â•" * 78 + "â•")
    
    orchestrator = SWTPipelineOrchestrator(
        input_file=args.input,
        output_dir=args.output_dir,
        output_format=args.output_format,
        skip_validation=args.skip_validation,
        skip_prediction=args.skip_prediction,
        keep_temp=args.keep_temp,
        verbose=args.verbose
    )
    
    success = orchestrator.run()
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())



