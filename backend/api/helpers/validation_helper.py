import os
import uuid
from datetime import datetime


def normalize_tax_type(tax_type: object) -> str:
    try:
        return str(tax_type or "").strip().lower()
    except Exception:
        return ""


def normalize_column(col: object) -> str:
    try:
        s = str(col or "")
    except Exception:
        return ""
    return s.strip().lower().replace(" ", "_").replace("-", "_")


def safe_seek0(file_storage) -> None:
    """
    Ensure the underlying stream is rewound before any read/save/csv parsing.
    Works with werkzeug FileStorage or file-like objects.
    """
    try:
        if file_storage is None:
            return
        # werkzeug FileStorage has `.stream`
        stream = getattr(file_storage, "stream", None) or file_storage
        if hasattr(stream, "seek"):
            stream.seek(0)
    except Exception:
        return


def unique_suffix(upload_history_id=None) -> str:
    """
    Generates a high-entropy, time-ordered suffix for filenames.
    Example: 20260529_171501_123456_ab12cd34 (microseconds + random)
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    rnd = uuid.uuid4().hex[:8]
    if upload_history_id is not None:
        try:
            return f"{ts}_{int(upload_history_id)}_{rnd}"
        except Exception:
            return f"{ts}_{rnd}"
    return f"{ts}_{rnd}"


def make_unique_filename(prefix: str, original_filename: str, upload_history_id=None) -> str:
    """
    Keeps the original filename (sanitized by caller) but guarantees uniqueness.
    """
    base, ext = os.path.splitext(original_filename or "")
    suf = unique_suffix(upload_history_id=upload_history_id)
    return f"{prefix}_{suf}_{base}{ext}"

