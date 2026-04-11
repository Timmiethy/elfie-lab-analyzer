"""Proof-pack file helpers."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from app.config import settings
from app.services.privacy import write_private_file


def proof_pack_route(job_id: UUID | str) -> str:
    return f"/api/jobs/{job_id}/proof-pack"


def proof_pack_path(job_id: UUID | str) -> Path:
    return settings.artifact_store_path / "proof_packs" / f"{job_id}.json"


def write_proof_pack(job_id: UUID | str, payload: dict) -> Path:
    path = proof_pack_path(job_id)
    return write_private_file(
        path,
        json.dumps(payload, sort_keys=True, indent=2, default=str).encode("utf-8"),
    )


def read_proof_pack(job_id: UUID | str) -> dict | None:
    path = proof_pack_path(job_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
