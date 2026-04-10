
# Labs analyzer for Elfie: source-of-truth blueprint v10
## Patient lab understanding as a Health Report extension, not a standalone lab app

This document is the build contract. It defines the product boundary, runtime anatomy, trust model, UX contract, data contracts, validation gates, and proof artifacts. It does not assign work to agents. It does not describe daily plans. It names the thing that must exist, how it must behave, what may not happen, and how the result will be judged.

The system being built is:

- a patient-facing lab understanding feature
- embedded into Elfie's existing Health Report / My Health / share surfaces
- strict about support boundaries
- explicit about what was reviewed, what was not reviewed, and why
- deterministic where claims are made
- multilingual only where templates are validated
- image-aware but honest about the weaker trust level of image input
- longitudinal only where the result is comparable

The strongest accurate sentence stays the same:

**The reasoning core is deterministic.  
Extraction is empirical.  
Mapping is auditable hybrid software.  
Explanation is bounded and downstream.**

That statement governs every architecture and UX choice below.

---

## 0. meta-protocol

### 0.1 Goal lock

Build a proof that can do six things well enough to be credible inside Elfie's current product shape:

1. Accept a supported lab input and reject unsupported input loudly.
2. Turn supported input into a structured lab result set with provenance.
3. Assign a small number of patient-relevant findings using deterministic rules, deterministic severity classes, and deterministic next-step classes.
4. Render a patient artifact that answers five questions clearly:
   - what did you find
   - how serious is it
   - what should I do next
   - what did you not assess
   - why did you say this
5. Fit naturally into Elfie's current customer flow: Home / My Health / Health Report / export / share / family support / rewards-neutral follow-up.
6. Produce a proof pack with hard evidence, not only a polished demo.

### 0.2 Final output definitions

The proof is complete only if all of the following artifacts exist and pass their gates:

1. **Trusted patient artifact**
   - input accepted or refused explicitly
   - structured results for supported rows
   - flagged findings
   - deterministic severity class
   - deterministic next-step class
   - "what we did not assess"
   - provenance drilldown
   - language-tagged output
   - support coverage line

2. **Clinician-share artifact**
   - one-page, scan-friendly
   - top findings
   - severity classes
   - next-step classes
   - unsupported / suppressed items
   - deep link or annex for provenance
   - readable in under 10 seconds

3. **Normalization trace**
   - source row
   - extracted fields
   - mapped analyte
   - raw unit
   - canonical unit
   - threshold source
   - rule identifiers
   - suppression reason if any

4. **Benchmark pack**
   - parser report
   - mapping report
   - rule / severity / next-step report
   - coverage report
   - explanation fidelity report
   - patient comprehension report
   - partial-support misread report
   - clinician scan-time report
   - ablation report

5. **Demo pack**
   - one trusted PDF path
   - one partial-support path
   - one unsupported path
   - one image-beta preview path
   - one longitudinal comparable-history path
   - one multilingual path in each launch language

6. **Lineage bundle**
   - source checksum
   - parser version
   - OCR version if image lane used
   - terminology release
   - mapping threshold config
   - unit engine version
   - rule pack version
   - severity policy version
   - next-step policy version
   - template version
   - model version
   - build commit

### 0.3 Proof tiers and downgrade ladder

External dependencies are real. The blueprint therefore has an explicit downgrade ladder.

**Tier P0: full proof**
- 30 to 50 real reports
- 20 row-labeled parser gold documents
- 300 mapping-labeled rows
- 30 rule / severity / next-step labeled cases
- English and Vietnamese validated
- trusted PDF lane public demo
- image beta lane preview
- longitudinal comparable demo

**Tier P1: narrow proof**
- 15 to 25 real reports
- 10 row-labeled parser gold documents
- 150 mapping-labeled rows
- 15 policy-labeled cases
- one layout family per launch language
- trusted PDF lane public demo
- image beta lane hidden behind operator toggle
- longitudinal demo only on seeded comparable pairs

**Tier P2: seeded proof**
- 5 to 10 seeded reports only
- no external generalization claims
- benchmark language reduced to "demonstrated on seeded cases"
- image beta disabled
- multilingual limited to one language
- clinician-share artifact optional

If the corpus is thin, the claim set contracts automatically. The demo does not bluff.

### 0.4 What changed after strict self-validation

Accepted from the latest critique cycle:

- The patient layer still needed harder numeric gates.
- The blueprint still mixed proof-critical work with extension surfaces.
- Image support had to exist as a real customer concession, but it had to stay visibly weaker than the trusted PDF lane.
- Multilingual output needed a real launch matrix and per-language gates.
- Longitudinal delta needed to stay first-class, but only on comparable history and with neutral wording.
- The proof needed an explicit contingency for thin corpora.
- The explanation layer needed a real schema and a real failure policy.
- The UX needed to reflect Elfie's actual customer flow, not just a generic upload-result-chat pattern.
- The build story needed a source-of-truth document without agent assignment noise in the main body.

Rejected after validation:

- The trusted reasoning path does not need more black-box ML.
- The main proof should not center coach handoff or challenge hooks.
- The runtime does not need a distributed queue for this proof.
- The patient surface should not advertise image parity with PDF support.
- Severity and next-step should not be delegated to an LLM.

### 0.5 Non-negotiable covenants

1. No raw PDF or raw image is passed into the explanation model in the trusted path.
2. No finding appears without a source row, normalization trace, and policy identifier.
3. Unsupported rows must be visible in the patient artifact.
4. No unsupported input may silently produce a supported-seeming summary.
5. No severity or next-step may be generated by a model.
6. Image input never silently upgrades into trusted support.
7. Rewards may attach to healthy behaviors, follow-through, reading, and sharing. Rewards may never attach to "good" or "bad" lab values.
8. The patient artifact is primary. The clinician-share artifact is secondary.
9. The feature stays inside a wellness-support posture. It does not claim diagnosis, treatment selection, or remote monitoring.
10. The support boundary must be visible on the first upload screen and in the final result.
11. Out-of-layout false support target is zero.
12. Mixed-language and partially supported results must render visibly as mixed / partial, never as fully reviewed.

---

## 1. product fit to Elfie

### 1.1 What Elfie publicly ships today

Public materials show a product that already combines:

- personalized self-monitoring plans
- rewards, challenges, quizzes, coins, and challenges
- medication reminders and a digital pillbox with a 4 million+ drug inventory backed by WHODrugs
- Apple Health and Google Fit connectivity
- broad wearable support and CGM integration claims
- Omron connectivity
- face-scan measurement using Binah.ai
- family support
- AI coach surfaces with a wellness-only boundary
- data export
- a Health Report that combines lab results, vitals, and lifestyle trends into a shareable report
- clinician-facing ElfieCare workflows including pre-visit, in-visit, and post-visit tools
- anonymized longitudinal data products for research and pharma use
- multilingual app support
- region-aware data hosting and unit preferences

This matters because the lab analyzer should not behave like a standalone diagnostic mini-app. It should behave like a stronger Health Report module with tighter provenance, clearer patient language, and better structured follow-through.

### 1.2 What this track challenge should extend, not replace

The best fit is not "new tab called Labs AI." The best fit is:

- **Health Report enrichment**  
  Add a lab understanding card inside the existing report flow.

- **My Health longitudinal card**  
  Add a "last comparable result" block for selected analytes when history exists.

- **Family support visibility**  
  Make the patient artifact easy to share or review with a caregiver.

- **Doctor-share bridge**  
  Reuse the existing share/export behavior rather than invent a new referral flow.

- **Rewards-neutral completion tasks**  
  Reward upload, reading the summary, acknowledging unsupported items, and share/export if Elfie's policy allows. Do not reward the value itself.

- **Coach boundary**  
  Keep lab education inside the same wellness boundary that Elfie's AI coach already uses. Do not widen the claim surface.

### 1.3 Elfie's public UX and customer-experience method

OSINT suggests a consistent method:

- the Home screen is a plan hub
- the Health surface is where personal health history and family support live
- export and share are in product, not hidden in support channels
- the app is friendly and warm, not cold and clinical
- the reward engine reinforces behaviors
- AI is allowed, but kept inside a wellness fence
- localization is explicit: language, region, and units are configurable
- camera-based health workflows already exist through face scan
- the app tolerates delegated care and family visibility
- the app already asks users to revisit data over time, not as one-off events

The lab feature should copy that pattern. It should be one clean artifact inside an existing behavior loop.

### 1.4 Customer jobs to be done

The feature succeeds only if it helps users do these jobs:

1. "I uploaded something. Tell me if you can read it."
2. "Tell me what matters without pretending you reviewed everything."
3. "Tell me how serious this looks in plain language."
4. "Tell me what I should do next without sounding diagnostic."
5. "Tell me what changed since last time if the comparison is valid."
6. "Let me show this to someone else."
7. "Let me use this in my language."
8. "Do not say more than you know."

### 1.5 What we should implement further, based on what Elfie already has

These are not proof-critical lanes, but they are the highest-fit extensions because they reuse surfaces Elfie already exposes publicly:

- medication-context overlay: combine pillbox and flagged lab history to suggest generic follow-up tasks such as "bring this result to your next review" or "check whether your medication list is current"
- family-share mode: caregiver-readable summary with the same support-boundary rules
- Health Report timeline fusion: labs + vitals + lifestyle on one chronology
- country-aware copy packs: severity / next-step phrasing adjusted for local care pathways
- patient export packages for Mon Espace Santé or similar export destinations where applicable
- structured research export: anonymized normalized lab rows for future RWE use, out of the patient runtime path
- clinician packet deep link from the patient artifact
- coach prompt seeds generated from deterministic findings, but kept outside the trusted path

---

## 2. stack selection protocol

### 2.1 Constraint sheet

The build is constrained by these facts:

- narrow proof window
- patient-facing trust burden
- multilingual output
- PDF first, image second
- no raw-document LLM interpretation
- deterministic clinical path
- region-aware data posture
- artifact-heavy output
- one-node proof deployment is acceptable
- runtime complexity must stay low

### 2.2 Chosen stack

**API and render layer**
- FastAPI
- server-rendered HTML or lightweight React frontend behind the same app
- Jinja or React is acceptable as long as the result artifact is deterministic and testable

**Data and job layer**
- PostgreSQL
- Postgres-backed job table
- no Valkey, no external queue daemon in the proof
- object storage bucket per region or encrypted local artifact volume for strictly local proof mode only

**Trusted document lane**
- `pdfplumber` for machine-generated PDFs
- custom layout adapters for supported families
- no OCR in the trusted lane

**Image beta lane**
- Qwen-VL for lane classification / support scoring
- docTR for OCR
- Surya for layout assistance
- preview-only unless the exact same acceptance gates as the trusted lane are met

**Terminology and units**
- locally pinned LOINC artifact
- local alias tables
- deterministic UCUM validation and conversion layer
- no runtime dependence on LOINC's beta FHIR terminology service

**Policy core**
- in-process Python rule engine
- deterministic severity and next-step tables
- explicit policy versioning

**Explanation**
- Qwen only
- structured findings in, bounded text out
- no raw source document context
- off in benchmark-critical runs unless a specific explanation gate is being measured

### 2.3 Boring choices and justified exceptions

Boring choices:
- FastAPI
- Postgres
- one app
- one database
- one object store
- one trusted parser
- in-process policy engine

Justified exceptions:
- image beta lane exists because public Elfie behavior already includes camera-based health input
- one empirical mapping challenger exists because analyte identity is the one place where the literature supports it
- multilingual support is explicit because Elfie already ships 10+ languages publicly

### 2.4 LOINC artifact and licensing discipline

The local terminology artifact is a real dependency and must be treated like one.

Requirements:
- registered LOINC download account
- artifact stored outside the public repo
- checksum recorded
- version pinned in configuration
- artifact import step documented
- redistribution not assumed
- container image may include the artifact only if license terms permit that deployment path; otherwise mount at runtime from an internal artifact store
- the service must boot fail-fast if the configured terminology snapshot is missing

---

## 3. architecture tailoring

### 3.1 Runtime topology

One app. One database. One artifact store. One job table.

Flow:

1. upload enters API
2. preflight classifies input lane
3. trusted PDF lane or image beta lane selected
4. extraction runs
5. extraction QA runs
6. provisional observations created
7. analyte mapping and abstention run
8. UCUM validation and canonicalization run
9. panel reconstruction runs
10. deterministic rules fire
11. deterministic severity and next-step assignment runs
12. structured patient artifact renders
13. clinician-share artifact renders
14. lineage and benchmark telemetry persist

### 3.2 Input lanes

#### Lane A: trusted PDF
Supported:
- machine-generated PDFs where text is embedded
- supported layout families
- supported languages only

Refused:
- password-protected PDFs
- corrupted PDFs
- image-only PDFs
- scanned PDFs without embedded text
- unsupported file size
- unsupported page count
- duplicate checksum already processed unless user requests reprocess

#### Lane B: image beta
Accepted only into preview mode:
- camera photos
- screenshots
- scanned exports
- image-only PDFs converted to image frames

Possible outcomes:
- preview only
- request a PDF upload
- unsupported
- trusted promotion only if every downstream gate equals the trusted PDF lane gates

#### Lane C: structured import
- FHIR `DiagnosticReport` plus `Observation`
- internal seeded JSON fixtures for testing
- not the hero demo path, but used for control cases and history overlay

### 3.3 Input sanitization

Hard limits:
- file type whitelist: pdf, png, jpg, jpeg, webp
- max file size
- max pages
- password-protected PDFs rejected
- encrypted or malformed files rejected
- MIME and extension must agree
- virus/malware scan hook stubbed
- checksum recorded before processing
- duplicate upload path explicit
- if extraction returns zero rows on a supposed PDF, the result is "unsupported or image-only", not silent emptiness

### 3.4 Core modules

- input gateway
- support classifier
- parser
- OCR adapter
- extraction QA
- provisional observation builder
- analyte resolver
- UCUM validator and converter
- panel reconstructor
- rule engine
- severity policy engine
- next-step policy engine
- explanation adapter
- artifact renderer
- lineage logger
- benchmark recorder

### 3.5 Data contracts

#### Observation contract
Each reviewed row becomes a canonical observation with:

- source document id
- source page
- source row hash
- raw analyte label
- raw value string
- raw unit string
- parsed numeric value or null
- candidate analytes with scores
- accepted analyte or null
- specimen context if available
- method context if available
- raw printed reference range
- canonical unit
- canonical value
- language id
- support state
- suppression reason list

#### Patient context contract
The patient overlay is separate from the document.

Fields:
- birth year or age band
- sex
- preferred language
- country / region
- known conditions if available from existing Elfie profile
- medication list if already present in Elfie
- prior comparable observations if present

Missing values do not kill the whole report. They kill only the policies that need them.

### 3.6 Reference range reconciliation policy

Three threshold sources may exist:

1. lab-printed range
2. deterministic policy threshold
3. derived threshold requiring patient overlay

Required behavior:
- always show the printed lab range if present
- show the policy threshold if the finding depends on it
- if they conflict, say they conflict
- if the policy threshold is stricter than the printed range, say the flag is based on policy threshold, not only the printed range
- if the conflict cannot be reconciled safely, suppress severity and next step for that finding
- no visual range bar may imply that the printed range is the only reason a finding was flagged

### 3.7 Analyte resolver

The resolver is auditable hybrid software.

Input:
- raw analyte label
- panel header
- specimen context
- method hints
- unit
- language
- local alias tables
- local terminology snapshot

Output:
- ranked candidates
- accepted candidate or abstain
- score
- threshold used
- rejection reason

Modes:
- deterministic lexical rules only
- optional empirical challenger for ranking and calibration
- never auto-accept below threshold
- every abstention reason stored

### 3.8 Rule engine

The proof supports only a narrow analyte set, but every supported analyte is deeply specified.

Priority packs:
- glycemia / diabetes
- lipids / cardiovascular risk proxies
- kidney function

Every rule yields:
- finding id
- support criteria
- supporting observations
- threshold source
- suppression conditions
- explanatory scaffold id
- severity class candidate
- next-step class candidate

### 3.9 Severity policy

Severity is not inferred by an LLM. It is assigned from closed policy tables.

Classes:
- S0 no actionable finding
- S1 review routinely
- S2 discuss at next planned visit
- S3 contact clinician soon
- S4 urgent follow-up recommended
- SX cannot assess severity

Requirements:
- explicit precedence when multiple findings exist
- explicit demotion when required context is missing
- explicit suppression when lab range and policy threshold conflict in unresolved ways
- S4 is only allowed for a small, signed-off critical-value subset with cited policy source
- if no signed-off urgent subset exists for launch country, S4 is disabled for that language / country pack

### 3.10 Next-step policy

Next-step is also closed-table, not generated.

Classes:
- A0 no specific action beyond routine self-monitoring
- A1 review at next planned visit
- A2 schedule routine follow-up
- A3 contact clinician soon
- A4 seek urgent review
- AX cannot suggest a next step safely

Each next-step class maps to:
- allowed wording
- timing wording
- disallowed wording
- escalation disclaimer
- locale variant template
- suppression behavior

### 3.11 Explanation adapter

The explanation layer is downstream and bounded.

Input:
- structured findings only
- severity class
- next-step class
- support coverage
- unsupported summary
- preferred language
- approved template pack
- patient glossary pack

Output schema:
- headline
- finding bullets
- one short paragraph
- next-step sentence
- unsupported sentence
- threshold provenance sentence if needed
- disclaimer footer

Hard rules:
- no diagnosis labels unless the deterministic policy explicitly allows a generic educational phrasing
- no invented values
- no medication advice
- no treatment advice
- no speculation about symptoms
- if the model output fails schema or grounding checks, fall back to deterministic templates

### 3.12 Longitudinal contract

Delta is first-class, but only where comparison is valid.

Comparability requires:
- same analyte
- comparable units after deterministic conversion
- comparable method or approved comparability rule
- no unresolved specimen mismatch
- no unresolved support-state mismatch

Patient-facing wording:
- increased
- decreased
- similar
- trend unavailable

Forbidden wording:
- improving
- worsening
- better
- worse

If comparability fails, the card exists only as "no valid comparison available."

---

## 4. UX contract

### 4.1 Screen A: upload

Primary call to action:
- Upload a PDF of your lab report

Secondary call to action:
- Add a photo or screenshot (beta, limited support)

Required visible copy:
- "PDF reports work best in this proof."
- "Photo and screenshot support is limited and may only produce a preview."
- supported languages listed honestly
- privacy and share note if applicable

Forbidden copy:
- "Take a photo" as the main path
- blanket claims that all lab reports are supported
- blanket claims that Vietnamese and English documents are fully supported unless the language pack gates pass

### 4.2 Screen B: processing

Stages:
- upload received
- checking file format
- reading supported rows
- matching lab values
- building your summary

Visible branches:
- unsupported format
- partially supported
- image preview only
- ready

A spinner without state text is not acceptable.

### 4.3 Screen C: patient artifact

This is the main surface.

It must show:

1. **Support banner**
   - fully supported
   - partially supported
   - could not assess fully

2. **Severity banner**
   - color + icon + text
   - must not rely on color alone
   - must support S0/S1/S2/S3/S4/SX

3. **Needs attention**
   - flagged cards
   - plain-language analyte name
   - value and unit
   - one-sentence finding
   - threshold provenance line
   - severity chip

4. **Reviewed and not flagged**
   - collapsed by default
   - phrased as "reviewed and not flagged"
   - not "normal" if the report is partial

5. **What to do next**
   - next-step title
   - timing
   - reason
   - non-diagnostic disclaimer if needed

6. **What we did not assess**
   - unsupported analytes
   - unsupported units
   - unreadable rows
   - missing overlay context
   - unresolved threshold conflict
   - mixed-language unsupported rows

7. **Why this was flagged**
   - tappable provenance detail
   - row source
   - policy threshold
   - printed range if present

Primary actions:
- share summary
- export summary
- learn about these reviewed results

### 4.4 Screen D: comparable history card

This card appears only if a valid prior comparable observation exists.

It must show:
- current value
- previous comparable value
- direction: increased / decreased / similar
- date labels
- comparability status
- no health judgment words

### 4.5 Screen E: guided ask

This is not free chat in the proof.

Allowed prompts:
- what was flagged
- why was this flagged
- what should I do next
- what was not assessed
- what does this reviewed test usually measure

Blocked intents:
- diagnosis
- treatment choice
- medication changes
- symptom triage
- anything not grounded in structured findings

If the guided answer layer fails, the static FAQ blocks still exist.

### 4.6 Screen F: clinician-share artifact

One page. Scannable fast.

It must show:
- report date
- top findings
- severity classes
- next-step classes
- support coverage
- what was not assessed
- QR or link to deeper provenance

It must not inline a wall of raw rows.

### 4.7 Accessibility and language

Requirements:
- WCAG-aware contrast
- color-independent meaning
- screen-reader order
- tap target minimums
- no jargon beyond approved glossary terms
- language fallback explicit
- mixed-language cases visible
- right-to-left layout support only if the language pack is validated

---

## 5. data sources and thresholds

### 5.1 Clinical threshold sources

Allowed threshold sources:
- cited guideline
- deterministic public-health threshold
- lab-printed range
- explicitly versioned local policy table

Every finding records which one was used.

### 5.2 Launch languages

Trusted languages for the proof:
- English
- Vietnamese

Secondary packs, disabled by default:
- French
- Spanish
- Arabic

Each language has four separate statuses:
- UI supported
- document parsing supported
- explanation template supported
- clinician-share template supported

A language is not "supported" unless all required statuses pass their gates.

### 5.3 Supported analyte list for the proof

The proof must be narrow and explicit.

Required:
- fasting glucose
- HbA1c
- creatinine
- eGFR when age and sex are present
- total cholesterol
- LDL-C
- HDL-C
- triglycerides

Optional if corpus supports them:
- urine albumin / ACR
- non-HDL cholesterol
- blood urea nitrogen
- fasting status marker if present in source

Anything else is visible as "not assessed" unless explicitly supported.

### 5.4 Demographics overlay

Required overlay for some policies:
- age or birth year
- sex

Optional overlay:
- known conditions from Elfie profile
- medication classes from pillbox
- country / region

Missing overlay behavior:
- affected rules suppressed
- patient artifact says why
- supported rows remain visible
- unsupported policy path does not contaminate unrelated findings

### 5.5 Coverage gates

Coverage must be measured, not implied.

Primary gates:
- trusted PDF supported-document coverage
- accepted-observation coverage
- rule-suppression rate
- partial-support rate
- unsupported rate by lane
- image-preview abandon rate
- multilingual fallback rate

Out-of-layout false support target is zero.

---

## 6. optimization protocol

### 6.1 Optimize in this order

1. refuse unsupported input early
2. parse only supported rows
3. keep one trusted parser
4. use deterministic templates before LLM output
5. store compact provenance, not verbose duplicated blobs
6. render one patient artifact and derive the clinician artifact from the same structured packet
7. run image beta only when explicitly chosen

### 6.2 What not to optimize yet

- no runtime vector store
- no multi-service split
- no semantic cache
- no broad agent runtime
- no generic chat product
- no auto-OCR promotion into trusted output

---

## 7. CI/CD and lineage protocol

### 7.1 Pipeline

Stages:
1. lint and format
2. unit tests
3. contract tests
4. parser fixtures
5. mapping fixtures
6. rule / severity / next-step fixtures
7. UI snapshot and accessibility checks
8. multilingual template checks
9. benchmark subset
10. artifact generation smoke test

### 7.2 Release gates

The build is red if any of these fail:

- parser row F1 below threshold
- out-of-layout false support above zero
- mapping accepted precision below threshold
- severity agreement below threshold
- next-step agreement below threshold
- support banner missing in any partial-support screen
- unsupported rows hidden in patient artifact
- language pack missing required copy
- explanation fidelity below threshold on enabled language packs
- lineage bundle incomplete

### 7.3 Reprocessing protocol

Reprocessing is mandatory when any of these change:
- parser version
- OCR version
- terminology snapshot
- alias tables
- unit engine
- rule pack
- severity table
- next-step table
- explanation templates

Rules:
- old artifacts remain reproducible
- new run gets a new lineage id
- user-facing artifact shows the latest active run only
- benchmark pack stores both old and new results for regression comparison

---

## 8. operations protocol

### 8.1 Job semantics

The job table needs:

- idempotency key
- input checksum
- lane type
- status
- retry count
- dead-letter flag
- operator note field
- artifact pointers
- region

Retry policy:
- bounded retries
- no duplicate artifact creation on retry
- partial state cleaned or replaced atomically
- dead-letter state visible to operator
- user sees a terminal failure state, not an infinite spinner

### 8.2 Support and operator states

Operator states:
- supported
- partial support
- unsupported input
- image preview only
- dead-letter
- reprocess pending

User states:
- ready
- partially reviewed
- could not assess
- upload another file
- try PDF instead

### 8.3 Observability

Required logs:
- input lane decision
- parser support family
- extraction coverage
- mapping abstention reasons
- UCUM failures
- rule firings
- severity / next-step assignments
- explanation fallback usage
- language pack id
- support banner id
- share/export generation

Required metrics:
- trusted PDF success rate
- image beta preview rate
- partial-support rate
- out-of-layout false support
- explanation fallback rate
- patient artifact render latency
- clinician artifact render latency

---

## 9. security and compliance protocol

### 9.1 Trust boundary

- no raw document to LLM in trusted path
- explanation receives structured findings only
- model output never sets values, severity, or next steps
- region selection governs storage location
- patient artifact and share artifact inherit region and retention metadata

### 9.2 Data handling

- encryption at rest
- HTTPS in transit
- retention policy per region
- local encrypted artifact path allowed only in proof mode and only if explicitly configured
- exported files time-limited or mailed through existing approved mechanisms
- audit log for share events

### 9.3 Regulatory posture

This feature must stay inside a wellness-support posture unless Elfie changes product claims, governance, and regulatory strategy. That means:
- no diagnosis labels as product claims
- no medication changes
- no monitoring claims
- no implication that the app replaces professional care
- urgent-routing classes only if a signed-off critical-value source exists for the relevant language/country pack

---

## 10. benchmark and validation protocol

### 10.1 Hard numeric gates

#### Trusted PDF lane
- parser row precision >= 0.98 on supported layouts
- parser row recall >= 0.96 on supported layouts
- parser row F1 >= 0.97 on supported layouts
- out-of-layout false support = 0
- supported-document coverage >= 0.85 for the declared proof tier
- accepted-observation coverage >= 0.90 on supported documents

#### Mapping and units
- accepted analyte precision >= 0.97
- unsupported precision >= 0.995
- unsafe unit false accept = 0

#### Rules and policy
- rule agreement >= 0.95 on labeled policy cases
- severity agreement >= 0.95
- next-step agreement >= 0.95
- S4/A4 only on signed-off cases
- unsupported-context suppression recall >= 0.99

#### Patient artifact
- five-question task accuracy >= 0.90 in English
- five-question task accuracy >= 0.90 in Vietnamese
- partial-support misread rate <= 0.05
- unsupported visibility omission rate = 0
- threshold-conflict visibility omission rate = 0

#### Explanation
- grounded-fact fidelity >= 0.98 on enabled language packs
- jargon escape rate <= 0.02
- blocked-intent refusal accuracy >= 0.98
- deterministic template fallback availability = 1.00

#### Image beta
- false trusted promotion = 0
- preview false support = 0
- preview abandon rate tracked and reported
- image lane disabled from the public demo if preview utility cannot be demonstrated honestly

#### Clinician-share
- top-3 finding extraction within 10 seconds for test raters >= 0.90
- unsupported visibility in share artifact = 1.00

### 10.2 Baselines and ablation

Baselines:
- raw PDF only
- raw PDF + printed high/low only
- normalized labs only
- normalized labs + deterministic rules
- normalized labs + deterministic rules + severity / next-step
- normalized labs + deterministic rules + severity / next-step + explanation

This proves where the value sits.

### 10.3 Patient comprehension benchmark

Operational definition:
- a fixed bank of five task questions per case
- same questions asked against raw PDF baseline and patient artifact
- answer key created per labeled case
- automatic scoring where possible
- manual review on edge cases
- report both accuracy and wrong-confidence rate

Question classes:
1. which results were flagged
2. how serious is the reviewed result
3. what should the person do next
4. what was not assessed
5. why was the result flagged

### 10.4 Curated stress sources

Validation does not rely only on clean reports. The proof pack must include:

- real supported PDFs
- intentionally corrupted PDFs
- password-protected PDFs
- image-only PDFs
- screenshots
- camera photos
- mixed-language documents
- contradictory printed ranges
- unsupported units
- incomplete panels
- duplicate uploads
- prior-result pairs that are and are not comparable

These are defined in Appendix A.

---

## 11. schema and persistence protocol

### 11.1 Core tables

- documents
- jobs
- extracted_rows
- observations
- mapping_candidates
- rule_events
- policy_events
- patient_artifacts
- clinician_artifacts
- lineage_runs
- benchmark_runs
- share_events

### 11.2 Required columns

Every persisted row used in reasoning must retain:
- source document id
- source page
- raw text
- normalized value
- canonical unit
- accepted analyte id or null
- support state
- suppression reason list
- rule ids
- severity id
- next-step id
- lineage id

### 11.3 Lineage completeness

No artifact is complete unless it can answer:
- which row did this come from
- which analyte code was assigned
- which threshold source was used
- which rule fired
- which severity policy row won
- which next-step row won
- which template or model rendered the text

---

## 12. deployment and packaging protocol

### 12.1 Proof deployment posture

This is a proof-tier deployment:
- one app instance
- one Postgres instance
- one artifact store
- one worker process
- one region at a time
- no HA claims
- no broad layout-family claims
- no image-parity claims

### 12.2 Demo package

The live demo must show, in order:
1. upload trusted PDF
2. support decision
3. normalized findings
4. one visible rule firing
5. severity class
6. next-step class
7. what was not assessed
8. clinician-share export
9. longitudinal comparable card
10. image beta preview, only if it passes its own preview honesty gate

### 12.3 Proof narrative

The proof narrative must say:
- narrow supported proof
- deterministic reasoning core
- bounded image beta
- patient-first artifact
- explicit abstention
- multilingual only where validated
- no diagnosis claim
- no silent support inflation

---

## 13. documentation and source register protocol

### 13.1 Main documents

The v10 pack consists of:
- source-of-truth blueprint
- parallel distribution plan
- unit tests and guardrails pack

### 13.2 What belongs in appendices, not the main body

- extension hooks for coach / challenge / research
- broader future-lane roadmaps
- deep literature notes
- non-critical source commentary

---

## 14. final output contract

A reviewer should be able to answer "yes" to all of these:

- Can the feature reject unsupported input honestly?
- Can it show a patient what mattered and what did not?
- Can it assign severity and next step without an LLM making those decisions?
- Can it explain itself with provenance?
- Can it stay inside Elfie's public wellness boundary?
- Can it fit Elfie's current Health Report / share / family / localization model?
- Can two people build it in parallel without stepping on the same files?
- Can the proof be rerun and audited?

If the answer to any of those is no, the proof is not done.

---

## Appendix A. validation source design

This appendix defines the stress sources. These are part of the build, not future work.

### A1. Trusted PDF corpus
- machine-generated PDFs
- declared layout families
- English and Vietnamese launch-language cases
- at least one partial-support case
- at least one threshold-conflict case

### A2. Image beta corpus
- camera photo of printed report
- screenshot of portal report
- scan exported as image-only PDF
- blurred photo
- rotated photo
- cropped image with missing header
- multilingual image
- mixed-language image

### A3. Parser gold set
- row-level labels
- page-level support labels
- out-of-layout negatives
- duplicate row traps
- split-line traps

### A4. Mapping gold set
- analyte label
- context
- unit
- correct code
- acceptable alternates if any
- must-abstain cases

### A5. Policy gold set
- observations
- expected finding set
- expected severity class
- expected next-step class
- expected suppression conditions

### A6. UX stress cases
- fully supported
- partially supported
- unsupported
- threshold conflict
- missing age / sex
- mixed language
- image preview only
- comparable history valid
- comparable history invalid

### A7. Comprehension task bank
Five questions per case, scored against:
- raw PDF baseline
- structured patient artifact
- clinician-share artifact where relevant

---

## Appendix B. full source register

### B1. Official Elfie product surface
1. Elfie home page — https://www.elfie.co/
2. Elfie for everybody — https://www.elfie.co/everybody
3. Elfie for healthcare — https://www.elfie.co/healthcare
4. Elfie for pharma — https://www.elfie.co/pharma
5. ElfieCare — https://www.elfie.co/care
6. ElfieResearch — https://www.elfie.co/scientists
7. Elfie for insurers — https://www.elfie.co/insurers
8. Elfie for employers / works — https://www.elfie.co/employers
9. Elfie ethics — https://www.elfie.co/ethics
10. Elfie about us — https://www.elfie.co/about-us
11. Elfie Google Play listing — https://play.google.com/store/apps/details?id=co.elfie.app
12. Elfie Apple App Store listing — https://apps.apple.com/cl/app/elfie-health-rewards/id1581530269?l=en-GB
13. Elfie privacy notice — https://www.elfie.co/knowledge/privacy
14. Elfie terms of use — https://www.elfie.co/knowledge/terms-of-use
15. Elfie medication knowledge page — https://www.elfie.co/knowledge/medications
16. Elfie evidence sources & methodology — https://www.elfie.co/knowledge/evidence-sources-methodology
17. Elfie gamification / digital practitioner article — https://www.elfie.co/knowledge/the-gamification-of-healthcare-emergence-of-the-digital-practitioner
18. Elfie framework for gamifying self-monitoring — https://www.elfie.co/knowledge/framework-for-gamifying-self-monitoring
19. Elfie digital health page — https://www.elfie.co/digital-health
20. Elfie partners page — https://www.elfie.co/partners

### B2. Official Elfie help pages and UX clues
21. What is my health plan — https://www.elfie.co/help/what-is-my-health-plan-self-monitoring-plan
22. What languages is the Elfie app available in — https://www.elfie.co/help/in-which-language-is-the-elfie-app-available
23. What countries is Elfie available in — https://www.elfie.co/help/in-which-countries-is-the-elfie-app-available
24. How do I export my data — https://www.elfie.co/help/how-do-i-export-my-data
25. How can I support / follow the health of a relative / friend — https://www.elfie.co/help/how-can-i-support-follow-the-health-of-a-relative-friend-with-elfie
26. How can I invite a friend / relative — https://www.elfie.co/help/how-can-i-invite-a-friend-relatives-to-elfie
27. What apps can Elfie sync with — https://www.elfie.co/help/what-apps-does-elfie-sync-with
28. Can I import data from my smartwatch into Elfie — https://www.elfie.co/help/can-i-import-data-from-my-smartwatch-into-elfie
29. Which devices can synchronize with Apple Health and Google Fit — https://www.elfie.co/help/which-devices-can-synchronize-with-apple-health-and-google-fit
30. How do I connect my wearable devices on the Elfie App — https://www.elfie.co/help/how-do-i-connect-my-wearables-on-elfie-app
31. How do I count my steps — https://www.elfie.co/help/how-do-i-count-my-steps
32. Why didn't the steps synchronize — https://www.elfie.co/help/why-my-steps-in-wearable-device-did-not-sync-with-elfie
33. What vitals can Elfie face scan capture — https://www.elfie.co/help/face-scan-capabilities
34. How accurate is your face scan technology — https://www.elfie.co/help/how-accurate-is-your-face-scan-technology
35. Is there a battery requirement for face scan — https://www.elfie.co/help/is-there-a-battery-requirement-on-the-device-in-order-to-get-a-face-scan-done
36. Why do I need internet to use Elfie — https://www.elfie.co/help/why-do-i-need-internet-to-use-elfie
37. What does the medication / pillbox feature do — https://www.elfie.co/help/what-does-medication-do
38. Where is your medication database coming from — https://www.elfie.co/help/where-is-your-medication-database-coming-from
39. What are the rules of the challenge — https://www.elfie.co/help/what-are-the-rules-of-the-challenge
40. How do I earn Elfie coins — https://www.elfie.co/help/how-do-i-earn-elfie-coins
41. What questions can I ask to the Elfie AI coach — https://www.elfie.co/help/what-questions-can-i-ask-to-elfie-ai-coach
42. What's the difference between AI COACH and TALK TO US — https://www.elfie.co/help/whats-the-difference-between-ai-coach-and-talk-to-us
43. Can I talk to a human coach — https://www.elfie.co/help/can-i-talk-to-a-human-coach
44. How can I get support from a human — https://www.elfie.co/help

### B3. Qwen and model infrastructure
45. Model Studio model list — https://www.alibabacloud.com/help/en/model-studio/models
46. Qwen API reference — https://www.alibabacloud.com/help/en/model-studio/qwen-api-reference/
47. Qwen OpenAI compatibility — https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope
48. Qwen structured output — https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output
49. Qwen Code docs — https://qwenlm.github.io/qwen-code-docs/
50. Qwen Code headless mode — https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/
51. Qwen Code subagents — https://qwenlm.github.io/qwen-code-docs/en/users/features/sub-agents/
52. Qwen Code GitHub repo — https://github.com/QwenLM/qwen-code
53. Qwen3-Coder GitHub repo — https://github.com/QwenLM/Qwen3-Coder
54. Qwen vision compatibility docs — https://www.alibabacloud.com/help/en/model-studio/qwen-vl-compatible-with-openai

### B4. PDF, OCR, and image tooling
55. pdfplumber repo — https://github.com/jsvine/pdfplumber
56. pdfplumber stable README — https://github.com/jsvine/pdfplumber/blob/stable/README.md?plain=1
57. pdfplumber discussion on machine-generated PDFs — https://github.com/jsvine/pdfplumber/discussions/908
58. docTR repo — https://github.com/mindee/doctr
59. docTR docs — https://mindee.github.io/doctr/
60. Surya repo — https://github.com/datalab-to/surya

### B5. Standards and interoperability
61. HL7 FHIR Observation — https://build.fhir.org/observation.html
62. HL7 FHIR DiagnosticReport — https://build.fhir.org/diagnosticreport.html
63. HL7 Europe laboratory DiagnosticReport profile — https://hl7.eu/fhir/laboratory/StructureDefinition-DiagnosticReport-eu-lab.profile.json.html
64. AU Base DiagnosticReport — https://hl7.org.au/fhir/4.1.0/StructureDefinition-au-diagnosticreport.html
65. LOINC home — https://loinc.org/
66. LOINC FHIR service notice — https://loinc.org/fhir/
67. LOINC versioning / beta notice — https://loinc.org/kb/versioning/
68. UCUM — https://ucum.org/ucum
69. SNOMED CT overview — https://www.snomed.org/

### B6. Clinical and policy sources
70. NKF CKD-EPI 2021 equation — https://www.kidney.org/professionals/ckd-epi-creatinine-equation-2021
71. CDC diabetes testing overview — https://www.cdc.gov/diabetes/diabetes-testing/index.html
72. CDC critical values reporting summary — https://www.cdc.gov/labbestpractices/pdfs/CDC_ReportingCriticalValuesSummary.pdf
73. KDIGO guidelines — https://kdigo.org/guidelines/
74. FDA CDS guidance 2026 — https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software
75. FDA CDS guidance PDF — https://www.fda.gov/media/109618/download

### B7. Prior art and adjacent evidence
76. MIMIC-IV-Note — https://physionet.org/content/mimic-iv-note/2.2/
77. Automated LOINC mapping literature example — https://pubmed.ncbi.nlm.nih.gov/35308998/
78. Patient understanding of test results literature example — https://pmc.ncbi.nlm.nih.gov/articles/PMC11347896/
79. NKF / eGFR discussion overview — https://pmc.ncbi.nlm.nih.gov/articles/PMC10797164/
80. Apple Health Records support — https://support.apple.com/guide/iphone/view-health-records-iphaf8f77912/ios
81. Apple Health sharing — https://support.apple.com/guide/iphone/share-your-health-data-iph5ede58c3d/ios
82. Google Fit help — https://support.google.com/fit
