# Elfie Labs Analyzer

Elfie Labs Analyzer is a full-stack lab report understanding system. It accepts PDF/image lab reports, extracts structured observations, maps analytes to LOINC concepts, runs clinical rule evaluation, and produces both patient-friendly and clinician-share artifacts.

## What This Repository Contains

- **Backend (`backend/`)**: FastAPI service + async SQLAlchemy + Alembic migrations + analysis pipeline orchestration.
- **Frontend (`frontend/`)**: Vite + React + TypeScript web app.
- **Terminology and mapping data (`data/`)**: LOINC and related mapping inputs.
- **Generated artifacts (`artifacts/`)**: Output files created by analysis jobs.
- **Docs and design references (`docs/`, `labs_analyzer_v10_*.md`)**: Product and architecture guidance.

## Core Pipeline (High Level)

1. Parse/OCR the uploaded document.
2. Normalize extracted observations.
3. Resolve analytes to terminology targets.
4. Evaluate rules/severity and next-step policies.
5. Generate explanation + lineage/provenance.
6. Render patient and clinician artifacts.

This stage separation is intentional and should be preserved unless a change explicitly reshapes architecture.

## Prerequisites

- Python **3.11**
- Node.js (LTS recommended)
- npm
- PostgreSQL (unless using Docker Compose setup)

## Quick Start

### 1) Configure Environment

From repo root:

```bash
cp .env.example .env
```

All runtime settings use the `ELFIE_` prefix (see `backend/app/config.py`).

### 2) Start Dependencies (Optional Docker Path)

From repo root:

```bash
docker compose up
```

This starts Postgres and backend services with mounted `data/` and `artifacts/`.

### 3) Run Backend Locally

```bash
cd backend
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Backend default URL: `http://localhost:8000`

If working with image-beta OCR lane:

```bash
pip install -e ".[dev,image-beta]"
```

### 4) Run Frontend Locally

```bash
cd frontend
npm install
npm run dev
```

Frontend default URL: `http://localhost:5173`

## Development Commands

### Backend (`backend/`)

```bash
pytest
pytest tests/unit/
pytest tests/integration/
ruff check .
ruff format .
mypy .
alembic upgrade head
```

### Frontend (`frontend/`)

```bash
npm run lint
npm run build
npm run preview
```

## Repository Layout

```text
backend/
  app/
    api/routes/         # /api routes (health, upload, jobs, artifacts)
    services/           # parsing, OCR, mapping, rules, rendering, lineage
    workers/pipeline.py # orchestration entrypoint
  tests/
frontend/
  src/components/       # feature-oriented UI components
  src/services/api.ts   # frontend API client
data/                   # terminology inputs
artifacts/              # generated outputs
docs/                   # design and reference docs
scripts/                # local helper scripts
contracts/              # contract examples and freeze docs
```

## Environment Variables (Common)

- `ELFIE_DATABASE_URL`
- `ELFIE_DATABASE_URL_SYNC`
- `ELFIE_QWEN_API_KEY`
- `ELFIE_QWEN_BASE_URL`
- `ELFIE_QWEN_MODEL`
- `ELFIE_QWEN_VL_MODEL`
- `ELFIE_IMAGE_BETA_ENABLED`

Do not commit secrets, real patient data, or generated sensitive artifacts.

## API/Contract Notes

If you change API contracts, keep backend schemas/routes and frontend `src/services/api.ts` in sync.

Contract examples are available in `contracts/examples/` and companion notes in `contracts/README.md`.

## Contribution Guidance

- Keep changes minimal and scoped.
- Preserve pipeline boundaries where possible.
- Add/update tests near impacted backend behavior.
- Use existing naming conventions tied to lab domain concepts (`observation`, `artifact`, `lineage`, etc.).

---

If you're making larger architectural/product changes, review the design references in `docs/` and `labs_analyzer_v10_*.md` before implementation.
