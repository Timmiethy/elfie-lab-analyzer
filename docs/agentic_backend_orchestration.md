# Agentic Backend Orchestration Runbook

This guide defines start-to-end operation for **Copilot orchestrator + Gemini CLI worker** workflows in this repository.

## 1. Scope and Operating Model
- Copilot owns planning, decomposition, packet generation, gating, and synthesis.
- Gemini CLI executes implementation/debugging for one packet at a time.
- Human supervisor approves policy-impacting merges.
- Backend is primary scope; frontend is out of scope unless explicitly requested.

## 2. Prerequisites
- Python 3.11
- Node.js LTS + npm
- PostgreSQL 16+ or Docker Compose
- Gemini CLI installed and authenticated
- Repository cloned locally

Install Gemini CLI (stable):

```bash
npm install -g @google/gemini-cli@latest
gemini --version
```

Project runtime env (Qwen via Alibaba Cloud) comes from `.env` and `backend/app/config.py`.

## 3. One-Time Project Setup
1. Copy environment:

```bash
cp .env.example .env
```

2. Install backend dependencies:

```bash
cd backend
pip install -e ".[dev]"
```

3. Ensure terminology metadata exists (required at app boot):

```bash
mkdir -p ../data/loinc
cat > ../data/loinc/metadata.json <<'JSON'
{
  "release": "local-dev",
  "checksum": "sha256:local"
}
JSON
```

4. Verify backend quality gates manually:

```bash
ruff check .
mypy .
pytest tests/unit/ -q
pytest tests/integration/ -q
```

## 4. Repository Orchestration Files
- `AGENTS.md`: source-of-truth orchestrator protocol
- `GEMINI.md`: worker-specific execution contract
- `.gemini/settings.json`: project-level Gemini controls
- `.gemini/system.md`: optional system override instructions
- `scripts/agent_ops/schemas/*.json`: task/result contracts
- `scripts/agent_ops/templates/*.json|*.md`: packet/prompt templates
- `scripts/agent_ops/*.py|*.ps1`: dispatch/validate/merge tools

## 5. Task Packet Lifecycle
### 5.1 Create a task packet
Start from:
- `scripts/agent_ops/templates/task_packet.template.json`

Set at minimum:
- `task_id`
- `objective`
- `allowed_paths`
- `forbidden_paths`
- `required_commands`
- `required_tests`
- `completion_definition`
- token/tool budgets

### 5.2 Dispatch packet to worker
PowerShell (Windows-first):

```powershell
pwsh ./scripts/agent_ops/dispatch_worker.ps1 `
  -TaskPacket ./artifacts/proof_packs/task.packet.json `
  -Output ./artifacts/proof_packs/task.result.json `
  -ApprovalMode auto_edit `
  -MaxRepairAttempts 2 `
  -LocalCheckTimeoutSeconds 900
```

The dispatcher uses stdin-based prompt transport to avoid shell escaping and command-line length issues on Windows.
By default, dispatcher executes packet `required_commands` and `required_tests` locally after worker response normalization, so merge gates do not depend on worker-side shell tool availability.

Recommended optional flag for robustness:

```bash
python scripts/agent_ops/dispatch_worker.py \
  --task-packet ./artifacts/proof_packs/task.packet.json \
  --output ./artifacts/proof_packs/task.result.json \
  --max-repair-attempts 2
```

Optional flag (diagnostics only):

```bash
python scripts/agent_ops/dispatch_worker.py \
  --task-packet ./artifacts/proof_packs/task.packet.json \
  --output ./artifacts/proof_packs/task.result.json \
  --skip-local-required-checks
```

If Gemini returns non-JSON prose, dispatcher retry logic issues a repair prompt and attempts to recover a schema-valid worker result.

Python direct:

```bash
python scripts/agent_ops/dispatch_worker.py \
  --task-packet ./artifacts/proof_packs/task.packet.json \
  --output ./artifacts/proof_packs/task.result.json
```

### 5.3 Validate worker result

```bash
python scripts/agent_ops/validate_worker_result.py \
  --result ./artifacts/proof_packs/task.result.json \
  --task-packet ./artifacts/proof_packs/task.packet.json
```

Validator defaults to fail-closed for non-completed statuses. For intentional inspection of blocked/failed artifacts:

```bash
python scripts/agent_ops/validate_worker_result.py \
  --result ./artifacts/proof_packs/task.result.json \
  --task-packet ./artifacts/proof_packs/task.packet.json \
  --allow-noncompleted
```

Validation checks:
- schema version and required fields
- status enum
- scope compliance (`changed_files` within `allowed_paths`)
- required command/test evidence for completed tasks

### 5.4 Merge multiple worker results

```bash
python scripts/agent_ops/merge_worker_results.py \
  --wave-id wave-a \
  --results ./artifacts/proof_packs/task-a.result.json ./artifacts/proof_packs/task-b.result.json \
  --output ./artifacts/proof_packs/wave-a.merge.json
```

## 6. Deterministic Gate Matrix
A task can be marked done only when all pass:
1. Scope gate: no file changes outside packet scope.
2. Evidence gate: commands and tests executed with explicit outputs.
3. Quality gate: `ruff`, `mypy`, relevant pytest suites pass.
4. Contract gate: contract example tests still pass.
5. Supervisor gate: unresolved risks acknowledged or accepted.

## 7. Recommended Backend Wave Decomposition
### Wave A: Extraction lane hardening
- Focus: `backend/app/workers/pipeline.py`, extraction adapters, lane semantics.
- Keep trust-state behavior and abstention visibility intact.

### Wave B: Normalization hardening
- Focus: analyte resolver and UCUM conversion behavior.
- Preserve deterministic mapping and no-guess normalization rules.

### Wave C: Policy + artifact consistency
- Focus: rule engine, severity policy, next-step policy, renderer behavior.
- Ensure no model improvisation in severity/next-step logic.

### Wave D: lineage + proofs + observability
- Focus: lineage payload fields, proof packs, telemetry.
- Ensure auditability for every interpreted finding.

## 8. CI Policy
Backend pull requests must pass:
- `.github/workflows/backend-ci.yml`
- ruff
- mypy
- unit tests
- integration tests

No merge if CI fails.

## 9. Common Failure Modes and Corrective Actions
1. Worker returns prose instead of JSON:
- tighten prompt template
- rerun packet
- mark as blocked if repeated

2. Required tests missing in result:
- run validator (fails closed)
- reject task completion

3. Scope violation in changed files:
- reject result
- split packet by file ownership

4. Terminology bootstrap failure:
- create/fix `data/loinc/metadata.json`
- rerun tests

5. Missing task packet file:
- ensure the packet path exists before dispatch
- start from `scripts/agent_ops/templates/task_packet.template.json`

## 10. Minimal Daily Operator Flow
1. Create/update packet.
2. Dispatch worker.
3. Validate result.
4. Run backend gates.
5. Aggregate wave results.
6. Supervisor review.
7. Merge.

## 11. Corpus and Qwen Validation Execution
Use these scripts to run strict validation on real PDFs and provider connectivity.

1. Build corpus manifest (39 files expected):

```bash
python scripts/validation/build_pdf_manifest.py
```

2. Backend API smoke run (few files):

```bash
python scripts/validation/run_backend_corpus_validation.py \
  --base-url http://127.0.0.1:8000 \
  --manifest artifacts/validation/pdf_manifest.json \
  --tiers easy \
  --max-files 3
```

3. Backend full corpus run:

```bash
python scripts/validation/run_backend_corpus_validation.py \
  --base-url http://127.0.0.1:8000 \
  --manifest artifacts/validation/pdf_manifest.json
```

4. Strict mode (fail non-200 uploads and warnings):

```bash
python scripts/validation/run_backend_corpus_validation.py \
  --base-url http://127.0.0.1:8000 \
  --manifest artifacts/validation/pdf_manifest.json \
  --strict-upload-status \
  --fail-on-warning
```

5. Target one PDF for quick triage:

```bash
python scripts/validation/run_backend_corpus_validation.py \
  --base-url http://127.0.0.1:8000 \
  --manifest artifacts/validation/pdf_manifest.json \
  --tiers hard \
  --files hard/var_singapore_mr_password_protected.pdf
```

6. Qwen diagnostics:

```bash
python scripts/validation/check_qwen_api.py
```

Notes:
- The VLM diagnostic probe image must have width and height greater than 10 pixels. Using 1x1 payloads will fail with `invalid_parameter_error` even when auth and endpoint are healthy.
- Runtime image-beta policy for this repo is one image per VLM call, even though provider APIs may support multi-image requests.

7. Qwen diagnostics without vision call:

```bash
python scripts/validation/check_qwen_api.py --skip-vlm
```

Reports are written to `artifacts/validation/`.
