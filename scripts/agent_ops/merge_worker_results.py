from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any



def _load_result(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"result_root_not_object:{path}")
    return payload



def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge multiple worker result files into one wave bundle.")
    parser.add_argument("--wave-id", required=True, help="Wave identifier for aggregated output.")
    parser.add_argument("--results", nargs="+", required=True, help="List of worker result JSON files.")
    parser.add_argument("--output", required=True, help="Path to write merged bundle JSON.")
    return parser.parse_args()



def main() -> int:
    args = _parse_args()

    result_paths = [Path(item).resolve() for item in args.results]
    loaded_results = [_load_result(path) for path in result_paths]

    task_rows: list[dict[str, Any]] = []
    unresolved_blockers: list[dict[str, Any]] = []
    required_human_decisions: list[str] = []

    counts = {"completed": 0, "blocked": 0, "failed": 0}

    for result_path, result in zip(result_paths, loaded_results, strict=True):
        task_id = str(result.get("task_id") or "unknown-task")
        status = str(result.get("status") or "failed")
        summary = str(result.get("summary") or "")

        if status not in counts:
            status = "failed"
        counts[status] += 1

        task_rows.append(
            {
                "task_id": task_id,
                "status": status,
                "summary": summary,
                "result_file": str(result_path),
            }
        )

        if status in {"blocked", "failed"}:
            risks = [str(item) for item in result.get("risks", [])]
            followups = [str(item) for item in result.get("followups", [])]
            unresolved_blockers.append(
                {
                    "task_id": task_id,
                    "status": status,
                    "summary": summary,
                    "risks": risks,
                    "followups": followups,
                }
            )
            decision = f"Review {task_id} ({status}) and decide retry, re-scope, or human patch."
            required_human_decisions.append(decision)

    merge_bundle = {
        "schema_version": "merge-bundle-v1",
        "wave_id": args.wave_id,
        "task_ids": [str(result.get("task_id") or "unknown-task") for result in loaded_results],
        "counts": counts,
        "pass_fail_matrix": task_rows,
        "unresolved_blockers": unresolved_blockers,
        "required_human_decisions": required_human_decisions,
    }

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(merge_bundle, indent=2), encoding="utf-8")

    print(f"Merged {len(loaded_results)} worker results into {output_path}")

    if counts["failed"] > 0 or counts["blocked"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
