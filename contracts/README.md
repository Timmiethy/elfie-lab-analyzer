# Person A Contract Freeze

This directory contains the shared contract surface that Person B can rely on while the backend scaffold is still evolving.

## Frozen Now

- Field names, `contract_version` markers, and enum values in the backend artifact, observation, finding, and lineage schemas.
- The patient artifact shape returned by the renderer for a fully supported result.
- The clinician-share artifact shape returned by the renderer for the same finding set.
- The lineage bundle shape emitted by the provenance logger.
- The explicit trust-status marker for trusted PDF and non-trusted image-beta contracts.

## Not Yet Frozen

- Parser and OCR internals.
- Persistence details, migrations, and database row shape.
- Exact threshold tables, copy text, and presentation logic.
- Public URLs and any frontend rendering decisions.

## How To Use This Package

- Treat the JSON files in `contracts/examples/` as representative payloads, not synthetic test fixtures.
- Keep new backend changes aligned to these shapes unless this package is intentionally version-bumped.
- If a future change needs a breaking contract update, change the example payloads and this README together.

## Example Files

- `contracts/examples/patient_artifact_supported.json`
- `contracts/examples/patient_artifact_partial_support.json`
- `contracts/examples/patient_artifact_could_not_assess.json`
- `contracts/examples/patient_artifact_unsupported.json`
- `contracts/examples/patient_artifact_threshold_conflict.json`
- `contracts/examples/patient_artifact_comparable_history_available.json`
- `contracts/examples/patient_artifact_comparable_history_unavailable.json`
- `contracts/examples/patient_artifact_image_beta_non_trusted.json`
- `contracts/examples/clinician_artifact_supported.json`
- `contracts/examples/lineage_example.json`

The patient artifact examples intentionally cover the main contract-completeness states used by Person A:

- fully supported results
- partial support with a supported finding plus unsupported items
- could-not-assess fallback payloads
- unsupported analyte or modality paths
- threshold conflict handling
- comparable-history available and unavailable cases
- trusted PDF lane outputs
- non-trusted image-beta lane outputs
