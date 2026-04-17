"""Helpers for resolving repository data files across local and container layouts."""

from __future__ import annotations

from pathlib import Path


def _candidate_data_roots(anchor: Path) -> list[Path]:
    roots: list[Path] = []

    for depth in (4, 3, 2):
        if len(anchor.parents) > depth:
            roots.append(anchor.parents[depth] / "data")

    cwd = Path.cwd()
    roots.extend(
        [
            cwd / "data",
            cwd.parent / "data",
            Path("/app/data"),
            Path("/data"),
        ]
    )

    deduped: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        deduped.append(root)

    return deduped


def resolve_data_file(anchor_file: str | Path, *parts: str) -> Path:
    """Resolve a data file path robustly for local and Docker runtime layouts."""
    anchor = Path(anchor_file).resolve()
    roots = _candidate_data_roots(anchor)

    for root in roots:
        candidate = root.joinpath(*parts)
        if candidate.exists():
            return candidate

    # Fall back to the first candidate path for deterministic error messages.
    return roots[0].joinpath(*parts)
