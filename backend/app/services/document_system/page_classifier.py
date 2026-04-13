from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .config_registry import FamilyConfigRegistry, get_family_config_registry
from .contracts import PageKindV2


@dataclass(frozen=True)
class PageClassificationV2:
    page_kind: PageKindV2
    confidence: float
    reason_codes: list[str]


class PageClassifier:
    def __init__(self, registry: FamilyConfigRegistry | None = None) -> None:
        self._registry = registry or get_family_config_registry()

    def classify(self, text: str, *, block_texts: Iterable[str] | None = None) -> PageClassificationV2:
        normalized = _normalize(text)
        candidate_texts = [normalized]
        if block_texts is not None:
            candidate_texts.extend(_normalize(value) for value in block_texts if _normalize(value))

        scores: dict[PageKindV2, int] = {
            PageKindV2.LAB_RESULTS: _score(candidate_texts, self._registry.page_keywords("lab_results")),
            PageKindV2.THRESHOLD_REFERENCE: _score(candidate_texts, self._registry.page_keywords("threshold_reference")),
            PageKindV2.ADMIN_METADATA: _score(candidate_texts, self._registry.page_keywords("admin_metadata")),
            PageKindV2.NARRATIVE_GUIDANCE: _score(candidate_texts, self._registry.page_keywords("narrative_guidance")),
            PageKindV2.INTERPRETED_SUMMARY: _score(candidate_texts, self._registry.page_keywords("interpreted_summary")),
            PageKindV2.NON_LAB_MEDICAL: _score(candidate_texts, self._registry.page_keywords("non_lab_medical")),
            PageKindV2.FOOTER_HEADER: _score(candidate_texts, self._registry.page_keywords("footer_header")),
            PageKindV2.UNKNOWN: 0,
        }

        top_kind = max(scores, key=scores.get)
        top_score = scores[top_kind]
        total = sum(scores.values()) or 1
        confidence = round(top_score / total, 3)

        if top_score == 0:
            return PageClassificationV2(
                page_kind=PageKindV2.UNKNOWN,
                confidence=0.0,
                reason_codes=["page_no_keyword_match"],
            )

        reason_codes = [f"page_kind:{top_kind.value}", f"score:{top_score}"]
        if top_kind == PageKindV2.LAB_RESULTS and scores[PageKindV2.THRESHOLD_REFERENCE] > 0:
            reason_codes.append("mixed_lab_and_threshold_signals")

        return PageClassificationV2(
            page_kind=top_kind,
            confidence=confidence,
            reason_codes=reason_codes,
        )


def _score(texts: list[str], keywords: tuple[str, ...]) -> int:
    score = 0
    for text in texts:
        for keyword in keywords:
            if keyword in text:
                score += 1
    return score


def _normalize(value: str) -> str:
    return " ".join(str(value or "").lower().split())
