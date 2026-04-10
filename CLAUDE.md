# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Elfie Labs Analyzer — a patient-facing lab report understanding feature for Elfie Health Report. Users upload lab PDFs/images, the backend extracts observations, maps analytes to LOINC codes, applies clinical rules, and renders patient-friendly and clinician-share artifacts. Uses Qwen LLM for explanations and OCR (image beta lane).

## Commands

### Backend (FastAPI + Python 3.11) — from `backend/`

```bash
pip install -e ".[dev]"           # Install with dev dependencies
pip install -e ".[dev,image-beta]" # Include OCR extras (doctr, surya)
uvicorn app.main:app --reload     # Dev server on :8000
pytest                            # Run all tests
pytest tests/unit/                # Unit tests only
pytest tests/integration/         # Integration tests only
pytest -x -k "test_name"         # Run single test
ruff check .                     # Lint
ruff format .                    # Format
mypy .                           # Type checking
alembic upgrade head             # Run migrations
alembic revision --autogenerate -m "description"  # Create migration
```

### Frontend (Vite + React 19 + TypeScript) — from `frontend/`

```bash
npm install
npm run dev       # Dev server on :5173
npm run build     # Type-check + production build
npm run lint      # ESLint
```

### Docker (full stack)

```bash
docker compose up        # Postgres :5432 + backend :8000
```

### Environment

Copy `.env.example` to `.env`. All env vars use `ELFIE_` prefix (handled by pydantic-settings in `app/config.py`). Key vars: `ELFIE_DATABASE_URL`, `ELFIE_QWEN_API_KEY`, `ELFIE_IMAGE_BETA_ENABLED`.

## Architecture

### Processing Pipeline (`backend/app/workers/pipeline.py`)

The core flow is a 14-step pipeline orchestrated by `PipelineOrchestrator`:

1. **Preflight** — classify input (PDF vs image)
2. **Lane selection** — trusted PDF lane or image beta lane
3. **Extraction** — parse lab values from document (`services/parser/`, `services/ocr/`)
4. **Extraction QA** — validate extraction quality (`services/extraction_qa/`)
5. **Observation build** — create provisional observations (`services/observation_builder/`)
6. **Analyte mapping** — map raw labels to LOINC codes with abstention (`services/analyte_resolver/`)
7. **UCUM conversion** — normalize units (`services/ucum/`)
8. **Panel reconstruction** — group related tests (`services/panel_reconstructor/`)
9. **Rule evaluation** — fire deterministic clinical rules (`services/rule_engine/`)
10. **Severity assignment** — S0-S4/SX classification (`services/severity_policy/`)
11. **Next-step assignment** — A0-A4/AX action classes (`services/nextstep_policy/`)
12. **Patient artifact** — render patient-facing output (`services/artifact_renderer/`)
13. **Clinician artifact** — render clinician-share output
14. **Lineage persist** — store full reproducibility metadata (`services/lineage/`)

### Database (Postgres 16, SQLAlchemy 2.0 async)

12 core tables in `backend/app/models/tables.py`: `documents` → `jobs` → `extracted_rows` → `observations` → `mapping_candidates`, `rule_events` → `policy_events`, `patient_artifacts`, `clinician_artifacts`, `lineage_runs`, `benchmark_runs`, `share_events`. Migrations via Alembic.

### API Routes (`backend/app/api/routes/`)

All routes prefixed with `/api`:
- `/api/health` — health check
- `/api/upload` — file upload (PDF/image)
- `/api/jobs` — job status and management
- `/api/artifacts` — retrieve rendered artifacts

### LLM Integration

Uses Qwen models via OpenAI-compatible API (`openai` SDK pointing at `ELFIE_QWEN_BASE_URL`). `qwen-plus` for text explanation, `qwen-vl-max` for vision/OCR in image beta lane. Service in `services/explanation/`.

### Terminology Data (`data/`)

- `data/loinc/` — LOINC terminology files for analyte mapping
- `data/alias_tables/` — lab-specific name aliases
- `data/ucum/` — UCUM unit conversion tables

Import script: `scripts/import_loinc.py`

### Frontend

React 19 + TypeScript + Vite. Components organized by feature: `upload/`, `processing/`, `patient_artifact/`, `history_card/`, `guided_ask/`, `clinician_share/`. i18n support for English and Vietnamese (`src/i18n/`). API client in `src/services/api.ts`.

## Design Docs

- `labs_analyzer_v10_source_of_truth.md` — full blueprint specification (sections referenced throughout code)
- `labs_analyzer_v10_tests_guardrails.md` — test strategy and guardrails
- `labs_analyzer_v10_parallel_distribution_rewritten.md` — parallel processing design
