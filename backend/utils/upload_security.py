from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from werkzeug.utils import secure_filename


DEFAULT_MAX_UPLOAD_SIZE_MB = 100


class UploadSecurityError(ValueError):
    pass


def get_max_upload_size_bytes() -> int:
    raw = (os.getenv("RBA_MAX_UPLOAD_SIZE_MB") or "").strip()
    try:
        size_mb = int(raw) if raw else DEFAULT_MAX_UPLOAD_SIZE_MB
    except ValueError:
        size_mb = DEFAULT_MAX_UPLOAD_SIZE_MB
    return max(size_mb, 1) * 1024 * 1024


def validate_user_filename(filename: str) -> str:
    raw_name = str(filename or "").strip()
    safe_name = secure_filename(raw_name)

    if not raw_name or not safe_name:
        raise UploadSecurityError("Invalid filename")
    if raw_name != Path(raw_name).name:
        raise UploadSecurityError("Invalid filename")
    if "\x00" in raw_name or ".." in raw_name.replace("\\", "/").split("/"):
        raise UploadSecurityError("Invalid filename")

    return safe_name


def _read_head(file_storage, size: int = 4096) -> bytes:
    stream = getattr(file_storage, "stream", file_storage)
    current_pos = stream.tell()
    try:
        stream.seek(0)
        return stream.read(size) or b""
    finally:
        stream.seek(current_pos)


def _validate_magic_bytes(ext: str, head: bytes) -> None:
    ext = ext.lower()
    if ext == ".parquet" and not head.startswith(b"PAR1"):
        raise UploadSecurityError("Uploaded content does not match .parquet format")
    if ext == ".xlsx" and not head.startswith(b"PK"):
        raise UploadSecurityError("Uploaded content does not match .xlsx format")
    if ext == ".csv":
        if head.startswith(b"PK") or head.startswith(b"PAR1"):
            raise UploadSecurityError("Uploaded content does not match .csv format")
        if b"\x00" in head:
            raise UploadSecurityError("Uploaded content does not match .csv format")


def validate_upload_file(file_storage, *, allowed_extensions: Iterable[str]) -> str:
    safe_name = validate_user_filename(getattr(file_storage, "filename", ""))
    ext = Path(safe_name).suffix.lower()
    normalized_extensions = {str(item).lower() for item in (allowed_extensions or [])}

    if ext not in normalized_extensions:
        allowed = ", ".join(sorted(normalized_extensions))
        raise UploadSecurityError(f"Only {allowed} files are accepted")

    content_length = getattr(file_storage, "content_length", None)
    if content_length and int(content_length) > get_max_upload_size_bytes():
        raise UploadSecurityError("Uploaded file exceeds the allowed size limit")

    head = _read_head(file_storage)
    if head:
        _validate_magic_bytes(ext, head)

    return safe_name
