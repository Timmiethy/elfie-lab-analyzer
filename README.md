# Elfie Labs Analyzer

![Python 3.11](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)
![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-336791?logo=postgresql&logoColor=white)
![License MIT](https://img.shields.io/badge/License-MIT-green)

**Elfie Labs Analyzer** is an open-source, full-stack lab report understanding system. Upload a PDF or image of a lab report and get back structured clinical findings — mapped to LOINC codes, evaluated against clinical rules, with both patient-friendly and clinician-ready artifacts.

---

## Features

- **Universal ingestion** — PDF, PNG, and JPG lab reports
- **OCR + VLM extraction** — Mineru-based OCR with optional vision-language model lane
- **LOINC mapping** — Analyte resolver with alias tables and fuzzy normalization
- **UCUM unit validation** — Strict unit normalization against the UCUM standard
- **Panel reconstruction** — Groups related analytes into standard panels (CMP, CBC, etc.)
- **Clinical rule evaluation** — Configurable rule engine with policy packs
- **Severity + next-step assignment** — Per-finding severity classes and recommended actions
- **Dual artifacts** — Separate patient-friendly and clinician-detail outputs
- **Full lineage/provenance** — Every finding traces back to its source extraction

---

## Architecture

### 11-Stage Pipeline

Each stage is isolated and independently testable. Outputs feed the next stage only.

```
┌─────────────────────────────────────────────────────────────┐
│                      Lab Report Upload                       │
└──────────────────────────────┬──────────────────────────────┘
                               │
       ┌───────────────────────▼────────────────────────┐
  [1]  │  EXTRACTION          InputGateway + Mineru/OCR  │
       └───────────────────────┬────────────────────────┘
       ┌───────────────────────▼────────────────────────┐
  [2]  │  OBSERVATION_BUILD   ObservationBuilder         │
       └───────────────────────┬────────────────────────┘
       ┌───────────────────────▼────────────────────────┐
  [3]  │  ANALYTE_MAPPING     AnalyteResolver → LOINC    │
       └───────────────────────┬────────────────────────┘
       ┌───────────────────────▼────────────────────────┐
  [4]  │  UCUM_CONVERSION     UcumEngine unit validation │
       └───────────────────────┬────────────────────────┘
       ┌───────────────────────▼────────────────────────┐
  [5]  │  PANEL_RECONSTRUCTION PanelReconstructor        │
       └───────────────────────┬────────────────────────┘
       ┌───────────────────────▼────────────────────────┐
  [6]  │  RULE_EVALUATION     RuleEngine                 │
       └───────────────────────┬────────────────────────┘
       ┌───────────────────────▼────────────────────────┐
  [7]  │  SEVERITY_ASSIGNMENT SeverityPolicyEngine       │
       └───────────────────────┬────────────────────────┘
       ┌───────────────────────▼────────────────────────┐
  [8]  │  NEXTSTEP_ASSIGNMENT NextStepPolicyEngine       │
       └───────────────────────┬────────────────────────┘
       ┌───────────────────────▼────────────────────────┐
  [9]  │  PATIENT_ARTIFACT    ArtifactRenderer           │
       └───────────────────────┬────────────────────────┘
       ┌───────────────────────▼────────────────────────┐
 [10]  │  CLINICIAN_ARTIFACT  ArtifactRenderer           │
       └───────────────────────┬────────────────────────┘
       ┌───────────────────────▼────────────────────────┐
 [11]  │  LINEAGE_PERSIST     LineageLogger              │
       └────────────────────────────────────────────────┘
```

---

## Prerequisites

- **Python 3.11**
- **Node.js** (LTS recommended) + **npm**
- **PostgreSQL 15+** (or Docker)

---

## Quick Start

### 1. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` to set at minimum `ELFIE_DATABASE_URL`. See [Environment Variables](#environment-variables) below.

### 2. Start PostgreSQL

**Via Docker Compose (recommended):**

```bash
docker compose up
```

**Or** point `ELFIE_DATABASE_URL` at an existing Postgres instance.

### 3. Run the Backend

```bash
cd backend
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

Backend runs at `http://localhost:8000`.

> **Image/VLM lane:** install with `pip install -e ".[dev,image-beta]"` and set `ELFIE_IMAGE_BETA_ENABLED=true`.

### 4. Run the Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5173`.

---

## Development

### Backend

```bash
cd backend

# Tests
pytest                          # All tests
pytest tests/unit/ -xvs         # Unit tests, fail-fast + verbose
pytest tests/integration/       # Integration tests (requires live DB)

# A single test
pytest tests/unit/test_analyte_resolver_strict_alias.py::test_strict_matching -xvs

# Lint & format
ruff check .
ruff format .

# Type check
mypy .

# Database migrations
alembic upgrade head            # Apply pending migrations
alembic current                 # Show current revision
alembic downgrade -1            # Revert one migration
```

### Frontend

```bash
cd frontend

npm run lint      # ESLint
npm run build     # Production build
npm run preview   # Preview production build
```

### Full-Stack Validation (Windows)

Run the full pipeline against sample lab files with strict readiness checks:

```powershell
# Smoke test — one file, easy tier
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/validation/run_full_stack_validation.ps1 --max-files 1 --tiers easy

# Full corpus
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/validation/run_full_stack_validation.ps1 --fail-fast --tiers easy medium
```

---

## API Reference

All endpoints return JSON. See `contracts/` for full schema examples.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/upload` | Upload a lab report (PDF/PNG/JPG). Form fields: `file`, `age_years?`, `sex?`. Returns `{ job_id, lane, status }`. |
| `GET` | `/api/jobs/{job_id}` | Poll job status. Returns `{ id, status, message }`. |
| `GET` | `/api/artifacts/{job_id}/patient` | Patient-friendly artifact with findings and plain-language explanations. |
| `GET` | `/api/artifacts/{job_id}/clinician` | Clinician artifact with full clinical data, severity, and next steps. |
| `GET` | `/api/health` | Health check. Returns `{ status: "healthy" }`. |

---

## Environment Variables

All variables use the `ELFIE_` prefix. See `backend/app/config.py` for the full list.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ELFIE_DATABASE_URL` | ✅ | — | Async PostgreSQL URL (`postgresql+asyncpg://...`) |
| `ELFIE_CORS_ORIGINS` | — | `http://localhost:5173` | Comma-separated allowed CORS origins |
| `ELFIE_IMAGE_BETA_ENABLED` | — | `false` | Enable VLM image processing lane |
| `ELFIE_QWEN_API_KEY` | — | — | API key for VLM lane (required if image beta enabled) |
| `ELFIE_MAX_UPLOAD_SIZE_MB` | — | `20` | Maximum upload file size in MB |

> ⚠️ Never commit secrets, real patient data, or generated artifacts.

---

## Project Structure

```
elfie-lab-analyzer/
├── backend/
│   ├── app/
│   │   ├── api/routes/         # API endpoints (upload, jobs, artifacts, health)
│   │   ├── services/           # Pipeline services (resolver, renderer, rules, etc.)
│   │   ├── workers/
│   │   │   └── pipeline.py     # PipelineOrchestrator — main entrypoint
│   │   ├── models/tables.py    # SQLAlchemy ORM models
│   │   ├── schemas/            # Pydantic request/response schemas
│   │   ├── migrations/         # Alembic migration versions
│   │   └── config.py           # Environment-driven configuration
│   ├── tests/
│   │   ├── unit/               # Fast isolated tests
│   │   └── integration/        # Full async pipeline tests
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── components/         # React feature components
│   │   └── services/api.ts     # Typed API client
│   └── package.json
├── data/
│   ├── loinc/                  # LOINC mapping snapshots
│   ├── alias_tables/           # Analyte alias/synonym tables
│   └── ucum/                   # UCUM unit definitions
├── artifacts/                  # Generated report outputs (gitignored)
├── contracts/                  # API contract examples and docs
├── scripts/                    # Validation and utility scripts
├── docs/                       # Design and reference documentation
└── docker-compose.yml
```

---

## Contributing

Contributions are welcome! A few guidelines:

1. **Preserve pipeline boundaries** — each stage in `pipeline.py` is intentionally isolated. Avoid merging stages.
2. **Type hints everywhere** — the backend is checked with `mypy --strict`.
3. **Tests near behavior** — add or update unit tests in `tests/unit/` for any service changes.
4. **Sync API contracts** — if you change backend schemas or routes, update `frontend/src/services/api.ts` and `contracts/` accordingly.
5. **No secrets or patient data** — never commit `.env` files, API keys, or real lab data.

```bash
# Before submitting a PR
cd backend && ruff check . && ruff format . && mypy . && pytest tests/unit/
cd frontend && npm run lint && npm run build
```

---

## License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.
