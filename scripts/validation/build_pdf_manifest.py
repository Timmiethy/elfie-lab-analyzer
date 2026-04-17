from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

EXPECTED_TIERS = ("easy", "medium", "hard")
DEFAULT_EXPECTED_COUNT = 39


@dataclass(frozen=True)
class PdfEntry:
    relative_path: str
    tier: str
    file_name: str
    size_bytes: int
    sha256: str


def _parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent.parent
    default_pdf_root = repo_root / "pdfs"
    default_output = repo_root / "artifacts" / "validation" / "pdf_manifest.json"

    parser = argparse.ArgumentParser(
        description="Build a deterministic PDF corpus manifest for validation runs."
    )
    parser.add_argument(
        "--pdf-root",
        type=Path,
        default=default_pdf_root,
        help="Root directory containing tiered PDF folders.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_output,
        help="Output path for generated manifest JSON.",
    )
    parser.add_argument(
        "--expected-count",
        type=int,
        default=DEFAULT_EXPECTED_COUNT,
        help="Expected number of PDFs in the corpus.",
    )
    parser.add_argument(
        "--allow-count-mismatch",
        action="store_true",
        help="Allow writing a manifest when file count differs from expected count.",
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _discover_entries(pdf_root: Path) -> list[PdfEntry]:
    entries: list[PdfEntry] = []
    for tier in EXPECTED_TIERS:
        tier_dir = pdf_root / tier
        if not tier_dir.exists() or not tier_dir.is_dir():
            continue

        for file_path in sorted(tier_dir.glob("*.pdf"), key=lambda value: value.name.lower()):
            entries.append(
                PdfEntry(
                    relative_path=file_path.relative_to(pdf_root).as_posix(),
                    tier=tier,
                    file_name=file_path.name,
                    size_bytes=file_path.stat().st_size,
                    sha256=_sha256(file_path),
                )
            )

    return entries


def _validate_tiers(entries: list[PdfEntry]) -> list[str]:
    problems: list[str] = []
    for entry in entries:
        if entry.tier not in EXPECTED_TIERS:
            problems.append(
                f"Unsupported tier '{entry.tier}' for file {entry.relative_path}."
            )
    return problems


def _build_manifest(pdf_root: Path, entries: list[PdfEntry]) -> dict:
    per_tier: dict[str, list[str]] = {tier: [] for tier in EXPECTED_TIERS}
    for entry in entries:
        per_tier[entry.tier].append(entry.relative_path)

    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "pdf_root": str(pdf_root.resolve()),
        "total_files": len(entries),
        "tiers": {
            tier: {
                "count": len(per_tier[tier]),
                "files": per_tier[tier],
            }
            for tier in EXPECTED_TIERS
        },
        "files": [
            {
                "relative_path": entry.relative_path,
                "tier": entry.tier,
                "file_name": entry.file_name,
                "size_bytes": entry.size_bytes,
                "sha256": entry.sha256,
            }
            for entry in entries
        ],
    }


def main() -> int:
    args = _parse_args()
    pdf_root = args.pdf_root.resolve()
    if not pdf_root.exists() or not pdf_root.is_dir():
        raise SystemExit(f"PDF root does not exist or is not a directory: {pdf_root}")

    entries = _discover_entries(pdf_root)
    problems = _validate_tiers(entries)

    if args.expected_count >= 0 and len(entries) != args.expected_count:
        mismatch = (
            f"Expected {args.expected_count} PDFs but found {len(entries)} under {pdf_root}."
        )
        if args.allow_count_mismatch:
            problems.append(mismatch)
        else:
            raise SystemExit(mismatch)

    manifest = _build_manifest(pdf_root, entries)
    if problems:
        manifest["warnings"] = problems

    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(
        f"Wrote manifest to {output_path} with {manifest['total_files']} files "
        f"(easy={manifest['tiers']['easy']['count']}, "
        f"medium={manifest['tiers']['medium']['count']}, "
        f"hard={manifest['tiers']['hard']['count']})."
    )
    if problems:
        print("Warnings:")
        for problem in problems:
            print(f"- {problem}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
