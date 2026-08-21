# gst_registration_merger.py
import logging
import pandas as pd
from gst_validator import load_and_clean_registration_data, clean_columns, get_taxpayer_name_col
import os
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

logger = logging.getLogger(__name__)


def _normalize_tin_series(s: pd.Series) -> pd.Series:
    """
    Normalize TIN to match DB column `normalized_tin`:
    - cast to string
    - strip non-digits
    - left-pad to 9 digits when shorter
    """
    # Fix common float-cast artifacts like "500000198.0"
    s = (
        s.astype(str)
        .fillna("")
        .str.replace(".0", "", regex=False)
        .str.strip()
    )
    digits = s.str.replace(r'\D+', '', regex=True)
    digits = digits.apply(lambda x: x.zfill(9) if isinstance(x, str) and 0 < len(x) < 9 else x)
    return digits


def _fetch_taxpayer_names_from_db(normalized_tins):
    """
    Fetch taxpayer names from MySQL table `tin_registration_mst` using `normalized_tin`.
    Returns mapping dict: {normalized_tin: taxpayer_name}
    """
    # Import lazily to avoid pulling DB deps at import time
    from config.db_config import get_mysql_engine
    from sqlalchemy import text, bindparam

    normalized_tins = [t for t in normalized_tins if isinstance(t, str) and t.strip() != ""]
    if not normalized_tins:
        return {}

    engine = get_mysql_engine()
    try:
        mapping = {}
        # Chunk to keep IN list reasonable
        chunk_size = 1000
        with engine.connect() as conn:
            for i in range(0, len(normalized_tins), chunk_size):
                chunk = normalized_tins[i:i + chunk_size]
                q = text("""
                    SELECT normalized_tin, taxpayername
                    FROM tin_registration_mst
                    WHERE normalized_tin IN :tins
                """).bindparams(bindparam("tins", expanding=True))
                rows = conn.execute(q, {"tins": chunk}).fetchall()
                for norm_tin, taxpayername in rows:
                    if norm_tin is None:
                        continue
                    mapping[str(norm_tin)] = taxpayername
        return mapping
    finally:
        engine.dispose()


# Simple in-process cache (speeds up repeated validations in a dev server)
_TIN_NAME_CACHE = {}


def merge_taxpayer_names(gst_df):
    """
    Merge taxpayer names from registration data with GST data
    """
    # First check for existing taxpayer name columns in gst_df (case insensitive)
    existing_taxpayer_cols = [
        col for col in gst_df.columns 
        if col.lower().replace('_', '') in ['taxpayer', 'taxpayername', 'taxpayer_name', 'tax_payer', 'tax_payer_name']
    ]
    
    # Determine if we need to perform the merge
    perform_merge = False
    
    if existing_taxpayer_cols:
        # If taxpayer name column exists but has null values
        if gst_df[existing_taxpayer_cols[0]].isnull().any():
            perform_merge = True
        else:
            perform_merge = False
    else:
        perform_merge = True
    
    if perform_merge:
        # Prefer DB-backed mapping (tin_registration_mst.normalized_tin)
        if 'tin' in gst_df.columns:
            gst_df['tin'] = (
                gst_df['tin']
                .astype(str)
                .str.replace(".0", "", regex=False)
                .str.strip()
            )
            gst_df['_normalized_tin'] = _normalize_tin_series(gst_df['tin'])

            uniq = gst_df['_normalized_tin'].dropna().astype(str).unique().tolist()
            # Serve from cache when available, query only missing tins
            missing = [t for t in uniq if t not in _TIN_NAME_CACHE]
            if missing:
                try:
                    fetched = _fetch_taxpayer_names_from_db(missing)
                    _TIN_NAME_CACHE.update(fetched)
                except Exception:
                    pass
            db_map = {t: _TIN_NAME_CACHE.get(t) for t in uniq if _TIN_NAME_CACHE.get(t) is not None}

            if db_map:
                gst_df['_reg_taxpayer_name'] = gst_df['_normalized_tin'].map(db_map)

                if existing_taxpayer_cols:
                    existing_col = existing_taxpayer_cols[0]
                    gst_df[existing_col] = gst_df[existing_col].fillna(gst_df['_reg_taxpayer_name'])
                else:
                    gst_df['taxpayer_name'] = gst_df['_reg_taxpayer_name']

                gst_df.drop(columns=['_reg_taxpayer_name'], inplace=True)
            else:
                logger.warning(
                    "GST taxpayer lookup returned no rows from tin_registration_mst; "
                    "continuing without local registration-file fallback."
                )

            gst_df.drop(columns=['_normalized_tin'], inplace=True, errors='ignore')

    # Ensure taxpayer_name appears immediately after tin in validated dataframe
    try:
        cols = gst_df.columns.tolist()
        taxpayer_col = 'taxpayer_name' if 'taxpayer_name' in cols else (existing_taxpayer_cols[0] if existing_taxpayer_cols else None)
        if taxpayer_col and 'tin' in cols and taxpayer_col in cols and taxpayer_col != 'tin':
            cols.remove(taxpayer_col)
            tin_index = cols.index('tin')
            cols.insert(tin_index + 1, taxpayer_col)
            gst_df = gst_df[cols]
    except Exception:
        pass

    return gst_df

def finalize_gst_dataframe(gst_df):
    """
    Finalize the GST dataframe structure
    """
    # Get all possible taxpayer column names (case insensitive)
    possible_cols = ['taxpayer', 'taxpayername', 'taxpayer_name', 'tax_payer', 'tax_payer_name']
    existing_col = next((col for col in gst_df.columns 
                        if col.lower().replace('_', '') in [c.lower().replace('_', '') for c in possible_cols]), 
                       'taxpayer_name')
    
    # Get original columns (excluding any possible taxpayer name columns)
    original_columns = [col for col in gst_df.columns 
                       if col.lower().replace('_', '') not in [c.lower().replace('_', '') for c in possible_cols]]
    
    # Reconstruct DataFrame with desired order (taxpayer column after TIN)
    gst_df = gst_df[original_columns[:1] + [existing_col] + original_columns[1:]]
    
    return gst_df

def run_full_validation_pipeline(gst_df):
    """
    Run the full GST validation and cleaning pipeline
    """
    # Validate columns
    from gst_validator import validate_gst_columns
    is_valid, message = validate_gst_columns(gst_df)
    
    if not is_valid:
        return None, None, message
    
    # Clean data
    cleaned_df, removed_df = validate_gst_columns(gst_df)
    
    # Merge taxpayer names
    cleaned_df = merge_taxpayer_names(cleaned_df)
    
    # Finalize dataframe
    finalized_df = finalize_gst_dataframe(cleaned_df)
    
    # Save final validated data
    finalized_df.to_parquet("gst_validated.parquet", index=False)
    
    return finalized_df, removed_df, "Validation and cleaning completed successfully"

