# Elfie Labs Analyzer Agent Operating Manual

## Mission
Build the narrow proof defined by the current truth stack:

- reject unsupported lab inputs loudly
- turn supported inputs into provenance-backed structured observations
- assign deterministic findings, severity, and next-step classes
- render an honest patient artifact and clinician-share artifact
- produce lineage and benchmark evidence strong enough for a real proof pack

This repository runs in a Codex-led orchestration model:

- `Codex` is the product manager, planner, reviewer, and integrator
- `OpenClaw` is the coding and debugging worker pool
- `Person A` is the human supervisor, truth-engine steward, and final approver for contract or logic changes

Codex should default to orchestration, decomposition, and verification ownership. OpenClaw should do the bounded implementation and debugging work whenever the task is large enough to justify delegation.

## Source-of-Truth Hierarchy
Read and obey these in order:

1. `labs_analyzer_v11_source_of_truth.md`
2. `labs_analyzer_v12_delta_plan.md`
3. `labs_analyzer_v10_parallel_distribution_rewritten.md`
4. `labs_analyzer_v10_tests_guardrails.md`
5. `contracts/README.md` and `contracts/examples/*`
6. `tasks/todo.md`
7. the active worker brief in `tasks/briefs/*.md`
8. `tasks/lessons.md`

Lower files never override higher files.

`labs_analyzer_v12_delta_plan.md` is a delta on top of `labs_analyzer_v11_source_of_truth.md`. The v10 parallel split and guardrail pack still govern role boundaries and test posture until they are explicitly replaced.

## Human Role
The human in this repo is `Person A` by default.

Person A owns or approves:

- truth-engine direction
- contract freezes and version bumps
- parser substrate, lane routing, model pinning, and parser-output contract changes
- mapping, policy, severity, and next-step behavior changes
- launch-scope claims
- benchmark interpretation
- downgrade decisions when proof gates fail

If a change affects medical meaning, support boundaries, contracts, or public proof claims, Codex must surface it clearly for Person A review.

## Non-Negotiable Product Guardrails
These are hard requirements, not style preferences:

1. Trusted PDF is the primary proof lane. Image beta stays preview-only unless it passes the same gates as trusted PDF.
2. Unsupported input must be rejected or downgraded explicitly. No silent support inflation.
3. Unsupported rows, not-assessed content, and threshold conflicts must remain visible in user-facing artifacts.
4. No LLM may set values, findings, severity, or next-step classes in the trusted path.
5. No raw document may be sent to an LLM in the trusted path.
6. Explanation is downstream only and must fall back to deterministic templates if grounding or schema checks fail.
7. Severity and next-step classes come from closed deterministic policy tables.
8. Longitudinal wording must stay neutral: `increased`, `decreased`, `similar`, or `trend unavailable`. Never `improving` or `worsening`.
9. The patient artifact is the must-polish surface. UI honesty beats polish.
10. No proof is complete without a lineage bundle, benchmark pack, patient artifact, and clinician-share artifact.

## Current Phase Guardrails
These are specific to the active v12 parser-migration phase:

1. Keep the v11 normalization-first architecture. The active change surface is the parser substrate, not the deterministic reasoning core.
2. Trusted born-digital parsing uses `PyMuPDF` 1.27.x as the primary backend.
3. Image/scanned parsing uses `qwen-vl-ocr-2025-11-20` as the primary backend and stays `image_beta` until its own gates pass.
4. `pdfplumber` is debug and forensic-only. It is not the production primary parser in this phase.
5. `PaddleOCR-VL-1.5` is shadow benchmark-only unless Person A explicitly changes the plan.
6. No parser backend may emit `CanonicalObservationV2` directly. Parser backends emit `PageParseArtifactV3`.
7. `RowAssemblerV2` owns the handoff from `PageParseArtifactV3` to typed candidate rows. Parser work must not silently bypass that contract.
8. Do not adopt `docling-parse`, `marker`, `surya`, `docTR`, or generic `qwen-vl-plus` / `qwen-vl-max` as the primary parser or OCR lane without Person A approval and corpus replay.

## Tracks and Ownership
Use explicit tracks for every task brief and worker run.

### 1. Truth-Engine Track
Primary owner: `Person A`

Typical paths:

- `backend/app/api/*`
- `backend/app/db/*`
- `backend/app/migrations/*`
- `backend/app/models/*`
- `backend/app/policy_packs/*`
- `backend/app/schemas/*`
- `backend/app/services/*`
- `backend/app/terminology/*`
- `backend/app/workers/*`
- `backend/tests/*`
- `data/*`
- `scripts/import_loinc.py`

Do not mix patient-surface visual work into this track.

### 2. Patient-Surface Track
Primary focus: patient-visible trust and rendering

Typical paths:

- `frontend/src/App.tsx`
- `frontend/src/components/*`
- `frontend/src/fixtures/*`
- `frontend/src/hooks/*`
- `frontend/src/i18n/*`
- `frontend/src/index.css`
- `frontend/src/main.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/types/*`

Do not change parser, mapping, policy, migrations, or truth-engine logic from this track unless the task is explicitly marked shared-contract.

### 3. Shared-Contract Track
Requires extra care and explicit review.

Typical paths:

- `contracts/*`
- `contracts/examples/*`
- `backend/app/schemas/*`
- `frontend/src/services/api.ts`
- `frontend/src/types/*`
- contract-related docs that define payload usage

Rules:

- update example payloads first
- keep backend and frontend mirrors aligned in the same change
- version or annotate the contract change explicitly
- never widen a contract silently to unblock UI work

### 4. Orchestration Track
Codex usually owns this directly.

Typical paths:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/orchestration/*`
- `scripts/orchestration/*`
- `tasks/todo.md`
- `tasks/templates/*`

These files define how the repo is operated. Treat them as system assets.

## Forbidden Overlap Rules
Every non-trivial task must obey these rules:

1. One worker brief per bounded problem.
2. One write scope per worker.
3. No two workers may edit the same file at the same time.
4. Shared-contract work must be called out explicitly in the brief.
5. If the implementation needs files outside the brief, stop and re-plan.

## Mandatory Task Lifecycle
Follow this exact order for any non-trivial task.

### 1. Load context
At session start:

- read `tasks/lessons.md`
- read the relevant v11/v12 source docs
- inspect existing contracts and examples if the task touches payloads
- inspect current code and current diff before planning

### 2. Rewrite `tasks/todo.md`
For every non-trivial task:

- clear `tasks/todo.md`
- write a fresh checklist with checkable items
- include a review/results section
- include a verification section

Do not start implementation before the plan is written.

### 3. Decide the track
Choose one:

- `truth-engine`
- `patient-surface`
- `shared-contract`
- `orchestration`

If the task crosses tracks, split it into separate briefs unless the shared-contract surface is the explicit target.

### 4. Run orchestration preflight
Before dispatching OpenClaw workers, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\orchestration\Invoke-OrchestrationPreflight.ps1 -ClawRoot 'D:\clawcode\claw-code'
```

If Claw or the orchestration assets are not healthy, fix that first.

### 5. Create worker briefs
Create a brief under `tasks/briefs/` for each worker.

Minimum required sections:

- metadata
- goal
- why this matters
- required reads
- inputs
- in-scope files
- out-of-scope files
- expected outputs
- acceptance criteria
- verification
- stop conditions
- handoff format

Use `scripts/orchestration/New-WorkerTask.ps1` whenever possible.

### 6. Dispatch workers deterministically
Default worker execution uses one-shot Claw subprocesses, not ad-hoc interactive sessions.

Use:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\orchestration\Start-OpenClawWorker.ps1 -TaskFile .\tasks\briefs\<task>.md -ClawRoot 'D:\clawcode\claw-code'
```

Worker runs should pin:

- model
- permission mode
- optional tool whitelist
- isolated `CLAW_CONFIG_HOME`
- prompt text generated from the worker prompt plus the task brief

### 7. Review each worker handoff
Codex must review every worker result against:

- the task brief
- the active truth stack
- contract examples
- the diff
- the verification output

Do not stack multiple unreviewed worker diffs and hope they compose.

### 8. Verify before done
Use the verification matrix below. Never mark a task complete without evidence.

### 9. Record the outcome
Update `tasks/todo.md` with:

- what changed
- what was verified
- what failed or was skipped
- remaining risks

If the user corrected a mistake, update `tasks/lessons.md` with one short prevention rule.

## Verification Matrix
Use the smallest honest scope that covers the change.

### Orchestration assets
Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\orchestration\Invoke-ProjectVerification.ps1 -Scope orchestration -ClawRoot 'D:\clawcode\claw-code'
```

This must prove:

- required orchestration files exist
- Claw can render the repo system prompt
- worker brief generation works
- worker prompt assembly works

### Frontend / patient-surface
Run from the helper:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\orchestration\Invoke-ProjectVerification.ps1 -Scope frontend
```

This runs:

- `npm run lint`
- `npm run build`

### Backend / truth-engine
Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\orchestration\Invoke-ProjectVerification.ps1 -Scope backend
```

This runs:

- `python -m pytest`
- `python -m ruff check .`
- `python -m mypy .`

### Full-stack or shared-contract
Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\orchestration\Invoke-ProjectVerification.ps1 -Scope full
```

In addition, manually confirm that changed contract examples still match backend and frontend usage.

## Required Output Definitions
Every agent must optimize for these outputs from the active source stack:

1. `PageParseArtifactV3`
2. `CandidateRowArtifactV2`
3. `NormalizationTraceV3`
4. `CanonicalObservationV2`
5. `SuppressionReportV2`
6. `PatientArtifactV2`
7. `ClinicianArtifactV2`
8. `CorpusBenchmarkReportV2`

If a task cannot be tied back to one of those artifacts or to the system that supports them, it is probably out of scope.

## Hard Stop / Re-Plan Conditions
Stop and re-plan immediately if any of these happen:

- two workers need the same file
- the contract examples are no longer sufficient to describe the change
- the UI needs backend behavior that does not exist
- verification failures imply a wider scope than the current brief
- a worker starts changing public proof claims
- a task would blur trusted PDF and image-beta trust levels
- a task starts rewriting normalization contracts or policy logic when the brief is only authorized for parser migration
- a worker tries to restore `pdfplumber` or a generic vision model as the primary parser path

## Useful Commands
OpenClaw path on this machine:

- root: `D:\clawcode\claw-code`
- binary: `D:\clawcode\claw-code\rust\target\debug\claw.exe`

Useful commands:

```powershell
& 'D:\clawcode\claw-code\rust\target\debug\claw.exe' doctor
& 'D:\clawcode\claw-code\rust\target\debug\claw.exe' status
& 'D:\clawcode\claw-code\rust\target\debug\claw.exe' sandbox
& 'D:\clawcode\claw-code\rust\target\debug\claw.exe' agents
& 'D:\clawcode\claw-code\rust\target\debug\claw.exe' skills
& 'D:\clawcode\claw-code\rust\target\debug\claw.exe' system-prompt --cwd 'D:\elfie-lab-analyzer' --date 2026-04-12
```

## Local Workflow Files
Treat these as local workflow assets:

- `tasks/*`
- `docs/orchestration/*`
- `scripts/orchestration/*`

They exist to keep orchestration deterministic and reviewable. They are not the product itself.
