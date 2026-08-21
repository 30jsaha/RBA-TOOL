from __future__ import annotations

from typing import Dict, List, Set, Tuple

import os
import io
import pandas as pd

from sqlalchemy import text

from api.helpers.validation_helper import normalize_column, normalize_tax_type, safe_seek0
from config.db_config import get_mysql_engine


MIN_MATCH_PERCENTAGE = 60
TAX_TYPES: Tuple[str, str, str] = ("gst", "swt", "cit")


def _read_headers_from_path(file_path: str) -> List[str]:
    p = str(file_path or "")
    lp = p.lower()
    if lp.endswith(".csv"):
        try:
            df0 = pd.read_csv(p, nrows=0, encoding="utf-8-sig", low_memory=False)
            return list(df0.columns)
        except Exception:
            df0 = pd.read_csv(p, nrows=0, low_memory=False)
            return list(df0.columns)
    if lp.endswith(".parquet"):
        try:
            import pyarrow.parquet as pq

            pf = pq.ParquetFile(p)
            return list(pf.schema.names or [])
        except Exception:
            df0 = pd.read_parquet(p)
            return list(df0.columns)
    return []


def _resolve_column_msts_query(engine) -> Tuple[str, str, Optional[str]]:
    """
    Supports multiple schemas seen in environments:
      - standardized_column_name OR standard_column_name
      - tax_type OR file_type
      - optional is_active
    Returns (column_name_col, tax_type_col, is_active_col_or_None)
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'column_msts'
                """
            )
        ).fetchall()
    cols = {str(r[0] or "").strip().lower() for r in (rows or [])}

    col_name_col = None
    for cand in ("standardized_column_name", "standard_column_name"):
        if cand in cols:
            col_name_col = cand
            break
    if not col_name_col:
        raise RuntimeError("column_msts missing standardized column name field")

    tax_type_col = "tax_type" if "tax_type" in cols else ("file_type" if "file_type" in cols else None)
    if not tax_type_col:
        raise RuntimeError("column_msts missing tax type field")

    is_active_col = "is_active" if "is_active" in cols else None
    return col_name_col, tax_type_col, is_active_col


def _fetch_expected_columns(engine, tax_type: str) -> Set[str]:
    tax_type = normalize_tax_type(tax_type)
    if not tax_type:
        return set()

    col_name_col, tax_type_col, is_active_col = _resolve_column_msts_query(engine)
    where = [f"LOWER({tax_type_col}) = :tax_type"]
    params = {"tax_type": tax_type}
    if is_active_col:
        where.append(f"{is_active_col} = 1")

    q = f"SELECT {col_name_col} FROM column_msts WHERE " + " AND ".join(where)
    with engine.connect() as conn:
        rows = conn.execute(text(q), params).fetchall()

    out = set()
    for r in rows or []:
        try:
            out.add(normalize_column(r[0]))
        except Exception:
            continue
    out.discard("")
    return out


def validate_uploaded_file_type(
    file_or_path,
    selected_tax_type: str,
) -> Dict:
    """
    Request-safe file type detection against `column_msts`.

    - No module-level mutable state
    - Always rewinds stream before any read when a FileStorage-like object is passed
    """
    selected = normalize_tax_type(selected_tax_type)
    scores: Dict[str, int] = {t: 0 for t in TAX_TYPES}

    # Normalize uploaded headers
    headers_norm: Set[str] = set()
    try:
        if isinstance(file_or_path, str):
            headers = _read_headers_from_path(file_or_path)
        else:
            safe_seek0(file_or_path)
            # Prefer path if already saved on disk
            path = getattr(file_or_path, "name", None)
            if isinstance(path, str) and os.path.exists(path):
                headers = _read_headers_from_path(path)
            else:
                # As a fallback, load 0-row frame from bytes
                safe_seek0(file_or_path)
                data = file_or_path.read()
                safe_seek0(file_or_path)
                headers = list(pd.read_csv(io.BytesIO(data), nrows=0).columns)
        headers_norm = {normalize_column(h) for h in (headers or [])}
        headers_norm.discard("")
    except Exception:
        headers_norm = set()

    detected = None
    try:
        engine = get_mysql_engine()
        try:
            expected_by_type = {t: _fetch_expected_columns(engine, t) for t in TAX_TYPES}
        finally:
            try:
                engine.dispose()
            except Exception:
                pass

        for t, expected in expected_by_type.items():
            if not expected:
                scores[t] = 0
                continue
            matched = len(expected.intersection(headers_norm))
            scores[t] = int(round((matched / float(len(expected))) * 100))

        detected = max(scores.items(), key=lambda kv: kv[1])[0] if scores else None
    except Exception:
        detected = None

    selected_score = int(scores.get(selected, 0)) if selected else 0
    ok = bool(selected) and selected_score >= MIN_MATCH_PERCENTAGE

    msg = ""
    if not ok:
        if detected and selected and detected != selected:
            msg = (
                f"Wrong file selected. Uploaded file appears to be {detected.upper()} "
                f"but selected tax type is {selected.upper()}."
            )
        else:
            msg = "Wrong file selected. Uploaded file structure does not match the selected tax type."

    return {
        "valid": ok,
        "detected_tax_type": detected,
        "selected_tax_type": selected,
        "match_score": scores,
        "message": msg,
    }
