● Elfie Labs — Adversarial Review (empirically probed, no fixes)                          
                                                                                                                                           
  🔴 CRITICAL                                                                                                                              
                                                                                                                                           
  1. Committed Qwen API key .env:6 — ELFIE_QWEN_API_KEY=sk-40f6f648a29e4195af99a31719c1e748 live in repo. Rotate + purge history.          
  2. HbA1c NGSP vs IFCC collision analyte_resolver/__init__.py:437–447 + launch_scope_analyte_aliases.json — METRIC-0063 (%) and           
  METRIC-0064 (mmol/mol) both normalize to "hba1c". First-come wins. Clinically wrong.                                                     
  3. Debug VLM dump always written pipeline.py:359–373 — raw extraction (PHI) written to artifacts/debug/{job}_vlm_extraction.json +       
  embedded in patient_artifact["_debug_raw_extraction"]. No DEBUG flag.
  4. Profile override silent bypass rule_engine/__init__.py:610–618 — profile.ref_high=None returns None without fall-through to rule
  thresholds. Findings vanish.
  5. Profile override hardcoded S1 rule_engine:613,617 — crosses ref_high → always S1. No S2/S3/S4 gradient.
  6. Session/transaction boundary upload.py:128–139 — session.commit() runs even if pipeline.run() partial-fails inside async-with. Partial
   state persisted.

  🟠 HIGH

  7. CORS main.py:34–41 — allow_methods=["*"] + allow_headers=["*"] + allow_credentials=True. CSRF/header injection surface.
  8. All children → SX severity_policy/__init__.py:26,36–37 — blanket SX suppresses valid age-stratified rules (eGFR, creatinine). Double
  suppression vs rule engine demographics.
  9. Rule precedence non-deterministic rule_engine:141–155 — first match wins, unsorted. No priority/rule_id sort.
  10. HDL sex fallback empty rule_engine:632–635 — sex_thresholds without "default" key → empty thresholds → silent miss.
  11. Numeric range tokens dropped analyte_resolver:421–423 — "3","10" in _TRAILING_QUALIFIER_TOKENS shreds "Glucose 100-150" →
  unrecognized.
  12. Token-signature uniqueness constraint analyte_resolver:160–161 — ambiguous tokens silently fall through rather than returning
  multi-candidate.
  13. PDF bomb DoS vlm_gateway.py:94–102 — pdfplumber.to_image(150dpi) full in-memory, 30 pages unbounded. OOM-crashable.
  14. Global VLM auto-mock conftest.py:18–89 — 96% of tests bypass real OCR/VLM. Integration tests = false confidence. Zero PDF fixtures on
   disk.
  15. CI lint/type non-blocking .github/workflows/backend-ci.yml:80–93 — ruff/mypy don't gate, no --strict, no coverage threshold.
  16. Duplicate trust-status pipeline.py:341–345 — dead/copy-paste block (harmless, smell).

  🟡 MEDIUM

  17. NaN silent in-range rule_engine:699–735 — NaN < low False, NaN > high False → returns True. Pathological values pass.
  18. Float boundary without epsilon rule_engine:624,639 — strict >=/<= on float parsed JSON. No math.isclose.
  19. Panel field drift panel_reconstructor/__init__.py:94 expects candidate_code vs rule policy codes. Silent regrouping failure if schema
   moves.
  20. Lineage uuid5 collision lineage/__init__.py:14,21 — json.dumps(default=str) flattens datetime==iso-string → same lineage_id for
  different payloads.
  21. Markdown/XSS in artifact artifact_renderer:120–127 — analyte_display from OCR not escaped. Injection risk downstream.
  22. Correlation ID lost main.py:46 sets ContextVar, pipeline _LOGGER doesn't read it. Tracing broken.
  23. Unbounded upload race upload.py:43–45,88–108 — full await file.read() before size check; idempotency check → create non-atomic.
  24. API key leak on httpx error vlm_gateway.py:161,192 — %s on HTTPError; no header redaction.
  25. No timeout on pdfplumber to_image vlm_gateway.py:97–102 — only httpx has 60s; image conv can hang job.
  26. VLM confidence default=100 vlm_gateway.py:28–32 + lab_normalizer.py:39 (score or 95) — never gates low quality early; 0 not treated
  as unset.
  27. MIME allowlist thin input_gateway.py:46–51 — no polyglot/magic-byte check; extension+MIME alias bypass.
  28. IMAGE_BETA gate late pipeline.py:295 — checked post-classification; env override can flip prod silently.
  29. Empty doc silent continue pipeline.py:563–565 — zero rows proceed, no audit flag.
  30. N+1 loop pipeline.py:792–806 — O(n·m) dict filter per finding.
  31. Enum/string status drift pipeline.py:199 string compare "fully_supported"; no enum validation.
  32. retry_count no DB default tables.py:52 ORM default only; migration has no server_default. NULL on raw SQL insert.
  33. Exception context dropped pipeline.py:468 no exc_info=True; upload.py:144 str(exc) only.
  34. Retry race jobs.py:107–182 local retry_count incremented before DB commit; spam bypasses max_job_retries.
  35. Monolithic migration 20260410_0001_initial_schema.py — single rev, no safe rollback checkpoint.
  36. Docker compose no mem_limit/cpus/restart. Healthcheck exists but no auto-recover.
  37. Floating deps pyproject.toml all >=, no upper bound. Silent break on minor bumps.
  38. Frontend no tests — no vitest/jest; CI has no FE gate.
  39. Response not schema-validated services/api.ts:11–12 bare .json(); no zod. Drift = runtime crash.
  40. Hardcoded /api services/api.ts:3 — breaks split-domain prod deploy.
  41. No error boundary patient_artifact/index.tsx — single throw blanks UI.
  42. Polling no AbortController/backoff processing/index.tsx:15–16,98–189 — fixed 2s, 180 retries, no cancel.
  43. Status string normalization fragile processing:148–168 — case-sensitive enum parse.
  44. threading.Lock in async observability.py:32–47 — not asyncio-safe; snapshot unguarded.

  🟢 LOW

  45. Dead code analyte_resolver:67 _LABEL_UNIT_STRIP_RE = None unused.
  46. Sex-threshold key case rule_engine:634–635 — JSON keys lowercased today, not enforced at load.
  47. Child cutoff <18 severity_policy:26 — no comment on rationale.
  48. Trailing tokens s,p,u analyte_resolver:32–64 — single-letter collisions possible.
  49. BytesIO not context-managed vlm_gateway:99–102 — GC-only cleanup.
  50. Blob URL leak clinician_share:341–371 — setTimeout(revoke,1000) race on navigate.
  51. Empty test test_phase_15_observability.py — 1 line, intent unclear.
  52. Flaky sleep tests/integration/helpers.py:40 — 0.05*(n+1) exp backoff on slow CI.