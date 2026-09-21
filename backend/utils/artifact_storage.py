"""Safe paths for newly generated, user/run-scoped artifacts.

This module only establishes the Phase 1 storage contract. Existing tax
pipeline directories are deliberately not used or migrated here.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from utils.file_utils import get_backend_storage_dir


class ArtifactStorageError(ValueError):
    """Raised when an artifact path input is unsafe or invalid."""


_TAX_TYPES = {"GST", "SWT", "CIT"}
_ARTIFACT_KINDS = {"input", "validation", "result", "report", "export"}
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def get_artifact_storage_root() -> Path:
    """Return the configurable root for new artifacts only."""
    configured = os.getenv("RBA_ARTIFACT_STORAGE_ROOT", "").strip()
    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        root = Path(get_backend_storage_dir("storage", "artifacts")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_component(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text or text in {".", ".."} or not _SAFE_COMPONENT.fullmatch(text):
        raise ArtifactStorageError(f"Invalid {label}")
    return text


def normalize_tax_type(tax_type: object) -> str:
    normalized = str(tax_type or "").strip().upper()
    if normalized not in _TAX_TYPES:
        raise ArtifactStorageError("Invalid tax type")
    return normalized


def normalize_artifact_kind(artifact_kind: object) -> str:
    normalized = str(artifact_kind or "").strip().lower()
    if normalized not in _ARTIFACT_KINDS:
        raise ArtifactStorageError("Invalid artifact kind")
    return normalized


def normalize_logical_name(logical_name: object) -> str:
    raw = str(logical_name or "").strip()
    if not raw or "\x00" in raw or Path(raw).is_absolute():
        raise ArtifactStorageError("Invalid logical name")
    if raw.replace("\\", "/").split("/")[-1] != raw or ".." in raw.replace("\\", "/").split("/"):
        raise ArtifactStorageError("Invalid logical name")
    return _safe_component(raw, "logical name")


def artifact_run_directory(user_id: object, run_id: object, *, create: bool = False) -> Path:
    root = get_artifact_storage_root()
    user_component = _safe_component(user_id, "user id")
    run_component = _safe_component(run_id, "run id")
    directory = (root / "users" / user_component / "runs" / run_component).resolve()
    if root not in directory.parents:
        raise ArtifactStorageError("Artifact path escaped storage root")
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def artifact_path(
    user_id: object,
    run_id: object,
    artifact_kind: object,
    logical_name: object,
    *,
    create: bool = False,
) -> Path:
    """Build a path entirely from validated server-side values."""
    run_dir = artifact_run_directory(user_id, run_id, create=create)
    kind = normalize_artifact_kind(artifact_kind)
    name = normalize_logical_name(logical_name)
    path = (run_dir / kind / name).resolve()
    if get_artifact_storage_root() not in path.parents:
        raise ArtifactStorageError("Artifact path escaped storage root")
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def is_artifact_path(path: object) -> bool:
    """Return whether a path is contained by the configured artifact root."""
    try:
        root = get_artifact_storage_root()
        candidate = Path(path).resolve()
        return candidate == root or root in candidate.parents
    except (OSError, TypeError, ValueError):
        return False
