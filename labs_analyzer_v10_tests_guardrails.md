
# Labs analyzer for Elfie: unit tests and guardrails v10
## The proof fails fast. It does not "mostly work."

This document defines the test surface and guardrails for the proof. The point is not to make the suite large. The point is to make every silent failure impossible.

---

## 0. hard stop guardrails

The build is red if any of these happen:

1. unsupported input renders as fully supported
2. unsupported rows disappear from the patient artifact
3. out-of-layout documents produce any supported-seeming finding
4. model output changes a value, severity, or next step
5. severity or next-step is assigned without the required context
6. threshold conflicts are not visible when present
7. image beta output is promoted to trusted without passing the trusted gates
8. mixed-language unsupported rows are hidden
9. clinician-share artifact omits unsupported content
10. lineage bundle is incomplete
11. S4/A4 appears without an approved critical-value rule source
12. explanation emits blocked content classes
13. the support banner is missing on any result screen
14. the longitudinal card says improving/worsening
15. there is no deterministic fallback when explanation fails

---

## 1. unit test families

### 1.1 Input and sanitization tests
Cases:
- valid machine-generated PDF
- password-protected PDF
- corrupted PDF
- image-only PDF
- png upload
- jpeg upload
- file too large
- page count too high
- duplicate checksum
- MIME mismatch

Assertions:
- lane classification correct
- rejection reason correct
- no parser invocation on hard reject
- duplicate behavior deterministic

### 1.2 Parser tests
Cases:
- one-row-per-line table
- merged rows
- wrapped analyte names
- repeated header rows
- empty pages
- header only
- mixed table and free text
- supported layout family A/B/C
- out-of-layout negative

Assertions:
- row extraction precision
- row extraction recall
- page support decision
- no false support on negative layout

### 1.3 OCR / image beta tests
Cases:
- screenshot
- clean camera photo
- rotated image
- blurred image
- cropped image
- multilingual image
- glare / shadow case
- portal screenshot with tiny text

Assertions:
- lane stays beta
- preview allowed only when thresholds pass
- false trusted promotion impossible
- preview copy states correct
- fallback copy present

### 1.4 Mapping tests
Cases:
- straightforward label match
- ambiguous synonym
- context-disambiguated synonym
- wrong unit trap
- method-specific distinction
- must-abstain label
- multilingual alias
- panel-context disambiguation

Assertions:
- accepted code correct
- abstention correct
- score threshold honored
- candidate list persisted
- wrong-unit cases abstain

### 1.5 UCUM and conversion tests
Cases:
- exact canonical unit
- safe conversion
- unsupported unit
- malformed unit
- dimension mismatch
- thousand-separator locale issue
- comma decimal locale issue

Assertions:
- canonical value correct
- malformed unit rejected
- unsafe conversion rejected
- locale parsing correct

### 1.6 Reference-range reconciliation tests
Cases:
- printed range and policy agree
- printed range wider than policy
- printed range narrower than policy
- printed range missing
- printed range contradictory
- policy requires age/sex and overlay missing

Assertions:
- provenance sentence present
- conflict visible
- severity suppressed where required
- printed range still shown when available

### 1.7 Rule tests
Cases:
- single glycemia flag
- multiple lipid findings
- kidney finding with overlay present
- kidney finding with overlay missing
- incomplete panel
- contradictory data
- all reviewed and not flagged
- unsupported analyte in same report

Assertions:
- expected finding ids
- expected suppressions
- no unsupported analyte leaks into finding set

### 1.8 Severity policy tests
Cases:
- one finding per severity class
- multiple findings, precedence resolution
- missing context demotion
- threshold conflict suppression
- urgent class allowed case
- urgent class forbidden case

Assertions:
- exact severity id
- exact suppressions
- urgent gating enforced

### 1.9 Next-step policy tests
Cases:
- each severity class to next-step mapping
- action suppressed when context missing
- locale-specific copy key exists
- disallowed wording absent

Assertions:
- exact next-step id
- allowed copy key present
- blocked copy absent

### 1.10 Explanation adapter tests
Cases:
- standard finding set
- partial-support case
- unsupported-heavy case
- threshold conflict case
- multilingual enabled pack
- blocked intent prompt injection attempt

Assertions:
- schema valid
- facts grounded
- no new values
- no diagnosis statement beyond allowed template
- fallback template available

### 1.11 Longitudinal tests
Cases:
- same analyte comparable
- unit conversion comparable
- method mismatch
- specimen mismatch
- missing prior value
- unsupported prior value

Assertions:
- card visibility correct
- wording is neutral
- trend unavailable shown when needed
- no improving/worsening language

### 1.12 UI state tests
Cases:
- full support
- partial support
- unsupported
- image beta preview
- threshold conflict
- missing context
- mixed language
- explanation fallback

Assertions:
- support banner present
- unsupported section visible
- severity banner visible
- next-step section visible or safely suppressed
- provenance CTA visible
- color is not the only meaning channel

### 1.13 Clinician-share tests
Cases:
- straightforward supported report
- partial-support report
- threshold conflict report
- unsupported-heavy report

Assertions:
- top findings present
- unsupported visible
- support coverage visible
- QR/link present if configured
- report length bounded

---

## 2. integration tests

### 2.1 Trusted PDF path integration
Input:
- one supported PDF fixture

Assertions:
- upload accepted
- rows extracted
- observations normalized
- rules fired
- patient artifact rendered
- clinician-share artifact rendered
- lineage bundle complete

### 2.2 Partial-support integration
Input:
- one supported PDF with unsupported rows

Assertions:
- reviewed rows shown
- unsupported rows shown
- no unsupported row counted as reviewed
- patient artifact says partial support

### 2.3 Unsupported integration
Input:
- image-only PDF or corrupt PDF

Assertions:
- user gets unsupported state
- no findings emitted
- retry guidance shown

### 2.4 Image beta integration
Input:
- screenshot / camera photo

Assertions:
- preview or retry only
- never trusted unless full gates pass
- beta label visible

### 2.5 Multilingual integration
Input:
- English pack, Vietnamese pack

Assertions:
- all required strings resolve
- severity labels correct
- next-step labels correct
- unsupported and cannot-assess copy present
- language tag persisted

---

## 3. accessibility and UX guardrails

### 3.1 Accessibility checks
- contrast ratios
- keyboard navigation where applicable
- focus order
- screen-reader names
- icon + text for severity
- no information conveyed by color alone
- tap target minimums

### 3.2 UX honesty checks
- upload screen does not promise image parity
- result screen always shows support state
- "reviewed and not flagged" never becomes "normal" on partial-support cases
- threshold conflicts always surfaced
- missing demographics are called out when they suppress findings
- guided ask does not expose blocked intent routes

### 3.3 Patient-comprehension checks
For each task case:
- can user identify what was flagged
- can user identify severity
- can user identify next step
- can user identify what was not assessed
- can user explain why a finding was flagged

Record:
- accuracy
- wrong-confidence
- time to answer

---

## 4. performance guardrails

### 4.1 Trusted PDF lane
- upload accept latency target
- parse latency target
- artifact render latency target
- no OOM on declared page limit

### 4.2 Image beta lane
- preview latency tracked separately
- if latency exceeds budget, lane remains beta-only and off in public demo

### 4.3 UI render
- patient artifact first meaningful paint within target on a mid-tier phone profile
- clinician-share export within target

---

## 5. benchmark artifacts

The proof pack must contain machine-readable outputs:

- `parser_report.json`
- `mapping_report.json`
- `policy_report.json`
- `coverage_report.json`
- `explanation_report.json`
- `patient_comprehension_report.json`
- `partial_support_report.json`
- `clinician_scan_report.json`
- `ablation_report.json`

Each report includes:
- build commit
- lineage version ids
- corpus id
- lane id
- language id
- timestamp

---

## 6. synthetic and adversarial validation corpus

### 6.1 Synthetic documents
Use generated fixtures for:
- reordered columns
- merged header rows
- empty ranges
- localized decimals
- missing units
- duplicated analyte names
- conflicting ranges
- unsupported analytes

### 6.2 Adversarial documents
Use designed traps for:
- same label, wrong specimen
- same label, wrong method
- misleading unit
- truncated value
- mixed-language rows
- fake table lines
- low-quality screenshot with one readable analyte that should still stay preview-only

### 6.3 UX adversarial cases
- partial-support case with many green reviewed rows
- unsupported-heavy case that tempts the UI to look "mostly fine"
- threshold-conflict case where the printed range suggests normal
- no-overlay case where the patient expects a kidney interpretation
- multilingual case where translation fallback fires

---

## 7. regression matrix

Every accepted bug becomes:
- one fixture
- one test
- one report-row tag

Regression tags:
- parser
- mapping
- units
- policy
- severity
- next-step
- explanation
- multilingual
- image-beta
- patient-visibility
- clinician-share
- lineage

---

## 8. proof-critical stop/go summary

Go only if:
- trusted PDF lane passes all hard gates
- patient artifact passes comprehension gates in launch languages
- out-of-layout false support is zero
- unsupported visibility omission is zero
- S4/A4 logic is signed off or disabled
- explanation has deterministic fallback
- lineage is complete

Stop or downgrade if:
- image beta is noisy
- multilingual pack fails
- partial-support misread rate too high
- benchmark corpus too thin for claimed tier

---

## 9. shortest true summary

The tests are not here to prove the feature works.  
They are here to prove the feature does not lie.
