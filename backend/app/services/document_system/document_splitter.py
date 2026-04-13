from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable

from .contracts import (
    DocumentPacketV1,
    DocumentPageGroupV1,
    DocumentRouteDecision,
    PageKindV2,
    RouteLaneType,
)


@dataclass(frozen=True)
class PageRoutingHint:
    page_number: int
    page_kind: PageKindV2
    confidence: float


class DocumentSplitter:
    """Split a routed document into logical page groups with lineage."""

    def split(
        self,
        *,
        checksum: str,
        route_decision: DocumentRouteDecision,
        page_hints: Iterable[PageRoutingHint],
    ) -> DocumentPacketV1:
        hints = sorted(list(page_hints), key=lambda hint: hint.page_number)
        page_groups: list[DocumentPageGroupV1] = []
        current_pages: list[int] = []
        current_class = ""
        current_lane = route_decision.lane_type

        for hint in hints:
            group_class, group_lane = _classify_page_group(hint.page_kind, route_decision.lane_type)
            if not current_pages:
                current_pages = [hint.page_number]
                current_class = group_class
                current_lane = group_lane
                continue

            if group_class == current_class and group_lane == current_lane:
                current_pages.append(hint.page_number)
                continue

            page_groups.append(
                _materialize_group(
                    checksum=checksum,
                    page_numbers=current_pages,
                    document_class=current_class,
                    lane_type=current_lane,
                )
            )
            current_pages = [hint.page_number]
            current_class = group_class
            current_lane = group_lane

        if current_pages:
            page_groups.append(
                _materialize_group(
                    checksum=checksum,
                    page_numbers=current_pages,
                    document_class=current_class,
                    lane_type=current_lane,
                )
            )

        packet_id = sha256(f"packet:{checksum}:{route_decision.lane_type.value}".encode("utf-8")).hexdigest()[:24]
        return DocumentPacketV1(
            packet_id=packet_id,
            parent_checksum=checksum,
            route_decision=route_decision,
            page_groups=page_groups,
        )


def _classify_page_group(page_kind: PageKindV2, default_lane: RouteLaneType) -> tuple[str, RouteLaneType]:
    if page_kind == PageKindV2.INTERPRETED_SUMMARY:
        return ("interpreted_summary", RouteLaneType.INTERPRETED_SUMMARY)
    if page_kind == PageKindV2.NON_LAB_MEDICAL:
        return ("non_lab_medical", RouteLaneType.NON_LAB_MEDICAL)
    if page_kind in {PageKindV2.LAB_RESULTS, PageKindV2.THRESHOLD_REFERENCE}:
        if default_lane == RouteLaneType.IMAGE_PDF_LAB:
            return ("image_pdf_lab", RouteLaneType.IMAGE_PDF_LAB)
        return ("trusted_pdf_lab", RouteLaneType.TRUSTED_PDF_LAB)
    if page_kind == PageKindV2.ADMIN_METADATA:
        return ("admin_metadata", default_lane)
    if page_kind == PageKindV2.NARRATIVE_GUIDANCE:
        return ("narrative_guidance", default_lane)
    if page_kind == PageKindV2.FOOTER_HEADER:
        return ("footer_header", default_lane)
    return ("unknown", default_lane)


def _materialize_group(
    *,
    checksum: str,
    page_numbers: list[int],
    document_class: str,
    lane_type: RouteLaneType,
) -> DocumentPageGroupV1:
    source = f"{checksum}:{document_class}:{lane_type.value}:{','.join(str(value) for value in page_numbers)}"
    group_id = sha256(source.encode("utf-8")).hexdigest()[:16]
    return DocumentPageGroupV1(
        group_id=group_id,
        page_numbers=page_numbers,
        document_class=document_class,
        lane_type=lane_type,
        reason_codes=[f"group_class:{document_class}", f"group_lane:{lane_type.value}"],
    )
