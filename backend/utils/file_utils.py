# utils/file_utils.py
# Shared file handling helpers for CIT, GST, SWT pipelines

import os
from pathlib import Path

import pandas as pd


_DEFAULT_EC2_BACKEND_ROOT = Path("/var/www/rbatool/backend")


def get_backend_root_dir():
    """
    Resolve the backend root directory safely for local Windows dev and Linux/EC2.
    """
    override = (os.getenv("RBA_BACKEND_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()

    if os.name != "nt" and _DEFAULT_EC2_BACKEND_ROOT.exists():
        return _DEFAULT_EC2_BACKEND_ROOT

    return Path(__file__).resolve().parents[1]


def get_backend_storage_dir(*parts):
    """
    Build an absolute backend-owned storage path and ensure it exists.
    """
    directory = get_backend_root_dir().joinpath(*parts)
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory)


def get_backend_upload_dir():
    """
    Central resolver for the shared backend uploads directory.
    Allows an explicit env override via `RBA_UPLOAD_DIR`.
    """
    override = (os.getenv("RBA_UPLOAD_DIR") or "").strip()
    if override:
        directory = Path(override).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        return str(directory)

    return get_backend_storage_dir("uploads")


def detect_and_load(directory="."):
    """
    Scans a directory for .csv or .parquet files.
    If one file found, loads it automatically.
    If multiple found, prompts user to choose.
    Returns (dataframe, filename).
    """
    supported = [".csv", ".parquet"]
    found = [f for f in os.listdir(directory)
             if any(f.endswith(ext) for ext in supported)]

    if not found:
        raise FileNotFoundError(
            f"No .csv or .parquet file found in: {directory}"
        )

    if len(found) > 1:
        print("Multiple files found:")
        for i, f in enumerate(found):
            print(f"  [{i}] {f}")
        choice = int(input("Enter the number of the file to use: "))
        filename = found[choice]
    else:
        filename = found[0]
        print(f"Auto-detected file: {filename}")

    filepath = os.path.join(directory, filename)
    df = load_file(filepath)
    return df, filename


def load_file(filepath):
    """
    Loads a .csv or .parquet file into a DataFrame.
    Raises ValueError for unsupported formats.
    """
    if filepath.endswith(".parquet"):
        df = pd.read_parquet(filepath)
    elif filepath.endswith(".csv"):
        df = pd.read_csv(filepath)
    else:
        raise ValueError(
            f"Unsupported file format: {filepath}. "
            "Only .csv and .parquet are accepted."
        )
    print(f"Loaded: {filepath} | shape: {df.shape}")
    return df


def validate_extension(filename):
    """
    Returns True if file is .csv or .parquet, False otherwise.
    Used by API upload routes before processing begins.
    """
    return filename.lower().endswith((".csv", ".parquet"))


def cleanup_files(file_list):
    """
    Deletes a list of intermediate/temp files.
    Silently skips files that don't exist.
    """
    for f in file_list:
        try:
            if os.path.exists(f):
                os.remove(f)
                print(f"  Deleted: {f}")
        except Exception as e:
            print(f"  Could not delete {f}: {e}")


def save_outputs(df, base_name, formats=("csv",)):
    """
    Saves a DataFrame to one or more formats.
    formats can include 'csv' and/or 'parquet'.
    Returns list of saved filenames.
    """
    saved = []
    for fmt in formats:
        if fmt == "csv":
            path = f"{base_name}.csv"
            df.to_csv(path, index=False)
        elif fmt == "parquet":
            path = f"{base_name}.parquet"
            df.to_parquet(path, index=False)
        else:
            print(f"  Warning: unknown format '{fmt}', skipping.")
            continue
        print(f"  Saved: {path}")
        saved.append(path)
    return saved
