- For agent_ops dispatches in this repo, pass explicit --gemini-bin C:/Users/hlbtp/AppData/Roaming/npm/gemini.cmd to avoid PATH-dependent gemini_binary_not_found failures.
- Prefer Gemini 3.x Flash models for retry waves when Pro capacity is exhausted; validated working values: gemini-3.1-flash-lite-preview and gemini-3-flash-preview.
- When worker-result validation fails with invalid_command_item_type, tighten packet constraints to force commands_executed/test_results as [] so dispatcher-only check objects remain schema-valid.

- Qwen/DashScope VLM health probes must use images with width and height both > 10px; 1x1 data URLs trigger invalid_parameter_error and can look like false API outages.
- Start backend validation server from repo root with factory module path (backend.app.main:create_app); launching from backend/ with app.main can produce ASGI app=None behavior and misleading 500s.
- Patient artifact payloads can omit trust_status; frontend summary rendering must default trust metadata (and other enum/array fields) defensively to avoid post-loading blank-screen crashes.
- Frontend blank-screen regression: `HistoryCard` expects an `observations` prop; passing `history` from patient artifact causes a post-loading render crash.



- When terminal cwd is backend/, use paths relative to backend (app/, tests/, ../scripts/...) for git and lint commands; prefixing backend/ can silently no-op checks or target non-existent backend/backend paths.

- Validation runners should hard-fail immediately when `docker compose up` fails (e.g., Docker daemon down) instead of waiting on health polls; this avoids multi-minute wasted compute cycles.