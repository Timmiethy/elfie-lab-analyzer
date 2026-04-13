"""Analyte resolver: auditable hybrid mapping (blueprint section 3.7)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.ucum import UcumEngine

_EXCLUDED_ROW_TYPES = {
    "admin_metadata_row",
    "threshold_reference_row",
    "threshold_table_row",
    "narrative_guidance_row",
    "narrative_row",
    "header_footer_row",
    "header_row",
    "footer_row",
    "test_request_row",
    "unparsed_row",
}
_BILINGUAL_TRANSLATIONS = {
    "钠": "sodium",
    "氯化物": "chloride",
    "钾": "potassium",
    "葡萄糖": "glucose",
    "葡萄糖血红蛋白": "hba1c",
    "葡萄糖血紅蛋白": "hba1c",
    "糖化血红蛋白": "hba1c",
    "糖化血紅蛋白": "hba1c",
    "肌酸酐": "creatinine",
    "肌酐": "creatinine",
    "尿素": "urea",
    "尿酸": "uric acid",
    "三酸甘油酯": "triglycerides",
    "总胆固醇": "total cholesterol",
    "總膽固醇": "total cholesterol",
    "高脂蛋白(好)胆固醇": "hdl-c",
    "高脂蛋白(好)膽固醇": "hdl-c",
    "低脂蛋白(坏)胆固醇": "ldl-c",
    "低脂蛋白(壞)膽固醇": "ldl-c",
    "谷草转氨基酶": "ast",
    "谷丙转氨基酶": "alt",
    "估算肾小球滤过率": "egfr",
    "估算腎小球過濾率": "egfr",
    "估計腎小球濾過率": "egfr",
    "尿白蛋白": "urine albumin",
    "尿肌酐": "urine creatinine",
    "尿白蛋白/肌酐比": "acr",
    "尿白蛋白肌酐比": "acr",
    "白蛋白/肌酐比": "acr",
    "尿白蛋白/肌酐率": "acr",
    # v12: Innoquest bilingual aliases for newly-scoped analytes
    "脂蛋白(a)": "lipoprotein(a)",
    "载脂蛋白a1": "apolipoprotein a1",
    "載脂蛋白a1": "apolipoprotein a1",
    "载脂蛋白b": "apolipoprotein b",
    "載脂蛋白b": "apolipoprotein b",
    "血清胰岛素": "serum insulin",
    "血清胰島素": "serum insulin",
    "γ谷氨酰转肽酶": "ggt",
    "γ-谷氨酰转移酶": "ggt",
    "谷氨酰转肽酶": "ggt",
    "谷氨酰转移酶": "ggt",
    "总胆红素": "total bilirubin",
    "總膽紅素": "total bilirubin",
    # v12 wave-2: spaced variants for apolipoprotein labels from Innoquest
    # fixtures where normalization preserves a space between Chinese text and
    # the trailing Latin letter (e.g. ``载脂蛋白 A`` → ``载脂蛋白 a``).
    "载脂蛋白 a": "apolipoprotein a1",
    "載脂蛋白 a": "apolipoprotein a1",
    # v12 wave-2: spaced variants (continued)
    "载脂蛋白 b": "apolipoprotein b",
    "載脂蛋白 b": "apolipoprotein b",
    # v12 wave-4: residual Unicode fixture-backed normalization misses from
    # Innoquest DBTICRP path where bilingual replacement leaves adjacent
    # English+Chinese duplicates or uses shortened Chinese forms.
    "总红胆素": "total bilirubin",
    "總紅膽素": "total bilirubin",
}
_ACR_CANDIDATE = {
    "candidate_code": "9318-7",
    "candidate_display": "ACR",
    "canonical_label": "albumin/creatinine ratio",
    "threshold_used": 0.9,
    "panel_key": "kidney",
    "aliases": {
        "acr",
        "uacr",
        "albumin/creatinine ratio",
        "albumin creatinine ratio",
        "urine albumin/creatinine ratio",
        "urine albumin creatinine ratio",
        "urine albumin creatinine ratio",
        "urine albumin creatinine ratio",
        "albumin creatinine ratio urine",
        "urine acr",
    },
}
_LOOKUP_NORMALIZE_RE = re.compile(r"[^a-z0-9%+/]+")
# v12: normalized labels that must be excluded before candidate lookup
# to prevent threshold/risk text from leaking as partial observations.
_BLOCKED_NORMALIZED_LABELS = {"threshold_category"}
_LABEL_REWRITES = {
    "ldl cholesterol calculated": "ldl-c",
    "ldl cholesterol calc": "ldl-c",
    "ldl cholesterol": "ldl-c",
    "non hdl cholesterol": "non-hdl cholesterol",
    "absolute cd 4 helper": "cd4 cells",
    "cd 4 pos lymph": "cd4 cells",
    "cd4 pos lymph": "cd4 cells",
    "cd4 positive lymphocytes": "cd4 cells",
    "abs cd 8 suppressor": "cd8 cells",
    "absolute cd 8 suppressor": "cd8 cells",
    "cd 8 pos lymph": "cd8 cells",
    "cd8 pos lymph": "cd8 cells",
    "cd8 positive lymphocytes": "cd8 cells",
    "neutrophils absolute": "neutrophils",
    "absolute neutrophils": "neutrophils",
    "lymphs absolute": "total lymphocyte count",
    "lymphocytes absolute": "total lymphocyte count",
    "absolute lymphocytes": "total lymphocyte count",
    "monocytes absolute": "monocytes",
    "absolute monocytes": "monocytes",
    "eos absolute": "eosinophils",
    "absolute eosinophils": "eosinophils",
    "eosinophils absolute": "eosinophils",
    "baso absolute": "basophils",
    "absolute basophils": "basophils",
    "basophils absolute": "basophils",
    "basophils p": "basophils",
    "monocytesabsolute": "monocytes",
    "immature grans abs": "immature granulocytes",
    "egfr anon afr american": "egfr",
    "egfr non afr american": "egfr",
    "egfr african american": "egfr",
    "urea nitrogen bun": "urea nitrogen",
    "bun": "urea nitrogen",
    "t4 thyroxine total": "total thyroxine",
    "free t4 index t7": "free t4 index",
    "magnesium rbmc": "magnesium",
    # v12 wave-2 residual: mixed bilingual forms from DBTICRP fixture where
    # garbled encoding leaves partial English tokens after lookup normalization.
    "total chol": "total cholesterol",
    "lipoprotein a a": "lipoprotein(a)",
    # v12: threshold/risk category labels that must NOT resolve to real analytes
    "intermediate": "threshold_category",
    "low cv risk": "threshold_category",
    "high cv risk": "threshold_category",
    "very high cv risk": "threshold_category",
    "risk cut off low": "threshold_category",
    "risk cut off high": "threshold_category",
    "risk cut off": "threshold_category",
    "cut off low": "threshold_category",
    "cut off high": "threshold_category",
    # v12 wave-2 residual: additional threshold/risk table fragments from
    # DBTICRP fixture that must NOT surface as pseudo-lab rows.
    "moderate cv risk": "threshold_category",
    # v12: lookup-normalized forms of threshold labels that include numeric
    # cutoffs (e.g. ``Moderate CV Risk <2.6`` → ``moderate cv risk 2 6``).
    "moderate cv risk 2 6": "threshold_category",
    "very high cv risk 1 4": "threshold_category",
    "atherogenic low": "threshold_category",
    "atherogenic high": "threshold_category",
    "recurrent cv events": "threshold_category",
    "aip": "threshold_category",
    "biochem": "threshold_category",
    # v12 wave-2: bilingual residue from ``Total Chol 总胆固醇`` where the
    # Chinese part translates to ``total cholesterol`` and leaves a duped form
    # after adjacent-token deduplication in ``_apply_bilingual_normalization``.
    "total chol total cholesterol": "total cholesterol",
    # v12 wave-4: Innoquest DBTICRP residual duplicates after bilingual
    # replacement where English label + Chinese translation both survive
    # adjacent-token dedup because the tokens are not identical.
    "triglyceride triglycerides": "triglycerides",
    "apolipoprotein a1 apolipoprotein a11": "apolipoprotein a1",
}
_UNIT_COMPATIBILITY_BY_CANONICAL = {
    "2345-7": {"mass_concentration", "molar_concentration"},
    "4548-4": {"hba1c", "ratio"},
    "2160-0": {"mass_concentration", "molar_concentration"},
    "62238-1": {"filtration_rate"},
    "2823-3": {"molar_concentration"},
    "2093-3": {"mass_concentration", "molar_concentration"},
    "13457-7": {"mass_concentration", "molar_concentration"},
    "2085-9": {"mass_concentration", "molar_concentration"},
    "2571-8": {"mass_concentration", "molar_concentration"},
    "2951-2": {"molar_concentration"},
    "2075-0": {"molar_concentration"},
    "14937-7": {"molar_concentration"},
    "3084-1": {"molar_concentration"},
    "1920-8": {"enzyme_activity"},
    "1742-6": {"enzyme_activity"},
    "14957-5": {"mass_concentration"},
    "2161-8": {"molar_concentration"},
    "9318-7": {"ratio"},
    "55101-9": {"mass_concentration"},
    "71856-9": {"mass_concentration", "molar_concentration"},
    "30452-3": {"mass_concentration"},
    "14933-6": {"ratio"},
    "17385-6": {"ratio"},
    "6690-2": {"cell_count"},
    "789-8": {"cell_count"},
    "718-7": {"mass_concentration"},
    "4544-3": {"ratio"},
    "777-3": {"cell_count"},
    "787-2": {"volume"},
    "785-6": {"mass"},
    "786-4": {"mass_concentration"},
    "788-0": {"ratio"},
    "32623-1": {"volume"},
    "751-8": {"ratio", "cell_count"},
    "736-9": {"ratio", "cell_count"},
    "5905-5": {"ratio", "cell_count"},
    "713-8": {"ratio", "cell_count"},
    "706-2": {"ratio", "cell_count"},
    "24467-3": {"ratio", "cell_count"},
    "14135-7": {"ratio", "cell_count"},
    "8123-2": {"ratio"},
    "1975-2": {"mass_concentration", "molar_concentration"},
    "6768-6": {"enzyme_activity"},
    "2885-2": {"mass_concentration"},
    "1751-7": {"mass_concentration"},
    "2884-5": {"mass_concentration"},
    "1753-3": {"ratio"},
    "17861-6": {"mass_concentration"},
    "2028-9": {"molar_concentration"},
    "3094-0": {"mass_concentration"},
    "3016-3": {"enzyme_activity"},
    "3026-2": {"mass_concentration"},
    "62292-8": {"mass_concentration"},
    "1988-5": {"mass_concentration"},
    "19125-0": {"mass_concentration"},
    "3050-6": {"ratio"},
    "5811-5": {"ratio"},
    "5803-2": {"ratio"},
    "4537-7": {"sedimentation_rate"},
    "1988-1": {"mass_concentration"},
    "38518-7": {"ratio", "cell_count"},
    # v12: Innoquest normalization wave - newly supported analytes
    "13386-7": {"molar_concentration"},  # Lipoprotein(a) [Moles/volume]
    "15232-1": {"mass_concentration"},   # Apolipoprotein A1 [Mass/volume]
    "18768-1": {"mass_concentration"},   # Apolipoprotein B [Mass/volume]
    "11566-8": {"enzyme_activity"},      # Insulin [Units/volume] - uIU/mL -> enzyme_activity
    "2324-2": {"enzyme_activity"},       # GGT [Enzymatic activity/volume]
    "33762-6": {"mass_concentration"},   # NT-proBNP [Mass/volume] - pg/mL -> mass_concentration
}


class AnalyteResolver:
    """Map raw analyte labels to terminology codes.

    Modes: deterministic lexical rules, optional empirical challenger.
    Never auto-accept below threshold. Every abstention reason stored.
    """

    def resolve(self, raw_label: str, context: dict) -> dict:
        row_type = self._normalize(context.get("row_type", "measured_analyte_row"))
        family_adapter_id = self._normalize(context.get("family_adapter_id", ""))
        specimen_context = self._normalize(context.get("specimen_context", ""))
        language_id = self._normalize(context.get("language_id", ""))
        measurement_kind = self._normalize(context.get("measurement_kind", ""))
        raw_unit_string = self._normalize(context.get("raw_unit_string", ""))
        if not raw_unit_string and isinstance(context.get("primary_result"), dict):
            raw_unit_string = self._normalize(context["primary_result"].get("unit", ""))
        source_observation_ids = self._normalize_identifier_list(context.get("source_observation_ids"))
        derived_formula_id = self._normalize(context.get("derived_formula_id", ""))

        if row_type in _EXCLUDED_ROW_TYPES:
            return self._build_excluded_result(
                raw_label=raw_label,
                row_type=row_type,
                family_adapter_id=family_adapter_id,
                specimen_context=specimen_context,
                language_id=language_id,
                measurement_kind=measurement_kind,
                raw_unit_string=raw_unit_string,
                derived_formula_id=derived_formula_id,
                source_observation_ids=source_observation_ids,
            )

        if row_type == "derived_analyte_row" and not source_observation_ids:
            return self._build_derived_unbound_result(
                raw_label=raw_label,
                family_adapter_id=family_adapter_id,
                specimen_context=specimen_context,
                language_id=language_id,
                measurement_kind=measurement_kind,
                raw_unit_string=raw_unit_string,
                source_observation_ids=source_observation_ids,
            )

        normalized_label, normalization_trace = self._normalize_label(
            raw_label,
            family_adapter_id=family_adapter_id,
            language_id=language_id,
        )
        candidates, candidate_trace, support_code, failure_code, support_state = self._score_candidates(
            normalized_label,
            specimen_context=specimen_context,
            language_id=language_id,
            raw_unit_string=raw_unit_string,
            row_type=row_type,
            measurement_kind=measurement_kind,
            family_adapter_id=family_adapter_id,
            source_observation_ids=source_observation_ids,
            normalization_trace=normalization_trace,
        )
        accepted_candidate = next((candidate for candidate in candidates if candidate["accepted"]), None)

        if accepted_candidate is None:
            if candidates:
                support_state = "partial"
            else:
                support_state = "unsupported"
        else:
            support_state = "supported"
            support_code = "supported_result"
            failure_code = None

        return {
            "raw_label": raw_label,
            "normalized_label": normalized_label,
            "context": {
                "row_type": row_type or None,
                "family_adapter_id": family_adapter_id or None,
                "specimen_context": specimen_context or None,
                "language_id": language_id or None,
                "measurement_kind": measurement_kind or None,
                "raw_unit_string": raw_unit_string or None,
                "derived_formula_id": derived_formula_id or None,
                "source_observation_ids": source_observation_ids,
            },
            "candidates": candidates,
            "candidate_trace": candidate_trace,
            "accepted_candidate": accepted_candidate,
            "support_state": support_state,
            "support_code": support_code,
            "failure_code": failure_code,
            "abstention_reasons": self._collect_abstention_reasons(candidates, failure_code=failure_code),
        }

    @staticmethod
    def _normalize(value: object) -> str:
        return " ".join(str(value or "").strip().lower().split())

    def _normalize_label(
        self,
        raw_label: str,
        *,
        family_adapter_id: str,
        language_id: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        raw_text = self._normalize(raw_label)
        translated_text = raw_text
        bilingual_applied = False

        if family_adapter_id == "innoquest_bilingual_general" or language_id not in {"", "en"}:
            translated_text = self._apply_bilingual_normalization(raw_text)
            bilingual_applied = translated_text != raw_text

        lookup_text = _normalize_lookup_label(translated_text)
        rewritten_text = _LABEL_REWRITES.get(lookup_text)
        final_text = rewritten_text or translated_text

        return final_text, [
            {
                "stage": "family_filter",
                "status": "pass",
                "detail": family_adapter_id or "default",
            },
            {
                "stage": "bilingual_alias_normalization",
                "status": "applied" if bilingual_applied else "skipped",
                "detail": translated_text,
            },
            {
                "stage": "lexical_rewrite",
                "status": "applied" if rewritten_text else "skipped",
                "detail": final_text,
            },
        ]

    def _score_candidates(
        self,
        normalized_label: str,
        *,
        specimen_context: str,
        language_id: str,
        raw_unit_string: str,
        row_type: str,
        measurement_kind: str,
        family_adapter_id: str,
        source_observation_ids: list[str],
        normalization_trace: list[dict[str, Any]],
    ) -> tuple[list[dict], list[dict[str, Any]], str, str | None, str]:
        # v12: blocked labels (e.g. threshold/risk category text) must not
        # reach the candidate pool. Treat them as excluded so they never
        # surface as partial observations.
        if normalized_label in _BLOCKED_NORMALIZED_LABELS:
            return (
                [],
                normalization_trace
                + [{"stage": "lexical_match", "status": "fail", "detail": "blocked_label"}],
                "threshold_category",
                "threshold_category",
                "unsupported",
            )
        if not normalized_label:
            return (
                [],
                normalization_trace
                + [
                    {
                        "stage": "lexical_match",
                        "status": "fail",
                        "detail": "missing_label",
                    }
                ],
                "partial_result",
                "unsupported_family",
                "unsupported",
            )

        candidate = self._lookup_candidate(normalized_label, specimen_context, language_id, raw_unit_string)
        if candidate is None:
            return (
                [
                    {
                        "candidate_code": "__unmapped__",
                        "candidate_display": normalized_label or "unmapped",
                        "score": 0.0,
                        "threshold_used": 0.95,
                        "accepted": False,
                        "rejection_reason": "unsupported_family",
                        "stage_trace": normalization_trace
                        + [
                            {
                                "stage": "lexical_match",
                                "status": "fail",
                                "detail": normalized_label,
                            },
                            {
                                "stage": "unit_compatibility",
                                "status": "skip",
                                "detail": "no_candidate",
                            },
                            {
                                "stage": "derived_direct_compatibility",
                                "status": "skip",
                                "detail": row_type,
                            },
                            {
                                "stage": "threshold",
                                "status": "reject",
                                "detail": "unsupported_family",
                            },
                        ],
                    }
                ],
                normalization_trace,
                "partial_result",
                "unsupported_family",
                "unsupported" if measurement_kind == "derived" and not source_observation_ids else "partial",
            )

        score = candidate["score"]
        threshold_used = candidate["threshold_used"]
        unit_compatibility = self._unit_compatibility(candidate, raw_unit_string)
        derived_compatibility = self._derived_compatibility(row_type, measurement_kind, source_observation_ids)
        accepted = score >= threshold_used and unit_compatibility["compatible"] and derived_compatibility["compatible"]
        rejection_reason = None if accepted else unit_compatibility["rejection_reason"] or derived_compatibility["rejection_reason"] or "below_threshold"
        support_state = "supported" if accepted else "partial"
        support_code = "supported_result" if accepted else "partial_result"
        failure_code = None if accepted else rejection_reason

        candidate_trace = normalization_trace + [
            {
                "stage": "lexical_match",
                "status": "pass" if candidate["candidate_code"] != "__unmapped__" else "fail",
                "detail": normalized_label,
            },
            {
                "stage": "specimen_method_compatibility",
                "status": "pass" if candidate["score"] >= candidate["threshold_used"] else "warn",
                "detail": specimen_context or None,
            },
            {
                "stage": "unit_compatibility",
                "status": "pass" if unit_compatibility["compatible"] else "fail",
                "detail": unit_compatibility["unit_family"],
            },
            {
                "stage": "derived_direct_compatibility",
                "status": "pass" if derived_compatibility["compatible"] else "fail",
                "detail": derived_compatibility["detail"],
            },
            {
                "stage": "threshold",
                "status": "accept" if accepted else "reject",
                "detail": threshold_used,
            },
        ]

        return (
            [
                {
                    "candidate_code": candidate["candidate_code"],
                    "candidate_display": candidate["candidate_display"],
                    "score": score,
                    "threshold_used": threshold_used,
                    "accepted": accepted,
                    "rejection_reason": rejection_reason,
                    "stage_trace": candidate_trace,
                }
            ],
            candidate_trace,
            support_code,
            failure_code,
            support_state,
        )

    def _lookup_candidate(
        self,
        normalized_label: str,
        specimen_context: str,
        language_id: str,
        raw_unit_string: str,
    ) -> dict | None:
        lookup_label = _normalize_lookup_label(normalized_label)
        if normalized_label in _ACR_CANDIDATE["aliases"] or lookup_label in _ACR_CANDIDATE["aliases"]:
            score = 0.99
            unit_compatibility = self._unit_compatibility(_ACR_CANDIDATE, raw_unit_string)
            if not unit_compatibility["compatible"]:
                score = 0.88
            return {
                "candidate_code": _ACR_CANDIDATE["candidate_code"],
                "candidate_display": _ACR_CANDIDATE["candidate_display"],
                "threshold_used": _ACR_CANDIDATE["threshold_used"],
                "score": score,
            }

        for analyte in _load_launch_scope_metadata()["analytes"]:
            aliases = analyte["aliases"]
            if normalized_label not in aliases and lookup_label not in aliases:
                continue

            score = 0.99
            if analyte["panel_key"] == "glycemia" and specimen_context not in {"serum", "plasma", "blood", ""}:
                score = 0.95
            if analyte["canonical_label"] == "hba1c" and language_id not in {"en", ""}:
                score = min(score, 0.97)

            return {
                "candidate_code": analyte["candidate_code"],
                "candidate_display": _display_name(analyte["canonical_label"]),
                "threshold_used": analyte["threshold_used"],
                "score": score,
            }

        return None

    def _unit_compatibility(self, candidate: dict[str, Any], raw_unit_string: str) -> dict[str, Any]:
        if not raw_unit_string:
            return {
                "compatible": True,
                "rejection_reason": None,
                "unit_family": "unitless",
            }

        unit_family = UcumEngine().classify_unit_family(raw_unit_string)
        expected_families = _UNIT_COMPATIBILITY_BY_CANONICAL.get(candidate["candidate_code"], {"unknown"})
        if unit_family == "unknown":
            return {
                "compatible": False,
                "rejection_reason": "unit_parse_fail",
                "unit_family": unit_family,
            }
        if unit_family not in expected_families:
            return {
                "compatible": False,
                "rejection_reason": "unit_mismatch",
                "unit_family": unit_family,
            }
        return {
            "compatible": True,
            "rejection_reason": None,
            "unit_family": unit_family,
        }

    def _derived_compatibility(
        self,
        row_type: str,
        measurement_kind: str,
        source_observation_ids: list[str],
    ) -> dict[str, Any]:
        if row_type == "derived_analyte_row" or measurement_kind == "derived":
            if source_observation_ids:
                return {"compatible": True, "rejection_reason": None, "detail": "source_links_present"}
            return {"compatible": False, "rejection_reason": "derived_observation_unbound", "detail": "missing_source_links"}
        return {"compatible": True, "rejection_reason": None, "detail": "measured"}

    def _build_excluded_result(
        self,
        *,
        raw_label: str,
        row_type: str,
        family_adapter_id: str,
        specimen_context: str,
        language_id: str,
        measurement_kind: str,
        raw_unit_string: str,
        derived_formula_id: str,
        source_observation_ids: list[str],
    ) -> dict:
        return {
            "raw_label": raw_label,
            "normalized_label": self._normalize(raw_label),
            "context": {
                "row_type": row_type or None,
                "family_adapter_id": family_adapter_id or None,
                "specimen_context": specimen_context or None,
                "language_id": language_id or None,
                "measurement_kind": measurement_kind or None,
                "raw_unit_string": raw_unit_string or None,
                "derived_formula_id": derived_formula_id or None,
                "source_observation_ids": source_observation_ids,
            },
            "candidates": [],
            "candidate_trace": [
                {
                    "stage": "family_filter",
                    "status": "pass",
                    "detail": family_adapter_id or "default",
                },
                {
                    "stage": "row_type_filter",
                    "status": "fail",
                    "detail": row_type,
                },
            ],
            "accepted_candidate": None,
            "support_state": "unsupported",
            "support_code": row_type,
            "failure_code": row_type,
            "abstention_reasons": [row_type],
        }

    def _build_derived_unbound_result(
        self,
        *,
        raw_label: str,
        family_adapter_id: str,
        specimen_context: str,
        language_id: str,
        measurement_kind: str,
        raw_unit_string: str,
        source_observation_ids: list[str],
    ) -> dict:
        return {
            "raw_label": raw_label,
            "normalized_label": self._normalize(raw_label),
            "context": {
                "row_type": "derived_analyte_row",
                "family_adapter_id": family_adapter_id or None,
                "specimen_context": specimen_context or None,
                "language_id": language_id or None,
                "measurement_kind": measurement_kind or None,
                "raw_unit_string": raw_unit_string or None,
                "source_observation_ids": source_observation_ids,
            },
            "candidates": [],
            "candidate_trace": [
                {
                    "stage": "family_filter",
                    "status": "pass",
                    "detail": family_adapter_id or "default",
                },
                {
                    "stage": "derived_direct_compatibility",
                    "status": "fail",
                    "detail": "missing_source_links",
                },
            ],
            "accepted_candidate": None,
            "support_state": "unsupported",
            "support_code": "derived_observation_unbound",
            "failure_code": "derived_observation_unbound",
            "abstention_reasons": ["derived_observation_unbound"],
        }

    @staticmethod
    def _collect_abstention_reasons(candidates: list[dict], *, failure_code: str | None = None) -> list[str]:
        reasons: list[str] = []
        if failure_code and failure_code not in reasons:
            reasons.append(failure_code)
        for candidate in candidates:
            reason = candidate.get("rejection_reason")
            if reason and reason not in reasons:
                reasons.append(reason)
        return reasons

    def _apply_bilingual_normalization(self, value: str) -> str:
        translated = value
        for source, target in sorted(
            _BILINGUAL_TRANSLATIONS.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if source in translated:
                translated = translated.replace(source, target)
        deduped: list[str] = []
        for token in translated.split():
            if not deduped or deduped[-1] != token:
                deduped.append(token)
        if len(deduped) % 2 == 0:
            midpoint = len(deduped) // 2
            if deduped[:midpoint] == deduped[midpoint:]:
                deduped = deduped[:midpoint]
        return " ".join(deduped)

    @staticmethod
    def _normalize_identifier_list(value: object) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, (list, tuple, set)):
            return [identifier for identifier in (_normalize_identifier(item) for item in value) if identifier]
        normalized = _normalize_identifier(value)
        return [normalized] if normalized else []


def _normalize_identifier(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = " ".join(str(value).strip().split())
    if not text:
        return None
    return text.lower()


@lru_cache(maxsize=1)
def _load_launch_scope_metadata() -> dict:
    metadata_path = Path(__file__).resolve().parents[4] / "data" / "alias_tables" / "launch_scope_analyte_aliases.json"
    if metadata_path.exists():
        raw_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    else:
        raw_metadata = {
            "version": "launch-scope-analyte-aliases-v1",
            "analytes": [],
        }

    analytes: list[dict] = []
    for entry in raw_metadata.get("analytes", []):
        canonical_label = _normalize_metadata_text(entry.get("canonical_label"))
        aliases = {
            _normalize_metadata_text(canonical_label),
            _normalize_lookup_label(canonical_label),
        }
        aliases.update(_normalize_metadata_text(alias) for alias in entry.get("aliases", []))
        aliases.update(_normalize_lookup_label(alias) for alias in entry.get("aliases", []))
        aliases.update(_normalize_metadata_text(code) for code in entry.get("codes", []))
        analytes.append(
            {
                "canonical_label": canonical_label,
                "candidate_code": str(entry.get("codes", [""])[0] or "").strip(),
                "candidate_display": str(entry.get("candidate_display") or canonical_label or "unmapped").strip(),
                "threshold_used": float(entry.get("threshold_used") or 0.9),
                "panel_key": str(entry.get("panel_key") or "").strip(),
                "aliases": {alias for alias in aliases if alias},
            }
        )
    raw_metadata["analytes"] = analytes
    return raw_metadata


def _normalize_metadata_text(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _normalize_lookup_label(value: object) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("&", " and ")
    text = text.replace("%", " % ")
    text = text.replace("/", " / ")
    text = text.replace("-", " ")
    text = _LOOKUP_NORMALIZE_RE.sub(" ", text)
    return " ".join(text.split())


def _display_name(canonical_label: str) -> str:
    display_overrides = {
        "acr": "ACR",
        "egfr": "eGFR",
        "fasting glucose": "Glucose",
        "fasting plasma glucose": "Glucose",
        "hba1c": "HbA1c",
        "ldl-c": "LDL-C",
        "hdl-c": "HDL-C",
    }
    if canonical_label in display_overrides:
        return display_overrides[canonical_label]
    return " ".join(
        token.upper() if len(token) <= 3 else token.capitalize()
        for token in canonical_label.split()
    )
