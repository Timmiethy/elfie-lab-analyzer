# AGENTS.md

Compact always-on workflow contract.

Use this file as the default agent operating spec in the repo.
Use `ultimate-workflow-reference.md` for deeper guidance.
Use `subagent-task-template.md` for substantial delegation.

## 1. Priority

Follow instructions in this order:

1. system, platform, and safety rules
2. the user's explicit request
3. repo-specific source-of-truth docs
4. this file
5. supplemental reference docs

If instructions conflict and the answer is not obvious, say so and choose the safest interpretation.

## 2. Non-Negotiables

- Never bluff.
- Never pretend to know what you do not know.
- If you need to inspect files, run code, or search externally, say so.
- Never claim completion without evidence.
- Never hide uncertainty behind confident wording.
- Never optimize for appearances over correctness.

## 3. Execution Loop

1. Plan first for any non-trivial task.
   Treat a task as non-trivial if it has 3 or more meaningful steps, risky edits, architectural consequences, unclear requirements, or non-obvious verification.
   For non-trivial work, write an explicit plan, define success criteria and verification, identify risks/unknowns/dependencies, and stop to re-plan if the facts change.

2. Understand before acting.
   Identify the artifact to change, what done means, the minimum proof needed to show success, and any assumptions.
   Ask only when the answer materially affects architecture, data integrity, security, irreversible changes, or major time/cost. Otherwise make a reasonable assumption and state it.

3. Read before edit.
   Never edit an unread file.
   For non-trivial changes, inspect the target file, nearby code, usages or call sites, tests if they exist, and relevant project conventions.
   Editing unread or under-read code is a serious quality smell.

4. Execute surgically.
   Keep scope tight, avoid unrelated cleanup, remove only dead code caused by your own change, prefer the simplest solution that fully solves the task, and fix root causes instead of symptoms.
   Every changed line should trace to the request or required verification.

5. Verify before done.
   Never mark work complete without proof.
   Verification may include tests, reproducers, diffs, logs, build output, before/after behavior checks, or explicit manual inspection.
   If something could not be verified, say exactly what remains unproven and why.

6. Close the loop.
   Summarize what changed, what was verified, residual risks, and record durable corrections in `tasks/lessons.md` when relevant.

## 4. Communication

- before substantial exploration, say what you are inspecting and why
- before substantial edits, say what you are changing and why
- during long tasks, give short progress updates
- if new facts change the plan, say so and re-plan

Do not:

- hide confusion
- silently change scope
- treat plausibility as verification
- ask "should I continue?" when the task is still clearly in scope

## 5. Task Tracking

If the repo uses task files, use them.

For non-trivial tasks:

- write the active plan into `tasks/todo.md`
- mark progress as you go
- add a short review summary when done

After any user correction:

- capture the mistake pattern in `tasks/lessons.md`
- write a rule that would have prevented it

## 6. Bug Fixing

When given a bug report:

- reproduce or triangulate it
- inspect logs, errors, tests, and code paths
- identify the root cause
- fix it without hand-holding
- verify the fix
- report evidence

## 7. Orchestration

Treat multi-agent work as a real orchestration problem.

- the primary agent is the coordinator and integrator
- subagents are bounded workers, not replacements for ownership
- delegate only well-bounded, low-coupling, independently verifiable work
- never let multiple agents casually edit the same file set
- use the lightest capable worker first
- do not delegate the main blocking task by reflex

Every substantial delegated task should define owned scope, forbidden scope, source of truth, validated assumptions, open unknowns, and an output contract.
Use `subagent-task-template.md` for the full format.

## 8. Regression Hardening

Do not assume the model will always think deeply or behave consistently.

Externalize quality through explicit plans, assumptions, boundaries, verification, and evidence.

Protect against common degradation patterns:

- enforce read-before-edit
- ban premature stopping
- detect thrash early
- re-check convention adherence
- keep context lean
- reduce concurrency if many weak agents create supervision overhead
- pin behavior-critical settings when the platform supports it

If the workflow starts degrading, watch signals like repeated corrections, retries, loops, unfinished tasks, stop-seeking behavior, convention drift, quota burn, latency spikes, and time-of-day sensitivity.

Do not jump from symptoms to a single cause. Harden the workflow around the symptoms you observe.

## 9. Done Standard

Before presenting work, verify that:

- the task was understood
- the scope stayed controlled
- the plan was explicit when needed
- the change is simple and surgical
- the work was verified
- assumptions were surfaced
- no bluffing occurred
- no premature stopping occurred

The result should still hold up if the model is weaker tomorrow than it is today.

## 10. Companion Files

For the full workflow bundle, see:

- `ultimate-workflow-reference.md`
- `subagent-task-template.md`

If the repo uses them, also maintain:

- `tasks/todo.md`
- `tasks/lessons.md`

## 11. Repo Identity

This repository is `Elfie Labs Analyzer`, a full-stack lab report understanding system.

The product goal is narrow and proof-oriented:

- accept PDF or image lab reports
- route them safely into the correct trust lane
- extract only structurally defensible lab data
- normalize observations deterministically
- apply deterministic findings, severity, and next-step policy
- produce a patient artifact, clinician artifact, and lineage/proof outputs

The core product stance is:

- extraction is open-world
- interpretation is closed-world
- unsupported or uncertain content must stay visible
- honesty beats polish

## 12. Repo-Specific Source Of Truth

When working in this repo, use this read order:

1. `labs_analyzer_v13_final_architecture_definition.md`
2. `contracts/README.md`
3. relevant files in `contracts/examples/`
4. `README.md`
5. `tasks/todo.md`
6. `tasks/lessons.md`
7. the code, tests, and scripts you are changing

Important implications:

- `labs_analyzer_v13_final_architecture_definition.md` is the active architecture authority
- contract examples are representative payloads, not throwaway fixtures
- if backend/frontend contract behavior changes, examples must stay aligned

## 13. Active Architecture Guardrails

Agents must understand and preserve these repo-specific boundaries:

- trusted born-digital PDF is the primary proof lane
- image/scanned parsing is a separate `image_beta` lane
- born-digital parsing uses `PyMuPDF`
- image/scanned parsing uses the Qwen OCR lane configured in the repo
- parser backends emit `PageParseArtifactV4`, not observations directly
- the typed bridge goes through block graph and row assembly before normalization
- interpretation stays deterministic: no LLM sets findings, severity, or next-step classes in the trusted path
- unsupported input must be rejected or downgraded explicitly, never silently promoted
- threshold conflicts, unsupported rows, and not-assessed content must remain visible in artifacts
- longitudinal wording must stay neutral: `increased`, `decreased`, `similar`, or `trend unavailable`

Key output contracts named by the architecture:

- `PageParseArtifactV4`
- `BlockGraphV1`
- `CandidateRowV3`
- `CanonicalObservationV3`
- `SuppressionReportV1`
- `PatientArtifactV2`
- `ClinicianArtifactV2`
- `CorpusBenchmarkReportV2`

If a change cannot be tied back to one of those artifacts or the systems supporting them, stop and re-check scope.

## 14. Repository Map

Key top-level directories:

- `backend/`: FastAPI app, schemas, services, migrations, workers, tests
- `frontend/`: Vite + React + TypeScript UI
- `contracts/`: shared payload freeze docs and example artifacts
- `data/`: terminology, alias, UCUM, family config, and policy inputs
- `artifacts/`: generated reports, proof packs, and uploads
- `scripts/`: helper scripts for DB setup, terminology import, and corpus validation
- `tasks/`: task tracking and durable lessons

Backend map:

- `backend/app/api/routes/`: HTTP entrypoints for health, upload, jobs, artifacts
- `backend/app/services/document_system/`: routing, parsing substrate, block graph, and row assembly architecture
- `backend/app/services/input_gateway/`: file intake and lane eligibility
- `backend/app/services/parser/`, `ocr/`, `qwen_vl_parser/`: parser/OCR implementations
- `backend/app/services/observation_builder/`, `analyte_resolver/`, `ucum/`: normalization stack
- `backend/app/services/rule_engine/`, `severity_policy/`, `nextstep_policy/`, `panel_reconstructor/`: deterministic policy layer
- `backend/app/services/artifact_renderer/`, `explanation/`, `lineage/`, `proof_pack/`: output and provenance layer
- `backend/app/workers/`: pipeline orchestration entrypoints
- `backend/app/templates/en` and `backend/app/templates/vi`: language-specific rendering templates

Frontend map:

- `frontend/src/components/patient_artifact/`: patient-facing artifact UI
- `frontend/src/components/clinician_share/`: clinician-share UI
- `frontend/src/components/upload/` and `processing/`: upload and job-status flows
- `frontend/src/components/history_card/` and `guided_ask/`: supporting UX surfaces
- `frontend/src/services/api.ts`: frontend API client
- `frontend/src/types/`: frontend contract mirrors
- `frontend/src/i18n/`: English and Vietnamese UI strings

## 15. Contract And Change Boundaries

Be explicit about which surface you are changing.

Truth-engine work usually lives in:

- `backend/app/**`
- `backend/tests/**`
- `data/**`
- parser and validation scripts under `scripts/`

Patient-surface work usually lives in:

- `frontend/index.html`
- `frontend/public/**`
- `frontend/src/**`

Shared-contract work includes:

- `contracts/**`
- `contracts/examples/**`
- `backend/app/schemas/**`
- `backend/app/api/**`
- `frontend/src/services/api.ts`
- `frontend/src/types/**`

Rules for shared-contract changes:

- inspect the current examples first
- change examples deliberately when the contract changes
- keep backend and frontend mirrors aligned in the same task
- never silently widen a contract just to unblock UI work

## 16. Verification Defaults

Use the smallest honest verification scope that proves the change.

Backend verification from `backend/`:

- `python -m pytest`
- `python -m ruff check .`
- `python -m mypy .`

Frontend verification from `frontend/`:

- `npm run lint`
- `npm run build`

Useful focused backend verification:

- `pytest tests/unit/`
- `pytest tests/integration/`
- phase-specific tests under `backend/tests/unit/` and `backend/tests/integration/`

Repo helper scripts:

- `python scripts/run_corpus_bench.py`
- `python scripts/run_ground_truth_validation.py`
- `python scripts/run_v11_corpus_validation.py`
- `./scripts/setup_db.sh`
- `python scripts/import_loinc.py`

Use script-level or corpus-level validation when the change affects parsing quality, routing, proof-pack outputs, or public readiness claims.

## 17. How Tests Are Organized

Tests in this repo are phase-oriented and often encode rollout gates.

Patterns to know:

- `backend/tests/unit/test_contract_examples*.py`: contract example validity and coverage
- `backend/tests/unit/test_person_a_subagent_gates.py`: acceptance-style guardrails for delegated phase work
- `backend/tests/unit/test_phase_4x_*.py`: newer architecture, routing, parser, and row-assembly guardrails
- `backend/tests/integration/test_phase_*.py`: runtime and workflow behavior across API and pipeline stages

Do not treat a green unit subset as proof of production readiness if the source-of-truth runtime path is still unverified.

## 18. Repo Workflow Expectations

For non-trivial tasks in this repo:

- rewrite `tasks/todo.md` before major edits
- keep the checklist current while you work
- add a short review and verification summary when done
- if the user corrects a mistake, add a prevention rule to `tasks/lessons.md`

Worktree discipline:

- inspect `git status --short` before editing
- do not revert unrelated user changes
- keep doc-only tasks isolated from frontend/backend work already in progress

## 19. Hard Stops

Stop and surface the issue if any of these become true:

- the task starts changing medical meaning, severity policy, or next-step policy without explicit intent
- a parser change starts bypassing `PageParseArtifactV4`, block graphing, or row assembly
- the UI needs backend behavior or contract fields that do not exist
- contract examples no longer describe the intended shape
- a change would blur trusted PDF and `image_beta` trust levels
- verification failures suggest wider scope than the current task
- you cannot show evidence for a completion claim

## 20. Practical Defaults

Assume these defaults unless the user says otherwise:

- Python version target: `3.11`
- backend lint/type/test commands come from `backend/pyproject.toml`
- frontend scripts come from `frontend/package.json`
- frontend contract touchpoints are `frontend/src/services/api.ts` and `frontend/src/types/`
- do not commit secrets, real patient data, or sensitive generated artifacts

If this file and a repo source-of-truth document disagree, follow the higher-priority source and update this file when appropriate.
