
# Labs Analyzer source of truth v11
## Normalization-first architecture after adversarial failure review

This document replaces the weak parts of v10 that were exposed by a real failure on `seed_innoquest_dbticbm.pdf`.

The problem is not that the trusted path is wrong.
The problem is that the current trusted path is still too loose before normalization and too coarse after normalization failure.

The failure on the attached output is clear:
- a text PDF was parsed
- obvious analyte rows were visible
- no supported rows were produced
- admin metadata, narrative guidance, and threshold tables leaked into "What was not assessed"
- many true lab rows were demoted into a catch-all `insufficient_support`

That means the pipeline is still failing at the boundary between extraction and normalization, not at the deterministic rule layer.

This source of truth does four things:

1. preserves the strongest part of the prior architecture: normalization before interpretation
2. replaces catch-all failure handling with typed support-state codes
3. inserts a stricter row-construction and row-typing protocol before analyte mapping
4. adds concrete acceptance gates for parsability, observation construction, normalization, and leak prevention

---

## 0. Core axiom

Clarity, robustness, well-proven over complexity. Keep the deterministic reasoning core. Fix the messy edges before it. fileciteturn16file7

The runtime truth boundary remains:

- extraction is empirical
- row assembly is rule-bounded and testable
- analyte mapping is auditable hybrid software with abstention
- unit semantics, panel reconstruction, rules, severity, and next-step assignment are deterministic
- explanation is downstream and never sets findings, severity, or next steps

---

## 1. Failure statement

### 1.1 Observed failure

The attached result artifact for `seed_innoquest_dbticbm.pdf` shows:
- "No supported rows were flagged"
- metadata fields like `Ref`, `DOB`, `Collected`, and `Report Printed` listed as `insufficient_support`
- real analytes like `Sodium 钠`, `Creatinine 肌酸酐`, `Glucose 葡萄糖`, `HbA1c 葡萄糖血红蛋白`, `Urine Albumin`, and `Urine Creatinine` also listed as `insufficient_support`
- narrative and threshold-table text like `Normal`, `IFG (Prediabetes)`, `KDIGO`, and guideline sentences also listed as `insufficient_support` fileciteturn20file0

This is not acceptable behavior for a supported text PDF.

### 1.2 What this failure proves

It proves at least one of the following is true:
- row construction is not stable enough to join bilingual labels, values, and units into a single observation candidate
- row typing is too permissive and allows admin / narrative / threshold rows into the observation pool
- analyte mapping gates are too coarse and demote valid rows into a generic fallback state
- numeric and unit extraction are too brittle for comparator-first rows and dual-value rows
- the user-facing "What we did not assess" list is showing internal debug rejects that should never surface to patients

### 1.3 What it does not prove

It does not prove the deterministic rule engine is wrong.
It does not prove the patient artifact concept is wrong.
It does not prove the trusted PDF lane is wrong.

It proves the architecture between parser output and canonical observation construction is still under-specified.

---

## 2. Final goal outputs

The pipeline is correct only if it can produce all of the following.

### 2.1 Runtime outputs

1. **Canonical observations**
   - one row per accepted measurement or accepted derived observation
   - typed support state
   - typed provenance trace
   - typed unit semantics
   - typed threshold provenance

2. **Findings packet**
   - deterministic findings
   - deterministic severity
   - deterministic next-step class
   - typed suppression reasons where needed

3. **Patient artifact**
   - what was found
   - how serious it is
   - what to do next
   - what was not assessed
   - why each supported result was flagged or not flagged

4. **Clinician share artifact**
   - compact finding summary
   - support coverage
   - what was not assessed
   - drilldown provenance link or appendix

### 2.2 Required debug outputs

These are required even in proof mode.

1. **Parser trace**
   - page classifier decision
   - block classifier decision
   - row-construction decisions
   - family adapter used
   - extraction QA metrics

2. **Normalization trace**
   - raw row text
   - row type
   - parsed label/value/unit/range fields
   - locale normalization result
   - analyte candidates and scores
   - accepted analyte or abstain
   - unit validation result
   - derived-observation linkage where used

3. **Suppression report**
   - exact typed reason code
   - whether suppression is user-visible
   - whether suppression is debug-only

### 2.3 Forbidden outputs

The system must never:
- show admin metadata as a patient-facing unsupported lab row
- show guideline narrative as a failed analyte
- show threshold-table rows as failed analytes
- collapse every failure into `insufficient_support`
- generate a finding without a canonical observation
- generate severity or next-step from an LLM

---

## 3. Support boundary

### 3.1 Trusted PDF lane

Trusted means:
- machine-generated PDF
- supported family or supported generic row grammar
- row-construction gates passed
- normalization gates passed
- no OCR in the trusted path

### 3.2 OCR / image beta lane

Beta means:
- image-only or OCR-required document
- preview-only unless it passes the same row-construction and normalization gates as the trusted lane
- no silent promotion into trusted
- separate metrics, separate kill switch, separate support label

### 3.3 Explicitly unsupported

Unsupported means:
- password-protected or corrupt PDF
- encrypted file without unlock path
- page family not supported
- image/OCR preview that does not pass promotion gates
- document type not a raw lab result packet
- narrative-only pathology or imaging packet without row-level lab structure
- synthetic interpreted reports used as source documents

---

## 4. Ingestion architecture

### 4.1 Preflight contract

Before parsing:
- verify file type and extension
- verify not password-protected
- verify not corrupt
- compute checksum
- classify document as text-capable PDF, image-heavy PDF, mixed, or unsupported
- record duplicate detection

### 4.2 Page classifier

Every page must be classified before row parsing.

Allowed page types:
- raw lab table page
- threshold interpretation table page
- narrative note page
- admin header/footer page
- mixed page
- non-lab medical page
- already-interpreted summary page

A page marked `non-lab medical page` or `already-interpreted summary page` is not sent into the trusted row parser.

### 4.3 Block classifier

Inside each page:
- segment header
- segment footer
- segment patient/admin metadata
- segment analyte table
- segment threshold table
- segment explanatory narrative
- segment tests-requested block

Only analyte-table blocks and approved dual-purpose result blocks may feed the canonical observation builder.

### 4.4 Family adapter registry

Each supported family has:
- family id
- anchor patterns
- row grammar
- unit grammar
- known bilingual aliases
- known threshold-table signatures
- known narrative boilerplate signatures

The registry may include:
- `innoquest_bilingual_general`
- `quest_standard`
- `labcorp_standard`

The generic parser exists, but it is second priority to a matching family adapter.

---

## 5. Row construction protocol

This section is the load-bearing fix.

### 5.1 Problem

In the Innoquest PDF, English analyte label, Chinese alias, numeric value, unit, and range do not all sit on exactly one baseline. The document is text-extractable, but the row is visually one row and textually several micro-rows.

Examples from direct inspection:
- `Sodium` label, `钠` alias, `141`, `mmol/L`, and `(135-145)` live on nearby but not identical y positions
- `HbA1c` has two measured values on one result line: `%` and `mmol/mol`
- `ACR` puts the comparator before the numeric value: `< 0.1 mg Alb/mmol`
- eGFR has a measured value line followed by narrative classification lines
- glucose and HbA1c pages include interpretation tables that look structurally similar to result rows

### 5.2 Row assembly algorithm

Row assembly is not string splitting. It is a geometry + grammar step.

Steps:
1. extract words with coordinates
2. cluster words into micro-lines by y proximity
3. merge adjacent micro-lines into a candidate row window using:
   - x-column expectations
   - family adapter grammar
   - bilingual label patterns
   - allowed y drift per family
4. emit a candidate row object with typed fields, not just free text

### 5.3 Candidate row object

Each candidate row must have:
- page id
- block id
- row id
- raw text
- label tokens
- alias tokens
- value tokens
- unit tokens
- reference tokens
- comparator tokens
- trailing note tokens
- x/y bounds
- block type
- family adapter id
- row confidence

### 5.4 Row types

Every candidate row must be typed before normalization.

Allowed row types:
- measured analyte row
- derived analyte row
- threshold reference row
- narrative guidance row
- admin metadata row
- footer/header row
- tests-requested row
- unsupported row

Only `measured analyte row` and `derived analyte row` may enter canonical observation construction.

### 5.5 Leak prevention

The following rows must be rejected before normalization:
- `DOB :`
- `Collected :`
- `Report Printed :`
- `Source:`
- `Normal`
- `IFG (Prediabetes)`
- `KDIGO 2012 Albuminuria Categories`
- `Result should be interpreted alongside clinical presentation`
- `Tests Requested`

If any of these appear in patient-facing "What we did not assess", the build fails.

---

## 6. Locale and value parsing protocol

This section is new and mandatory.

### 6.1 Locale parser

The parser must normalize:
- decimal point and decimal comma
- thousands separators
- inequality prefixes: `<`, `>`, `<=`, `>=`
- range dashes: `-`, `–`, `to`
- mixed whitespace
- superscript/subscript loss
- unit typography variants
- date formats affecting longitudinal order

### 6.2 Value channels

Each row may contain up to four value channels:
- primary measured value
- secondary measured value
- printed reference range
- policy threshold table values

These channels must never be merged.

Examples:
- HbA1c row: primary measured value = `5.2%`, secondary measured value = `33 mmol/mol`
- ACR row: primary measured value = `< 0.1 mg Alb/mmol`, printed range = `< 3.5`
- glucose interpretation table: threshold table only, not measured value
- HbA1c category table: threshold table only, not measured value

### 6.3 Parsed numeric contract

Each parsed numeric field must store:
- raw token string
- normalized comparator
- normalized numeric value
- scale if relevant
- parse confidence
- parse locale

### 6.4 Parse failure codes

Forbidden catch-all:
- `insufficient_support`

Required typed failure codes:
- `admin_metadata_row`
- `narrative_row`
- `threshold_table_row`
- `footer_or_header_row`
- `unreadable_value`
- `unit_parse_fail`
- `mixed_measurement_and_threshold_row`
- `bilingual_label_unresolved`
- `ambiguous_analyte`
- `unsupported_family`
- `missing_overlay_context`
- `derived_observation_unbound`
- `specimen_or_method_conflict`
- `out_of_policy_scope`

Patient-facing UI may collapse some of these into plain language. Internal traces may not.

---

## 7. Canonical observation protocol

### 7.1 Observation contract

Each accepted canonical observation must include:
- source document id
- source page
- source block id
- source row id
- row type
- raw analyte label
- raw alias label if present
- raw value string
- raw unit string
- raw printed reference range
- parsed comparator
- parsed numeric value
- parsed locale
- specimen context
- method context
- candidate analytes with scores
- accepted analyte id
- accepted analyte family
- canonical unit
- canonical value
- measurement kind
- support state
- suppression reason list
- lineage version bundle

### 7.2 Measurement kinds

Allowed kinds:
- `direct_measurement`
- `derived_measurement`
- `qualitative_measurement`
- `threshold_reference`
- `narrative_context`

Only the first three may feed patient findings.

### 7.3 Derived-observation contract

Derived observations must be explicit.

Required fields:
- derived formula id
- source observation ids
- formula version
- derivation prerequisites met
- derivation suppression reasons

Examples:
- eGFR
- ACR
- ratio values
- future delta statistics

No derived value may appear without source links.

### 7.4 Dual-unit observations

A single analyte may carry multiple valid result expressions.

Examples:
- HbA1c NGSP `%`
- HbA1c IFCC `mmol/mol`

Rules:
- one clinical analyte id
- multiple result expressions allowed
- one primary display per locale/policy pack
- secondary expression preserved
- no duplicate finding generation from the two expressions

---

## 8. Analyte resolver protocol

### 8.1 Resolver inputs

Resolver inputs must include:
- normalized label tokens
- alias tokens
- bilingual stripped tokens
- specimen
- method
- unit
- panel header
- family adapter id
- language id
- local terminology snapshot
- local curated alias table

### 8.2 Matching stages

Stage 1: family adapter hard filters  
Stage 2: lexical candidate generation  
Stage 3: bilingual alias normalization  
Stage 4: specimen and method compatibility check  
Stage 5: unit compatibility check  
Stage 6: derived-vs-direct compatibility check  
Stage 7: thresholded accept or abstain

### 8.3 Hard negative rules

The resolver must abstain when:
- specimen conflicts with candidate analyte
- direct and calculated analytes are both plausible and unresolved
- multiple analytes share the same friendly name but method/scale differs and context is missing
- the row type is not `measured analyte row` or `derived analyte row`

### 8.4 Family-level reporting

Benchmark output must report:
- precision by analyte family
- recall by analyte family
- abstention rate by analyte family
- top confusion pairs by analyte family

Global averages are not enough.

---

## 9. Unit semantics and normalization

### 9.1 UCUM policy

Unit handling is semantic, not cosmetic. The system must validate unit meaning before conversion. Wrong unit acceptance is a build-failing error.

### 9.2 Conversion contract

Each accepted conversion stores:
- raw unit
- normalized UCUM form
- conversion formula id
- conversion coefficient or rule id
- output unit
- conversion confidence
- conversion warnings

### 9.3 Special cases

The following require explicit fixtures:
- `umol/L` vs typography variants
- `mL/min/1.73m2`
- `mg Alb/mmol`
- `%` and `mmol/mol` dual-channel HbA1c
- qualitative urine result units if later added

---

## 10. Deterministic reasoning core

This remains the same in principle.

### 10.1 Rule engine

Rules only consume accepted canonical observations.

Each rule must store:
- rule id
- finding id
- support criteria
- supporting observation ids
- threshold source
- suppression conditions

### 10.2 Severity policy

Closed table only.
No LLM.
No guessed urgency.

### 10.3 Next-step policy

Closed table only.
No medication advice.
No diagnosis claim.
If context is insufficient, emit `AX cannot suggest safely`.

### 10.4 Reference range reconciliation

Three sources may exist:
- printed lab range
- deterministic policy threshold
- patient-overlay-dependent threshold

Behavior:
- always expose printed range if present
- expose policy threshold if used
- if they conflict, say so
- if unresolved, suppress severity and next-step

---

## 11. User-visible unsupported policy

### 11.1 Patient-visible unsupported list

The patient-visible list may include only:
- unsupported analytes
- unsupported units
- unreadable rows
- missing context required for a specific policy
- unresolved threshold conflict
- unsupported image preview rows

It may not include:
- admin metadata
- narrative guideline text
- threshold-table categories
- footer/header text
- test-request lists

### 11.2 Coverage display

The artifact must show:
- reviewed rows count
- supported result rows count
- unsupported result rows count
- rows excluded because they were not result rows

The last count is debug-visible and optionally clinician-visible, not patient-primary.

---

## 12. Concrete fixes for the `seed_innoquest_dbticbm.pdf` class

This class needs explicit handling.

### 12.1 Adapter behavior

The `innoquest_bilingual_general` family adapter must:
- merge English label + Chinese alias + value + unit + range across small y drift
- recognize result pages separately from interpretation tables
- recognize threshold tables on glucose and HbA1c pages
- classify page 3 ACR lines as urine chemistry results, not narrative
- keep patient/admin header data out of the observation pool

### 12.2 Expected accepted rows

For this document, the trusted path should at minimum construct canonical observations for:
- Sodium
- Potassium
- Chloride
- Urea
- Creatinine
- eGFR
- Uric Acid
- AST
- ALT
- Glucose
- HbA1c
- Urine Albumin
- Urine Creatinine
- ACR

### 12.3 Expected non-observation rows

The trusted path should not attempt to normalize:
- KDIGO explanatory narrative
- glucose category table rows
- HbA1c category table rows
- patient header fields
- footer and page counters
- "Tests Requested" block

### 12.4 Hard failure rule

If a supported family adapter sees a row with:
- analyte label present
- numeric value present
- unit present or known unit-optional exception
and still emits generic unsupported,
the build fails.

---

## 13. Benchmark and release gates

### 13.1 Parser and row-construction

Required gates on supported families:
- block classifier accuracy >= 0.99 for admin/narrative vs analyte blocks
- result-row type precision >= 0.99
- result-row type recall >= 0.97
- row assembly F1 >= 0.97
- admin/narrative leak rate into observation pool == 0 on gold fixtures

### 13.2 Normalization

Required gates:
- accepted analyte precision >= 0.98
- accepted analyte recall >= 0.95 on supported analyte families
- accepted-observation coverage >= 0.95 on supported families
- zero unsafe unit false accepts
- dual-unit handling accuracy == 1.00 on HbA1c fixtures
- comparator parsing accuracy == 1.00 on ACR-style fixtures
- derived-observation linkage accuracy == 1.00 on eGFR/ACR fixtures

### 13.3 Family-level gates

Every launch family must clear:
- family precision >= 0.97
- family recall >= 0.93
- family abstention rate below declared family budget
- top confusion pairs reviewed

### 13.4 Image beta

Because this lane is weaker:
- false trusted promotion == 0
- preview false support == 0
- OCR row linkage F1 declared and measured separately
- preview usefulness must be measured separately from trusted correctness

### 13.5 Patient artifact

Required gates:
- no patient-facing unsupported item may be admin or narrative text
- unsupported reason text must map from typed reason codes
- severity agreement >= 0.95
- next-step agreement >= 0.95
- patient five-question comprehension >= declared threshold on gold cases
- patient partial-support misread rate <= declared threshold

---

## 14. Reprocessing and lineage

Reprocess on any change to:
- family adapter
- row assembly logic
- row-type classifier rules
- locale numeric parser
- alias tables
- terminology snapshot
- UCUM engine
- conversion rules
- derived formula table
- deterministic rules
- severity table
- next-step table
- template pack

The lineage bundle must include:
- parser version
- adapter version
- row assembly version
- row-type rule set version
- terminology version
- unit engine version
- formula version
- rule version
- severity version
- next-step version
- template version
- document checksum

---

## 15. Fixing guide

### 15.1 Immediate patch order

1. remove generic `insufficient_support` from internal code paths
2. implement typed row types before analyte mapping
3. implement typed support-state codes
4. add family adapter for `innoquest_bilingual_general`
5. add locale numeric parser
6. add dual-unit observation support
7. add derived-observation contract
8. hard-fail patient-facing leaks of metadata/narrative rows
9. add family-level normalization reports
10. add explicit fixtures for comparator-first rows and threshold-table leakage

### 15.2 Non-negotiable tests to write first

- `test_admin_rows_never_enter_observation_pool`
- `test_threshold_table_rows_never_surface_as_unassessed_labs`
- `test_innoquest_bilingual_row_merge_sodium`
- `test_innoquest_hba1c_dual_unit_result`
- `test_innoquest_acr_comparator_first_value`
- `test_egfr_row_kept_and_guideline_note_rejected`
- `test_patient_artifact_never_shows_DOB_as_unassessed_lab`
- `test_generic_insufficient_support_forbidden`
- `test_locale_decimal_comma_parser`
- `test_derived_observation_requires_source_links`

### 15.3 Build stop conditions

Stop the build if any of these occur:
- a supported text PDF yields zero accepted observations when the gold set expects accepted rows
- a patient-visible artifact shows admin metadata as "not assessed"
- a threshold-table row is shown as a failed lab result
- dual-unit rows create duplicate findings
- comparator-first values lose the comparator
- the image lane is silently promoted
- a new adapter improves one family and degrades another without benchmark evidence

---

## 16. Self-debate

### 16.1 Objection: this is too strict and will reduce coverage

Yes. That is intentional.
False normalization is worse than explicit abstention.
Coverage must rise by improving row construction and family adapters, not by loosening acceptance gates.

### 16.2 Objection: a generic parser should be enough for a text PDF

No.
The failure on `seed_innoquest_dbticbm.pdf` shows why.
Text extractability is not the same as canonical row structure.
Bilingual labels, micro-baseline drift, dual-value rows, and threshold tables all break naive line-based parsing.

### 16.3 Objection: typed failure codes are too much work

No.
The attached artifact proves the opposite.
A single catch-all `insufficient_support` destroyed both debuggability and patient trust. fileciteturn20file0

### 16.4 Objection: the strongest part was the deterministic rule engine, not normalization

Wrong.
The deterministic rule engine only matters after correct canonical observations exist.
This failure happened before the rule engine had anything trustworthy to consume.

### 16.5 Objection: why not let the LLM repair row extraction mistakes

Because this is exactly the wrong place to trade determinism for guesswork.
The LLM may assist in beta preview or offline labeling. It may not set trusted values, severity, or next steps.

### 16.6 Final judgment

The original strongest idea survives:
normalize first, interpret second.

The architecture update is not a rewrite.
It is a hardening pass around the exact place the real failure happened:
candidate row construction, row typing, locale parsing, dual-value handling, and typed suppression.

---

## 17. Minimal claim after this update

The runtime claim is now:

"We can take a supported machine-generated lab PDF, separate result rows from metadata and narrative text, construct canonical observations with typed provenance and typed support states, assign deterministic findings / severity / next-step classes, and refuse anything that does not meet those gates."

That is a claim worth defending.
