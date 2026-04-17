# Repository Guidelines

## Project Overview
Elfie Labs Analyzer is a full-stack lab report understanding system. Users upload lab PDFs/images, the backend extracts structured observations, maps analytes to LOINC, evaluates deterministic policies, and renders patient-friendly plus clinician-share artifacts.

This repository now uses a **supervised autonomous orchestration model**:
- **GitHub Copilot** is the Product Manager/Orchestrator agent.
- **Gemini CLI** is the coding/debugging worker agent.
- **Human supervisor** is the final approval gate.

The frontend is already in place. Orchestration emphasis is backend-first.

## Non-Negotiable Truthfulness
Never try to cheat. If you don't know something, say you don't know. If you need to look something up, say you need to look it up. If you need to run code to find the answer, say you need to run code. Always be honest about what you know and what you don't know.

## Role Contract
### Copilot Orchestrator
- Owns planning, decomposition, wave ordering, and gate decisions.
- Emits machine-readable task packets for workers.
- Never marks work complete without command/test evidence.

### Gemini Worker
- Executes exactly one task packet scope at a time.
- Returns only schema-valid worker result artifacts.
- Fails closed if requirements are ambiguous or unverifiable.

### Human Supervisor
- Approves policy-changing, contract-changing, or safety-impacting merges.
- Decides on unresolved blockers and risk acceptance.

## Workflow Orchestration Protocol
### 1. Plan-First Default
- Enter plan mode for any non-trivial task (3+ steps or architecture decisions).
- If execution drifts or fails, stop and re-plan before continuing.
- Plan verification steps up front (not only implementation tasks).

### 2. Task Packet Contract (Orchestrator -> Worker)
Each packet must include:
- `schema_version`
- `task_id`
- `objective`
- `repo_root`
- `allowed_paths`
- `forbidden_paths`
- `required_commands`
- `required_tests`
- `completion_definition`
- `max_prompt_tokens`
- `max_tool_calls`

Packets that omit required fields are invalid and must not be executed.

### 3. Worker Result Contract (Worker -> Orchestrator)
Each worker result must include:
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

Prose-only results are not accepted.

### 4. Deterministic Merge Gates
No merge unless all are true:
- Packet scope respected (`allowed_paths` only).
- Required commands executed with non-fabricated evidence.
- Required tests pass.
- CI passes.
- Contract fixtures still validate.

### 5. Subagent Strategy
- Use subagents liberally for exploration/research to keep primary context clean.
- Use one focused tack per subagent.
- Parallelize only when file ownership does not overlap.

### 6. Self-Improvement Loop
- After any correction, update local `tasks/lessons.md`.
- Convert repeated mistakes into explicit rules.
- Re-check lessons before similar tasks.

### 7. Verification Before Done
- Never mark done without proving behavior.
- Diff behavior when relevant (before/after).
- Ask: "Would a staff engineer approve this?"

### 8. Autonomous Bug Fixing
- When given a bug report, diagnose and fix directly.
- Drive from logs/tests/errors, then verify with tests.

## Token-Efficiency Protocol (Mandatory)
- Keep worker context packets minimal: touched files + direct dependencies only.
- Prefer targeted commands (`rg`, narrow tests, focused diffs).
- Avoid dumping raw logs; summarize into structured evidence fields.
- Enforce packet token/tool-call budgets.
- Parallelize at wave level only when scopes are disjoint.

## Clinical and Runtime Guardrails (Must Hold)
- Runtime clinical logic must remain deterministic and table-driven.
- Severity and next-step classes come from explicit policy code/tables, not model improvisation.
- Unsupported/ambiguous rows must remain visible in `not_assessed`/unsupported outputs.
- No interpreted finding without lineage/provenance.
- Preserve trust-state semantics (trusted vs non-trusted-beta) unless contract version is intentionally changed.

## Security and Compliance Guardrails
- Never commit secrets, credentials, or real patient data.
- Keep API keys in environment files, not source.
- Do not place secrets in prompts, task packets, or worker results.
- Keep MCP servers untrusted by default; allowlist tools explicitly.

## Project Structure & Module Organization
- `backend/`: FastAPI app, async SQLAlchemy models, Alembic migrations, processing pipeline.
- `backend/app/api/routes/`: `/api` routes (health/upload/jobs/artifacts).
- `backend/app/services/`: parsing, OCR/image, mapping, rules, severity/nextstep, explanation, lineage, rendering.
- `backend/app/workers/pipeline.py`: orchestration entrypoint.
- `backend/tests/`: pytest suites (`unit/`, `integration/`).
- `frontend/`: Vite + React + TypeScript client.
- `data/`: alias, policy, LOINC, UCUM inputs.
- `artifacts/`: generated output storage.
- `scripts/`: operational helper scripts and agent orchestrator scripts.
- `contracts/examples/`: frozen contract payload examples.

## Build, Test, and Development Commands
Backend commands run from `backend/`:
- `pip install -e ".[dev]"`
- `pip install -e ".[dev,image-beta]"`
- `uvicorn app.main:app --reload`
- `pytest`
- `pytest tests/unit/`
- `pytest tests/integration/`
- `ruff check .`
- `ruff format .`
- `mypy .`
- `alembic upgrade head`

Frontend commands run from `frontend/`:
- `npm install`
- `npm run dev`
- `npm run build`
- `npm run lint`
- `npm run preview`

Repo-root commands:
- `docker compose up`

## Testing Guidelines
- Add tests close to changed behavior (`unit/` or `integration/`).
- Keep shared fixtures in `backend/tests/conftest.py`.
- For pipeline changes, validate row extraction contracts, mapping, policy output, and artifacts.
- Keep contract examples aligned with schema versions.

## Environment & Configuration Notes
- Copy `.env.example` to `.env` before backend work.
- Runtime config uses `ELFIE_` prefix in `backend/app/config.py`.
- Key vars: `ELFIE_DATABASE_URL`, `ELFIE_DATABASE_URL_SYNC`, `ELFIE_QWEN_API_KEY`, `ELFIE_QWEN_BASE_URL`, `ELFIE_QWEN_MODEL`, `ELFIE_QWEN_VL_MODEL`, `ELFIE_IMAGE_BETA_ENABLED`.
- Qwen provider for project runtime is Alibaba Cloud (`dashscope.aliyuncs.com`).

## Task Management (Local Scratch Workflow)
- Use local `tasks/todo.md` and `tasks/lessons.md` for active sessions.
- Seed local files from committed templates:
	- `tasks/todo.example.md`
	- `tasks/lessons.example.md`
- Keep live scratch files uncommitted.

## Definition of Done
Work is done only when:
1. Requirements are fully implemented within approved scope.
2. Required tests pass locally (and in CI where applicable).
3. Contract compatibility is preserved or intentionally versioned.
4. Worker result artifacts contain verifiable evidence.
5. Risks and follow-ups are explicitly documented.

## Working Guidelines
- Preserve pipeline stage boundaries unless intentional architecture change is approved.
- Keep backend/frontend contract changes synchronized.
- Update docs/scripts/migrations when changing source-of-truth data shape.
- Prefer simple, explicit, minimal-impact changes.

