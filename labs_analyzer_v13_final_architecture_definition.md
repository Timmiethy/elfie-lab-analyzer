# Labs Analyzer final architecture definition v13

## Goal
Accept any uploaded report, route it safely, extract only what is structurally defensible, normalize into canonical observations, and produce a production-safe patient artifact and clinician artifact. Extraction is open-world. Interpretation is closed-world.

## 1) Control plane

### 1.1 Input gateway

Owns:

- file sanitization
- checksum
- MIME / extension sanity
- corruption / encryption detection
- initial lane eligibility

### 1.2 Document router

Returns one terminal document class:

- `trusted_pdf_lab`
- `image_pdf_lab`
- `composite_packet`
- `interpreted_summary`
- `non_lab_medical`
- `unsupported`

No downstream stage may override this silently.

### 1.3 Document splitter

For `composite_packet`, split into logical page groups / subdocuments before extraction.

### 1.4 Page classifier

For each page or split segment, assign:

- `lab_results`
- `threshold_reference`
- `admin_metadata`
- `narrative_guidance`
- `interpreted_summary`
- `non_lab_medical`
- `footer_header`
- `unknown`

## 2) Parser substrates

Exactly two runtime parser backends.

### 2.1 Born-digital lane

Backend: PyMuPDF
Input: born-digital PDFs
Output: `PageParseArtifactV4`

### 2.2 Image/scanned lane

Backend: Qwen-OCR
Input: scanned PDFs, image PDFs, photos
Output: `PageParseArtifactV4`

### 2.3 Shared parser contract

Both lanes must emit the same shape:

- page text
- blocks
- reading order
- word / box geometry when available
- table-like structures when available
- language candidates
- parser lineage
- lane type
- page kind hint

No parser backend may emit observations directly.

## 3) Shared typed middle

This is the only extraction-to-normalization bridge.

### 3.1 Block graph builder

`PageParseArtifactV4 -> BlockGraphV1`

Allowed block roles:

- `result_block`
- `threshold_block`
- `admin_block`
- `narrative_block`
- `header_footer_block`
- `unknown_block`

### 3.2 Line classifier

Classifies fragments as:

- value-bearing
- continuation
- heading
- metadata
- threshold
- narrative
- unknown

No analyte mapping here.

### 3.3 Row grouping

Builds candidate rows using:

- geometry
- reading order
- block role
- continuation logic

Must support:

- multiline rows
- comparator-first rows
- dual-unit rows
- bilingual labels
- qualitative rows

Must forbid:

- giant hybrid rows
- heading-shadow rows
- threshold-table leakage into result rows

### 3.4 Row field parser

Produces `CandidateRowV3` fields:

- `raw_label`
- `raw_value`
- `raw_unit`
- `raw_reference_range`
- `parsed_numeric_value`
- `parsed_comparator`
- `parsed_locale`
- `secondary_result`

Must be locale-aware.

### 3.5 Row arbitration

Resolves overlap, duplicates, shadows, and block-local conflicts.
All suppressions must be typed and traceable.

## 4) Deterministic normalization core

### 4.1 Analyte candidate generation

Input: typed candidate row
Output: ranked analyte candidates

Uses:

- family config
- alias packs
- bilingual alias packs
- specimen / method context
- panel context
- unit compatibility

### 4.2 Analyte resolver

Deterministic acceptance / abstention.
Terminal states:

- `supported`
- `partial`
- `unsupported`
- `ambiguous`

No silent coercion.

### 4.3 Unit normalizer

UCUM-aware canonicalization and safe conversion.
Rules:

- convert only when explicitly supported
- preserve unit family
- reject unsafe conversions

### 4.4 Derived observation engine

For eGFR, ACR, ratios, etc.
Requires:

- formula id
- source observation ids
- explicit source eligibility

### 4.5 Threshold reconciliation

Preserve both:

- lab-printed reference
- policy threshold

If unresolved conflict exists, severity / next-step may be withheld.

### 4.6 Canonical observation contract

Output: `CanonicalObservationV3`

Must contain:

- provenance
- raw source fields
- parsed fields
- accepted analyte or abstention
- canonical value/unit
- support state
- suppression reasons
- source linkage

## 5) Policy core

Fully deterministic.

### 5.1 Panel reconstructor

Groups observations into supported panels.

### 5.2 Rule engine

Structured rules only.

### 5.3 Severity engine

Deterministic severity class assignment.

### 5.4 Next-step engine

Deterministic next-step class assignment.

No raw LLM reasoning in the truth path.

## 6) Artifact plane

### 6.1 Patient artifact

Must answer:

- what was found
- how serious it is
- what to do next
- what was not assessed
- why it was not assessed

Must never expose:

- raw parser garbage
- metadata rows
- threshold prose
- narrative fragments
- internal ids
- raw suppression codes

### 6.2 Clinician artifact

Compact, traceable, provenance-backed.

### 6.3 Optional explanation layer

LLM is downstream-only, bounded, and never source-of-truth.

## 7) Config system

All document-family behavior must live in versioned config, not inline parser code:

- family registry
- page/block hints
- analyte alias packs
- bilingual packs
- threshold vocab
- heading vocab
- qualitative vocab
- blocked admin/narrative phrases
- unit variant registry

Contracts are code. Family behavior is config.

## 8) Lineage and observability

Every run must record:

- source checksum
- lane
- parser backend + version
- row assembly version
- config versions
- terminology release
- unit engine version
- rule pack version
- artifact version
- benchmark metadata

## 9) Validation system

Acceptance oracle is ground truth, not "parsed successfully."

Every file in `pdfs_by_difficulty` must end in exactly one correct state:

- `fully_normalized_supported_lab_report`
- `partially_normalized_supported_lab_report`
- `ocr_normalized_supported_lab_report`
- `composite_packet_artifact`
- `interpreted_summary_artifact`
- `non_lab_medical_artifact`
- `unsupported_artifact`

Passing means:

- correct terminal state
- correct artifact type
- no leakage
- correct supported analytes where applicable

## 10) Hard rules

- One primary backend per lane.
- Legacy parser path is offline-only, never co-equal runtime truth.
- Renderer is not a cleanup engine.
- No direct raw-document-to-clinical-interpretation model path.
- No file-specific hacks in runtime code.
- If uncertain, abstain explicitly.

## Final one-line summary

Semantic router/splitter -> PyMuPDF or Qwen-OCR substrate -> shared typed block/row middle -> deterministic normalization and policy core -> production-safe artifacts -> ground-truth validation.