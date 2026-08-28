from __future__ import annotations

import base64
import contextlib
import io
import mimetypes
import os
import tempfile
from pathlib import Path
from typing import Iterator, Optional

import pandas as pd
from cryptography.fernet import Fernet, InvalidToken
from flask import Response, send_file
from werkzeug.utils import secure_filename

from utils.file_utils import get_backend_storage_dir


FINAL_OUTPUT_ENCRYPTION_KEY_ENV = "FINAL_OUTPUT_ENCRYPTION_KEY"
ENCRYPTED_SUFFIX = ".enc"
DEFAULT_DOWNLOAD_EXTENSIONS = {".csv", ".txt", ".xlsx", ".parquet"}
FINAL_OUTPUT_ALLOWED_TAX_TYPES = {"GST", "SWT", "CIT"}
FINAL_OUTPUT_CLEANUP_EXTENSIONS = {".enc", ".csv", ".txt", ".xlsx", ".xls", ".parquet"}


class FinalOutputSecurityError(RuntimeError):
    pass



def _backend_root_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def get_final_output_directory(tax_type: str) -> Path:
    normalized = str(tax_type or "").strip().upper()
    if normalized not in FINAL_OUTPUT_ALLOWED_TAX_TYPES:
        raise FinalOutputSecurityError("Invalid tax type")

    folder_map = {
        "GST": "gst",
        "SWT": "swt",
        "CIT": "cit",
    }
    expected_dir = (_backend_root_dir() / folder_map[normalized] / "final_output").resolve()
    expected_parent = (_backend_root_dir() / folder_map[normalized]).resolve()

    if expected_dir.parent != expected_parent or expected_dir.name != "final_output":
        raise FinalOutputSecurityError("Invalid final output directory")

    return expected_dir


def cleanup_final_output_directory(tax_type: str) -> int:
    report = cleanup_final_output_directory_report(tax_type)
    return int(report["deleted"])


def cleanup_final_output_directory_report(tax_type: str) -> dict:
    target_dir = get_final_output_directory(tax_type)
    if not target_dir.exists():
        print(f"[FINAL_OUTPUT_CLEANUP][{tax_type}] directory missing: {target_dir}")
        return {"deleted": 0, "failed": []}
    if not target_dir.is_dir():
        raise FinalOutputSecurityError("Configured final output path is not a directory")

    removed_count = 0
    failed = []
    for entry in target_dir.iterdir():
        try:
            resolved_entry = entry.resolve()
        except FileNotFoundError:
            continue

        if resolved_entry.parent != target_dir:
            raise FinalOutputSecurityError("Refusing to clean outside final output directory")
        if not resolved_entry.is_file():
            continue
        if resolved_entry.suffix.lower() not in FINAL_OUTPUT_CLEANUP_EXTENSIONS:
            continue

        try:
            resolved_entry.unlink()
            removed_count += 1
        except OSError as exc:
            print(
                f"[FINAL_OUTPUT_CLEANUP][{tax_type}] failed to remove {resolved_entry.name}: {exc}"
            )
            failed.append(
                {
                    "tax_type": str(tax_type or "").strip().upper(),
                    "filename": resolved_entry.name,
                    "reason": str(exc),
                }
            )

    print(
        f"[FINAL_OUTPUT_CLEANUP][{tax_type}] removed {removed_count} file(s) from {target_dir}"
    )
    if failed:
        print(
            f"[FINAL_OUTPUT_CLEANUP][{tax_type}] {len(failed)} file(s) could not be removed"
        )
    return {"deleted": removed_count, "failed": failed}


def cleanup_all_final_output_directories() -> dict:
    deleted = {}
    failed = []

    for tax_type in ("GST", "SWT", "CIT"):
        report = cleanup_final_output_directory_report(tax_type)
        deleted[tax_type.lower()] = int(report["deleted"])
        failed.extend(report["failed"])

    return {
        "deleted": deleted,
        "failed": failed,
        "total_deleted": sum(deleted.values()),
    }

def _require_configured_key() -> bytes:
    configured = os.getenv(FINAL_OUTPUT_ENCRYPTION_KEY_ENV)
    if configured is None:
        raise FinalOutputSecurityError(
            f"{FINAL_OUTPUT_ENCRYPTION_KEY_ENV} is required for protected final output handling"
        )

    normalized = configured.strip()
    if not normalized:
        raise FinalOutputSecurityError(
            f"{FINAL_OUTPUT_ENCRYPTION_KEY_ENV} must not be empty"
        )

    try:
        Fernet(normalized.encode("utf-8"))
    except Exception as exc:
        raise FinalOutputSecurityError(
            f"{FINAL_OUTPUT_ENCRYPTION_KEY_ENV} is invalid"
        ) from exc

    return normalized.encode("utf-8")


def validate_final_output_encryption_config() -> None:
    _require_configured_key()


def _cipher() -> Fernet:
    return Fernet(_require_configured_key())


def sanitize_output_filename(
    filename: str,
    *,
    expected_prefix: Optional[str] = None,
    allowed_extensions=DEFAULT_DOWNLOAD_EXTENSIONS,
) -> str:
    raw_name = str(filename or "").strip()
    safe_name = secure_filename(raw_name)

    if not raw_name or not safe_name or raw_name != Path(raw_name).name:
        raise FinalOutputSecurityError("Invalid filename")

    ext = Path(safe_name).suffix.lower()
    if allowed_extensions and ext not in allowed_extensions:
        raise FinalOutputSecurityError("Invalid file type")

    if expected_prefix and not safe_name.startswith(expected_prefix):
        raise FinalOutputSecurityError("Invalid filename")

    return safe_name


def encrypted_output_path(output_dir: str | os.PathLike[str], logical_name: str) -> Path:
    return Path(output_dir).resolve() / f"{logical_name}{ENCRYPTED_SUFFIX}"


def plaintext_output_path(output_dir: str | os.PathLike[str], logical_name: str) -> Path:
    return Path(output_dir).resolve() / logical_name


def output_exists(output_dir: str | os.PathLike[str], logical_name: str) -> bool:
    encrypted = encrypted_output_path(output_dir, logical_name)
    plain = plaintext_output_path(output_dir, logical_name)
    return encrypted.is_file() or plain.is_file()


def encrypt_bytes(payload: bytes) -> bytes:
    token = _cipher().encrypt(payload)
    try:
        return base64.urlsafe_b64decode(token)
    except Exception:
        return token


def decrypt_bytes(payload: bytes) -> bytes:
    try:
        return _cipher().decrypt(payload)
    except InvalidToken:
        try:
            token = base64.urlsafe_b64encode(payload)
            return _cipher().decrypt(token)
        except InvalidToken as exc:
            raise FinalOutputSecurityError("Unable to decrypt protected file") from exc


def write_encrypted_output_bytes(
    output_dir: str | os.PathLike[str],
    logical_name: str,
    payload: bytes,
) -> Path:
    target_dir = Path(output_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    encrypted_path = encrypted_output_path(target_dir, logical_name)
    temp_path = encrypted_path.with_suffix(encrypted_path.suffix + ".tmp")
    plaintext_path = plaintext_output_path(target_dir, logical_name)

    temp_path.write_bytes(encrypt_bytes(payload))
    os.replace(temp_path, encrypted_path)

    if plaintext_path.exists():
        plaintext_path.unlink()

    if plaintext_path.exists():
        raise FinalOutputSecurityError(f"Plaintext file still exists after encryption: {plaintext_path.name}")
    if not encrypted_path.is_file() or encrypted_path.stat().st_size <= 0:
        raise FinalOutputSecurityError(f"Encrypted file was not written successfully: {encrypted_path.name}")

    return encrypted_path


def write_encrypted_output_file(
    source_path: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    logical_name: str,
) -> Path:
    payload = Path(source_path).read_bytes()
    return write_encrypted_output_bytes(output_dir, logical_name, payload)


def write_encrypted_output_dataframe(
    dataframe: pd.DataFrame,
    output_dir: str | os.PathLike[str],
    logical_name: str,
) -> Path:
    suffix = Path(logical_name).suffix.lower() or ".csv"
    temp_root = Path(get_backend_storage_dir("tmp", "encrypted_output_staging"))
    temp_root.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(prefix="rba_encrypt_", suffix=suffix, dir=str(temp_root))
    os.close(fd)

    try:
        temp_file = Path(temp_path)
        if suffix in {".xlsx", ".xls"}:
            dataframe.to_excel(temp_file, index=False)
        else:
            dataframe.to_csv(temp_file, index=False)
        return write_encrypted_output_file(temp_file, output_dir, logical_name)
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass



def read_encrypted_dataframe(
    output_dir: str | os.PathLike[str],
    logical_name: str,
) -> pd.DataFrame:
    payload = read_output_bytes(output_dir, logical_name)
    suffix = Path(logical_name).suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(io.BytesIO(payload))
    return pd.read_csv(io.BytesIO(payload))

def migrate_plaintext_output(
    output_dir: str | os.PathLike[str],
    logical_name: str,
) -> Path | None:
    plain_path = plaintext_output_path(output_dir, logical_name)
    if not plain_path.is_file():
        return None
    return write_encrypted_output_file(plain_path, output_dir, logical_name)


def normalize_logical_name(logical_name: str) -> str:
    name = str(logical_name or "").strip()
    if name.endswith(ENCRYPTED_SUFFIX):
        name = name[:-len(ENCRYPTED_SUFFIX)]
    return name


def read_output_bytes(
    output_dir: str | os.PathLike[str],
    logical_name: str,
) -> bytes:
    clean_name = normalize_logical_name(logical_name)
    encrypted_path = encrypted_output_path(output_dir, clean_name)
    if encrypted_path.is_file():
        return decrypt_bytes(encrypted_path.read_bytes())

    plaintext_path = plaintext_output_path(output_dir, clean_name)
    if plaintext_path.is_file():
        data = plaintext_path.read_bytes()
        try:
            return decrypt_bytes(data)
        except Exception:
            return data

    raw_path = Path(output_dir).resolve() / logical_name
    if raw_path.is_file():
        data = raw_path.read_bytes()
        try:
            return decrypt_bytes(data)
        except Exception:
            return data

    raise FileNotFoundError(logical_name)


@contextlib.contextmanager
def materialize_output_to_tempfile(
    output_dir: str | os.PathLike[str],
    logical_name: str,
) -> Iterator[str]:
    clean_name = normalize_logical_name(logical_name)
    suffix = Path(clean_name).suffix or ".csv"
    temp_root = Path(get_backend_storage_dir("tmp", "decrypted_outputs"))
    temp_root.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(prefix="rba_", suffix=suffix, dir=str(temp_root))
    os.close(fd)

    try:
        Path(temp_path).write_bytes(read_output_bytes(output_dir, logical_name))
        yield temp_path
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass
        except Exception:
            pass


def secure_download_response(
    output_dir: str | os.PathLike[str],
    logical_name: str,
) -> Response:
    payload = read_output_bytes(output_dir, logical_name)
    mimetype = mimetypes.guess_type(logical_name)[0] or "application/octet-stream"
    return send_file(
        io.BytesIO(payload),
        mimetype=mimetype,
        as_attachment=True,
        download_name=logical_name,
        max_age=0,
        conditional=False,
    )


def sanitize_file_reference(reference: str) -> str:
    raw = str(reference or "").strip()
    if not raw:
        raise FinalOutputSecurityError("Invalid filename")
    basename = Path(raw.replace("\\", "/")).name
    return sanitize_output_filename(basename)
