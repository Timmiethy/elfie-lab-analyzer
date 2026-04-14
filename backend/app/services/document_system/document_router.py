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
        high_signal_composite_score = _keyword_score(
            normalized_text,
            (
                "cardioiq",
                "cardio iq",
                "cardioiq annotation",
                "mayo clinic",
                "merged report",
                "multiple reports",
            ),
        )
        admin_score = _keyword_score(normalized_text, self._registry.route_keywords("admin_markers"))

        scanned_structure = _is_scanned_structure(route_input)
        text_rich_structure = _is_text_rich_structure(route_input)
        mixed_structure = route_input.has_text_layer and route_input.has_image_layer

        if non_lab_score >= max(summary_score, lab_score + 1) and non_lab_score >= 2:
            reason_codes.extend(["non_lab_medical_keywords", f"non_lab_score:{non_lab_score}"])
            return self._finalize(
                lane_type=RouteLaneType.NON_LAB_MEDICAL,
                route_input=route_input,
                document_class="non_lab_medical",
                confidence=_confidence_from_scores(non_lab_score, lab_score, summary_score),
                reason_codes=reason_codes,
            )

        if summary_score > lab_score and summary_score >= 2 and non_lab_score < summary_score:
            reason_codes.extend(["interpreted_summary_keywords", f"summary_score:{summary_score}"])
            return self._finalize(
                lane_type=RouteLaneType.INTERPRETED_SUMMARY,
                route_input=route_input,
                document_class="interpreted_summary",
                confidence=_confidence_from_scores(summary_score, lab_score, non_lab_score),
                reason_codes=reason_codes,
            )

        # Synthesized health reports often include copied lab terms but should
        # still route to interpreted summary artifacts rather than raw-lab flow.
        if (
            summary_score >= 2
            and "health report" in normalized_text
            and route_input.page_count >= 10
            and admin_score <= 1
            and non_lab_score <= 1
        ):
            reason_codes.extend([
                "synthesized_health_summary_keywords",
                f"summary_score:{summary_score}",
                f"lab_score:{lab_score}",
            ])
            return self._finalize(
                lane_type=RouteLaneType.INTERPRETED_SUMMARY,
                route_input=route_input,
                document_class="interpreted_summary",
                confidence=_confidence_from_scores(summary_score + 1, lab_score, non_lab_score),
                reason_codes=reason_codes,
            )

        composite_semantic_signal = (
            composite_score >= 2
            or high_signal_composite_score >= 1
            or non_lab_score >= 3
            or (summary_score >= 2 and non_lab_score >= 2)
        )
        composite_structure_signal = (
            (route_input.text_extractability >= 0.5 and route_input.image_density <= 0.5)
            or non_lab_score >= 3
        )
        if (
            lab_score > 0
            and route_input.page_count > 1
            and scanned_structure
            and composite_semantic_signal
        ):
            reason_codes.extend([
                "composite_packet_scanned_structure",
                f"lab_score:{lab_score}",
                f"summary_score:{summary_score}",
                f"non_lab_score:{non_lab_score}",
                f"composite_score:{composite_score}",
                f"high_signal_composite_score:{high_signal_composite_score}",
            ])
            if mixed_structure:
                reason_codes.append("mixed_text_and_image_structure")
            return self._finalize(
                lane_type=RouteLaneType.IMAGE_PDF_LAB,
                route_input=route_input,
                document_class="composite_packet",
                confidence=_confidence_from_scores(lab_score + composite_score, summary_score, non_lab_score),
                reason_codes=reason_codes,
            )
        if (
            lab_score > 0
            and route_input.page_count > 1
            and text_rich_structure
            and not scanned_structure
            and composite_semantic_signal
            and composite_structure_signal
        ):
            reason_codes.extend([
                "composite_packet_signals",
                f"lab_score:{lab_score}",
                f"summary_score:{summary_score}",
                f"non_lab_score:{non_lab_score}",
                f"composite_score:{composite_score}",
                f"high_signal_composite_score:{high_signal_composite_score}",
            ])
            if mixed_structure:
                reason_codes.append("mixed_text_and_image_structure")
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

        if route_input.total_text_chars == 0 and not route_input.has_image_layer:
            reason_codes.extend([
                "no_extractable_text_layer",
                "trusted_parse_required_for_honest_failure",
            ])
            return self._finalize(
                lane_type=RouteLaneType.TRUSTED_PDF_LAB,
                route_input=route_input,
                document_class="trusted_pdf_lab",
                confidence=0.0,
                reason_codes=reason_codes,
            )

        if lab_score > 0:
            reason_codes.extend([f"lab_score:{lab_score}", f"summary_score:{summary_score}", f"non_lab_score:{non_lab_score}"])
            if scanned_structure:
                reason_codes.append("semantic_lab_scanned_structure")
                return self._finalize(
                    lane_type=RouteLaneType.IMAGE_PDF_LAB,
                    route_input=route_input,
                    document_class="image_pdf_lab",
                    confidence=_confidence_from_scores(lab_score, summary_score, non_lab_score),
                    reason_codes=reason_codes,
                )

            reason_codes.append("semantic_lab_text_structure")
            return self._finalize(
                lane_type=RouteLaneType.TRUSTED_PDF_LAB,
                route_input=route_input,
                document_class="trusted_pdf_lab",
                confidence=_confidence_from_scores(lab_score, summary_score, non_lab_score),
                reason_codes=reason_codes,
            )

        if scanned_structure:
            reason_codes.extend([
                "scanned_document_needs_ocr_classification",
                f"image_density:{route_input.image_density}",
                f"text_extractability:{route_input.text_extractability}",
            ])
            return self._finalize(
                lane_type=RouteLaneType.IMAGE_PDF_LAB,
                route_input=route_input,
                document_class="image_pdf_lab",
                confidence=_confidence_from_scores(max(admin_score, 1), summary_score, non_lab_score),
                reason_codes=reason_codes,
            )

        if text_rich_structure and lab_score == 0:
            reason_codes.extend([
                "no_lab_semantic_signals",
                f"summary_score:{summary_score}",
                f"non_lab_score:{non_lab_score}",
                f"admin_score:{admin_score}",
            ])
            return self._finalize(
                lane_type=RouteLaneType.UNSUPPORTED,
                route_input=route_input,
                document_class="unsupported",
                confidence=_confidence_from_scores(max(summary_score, non_lab_score, admin_score, 1), lab_score, composite_score),
                reason_codes=reason_codes,
            )

        # Low-signal fallback keeps unknown PDFs safe instead of forcing lab normalization.
        reason_codes.extend([
            "low_signal_pdf_fallback",
            f"lab_score:{lab_score}",
            f"summary_score:{summary_score}",
            f"non_lab_score:{non_lab_score}",
            f"image_density:{route_input.image_density}",
            f"text_extractability:{route_input.text_extractability}",
        ])
        return self._finalize(
            lane_type=RouteLaneType.UNSUPPORTED,
            route_input=route_input,
            document_class="unsupported",
            confidence=_confidence_from_scores(max(admin_score, 1), summary_score, non_lab_score),
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


def _is_scanned_structure(route_input: DocumentRouteInput) -> bool:
    if route_input.extension in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        return True
    if route_input.has_image_layer and not route_input.has_text_layer:
        return True
    if route_input.has_image_layer and route_input.total_text_chars < 64 and route_input.text_extractability < 0.4:
        return True
    if route_input.has_image_layer and route_input.image_density >= 0.5 and route_input.total_text_chars < 512:
        return True
    if route_input.image_density >= 0.8 and route_input.total_text_chars < 128:
        return True
    return False


def _is_text_rich_structure(route_input: DocumentRouteInput) -> bool:
    return route_input.has_text_layer and route_input.total_text_chars >= 64
