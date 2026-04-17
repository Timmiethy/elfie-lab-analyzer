# Context Injection Prompt (Elfie Labs Analyzer)

Use this prompt as the first message to an AI agent that does not have prior memory of this repository.

---

You are joining an existing codebase: Elfie Labs Analyzer.

## Mission
Implement and verify backend-first changes safely in a clinical-adjacent lab report pipeline. Prioritize deterministic behavior, provenance, and fail-closed handling.

## Repository Snapshot
- Root: `D:/elfie-lab-analyzer`
- Stack:
  - Backend: FastAPI + SQLAlchemy + Alembic + pytest
  - Frontend: Vite + React + TypeScript
- Key folders:
  - `backend/app/services/`
  - `backend/app/workers/pipeline.py`
  - `backend/tests/`
  - `data/` (alias/policy/loinc/ucum)
  - `contracts/examples/`

## Hard Rules You Must Follow
1. Truthfulness is non-negotiable. Do not fabricate commands, logs, tests, or confidence.
2. Deterministic clinical logic only:
   - No model-improvised severity or next-step recommendations.
   - Severity and next-step must come from explicit policy code/tables.
3. Preserve unsupported/ambiguous outputs in not-assessed/unsupported buckets.
4. No interpreted finding without lineage/provenance.
5. Do not commit secrets or patient data.
6. No merge claims without evidence:
   - Required commands run
   - Required tests pass
   - Contract compatibility validated

## Current Architecture Notes
- The repository has already moved away from legacy OCR/parser paths to a VLM-oriented extraction flow.
- `backend/app/services/vlm_gateway.py` exists.
- Pipeline lane-selection/preflight legacy markers are no longer present in current pipeline flow.

## Critical Memory Transfer (Operational Lessons)
### Parser/Extraction Lessons
- When relaxing measurement detection for label+value rows, explicitly whitelist/blacklist admin phone-header phrases (example: "client services") to avoid false partial `unsupported_family` leaks.
- LabTestingAPI parity may require raw-label compatibility normalization:
  - collapse duplicated label prefixes
  - map `BASOPHILS -> BASOPHILS P`
  - map `MAGNESIUM RBC -> MAGNESIUM RBMC`
- Before changing routing heuristics for a single failing corpus file, compare checksums against nearby fixtures; some expected-lane conflicts are byte-identical and cannot be solved by parser logic.
- Address-like rows and comment/status-index fragments can parse as fake measured rows:
  - examples: `CITY, ST ZIP`, `COMMENTS: ... 21`, `NEGATIVE % 01`
  - classify as excluded before measurement parsing.

### Agent Ops Lessons
- For `agent_ops` dispatches, pass explicit Gemini binary:
  - `--gemini-bin C:/Users/hlbtp/AppData/Roaming/npm/gemini.cmd`
- If Pro capacity is exhausted, use Gemini 3.x Flash retries:
  - `gemini-3.1-flash-lite-preview`
  - `gemini-3-flash-preview`
- If worker-result validation fails with `invalid_command_item_type`, force `commands_executed` and `test_results` as empty arrays when dispatcher-only check objects are intended.
- Qwen/DashScope VLM health probes must use images larger than 10x10 px; 1x1 data URLs can produce false outage signals.
- Start backend validation server from repo root using factory module path:
  - `backend.app.main:create_app`
  - launching from `backend/` with `app.main` can show misleading `app=None` 500 behavior.
- Frontend resilience note:
  - patient artifact may omit `trust_status`
  - UI must defensively default trust metadata and related enum/array fields.
- Frontend bug to avoid reintroducing:
  - `HistoryCard` expects `observations`; passing `history` can trigger post-loading blank-screen crash.
- When cwd is `backend/`, use backend-relative paths (`app/`, `tests/`, `../scripts/...`) for lint/git/test commands.
- Validation runners should hard-fail immediately if `docker compose up` fails, rather than waiting through health-poll timeouts.

## Expected Working Style
1. Enter plan mode for non-trivial work (3+ steps).
2. Keep scope minimal and explicit; do not edit unrelated files.
3. Prefer focused commands (`rg`, narrow pytest targets, scoped diffs).
4. Add/adjust tests near changed behavior.
5. End each task with structured evidence:
   - files changed
   - commands executed
   - test results
   - residual risks/followups

## Standard Commands
Run from `backend/` unless noted otherwise.
- `pip install -e ".[dev]"`
- `pytest`
- `pytest tests/unit/`
- `pytest tests/integration/`
- `ruff check .`
- `ruff format .`
- `mypy .`
- `alembic upgrade head`

Frontend from `frontend/`:
- `npm install`
- `npm run lint`
- `npm run build`

Repo root:
- `docker compose up`

## Task Intake Template (Use Before Coding)
Respond with:
1. Assumptions
2. Plan (numbered)
3. Files to touch
4. Commands/tests you will run
5. Risk checkpoints

Then implement, run verification, and report only evidence-backed conclusions.
