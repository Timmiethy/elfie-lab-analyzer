from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_RESULT_FIELDS = {
    "schema_version",
    "task_id",
    "status",
    "summary",
    "changed_files",
    "commands_executed",
    "test_results",
    "evidence",
    "risks",
    "followups",
}



def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"json_root_must_be_object:{path}")
    return payload



def _normalize_rel_path(path_value: str) -> str:
    return str(Path(path_value)).replace("\\", "/").lstrip("./")



def _scope_match(rel_path: str, scope: str) -> bool:
    normalized_scope = _normalize_rel_path(scope)
    if any(char in normalized_scope for char in "*?[]"):
        return fnmatch.fnmatch(rel_path, normalized_scope)
    if rel_path == normalized_scope:
        return True
    prefix = normalized_scope.rstrip("/") + "/"
    return rel_path.startswith(prefix)



def _is_allowed_path(rel_path: str, allowed_paths: list[str], forbidden_paths: list[str]) -> bool:
    if any(_scope_match(rel_path, forbidden) for forbidden in forbidden_paths):
        return False
    return any(_scope_match(rel_path, allowed) for allowed in allowed_paths)



def _validate_structure(result: dict[str, Any], errors: list[str]) -> None:
    missing = sorted(REQUIRED_RESULT_FIELDS.difference(result.keys()))
    if missing:
        errors.append(f"missing_fields:{','.join(missing)}")

    if result.get("schema_version") != "worker-result-v1":
        errors.append("schema_version_mismatch")

    if result.get("status") not in {"completed", "blocked", "failed"}:
        errors.append("invalid_status")

    for key in ["changed_files", "commands_executed", "test_results", "evidence", "risks", "followups"]:
        if key in result and not isinstance(result.get(key), list):
            errors.append(f"field_not_list:{key}")

    for index, command_item in enumerate(result.get("commands_executed", [])):
        if not isinstance(command_item, dict):
            errors.append(f"invalid_command_item_type:{index}")
            continue
        if "command" not in command_item or "exit_code" not in command_item or "purpose" not in command_item:
            errors.append(f"invalid_command_item_fields:{index}")

    for index, test_item in enumerate(result.get("test_results", [])):
        if not isinstance(test_item, dict):
            errors.append(f"invalid_test_item_type:{index}")
            continue
        if "name" not in test_item or "status" not in test_item:
            errors.append(f"invalid_test_item_fields:{index}")

    for index, evidence_item in enumerate(result.get("evidence", [])):
        if not isinstance(evidence_item, dict):
            errors.append(f"invalid_evidence_item_type:{index}")
            continue
        if "summary" not in evidence_item:
            errors.append(f"invalid_evidence_item_fields:{index}")

    if not isinstance(result.get("summary"), str) or len(result.get("summary", "").strip()) < 5:
        errors.append("summary_too_short")



def _validate_completed_minimums(
    result: dict[str, Any],
    errors: list[str],
    *,
    required_command_count: int,
    required_test_count: int,
) -> None:
    if result.get("status") != "completed":
        return

    if required_command_count > 0 and not result.get("commands_executed"):
        errors.append("completed_without_commands")
    if required_test_count > 0 and not result.get("test_results"):
        errors.append("completed_without_test_results")
    if not result.get("evidence"):
        errors.append("completed_without_evidence")



def _validate_against_packet(result: dict[str, Any], packet: dict[str, Any], errors: list[str]) -> None:
    if str(result.get("task_id")) != str(packet.get("task_id")):
        errors.append("task_id_mismatch")

    allowed_paths = [str(path) for path in packet.get("allowed_paths", [])]
    forbidden_paths = [str(path) for path in packet.get("forbidden_paths", [])]

    for changed_path in result.get("changed_files", []):
        rel_path = _normalize_rel_path(str(changed_path))
        if not _is_allowed_path(rel_path, allowed_paths, forbidden_paths):
            errors.append(f"changed_path_out_of_scope:{rel_path}")

    if result.get("status") != "completed":
        return

    commands = [
        str(command_item.get("command", ""))
        for command_item in result.get("commands_executed", [])
        if isinstance(command_item, dict)
    ]
    tests = [
        test_item
        for test_item in result.get("test_results", [])
        if isinstance(test_item, dict)
    ]

    for required_command in packet.get("required_commands", []):
        token = str(required_command)
        if token and not any(token in command for command in commands):
            errors.append(f"required_command_missing:{token}")

    for required_test in packet.get("required_tests", []):
        token = str(required_test)
        passed = any(
            token in str(test_result.get("name", "")) and str(test_result.get("status")) == "passed"
            for test_result in tests
        )
        if token and not passed:
            errors.append(f"required_test_not_passed:{token}")



def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate worker_result JSON against schema and packet scope.")
    parser.add_argument("--result", required=True, help="Path to worker result JSON.")
    parser.add_argument("--task-packet", help="Optional task packet JSON for scope checks.")
    parser.add_argument(
        "--allow-noncompleted",
        action="store_true",
        help="Allow blocked/failed status to pass structural validation (default is fail closed).",
    )
    return parser.parse_args()



def main() -> int:
    args = _parse_args()

    result_path = Path(args.result).resolve()
    result = _load_json(result_path)

    errors: list[str] = []
    required_command_count = 0
    required_test_count = 0

    if args.task_packet:
        packet_path = Path(args.task_packet).resolve()
        packet = _load_json(packet_path)
        required_command_count = len(packet.get("required_commands", []))
        required_test_count = len(packet.get("required_tests", []))
        _validate_against_packet(result, packet, errors)

    _validate_structure(result, errors)
    _validate_completed_minimums(
        result,
        errors,
        required_command_count=required_command_count,
        required_test_count=required_test_count,
    )

    if not args.allow_noncompleted and result.get("status") != "completed":
        errors.append(f"non_completed_status:{result.get('status')}")

    if errors:
        print("Worker result validation FAILED")
        for error in errors:
            print(f" - {error}")
        return 1

    print("Worker result validation PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
