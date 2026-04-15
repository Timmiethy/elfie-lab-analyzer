from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from math import ceil
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

_GROUND_TRUTH_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "pdfs_by_difficulty_ground_truth.json"
_CORPUS_ROOT = Path(__file__).resolve().parents[3]
_REPORT_DIR = _CORPUS_ROOT / "artifacts" / "corpus_reports"

_PLACEHOLDER_ANALYTE_MARKERS = (
    "as present in file",
    "core analyte",
    "if present",
    "only if",
    "if ocr confidence passes",
    "analytes present",
    "related",
    "profile analytes",
    "panel analytes",
    "chemistry/lipid analytes",
    "chemistry and hematology analytes",
    "cbc core",
    "lipids",
    "biochemistry analytes",
    "hba1c if present",
    "independent of order",
    "raw measured analytes",
    "raw-lab analytes",
    "from each subreport separately",
    "visible in crop",
    "that do not require",
    "urine r/m analytes",
)

_TERMINAL_EQUIVALENCE: dict[str, set[str]] = {
    "fully_normalized_supported_lab_report": {
        "fully_normalized_supported_lab_report",
        "partially_normalized_supported_lab_report",
        "fully_normalized_supported_lab_report_with_threshold_conflict_visibility",
    },
    "partially_normalized_supported_lab_report": {
        "partially_normalized_supported_lab_report",
        "fully_normalized_supported_lab_report_with_threshold_conflict_visibility",
    },
    "ocr_normalized_supported_lab_report": {
        "ocr_normalized_supported_lab_report",
        "ocr_or_trusted_mixed_language_single_analyte_report",
        "production_safe_unsupported_or_matrix_report",
    },
    "composite_packet_artifact": {
        "composite_packet_artifact",
        "composite_or_interpreted_summary_artifact",
    },
    "interpreted_summary_artifact": {
        "interpreted_summary_artifact",
        "composite_or_interpreted_summary_artifact",
        "non_lab_or_interpreted_summary_artifact",
    },
    "non_lab_medical_artifact": {
        "non_lab_medical_artifact",
        "non_lab_or_interpreted_summary_artifact",
        "non_lab_or_pathology_artifact",
    },
    "unsupported_encrypted_artifact": {
        "unsupported_encrypted_artifact",
        "production_safe_unsupported_or_matrix_report",
        "non_lab_medical_artifact",
        "non_lab_or_pathology_artifact",
    },
    "production_safe_unsupported_or_matrix_report": {
        "production_safe_unsupported_or_matrix_report",
        "unsupported_matrix_artifact",
    },
    "exact_duplicate_of_seed_innoquest_standard_sample_report": {
        "production_safe_unsupported_or_matrix_report",
        "unsupported_matrix_artifact",
        "exact_duplicate_of_seed_innoquest_standard_sample_report",
    },
    "exact_duplicate_of_seed_labcorp_cd4_cd8_sample": {
        "fully_normalized_supported_lab_report",
        "partially_normalized_supported_lab_report",
        "exact_duplicate_of_seed_labcorp_cd4_cd8_sample",
    },
    "fully_normalized_supported_lab_report_with_threshold_conflict_visibility": {
        "fully_normalized_supported_lab_report_with_threshold_conflict_visibility",
        "fully_normalized_supported_lab_report",
        "partially_normalized_supported_lab_report",
    },
    "ocr_or_trusted_mixed_language_single_analyte_report": {
        "ocr_or_trusted_mixed_language_single_analyte_report",
        "ocr_normalized_supported_lab_report",
        "fully_normalized_supported_lab_report",
        "partially_normalized_supported_lab_report",
        "production_safe_unsupported_or_matrix_report",
    },
    "non_lab_or_interpreted_summary_artifact": {
        "non_lab_or_interpreted_summary_artifact",
        "non_lab_medical_artifact",
        "interpreted_summary_artifact",
        "production_safe_unsupported_or_matrix_report",
    },
    "non_lab_or_pathology_artifact": {
        "non_lab_or_pathology_artifact",
        "non_lab_medical_artifact",
        "production_safe_unsupported_or_matrix_report",
    },
    "composite_or_interpreted_summary_artifact": {
        "composite_or_interpreted_summary_artifact",
        "composite_packet_artifact",
        "interpreted_summary_artifact",
    },
}


@dataclass(frozen=True)
class GroundTruthEntry:
    file: str
    expected_terminal_state: str
    lane: str
    document_family: str
    artifact_kind: str
    must_extract_analytes: list[str] = field(default_factory=list)
    must_not_surface: list[str] = field(default_factory=list)
    notes: str | None = None

    @property
    def relative_pdf_path(self) -> str:
        if self.file.startswith("pdfs_by_difficulty/"):
            return self.file[len("pdfs_by_difficulty/") :]
        return self.file


@dataclass(frozen=True)
class GroundTruthDataset:
    dataset: str
    version: str
    global_must_not_surface: list[str]
    entries: list[GroundTruthEntry]


@dataclass
class GroundTruthRunResult:
    file: str
    expected_terminal_state: str
    observed_terminal_state: str
    expected_lane: str
    observed_lane: str
    route_document_class: str | None
    status: str
    mismatches: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.mismatches

    def to_report(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "expected_terminal_state": self.expected_terminal_state,
            "observed_terminal_state": self.observed_terminal_state,
            "expected_lane": self.expected_lane,
            "observed_lane": self.observed_lane,
            "route_document_class": self.route_document_class,
            "status": self.status,
            "passed": self.passed,
            "mismatches": list(self.mismatches),
        }


@dataclass
class GroundTruthReport:
    contract_version: str = "corpus-ground-truth-report-v1"
    timestamp: str = ""
    total_files: int = 0
    passed: int = 0
    failed: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)

    def finalize(self, run_results: list[GroundTruthRunResult]) -> None:
        self.timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        self.total_files = len(run_results)
        self.passed = sum(1 for result in run_results if result.passed)
        self.failed = self.total_files - self.passed
        self.results = [result.to_report() for result in run_results]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "timestamp": self.timestamp,
            "total_files": self.total_files,
            "passed": self.passed,
            "failed": self.failed,
            "results": self.results,
        }


def load_ground_truth() -> GroundTruthDataset:
    payload = json.loads(_GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
    entries = [
        GroundTruthEntry(
            file=str(item["file"]),
            expected_terminal_state=str(item["expected_terminal_state"]),
            lane=str(item["lane"]),
            document_family=str(item.get("document_family") or "unknown"),
            artifact_kind=str(item.get("artifact_kind") or "unknown"),
            must_extract_analytes=[str(value) for value in item.get("must_extract_analytes", [])],
            must_not_surface=[str(value) for value in item.get("must_not_surface", [])],
            notes=str(item.get("notes")) if item.get("notes") is not None else None,
        )
        for item in payload.get("files", [])
    ]
    return GroundTruthDataset(
        dataset=str(payload.get("dataset") or "pdfs_by_difficulty"),
        version=str(payload.get("version") or "unknown"),
        global_must_not_surface=[str(value) for value in payload.get("global_must_not_surface", [])],
        entries=entries,
    )


@dataclass(frozen=True)
class ChecksumExpectation:
    checksum: str
    files: tuple[str, ...]
    expected_lanes: frozenset[str]
    expected_terminal_states: frozenset[str]

    @property
    def lane_conflict(self) -> bool:
        return len(self.expected_lanes) > 1

    @property
    def terminal_conflict(self) -> bool:
        return len(self.expected_terminal_states) > 1


def build_checksum_expectation_index(dataset: GroundTruthDataset) -> dict[str, ChecksumExpectation]:
    grouped: dict[str, dict[str, Any]] = {}

    for entry in dataset.entries:
        checksum = sha256(load_pdf(entry)).hexdigest()
        bucket = grouped.setdefault(
            checksum,
            {
                "files": [],
                "expected_lanes": set(),
                "expected_terminal_states": set(),
            },
        )
        bucket["files"].append(entry.file)
        bucket["expected_lanes"].add(entry.lane)
        bucket["expected_terminal_states"].add(entry.expected_terminal_state)

    index: dict[str, ChecksumExpectation] = {}
    for checksum, bucket in grouped.items():
        index[checksum] = ChecksumExpectation(
            checksum=checksum,
            files=tuple(sorted(str(value) for value in bucket["files"])),
            expected_lanes=frozenset(str(value) for value in bucket["expected_lanes"]),
            expected_terminal_states=frozenset(
                str(value) for value in bucket["expected_terminal_states"]
            ),
        )
    return index


def load_pdf(entry: GroundTruthEntry) -> bytes:
    path = _CORPUS_ROOT / entry.file
    if not path.exists():
        raise FileNotFoundError(f"ground truth pdf not found: {path}")
    return path.read_bytes()


def expected_runtime_lane(entry: GroundTruthEntry) -> str:
    return _manifest_lane_to_runtime_lane(entry.lane)


def infer_observed_terminal_state(
    *,
    preflight: dict[str, Any],
    pipeline_result: dict[str, Any] | None,
) -> str:
    failure_code = str(preflight.get("failure_code") or "")
    route_document_class = str(preflight.get("route_document_class") or "")
    lane_type = str(preflight.get("lane_type") or "unsupported")

    if failure_code == "pdf_password_protected":
        return "unsupported_encrypted_artifact"

    if route_document_class == "composite_packet":
        return "composite_packet_artifact"
    if route_document_class == "interpreted_summary":
        return "interpreted_summary_artifact"
    if route_document_class == "non_lab_medical":
        return "non_lab_medical_artifact"

    if pipeline_result is None:
        if lane_type in {"unsupported", "image_beta"}:
            return "production_safe_unsupported_or_matrix_report"
        return "blocked_without_runtime_result"

    status = str(pipeline_result.get("status") or "")
    support_banner = _pipeline_support_banner(pipeline_result)
    if lane_type == "trusted_pdf":
        if status == "completed":
            return "fully_normalized_supported_lab_report"
        if status == "partial":
            return "partially_normalized_supported_lab_report"
    if lane_type == "image_beta":
        if support_banner == "could_not_assess":
            return "production_safe_unsupported_or_matrix_report"
        if status in {"completed", "partial"}:
            return "ocr_normalized_supported_lab_report"
    if lane_type == "unsupported":
        return "production_safe_unsupported_or_matrix_report"

    return "production_safe_unsupported_or_matrix_report"


def validate_entry(
    *,
    dataset: GroundTruthDataset,
    entry: GroundTruthEntry,
    preflight: dict[str, Any],
    pipeline_result: dict[str, Any] | None,
    checksum_expectation: ChecksumExpectation | None = None,
) -> GroundTruthRunResult:
    observed_terminal_state = infer_observed_terminal_state(
        preflight=preflight,
        pipeline_result=pipeline_result,
    )
    mismatches: list[str] = []

    mismatches.extend(
        assert_lane(
            entry=entry,
            preflight=preflight,
            checksum_expectation=checksum_expectation,
        )
    )
    mismatches.extend(
        assert_terminal_state(
            entry=entry,
            observed_terminal_state=observed_terminal_state,
            pipeline_result=pipeline_result,
            checksum_expectation=checksum_expectation,
        )
    )
    mismatches.extend(
        assert_route_behavior(
            entry=entry,
            preflight=preflight,
            pipeline_result=pipeline_result,
            checksum_expectation=checksum_expectation,
        )
    )
    mismatches.extend(assert_analyte_set(entry=entry, pipeline_result=pipeline_result))
    mismatches.extend(
        assert_supported_observation_floor(entry=entry, pipeline_result=pipeline_result)
    )
    mismatches.extend(
        assert_family_specific_hard_gates(entry=entry, pipeline_result=pipeline_result)
    )
    mismatches.extend(
        assert_artifact_leaks(
            dataset=dataset,
            entry=entry,
            pipeline_result=pipeline_result,
        )
    )

    return GroundTruthRunResult(
        file=entry.file,
        expected_terminal_state=entry.expected_terminal_state,
        observed_terminal_state=observed_terminal_state,
        expected_lane=entry.lane,
        observed_lane=str(preflight.get("lane_type") or "unsupported"),
        route_document_class=str(preflight.get("route_document_class") or "") or None,
        status=str(pipeline_result.get("status") if pipeline_result else "not_run"),
        mismatches=mismatches,
    )


def assert_lane(
    *,
    entry: GroundTruthEntry,
    preflight: dict[str, Any],
    checksum_expectation: ChecksumExpectation | None = None,
) -> list[str]:
    expected_lane = expected_runtime_lane(entry)
    observed_lane = str(preflight.get("lane_type") or "unsupported")
    messages: list[str] = []

    if checksum_expectation is not None and checksum_expectation.lane_conflict:
        allowed_lanes = {
            _manifest_lane_to_runtime_lane(manifest_lane)
            for manifest_lane in checksum_expectation.expected_lanes
        }
        if observed_lane in allowed_lanes:
            return messages

    if entry.lane == "unsupported" and observed_lane != "unsupported":
        messages.append(f"lane_mismatch: expected unsupported, got {observed_lane}")

    if entry.lane == "image_pdf" and observed_lane == "trusted_pdf":
        messages.append("lane_mismatch: expected image lane but routed trusted_pdf")

    if entry.lane == "trusted_pdf" and observed_lane == "image_beta":
        allowed = entry.expected_terminal_state in {
            "ocr_or_trusted_mixed_language_single_analyte_report",
            "composite_or_interpreted_summary_artifact",
        }
        if not allowed:
            messages.append("lane_mismatch: expected trusted lane but routed image_beta")

    if expected_lane == "image_beta" and str(preflight.get("route_lane_type") or "") == "image_pdf_lab":
        if observed_lane == "trusted_pdf":
            messages.append("unsafe_lane_promotion: image route was promoted to trusted_pdf")

    return messages

def assert_terminal_state(
    *,
    entry: GroundTruthEntry,
    observed_terminal_state: str,
    pipeline_result: dict[str, Any] | None,
    checksum_expectation: ChecksumExpectation | None = None,
) -> list[str]:
    expected = entry.expected_terminal_state
    accepted = set(_TERMINAL_EQUIVALENCE.get(expected, {expected}))

    if checksum_expectation is not None and checksum_expectation.terminal_conflict:
        for candidate in checksum_expectation.expected_terminal_states:
            accepted.update(_TERMINAL_EQUIVALENCE.get(candidate, {candidate}))

    if _pipeline_support_banner(pipeline_result) == "could_not_assess":
        accepted.add("production_safe_unsupported_or_matrix_report")

    if observed_terminal_state in accepted:
        return []
    return [
        f"terminal_state_mismatch: expected {expected}, observed {observed_terminal_state}"
    ]


def assert_route_behavior(
    *,
    entry: GroundTruthEntry,
    preflight: dict[str, Any],
    pipeline_result: dict[str, Any] | None,
    checksum_expectation: ChecksumExpectation | None = None,
) -> list[str]:
    expected = entry.expected_terminal_state
    route_document_class = str(preflight.get("route_document_class") or "")

    if checksum_expectation is not None and checksum_expectation.terminal_conflict:
        return []

    if _is_runtime_limited_image(preflight=preflight, pipeline_result=pipeline_result):
        return []

    messages: list[str] = []
    if "composite" in expected and route_document_class not in {"composite_packet", "interpreted_summary"}:
        messages.append(
            f"route_mismatch: composite file routed as {route_document_class or 'unknown'}"
        )

    if (
        "non_lab" in expected
        or "interpreted_summary" in expected
        or "pathology" in expected
    ) and route_document_class not in {"non_lab_medical", "interpreted_summary", "composite_packet"}:
        messages.append(
            f"route_mismatch: non-lab/interpreted file routed as {route_document_class or 'unknown'}"
        )

    return messages


def assert_analyte_set(*, entry: GroundTruthEntry, pipeline_result: dict[str, Any] | None) -> list[str]:
    if pipeline_result is None:
        return []

    support_banner = _pipeline_support_banner(pipeline_result)
    if support_banner == "could_not_assess":
        return []

    required = [
        analyte
        for analyte in entry.must_extract_analytes
        if not _is_placeholder_analyte(analyte)
    ]
    if not required:
        return []

    observed = observed_analytes(pipeline_result)
    matched = 0
    missing: list[str] = []

    for analyte in required:
        normalized_expected = _normalize_token(analyte)
        if not normalized_expected:
            continue
        if any(
            normalized_expected in candidate or candidate in normalized_expected
            for candidate in observed
        ):
            matched += 1
            continue
        missing.append(analyte)

    if not required:
        return []

    coverage = matched / max(1, len(required))
    minimum_coverage = _minimum_analyte_coverage_threshold(
        required_count=len(required),
        support_banner=support_banner,
    )
    if coverage >= minimum_coverage:
        return []

    return [f"missing_analyte: {analyte}" for analyte in missing]


def assert_supported_observation_floor(
    *,
    entry: GroundTruthEntry,
    pipeline_result: dict[str, Any] | None,
) -> list[str]:
    if pipeline_result is None:
        return []

    support_banner = _pipeline_support_banner(pipeline_result)
    if support_banner == "could_not_assess":
        return []

    required = [
        analyte
        for analyte in entry.must_extract_analytes
        if not _is_placeholder_analyte(analyte)
    ]
    if not required:
        return []

    supported_count = _supported_observation_count(pipeline_result)
    floor = _supported_observation_floor(
        required_count=len(required),
        support_banner=support_banner,
    )

    if supported_count >= floor:
        return []
    return [
        "supported_observation_floor_miss: "
        f"required_floor={floor} supported_count={supported_count}"
    ]


def assert_family_specific_hard_gates(
    *,
    entry: GroundTruthEntry,
    pipeline_result: dict[str, Any] | None,
) -> list[str]:
    if pipeline_result is None:
        return []

    file_name = entry.file.lower()
    messages: list[str] = []

    patient_artifact = pipeline_result.get("patient_artifact")
    not_assessed_labels = _patient_not_assessed_labels(patient_artifact)
    supported_labels = _supported_observation_labels(pipeline_result)

    if file_name.endswith("easy/seed_labtestingapi_sample_report.pdf"):
        must_not_leak = (
            "report status",
            "client information",
            "room",
            "floor",
            "address",
        )
        for marker in must_not_leak:
            if any(marker in label for label in not_assessed_labels):
                messages.append(f"labtestingapi_marker_leak: {marker}")

    if file_name.endswith("medium/seed_sterlingaccuris_pathology_sample_report.pdf"):
        pathology_markers = (
            "pathology",
            "final diagnosis",
            "microscopic",
            "gross description",
            "watermark",
            "signature",
        )
        for marker in pathology_markers:
            if any(marker in label for label in not_assessed_labels):
                messages.append(f"sterling_pathology_leak: {marker}")

        if _supported_observation_count(pipeline_result) < 2:
            messages.append("sterling_supported_coverage_floor_miss: expected>=2")

    if file_name.endswith("medium/seed_innoquest_dbticrp.pdf"):
        required_markers = ("apoa1", "apob", "apob/apoa1", "lp(a)")
        for marker in required_markers:
            marker_normalized = _normalize_token(marker)
            if not any(marker_normalized in label for label in supported_labels):
                messages.append(f"dbticrp_required_analyte_missing: {marker}")

        note_markers = (
            "eas",
            "consensus",
            "castelli",
            "recurrent cv",
            "clin chem",
            "lab med",
        )
        for marker in note_markers:
            if any(marker in label for label in not_assessed_labels):
                messages.append(f"dbticrp_note_leak: {marker}")

    return messages


def _is_placeholder_analyte(value: str) -> bool:
    normalized = value.lower()
    if any(marker in normalized for marker in _PLACEHOLDER_ANALYTE_MARKERS):
        return True
    if "analyte" in normalized and ("present" in normalized or "file" in normalized):
        return True
    return False


def assert_artifact_leaks(
    *,
    dataset: GroundTruthDataset,
    entry: GroundTruthEntry,
    pipeline_result: dict[str, Any] | None,
) -> list[str]:
    if pipeline_result is None:
        return []

    patient_artifact = pipeline_result.get("patient_artifact")
    if not isinstance(patient_artifact, dict):
        return ["artifact_missing: patient_artifact"]

    artifact_text = _collect_patient_artifact_text(patient_artifact)
    messages: list[str] = []

    for token in [*dataset.global_must_not_surface, *entry.must_not_surface]:
        normalized = _normalize_token(token)
        if not normalized:
            continue
        if normalized in artifact_text:
            messages.append(f"artifact_leak: {token}")

    return messages


def observed_analytes(pipeline_result: dict[str, Any]) -> set[str]:
    observations = pipeline_result.get("observations")
    if not isinstance(observations, list):
        return set()

    values: set[str] = set()
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        support_state = observation.get("support_state")
        if hasattr(support_state, "value"):
            support_state = support_state.value
        if str(support_state or "").lower() != "supported":
            continue

        for key in ("accepted_analyte_display", "raw_analyte_label", "accepted_analyte_code"):
            value = _normalize_token(observation.get(key))
            if value:
                values.add(value)

    return values


def _supported_observation_count(pipeline_result: dict[str, Any]) -> int:
    observations = pipeline_result.get("observations")
    if not isinstance(observations, list):
        return 0
    count = 0
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        support_state = observation.get("support_state")
        if hasattr(support_state, "value"):
            support_state = support_state.value
        if str(support_state or "").lower() == "supported":
            count += 1
    return count


def _supported_observation_labels(pipeline_result: dict[str, Any]) -> set[str]:
    observations = pipeline_result.get("observations")
    if not isinstance(observations, list):
        return set()

    labels: set[str] = set()
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        support_state = observation.get("support_state")
        if hasattr(support_state, "value"):
            support_state = support_state.value
        if str(support_state or "").lower() != "supported":
            continue

        for key in ("accepted_analyte_display", "raw_analyte_label"):
            value = _normalize_token(observation.get(key))
            if value:
                labels.add(value)

    return labels


def _patient_not_assessed_labels(patient_artifact: object) -> list[str]:
    if not isinstance(patient_artifact, dict):
        return []
    labels: list[str] = []
    for item in patient_artifact.get("not_assessed", []) or []:
        if not isinstance(item, dict):
            continue
        label = _normalize_token(item.get("raw_label"))
        if label:
            labels.append(label)
    return labels


def write_ground_truth_report(report: GroundTruthReport) -> Path:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = _REPORT_DIR / f"ground-truth-report-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _collect_patient_artifact_text(patient_artifact: dict[str, Any]) -> str:
    chunks: list[str] = []

    for card in patient_artifact.get("flagged_cards", []) or []:
        if not isinstance(card, dict):
            continue
        chunks.extend(
            [
                str(card.get("analyte_display") or ""),
                str(card.get("value") or ""),
                str(card.get("unit") or ""),
                str(card.get("finding_sentence") or ""),
            ]
        )

    for item in patient_artifact.get("not_assessed", []) or []:
        if not isinstance(item, dict):
            continue
        chunks.extend([str(item.get("raw_label") or ""), str(item.get("reason") or "")])

    findings = patient_artifact.get("findings", []) or []
    if isinstance(findings, list):
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            chunks.extend(
                [
                    str(finding.get("rule_id") or ""),
                    str(finding.get("suppression_reason") or ""),
                    str(finding.get("explanatory_scaffold_id") or ""),
                ]
            )

    chunks.append(json.dumps(patient_artifact, ensure_ascii=False, default=str))
    return _normalize_token("\n".join(chunks))


def _normalize_token(value: object) -> str:
    lowered = str(value or "").lower()
    lowered = re.sub(r"\s+", " ", lowered)
    lowered = re.sub(r"[^a-z0-9\u4e00-\u9fff%/+\-\s]", " ", lowered)
    return " ".join(lowered.split())


def _manifest_lane_to_runtime_lane(manifest_lane: str) -> str:
    if manifest_lane == "trusted_pdf":
        return "trusted_pdf"
    if manifest_lane == "image_pdf":
        return "image_beta"
    return "unsupported"


def _pipeline_support_banner(pipeline_result: dict[str, Any] | None) -> str:
    if not isinstance(pipeline_result, dict):
        return ""
    patient_artifact = pipeline_result.get("patient_artifact")
    if not isinstance(patient_artifact, dict):
        return ""
    return str(patient_artifact.get("support_banner") or "")


def _is_runtime_limited_image(
    *,
    preflight: dict[str, Any],
    pipeline_result: dict[str, Any] | None,
) -> bool:
    lane_type = str(preflight.get("lane_type") or "")
    if lane_type != "image_beta":
        return False
    if pipeline_result is None:
        return True
    return _pipeline_support_banner(pipeline_result) == "could_not_assess"


def _minimum_analyte_coverage_threshold(*, required_count: int, support_banner: str) -> float:
    if required_count <= 1:
        return 1.0
    if support_banner == "fully_supported":
        return 0.7
    return 0.5


def _supported_observation_floor(*, required_count: int, support_banner: str) -> int:
    if required_count <= 1:
        return 1
    if support_banner == "fully_supported":
        return max(1, ceil(required_count * 0.7))
    return max(1, ceil(required_count * 0.5))
