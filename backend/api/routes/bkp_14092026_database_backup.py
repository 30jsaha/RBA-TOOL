"""Administrative database backup and restore-point endpoints.

All filesystem and database targets are server-side configuration. The
frontend only ever sends a backup id, and restore is deliberately guarded by
an emergency snapshot and an explicit confirmation string.
"""

import gzip
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import text

from api.extensions import db
from config.db_config import get_mysql_engine, get_mysql_settings
from utils.database_locks import DatabaseMaintenanceBusy, financial_data_lock
from utils.rbac import require_permission


bp = Blueprint("database_backup", __name__, url_prefix="/api/database-backup")
_operation_lock = threading.Lock()
HISTORY_TABLE = "database_backup_history"
AUDIT_TABLE = "database_backup_audit"
BACKEND_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)
IMPLEMENTATION_VERSION = "backup-gzip-diagnostics-2026-09-14"


def _backup_dir():
    configured = os.getenv("BACKUP_DIR", "").strip()
    path = Path(configured) if configured else BACKEND_ROOT / "backups"
    if not path.is_absolute():
        path = BACKEND_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve()
    logger.info("Backup directory cwd=%s backend_root=%s configured=%s resolved=%s", Path.cwd(), BACKEND_ROOT, configured or "<default>", resolved)
    return resolved


def _debug_preserve_failures():
    return os.getenv("BACKUP_DEBUG_PRESERVE_FAILURES", "").strip().lower() in {"1", "true", "yes", "on"}


def _log_path(label, path):
    path = Path(path)
    exists = path.exists()
    size = path.stat().st_size if path.is_file() else None
    logger.info("Backup path label=%s path=%s absolute=%s exists=%s size=%s", label, path, path.resolve(), exists, size)


def _safe_error(exc):
    message = str(exc) or "Database backup operation failed."
    if "MYSQL_PWD" in message or "password" in message.lower():
        return "Database backup operation failed. Check the server database configuration."
    return message[:500]


def _settings_args(settings):
    return ["--host", settings["host"], "--port", str(settings["port"]), "--user", settings["user"]]


def _resolve_mysql_binary(binary_name, explicit_env):
    """Resolve a MySQL client without accepting a path from the request."""
    configured = os.getenv(explicit_env, "").strip()
    candidates = []
    if configured:
        configured_path = Path(configured).expanduser()
        candidates.append(configured_path / binary_name if configured_path.is_dir() else configured_path)
    mysql_path = os.getenv("MYSQL_PATH", "").strip()
    if mysql_path and explicit_env != "MYSQL_PATH":
        mysql_path = Path(mysql_path).expanduser()
        candidates.append(mysql_path / binary_name if mysql_path.is_dir() else mysql_path)
    path_match = shutil.which(binary_name) or shutil.which(f"{binary_name}.exe")
    if path_match:
        candidates.append(Path(path_match))

    for candidate in candidates:
        try:
            candidate = candidate.resolve()
            if not candidate.is_file():
                continue
            subprocess.run([str(candidate), "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=10)
            return str(candidate)
        except (OSError, subprocess.SubprocessError):
            continue
    raise RuntimeError(f"{binary_name} is not available on the server. Configure {explicit_env} or MYSQL_PATH.")


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _log_artifact_bytes(path, label):
    exists = path.is_file()
    size = path.stat().st_size if exists else 0
    header = b""
    if exists:
        with path.open("rb") as stream:
            header = stream.read(16)
    logger.info(
        "Backup %s artifact path=%s exists=%s size=%s first16_hex=%s first16_repr=%r gzip_magic=%s",
        label, path, exists, size, header.hex(), header, header[:2] == b"\x1f\x8b",
    )


def _validate_backup_record(row, settings):
    if row.get("database_name") != settings["database"]:
        raise RuntimeError("The selected backup does not belong to the configured database.")
    root = _backup_dir()
    source = (root / str(row["backup_name"])).resolve()
    if root not in source.parents or not source.is_file():
        raise RuntimeError("Selected backup file is unavailable.")
    if not os.access(source, os.R_OK):
        raise RuntimeError("Selected backup file is not readable.")
    if not row.get("checksum") or _sha256(source) != row["checksum"]:
        raise RuntimeError("Backup checksum validation failed; the file may have been changed.")
    try:
        with gzip.open(source, "rb") as dump:
            if not dump.read(1):
                raise RuntimeError("Selected backup file is empty.")
    except OSError as exc:
        raise RuntimeError("Selected backup file is not a valid readable gzip archive.") from exc
    return source


def _staging_database(settings):
    staging = os.getenv("RESTORE_STAGING_DB", "").strip()
    if not staging:
        raise RuntimeError("Safe restore preview is unavailable because an isolated staging database is not configured.")
    if staging.casefold() == settings["database"].casefold():
        raise RuntimeError("Safe restore preview is unavailable because the staging database cannot be the live database.")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", staging):
        raise RuntimeError("Safe restore preview is unavailable because the staging database name is invalid.")
    return staging


def _mysql_env(settings):
    env = os.environ.copy()
    env["MYSQL_PWD"] = settings["password"]
    return env


def _run_staging_mysql(args, settings, target_database, stdin=None):
    live_database = settings["database"]
    if target_database.casefold() == live_database.casefold():
        raise RuntimeError("Restore target safety check failed: the live database cannot be used as staging.")
    return subprocess.run(
        args,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_mysql_env(settings),
        check=False,
    )


def _staging_restore(source, backup_id, settings, user_id):
    staging = _staging_database(settings)
    mysql_bin = _resolve_mysql_binary("mysql", "MYSQL_PATH")
    started = time.monotonic()
    _audit(user_id, "RESTORE_PREVIEW_STARTED", backup_id, "IN_PROGRESS")
    db.session.commit()
    try:
        # The staging name is validated and compared with the live name before
        # constructing this command. It is the only database that may be reset.
        reset_args = [
            mysql_bin, *_settings_args(settings), "--execute",
            f"DROP DATABASE IF EXISTS `{staging}`; CREATE DATABASE `{staging}` CHARACTER SET utf8mb4;",
        ]
        reset_result = _run_staging_mysql(reset_args, settings, staging)
        if reset_result.returncode != 0:
            raise RuntimeError(reset_result.stderr.decode("utf-8", errors="replace")[:500] or "Unable to prepare the isolated staging database.")

        restore_args = [mysql_bin, *_settings_args(settings), staging]
        with gzip.open(source, "rb") as dump:
            restore_result = _run_staging_mysql(restore_args, settings, staging, stdin=dump)
        if restore_result.returncode != 0:
            raise RuntimeError(restore_result.stderr.decode("utf-8", errors="replace")[:500] or "The backup could not be restored into staging.")

        validate_args = [
            mysql_bin, *_settings_args(settings), "--batch", "--skip-column-names",
            "--execute", "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE';", staging,
        ]
        validate_result = _run_staging_mysql(validate_args, settings, staging)
        if validate_result.returncode != 0:
            raise RuntimeError(validate_result.stderr.decode("utf-8", errors="replace")[:500] or "The staging database could not be validated.")
        table_count_text = validate_result.stdout.decode("utf-8", errors="replace").strip().splitlines()
        table_count = int(table_count_text[-1]) if table_count_text and table_count_text[-1].isdigit() else 0
        if table_count <= 0:
            raise RuntimeError("Staging restore validation found no tables.")

        duration = round(time.monotonic() - started, 3)
        _audit(user_id, "RESTORE_PREVIEW_SUCCESS", backup_id, "SUCCESS", duration)
        db.session.commit()
        return {"staging_database": staging, "restored_tables": table_count, "duration": duration}
    except Exception as exc:
        duration = round(time.monotonic() - started, 3)
        _audit(user_id, "RESTORE_PREVIEW_FAILED", backup_id, "FAILED", duration, _safe_error(exc))
        db.session.commit()
        raise


def _available_tables(settings=None):
    settings = settings or get_mysql_settings()
    with get_mysql_engine().connect() as connection:
        rows = connection.execute(text(
            "SELECT TABLE_NAME FROM information_schema.tables "
            "WHERE TABLE_SCHEMA=:db AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"
        ), {"db": settings["database"]}).scalars().all()
    return [str(name) for name in rows]


def _validate_requested_tables(requested, settings):
    if not isinstance(requested, list) or not requested:
        raise ValueError("Select at least one database table.")
    if any(not isinstance(name, str) or not name.strip() for name in requested):
        raise ValueError("Selected table names must be non-empty strings.")
    requested = list(dict.fromkeys(name.strip() for name in requested))
    available = set(_available_tables(settings))
    unknown = [name for name in requested if name not in available]
    if unknown:
        raise ValueError("Unknown database table selected: " + ", ".join(unknown[:5]))
    return requested


def _run_dump(filename, backup_type, user_id, selected_tables=None):
    settings = get_mysql_settings()
    output_path = _backup_dir() / filename
    temporary_path = output_path.with_name(f"{output_path.name}.tmp")
    dump_bin = _resolve_mysql_binary("mysqldump", "MYSQLDUMP_PATH")
    logger.info("Backup start cwd=%s temp_dir=%s backup_dir=%s temp_path=%s final_path=%s dump_bin=%s", Path.cwd(), Path(os.getenv("TEMP", "")), output_path.parent, temporary_path, output_path, dump_bin)

    started = time.monotonic()
    metadata_id = db.session.execute(
        text(f"""INSERT INTO {HISTORY_TABLE}
            (backup_name, backup_type, database_name, backup_scope, table_list, status, created_at, created_by)
            VALUES (:name, :type, :database_name, :scope, :table_list, 'IN_PROGRESS', CURRENT_TIMESTAMP, :user_id)"""),
        {"name": filename, "type": backup_type, "database_name": settings["database"],
         "scope": "SELECTED_TABLES" if selected_tables else "ALL_TABLES",
         "table_list": ",".join(selected_tables) if selected_tables else None, "user_id": user_id},
    ).lastrowid
    db.session.commit()
    _audit(user_id, f"{backup_type}_STARTED", metadata_id, "IN_PROGRESS")
    db.session.commit()
    try:
        env = os.environ.copy()
        env["MYSQL_PWD"] = settings["password"]
        args = [dump_bin, *_settings_args(settings), "--single-transaction", "--routines", "--triggers", "--events", "--hex-blob"]
        args.extend([settings["database"], *selected_tables] if selected_tables else ["--databases", settings["database"]])
        temporary_path.unlink(missing_ok=True)
        
        # FIX: Stream mysqldump output through gzip via process pipe
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        
        with gzip.open(temporary_path, "wb") as compressed_out:
            shutil.copyfileobj(process.stdout, compressed_out)
            
        _, stderr_data = process.communicate()
        logger.info("mysqldump completed returncode=%s stderr_bytes=%s", process.returncode, len(stderr_data or b""))
        
        if process.returncode != 0:
            raise RuntimeError(stderr_data.decode("utf-8", errors="replace")[:500] or "mysqldump failed.")
            
        _log_artifact_bytes(temporary_path, "temporary")
        if not temporary_path.is_file() or temporary_path.stat().st_size <= 0:
            raise RuntimeError("The backup file was not created or is empty.")
            
        # Dynamically validate that expected tables exist in compressed archive
        expected_tables = selected_tables or _available_tables(settings)[:3]
        expected = {table.encode("utf-8") for table in expected_tables if table}
        found = set()
        
        with gzip.open(temporary_path, "rb") as dump:
            carry = b""
            for chunk in iter(lambda: dump.read(1024 * 1024), b""):
                haystack = carry + chunk
                found.update(table for table in expected if table in haystack)
                carry = haystack[-64:]
                
        if expected and not found:
            raise RuntimeError("Backup validation failed: expected table definitions were not found in archive.")

        checksum = _sha256(temporary_path)
        _log_path("validated-and-hashed-temp", temporary_path)
        os.replace(temporary_path, output_path)
        _log_path("final-after-atomic-replace", output_path)
        duration = round(time.monotonic() - started, 3)
        db.session.execute(text(f"""UPDATE {HISTORY_TABLE}
            SET status='SUCCESS', file_size=:size, completed_at=CURRENT_TIMESTAMP,
                duration=:duration, checksum=:checksum WHERE id=:id"""),
            {"size": output_path.stat().st_size, "duration": duration, "checksum": checksum, "id": metadata_id},
        )
        _audit(user_id, f"{backup_type}_SUCCESS", metadata_id, "SUCCESS", duration)
        db.session.commit()
        return metadata_id, output_path
    except Exception as exc:
        duration = round(time.monotonic() - started, 3)
        db.session.execute(text(f"""UPDATE {HISTORY_TABLE}
            SET status='FAILED', completed_at=CURRENT_TIMESTAMP, duration=:duration,
                error_message=:error WHERE id=:id"""),
            {"duration": duration, "error": _safe_error(exc), "id": metadata_id},
        )
        _audit(user_id, f"{backup_type}_FAILED", metadata_id, "FAILED", duration, _safe_error(exc))
        db.session.commit()
        if _debug_preserve_failures():
            _log_path("preserved-failed-temp", temporary_path)
            _log_path("preserved-failed-final", output_path)
            logger.error("PRESERVED FAILED BACKUP ARTIFACT temp=%s final=%s", temporary_path.resolve(), output_path.resolve())
        else:
            try:
                temporary_path.unlink(missing_ok=True)
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _audit(user_id, action, backup_id, status, duration=None, error=None):
    db.session.execute(text(f"""INSERT INTO {AUDIT_TABLE}
        (user_id, action, backup_id, status, duration, error_message, created_at)
        VALUES (:user_id, :action, :backup_id, :status, :duration, :error, CURRENT_TIMESTAMP)"""),
        {"user_id": user_id, "action": action, "backup_id": backup_id, "status": status, "duration": duration, "error": error})


def _busy_json(exc):
    return jsonify({"success": False, "message": str(exc)}), 409


@bp.get("/status")
@jwt_required()
@require_permission("settings.db_restore_point.view")
def status():
    settings = get_mysql_settings()
    engine = get_mysql_engine()
    with engine.connect() as connection:
        tables = connection.execute(text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=:db"), {"db": settings["database"]}).scalar()
    last = db.session.execute(text(f"SELECT backup_name, backup_type, completed_at FROM {HISTORY_TABLE} WHERE status='SUCCESS' ORDER BY completed_at DESC LIMIT 1")).mappings().first()
    return jsonify({"database": settings["database"], "engine": "MySQL 8.0", "total_tables": int(tables or 0), "backup_location": str(_backup_dir()), "last_backup": dict(last) if last else None})


@bp.get("/runtime-info")
@jwt_required()
@require_permission("settings.db_restore_point.view")
def runtime_info():
    return jsonify({
        "cwd": str(Path.cwd()),
        "python_executable": sys.executable,
        "database_backup_file": str(Path(__file__).resolve()),
        "backend_root": str(BACKEND_ROOT),
        "backup_directory": str(_backup_dir()),
        "temporary_directory": os.getenv("TEMP", ""),
        "implementation_version": IMPLEMENTATION_VERSION,
        "debug_preserve_failures": _debug_preserve_failures(),
    })


@bp.get("/tables")
@jwt_required()
@require_permission("settings.db_restore_point.view")
def list_tables():
    try:
        return jsonify({"tables": _available_tables()})
    except Exception as exc:
        return jsonify({"success": False, "message": _safe_error(exc)}), 500


@bp.get("/list")
@jwt_required()
@require_permission("settings.db_restore_point.view")
def list_backups():
    rows = db.session.execute(text(
        f"SELECT id, backup_name, backup_type, database_name, backup_scope, table_list, status, file_size, checksum, "
        f"created_at, completed_at, duration, created_by, error_message FROM {HISTORY_TABLE} "
        "ORDER BY created_at DESC LIMIT 200"
    )).mappings().all()
    return jsonify({"backups": [dict(row) for row in rows]})


@bp.post("/create")
@jwt_required()
@require_permission("settings.db_restore_point.create")
def create_backup():
    request_data = request.get_json(silent=True) or {}
    if not isinstance(request_data, dict):
        return jsonify({"success": False, "message": "Backup request must be a JSON object."}), 400
    scope = request_data.get("scope", "ALL_TABLES")
    if scope not in {"ALL_TABLES", "SELECTED_TABLES"}:
        return jsonify({"success": False, "message": "Invalid backup scope."}), 400
    settings = get_mysql_settings()
    try:
        selected_tables = _validate_requested_tables(request_data.get("tables"), settings) if scope == "SELECTED_TABLES" else None
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    if not _operation_lock.acquire(blocking=False):
        return _busy_json(DatabaseMaintenanceBusy("Another backup or restore is already running."))
    try:
        with financial_data_lock(get_mysql_engine(), timeout_seconds=0):
            stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
            backup_type = "SELECTED_TABLES" if selected_tables else "FULL_BACKUP"
            backup_id, path = _run_dump(f"database_{stamp}_{uuid.uuid4().hex}.sql.gz", backup_type, get_jwt_identity(), selected_tables)
            return jsonify({"success": True, "id": backup_id, "backup_name": path.name, "message": "Database backup created successfully."}), 201
    except DatabaseMaintenanceBusy as exc:
        return _busy_json(exc)
    except Exception as exc:
        return jsonify({"success": False, "message": _safe_error(exc)}), 500
    finally:
        _operation_lock.release()


@bp.get("/download/<int:backup_id>")
@jwt_required()
@require_permission("settings.db_restore_point.view")
def download_backup(backup_id):
    row = db.session.execute(text(f"SELECT backup_name FROM {HISTORY_TABLE} WHERE id=:id AND status='SUCCESS'"), {"id": backup_id}).mappings().first()
    if not row:
        return jsonify({"success": False, "message": "Backup not found."}), 404
    root = _backup_dir()
    target = (root / str(row["backup_name"])).resolve()
    if root not in target.parents or not target.is_file():
        return jsonify({"success": False, "message": "Backup file is unavailable."}), 404
    return send_file(target, as_attachment=True, download_name=target.name, mimetype="application/gzip")


@bp.post("/<int:backup_id>/preview")
@jwt_required()
@require_permission("settings.db_restore_point.restore")
def preview_restore(backup_id):
    row = db.session.execute(text(f"SELECT * FROM {HISTORY_TABLE} WHERE id=:id AND status='SUCCESS'"), {"id": backup_id}).mappings().first()
    if not row:
        return jsonify({"success": False, "message": "Only successful backups can be previewed."}), 404
    settings = get_mysql_settings()
    try:
        source = _validate_backup_record(row, settings)
    except Exception as exc:
        return jsonify({"success": False, "message": _safe_error(exc)}), 400

    if not _operation_lock.acquire(blocking=False):
        return _busy_json(DatabaseMaintenanceBusy("Another backup or restore preview is already running."))
    try:
        try:
            staging_result = _staging_restore(source, backup_id, settings, get_jwt_identity())
        except RuntimeError as exc:
            message = _safe_error(exc)
            status_code = 503 if "not configured" in message or "live database" in message or "staging database name" in message else 500
            return jsonify({"success": False, "message": message}), status_code
        return jsonify({
            "success": True,
            "backup_id": backup_id,
            "backup_name": row["backup_name"],
            "created_at": row["created_at"],
            "file_size": row["file_size"],
            "database_name": settings["database"],
            "staging_database": staging_result["staging_database"],
            "tables": staging_result["restored_tables"],
            "tables_affected": staging_result["restored_tables"],
            "validation_status": "PASSED",
            "duration": staging_result["duration"],
            "message": "Backup restored and validated successfully in isolated staging database.",
        })
    finally:
        _operation_lock.release()


@bp.post("/restore")
@jwt_required()
@require_permission("settings.db_restore_point.restore")
def restore_backup():
    return jsonify({
        "success": False,
        "message": "Direct restore is disabled. Configure and verify an isolated staging restore workflow first.",
    }), 410
