from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .config_registry import FamilyConfigRegistry, get_family_config_registry
from .contracts import BlockRoleV1, PageKindV2, SourceSpanV1

_RANGE_RE = re.compile(
    r"(?:[<>]=?|≤|≥)?\s*\d[\d,]*(?:\.\d+)?\s*(?:-|–|to)\s*(?:[<>]=?|≤|≥)?\s*\d[\d,]*(?:\.\d+)?",
    re.I,
)
_NUMERIC_RE = re.compile(r"(?:[<>]=?|≤|≥)?\s*\d[\d,]*(?:\.\d+)?")
_WORD_RE = re.compile(r"[A-Za-z\u00C0-\u024F\u4E00-\u9FFF0-9_/%.-]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")

_PAGE_EVIDENCE_VERSION = "page-classification-evidence-v1"
_BLOCK_EVIDENCE_VERSION = "block-classification-evidence-v1"


@dataclass(frozen=True)
class PageClassificationV2:
    page_kind: PageKindV2
    confidence: float
    reason_codes: list[str]
    evidence: PageClassificationEvidenceV1
    ambiguous: bool = False


@dataclass(frozen=True)
class BlockClassificationV1:
    block_role: BlockRoleV1
    confidence: float
    reason_codes: list[str]
    evidence: BlockClassificationEvidenceV1
    ambiguous: bool = False


@dataclass(frozen=True)
class PageClassificationEvidenceV1:
    contract_version: str
    block_position_score: float
    numeric_token_density: float
    table_density: float
    threshold_pattern_density: float
    admin_positional_signal: float
    header_footer_positional_signal: float
    bilingual_label_signal: float


@dataclass(frozen=True)
class BlockClassificationEvidenceV1:
    contract_version: str
    block_position_band: str
    numeric_token_density: float
    threshold_pattern_density: float
    admin_positional_signal: float
    header_footer_positional_signal: float
    bilingual_label_signal: float


class PageClassifier:
    def __init__(self, registry: FamilyConfigRegistry | None = None) -> None:
        self._registry = registry or get_family_config_registry()

    def classify(self, text: str, *, block_texts: Iterable[str] | None = None) -> PageClassificationV2:
        normalized = _normalize(text)
        candidate_texts = [normalized]
        if block_texts is not None:
            candidate_texts.extend(_normalize(value) for value in block_texts if _normalize(value))

        evidence = _build_page_evidence(
            normalized,
            candidate_texts,
            admin_keywords=self._registry.page_keywords("admin_metadata"),
            header_keywords=self._registry.page_keywords("footer_header"),
            threshold_keywords=self._registry.page_keywords("threshold_reference"),
        )

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

        if evidence.numeric_token_density >= 0.08:
            scores[PageKindV2.LAB_RESULTS] += 1
        if evidence.table_density >= 0.35:
            scores[PageKindV2.LAB_RESULTS] += 2
        if evidence.threshold_pattern_density >= 0.08:
            scores[PageKindV2.THRESHOLD_REFERENCE] += 2
        if evidence.admin_positional_signal >= 0.2:
            scores[PageKindV2.ADMIN_METADATA] += 1
        if evidence.header_footer_positional_signal >= 0.2:
            scores[PageKindV2.FOOTER_HEADER] += 1
        if evidence.bilingual_label_signal > 0.0:
            scores[PageKindV2.LAB_RESULTS] += 1

        top_kind = max(scores, key=scores.get)
        top_score = scores[top_kind]
        ordered_scores = sorted(scores.values(), reverse=True)
        second_score = ordered_scores[1] if len(ordered_scores) > 1 else 0
        margin = top_score - second_score
        total = sum(scores.values()) or 1
        confidence = round(top_score / total, 3)

        if top_score == 0:
            return PageClassificationV2(
                page_kind=PageKindV2.UNKNOWN,
                confidence=0.0,
                reason_codes=["page_no_keyword_match"],
                evidence=evidence,
                ambiguous=True,
            )

        if margin == 0 and confidence < 0.3:
            return PageClassificationV2(
                page_kind=PageKindV2.UNKNOWN,
                confidence=confidence,
                reason_codes=["ambiguous_page_classification", f"top_kind:{top_kind.value}", f"top_score:{top_score}", f"margin:{margin}"],
                evidence=evidence,
                ambiguous=True,
            )

        reason_codes = [f"page_kind:{top_kind.value}", f"score:{top_score}"]
        if top_kind == PageKindV2.LAB_RESULTS and scores[PageKindV2.THRESHOLD_REFERENCE] > 0:
            reason_codes.append("mixed_lab_and_threshold_signals")

        return PageClassificationV2(
            page_kind=top_kind,
            confidence=confidence,
            reason_codes=reason_codes,
            evidence=evidence,
        )

    def classify_block(
        self,
        text: str,
        *,
        bbox: SourceSpanV1 | None,
        page_height: float,
        reading_order: int,
        total_blocks: int,
    ) -> BlockClassificationV1:
        normalized = _normalize(text)
        evidence = _build_block_evidence(
            normalized,
            bbox=bbox,
            page_height=page_height,
            reading_order=reading_order,
            total_blocks=total_blocks,
            admin_keywords=self._registry.block_keywords("admin_block"),
            header_keywords=self._registry.block_keywords("header_footer_block"),
            threshold_keywords=self._registry.block_keywords("threshold_block"),
        )

        scores: dict[BlockRoleV1, int] = {
            BlockRoleV1.RESULT_BLOCK: _keyword_score(normalized, self._registry.block_keywords("result_block")),
            BlockRoleV1.THRESHOLD_BLOCK: _keyword_score(normalized, self._registry.block_keywords("threshold_block")),
            BlockRoleV1.ADMIN_BLOCK: _keyword_score(normalized, self._registry.block_keywords("admin_block")),
            BlockRoleV1.NARRATIVE_BLOCK: _keyword_score(normalized, self._registry.block_keywords("narrative_block")),
            BlockRoleV1.HEADER_FOOTER_BLOCK: _keyword_score(normalized, self._registry.block_keywords("header_footer_block")),
            BlockRoleV1.UNKNOWN_BLOCK: 0,
        }

        if evidence.numeric_token_density >= 0.1:
            scores[BlockRoleV1.RESULT_BLOCK] += 1
        if evidence.threshold_pattern_density >= 0.08:
            scores[BlockRoleV1.THRESHOLD_BLOCK] += 2
        if evidence.admin_positional_signal >= 0.5:
            scores[BlockRoleV1.ADMIN_BLOCK] += 1
        if evidence.header_footer_positional_signal >= 0.5:
            scores[BlockRoleV1.HEADER_FOOTER_BLOCK] += 2
        if evidence.bilingual_label_signal > 0.0:
            scores[BlockRoleV1.RESULT_BLOCK] += 1

        top_role = max(scores, key=scores.get)
        top_score = scores[top_role]
        ordered_scores = sorted(scores.values(), reverse=True)
        second_score = ordered_scores[1] if len(ordered_scores) > 1 else 0
        margin = top_score - second_score
        total = sum(scores.values()) or 1
        confidence = round(top_score / total, 3)

        if top_score == 0:
            return BlockClassificationV1(
                block_role=BlockRoleV1.UNKNOWN_BLOCK,
                confidence=0.0,
                reason_codes=["block_no_keyword_match"],
                evidence=evidence,
                ambiguous=True,
            )

        ambiguous = margin == 0 and confidence < 0.3
        reason_codes = [f"block_role:{top_role.value}", f"score:{top_score}", f"margin:{margin}"]
        if ambiguous:
            reason_codes.insert(0, "ambiguous_block_classification")

        return BlockClassificationV1(
            block_role=BlockRoleV1.UNKNOWN_BLOCK if ambiguous else top_role,
            confidence=confidence,
            reason_codes=reason_codes,
            evidence=evidence,
            ambiguous=ambiguous,
        )


def _score(texts: list[str], keywords: tuple[str, ...]) -> int:
    score = 0
    for text in texts:
        for keyword in keywords:
            if keyword in text:
                score += 1
    return score


def _keyword_score(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def _token_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _numeric_density(text: str) -> float:
    token_count = _token_count(text)
    if token_count == 0:
        return 0.0
    numeric_count = len(_NUMERIC_RE.findall(text))
    return round(numeric_count / token_count, 4)


def _table_density(lines: list[str]) -> float:
    if not lines:
        return 0.0
    table_like = 0
    for line in lines:
        numeric_hits = len(_NUMERIC_RE.findall(line))
        token_count = len(_WORD_RE.findall(line))
        if numeric_hits >= 2 and token_count >= 4:
            table_like += 1
            continue
        if "|" in line or "\t" in line:
            table_like += 1
    return round(table_like / len(lines), 4)


def _threshold_density(lines: list[str], threshold_keywords: tuple[str, ...]) -> float:
    if not lines:
        return 0.0
    threshold_like = 0
    for line in lines:
        normalized = line.lower()
        if any(keyword in normalized for keyword in threshold_keywords):
            threshold_like += 1
            continue
        if _RANGE_RE.search(normalized):
            threshold_like += 1
    return round(threshold_like / len(lines), 4)


def _bilingual_signal(text: str) -> float:
    has_cjk = bool(_CJK_RE.search(text))
    has_latin = bool(_LATIN_RE.search(text))
    if has_cjk and has_latin:
        return 1.0
    if has_cjk or has_latin:
        return 0.25
    return 0.0


def _build_page_evidence(
    normalized_text: str,
    candidate_texts: list[str],
    *,
    admin_keywords: tuple[str, ...],
    header_keywords: tuple[str, ...],
    threshold_keywords: tuple[str, ...],
) -> PageClassificationEvidenceV1:
    lines = [line for line in normalized_text.splitlines() if line.strip()]
    if not lines and normalized_text:
        lines = [normalized_text]

    block_count = max(len(candidate_texts), 1)
    block_position_score = round(
        sum(1.0 - abs(((index + 0.5) / block_count) - 0.5) * 2.0 for index in range(block_count))
        / block_count,
        4,
    )
    numeric_token_density = _numeric_density(normalized_text)
    table_density = _table_density(lines)
    threshold_pattern_density = _threshold_density(lines, threshold_keywords)

    edge_blocks = [candidate_texts[index] for index in range(len(candidate_texts)) if index < 2 or index >= max(len(candidate_texts) - 2, 0)]
    admin_hits = sum(1 for value in edge_blocks if any(keyword in value for keyword in admin_keywords))
    header_hits = sum(1 for value in edge_blocks if any(keyword in value for keyword in header_keywords))
    edge_denominator = max(len(edge_blocks), 1)
    admin_signal = round(admin_hits / edge_denominator, 4)
    header_signal = round(header_hits / edge_denominator, 4)

    bilingual_label_signal = _bilingual_signal(normalized_text)

    return PageClassificationEvidenceV1(
        contract_version=_PAGE_EVIDENCE_VERSION,
        block_position_score=block_position_score,
        numeric_token_density=numeric_token_density,
        table_density=table_density,
        threshold_pattern_density=threshold_pattern_density,
        admin_positional_signal=admin_signal,
        header_footer_positional_signal=header_signal,
        bilingual_label_signal=bilingual_label_signal,
    )


def _build_block_evidence(
    normalized_text: str,
    *,
    bbox: SourceSpanV1 | None,
    page_height: float,
    reading_order: int,
    total_blocks: int,
    admin_keywords: tuple[str, ...],
    header_keywords: tuple[str, ...],
    threshold_keywords: tuple[str, ...],
) -> BlockClassificationEvidenceV1:
    relative_position = ((reading_order + 0.5) / max(total_blocks, 1))
    if bbox is not None and page_height > 0:
        relative_position = ((bbox.y0 + bbox.y1) / 2.0) / page_height

    if relative_position <= 0.18:
        band = "header"
    elif relative_position >= 0.82:
        band = "footer"
    else:
        band = "body"

    lines = [line for line in normalized_text.splitlines() if line.strip()]
    if not lines and normalized_text:
        lines = [normalized_text]

    numeric_token_density = _numeric_density(normalized_text)
    threshold_pattern_density = _threshold_density(lines, threshold_keywords)
    admin_signal = 1.0 if any(keyword in normalized_text for keyword in admin_keywords) and band in {"header", "footer"} else 0.0
    header_signal = 1.0 if any(keyword in normalized_text for keyword in header_keywords) and band in {"header", "footer"} else 0.0
    bilingual_label_signal = _bilingual_signal(normalized_text)

    return BlockClassificationEvidenceV1(
        contract_version=_BLOCK_EVIDENCE_VERSION,
        block_position_band=band,
        numeric_token_density=numeric_token_density,
        threshold_pattern_density=threshold_pattern_density,
        admin_positional_signal=admin_signal,
        header_footer_positional_signal=header_signal,
        bilingual_label_signal=bilingual_label_signal,
    )


def _normalize(value: str) -> str:
    return " ".join(str(value or "").lower().split())
