"""Persistence and authorization service for generated artifacts.

The service is intentionally not integrated with GST/SWT/CIT in Phase 1.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from config.db_config import get_mysql_engine
from utils.artifact_storage import (
    artifact_path,
    normalize_artifact_kind,
    normalize_logical_name,
    normalize_tax_type,
)
from utils.data_access import can_access_owner, current_user_id, is_global_admin


class ArtifactNotFoundError(LookupError):
    pass


class ArtifactAuthorizationError(PermissionError):
    pass


def _engine(engine=None):
    return engine or get_mysql_engine()


def _row_mapping(row):
    if row is None:
        return None
    return dict(row._mapping) if hasattr(row, "_mapping") else dict(row)


def create_artifact(
    *,
    user_id,
    run_id,
    tax_type,
    logical_name,
    artifact_kind,
    upload_id=None,
    status="created",
    expires_at=None,
    engine=None,
):
    """Create metadata for one new artifact and return its record."""
    if user_id is None:
        raise ValueError("user_id is required")
    path = artifact_path(user_id, run_id, artifact_kind, logical_name, create=True)
    tax = normalize_tax_type(tax_type)
    kind = normalize_artifact_kind(artifact_kind)
    name = normalize_logical_name(logical_name)
    status_value = str(status or "created").strip().lower()
    if not status_value or len(status_value) > 20:
        raise ValueError("Invalid artifact status")

    with _engine(engine).begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO generated_artifacts
                    (user_id, upload_id, run_id, tax_type, logical_name,
                     storage_path, artifact_kind, status, expires_at)
                VALUES
                    (:user_id, :upload_id, :run_id, :tax_type, :logical_name,
                     :storage_path, :artifact_kind, :status, :expires_at)
                """
            ),
            {
                "user_id": int(user_id),
                "upload_id": upload_id,
                "run_id": str(run_id),
                "tax_type": tax,
                "logical_name": name,
                "storage_path": str(path),
                "artifact_kind": kind,
                "status": status_value,
                "expires_at": expires_at,
            },
        )
        artifact_id = result.lastrowid
    return resolve_artifact(artifact_id, engine=engine, authorize=False)


def resolve_artifact(artifact_id, *, engine=None, authorize=True):
    with _engine(engine).connect() as conn:
        row = conn.execute(
            text("SELECT * FROM generated_artifacts WHERE id = :id LIMIT 1"),
            {"id": artifact_id},
        ).first()
    artifact = _row_mapping(row)
    if artifact is None:
        raise ArtifactNotFoundError("Artifact not found")
    if authorize and not authorize_artifact(artifact):
        raise ArtifactAuthorizationError("Artifact access denied")
    return artifact


def authorize_artifact(artifact, *, user_id=None, admin=None) -> bool:
    """Use the existing RBAC admin decision and ownership helper."""
    if admin is None:
        admin = is_global_admin()
    if admin:
        return True
    if user_id is None:
        user_id = current_user_id()
    return can_access_owner(artifact.get("user_id")) if user_id is None else (
        user_id is not None and str(artifact.get("user_id")) == str(user_id)
    )


def get_artifact_path(artifact, *, authorize=True) -> Path:
    if authorize and not authorize_artifact(artifact):
        raise ArtifactAuthorizationError("Artifact access denied")
    path = artifact_path(
        artifact["user_id"],
        artifact["run_id"],
        artifact["artifact_kind"],
        artifact["logical_name"],
    )
    recorded = Path(str(artifact["storage_path"])).resolve()
    if path != recorded:
        raise ValueError("Artifact storage metadata does not match its server path")
    return path


def mark_artifact_status(artifact_id, status, *, engine=None):
    status_value = str(status or "").strip().lower()
    if not status_value or len(status_value) > 20:
        raise ValueError("Invalid artifact status")
    with _engine(engine).begin() as conn:
        result = conn.execute(
            text("UPDATE generated_artifacts SET status = :status WHERE id = :id"),
            {"status": status_value, "id": artifact_id},
        )
    if not result.rowcount:
        raise ArtifactNotFoundError("Artifact not found")
    return resolve_artifact(artifact_id, engine=engine, authorize=False)


def safe_delete_artifact(artifact_id, *, engine=None):
    """Delete only one authorized artifact file and mark its metadata deleted."""
    artifact = resolve_artifact(artifact_id, engine=engine, authorize=True)
    path = get_artifact_path(artifact, authorize=False)
    if path.exists():
        if not path.is_file():
            raise ValueError("Artifact path is not a file")
        path.unlink()
    return mark_artifact_status(artifact_id, "deleted", engine=engine)
