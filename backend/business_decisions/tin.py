"""Canonical TIN matching without changing source/display values."""

import math
import re


_TIN_RE = re.compile(r"^[1-9][0-9]{8}$")
_NUMERIC_IMPORT_RE = re.compile(r"^[0-9]+\.0$")


def normalize_tin(value):
    """Return a canonical nine-digit TIN or ``None`` for matching.

    This deliberately does not pad, strip arbitrary punctuation, or mutate the
    source value.  It is only a business-decision lookup key.
    """
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
    except Exception:
        pass
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "nat", "null"}:
        return None
    if _NUMERIC_IMPORT_RE.fullmatch(text):
        text = text[:-2]
    return text if _TIN_RE.fullmatch(text) else None
