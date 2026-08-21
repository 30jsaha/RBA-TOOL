"""
regenerate_pkls.py
──────────────────
Run this script ONCE from the gst/ project directory to rebuild all four
pipeline pickle files from the current .py source files.

    cd E:\Payel_dataScience\project_IRC\gst
    python regenerate_pkls.py

After it completes you will see:
    ✔  gst_column_standardizer.pkl
    ✔  gst_validation_pipeline.pkl
    ✔  gst_fraud_detector.pkl
    ✔  gst_fraud_justification.pkl
"""

import pickle
import os
import sys

# ── Make sure we're running from the gst/ directory ───────────────────────────
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

print(f"\nWorking directory: {os.getcwd()}")
print("Regenerating pipeline pkl files...\n")

errors = []

# ── 1. gst_column_standardizer.pkl ────────────────────────────────────────────
try:
    from gst_column_standardizer import standardize_gst_columns, get_standardized_columns, save_standardized_data

    standardizer_funcs = {
        'standardize_gst_columns':  standardize_gst_columns,
        'get_standardized_columns': get_standardized_columns,
        'save_standardized_data':   save_standardized_data,
    }

    with open('gst_column_standardizer.pkl', 'wb') as f:
        pickle.dump(standardizer_funcs, f)
    print("  ✔  gst_column_standardizer.pkl")

except Exception as e:
    print(f"  ✘  gst_column_standardizer.pkl  →  {e}")
    errors.append('gst_column_standardizer.pkl')


# ── 2. gst_validation_pipeline.pkl ────────────────────────────────────────────
try:
    from gst_validator import (
        validate_gst_columns,
        validate_and_clean_gst_data,
        clean_columns,
        get_taxpayer_name_col,
        load_and_clean_registration_data,
    )

    validation_funcs = {
        'validate_gst_columns':             validate_gst_columns,
        'validate_and_clean_gst_data':      validate_and_clean_gst_data,
        'clean_columns':                    clean_columns,
        'get_taxpayer_name_col':            get_taxpayer_name_col,
        'load_and_clean_registration_data': load_and_clean_registration_data,
    }

    with open('gst_validation_pipeline.pkl', 'wb') as f:
        pickle.dump(validation_funcs, f)
    print("  ✔  gst_validation_pipeline.pkl")

except Exception as e:
    print(f"  ✘  gst_validation_pipeline.pkl  →  {e}")
    errors.append('gst_validation_pipeline.pkl')


# ── 3. gst_fraud_detector.pkl ─────────────────────────────────────────────────
try:
    from gst_fraud_detector import add_fraud_detection_features, get_required_columns

    detector_funcs = {
        'add_fraud_detection_features': add_fraud_detection_features,
        'get_required_columns':         get_required_columns,
    }

    with open('gst_fraud_detector.pkl', 'wb') as f:
        pickle.dump(detector_funcs, f)
    print("  ✔  gst_fraud_detector.pkl")

except Exception as e:
    print(f"  ✘  gst_fraud_detector.pkl  →  {e}")
    errors.append('gst_fraud_detector.pkl')


# ── 4. gst_fraud_justification.pkl ────────────────────────────────────────────
try:
    from gst_fraud_justification import create_gst_fraud_justification_file, get_required_columns as just_get_required_columns

    justification_funcs = {
        'create_gst_fraud_justification_file': create_gst_fraud_justification_file,
        'get_required_columns':                just_get_required_columns,
    }

    with open('gst_fraud_justification.pkl', 'wb') as f:
        pickle.dump(justification_funcs, f)
    print("  ✔  gst_fraud_justification.pkl")

except Exception as e:
    print(f"  ✘  gst_fraud_justification.pkl  →  {e}")
    errors.append('gst_fraud_justification.pkl')


# ── Summary ───────────────────────────────────────────────────────────────────
print()
if errors:
    print(f"  ⚠  {len(errors)} pkl(s) failed to regenerate: {', '.join(errors)}")
    print("     Fix the import errors above and re-run this script.")
    sys.exit(1)
else:
    print("  All 4 pkl files regenerated successfully.")
    print("  Restart the API and run the pipeline — the taxpayer name warning should be gone.\n")
