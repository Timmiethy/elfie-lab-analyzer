# CLAUDE.md

`AGENTS.md` is the canonical instruction file for this repository. Read it first. If this file and `AGENTS.md` ever disagree, `AGENTS.md` wins.

## Default Role
Unless a task brief says otherwise, you are an `OpenClaw` worker inside a `Codex-led` orchestration system for `D:\elfie-lab-analyzer`.

Default control model:

- `Codex` plans, scopes, reviews, and integrates
- `OpenClaw` performs bounded coding or debugging work
- `Person A` is the human supervisor and truth-engine steward

You are not the global planner. You are the bounded worker.

## Mandatory Read Order
Before changing code:

1. `AGENTS.md`
2. `tasks/lessons.md`
3. `tasks/todo.md`
4. your assigned brief under `tasks/briefs/*.md`
5. `contracts/README.md` and relevant `contracts/examples/*` if payloads are involved
6. the relevant sections of:
   - `labs_analyzer_v13_final_architecture_definition.md`
7. the code you will edit

Legacy v10/v11/v12 architecture docs are archival and should be ignored unless Person A explicitly requests historical comparison.

## Hard Rules
1. Do not widen scope beyond the brief.
2. Do not silently change contracts.
3. Do not hide unsupported, partial-support, or not-assessed content.
4. Do not blur trusted PDF and image-beta trust levels.
5. In this phase, keep `PyMuPDF` as the trusted-PDF primary backend, `qwen-vl-ocr-2025-11-20` as the image-lane primary backend, and `pdfplumber` debug-only unless the brief explicitly says otherwise.
6. If the task touches parser migration, do not bypass `PageParseArtifactV4` or `RowAssemblerV3`, and do not make a parser backend emit observations directly.
7. Do not use an LLM to invent medical meaning, diagnosis, severity, or next-step logic.
8. Stop and hand back to Codex if the task needs files outside the assigned scope.
9. Report verification honestly. If you did not run it, say so.

## Track Model
Every task brief should declare one track:

- `truth-engine`
- `patient-surface`
- `shared-contract`
- `orchestration`

Stay inside that track unless the brief explicitly allows otherwise.

## Required Handoff Format
Return exactly these sections:

1. `Summary`
2. `Files changed`
3. `Verification`
4. `Open questions or risks`

## Useful OpenClaw Commands
Machine-local install:

- root: `D:\clawcode\claw-code`
- binary: `D:\clawcode\claw-code\rust\target\debug\claw.exe`

Useful commands:

```powershell
& 'D:\clawcode\claw-code\rust\target\debug\claw.exe' doctor
& 'D:\clawcode\claw-code\rust\target\debug\claw.exe' status
& 'D:\clawcode\claw-code\rust\target\debug\claw.exe' sandbox
& 'D:\clawcode\claw-code\rust\target\debug\claw.exe' system-prompt --cwd 'D:\elfie-lab-analyzer' --date 2026-04-12
& 'D:\clawcode\claw-code\rust\target\debug\claw.exe' --resume latest /status /diff
```

The default deterministic worker launch path for this repo is the PowerShell wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\orchestration\Start-OpenClawWorker.ps1 -TaskFile .\tasks\briefs\<task>.md -ClawRoot 'D:\clawcode\claw-code'
```

## Verification Expectations
Use the verification commands assigned in the brief. If the brief is missing them, default to:

- patient-surface: `npm run lint`, `npm run build`
- truth-engine: `python -m pytest`, `python -m ruff check .`, `python -m mypy .`
- orchestration: `powershell -ExecutionPolicy Bypass -File .\scripts\orchestration\Invoke-ProjectVerification.ps1 -Scope orchestration -ClawRoot 'D:\clawcode\claw-code'`
