"""Privacy and security helpers for local backend enforcement."""

from __future__ import annotations

from pathlib import Path

PRIVATE_FILE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700


def ensure_private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(PRIVATE_DIR_MODE)
    except OSError:
        pass
    return path


def write_private_file(path: Path, file_bytes: bytes) -> Path:
    ensure_private_directory(path.parent)
    path.write_bytes(file_bytes)
    try:
        path.chmod(PRIVATE_FILE_MODE)
    except OSError:
        pass
    return path


def build_privacy_policy_payload(
    *,
    upload_retention_days: int,
    artifact_retention_days: int,
) -> dict:
    return {
        "status": "ok",
        "retention": {
            "upload_retention_days": upload_retention_days,
            "artifact_retention_days": artifact_retention_days,
        },
        "controls": {
            "artifact_access_audited": True,
            "api_failure_detail": "sanitized",
            "uploads_private_permissions": True,
            "artifact_store_private_permissions": True,
            "share_events_recorded": True,
        },
    }
