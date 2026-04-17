"""Analyte resolver: strict deterministic alias mapping (blueprint section 3.7)."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections import defaultdict
from functools import lru_cache
from typing import Any

from app.services.data_paths import resolve_data_file

_LOGGER = logging.getLogger(__name__)

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
    # Small numeric tokens that appear as part of compound units (e.g. "10^3/ul", "x10^6").
    # These are stripped as unit residuals; they do NOT affect analyte names that happen
    # to contain numbers like "T3", "T4" because those have letter+digit combos.
    "3",
    "10",
    # NOTE: three-or-more-digit numbers like "100", "150" are intentionally excluded
    # so reference-range tokens in labels like "Glucose 100-150" are not silently stripped.
}

_NON_ALNUM_PERCENT_RE = re.compile(r"[^a-z0-9%]+")
_PAREN_CONTENT_RE = re.compile(r"\([^)]*\)")

_ANALYTE_SHORTCUT_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bhaemoglobin\s*a\s*1\s*c\b"), "hba1c"),
    (re.compile(r"\bhemoglobin\s*a\s*1\s*c\b"), "hba1c"),
    (re.compile(r"\bhb\s*a\s*1\s*c\b"), "hba1c"),
    (re.compile(r"\ba\s*1\s*c\b"), "hba1c"),
    (re.compile(r"\bestimated\s+glomerular\s+filtration\s+rate\b"), "egfr"),
    (re.compile(r"\be\s*gfr\b"), "egfr"),
    (re.compile(r"\blow\s+density\s+lipoprotein\s+cholesterol\b"), "ldl c"),
    (re.compile(r"\bhigh\s+density\s+lipoprotein\s+cholesterol\b"), "hdl c"),
    (re.compile(r"\bldl\s+cholesterol\b"), "ldl c"),
    (re.compile(r"\bhdl\s+cholesterol\b"), "hdl c"),
    (re.compile(r"\begfr\s+ckd\s+epi\b"), "egfr"),
    (re.compile(r"\begfr\s+epi\b"), "egfr"),
    (re.compile(r"\bhba1c\s+ifcc\b"), "hba1c"),
    (re.compile(r"\bhba1c\s+dcct\b"), "hba1c"),
)


class AnalyteResolver:
    """Map raw analyte labels to terminology codes.

    Modes: strict deterministic alias matching.
    Never auto-accept fuzzy matches. Every abstention reason stored.
    """

    def resolve(self, raw_label: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = context or {}
        specimen_context = self._normalize(context.get("specimen_context", ""))
        language_id = self._normalize(context.get("language_id", ""))
        raw_unit = str(context.get("raw_unit") or "").strip()
        resolved = self._resolve_cached(raw_label, specimen_context, language_id, raw_unit)
        return self._clone_resolve_result(resolved)

    @lru_cache(maxsize=4096)
    def _resolve_cached(
        self,
        raw_label: str,
        specimen_context: str,
        language_id: str,
        raw_unit: str,
    ) -> dict[str, Any]:
        normalized_label = self._normalize(raw_label)
        normalized_unit = _normalize_unit_token(raw_unit)

        candidates = self._score_candidates(
            normalized_label, specimen_context, language_id, normalized_unit
        )
        accepted_candidate = next((c for c in candidates if c["accepted"]), None)
        support_state = "supported" if accepted_candidate is not None else "unsupported"

        return {
            "raw_label": raw_label,
            "normalized_label": normalized_label,
            "context": {
                "specimen_context": specimen_context or None,
                "language_id": language_id or None,
                "raw_unit": raw_unit or None,
            },
            "candidates": candidates,
            "accepted_candidate": accepted_candidate,
            "support_state": support_state,
            "abstention_reasons": self._collect_abstention_reasons(candidates),
        }

    @staticmethod
    def _clone_resolve_result(resolved: dict[str, Any]) -> dict[str, Any]:
        accepted = resolved.get("accepted_candidate")
        return {
            "raw_label": resolved.get("raw_label"),
            "normalized_label": resolved.get("normalized_label"),
            "context": dict(resolved.get("context") or {}),
            "candidates": [dict(candidate) for candidate in (resolved.get("candidates") or [])],
            "accepted_candidate": dict(accepted) if isinstance(accepted, dict) else None,
            "support_state": resolved.get("support_state"),
            "abstention_reasons": list(resolved.get("abstention_reasons") or []),
        }

    @staticmethod
    def _normalize(value: object) -> str:
        return _normalize_text(value)

    def _score_candidates(
        self,
        normalized_label: str,
        specimen_context: str,
        language_id: str,
        normalized_unit: str = "",
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

        if all(bool(candidate.get("_ambiguous_token_match")) for candidate in candidates):
            return [
                {
                    "candidate_code": candidate["candidate_code"],
                    "candidate_display": candidate["candidate_display"],
                    "score": 0.0,
                    "threshold_used": candidate["threshold_used"],
                    "accepted": False,
                    "rejection_reason": "ambiguous_tokens",
                }
                for candidate in candidates
            ]

        # Unit-based disambiguation only when candidates share canonical label
        # AND at least one candidate declares expected_ucum_units. Otherwise we
        # fall through to legacy first-match behavior (e.g. "Glucose" alias that
        # maps to multiple codes across distinct canonical labels).
        distinct_codes = {c.get("candidate_code") for c in candidates}
        distinct_canonical = {c.get("canonical_label") for c in candidates}
        any_unit_declared = any(c.get("expected_ucum_units") for c in candidates)
        if len(distinct_codes) > 1 and len(distinct_canonical) == 1 and any_unit_declared:
            return _disambiguate_by_unit(candidates, normalized_unit)

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
            if len(token_matches) > 1:
                codes = [c.get("candidate_code") for c in token_matches]
                _LOGGER.warning(
                    "Ambiguous token signature '%s' matched %d candidates %s — abstaining",
                    token_signature,
                    len(token_matches),
                    codes,
                )
                return [
                    {**candidate, "_ambiguous_token_match": True}
                    for candidate in token_matches
                ]

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
        expected_ucum_units: set[str] | None = None,
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
                "expected_ucum_units": set(expected_ucum_units or ()),
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
        if expected_ucum_units:
            analyte.setdefault("expected_ucum_units", set()).update(expected_ucum_units)
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

        raw_expected_units = entry.get("expected_ucum_units", [])
        if not isinstance(raw_expected_units, list):
            raw_expected_units = []
        expected_ucum_units = {
            _normalize_unit_token(str(u))
            for u in raw_expected_units
            if str(u or "").strip()
        }
        expected_ucum_units.discard("")

        analyte = upsert_analyte(
            candidate_code=candidate_code,
            canonical_label=canonical_label,
            candidate_display=str(entry.get("candidate_display") or canonical_label_raw).strip(),
            panel_key=str(entry.get("panel_key") or "").strip(),
            threshold_used=_coerce_threshold(
                entry.get("threshold_used"),
                default=_DEFAULT_THRESHOLD,
            ),
            expected_ucum_units=expected_ucum_units,
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
            "expected_ucum_units": sorted(analyte.get("expected_ucum_units") or set()),
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

    without_parentheses = _PAREN_CONTENT_RE.sub(" ", raw_text)
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
    normalized = _NON_ALNUM_PERCENT_RE.sub(" ", folded)
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
    normalized = value
    for pattern, replacement in _ANALYTE_SHORTCUT_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)
    return normalized


def _coerce_threshold(value: object, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


_UNIT_SYNONYMS = {
    "percent": "%",
    "pct": "%",
    "mmol mol": "mmol/mol",
    "mmolmol": "mmol/mol",
    "mmol.mol-1": "mmol/mol",
    "mmolperlmol": "mmol/mol",
    "ngsp %": "%",
    "ifcc": "mmol/mol",
}


def _normalize_unit_token(value: object) -> str:
    """Collapse a raw UCUM-ish unit string to a canonical comparison token.

    Lowercased, whitespace-collapsed, common synonym-folded. Not a full UCUM
    parser — sufficient for disambiguating candidates with distinct expected
    units (e.g. "%" vs "mmol/mol").
    """

    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    raw = " ".join(raw.split())
    if raw in _UNIT_SYNONYMS:
        return _UNIT_SYNONYMS[raw]
    return raw


def _disambiguate_by_unit(
    candidates: list[dict[str, Any]], normalized_unit: str
) -> list[dict[str, Any]]:
    """Route to a single candidate when multiple share a canonical label.

    If the supplied unit matches exactly one candidate's expected UCUM set,
    return just that candidate (accepted). Otherwise return all candidates
    with `accepted=False` and `rejection_reason="unit_required"`.
    """

    if normalized_unit:
        matching = [
            c
            for c in candidates
            if normalized_unit
            in {
                _normalize_unit_token(u)
                for u in (c.get("expected_ucum_units") or [])
            }
        ]
        if len(matching) == 1:
            candidate = matching[0]
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

    # Ambiguous: no unit or unit matches zero/multiple candidates.
    reason = "unit_required" if not normalized_unit else "unit_mismatch"
    return [
        {
            "candidate_code": candidate["candidate_code"],
            "candidate_display": candidate["candidate_display"],
            "score": 0.0,
            "threshold_used": candidate["threshold_used"],
            "accepted": False,
            "rejection_reason": reason,
        }
        for candidate in candidates
    ]
