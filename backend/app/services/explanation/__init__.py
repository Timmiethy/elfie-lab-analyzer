"""Explanation adapter: bounded Qwen output (blueprint section 3.11).

Input: structured findings only. No raw source document context.
Output: headline, finding bullets, paragraph, next-step sentence, disclaimer.
Falls back to deterministic templates on failure.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.schemas.finding import FindingSchema

_LOCALIZED_COPY = {
    "en": {
        "headline": "Structured findings summary",
        "empty_headline": "No structured findings to explain",
        "intro": "This explanation only restates the structured findings that are already present.",
        "summary_suffix_singular": "structured finding is included in this summary.",
        "summary_suffix_plural": "structured findings are included in this summary.",
        "empty_intro": "No valid structured findings were provided, so this adapter cannot summarize them safely.",
        "next_step": "The next-step class attached to the finding is restated here without being changed.",
        "nextstep_values_prefix": "Existing next-step class values:",
        "empty_next_step": "No next-step sentence is available because there are no findings to describe.",
        "disclaimer": "This content is descriptive only and does not assign, change, or override severity or next-step logic.",
        "invalid_notice": "Some findings could not be normalized safely and were skipped.",
        "finding_label": "Finding",
        "observed_value": "observed",
        "severity_class": "severity class",
        "nextstep_class": "next-step class",
        "threshold_source": "threshold source",
        "suppressed": "suppressed",
        "unsupported_sentence": "Some items are not supported by the terminology tables and are shown separately for review.",
        "threshold_provenance_sentence": "Each threshold comes from a recorded source that can be audited.",
    },
    "vi": {
        "headline": "Tóm tắt các phát hiện có cấu trúc",
        "empty_headline": "Không có phát hiện có cấu trúc để diễn giải",
        "intro": "Phần diễn giải này chỉ nhắc lại các phát hiện có cấu trúc đang có sẵn.",
        "summary_suffix_singular": "phát hiện có cấu trúc được đưa vào phần tóm tắt này.",
        "summary_suffix_plural": "phát hiện có cấu trúc được đưa vào phần tóm tắt này.",
        "empty_intro": "Không có phát hiện có cấu trúc hợp lệ, nên adapter này không thể tóm tắt an toàn.",
        "next_step": "Bước tiếp theo gắn với phát hiện được nhắc lại ở đây mà không bị thay đổi.",
        "nextstep_values_prefix": "Các giá trị bước tiếp theo hiện có:",
        "empty_next_step": "Không có câu về bước tiếp theo vì không có phát hiện nào để mô tả.",
        "disclaimer": "Nội dung này chỉ mang tính mô tả và không gán, thay đổi, hoặc ghi đè logic về mức độ hay bước tiếp theo.",
        "invalid_notice": "Một số phát hiện không thể được chuẩn hóa an toàn và đã bị bỏ qua.",
        "finding_label": "Phát hiện",
        "observed_value": "ghi nhận",
        "severity_class": "mức độ",
        "nextstep_class": "bước tiếp theo",
        "threshold_source": "nguồn ngưỡng",
        "suppressed": "bị ẩn",
        "unsupported_sentence": "Một số mục không được hỗ trợ bởi bảng thuật ngữ và được hiển thị riêng để xem xét.",
        "threshold_provenance_sentence": "Mỗi ngưỡng đến từ nguồn được ghi lại và có thể kiểm tra lại.",
    },
}


class ExplanationAdapter:
    async def generate(self, findings: list[dict], language: str) -> dict:
        language_id = self._normalize_language(language)
        normalized_findings, invalid_count = self._normalize_findings(findings)
        prompt_payload = self._build_prompt_payload(normalized_findings, language_id)

        model_result = await self._generate_with_model(prompt_payload)
        if model_result is not None:
            return model_result

        return self._render_fallback(normalized_findings, language_id, invalid_count)

    @staticmethod
    def _normalize_language(language: str | None) -> str:
        raw_language = str(language or "").strip().lower().replace("_", "-")
        if not raw_language:
            return "en"
        primary = raw_language.split("-", 1)[0]
        return primary if primary in _LOCALIZED_COPY else "en"

    @staticmethod
    def _normalize_findings(findings: list[dict]) -> tuple[list[dict], int]:
        normalized: list[dict] = []
        invalid_count = 0

        for finding in findings or []:
            try:
                validated = FindingSchema.model_validate(finding)
            except ValidationError:
                invalid_count += 1
                continue

            normalized_finding = validated.model_dump(mode="json")
            if isinstance(finding, dict):
                normalized_finding.update(
                    {key: value for key, value in finding.items() if key not in normalized_finding}
                )
            normalized.append(normalized_finding)

        normalized.sort(key=ExplanationAdapter._sort_key)
        return normalized, invalid_count

    @staticmethod
    def _sort_key(finding: dict) -> tuple[str, str, str]:
        return (
            str(finding.get("finding_id") or ""),
            str(finding.get("rule_id") or ""),
            str(finding.get("threshold_source") or ""),
        )

    @staticmethod
    def _build_prompt_payload(findings: list[dict], language_id: str) -> dict:
        return {
            "language_id": language_id,
            "findings": findings,
            "finding_count": len(findings),
        }

    async def _generate_with_model(self, prompt_payload: dict[str, Any]) -> dict | None:
        """Future hook for model-backed generation.

        The current implementation always falls back to deterministic copy.
        """

        return None

    def _render_fallback(self, findings: list[dict], language_id: str, invalid_count: int) -> dict:
        copy = _LOCALIZED_COPY[language_id]
        if not findings:
            return {
                "language_id": language_id,
                "headline": copy["empty_headline"],
                "finding_bullets": [],
                "paragraph": copy["empty_intro"],
                "next_step_sentence": copy["empty_next_step"],
                "unsupported_sentence": copy["unsupported_sentence"],
                "threshold_provenance_sentence": copy["threshold_provenance_sentence"],
                "disclaimer": self._join_disclaimer(copy, invalid_count),
                "generation_source": "fallback",
            }

        bullets = [self._render_finding_bullet(finding, copy) for finding in findings]
        headline = copy["headline"]
        paragraph = self._render_paragraph(findings, copy)
        next_step_sentence = self._render_next_step_sentence(findings, copy)

        return {
            "language_id": language_id,
            "headline": headline,
            "finding_bullets": bullets,
            "paragraph": paragraph,
            "next_step_sentence": next_step_sentence,
            "unsupported_sentence": copy["unsupported_sentence"],
            "threshold_provenance_sentence": copy["threshold_provenance_sentence"],
            "disclaimer": self._join_disclaimer(copy, invalid_count),
            "generation_source": "fallback",
        }

    @staticmethod
    def _render_finding_bullet(finding: dict, copy: dict[str, str]) -> str:
        label = (
            finding.get("explanatory_scaffold_id")
            or finding.get("rule_id")
            or copy["finding_label"]
        )
        parts = [f"{label}:"]

        observed_value = finding.get("observed_value")
        observed_unit = finding.get("observed_unit")
        if observed_value is not None:
            value_text = str(observed_value)
            if observed_unit:
                value_text = f"{value_text} {observed_unit}"
            parts.append(f"{copy['observed_value']} {value_text}")

        severity_class = finding.get("severity_class")
        nextstep_class = finding.get("nextstep_class")
        if severity_class is not None:
            parts.append(f"{copy['severity_class']} {severity_class}")
        if nextstep_class is not None:
            parts.append(f"{copy['nextstep_class']} {nextstep_class}")

        threshold_source = finding.get("threshold_source")
        if threshold_source:
            parts.append(f"{copy['threshold_source']} {threshold_source}")

        if finding.get("suppression_active"):
            reason = finding.get("suppression_reason")
            parts.append(f"{copy['suppressed']}{f': {reason}' if reason else ''}")

        return ", ".join(parts) + "."

    @staticmethod
    def _render_paragraph(findings: list[dict], copy: dict[str, str]) -> str:
        count = len(findings)
        suffix = copy["summary_suffix_singular"] if count == 1 else copy["summary_suffix_plural"]
        return f"{copy['intro']} {count} {suffix}"

    @staticmethod
    def _render_next_step_sentence(findings: list[dict], copy: dict[str, str]) -> str:
        if not findings:
            return copy["empty_next_step"]
        classes = sorted(
            {
                str(finding.get("nextstep_class"))
                for finding in findings
                if finding.get("nextstep_class") is not None
            }
        )
        if not classes:
            return copy["next_step"]
        joined = ", ".join(classes)
        return f"{copy['next_step']} {copy['nextstep_values_prefix']} {joined}."

    @staticmethod
    def _join_disclaimer(copy: dict[str, str], invalid_count: int) -> str:
        disclaimer = copy["disclaimer"]
        if invalid_count:
            disclaimer = f"{disclaimer} {copy['invalid_notice']}"
        return disclaimer
