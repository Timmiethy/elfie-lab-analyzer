# Agentic Backend Maintenance Guide

This guide covers operational maintenance for the Copilot-orchestrated, Gemini-worker engineering workflow.

## 1. Cadence
### Daily
- Review new worker results for schema validity and unresolved blockers.
- Confirm required tests were executed for each completed packet.
- Clear stale local scratch files (`tasks/todo.md`, `tasks/lessons.md`) if session ended.

### Weekly
- Audit packet quality: overly broad scope, missing tests, or weak completion definitions.
- Review CI failures by category (lint/type/tests/infrastructure).
- Verify deterministic guardrails are still reflected in AGENTS/GEMINI contracts.

### Monthly
- Review toolchain versions (Gemini CLI channel, Python deps, Ruff/MyPy).
- Evaluate incident patterns from lessons logs.
- Refine packet schema and templates only with explicit version bumps.

## 2. Versioning Policy
- `task-packet-v1` and `worker-result-v1` are stable contracts.
- Any breaking field change requires:
  1. schema version bump
  2. template updates
  3. runbook updates
  4. CI or validator updates

## 3. Incident Playbooks
### A. Worker output schema failures
Symptoms:
- validator fails on missing fields or invalid status.

Response:
1. keep failed artifact for traceability
2. rerun with narrower packet and stricter objective language
3. use dispatcher repair retries (`--max-repair-attempts 2`)
4. if repeated, mark blocked and escalate to supervisor

### B. Scope drift
Symptoms:
- `changed_files` includes files outside `allowed_paths`.

Response:
1. reject completion
2. split packet into smaller scope
3. enforce additional forbidden paths

### E. Non-completed validation handling
Symptoms:
- result status is `blocked` or `failed` and validator exits non-zero.

Response:
1. keep default fail-closed behavior for merge gates
2. use `--allow-noncompleted` only for triage/inspection workflows
3. never merge artifacts that remain non-completed

### C. Test regressions after merge candidate
Symptoms:
- required tests pass in worker report but fail locally/CI.

Response:
1. rerun tests in clean environment
2. compare command arguments and env assumptions
3. reject packet and re-dispatch with explicit reproducibility steps

### D. Extraction quality degradation
Symptoms:
- supported rows move to unsupported or vice versa unexpectedly.

Response:
1. run contract and integration suites
2. compare proof pack metrics and lineage versions
3. hold merge until root cause identified

## 4. Security and Compliance Maintenance
- Keep secrets in `.env` only.
- Rotate API keys as required by platform policy.
- Keep MCP servers untrusted by default.
- Explicitly allowlist MCP tools if/when enabled.
- Never store patient data in worker prompts or result artifacts.

## 5. Token-Efficiency Maintenance
- Monitor prompt size drift in packet templates.
- Keep context payloads minimal (changed files + direct dependencies).
- Replace broad tests with focused suites in packet requirements where feasible.
- Avoid full log dumps in worker results; keep summarized evidence.

## 6. Upgrade Procedure (Gemini CLI)
1. Update in a feature branch:

```bash
npm install -g @google/gemini-cli@latest
gemini --version
```

2. Run smoke workflow:
- dispatch one dry-run packet
- dispatch one real packet
- validate result
- run backend CI locally

3. Roll out only after successful smoke checks.

## 7. Operational Checklist for Supervisor Sign-Off
- Packet scope respected.
- Worker result schema valid.
- Required tests passed and reproducible.
- No contract drift unless intentional and approved.
- Risks documented with explicit follow-ups.
