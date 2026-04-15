from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

DOCUMENT_ROUTE_CONTRACT_VERSION = "document-route-v1"
DOCUMENT_PACKET_CONTRACT_VERSION = "document-packet-v1"
PAGE_PARSE_CONTRACT_VERSION = "page-parse-v4"
BLOCK_GRAPH_CONTRACT_VERSION = "block-graph-v1"
CANDIDATE_ROW_CONTRACT_VERSION = "candidate-row-v3"
SUPPRESSION_REPORT_CONTRACT_VERSION = "suppression-report-v1"
CANONICAL_OBSERVATION_CONTRACT_VERSION = "canonical-observation-v3"
CORPUS_EVALUATION_CONTRACT_VERSION = "corpus-evaluation-v2"


class RouteLaneType(str, Enum):
    TRUSTED_PDF_LAB = "trusted_pdf_lab"
    IMAGE_PDF_LAB = "image_pdf_lab"
    COMPOSITE_PACKET = "composite_packet"
    INTERPRETED_SUMMARY = "interpreted_summary"
    NON_LAB_MEDICAL = "non_lab_medical"
    UNSUPPORTED = "unsupported"


class PageKindV2(str, Enum):
    LAB_RESULTS = "lab_results"
    THRESHOLD_REFERENCE = "threshold_reference"
    ADMIN_METADATA = "admin_metadata"
    NARRATIVE_GUIDANCE = "narrative_guidance"
    INTERPRETED_SUMMARY = "interpreted_summary"
    NON_LAB_MEDICAL = "non_lab_medical"
    FOOTER_HEADER = "footer_header"
    UNKNOWN = "unknown"


class BlockRoleV1(str, Enum):
    RESULT_BLOCK = "result_block"
    THRESHOLD_BLOCK = "threshold_block"
    ADMIN_BLOCK = "admin_block"
    NARRATIVE_BLOCK = "narrative_block"
    HEADER_FOOTER_BLOCK = "header_footer_block"
    UNKNOWN_BLOCK = "unknown_block"


class CandidateRowTypeV3(str, Enum):
    MEASURED_ANALYTE_ROW = "measured_analyte_row"
    DERIVED_ANALYTE_ROW = "derived_analyte_row"
    QUALITATIVE_RESULT_ROW = "qualitative_result_row"
    THRESHOLD_REFERENCE_ROW = "threshold_reference_row"
    ADMIN_METADATA_ROW = "admin_metadata_row"
    NARRATIVE_GUIDANCE_ROW = "narrative_guidance_row"
    HEADER_FOOTER_ROW = "header_footer_row"
    TEST_REQUEST_ROW = "test_request_row"
    UNPARSED_ROW = "unparsed_row"


NORMALIZABLE_ROW_TYPES_V3 = {
    CandidateRowTypeV3.MEASURED_ANALYTE_ROW.value,
    CandidateRowTypeV3.DERIVED_ANALYTE_ROW.value,
    CandidateRowTypeV3.QUALITATIVE_RESULT_ROW.value,
}


def route_lane_to_runtime_lane(lane_type: RouteLaneType) -> str:
    if lane_type == RouteLaneType.TRUSTED_PDF_LAB:
        return "trusted_pdf"
    if lane_type == RouteLaneType.IMAGE_PDF_LAB:
        return "image_beta"
    if lane_type == RouteLaneType.COMPOSITE_PACKET:
        return "trusted_pdf"
    return "unsupported"


@dataclass(frozen=True)
class DocumentRouteDecision:
    contract_version: str = DOCUMENT_ROUTE_CONTRACT_VERSION
    lane_type: RouteLaneType = RouteLaneType.UNSUPPORTED
    runtime_lane_type: str = "unsupported"
    document_class: str = "unsupported"
    confidence: float = 0.0
    reason_codes: list[str] = field(default_factory=list)
    page_count: int = 0
    has_text_layer: bool = False
    has_image_layer: bool = False
    image_density: float = 0.0
    text_extractability: float = 0.0
    checksum: str = ""


@dataclass(frozen=True)
class DocumentPageGroupV1:
    group_id: str
    page_numbers: list[int]
    document_class: str
    lane_type: RouteLaneType
    reason_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DocumentPacketV1:
    contract_version: str = DOCUMENT_PACKET_CONTRACT_VERSION
    packet_id: str = ""
    parent_checksum: str = ""
    route_decision: DocumentRouteDecision = field(default_factory=DocumentRouteDecision)
    page_groups: list[DocumentPageGroupV1] = field(default_factory=list)


@dataclass(frozen=True)
class SourceSpanV1:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class PageParseBlockV4:
    block_id: str
    block_role: BlockRoleV1
    raw_text: str
    lines: list[str] = field(default_factory=list)
    bbox: SourceSpanV1 | None = None
    reading_order: int = 0
    language_tags: list[str] = field(default_factory=list)
    source_spans: list[SourceSpanV1] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PageParseArtifactV4:
    contract_version: str = PAGE_PARSE_CONTRACT_VERSION
    page_id: str = ""
    page_number: int = 1
    backend_id: str = "unknown"
    backend_version: str = "unknown"
    lane_type: str = "trusted_pdf"
    page_kind: PageKindV2 = PageKindV2.UNKNOWN
    text_extractability: float = 0.0
    language_candidates: list[str] = field(default_factory=list)
    blocks: list[PageParseBlockV4] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    raw_text: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BlockNodeV1:
    node_id: str
    block_id: str
    block_role: BlockRoleV1
    text: str
    page_number: int
    reading_order: int
    lines: list[str] = field(default_factory=list)
    bbox: SourceSpanV1 | None = None
    language_tags: list[str] = field(default_factory=list)
    source_spans: list[SourceSpanV1] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BlockEdgeV1:
    source_node_id: str
    target_node_id: str
    relation: str


@dataclass(frozen=True)
class BlockGraphV1:
    contract_version: str = BLOCK_GRAPH_CONTRACT_VERSION
    page_id: str = ""
    page_number: int = 1
    nodes: list[BlockNodeV1] = field(default_factory=list)
    edges: list[BlockEdgeV1] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateRowV3:
    contract_version: str = CANDIDATE_ROW_CONTRACT_VERSION
    row_id: str = ""
    document_id: str = ""
    source_page: int = 1
    source_block_id: str = ""
    row_type: CandidateRowTypeV3 = CandidateRowTypeV3.UNPARSED_ROW
    raw_text: str = ""
    raw_label: str = ""
    raw_value: str | None = None
    raw_unit: str | None = None
    raw_reference_range: str | None = None
    parsed_numeric_value: float | None = None
    parsed_comparator: str | None = None
    parsed_locale: dict[str, Any] = field(default_factory=dict)
    secondary_result: dict[str, Any] | None = None
    support_state: str = "excluded"
    support_code: str = "excluded"
    failure_code: str | None = None
    confidence: float = 0.0
    family_adapter_id: str = "generic_layout"
    page_class: str = "unknown"
    source_kind: str = "block"
    source_bounds: dict[str, float] | None = None
    candidate_trace: dict[str, Any] = field(default_factory=dict)
    parser_backend: str = "unknown"
    parser_backend_version: str = "unknown"
    row_assembly_version: str = "row-assembly-v3"


@dataclass(frozen=True)
class SuppressionRecordV1:
    row_id: str
    reason_code: str
    detail: str | None = None
    stage: str = "row_arbitration"


@dataclass(frozen=True)
class SuppressionReportV1:
    contract_version: str = SUPPRESSION_REPORT_CONTRACT_VERSION
    page_id: str = ""
    page_number: int = 1
    suppression_records: list[SuppressionRecordV1] = field(default_factory=list)


@dataclass(frozen=True)
class CanonicalObservationV3:
    contract_version: str = CANONICAL_OBSERVATION_CONTRACT_VERSION
    observation_id: str = ""
    source_row_id: str = ""
    support_state: str = "unsupported"
    analyte_code: str | None = None
    analyte_display: str | None = None
    canonical_value: float | None = None
    canonical_unit: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CorpusEvaluationMetricV2:
    metric_name: str
    value: float
    threshold: float | None = None
    status: str = "unknown"
    detail: str | None = None


@dataclass(frozen=True)
class CorpusEvaluationReportV2:
    contract_version: str = CORPUS_EVALUATION_CONTRACT_VERSION
    total_files: int = 0
    routed_files: int = 0
    crashes: int = 0
    silent_fallback_promotions: int = 0
    metrics: list[CorpusEvaluationMetricV2] = field(default_factory=list)
    by_family: dict[str, dict[str, float]] = field(default_factory=dict)
    by_lane: dict[str, dict[str, float]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
