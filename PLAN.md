## Plan: VLM Document Intelligence Refactor (V2 - Hardened)

**Summary of the Solution**
We are refactoring to a single-step, constrained Vision-Language Model architecture (using Alibaba Cloud Qwen3-VL) to replace the legacy OCR+LLM fragile pipeline. This guarantees deterministic JSON schema generation via constrained decoding, semantic normalization, and strict programmatic policy routing. The VLM extraction will exclusively generate a **flat, bounded array** representing laboratory data. All subsequent processing (triage, mapping, unit translation, severity routing) is handled through standard deterministic Python execution (no LLM logic). 

### Identified Flaws & Patches from V1
1. **API Limitations (The "Logprob" Risk):** *Critique:* Alibaba's managed Qwen3-VL API does not natively expose token-level entropy/logprob confidence scores alongside structured JSON outputs (unlike a local `vLLM` instance). *Patch:* We must transition the "confidence" metric from native model logprobs to an explicitly constrained integer field (`confidence_score`, bounded 0-100) inside the JSON schema, combined with strict programmatic bounds checks in our pipeline.
2. **Schema Breakage (The "Bounding Box" Risk):** *Critique:* Asking a VLM to generate heavily nested coordinate structures `[ymin, xmin, ymax, xmax]` for *every* individual metric (name, value, unit, range) causes frequent schema compilation errors and hallucinations. *Patch:* We must flatten the requested JSON schema into an array of `TestRow` objects containing a singular `row_bounding_box`, bounding the entire visual row rather than fragmenting it.
3. **The Molecular Weight Risk:** *Critique:* Relying on the VLM or an external query to dynamically execute mass-to-molar conversions (e.g., mg/dL to mmol/L) introduces hallucination or network latency. *Patch:* We must implement a static JSON mapping table of target LOINC molecular mass constraints natively inside `data/ucum/molar_weights.json`.
4. **Lane Selection Debt:** *Critique:* Removing OCR means the `preflight` classifier (separating trusted PDFs from image betas) is useless. *Patch:* Rip out lane routing entirely. All inputs are visual arrays routed directly to the VLM.

**Items to Discard Mercilessly Right Away**
- ocr (Delete entirely)
- parser (Regex fallbacks; delete entirely)
- extraction_qa (Prompt repair is dead in a constrained PDA schema; delete entirely)
- pipeline.py lane selection logic (preflight image vs pdf checks).
- Hybrid text/OCR generation dependencies (e.g., passing PDF text + image as a combined prompt).

**Technical Debt to Solve**
- **Now:**
  - Rewrite `pydantic` schemas in `backend/app/schemas/extraction.py` to be strictly FLAT (e.g., `list[TestRow]`) with the aforementioned `confidence_score` and `row_bbox` integers.
  - Establish a deterministic UCUM mapping table for LOINC identifiers requiring mass-to-molar conversions (`data/ucum/molar_weights.json`).
- **Later (Post-Removal):**
  - Delete `parser-heuristics.md` notes.
  - Clear out legacy Tesseract/adapter configuration environments from Docker and dependencies.

**Concrete Workflow & Step-by-Step Instructions**

*Phase 1: Architecture Cleanup & Schema Constraints*
1. **Delete Dead Paths:** Remove `/services/ocr`, `/services/parser`, `/services/extraction_qa` directories. Rip out `PipelineStep.LANE_SELECTION` and `PREFLIGHT` from pipeline.py.
2. **Define Flat JSON Schema Constraints:** Update `backend/app/schemas/extraction.py`. Create `VLMAnalyteRow` featuring strictly typed fields: `analyte_name`, `value` (nullable string), `unit` (nullable string), `reference_range_raw` (nullable string), `row_bbox_ymin_xmin_ymax_xmax` (array of 4 integers), and `confidence_score` (integer 0-100).

*Phase 2: VLM Integration & Extraction*
3. **Implement Gateway Client:** Create `backend/app/services/vlm_gateway.py`. Implement an explicit Alibaba Cloud Python SDK invocation targeting Qwen3-VL, enforcing `response_format={"type": "json_schema"}` matched against the `VLMAnalyteRow` array. Send the image array and drop all raw text inputs. 

*Phase 3: Semantic & Unit Normalization*
4. **Enforce Local Normalization:** 
   - Update `analyte_resolver.py` to map the `analyte_name` strictly against `launch_scope_analyte_aliases.json` (no fuzzy LLM matching).
   - Update `app/services/ucum.py`. If a unit is mass-based but the policy rule table requires molar, consult the new local file `data/ucum/molar_weights.json` keyed by LOINC to derive the conversion multiplier mathematically using standard Python arithmetic.

*Phase 4: Triage & Abstention*
5. **Implement Safe Abstention routing:** In pipeline.py, iterate the returned VLM rows. If `confidence_score < 90`, OR if mapping misses, OR if UCUM conversion fails, branch the row into an `unsupported` bucket within the artifact structure, preserving its lineage (`row_bbox`) so the UI can highlight exactly what was skipped to the patient.

*Phase 5: Deterministic Patient Artifact*
6. **Rule & Render Triage:** Feed the accepted, normalized array strictly through `severity_policy` and `nextstep_policy`. Append the spatial coordinates `row_bbox` array to the final `patient_artifact` JSON output so the frontend (React) can accurately draw a highlight box over the source document.

**Verification (Strict Success Criteria)**
1. **Payload Contract:** Send an example PDF to the API pipeline locally. Assert the output strictly contains flat array outputs with corresponding `[ymin, xmin, ymax, xmax]` integers and a valid confidence score. Any nested or hallucinatory keys must fail the build.
2. **Safe Abstention Gate:** Feed a mock image with an obscured/smudged value row. The VLM must output `confidence_score < 90`. Assert the pipeline automatically flags this as `TrustStatus.NON_TRUSTED`, omits it from clinical interpretation, and places it in the `unsupported` banner section.
3. **Unit Translation Matrix:** Pass a mock extraction containing "Glucose: 90 mg/dL". Assert that `ucum.py` intercepts this, looks up Glucose molar weight in the JSON file, and transforms it flawlessly to `mmol/L` without LLM mediation.

**Principles, Protocols, Rules, and Guardrails**
- **Zero Hallucination Tolerance (Strict Lineage):** Every single interpreted data row MUST possess complete spatial bounding box coordinates. Empty coordinates equal dropped data (safe abstention).
- **Rules are Code:** The model determines *what* is written on the page. Deterministic Python code determines *what to do about it*. Never let the VLM output severity scores, risk metrics, or patient instructions.
- **Fail Closed (Safe Abstention):** Any error in mapping, unit conversion, or confidence thresholding immediately invalidates the row. It is placed into a "We couldn't read this" UX bucket. False negatives (missing data) are clinically safer than false positives (hallucinated severity).
- **Static Ground Truth:** Do not query dynamic web endpoints for LOINC molecular weights or terminologies at runtime. Everything must be locally deterministic inside the data volume.
- **Multilingual Output:** Translation logic must strictly map non-English labels -> canonical ontology (LOINC). Final artifact explanations must exclusively pull from validated resource dictionaries (i18n), never using LLM auto-translated output for patient clarity.