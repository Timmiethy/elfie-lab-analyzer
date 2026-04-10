# Labs analyzer for Elfie: parallel distribution plan v10
## Two-person parallel split with non-overlapping ownership

This document is not the product spec. The product spec lives in the source-of-truth blueprint. This document only defines who owns what, where the boundaries sit, what each side must produce, and which shared contracts must stay stable so both people can work at full speed without collision.

The split is simple on purpose.

- One side owns runtime truth.
- One side owns patient-visible trust.
- Shared contracts are the only intentional overlap.

---

## 0. working rules

1. The source-of-truth blueprint wins over every local design choice.
2. Each person owns one coherent vertical slice.
3. Shared contracts are versioned and example-driven.
4. No silent ownership drift across directories.
5. Backend truth beats UI convenience. UI honesty beats visual polish.
6. If a field is not in the contract, it does not exist.
7. If a feature crosses both slices, the contract changes first.
8. The patient artifact wins every tradeoff.
9. The trusted PDF lane wins every tradeoff.
10. Optional lanes never block the core proof.

---

## 1. top-level split

### Person A owns the truth engine

This side owns everything from input intake to structured findings and policy output.

Primary responsibility:
- turn a supported input into a correct, versioned, provenance-backed structured result

Core surfaces:
- input intake
- file validation and sanitization
- PDF parsing
- image beta extraction adapters
- extraction QA
- canonical observation schema
- analyte resolution
- terminology artifacts
- unit validation and conversion
- deterministic rules
- severity policy
- next-step policy
- lineage and reprocessing
- job semantics
- persistence
- API output payloads
- benchmark generation

Directory ownership:
- `app/api/*`
- `app/ingest/*`
- `app/parser/*`
- `app/image/*`
- `app/normalize/*`
- `app/terminology/*`
- `app/policy/*`
- `app/jobs/*`
- `app/db/*`
- `app/benchmarks/*`
- `tests/parser/*`
- `tests/normalize/*`
- `tests/policy/*`
- `tests/contracts_backend/*`

Person A does not own:
- patient screen composition
- localized UI copy
- visual states and accessibility styling
- patient report card layout
- clinician-share visual layout
- guided ask presentation
- screenshot regression assets

### Person B owns the patient surface

This side owns everything from structured payload to patient-visible experience.

Primary responsibility:
- turn structured findings into a readable, honest, accessible patient artifact without overstating certainty

Core surfaces:
- upload screen
- processing state machine
- patient report card
- support / partial-support / cannot-assess states
- threshold reconciliation presentation
- comparable-history card
- clinician-share surface
- multilingual rendering
- guided ask or static FAQ surface
- provenance drilldown presentation
- accessibility implementation
- screenshot and visual regression pack
- comprehension task surfaces

Directory ownership:
- `web/app/*`
- `web/screens/*`
- `web/components/*`
- `web/state/*`
- `web/styles/*`
- `web/i18n/*`
- `web/share/*`
- `web/accessibility/*`
- `tests/ui/*`
- `tests/accessibility/*`
- `tests/comprehension/*`
- `tests/visual/*`
- `fixtures/screens/*`

Person B does not own:
- parser logic
- OCR / image extraction internals
- analyte mapping
- terminology artifacts
- UCUM conversion
- rule execution
- severity tables
- next-step tables
- DB migrations
- benchmark generation logic beyond UI-facing harnesses

This split is deliberate.

Person A owns truth.
Person B owns trust.

---

## 2. shared contract zone

Only these files and schemas are shared by design.

Shared contract surfaces:
1. OpenAPI schema
2. canonical observation schema
3. finding schema
4. severity enum and payload shape
5. next-step enum and payload shape
6. support-state taxonomy
7. unsupported-reason taxonomy
8. patient artifact payload schema
9. clinician-share payload schema
10. comparable-history payload schema
11. lineage payload schema
12. language-key registry
13. benchmark result schema

Shared directory:
- `contracts/*`
- `contracts/examples/*`

Contract rules:
- every contract has a version
- every contract has at least one example payload
- every enum change updates example payloads first
- no implicit contract drift through backend-only or UI-only edits
- no shared schema may be changed without updating tests on both sides

---

## 3. hard ownership boundaries

### Person A may edit
- all backend runtime code
- data models
- migrations
- parsers
- policy tables
- API handlers
- fixture generators for backend payloads
- benchmark runners
- structured lineage output

### Person B may edit
- all frontend code
- UI state handling
- copy templates
- language packs
- share layouts
- accessibility fixes
- screenshot baselines
- comprehension-task UI flows
- provenance display components

### Forbidden overlap

Person A must not edit:
- `web/screens/*`
- `web/styles/*`
- `web/i18n/*`
- `web/share/layout/*`

Person B must not edit:
- `app/parser/*`
- `app/normalize/*`
- `app/policy/*`
- `app/db/migrations/*`
- `app/terminology/*`

### Allowed overlap

Only these may be edited by both sides:
- `contracts/*`
- `contracts/examples/*`
- `README.md`
- proof assets under `docs/proof/*` when they reference frozen outputs rather than change behavior

---

## 4. dependency map

### Person A can proceed independently on
- intake contract
- file sanitization
- parser baseline
- image beta intake classification
- extraction QA
- canonical observation schema draft
- terminology artifact loader
- analyte resolver
- UCUM layer
- rules
- severity tables
- next-step tables
- lineage model
- jobs and retries
- benchmark harness
- seeded API fixtures

### Person B can proceed independently on
- upload screen
- processing state machine
- patient report shell
- support-state banners
- partial-support rendering
- cannot-assess rendering
- threshold reconciliation component shell
- comparable-history shell
- clinician-share shell
- i18n framework
- accessibility shell
- screenshot baseline harness
- comprehension-task shell

### Person B depends on Person A for
- frozen payload shapes
- severity and next-step enums
- unsupported-reason taxonomy
- provenance fields
- comparable-history fields
- API examples

### Person A depends on Person B for
- no runtime dependencies

That asymmetry is intentional. The truth engine should not wait on the UI.

---

## 5. freeze points

These are not planning milestones. They are contract stabilization points.

### Freeze point 1: truth payload freeze
Required fields become stable for:
- observation payload
- finding payload
- severity enum
- next-step enum
- support-state enum

### Freeze point 2: patient artifact payload freeze
Required fields become stable for:
- report card sections
- what-was-found block
- seriousness block
- what-to-do-next block
- what-was-not-assessed block
- why block
- comparable-history card

### Freeze point 3: language-key freeze
Required fields become stable for:
- all UI strings
- support-state strings
- refusal strings
- threshold reconciliation strings
- share artifact strings

### Freeze point 4: proof metric freeze
Required fields become stable for:
- parser metrics names
- coverage metrics names
- patient-layer metrics names
- comprehension metrics names
- export artifact names

Downstream code should consume mocks until the relevant freeze point exists. Once frozen, mocks should match live payloads exactly.

---

## 6. interface contract between both sides

Person A must provide these artifacts for Person B:
- OpenAPI spec
- JSON examples for every major state
- supported input success example
- partial-support example
- cannot-assess example
- unsupported example
- threshold-conflict example
- comparable-history available example
- comparable-history unavailable example
- clinician-share payload example
- lineage example

Person B must provide these artifacts for Person A:
- rendering map for every support state
- language-key registry
- screen-to-payload field map
- UI-required enum labels
- export layout field usage map
- front-end fixture expectations

Neither side should infer missing fields from screenshots or mockups.

---

## 7. deliverables by person

### Person A final deliverables

1. Trusted PDF intake path
2. Image beta intake path with explicit non-trusted status
3. Sanitizer and rejection rules
4. Parser baseline
5. Extraction QA rules
6. Canonical observation builder
7. Terminology artifact loader
8. Analyte resolver
9. UCUM validator and converter
10. Deterministic findings engine
11. Deterministic severity engine
12. Deterministic next-step engine
13. Reprocessing and lineage model
14. Stable API payloads
15. Benchmark result generator
16. Seeded fixtures for UI states
17. Unit and integration tests for the truth engine

### Person B final deliverables

1. Upload screen with honest support boundary
2. Processing screen with explicit support checks
3. Patient report card for supported cases
4. Partial-support and cannot-assess states
5. Threshold reconciliation UI
6. Comparable-history card with neutral wording
7. Clinician-share surface
8. Provenance drilldown surface
9. Launch-language rendering
10. Guided ask or FAQ surface if allowed by contract
11. Accessibility-compliant rendering
12. Screenshot and visual baselines
13. UI and comprehension tests for all visible states

---

## 8. proof-critical path vs non-blocking path

### Proof-critical for Person A
- trusted PDF lane
- parsing
- normalization
- rules
- severity
- next-step policy
- API payloads
- benchmarks

### Non-blocking or degradable for Person A
- image beta promotion logic
- optional empirical mapping challenger
- advanced export polish

### Proof-critical for Person B
- upload honesty
- report card
- support-state visibility
- what-to-do-next block
- what-was-not-assessed block
- accessibility
- launch-language pack

### Non-blocking or degradable for Person B
- guided ask
- secondary language packs
- advanced provenance polish
- clinician-share visual refinement beyond baseline scannability

If there is pressure, non-blocking surfaces collapse first. The patient report card does not.

---

## 9. tests owned by each side

### Person A owns tests for
- file sanitization
- parser extraction
- out-of-layout rejection
- analyte mapping
- UCUM validation
- policy firing
- severity assignment
- next-step assignment
- lineage completeness
- API schema compliance
- benchmark artifact generation

### Person B owns tests for
- screen state rendering
- support-state visibility
- threshold reconciliation visibility
- accessibility
- launch-language string coverage
- patient artifact completeness
- clinician-share rendering
- comparable-history visibility rules
- comprehension-task rendering
- visual regression

### Shared contract tests
- payload examples validate against schema
- frontend fixtures validate against schema
- all enums render a visible user-facing state when required
- unsupported reasons are not silently dropped in the patient UI

---

## 10. failure containment

### If Person A is late
- image beta remains preview-only or disabled
- optional mapping challenger remains off
- clinician-share export may stay plain HTML
- only trusted PDF lane is required for proof

### If Person B is late
- guided ask drops to static FAQ
- secondary language packs remain off
- provenance stays simple but visible
- clinician-share styling stays minimal
- patient artifact remains the only must-polish surface

### If contracts churn too often
- freeze contracts
- move all extras out of the active proof
- reject any new field not tied to a required output artifact

---

## 11. acceptance check for non-conflict

The split is correct only if all of the following remain true:

1. Person A can finish the full truth engine without touching UI directories.
2. Person B can build every visible state from fixture payloads before live binding.
3. Contract changes are rare, explicit, and versioned.
4. No one needs to edit the other side's core directories to unblock progress.
5. The patient artifact can ship even if the image beta lane, guided ask, and extra language packs are off.

If any of these stop being true, the split is wrong and the contract needs to be tightened.

---

## 12. shortest true summary

Person A builds the system that decides what can be trusted.
Person B builds the system that shows that trust honestly to a patient.
The contract layer is the only handshake.
