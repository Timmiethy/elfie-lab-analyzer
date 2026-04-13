from __future__ import annotations

from typing import Any

from .contracts import BlockRoleV1, PageParseArtifactV4, PageParseBlockV4, PageKindV2
from .page_classifier import PageClassifier


class OcrSubstrate:
    """Image/scanned substrate that emits PageParseArtifactV4.

    This substrate never upgrades OCR output into trusted born-digital status.
    """

    def __init__(self, page_classifier: PageClassifier | None = None) -> None:
        self._page_classifier = page_classifier or PageClassifier()

    def artifact_from_text(
        self,
        *,
        page_text: str,
        page_number: int,
        document_id: str,
        backend_id: str,
        backend_version: str,
        warnings: list[str] | None = None,
    ) -> PageParseArtifactV4:
        classification = self._page_classifier.classify(page_text)
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        block_role = _role_from_page_kind(classification.page_kind)

        block = PageParseBlockV4(
            block_id=f"ocr-page-{page_number}:block-000",
            block_role=block_role,
            raw_text=" ".join(lines),
            lines=lines,
            reading_order=0,
            language_tags=_language_candidates(page_text),
            metadata={"source": "ocr", "page_kind_confidence": classification.confidence},
        )

        return PageParseArtifactV4(
            page_id=f"ocr:{document_id}:page-{page_number}",
            page_number=page_number,
            backend_id=backend_id,
            backend_version=backend_version,
            lane_type="image_beta",
            page_kind=classification.page_kind,
            text_extractability=0.25 if lines else 0.0,
            language_candidates=_language_candidates(page_text),
            blocks=[block],
            tables=[],
            images=[{"source": "ocr_lane"}],
            raw_text=page_text,
            warnings=list(warnings or []),
            metadata={"reason_codes": classification.reason_codes},
        )

    def artifact_from_backend_result(
        self,
        *,
        backend_result: Any,
        page_number: int,
        document_id: str,
        backend_id: str,
        backend_version: str,
    ) -> PageParseArtifactV4:
        text = _extract_text_from_backend_result(backend_result)
        warnings = _extract_warnings_from_backend_result(backend_result)
        return self.artifact_from_text(
            page_text=text,
            page_number=page_number,
            document_id=document_id,
            backend_id=backend_id,
            backend_version=backend_version,
            warnings=warnings,
        )


def _role_from_page_kind(page_kind: PageKindV2) -> BlockRoleV1:
    if page_kind == PageKindV2.LAB_RESULTS:
        return BlockRoleV1.RESULT_BLOCK
    if page_kind == PageKindV2.THRESHOLD_REFERENCE:
        return BlockRoleV1.THRESHOLD_BLOCK
    if page_kind == PageKindV2.ADMIN_METADATA:
        return BlockRoleV1.ADMIN_BLOCK
    if page_kind in {PageKindV2.NARRATIVE_GUIDANCE, PageKindV2.INTERPRETED_SUMMARY, PageKindV2.NON_LAB_MEDICAL}:
        return BlockRoleV1.NARRATIVE_BLOCK
    if page_kind == PageKindV2.FOOTER_HEADER:
        return BlockRoleV1.HEADER_FOOTER_BLOCK
    return BlockRoleV1.UNKNOWN_BLOCK


def _extract_text_from_backend_result(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "raw_text", "content", "ocr_text"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text
        lines = value.get("lines")
        if isinstance(lines, list):
            return "\n".join(str(line) for line in lines if str(line).strip())
    if isinstance(value, list):
        return "\n".join(str(line) for line in value if str(line).strip())
    return ""


def _extract_warnings_from_backend_result(value: Any) -> list[str]:
    if isinstance(value, dict):
        warnings = value.get("warnings")
        if isinstance(warnings, list):
            return [str(item) for item in warnings]
    return []


def _language_candidates(text: str) -> list[str]:
    langs = ["en"]
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        langs.append("zh")
    return langs
