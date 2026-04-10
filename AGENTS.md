# Repository Guidelines

## Project Overview
Elfie Labs Analyzer is a full-stack lab report understanding feature. Users upload lab PDFs or images, the backend extracts structured observations, maps analytes to LOINC, evaluates clinical rules, and renders patient-friendly and clinician-share artifacts. The repo is split into a Python FastAPI backend and a Vite + React + TypeScript frontend.

## Workflow Orchestration
Never try to cheat. If you don't know something, say you don't know. If you need to look something up, say you need to look it up. If you need to run code to find the answer, say you need to run code. Always be honest about what you know and what you don't know.

### 1. Plan Node Default
- Enter plan mode for any non-trivial task involving 3 or more steps or architectural decisions.
- If something goes sideways, stop and re-plan immediately instead of pushing through blindly.
- Use plan mode for verification steps, not just implementation.
- Write detailed specs upfront to reduce ambiguity.

### 2. Subagent Strategy
- Use subagents liberally to keep the main context window clean.
- Offload research, exploration, and parallel analysis to subagents.
- For complex problems, use subagents to increase parallel compute and focused investigation.
- Keep one tack per subagent for focused execution.

### 3. Self-Improvement Loop
- After any correction from the user, update `tasks/lessons.md` with the pattern.
- Write rules that prevent the same mistake from recurring.
- Ruthlessly iterate on these lessons until the mistake rate drops.
- Review lessons at session start when they are relevant to the project.
- Treat `tasks/lessons.md` as a local workflow file and do not commit it.

### 4. Verification Before Done
- Never mark a task complete without proving it works.
- Diff behavior between main and your changes when relevant.
- Ask: `Would a staff engineer approve this?`
- Run tests, check logs, and demonstrate correctness before closing out work.

### 5. Demand Elegance (Balanced)
- For non-trivial changes, pause and ask whether there is a more elegant solution.
- If a fix feels hacky, revisit it with full context and implement the cleaner version.
- Skip this for simple, obvious fixes to avoid over-engineering.
- Challenge your own work before presenting it.

### 6. Autonomous Bug Fixing
- When given a bug report, fix it without requiring hand-holding.
- Use logs, errors, and failing tests to drive the investigation and resolution.
- Minimize context switching for the user.
- Fix failing CI-style issues proactively when they are in scope.

## Task Management
1. Clear `tasks/todo.md` entirely and write a fresh plan with checkable items.
2. Verify the plan before starting implementation.
3. Mark items complete as progress is made.
4. Explain changes at a high level during each step.
5. Add a review/results section to `tasks/todo.md`.
6. Update `tasks/lessons.md` after corrections.
7. Treat everything under `tasks/` as local workflow scratch space and never commit it.

## Core Principles
- Simplicity first: make every change as simple as possible and minimize code impact.
- No laziness: find root causes, avoid temporary fixes, and hold changes to senior developer standards.
- Minimal impact: only touch what is necessary and avoid introducing regressions.

## Project Structure & Module Organization
- `backend/`: FastAPI application, async SQLAlchemy models, Alembic migrations, and the processing pipeline.
- `backend/app/api/routes/`: HTTP routes under `/api` such as `health`, `upload`, `jobs`, and `artifacts`.
- `backend/app/services/`: domain services for parsing, OCR, analyte resolution, rule evaluation, severity/next-step policies, explanation, lineage, and rendering.
- `backend/app/workers/pipeline.py`: orchestration entry point for the multi-step lab analysis flow.
- `backend/tests/`: pytest-based test suite with `unit/` and `integration/` directories.
- `frontend/`: Vite React client.
- `frontend/src/components/`: feature-oriented UI folders such as `upload`, `processing`, `patient_artifact`, `history_card`, `guided_ask`, and `clinician_share`.
- `frontend/src/services/api.ts`: frontend API client.
- `frontend/src/i18n/`: English and Vietnamese translations.
- `data/`: terminology and mapping inputs such as LOINC, alias tables, and UCUM resources.
- `artifacts/`: generated output storage mounted into the backend container.
- `scripts/`: local helper scripts such as terminology import and DB setup.
- `docs/` and `labs_analyzer_v10_*.md`: design references and guardrails. Read these before making large architectural changes.

## Build, Test, and Development Commands
Backend commands run from `backend/`:
- `pip install -e ".[dev]"`: install app and dev dependencies.
- `pip install -e ".[dev,image-beta]"`: include OCR/image-beta extras.
- `uvicorn app.main:app --reload`: start the API locally on port `8000`.
- `pytest`: run the backend test suite.
- `pytest tests/unit/`: run unit tests only.
- `pytest tests/integration/`: run integration tests only.
- `ruff check .`: lint Python code.
- `ruff format .`: format Python code.
- `mypy .`: run strict type checking.
- `alembic upgrade head`: apply DB migrations.

Frontend commands run from `frontend/`:
- `npm install`: install frontend dependencies.
- `npm run dev`: start Vite dev server on port `5173`.
- `npm run build`: type-check and build for production.
- `npm run lint`: run ESLint.
- `npm run preview`: preview the production build.

Repo-root commands:
- `docker compose up`: start Postgres and the backend with mounted `data/` and `artifacts/`.

## Coding Style & Naming Conventions
- Python targets `3.11` and uses Ruff plus strict MyPy. Keep type annotations complete and prefer small, explicit service functions over implicit shared state.
- Follow the existing Python layout: domain code under `app/services/`, schemas under `app/schemas/`, DB models under `app/models/`, and route wiring under `app/api/routes/`.
- React code uses TypeScript, functional components, semicolons, and single quotes. Match the current lightweight Vite setup instead of adding framework-heavy abstractions.
- Keep frontend components organized by feature folder. Existing component directories use lowercase names with `index.tsx`; follow that pattern unless there is a strong reason to change it.
- Prefer descriptive names tied to lab-processing concepts such as `observation`, `artifact`, `lineage`, `rule_event`, and `mapping_candidate`.

## Testing Guidelines
- Put backend tests under `backend/tests/unit/` or `backend/tests/integration/` based on scope.
- Extend `backend/tests/conftest.py` for shared fixtures instead of duplicating setup across tests.
- When changing pipeline logic, add or update tests around the affected stage and nearby contracts, especially schema shape, policy output, and artifact rendering.
- The frontend currently has no dedicated test runner configured. If you add one, keep it lightweight, document it in `frontend/package.json`, and place tests close to the affected UI code.

## Environment & Configuration Notes
- Copy `.env.example` to `.env` before local backend work.
- All runtime config uses the `ELFIE_` prefix via `pydantic-settings` in `backend/app/config.py`.
- Key env vars include `ELFIE_DATABASE_URL`, `ELFIE_DATABASE_URL_SYNC`, `ELFIE_QWEN_API_KEY`, `ELFIE_QWEN_BASE_URL`, `ELFIE_QWEN_MODEL`, `ELFIE_QWEN_VL_MODEL`, and `ELFIE_IMAGE_BETA_ENABLED`.
- The backend assumes local defaults for Postgres and allows frontend CORS from `http://localhost:5173`.
- Avoid committing secrets, real patient data, or generated artifact payloads that should stay local.

## Working Guidelines
- Preserve the pipeline stage boundaries unless the change intentionally reshapes the architecture. This repo is easier to reason about when parsing, normalization, policy evaluation, explanation, and rendering remain separate concerns.
- If you change API contracts, keep backend schemas, routes, and frontend `src/services/api.ts` in sync.
- If you change terminology inputs or DB shape, update the relevant script, migration, and any docs that describe the source of truth.
- For larger product or architecture shifts, review `CLAUDE.md` and the `labs_analyzer_v10_*.md` docs first so implementation stays aligned with the existing design direction.
