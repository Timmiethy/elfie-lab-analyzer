# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Elfie Labs Analyzer is a full-stack lab report understanding system that processes PDF/image lab reports, extracts structured observations, maps analytes to LOINC concepts, evaluates clinical rules, and generates both patient-friendly and clinician-shareable artifacts.

## What This Project Does

Elfie Labs Analyzer is an end-to-end pipeline for:
1. Ingestion - Accept PDF/image uploads of lab reports
2. Extraction - Parse documents and extract observations using OCR (Mineru + optional VLM)
3. Normalization - Normalize analytes and resolve to LOINC terminology
4. Enrichment - Validate units (UCUM), reconstruct panels, evaluate rules
5. Output - Generate patient-friendly and clinician artifacts with lineage/provenance

Stack:
- Backend: Python FastAPI + async SQLAlchemy + PostgreSQL
- Frontend: React 19 + TypeScript + Vite
- Data: LOINC snapshots, alias tables, UCUM mappings, policy packs

---

## Architecture

### Pipeline Stages (Intentional Separation)
See backend/app/workers/pipeline.py:

1. EXTRACTION (InputGateway classifies + Mineru/OCR)
2. OBSERVATION_BUILD (ObservationBuilder normalizes)
3. ANALYTE_MAPPING (AnalyteResolver -> LOINC)
4. UCUM_CONVERSION (UcumEngine validates units)
5. PANEL_RECONSTRUCTION (PanelReconstructor)
6. RULE_EVALUATION (RuleEngine)
7. SEVERITY_ASSIGNMENT (SeverityPolicyEngine)
8. NEXTSTEP_ASSIGNMENT (NextStepPolicyEngine)
9. PATIENT_ARTIFACT (ArtifactRenderer)
10. CLINICIAN_ARTIFACT (ArtifactRenderer)
11. LINEAGE_PERSIST (LineageLogger)

Key Pattern: Do not skip/flatten stages. Each output feeds the next and is independently testable.

### Directory Structure

backend/
  app/
    api/routes/ - upload, jobs, artifacts, health endpoints
    services/ - pipeline modules (resolver, renderer, etc.)
    workers/pipeline.py - PipelineOrchestrator
    models/tables.py - SQLAlchemy ORM
    schemas/ - Pydantic validation
  tests/ - unit/ and integration/ test suites

frontend/
  src/ - React components, API client, types

data/ - LOINC, UCUM, alias tables
artifacts/ - Generated outputs
contracts/ - API examples

---

## Commands

### Backend (Python)

cd backend

Install:
pip install -e ".[dev]"              # Standard
pip install -e ".[dev,image-beta]"   # With OCR

Run:
uvicorn app.main:app --reload        # Port 8000

Tests:
pytest                               # All tests
pytest tests/unit/ -xvs              # Unit only
pytest tests/unit/test_analyte_resolver_strict_alias.py::test_name -xvs

Lint/Format:
ruff check .      # Lint
ruff format .     # Format
mypy .            # Type check (strict)

Database:
alembic upgrade head     # Run migrations
alembic downgrade -1     # Revert one

### Frontend (TypeScript)

cd frontend

npm install       # Install
npm run dev       # Dev server (port 5173)
npm run build     # Production build
npm run lint      # ESLint

### Docker

docker compose up         # Start Postgres + services

### Full-Stack Validation (Windows)

powershell -NoProfile -ExecutionPolicy Bypass -File scripts/validation/run_full_stack_validation.ps1 --max-files 1 --tiers easy

---

## Running a Single Test

cd backend
pytest tests/unit/test_analyte_resolver_strict_alias.py::test_strict_matching -xvs

Flags: -x (stop first fail), -v (verbose), -s (show prints), -k "pattern"

---

## Environment

cp .env.example .env

Key variables (all prefixed ELFIE_):
- DATABASE_URL - PostgreSQL async URL
- QWEN_API_KEY - VLM API key (optional)
- IMAGE_BETA_ENABLED - Enable VLM lane (default: false)
- CORS_ORIGINS - Allowed origins (default: localhost:5173)
- MAX_UPLOAD_SIZE_MB - Upload limit (default: 20)

See backend/app/config.py for full settings list.

---

## Testing

Unit tests (tests/unit/):
- Mock all external deps (DB, VLM, Qwen)
- Fast and isolated
- Examples: test_analyte_resolver_strict_alias.py, test_contract_examples*.py

Integration tests (tests/integration/):
- Real DB, full async pipeline
- Examples: test_phase_12_api_flow.py, test_phase_14_operational_runtime.py

Fixtures (tests/conftest.py):
- mock_vlm_for_pipeline - Auto-mocks VLM for all tests
- async_session_factory - DB session
- async_client - FastAPI test client

---

## API

All routes return JSON. See backend/app/api/routes/:

POST /api/upload
  Form: file (PDF/PNG/JPG), age_years?, sex?
  Response: { job_id, lane, status }

GET /api/jobs/{job_id}
  Response: { id, status, message }

GET /api/artifacts/{job_id}/patient
  Response: PatientArtifact with findings and explanations

GET /api/artifacts/{job_id}/clinician
  Response: ClinicianArtifact with full clinical data

GET /api/health
  Response: { status: "healthy" }

---

## Domain Concepts

- Observation - Single extracted analyte-value-unit triplet
- Analyte - Measured quantity (Glucose, HbA1c, etc.)
- LOINC - Standard terminology codes for lab tests
- Panel - Group of related analytes (CMP, CBC, etc.)
- Artifact - Generated patient or clinician report
- Lineage - Provenance: how each finding was derived
- Severity - Clinical assessment (normal, low, moderate, high, critical)

---

## Common Workflows

### Adding a Service

1. Create backend/app/services/<name>/__init__.py
2. Implement with Pydantic schemas for I/O types
3. Add unit tests in backend/tests/unit/
4. Integrate into PipelineOrchestrator in pipeline.py
5. Update API schemas in backend/app/schemas/

### Modifying API Contract

1. Update Pydantic schema in backend/app/schemas/
2. Update route in backend/app/api/routes/
3. Sync frontend src/services/api.ts
4. Document breaking changes in contracts/

### Adding a Rule

1. Define logic in backend/app/services/rule_engine.py
2. Add YAML/JSON definition to backend/policy_tables/ if needed
3. Test with pytest tests/unit/test_rule_engine.py
4. Integrate into pipeline

---

## Persistence

- ORM: backend/app/models/tables.py (SQLAlchemy)
- Migrations: backend/app/migrations/versions/ (Alembic)
- Store: backend/app/db/store.py (TopLevelLifecycleStore)

cd backend
alembic upgrade head      # Apply pending
alembic current           # Show current version

---

## Observability

- Correlation IDs: X-Correlation-ID header (auto-generated or passed)
- Logging: backend/app/services/observability.py
- Metrics: backend/app/services/benchmark.py

---

## Guidelines

Do:
- Keep pipeline stages isolated and independently testable
- Use type hints everywhere (mypy --strict)
- Write tests near the behavior they validate
- Preserve stage boundaries in orchestration
- Sync backend and frontend API changes

Don't:
- Skip or flatten pipeline stages
- Commit secrets, real patient data, or generated artifacts
- Use non-async code in hot paths
- Bypass Pydantic validation
- Hard-code paths (use settings from config.py)

---

## Troubleshooting

Postgres connection issues:
  docker ps | grep postgres
  echo $ELFIE_DATABASE_URL
  psql "postgresql://elfie:elfie@localhost:5432/elfie_labs"

VLM / Image Beta issues:
  Set ELFIE_IMAGE_BETA_ENABLED=true
  Provide ELFIE_QWEN_API_KEY
  Check mock in tests/conftest.py

Frontend API errors:
  Frontend API client: frontend/src/services/api.ts
  Check backend /api/health
  Verify CORS settings in .env

Test failures:
  Run with -xvs for details
  Check conftest mocks
  Verify alembic current
  Look for correlation ID in logs

---

## References

- Design docs: docs/, labs_analyzer_v10_*.md
- Contracts: contracts/examples/, contracts/README.md
- Architecture decisions: AGENTS.md, GEMINI.md, PLAN.md
- Config: backend/pyproject.toml, frontend/package.json

---

Last updated: 2026-04-17
