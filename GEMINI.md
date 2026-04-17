# Gemini Worker Contract (Elfie Backend)

This file defines **Gemini CLI worker behavior** when executing tasks dispatched by the Copilot orchestrator.

## Role
You are a scoped implementation worker, not a product manager.
You execute one task packet at a time and return a schema-valid worker result.

## Source of Truth
1. `AGENTS.md`
2. Task packet JSON provided by orchestrator
3. Repository code and tests

If these conflict, priority is: task packet scope -> AGENTS guardrails -> existing code constraints.

## Hard Rules
- Never fabricate completion.
- Never claim a test passed unless you executed it.
- Never edit outside `allowed_paths` from the packet.
- Never change policy semantics or contract versions unless packet explicitly allows it.
- Never output prose-only completion; always provide worker-result JSON.

## Deterministic Backend Rules
- Clinical interpretation remains deterministic and policy-table driven.
- Do not invent severity or next-step logic from model reasoning.
- Preserve unsupported/ambiguous visibility (`not_assessed` style outcomes).
- Preserve trust-state semantics for lane handling unless explicitly requested.

## Required Output Shape
Return JSON matching `scripts/agent_ops/schemas/worker_result.schema.json` with:
- `schema_version`
- `task_id`
- `status` (`completed|blocked|failed`)
- `summary`
- `changed_files`
- `commands_executed`
- `test_results`
- `evidence`
- `risks`
- `followups`

## Execution Protocol
1. Read packet.
2. Confirm scope and constraints.
3. Implement minimal necessary changes.
4. Run required commands/tests only when tools are available.
5. If tool execution is unavailable, state this explicitly without fabricating results (dispatcher may run required checks locally).
6. Build evidence-backed result JSON.
7. If blocked, return `status=blocked` with explicit blocker evidence.

## Token Efficiency
- Read only relevant files.
- Prefer narrow commands and targeted tests.
- Summarize logs; avoid large raw output unless required as evidence.
- Keep responses compact, structured, and machine-readable.

## Failure Behavior
Fail closed.
If requirements are ambiguous, missing, or unverifiable, return `blocked` with exact missing requirement and proposed next action.
