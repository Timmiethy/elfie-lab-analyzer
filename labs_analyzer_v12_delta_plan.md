
# v12 delta plan: post-v11 changes only

## 0. Decision record

### Final stack verdict

Keep the v11 normalization-first architecture. Freeze the canonical observation contract, suppression taxonomy, threshold reconciliation rules, derived-observation rules, and patient-artifact honesty rules.

Replace the current parsing substrate.

Do not make `pdfplumber` the primary parser any longer.

Adopt a two-lane parsing stack:

1. Born-digital / machine-generated PDF lane  
   Primary: `PyMuPDF` 1.27.x  
   Purpose: page text, words, blocks, tables, images, page metadata, rendering, page geometry.  
   Role: trusted parser substrate for programmatic PDFs.

2. Image / scanned / screenshot / camera lane  
   Primary: `qwen-vl-ocr-2025-11-20`  
   Purpose: OCR, text localization, document parsing, table parsing.  
   Role: OCR and image-document parser.

3. Debug / forensic fallback  
   Secondary: `pdfplumber`  
   Purpose: character-level debugging, visual inspection, extraction comparison on disputed pages.  
   Role: offline diagnosis and family-specific troubleshooting only. Not primary.

4. Shadow evaluation only  
   Benchmark candidate: `PaddleOCR-VL-1.5`  
   Purpose: quarterly benchmark comparison and vendor-risk check.  
   Role: offline evaluation and contingency planning, not immediate production primary.

5. Do not adopt as primary parser in v12  
   - `docling-parse`
   - `marker`
   - `surya`
   - `docTR`
   - generic `qwen-vl-plus` / `qwen-vl-max` as OCR

This is the smallest stack change that fixes the current failure mode without discarding the real moat.

---

## 1. Why v11 changes are not enough

v11 fixed the normalization contract. The failure now sits earlier:

- text is extractable, but rows are still assembled badly
- measured analytes and narrative text still compete in the same funnel
- bilingual labels, dual-value rows, comparator-first rows, and reference-threshold notes are still contaminating candidate rows
- image-heavy inputs still do not reach parity with the typed downstream pipeline

That means the current problem is no longer "we need smarter rules." It is "the parser substrate is too weak and too monolithic for the typed normalization contract we already defined."

v12 therefore changes the parser substrate, not the reasoning core.

---

## 2. Option scorecard

### A. `pdfplumber` as primary

Pros:
- excellent character-level extraction and visual debugging
- mature and simple
- useful for forensic comparison on clean text PDFs

Cons:
- explicitly optimized for machine-generated PDFs, not scanned PDFs
- table extraction is heuristic and not stable enough to be the main abstraction
- too easy to build a fragile line-splitting parser on top of it
- does not solve image-heavy PDFs, screenshots, or camera captures

Verdict:
Keep for debugging and edge-case inspection. Retire as the primary parser.

### B. `PyMuPDF` as primary born-digital parser

Pros:
- strong low-level extraction surface for text, images, metadata, and tables
- current MuPDF 1.27.1 improved structured text extraction and table hunting
- lower operational debt than a full document-AI stack
- good fit for typed page/block/row assembly

Cons:
- not an OCR engine
- still requires family adapters and typed row assembly
- raw extraction alone will not solve bilingual rows or derived-measurement semantics

Verdict:
Best primary parser substrate for the trusted text-PDF lane.

### C. `docling-parse` as primary

Pros:
- good coordinate-rich extraction model
- active development
- integrated with broader Docling ecosystem

Cons:
- more moving parts than needed for this pipeline
- active bug surface in 2026, including page-count failure cases and recent parser-backend churn
- higher operational and upgrade risk than PyMuPDF for a narrow lab-pipeline core

Verdict:
Do not make it the production primary now. Keep as a research alternative only.

### D. `marker` as primary

Pros:
- strong multi-format document conversion
- good broad parsing ambition
- high community activity

Cons:
- broader than the use case
- encourages whole-document conversion when we need typed lab-row extraction
- optional LLM path increases variance and cost
- GPL licensing makes immediate commercial embedding less comfortable

Verdict:
Useful benchmark and exploration tool. Wrong primary production fit.

### E. `qwen-vl-ocr-2025-11-20`

Pros:
- purpose-built for text extraction and structured parsing from scanned documents, tables, and receipts
- explicitly supports multilingual extraction, table parsing, and formula recognition
- based on Qwen3-VL architecture with improved document parsing and text localization
- lower integration debt than self-hosting a separate OCR stack
- cheaper than general-purpose Qwen-VL tiers in global deployment

Cons:
- managed API dependency
- rate limits and residency must be handled
- still not a replacement for typed row assembly and normalization
- must be pinned to a snapshot, not `latest`

Verdict:
Best OCR/image parser for the production pipeline right now.

### F. `qwen3-vl-plus` / `qwen-vl-plus` / `qwen-vl-max`

Pros:
- stronger multimodal reasoning and localization than smaller models
- useful for page-level classification, disagreement review, and offline red-teaming

Cons:
- more expensive than Qwen-OCR for OCR-centric work
- overkill as the primary OCR engine
- increases token cost without solving typed normalization by itself

Verdict:
Use only as an escalation checker or offline evaluator. Do not use as the primary OCR parser.

### G. `PaddleOCR-VL-1.5`

Pros:
- current paper-level SOTA for real-world document parsing under scanning, warping, screen photography, illumination, and skew
- compact 0.9B model relative to reported quality
- strong candidate if on-prem or vendor independence becomes mandatory

Cons:
- self-hosting and serving burden
- new model integration, GPU planning, and observability debt
- larger implementation change than needed right now
- not aligned with the Qwen-based stack already in motion

Verdict:
Best open/self-host contingency. Keep as shadow benchmark, not the immediate primary.

### H. `surya`

Pros:
- OCR, layout, reading order, table recognition in many languages
- useful on-prem layout/OCR toolkit

Cons:
- more operational burden
- not enough reason to add a third document-intelligence stack while parser replacement is already underway

Verdict:
Do not add in v12.

### I. `docTR`

Pros:
- accessible OCR library
- still maintained

Cons:
- OCR library, not a complete document-parser strategy
- current PyTorch-only backend shift is fine, but it does not solve the architecture gap by itself

Verdict:
Do not add in v12.

---

## 3. Final best verdict

### Best overall stack for the pipeline as of 2026-04-12

- API/runtime: keep current Python + FastAPI + PostgreSQL modular monolith
- Job execution: keep database-backed job table workers unless measured load proves otherwise
- Trusted text-PDF lane: `PyMuPDF` 1.27.x
- OCR/image lane: `qwen-vl-ocr-2025-11-20`
- Visual escalation checker: none in primary path; optional `qwen3-vl-plus` in offline disagreement bench
- Debug parser: `pdfplumber`
- Shadow benchmark / vendor-risk hedge: `PaddleOCR-VL-1.5`
- Normalization core: keep v11, continue bug-fix evolution
- Derived reasoning core: keep deterministic
- Explanation layer: unchanged from v11

### Why this is the best verdict

It wins on reliability because it separates born-digital extraction from OCR extraction instead of forcing one tool to do both badly.

It wins on cost because Qwen-OCR is materially cheaper than the general Qwen-VL tiers for document parsing, and because PyMuPDF carries almost no additional serving cost.

It wins on technical debt because it avoids introducing Docling/Marker/Surya as new primary platform dependencies.

It keeps cutting-edge accuracy because the OCR lane moves to the strongest practical managed document parser in the current Qwen stack, while the open-source hedge remains PaddleOCR-VL-1.5.

---

## 4. v12 architecture delta

### 4.1 Replace the parser substrate

Remove:
- `pdfplumber` as the default page parser
- `extract_tables()`-driven row creation as a primary mechanism

Add:
- `BornDigitalPageParser` backed by PyMuPDF
- `ImagePageParser` backed by Qwen-OCR
- `ParserDebugBackend` backed by pdfplumber

### 4.2 Keep the typed normalization funnel exactly where it is

Do not change these contracts except for bug fixes:

- `CanonicalObservationV2`
- `CandidateRow`
- `SupportCode`
- `FailureCode`
- `DerivedObservation`
- `ThresholdReconciliationRecord`
- `SuppressionReport`
- patient artifact visibility rules
- clinician artifact visibility rules

### 4.3 Introduce a parser-output contract

Every parser backend must emit `PageParseArtifactV3`:

```yaml
page_id: str
backend_id: enum[pymupdf,qwen_ocr,pdfplumber_debug]
backend_version: str
lane_type: enum[trusted_pdf,image_beta,debug]
page_kind: enum[lab_results,threshold_table,admin_meta,narrative,footer,unknown]
text_extractability: enum[high,medium,low,none]
language_candidates: [str]
block_count: int
blocks:
  - block_id: str
    block_type: enum[result_table,threshold_table,admin_meta,narrative,footer,header,unknown]
    bbox: [float,float,float,float]
    lines: [...]
tables: [...]
images: [...]
warnings: [str]
```

No parser backend may emit `CanonicalObservation` directly.

### 4.4 Introduce a row-assembly contract

A dedicated `RowAssemblerV2` now owns conversion from blocks/tables into typed candidate rows.

Inputs:
- `PageParseArtifactV3`
- family adapter
- locale profile
- analyte alias bundle

Outputs:
- `CandidateRow[]`

Candidate rows must have:

```yaml
row_id: str
row_type: enum[measured_analyte,derived_analyte,qualitative_result,admin_meta,threshold_row,narrative_row,footer_row,noise]
raw_label: str
raw_value_primary: str | null
raw_value_secondary: str | null
raw_unit_primary: str | null
raw_unit_secondary: str | null
raw_reference: str | null
parsed_comparator: str | null
parsed_locale: str | null
specimen_hint: str | null
method_hint: str | null
source_block_id: str
source_tokens: [...]
```

Only `measured_analyte`, `derived_analyte`, and approved `qualitative_result` rows may continue into analyte resolution.

### 4.5 Add lane-specific parser rules

#### Trusted PDF lane
Precondition:
- machine-generated or high-confidence born-digital page
- PyMuPDF text layer exists
- text coverage above threshold

Path:
- PyMuPDF -> block classifier -> row assembler -> normalization

#### Image lane
Precondition:
- image density high, text layer absent, or raster-first upload

Path:
- Qwen-OCR -> block classifier -> row assembler -> normalization

Constraint:
- image lane remains `image_beta` until all image-specific release gates are met
- zero silent promotion into trusted status

#### Debug lane
Used only in:
- CI differentials
- bug triage
- disagreement analysis

Path:
- pdfplumber char extraction and overlays
- never used to publish production user artifacts directly

---

## 5. Model pinning

Pin exact versions.

Required pins:

- `PyMuPDF` / MuPDF: 1.27.1 family
- `qwen-vl-ocr-2025-11-20`
- `pdfplumber` stable pinned in lockfile
- `PaddleOCR-VL-1.5` only in shadow benchmark environment

Forbidden:
- `latest` aliases in production
- swapping OCR snapshots without benchmark rerun
- parser backend changes without corpus replay

---

## 6. Guardrails

### 6.1 Parser guardrails
- No parser backend may create observations directly.
- No parser backend may emit patient-visible text directly.
- Any page with ambiguous page kind must be downgraded before row assembly.
- Narrative, admin, footer, and threshold blocks are fenced off before analyte mapping.
- If page text extraction and OCR disagree materially on the same trusted PDF page, emit `parser_disagreement` and downgrade.

### 6.2 OCR guardrails
- Qwen-OCR output must still pass the same `CandidateRow` grammar gates as born-digital pages.
- OCR confidence alone cannot create trust. The normalization gates decide trust.
- Image-lane pages that fail row grammar or analyte binding go to preview-only or unsupported, never to trusted output.

### 6.3 Normalization guardrails
- `insufficient_support` remains forbidden as a generic sink.
- Every failed row must map to a typed `support_code` / `failure_code`.
- Metadata and narrative content are forbidden from patient-visible `what was not assessed`.
- Derived observations require explicit formula id and source observation ids.
- Threshold conflicts must be rendered visibly or suppression must occur.

### 6.4 Cost guardrails
- Qwen-OCR is primary for OCR/document parsing.
- General-purpose Qwen-VL models may not be used in the primary parsing path.
- `qwen3-vl-plus` may be used only in capped offline disagreement batches.

---

## 7. Release gates

### 7.1 Trusted PDF lane
Minimum stop/go gates:
- row_precision >= 0.98
- row_recall >= 0.95
- row_f1 >= 0.965
- false_supported_out_of_layout == 0
- accepted_observation_precision >= 0.99
- unsafe_unit_false_accept == 0
- metadata_leak_to_patient_artifact == 0
- threshold_table_leak_to_candidate_rows == 0

### 7.2 OCR/image lane
Minimum stop/go gates for preview-only beta:
- OCR_row_f1 >= 0.90
- field_linkage_accuracy >= 0.93
- preview_false_support == 0
- trusted_promotion_rate == 0 until full image benchmark passes
- image_abandon_rate tracked and reported

### 7.3 Cross-lane normalization
- same canonical analyte from same document rendered by different parsers must match within tolerance
- dual-value rows must preserve both values and unit families
- comparator-first rows must preserve comparator semantics
- derived rows must never be mistaken for measured rows

---

## 8. Clear output definitions

v12 production outputs must be these and only these:

1. `PageParseArtifactV3`
2. `CandidateRowArtifactV2`
3. `NormalizationTraceV3`
4. `CanonicalObservationV2`
5. `SuppressionReportV2`
6. `PatientArtifactV2`
7. `ClinicianArtifactV2`
8. `CorpusBenchmarkReportV2`

The pipeline is done when:
- every production artifact can be reproduced from raw file + pinned versions
- every suppression has a typed reason
- every patient-visible finding links to a traceable observation lineage
- every parser backend can be replayed on the corpus and compared side by side

---

## 9. Concrete rejected changes

Rejected in v12:

- replacing normalization with end-to-end vision parsing
- using generic Qwen-VL as the primary OCR engine
- adding Docling as another production parser stack
- adding Marker as the production parser
- adding Surya or docTR to the primary pipeline
- adding Redis/Valkey solely to support parser migration
- changing rule logic before parser migration stabilizes

---

## 10. Rollback and failure policy

If PyMuPDF integration underperforms:
- keep PyMuPDF page rendering and metadata
- temporarily re-enable `pdfplumber` extraction only for approved families
- do not revert the typed row funnel

If Qwen-OCR underperforms:
- keep image lane preview-only
- continue blocking trusted promotion
- activate the shadow PaddleOCR-VL benchmark track
- do not weaken image-lane gates to save coverage

If benchmark regressions appear:
- freeze alias-table edits
- freeze new family adapters
- bisect parser backend changes before touching normalization logic

---

## 11. Source-of-truth update rule

v12 is a delta on top of v11.

Anything not changed here remains as defined in v11.

v12 changes only:
- parser substrate
- parser artifacts
- row assembly contract
- lane routing
- model pinning
- parser-specific gates
- rollback policy
