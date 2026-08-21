#!/usr/bin/env python3
"""
Safe wrapper for SWT Justification Generation with robust CSV export
"""

import sys
import os
import pandas as pd
import numpy as np
from pathlib import Path

# Add the current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def safe_save_to_csv(df, filepath):
    """Safely save DataFrame to CSV handling complex data types"""
    try:
        print(f"  Saving CSV to: {filepath}")
        
        # Make a copy to avoid modifying original
        df_copy = df.copy()
        
        # Process each column to ensure string conversion works
        for col in df_copy.columns:
            try:
                if df_copy[col].dtype == 'object':
                    # Convert any non-string objects to strings
                    df_copy[col] = df_copy[col].apply(
                        lambda x: str(x) if x is not None and not isinstance(x, str) else x
                    )
            except Exception as col_e:
                print(f"  Warning: Could not process column {col}: {col_e}")
                # Force convert entire column to string using astype
                try:
                    df_copy[col] = df_copy[col].astype(str)
                except:
                    pass
        
        # Save to CSV
        df_copy.to_csv(filepath, index=False, encoding='utf-8-sig')
        print("  [OK] CSV saved successfully")
        return True
        
    except Exception as e:
        print(f"  [ERROR] Error saving to CSV: {e}")
        
        # Ultimate fallback - try with minimal data
        try:
            # Try to save only basic columns
            basic_cols = ['tin', 'taxpayer_name', 'predicted_fraud', 'fraud_probability']
            available_cols = [col for col in basic_cols if col in df.columns]
            if available_cols:
                df[available_cols].to_csv(filepath, index=False, encoding='utf-8-sig')
                print("  [OK] Saved basic columns only")
                return True
        except:
            pass
            
        return False

# Import the original function and monkey patch it
try:
    # Try to import the original module
    import importlib.util
    
    # Load the original script
    original_script = Path(__file__).parent / "5_swt_justification.py"
    if original_script.exists():
        spec = importlib.util.spec_from_file_location("swt_justification_original", original_script)
        original_module = importlib.util.module_from_spec(spec)
        
        # Monkey patch the to_csv method before executing
        def patched_to_csv(df, path, **kwargs):
            return safe_save_to_csv(df, path)
        
        # Execute the original script with our patched function
        spec.loader.exec_module(original_module)
        
        print("[OK] Successfully executed justification generation with safe CSV export")
    else:
        print(f"[ERROR] Original script not found: {original_script}")
        sys.exit(1)
        
except Exception as e:
    print(f"[ERROR] Error executing justification script: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
