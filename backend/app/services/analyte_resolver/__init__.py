"""Analyte resolver: strict deterministic alias mapping (blueprint section 3.7)."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from functools import lru_cache
from typing import Any

from app.services.data_paths import resolve_data_file

_DEFAULT_THRESHOLD = 0.9
_CONTEXT_TOKENS = {
    "blood",
    "level",
    "levels",
    "plasma",
    "reference",
    "result",
    "results",
    "serum",
    "specimen",
    "test",
    "tests",
    "unit",
    "units",
    "value",
}

_TRAILING_QUALIFIER_TOKENS = {
    "s",  # serum shorthand in several lab exports, e.g. "Creatinine S"
    "p",
    "u",
    "ul",
    "cmm",
    "wb",
    "ifcc",
    "dcct",
    "ngsp",
    "epi",
    "ckd",
    "calc",
    "calculated",
    # Unit residuals left behind after stripping parens/slashes. Analyte names
    # in lab reports frequently trail with their unit ("Na (mmol/L)", "Total
    # Cholesterol (mg/dL)") — we strip those so the core analyte token matches.
    "mg",
    "dl",
    "ml",
    "l",
    "mmol",
    "g",
    "pg",
    "ng",
    "mcg",
    "pmol",
    "nmol",
    "mol",
    "iu",
    "3",
    "10",
}


_LABEL_UNIT_STRIP_RE = None


class AnalyteResolver:
    """Map raw analyte labels to terminology codes.

    Modes: strict deterministic alias matching.
    Never auto-accept fuzzy matches. Every abstention reason stored.
    """

    def resolve(self, raw_label: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = context or {}
        normalized_label = self._normalize(raw_label)
        specimen_context = self._normalize(context.get("specimen_context", ""))
        language_id = self._normalize(context.get("language_id", ""))

        candidates = self._score_candidates(normalized_label, specimen_context, language_id)
        accepted_candidate = next((c for c in candidates if c["accepted"]), None)

        if accepted_candidate is None:
            support_state = "unsupported"
        else:
            support_state = "supported"

        return {
            "raw_label": raw_label,
            "normalized_label": normalized_label,
            "context": {
                "specimen_context": specimen_context or None,
                "language_id": language_id or None,
            },
            "candidates": candidates,
            "accepted_candidate": accepted_candidate,
            "support_state": support_state,
            "abstention_reasons": self._collect_abstention_reasons(candidates),
        }

    @staticmethod
    def _normalize(value: object) -> str:
        return _normalize_text(value)

    def _score_candidates(
        self, normalized_label: str, specimen_context: str, language_id: str
    ) -> list[dict[str, Any]]:
        if not normalized_label:
            return []

        candidates = self._lookup_candidates(normalized_label, specimen_context, language_id)
        if not candidates:
            return [
                {
                    "candidate_code": "__unmapped__",
                    "candidate_display": "unmapped",
                    "score": 0.0,
                    "threshold_used": _DEFAULT_THRESHOLD,
                    "accepted": False,
                    "rejection_reason": "unsupported_alias",
                }
            ]

        candidate = candidates[0]
        return [
            {
                "candidate_code": candidate["candidate_code"],
                "candidate_display": candidate["candidate_display"],
                "score": 1.0,
                "threshold_used": candidate["threshold_used"],
                "accepted": True,
                "rejection_reason": None,
            }
        ]

    def _lookup_candidates(
        self, normalized_label: str, _specimen_context: str, _language_id: str
    ) -> list[dict[str, Any]]:
        metadata = _load_launch_scope_metadata()
        alias_index = metadata.get("alias_index", {})
        exact_matches = alias_index.get(normalized_label, [])
        if exact_matches:
            canonical_exact_matches = [
                candidate
                for candidate in exact_matches
                if normalized_label == str(candidate.get("canonical_label") or "").strip()
            ]
            if canonical_exact_matches:
                return canonical_exact_matches
            return exact_matches

        token_signature = _token_signature(normalized_label)
        if token_signature:
            signature_index = metadata.get("token_signature_index", {})
            token_matches = signature_index.get(token_signature, [])
            # Deterministic but conservative: only accept token-order fallback if unique.
            if len(token_matches) == 1:
                return token_matches

        return []

    @staticmethod
    def _collect_abstention_reasons(candidates: list[dict[str, Any]]) -> list[str]:
        reasons: list[str] = []
        for candidate in candidates:
            reason = candidate.get("rejection_reason")
            if reason and reason not in reasons:
                reasons.append(str(reason))
        return reasons


@lru_cache(maxsize=1)
def _load_launch_scope_metadata() -> dict[str, Any]:
    metadata_path = resolve_data_file(
        __file__,
        "alias_tables",
        "launch_scope_analyte_aliases.json",
    )

    raw_metadata: dict[str, Any]
    if metadata_path.exists():
        parsed = json.loads(metadata_path.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            raw_metadata = parsed
        else:
            raw_metadata = {}
    else:
        raw_metadata = {
            "version": "launch-scope-analyte-aliases-v1",
            "analytes": [],
        }

    analytes_by_code: dict[str, dict[str, Any]] = {}
    ordered_codes: list[str] = []

    raw_analytes = raw_metadata.get("analytes", [])
    if not isinstance(raw_analytes, list):
        raw_analytes = []

    def upsert_analyte(
        *,
        candidate_code: str,
        canonical_label: str,
        candidate_display: str,
        panel_key: str,
        threshold_used: float,
    ) -> dict[str, Any]:
        analyte = analytes_by_code.get(candidate_code)
        if analyte is None:
            analyte = {
                "canonical_label": canonical_label,
                "candidate_code": candidate_code,
                "candidate_display": candidate_display or canonical_label or "unmapped",
                "panel_key": panel_key,
                "aliases": set(),
                "threshold_used": threshold_used,
            }
            analytes_by_code[candidate_code] = analyte
            ordered_codes.append(candidate_code)
            return analyte

        if canonical_label and not analyte.get("canonical_label"):
            analyte["canonical_label"] = canonical_label
        if candidate_display and not analyte.get("candidate_display"):
            analyte["candidate_display"] = candidate_display
        if panel_key and not analyte.get("panel_key"):
            analyte["panel_key"] = panel_key
        return analyte

    for entry in raw_analytes:
        if not isinstance(entry, dict):
            continue

        canonical_label_raw = str(entry.get("canonical_label") or "").strip()
        canonical_label = _normalize_metadata_text(canonical_label_raw)

        raw_codes = entry.get("codes", [])
        if not isinstance(raw_codes, list):
            raw_codes = []

        candidate_code = next(
            (str(code or "").strip() for code in raw_codes if str(code or "").strip()),
            "",
        )
        if not candidate_code:
            continue

        analyte = upsert_analyte(
            candidate_code=candidate_code,
            canonical_label=canonical_label,
            candidate_display=str(entry.get("candidate_display") or canonical_label_raw).strip(),
            panel_key=str(entry.get("panel_key") or "").strip(),
            threshold_used=_coerce_threshold(
                entry.get("threshold_used"),
                default=_DEFAULT_THRESHOLD,
            ),
        )

        analyte_aliases = analyte["aliases"]
        for value in (
            canonical_label_raw,
            entry.get("candidate_display"),
            *raw_codes,
            *(entry.get("aliases", []) if isinstance(entry.get("aliases", []), list) else []),
        ):
            analyte_aliases.update(_generate_alias_variants(value))

    metrics_path = resolve_data_file(
        __file__,
        "metric_definitions",
        "core_metrics.json",
    )
    if metrics_path.exists():
        try:
            parsed_metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            parsed_metrics = []

        if isinstance(parsed_metrics, list):
            for entry in parsed_metrics:
                if not isinstance(entry, dict):
                    continue

                metric_id = str(entry.get("metric_id") or "").strip()
                canonical_name = str(entry.get("canonical_name") or "").strip()
                if not metric_id or not canonical_name:
                    continue

                analyte = upsert_analyte(
                    candidate_code=metric_id,
                    canonical_label=_normalize_metadata_text(canonical_name),
                    candidate_display=canonical_name,
                    panel_key="",
                    threshold_used=_DEFAULT_THRESHOLD,
                )

                analyte_aliases = analyte["aliases"]
                raw_aliases = entry.get("aliases", [])
                if not isinstance(raw_aliases, list):
                    raw_aliases = []
                raw_loincs = entry.get("loinc_candidates", [])
                if not isinstance(raw_loincs, list):
                    raw_loincs = []

                for value in (canonical_name, metric_id, *raw_aliases, *raw_loincs):
                    analyte_aliases.update(_generate_alias_variants(value))

    analytes: list[dict[str, Any]] = []
    alias_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    token_signature_index: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for code in ordered_codes:
        analyte = analytes_by_code[code]
        aliases = sorted(alias for alias in analyte["aliases"] if alias)
        if not aliases:
            continue

        candidate = {
            "candidate_code": analyte["candidate_code"],
            "candidate_display": analyte["candidate_display"],
            "canonical_label": analyte["canonical_label"],
            "threshold_used": analyte["threshold_used"],
        }

        analytes.append(
            {
                "canonical_label": analyte["canonical_label"],
                "candidate_code": analyte["candidate_code"],
                "candidate_display": analyte["candidate_display"],
                "panel_key": analyte["panel_key"],
                "aliases": aliases,
                "threshold_used": analyte["threshold_used"],
            }
        )

        for alias in aliases:
            _append_unique_candidate(alias_index, alias, candidate)
            token_signature = _token_signature(alias)
            if token_signature:
                _append_unique_candidate(token_signature_index, token_signature, candidate)

    raw_metadata["analytes"] = analytes
    raw_metadata["alias_index"] = dict(alias_index)
    raw_metadata["token_signature_index"] = dict(token_signature_index)
    return raw_metadata


def _normalize_metadata_text(value: object) -> str:
    return _normalize_text(value)


def _generate_alias_variants(value: object) -> set[str]:
    raw_text = str(value or "").strip()
    if not raw_text:
        return set()

    variants: set[str] = set()

    def add_variant(candidate: str) -> None:
        normalized = _normalize_metadata_text(candidate)
        if normalized:
            variants.add(normalized)

    add_variant(raw_text)

    if "/" in raw_text:
        slash_parts = [part.strip() for part in raw_text.split("/") if part.strip()]
        normalized_parts = [_normalize_metadata_text(part) for part in slash_parts]
        # Expand slash aliases only for compact forms (e.g. "AST/SGOT", "CK/CPK").
        # This avoids over-broad aliases like "total cholesterol" from ratio metrics.
        if normalized_parts and all(part and len(part.split()) <= 1 for part in normalized_parts):
            for part in slash_parts:
                add_variant(part)

    if "," in raw_text:
        parts = [part.strip() for part in raw_text.split(",") if part.strip()]
        if len(parts) == 2:
            add_variant(f"{parts[1]} {parts[0]}")

    without_parentheses = re.sub(r"\([^)]*\)", " ", raw_text)
    if without_parentheses != raw_text:
        add_variant(without_parentheses)

    return variants


def _token_signature(value: str) -> str | None:
    tokens = [token for token in value.split() if token]
    if len(tokens) < 2:
        return None
    return " ".join(sorted(set(tokens)))


def _append_unique_candidate(
    index: dict[str, list[dict[str, Any]]],
    key: str,
    candidate: dict[str, Any],
) -> None:
    bucket = index.setdefault(key, [])
    candidate_code = candidate["candidate_code"]
    if any(existing.get("candidate_code") == candidate_code for existing in bucket):
        return
    bucket.append(candidate)


def _normalize_text(value: object) -> str:
    raw_text = str(value or "").strip().lower()
    if not raw_text:
        return ""

    folded = _ascii_fold(raw_text)
    normalized = re.sub(r"[^a-z0-9%]+", " ", folded)
    normalized = _normalize_analyte_shortcuts(normalized)

    tokens = [token for token in normalized.split() if token and token not in _CONTEXT_TOKENS]
    # Repeatedly strip trailing qualifier/unit tokens. "%" is treated as a
    # trailing unit sigil, so "HbA1c NGSP %" normalizes to "hba1c".
    while len(tokens) > 1 and (tokens[-1] in _TRAILING_QUALIFIER_TOKENS or tokens[-1] == "%"):
        tokens.pop()
    return " ".join(tokens)


def _ascii_fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(
        char for char in normalized if not unicodedata.combining(char) and ord(char) < 128
    )


def _normalize_analyte_shortcuts(value: str) -> str:
    normalized = re.sub(r"\bhaemoglobin\s*a\s*1\s*c\b", "hba1c", value)
    normalized = re.sub(r"\bhemoglobin\s*a\s*1\s*c\b", "hba1c", normalized)
    normalized = re.sub(r"\bhb\s*a\s*1\s*c\b", "hba1c", normalized)
    normalized = re.sub(r"\ba\s*1\s*c\b", "hba1c", normalized)
    normalized = re.sub(r"\bestimated\s+glomerular\s+filtration\s+rate\b", "egfr", normalized)
    normalized = re.sub(r"\be\s*gfr\b", "egfr", normalized)
    normalized = re.sub(r"\blow\s+density\s+lipoprotein\s+cholesterol\b", "ldl c", normalized)
    normalized = re.sub(r"\bhigh\s+density\s+lipoprotein\s+cholesterol\b", "hdl c", normalized)
    normalized = re.sub(r"\bldl\s+cholesterol\b", "ldl c", normalized)
    normalized = re.sub(r"\bhdl\s+cholesterol\b", "hdl c", normalized)
    normalized = re.sub(r"\begfr\s+ckd\s+epi\b", "egfr", normalized)
    normalized = re.sub(r"\begfr\s+epi\b", "egfr", normalized)
    normalized = re.sub(r"\bhba1c\s+ifcc\b", "hba1c", normalized)
    normalized = re.sub(r"\bhba1c\s+dcct\b", "hba1c", normalized)
    return normalized


def _coerce_threshold(value: object, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
