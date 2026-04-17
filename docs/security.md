# Security Operations

## Secret Handling

### API Keys (Qwen, others)

- Never commit real API keys to git.
- `.env` is gitignored (see `.gitignore:20`). Use `.env` for local dev only.
- `.env.example` holds the sentinel `__replace_me__` for every secret-bearing variable.
- CI uses GitHub Actions secrets, never checked-in values.

### Known Incidents

| Date       | Key                 | Remediation                                    |
|------------|---------------------|------------------------------------------------|
| 2026-04-17 | `ELFIE_QWEN_API_KEY` committed to working tree (`.env:6`). Not in git history (file gitignored). | **Rotate in Qwen/DashScope console immediately.** Replace local `.env` with new key. Audit logs for any external use of the old key. |

### Rotation Procedure

1. Log into the DashScope console.
2. Revoke the compromised key.
3. Issue a new key.
4. Update local `.env` (developer workstation only).
5. Update CI secret `ELFIE_QWEN_API_KEY` in GitHub Actions.
6. Redeploy backend; verify `POST /api/upload` smoke test passes.
7. Record the rotation in the table above.

### Pre-commit Protection

Recommended local hook (add to `.pre-commit-config.yaml`):

```yaml
- repo: https://github.com/Yelp/detect-secrets
  rev: v1.5.0
  hooks:
    - id: detect-secrets
```

## Logging Redaction

- `backend/app/services/vlm_gateway.py` MUST NOT log raw `httpx.HTTPError` objects; they can serialize request headers including `Authorization: Bearer ...`. Log `type(e).__name__` and `e.response.status_code` only.
- Any new outbound HTTP client follows the same pattern.

## PHI Handling

- The debug VLM dump at `backend/app/workers/pipeline.py` is gated behind `settings.debug AND settings.allow_debug_artifacts`. Default: disabled. Enable only on non-PHI test fixtures.
- Patient artifact JSON never contains raw extraction payloads in production responses.
