# Subagent Task Template

Use this template for any substantial delegated task.

## 1. Dispatch Header

| Field | Value |
|---|---|
| `task_id` | `TASK-{YYYYMMDD}-{###}` |
| `task_name` | short imperative title |
| `assigned_to` | agent name |
| `delegated_by` | parent agent |
| `priority` | `critical` / `high` / `medium` / `low` |
| `delegation_mode` | `in_session_subagent` / `isolated_run` |
| `timebox` | e.g. `10m`, `25m`, `60m` |
| `max_steps` | optional hard cap for agentic iterations |

## 2. Objective

State:

- what must be done
- why it matters to the parent task
- what successful completion produces

## 3. Task Boundary

Define exactly:

- `owned_scope`
- `forbidden_scope`
- `source_of_truth`
- `validated_assumptions`
- `open_unknowns`

Example:

```yaml
owned_scope:
  - src/runtime/session.ts
  - tests/session-export.test.ts
forbidden_scope:
  - docs/**
  - tooling/**
source_of_truth:
  - README.md
  - docs/contracts.md
validated_assumptions:
  - the export bug reproduces on current branch
  - parser contract is unchanged
open_unknowns:
  - exact failure path inside export parsing
```

## 4. Inputs

List only what the subagent actually needs.

| Name | Type | Location / Value | Notes |
|---|---|---|---|
| `repo_root` | `path` | `/abs/path/...` | required |
| `target_files` | `list[path]` | `[...]` | required |
| `upstream_notes` | `text` | `...` | optional |

## 5. Execution Instructions

1. Do the minimum exploration needed to act within `owned_scope`.
2. Complete only the assigned slice.
3. Do not broaden the task into cleanup or refactors unless explicitly allowed.
4. If blocked, return a blocker report with evidence instead of an open-ended question.
5. If `delegation_mode = isolated_run`, treat the task as stateless and do not assume parent-session context.

## 6. Decision Rules

Define:

- `may_decide`
- `must_escalate`
- `stop_conditions`

Example:

```yaml
may_decide:
  - add focused tests within owned_scope
  - rename local variables for clarity
must_escalate:
  - changing public interfaces
  - editing files outside owned_scope
  - adding dependencies
stop_conditions:
  - root cause cannot be isolated within timebox
  - required tool or input is unavailable
```

## 7. Output Contract

Deliver exactly:

- `summary`: 2-4 sentences
- `status`: `success` / `partial` / `failed`
- `outputs`: paths, identifiers, or structured results
- `evidence`: tests run, commands run, or observations proving completion
- `issues`: blockers, risks, deviations
- `next_actions`: only if needed

If code changed, also include:

- `files_touched`
- `verification_performed`
- `residual_risks`

## 8. Acceptance Criteria

- work stays inside `owned_scope`
- output matches the requested format
- verification evidence is included
- deviations are explicitly called out
- no silent assumptions were introduced

## 9. Failure Handling

| Scenario | Required action |
|---|---|
| Missing input | return `failed` with `missing_input` and name the missing item |
| Ambiguous instruction | return `partial` with one specific escalation question |
| Tool failure | retry if instructed; otherwise return evidence of failure |
| Out-of-scope issue discovered | report it, do not absorb it |
| Timebox exceeded | return `partial` with completed work and best next step |

## 10. Completion Format

```text
TASK COMPLETION REPORT
Task ID: TASK-{ID}
Status: success | partial | failed

Summary:
{2-4 sentence summary}

Files Touched:
- /abs/path/file1
- /abs/path/file2

Outputs:
- {artifact or result}

Evidence:
- {test / command / observed result}

Issues:
- None
```
