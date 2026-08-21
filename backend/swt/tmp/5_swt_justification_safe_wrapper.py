#!/usr/bin/env python3
        """Safe wrapper for SWT Justification Generation"""

        import sys
        import os
        import pandas as pd
        import numpy as np
        from pathlib import Path

        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        def safe_save_to_csv(df, filepath):
            try:
                df_copy = df.copy()
                for col in df_copy.columns:
                    if df_copy[col].dtype == 'object':
                        df_copy[col] = df_copy[col].apply(
                            lambda x: str(x) if x is not None and not isinstance(x, str) else x
                        )
                df_copy.to_csv(filepath, index=False, encoding='utf-8-sig')
                return True
            except Exception as e:
                print(f"Warning: CSV save failed - {e}")
                try:
                    basic_cols = ['tin', 'taxpayer_name', 'predicted_fraud', 'fraud_probability']
                    available_cols = [col for col in basic_cols if col in df.columns]
                    if available_cols:
                        df[available_cols].to_csv(filepath, index=False, encoding='utf-8-sig')
                        return True
                except:
                    pass
                return False

        # Execute original script
        original_script = Path(__file__).parent / "5_swt_justification.py"
        if original_script.exists():
            with open(original_script, 'r', encoding='utf-8') as f:
                code = f.read()
            
            # Replace to_csv calls
            import re
            code = re.sub(r'df\.to_csv\([^)]+\)', 'safe_save_to_csv(df, out_csv)', code)
            
            # Add safe_save_to_csv to the namespace
            exec(code, {'__name__': '__main__', 'safe_save_to_csv': safe_save_to_csv, 
                        'pd': pd, 'np': np, 'Path': Path})
        else:
            print(f"Original script not found: {original_script}")
            sys.exit(1)
        