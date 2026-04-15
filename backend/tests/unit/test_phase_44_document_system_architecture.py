from __future__ import annotations

from io import BytesIO
from uuid import uuid4

import pytest

from app.services.document_system.artifact_policy import ArtifactPolicy
from app.services.document_system.block_graph_builder import BlockGraphBuilder
from app.services.document_system.born_digital_substrate import BornDigitalSubstrate
from app.services.document_system.config_registry import get_family_config_registry
from app.services.document_system.contracts import (
    BlockGraphV1,
    BlockNodeV1,
    BlockRoleV1,
    PageKindV2,
    PageParseArtifactV4,
    PageParseBlockV4,
)
from app.services.document_system.document_router import DocumentRouteInput, DocumentRouter
from app.services.document_system.document_splitter import DocumentSplitter, PageRoutingHint
from app.services.document_system.page_classifier import PageClassifier
from app.services.document_system.row_assembler import RowAssemblerV3
from app.services.parser import _assert_lab_page_line_structure, _should_skip_page_for_normalization
from app.services.parser.born_digital_parser import BornDigitalParser


def _build_text_pdf(lines: list[str], *, pages: int = 1) -> bytes:
    objects: list[bytes] = []
    page_object_numbers: list[int] = []
    next_object_number = 3

    for _page_index in range(pages):
        content_lines = ["BT", "/F1 12 Tf", "72 720 Td"]
        for index, line in enumerate(lines):
            escaped_line = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            if index:
                content_lines.append("0 -18 Td")
            content_lines.append(f"({escaped_line}) Tj")
        content_lines.append("ET")
        stream = "\n".join(content_lines).encode()

        page_object_number = next_object_number
        content_object_number = next_object_number + 1
        next_object_number += 2
        page_object_numbers.append(page_object_number)

        objects.append(
            f"{page_object_number} 0 obj\n"
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {next_object_number} 0 R >> >> "
            f"/Contents {content_object_number} 0 R >>\n"
            "endobj\n".encode()
        )
        objects.append(
            f"{content_object_number} 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode()
            + stream
            + b"\nendstream\nendobj\n"
        )

    font_object_number = next_object_number
    kids = " ".join(f"{number} 0 R" for number in page_object_numbers)

    header_objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        f"2 0 obj\n<< /Type /Pages /Count {pages} /Kids [{kids}] >>\nendobj\n".encode(),
    ]

    objects = header_objects + objects
    objects.append(
        (
            f"{font_object_number} 0 obj\n"
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"
            "endobj\n"
        ).encode()
    )

    buffer = BytesIO()
    buffer.write(f"%PDF-1.4\n%fixture:{uuid4()}\n".encode())
    offsets = [0]
    for obj in objects:
        offsets.append(buffer.tell())
        buffer.write(obj)

    xref_offset = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode())
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.write(f"{offset:010d} 00000 n \n".encode())
    buffer.write(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            "startxref\n"
            f"{xref_offset}\n"
            "%%EOF\n"
        ).encode()
    )
    return buffer.getvalue()


def test_phase_44_registry_loads_versioned_config() -> None:
    registry = get_family_config_registry()
    assert registry.contract_version == "family-config-registry-v1"
    assert registry.version
    assert "lab_signals" in registry.route_hints


def test_phase_44_document_router_detects_non_lab_medical() -> None:
    decision = DocumentRouter().decide(
        DocumentRouteInput(
            checksum="abc",
            extension=".pdf",
            mime_type="application/pdf",
            page_count=2,
            image_density=0.1,
            text_extractability=0.9,
            has_text_layer=True,
            has_image_layer=False,
            total_text_chars=800,
            password_protected=False,
            corrupt=False,
                text_sample="Ultrasound report impression recommendation abdominal imaging",
        )
    )

    assert decision.lane_type.value in {"non_lab_medical", "interpreted_summary"}
    assert decision.runtime_lane_type == "unsupported"


def test_phase_44_document_router_detects_image_pdf_lab() -> None:
    decision = DocumentRouter().decide(
        DocumentRouteInput(
            checksum="abc",
            extension=".pdf",
            mime_type="application/pdf",
            page_count=1,
            image_density=0.92,
            text_extractability=0.08,
            has_text_layer=False,
            has_image_layer=True,
            total_text_chars=0,
            password_protected=False,
            corrupt=False,
            text_sample="",
        )
    )

    assert decision.lane_type.value == "image_pdf_lab"
    assert decision.runtime_lane_type == "image_beta"


def test_phase_44_document_router_detects_composite_packet_on_multipage_marker() -> None:
    decision = DocumentRouter().decide(
        DocumentRouteInput(
            checksum="abc",
            extension=".pdf",
            mime_type="application/pdf",
            page_count=8,
            image_density=0.34,
            text_extractability=0.66,
            has_text_layer=True,
            has_image_layer=True,
            total_text_chars=15000,
            password_protected=False,
            corrupt=False,
            text_sample="CardioIQ annotation report with glucose cholesterol and merged report appendix",
        )
    )

    assert decision.lane_type.value == "composite_packet"


def test_phase_44_document_router_keeps_scanned_composite_like_pdf_on_image_lane() -> None:
    decision = DocumentRouter().decide(
        DocumentRouteInput(
            checksum="abc",
            extension=".pdf",
            mime_type="application/pdf",
            page_count=12,
            image_density=1.0,
            text_extractability=0.0,
            has_text_layer=True,
            has_image_layer=True,
            total_text_chars=120,
            password_protected=False,
            corrupt=False,
            text_sample=(
                "ultrasound pathology report glucose sodium potassium chloride "
                "analyte result unit reference range chemistry panel"
            ),
        )
    )

    assert decision.lane_type.value == "image_pdf_lab"
    assert decision.runtime_lane_type == "image_beta"


def test_phase_44_document_router_detects_interpreted_summary_on_large_multipage_health_report() -> None:
    decision = DocumentRouter().decide(
        DocumentRouteInput(
            checksum="abc",
            extension=".pdf",
            mime_type="application/pdf",
            page_count=20,
            image_density=0.05,
            text_extractability=0.95,
            has_text_layer=True,
            has_image_layer=True,
            total_text_chars=30000,
            password_protected=False,
            corrupt=False,
            text_sample="Health report clinical summary action plan with glucose cholesterol and medical report sections",
        )
    )

    assert decision.lane_type.value == "interpreted_summary"
    assert decision.runtime_lane_type == "unsupported"


def test_phase_44_document_router_prioritizes_synthesized_health_summary() -> None:
    decision = DocumentRouter().decide(
        DocumentRouteInput(
            checksum="abc",
            extension=".pdf",
            mime_type="application/pdf",
            page_count=26,
            image_density=0.05,
            text_extractability=0.95,
            has_text_layer=True,
            has_image_layer=True,
            total_text_chars=29837,
            password_protected=False,
            corrupt=False,
            text_sample=(
                "Personal Health Report clinical summary recommendation action plan "
                "includes glucose cholesterol hemoglobin trends and age context"
            ),
        )
    )

    assert decision.lane_type.value == "interpreted_summary"
    assert decision.document_class == "interpreted_summary"
    assert decision.runtime_lane_type == "unsupported"


def test_phase_44_document_router_routes_scanned_composite_packet_to_image_lane() -> None:
    decision = DocumentRouter().decide(
        DocumentRouteInput(
            checksum="abc",
            extension=".pdf",
            mime_type="application/pdf",
            page_count=3,
            image_density=1.0,
            text_extractability=0.0,
            has_text_layer=True,
            has_image_layer=True,
            total_text_chars=120,
            password_protected=False,
            corrupt=False,
            text_sample=(
                "ultrasound radiology x-ray report with urinalysis glucose protein result unit reference range"
            ),
        )
    )

    assert decision.lane_type.value == "image_pdf_lab"
    assert decision.runtime_lane_type == "image_beta"
    assert decision.document_class == "composite_packet"


def test_phase_44_page_classifier_threshold_reference() -> None:
    classification = PageClassifier().classify(
        "Prediabetes IFG risk category target range normal high low"
    )
    assert classification.page_kind in {PageKindV2.THRESHOLD_REFERENCE, PageKindV2.LAB_RESULTS}


def test_phase_44_document_splitter_groups_contiguous_page_classes() -> None:
    router = DocumentRouter().decide(
        DocumentRouteInput(
            checksum="abc",
            extension=".pdf",
            mime_type="application/pdf",
            page_count=3,
            image_density=0.1,
            text_extractability=0.9,
            has_text_layer=True,
            has_image_layer=False,
            total_text_chars=1000,
            password_protected=False,
            corrupt=False,
            text_sample="glucose result",
        )
    )

    packet = DocumentSplitter().split(
        checksum="abc",
        route_decision=router,
        page_hints=[
            PageRoutingHint(page_number=1, page_kind=PageKindV2.ADMIN_METADATA, confidence=0.8),
            PageRoutingHint(page_number=2, page_kind=PageKindV2.LAB_RESULTS, confidence=0.9),
            PageRoutingHint(page_number=3, page_kind=PageKindV2.LAB_RESULTS, confidence=0.9),
        ],
    )

    assert packet.contract_version == "document-packet-v1"
    assert len(packet.page_groups) == 2


def test_phase_44_born_digital_substrate_emits_v4() -> None:
    pdf_bytes = _build_text_pdf([
        "Glucose 180 mg/dL",
        "Reference range 70-99",
        "HbA1c 6.8 %",
    ])

    artifacts = BornDigitalSubstrate().parse(pdf_bytes, source_file_path="fixture.pdf")
    assert len(artifacts) == 1

    artifact = artifacts[0]
    assert isinstance(artifact, PageParseArtifactV4)
    assert artifact.backend_id == "pymupdf"
    assert artifact.contract_version == "page-parse-v4"
    assert artifact.page_number == 1
    assert artifact.blocks


def test_phase_44_block_graph_builder_links_nodes() -> None:
    artifact = PageParseArtifactV4(
        page_id="doc:1",
        page_number=1,
        backend_id="pymupdf",
        backend_version="1.0",
        lane_type="trusted_pdf",
        page_kind=PageKindV2.LAB_RESULTS,
        blocks=[
            PageParseBlockV4(
                block_id="b1",
                block_role=BlockRoleV1.RESULT_BLOCK,
                raw_text="Glucose 180 mg/dL",
                lines=["Glucose 180 mg/dL"],
            ),
            PageParseBlockV4(
                block_id="b2",
                block_role=BlockRoleV1.RESULT_BLOCK,
                raw_text="HbA1c 6.8 %",
                lines=["HbA1c 6.8 %"],
            ),
        ],
        raw_text="Glucose 180 mg/dL\nHbA1c 6.8 %",
    )

    graph = BlockGraphBuilder().build(artifact)
    assert len(graph.nodes) == 2
    assert graph.edges
    assert graph.nodes[0].lines == ["Glucose 180 mg/dL"]
    assert graph.nodes[1].lines == ["HbA1c 6.8 %"]


def test_phase_44_parser_line_structure_assertion_raises_on_lost_multiline_arrays() -> None:
    graph = BlockGraphV1(
        page_id="doc:line-loss",
        page_number=1,
        nodes=[
            BlockNodeV1(
                node_id="n1",
                block_id="b1",
                block_role=BlockRoleV1.RESULT_BLOCK,
                text="Glucose 180 mg/dL HbA1c 6.8 %",
                page_number=1,
                reading_order=0,
                lines=[],
                metadata={"line_count": 2},
            ),
            BlockNodeV1(
                node_id="n2",
                block_id="b2",
                block_role=BlockRoleV1.RESULT_BLOCK,
                text="Sodium 141 mmol/L Potassium 4.0 mmol/L",
                page_number=1,
                reading_order=1,
                lines=[],
                metadata={"line_count": 2},
            ),
        ],
        edges=[],
    )

    with pytest.raises(ValueError, match="trusted_pdf_line_structure_lost"):
        _assert_lab_page_line_structure(graph, page_class="analyte_table_page")


def test_phase_44_page_fencing_skips_low_signal_non_lab_page() -> None:
    assert _should_skip_page_for_normalization(
        "non_lab_medical",
        metadata={
            "page_classification_evidence": {
                "numeric_token_density": 0.02,
                "table_density": 0.05,
            }
        },
    )


def test_phase_44_page_fencing_keeps_numeric_dense_non_lab_page_for_split_packets() -> None:
    assert not _should_skip_page_for_normalization(
        "non_lab_medical",
        metadata={
            "page_classification_evidence": {
                "numeric_token_density": 0.22,
                "table_density": 0.41,
            }
        },
    )


def test_phase_44_row_assembler_v3_builds_rows() -> None:
    artifact = PageParseArtifactV4(
        page_id="doc:1",
        page_number=1,
        backend_id="pymupdf",
        backend_version="1.0",
        lane_type="trusted_pdf",
        page_kind=PageKindV2.LAB_RESULTS,
        blocks=[
            PageParseBlockV4(
                block_id="b1",
                block_role=BlockRoleV1.RESULT_BLOCK,
                raw_text="Glucose 180 mg/dL 70-99",
                lines=["Glucose 180 mg/dL 70-99"],
            ),
            PageParseBlockV4(
                block_id="b2",
                block_role=BlockRoleV1.THRESHOLD_BLOCK,
                raw_text="Prediabetes 100-125",
                lines=["Prediabetes 100-125"],
            ),
        ],
        raw_text="Glucose 180 mg/dL 70-99\nPrediabetes 100-125",
    )

    graph = BlockGraphBuilder().build(artifact)
    rows, suppression = RowAssemblerV3().assemble(
        block_graph=graph,
        artifact=artifact,
        family_adapter_id="generic_layout",
        page_class="analyte_table_page",
    )

    assert rows
    assert suppression.contract_version == "suppression-report-v1"
    assert any(
        row.row_type.value in {"measured_analyte_row", "threshold_reference_row"}
        for row in rows
    )


def test_phase_44_row_assembler_v3_excludes_unknown_non_result_blocks() -> None:
    artifact = PageParseArtifactV4(
        page_id="doc:unknown-block",
        page_number=1,
        backend_id="pymupdf",
        backend_version="1.0",
        lane_type="trusted_pdf",
        page_kind=PageKindV2.LAB_RESULTS,
        blocks=[
            PageParseBlockV4(
                block_id="u1",
                block_role=BlockRoleV1.UNKNOWN_BLOCK,
                raw_text="Final Diagnosis: Chronic inflammatory changes",
                lines=["Final Diagnosis: Chronic inflammatory changes"],
                metadata={
                    "block_classification_evidence": {
                        "numeric_token_density": 0.0,
                        "threshold_pattern_density": 0.0,
                    }
                },
            ),
        ],
        raw_text="Final Diagnosis: Chronic inflammatory changes",
    )

    graph = BlockGraphBuilder().build(artifact)
    rows, _suppression = RowAssemblerV3().assemble(
        block_graph=graph,
        artifact=artifact,
        family_adapter_id="generic_layout",
        page_class="analyte_table_page",
    )

    assert len(rows) == 1
    assert rows[0].support_code == "excluded"
    assert rows[0].failure_code == "unknown_block_non_result"


def test_phase_44_artifact_policy_hides_internal_markers() -> None:
    result = ArtifactPolicy().sanitize_not_assessed(
        [
            {"raw_label": "DOB", "reason": "admin_metadata_row"},
            {"raw_label": "glucose", "reason": "unsupported_family"},
            {"raw_label": "glucose", "reason": "unsupported_family"},
        ]
    )

    assert len(result.not_assessed) == 1
    assert result.not_assessed[0]["reason"] == "unsupported_family"


def test_phase_44_born_digital_parser_v3_compatibility() -> None:
    pdf_bytes = _build_text_pdf(["Glucose 180 mg/dL", "HbA1c 6.8 %"])
    parser = BornDigitalParser()
    artifacts_v3 = parser.parse(pdf_bytes, source_file_path="fixture.pdf")
    artifacts_v4 = parser.parse_v4(pdf_bytes, source_file_path="fixture.pdf")

    assert len(artifacts_v3) == len(artifacts_v4)
    assert artifacts_v3[0].backend_id == "pymupdf"
