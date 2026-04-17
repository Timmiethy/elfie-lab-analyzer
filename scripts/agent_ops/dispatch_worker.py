from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parent
DEFAULT_TEMPLATE_PATH = SCRIPT_ROOT / "templates" / "worker_prompt.template.md"

REQUIRED_PACKET_FIELDS = {
    "schema_version",
    "task_id",
    "objective",
    "repo_root",
    "allowed_paths",
    "forbidden_paths",
    "required_commands",
    "required_tests",
    "completion_definition",
    "max_prompt_tokens",
    "max_tool_calls",
}

DISPATCH_PROMPT_HINT = "Use stdin instructions as the full task. Return only one JSON object."
REPAIR_PROMPT_HINT = "Return only one valid JSON object and nothing else."
DEFAULT_LOCAL_CHECK_TIMEOUT = 900


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"json_root_must_be_object:{path}")
    return loaded


def _validate_task_packet(packet: dict[str, Any]) -> None:
    missing = sorted(REQUIRED_PACKET_FIELDS.difference(packet.keys()))
    if missing:
        raise ValueError(f"task_packet_missing_fields:{','.join(missing)}")
    if packet.get("schema_version") != "task-packet-v1":
        raise ValueError("task_packet_schema_version_mismatch")



def _compact_packet(packet: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "schema_version",
        "task_id",
        "objective",
        "allowed_paths",
        "forbidden_paths",
        "required_commands",
        "required_tests",
        "completion_definition",
        "max_prompt_tokens",
        "max_tool_calls",
        "constraints",
        "deliverables",
    ]
    return {key: packet[key] for key in keys if key in packet}



def _build_prompt(packet: dict[str, Any], template_path: Path) -> str:
    template = template_path.read_text(encoding="utf-8")
    packet_json = json.dumps(_compact_packet(packet), ensure_ascii=True, indent=2)
    return template.replace("{{TASK_PACKET_JSON}}", packet_json)



def _extract_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    index = 0
    length = len(text)

    while index < length:
        char = text[index]
        if char != "{":
            index += 1
            continue
        try:
            obj, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            index += 1
            continue
        if isinstance(obj, dict):
            return obj
        index += 1

    return None



def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        normalized.append(str(item))
    return normalized


def _normalize_evidence(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            summary = str(item.get("summary") or "").strip()
            if not summary:
                continue
            normalized.append(
                {
                    "type": str(item.get("type") or "note"),
                    "summary": summary,
                }
            )
            continue

        summary = str(item).strip()
        if not summary:
            continue
        normalized.append({"type": "note", "summary": summary})

    return normalized



def _normalize_result(candidate: dict[str, Any], task_id: str, notes_suffix: str) -> dict[str, Any]:
    status = str(candidate.get("status") or "failed")
    if status not in {"completed", "blocked", "failed"}:
        status = "failed"

    result = {
        "schema_version": "worker-result-v1",
        "task_id": task_id,
        "status": status,
        "summary": str(candidate.get("summary") or "No worker summary provided."),
        "changed_files": _normalize_string_list(candidate.get("changed_files")),
        "commands_executed": candidate.get("commands_executed")
        if isinstance(candidate.get("commands_executed"), list)
        else [],
        "test_results": candidate.get("test_results")
        if isinstance(candidate.get("test_results"), list)
        else [],
        "evidence": _normalize_evidence(candidate.get("evidence")),
        "risks": _normalize_string_list(candidate.get("risks")),
        "followups": _normalize_string_list(candidate.get("followups")),
        "notes": str(candidate.get("notes") or "").strip(),
    }

    if result["status"] == "completed" and not result["evidence"]:
        result["evidence"] = [
            {
                "type": "note",
                "summary": "Completed packet with no required commands/tests and no code changes.",
            }
        ]

    if notes_suffix:
        note_line = notes_suffix.strip()
        if result["notes"]:
            result["notes"] = f"{result['notes']} | {note_line}"
        else:
            result["notes"] = note_line

    return result



def _failed_result(task_id: str, summary: str, notes: str = "") -> dict[str, Any]:
    return {
        "schema_version": "worker-result-v1",
        "task_id": task_id,
        "status": "failed",
        "summary": summary,
        "changed_files": [],
        "commands_executed": [],
        "test_results": [],
        "evidence": [{"type": "note", "summary": summary}],
        "risks": [summary],
        "followups": ["Inspect raw worker output and refine packet/prompt constraints."],
        "notes": notes,
    }



def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dispatch one task packet to Gemini CLI.")
    parser.add_argument("--task-packet", required=True, help="Path to task packet JSON file.")
    parser.add_argument("--output", required=True, help="Path to write worker result JSON.")
    parser.add_argument("--repo-root", help="Repository root. Defaults to packet repo_root.")
    parser.add_argument("--gemini-bin", default="gemini", help="Gemini CLI executable path.")
    parser.add_argument("--model", help="Gemini model override for this run.")
    parser.add_argument(
        "--approval-mode",
        default="auto_edit",
        choices=["default", "auto_edit", "yolo", "plan"],
        help="Gemini approval mode for the session.",
    )
    parser.add_argument(
        "--template",
        default=str(DEFAULT_TEMPLATE_PATH),
        help="Worker prompt template path.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=1800,
        help="Subprocess timeout in seconds.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write prompt artifact and return without executing Gemini.",
    )
    parser.add_argument(
        "--max-repair-attempts",
        type=int,
        default=1,
        help="Maximum Gemini retry attempts when worker JSON is not parseable.",
    )
    parser.add_argument(
        "--skip-local-required-checks",
        action="store_true",
        help="Disable local execution of required_commands/required_tests in dispatcher.",
    )
    parser.add_argument(
        "--local-check-timeout-seconds",
        type=int,
        default=DEFAULT_LOCAL_CHECK_TIMEOUT,
        help="Timeout per local required command/test execution.",
    )
    return parser.parse_args()


def _summarize_output(stdout: str, stderr: str, *, max_chars: int = 1200) -> str:
    output = (stdout or "")
    if stderr:
        output = f"{output}\n[stderr]\n{stderr}" if output else f"[stderr]\n{stderr}"
    compact = "\n".join(line for line in output.splitlines() if line.strip())
    compact = compact.strip()
    if not compact:
        return "no_output"
    if len(compact) <= max_chars:
        return compact
    return f"{compact[:max_chars]}...(truncated)"


def _apply_local_required_checks(
    *,
    result: dict[str, Any],
    packet: dict[str, Any],
    repo_root: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    required_commands = [str(item) for item in packet.get("required_commands", []) if str(item).strip()]
    required_tests = [str(item) for item in packet.get("required_tests", []) if str(item).strip()]

    if not required_commands and not required_tests:
        return result

    command_entries = result.get("commands_executed") if isinstance(result.get("commands_executed"), list) else []
    test_entries = result.get("test_results") if isinstance(result.get("test_results"), list) else []
    evidence_entries = result.get("evidence") if isinstance(result.get("evidence"), list) else []
    risk_entries = result.get("risks") if isinstance(result.get("risks"), list) else []
    followup_entries = result.get("followups") if isinstance(result.get("followups"), list) else []

    all_passed = True

    def _run_and_record(command: str, purpose: str, *, is_test: bool) -> None:
        nonlocal all_passed
        try:
            completed = subprocess.run(
                command,
                cwd=repo_root,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            exit_code = int(completed.returncode)
            summary = _summarize_output(completed.stdout, completed.stderr)
        except subprocess.TimeoutExpired:
            exit_code = 124
            summary = f"timeout_after_{timeout_seconds}s"

        command_entries.append(
            {
                "command": command,
                "exit_code": exit_code,
                "purpose": purpose,
                "output_summary": summary,
            }
        )
        evidence_entries.append(
            {
                "type": "test" if is_test else "lint",
                "summary": f"{command} => exit_code {exit_code}",
            }
        )

        if is_test:
            test_entries.append(
                {
                    "name": command,
                    "status": "passed" if exit_code == 0 else "failed",
                    "details": summary,
                }
            )

        if exit_code != 0:
            all_passed = False
            risk_entries.append(f"required_check_failed:{command}:exit_{exit_code}")

    for command in required_commands:
        _run_and_record(command, "required_command", is_test=False)

    for test_command in required_tests:
        _run_and_record(test_command, "required_test", is_test=True)

    result["commands_executed"] = command_entries
    result["test_results"] = test_entries
    result["evidence"] = evidence_entries
    result["risks"] = sorted({str(item) for item in risk_entries})
    result["followups"] = sorted({str(item) for item in followup_entries})

    if all_passed:
        if result.get("status") in {"blocked", "failed"}:
            original_status = str(result.get("status"))
            result["status"] = "completed"
            result["summary"] = (
                "Worker response was recovered and all required local checks passed. "
                f"Original status was {original_status}."
            )
    else:
        result["status"] = "failed"
        result["summary"] = "One or more required local commands/tests failed."
        result["followups"] = sorted(
            {
                *{str(item) for item in result["followups"]},
                "Inspect failed required checks in commands_executed/test_results.",
            }
        )

    return result


def _run_gemini_once(
    *,
    gemini_bin: str,
    approval_mode: str,
    model: str | None,
    prompt_hint: str,
    prompt_stdin: str,
    repo_root: Path,
    timeout_seconds: int,
) -> tuple[list[str], subprocess.CompletedProcess[str]]:
    command = [
        gemini_bin,
        "--output-format",
        "json",
        "--approval-mode",
        approval_mode,
    ]
    if model:
        command.extend(["--model", model])
    command.extend(["--prompt", prompt_hint])

    completed = subprocess.run(
        command,
        cwd=repo_root,
        input=prompt_stdin,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    return command, completed


def _build_repair_prompt(
    *,
    task_id: str,
    previous_response: str,
) -> str:
    return (
        "You returned output that was not a valid worker_result JSON object.\n"
        "Return ONLY one JSON object matching this shape and keys:\n"
        "{\n"
        "  \"schema_version\": \"worker-result-v1\",\n"
        "  \"task_id\": \"<task-id>\",\n"
        "  \"status\": \"completed|blocked|failed\",\n"
        "  \"summary\": \"string\",\n"
        "  \"changed_files\": [],\n"
        "  \"commands_executed\": [],\n"
        "  \"test_results\": [],\n"
        "  \"evidence\": [],\n"
        "  \"risks\": [],\n"
        "  \"followups\": [],\n"
        "  \"notes\": \"string\"\n"
        "}\n"
        "Use this task_id exactly: "
        f"{task_id}\n"
        "Do not include markdown fences.\n"
        "Previous invalid output:\n"
        f"{previous_response}\n"
    )


def _parse_outer_output(completed: subprocess.CompletedProcess[str], task_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if completed.returncode != 0:
        failed = _failed_result(
            task_id,
            f"gemini_nonzero_exit:{completed.returncode}",
            notes=(completed.stderr or "").strip()[:1200],
        )
        return None, failed

    try:
        outer = json.loads(completed.stdout)
    except json.JSONDecodeError:
        failed = _failed_result(task_id, "gemini_output_not_json", notes=completed.stdout[:1200])
        return None, failed

    if not isinstance(outer, dict):
        failed = _failed_result(task_id, "gemini_outer_payload_not_object")
        return None, failed

    response_text = outer.get("response")
    if not isinstance(response_text, str):
        failed = _failed_result(task_id, "gemini_response_field_missing")
        return None, failed

    return outer, None



def main() -> int:
    args = _parse_args()

    packet_path = Path(args.task_packet).resolve()
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    template_path = Path(args.template).resolve()

    started_at = datetime.now(UTC)

    try:
        packet = _load_json(packet_path)
        _validate_task_packet(packet)
    except Exception as exc:  # noqa: BLE001
        failed = _failed_result("unknown-task", f"invalid_task_packet:{exc}")
        output_path.write_text(json.dumps(failed, indent=2), encoding="utf-8")
        return 1

    task_id = str(packet["task_id"])

    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(packet["repo_root"]).resolve()
    if not repo_root.exists():
        failed = _failed_result(task_id, f"repo_root_not_found:{repo_root}")
        output_path.write_text(json.dumps(failed, indent=2), encoding="utf-8")
        return 1

    prompt = _build_prompt(packet, template_path)
    prompt_path = output_path.with_suffix(".prompt.md")
    prompt_path.write_text(prompt, encoding="utf-8")

    if args.dry_run:
        dry_result = {
            "schema_version": "worker-result-v1",
            "task_id": task_id,
            "status": "blocked",
            "summary": "Dry run complete. Prompt rendered; Gemini execution skipped.",
            "changed_files": [],
            "commands_executed": [],
            "test_results": [],
            "evidence": [{"type": "note", "path": str(prompt_path), "summary": "Prompt artifact written."}],
            "risks": ["No worker execution evidence in dry-run mode."],
            "followups": ["Run again without --dry-run."],
            "notes": "dry_run=true",
        }
        output_path.write_text(json.dumps(dry_result, indent=2), encoding="utf-8")
        return 0

    attempts: list[dict[str, Any]] = []
    try:
        command, completed = _run_gemini_once(
            gemini_bin=args.gemini_bin,
            approval_mode=args.approval_mode,
            model=args.model,
            prompt_hint=DISPATCH_PROMPT_HINT,
            prompt_stdin=prompt,
            repo_root=repo_root,
            timeout_seconds=args.timeout_seconds,
        )
        attempts.append(
            {
                "attempt": 1,
                "mode": "dispatch",
                "command": command,
                "return_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )
    except FileNotFoundError:
        failed = _failed_result(task_id, f"gemini_binary_not_found:{args.gemini_bin}")
        output_path.write_text(json.dumps(failed, indent=2), encoding="utf-8")
        return 1
    except subprocess.TimeoutExpired:
        failed = _failed_result(task_id, "gemini_timeout", notes=f"timeout_seconds={args.timeout_seconds}")
        output_path.write_text(json.dumps(failed, indent=2), encoding="utf-8")
        return 1

    finished_at = datetime.now(UTC)

    raw_record = {
        "task_id": task_id,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": int((finished_at - started_at).total_seconds()),
        "repo_root": str(repo_root),
        "attempts": attempts,
        "prompt_path": str(prompt_path),
    }
    outer, failed = _parse_outer_output(completed, task_id)
    if failed is not None:
        output_path.with_suffix(".raw.json").write_text(json.dumps(raw_record, indent=2), encoding="utf-8")
        output_path.write_text(json.dumps(failed, indent=2), encoding="utf-8")
        return 1

    assert outer is not None
    response_text = str(outer.get("response") or "")
    candidate = _extract_json_object(response_text)

    repair_attempt = 0
    while candidate is None and repair_attempt < max(0, args.max_repair_attempts):
        repair_attempt += 1
        repair_prompt = _build_repair_prompt(task_id=task_id, previous_response=response_text)
        try:
            repair_command, repair_completed = _run_gemini_once(
                gemini_bin=args.gemini_bin,
                approval_mode=args.approval_mode,
                model=args.model,
                prompt_hint=REPAIR_PROMPT_HINT,
                prompt_stdin=repair_prompt,
                repo_root=repo_root,
                timeout_seconds=args.timeout_seconds,
            )
            attempts.append(
                {
                    "attempt": repair_attempt + 1,
                    "mode": "repair",
                    "command": repair_command,
                    "return_code": repair_completed.returncode,
                    "stdout": repair_completed.stdout,
                    "stderr": repair_completed.stderr,
                }
            )
        except subprocess.TimeoutExpired:
            break

        repair_outer, repair_failed = _parse_outer_output(repair_completed, task_id)
        if repair_failed is not None:
            continue
        assert repair_outer is not None
        response_text = str(repair_outer.get("response") or "")
        candidate = _extract_json_object(response_text)

    raw_record["attempts"] = attempts
    output_path.with_suffix(".raw.json").write_text(json.dumps(raw_record, indent=2), encoding="utf-8")

    if candidate is None:
        failed = _failed_result(
            task_id,
            "worker_result_json_not_found_in_response",
            notes=response_text[:1200],
        )
        output_path.write_text(json.dumps(failed, indent=2), encoding="utf-8")
        return 1

    normalized = _normalize_result(candidate, task_id, notes_suffix="dispatched_by=dispatch_worker.py")
    if not args.skip_local_required_checks:
        normalized = _apply_local_required_checks(
            result=normalized,
            packet=packet,
            repo_root=repo_root,
            timeout_seconds=args.local_check_timeout_seconds,
        )
    output_path.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
