from __future__ import annotations

from dataclasses import dataclass

from .config_registry import FamilyConfigRegistry, get_family_config_registry
from .contracts import DocumentRouteDecision, RouteLaneType, route_lane_to_runtime_lane


@dataclass(frozen=True)
class DocumentRouteInput:
    checksum: str
    extension: str
    mime_type: str
    page_count: int
    image_density: float
    text_extractability: float
    has_text_layer: bool
    has_image_layer: bool
    total_text_chars: int
    password_protected: bool
    corrupt: bool
    text_sample: str = ""


class DocumentRouter:
    def __init__(
        self,
        *,
        registry: FamilyConfigRegistry | None = None,
        image_density_threshold: float = 0.35,
        text_extractability_threshold: float = 0.65,
    ) -> None:
        self._registry = registry or get_family_config_registry()
        self._image_density_threshold = image_density_threshold
        self._text_extractability_threshold = text_extractability_threshold

    def decide(self, route_input: DocumentRouteInput) -> DocumentRouteDecision:
        reason_codes: list[str] = []

        if route_input.password_protected:
            return self._finalize(
                lane_type=RouteLaneType.UNSUPPORTED,
                route_input=route_input,
                document_class="unsupported",
                confidence=1.0,
                reason_codes=["pdf_password_protected"],
            )

        if route_input.corrupt or route_input.page_count == 0:
            return self._finalize(
                lane_type=RouteLaneType.UNSUPPORTED,
                route_input=route_input,
                document_class="unsupported",
                confidence=1.0,
                reason_codes=["pdf_corrupt_or_unreadable"],
            )

        normalized_text = _normalize(route_input.text_sample)
        lab_score = _keyword_score(normalized_text, self._registry.route_keywords("lab_signals"))
        summary_score = _keyword_score(normalized_text, self._registry.route_keywords("interpreted_summary"))
        non_lab_score = _keyword_score(normalized_text, self._registry.route_keywords("non_lab_medical"))
        composite_score = _keyword_score(normalized_text, self._registry.route_keywords("composite_markers"))
        admin_score = _keyword_score(normalized_text, self._registry.route_keywords("admin_markers"))

        if summary_score > lab_score and summary_score >= 2:
            reason_codes.extend(["interpreted_summary_keywords", f"summary_score:{summary_score}"])
            return self._finalize(
                lane_type=RouteLaneType.INTERPRETED_SUMMARY,
                route_input=route_input,
                document_class="interpreted_summary",
                confidence=_confidence_from_scores(summary_score, lab_score, non_lab_score),
                reason_codes=reason_codes,
            )

        if non_lab_score > lab_score and non_lab_score >= 2:
            reason_codes.extend(["non_lab_medical_keywords", f"non_lab_score:{non_lab_score}"])
            return self._finalize(
                lane_type=RouteLaneType.NON_LAB_MEDICAL,
                route_input=route_input,
                document_class="non_lab_medical",
                confidence=_confidence_from_scores(non_lab_score, lab_score, summary_score),
                reason_codes=reason_codes,
            )

        if lab_score > 0 and (summary_score > 0 or non_lab_score > 0 or composite_score > 0) and route_input.page_count > 1:
            reason_codes.extend([
                "composite_packet_signals",
                f"lab_score:{lab_score}",
                f"summary_score:{summary_score}",
                f"non_lab_score:{non_lab_score}",
                f"composite_score:{composite_score}",
            ])
            return self._finalize(
                lane_type=RouteLaneType.COMPOSITE_PACKET,
                route_input=route_input,
                document_class="composite_packet",
                confidence=_confidence_from_scores(lab_score + composite_score, summary_score, non_lab_score),
                reason_codes=reason_codes,
            )

        if route_input.extension in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
            reason_codes.append("image_file_route")
            return self._finalize(
                lane_type=RouteLaneType.IMAGE_PDF_LAB,
                route_input=route_input,
                document_class="image_pdf_lab",
                confidence=0.95,
                reason_codes=reason_codes,
            )

        image_like = (
            route_input.image_density >= self._image_density_threshold
            or route_input.text_extractability < self._text_extractability_threshold
        )

        if image_like:
            reason_codes.extend([
                "image_density_or_text_extractability_route",
                f"image_density:{route_input.image_density}",
                f"text_extractability:{route_input.text_extractability}",
                f"lab_score:{lab_score}",
            ])
            return self._finalize(
                lane_type=RouteLaneType.IMAGE_PDF_LAB,
                route_input=route_input,
                document_class="image_pdf_lab",
                confidence=_confidence_from_scores(max(lab_score, 1), admin_score, summary_score),
                reason_codes=reason_codes,
            )

        reason_codes.extend([
            "trusted_born_digital_route",
            f"lab_score:{lab_score}",
            f"admin_score:{admin_score}",
            f"image_density:{route_input.image_density}",
        ])
        return self._finalize(
            lane_type=RouteLaneType.TRUSTED_PDF_LAB,
            route_input=route_input,
            document_class="trusted_pdf_lab",
            confidence=_confidence_from_scores(max(lab_score, 1), summary_score, non_lab_score),
            reason_codes=reason_codes,
        )

    def _finalize(
        self,
        *,
        lane_type: RouteLaneType,
        route_input: DocumentRouteInput,
        document_class: str,
        confidence: float,
        reason_codes: list[str],
    ) -> DocumentRouteDecision:
        runtime_lane_type = route_lane_to_runtime_lane(lane_type)
        return DocumentRouteDecision(
            lane_type=lane_type,
            runtime_lane_type=runtime_lane_type,
            document_class=document_class,
            confidence=round(max(0.0, min(1.0, confidence)), 3),
            reason_codes=reason_codes,
            page_count=route_input.page_count,
            has_text_layer=route_input.has_text_layer,
            has_image_layer=route_input.has_image_layer,
            image_density=round(route_input.image_density, 3),
            text_extractability=round(route_input.text_extractability, 3),
            checksum=route_input.checksum,
        )


def _keyword_score(text: str, keywords: tuple[str, ...]) -> int:
    if not text:
        return 0
    return sum(1 for keyword in keywords if keyword in text)


def _confidence_from_scores(primary: int, secondary: int, tertiary: int) -> float:
    denominator = max(primary + secondary + tertiary, 1)
    return primary / denominator


def _normalize(value: str) -> str:
    return " ".join(str(value or "").lower().split())
