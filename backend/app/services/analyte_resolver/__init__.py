"""Analyte resolver: auditable hybrid mapping (blueprint section 3.7)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


class AnalyteResolver:
    """Map raw analyte labels to terminology codes.

    Modes: deterministic lexical rules, optional empirical challenger.
    Never auto-accept below threshold. Every abstention reason stored.
    """

    def resolve(self, raw_label: str, context: dict) -> dict:
        normalized_label = self._normalize(raw_label)
        specimen_context = self._normalize(context.get("specimen_context", ""))
        language_id = self._normalize(context.get("language_id", ""))

        candidates = self._score_candidates(normalized_label, specimen_context, language_id)
        accepted_candidate = next((candidate for candidate in candidates if candidate["accepted"]), None)

        if accepted_candidate is None:
            support_state = "partial" if candidates else "unsupported"
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
        return " ".join(str(value or "").strip().lower().split())

    def _score_candidates(self, normalized_label: str, specimen_context: str, language_id: str) -> list[dict]:
        if not normalized_label:
            return []

        candidate = self._lookup_candidate(normalized_label, specimen_context, language_id)
        if candidate is None:
            return [
                {
                    "candidate_code": "__unmapped__",
                    "candidate_display": normalized_label or "unmapped",
                    "score": 0.0,
                    "threshold_used": 0.95,
                    "accepted": False,
                    "rejection_reason": "below_threshold",
                }
            ]

        score = candidate["score"]
        threshold_used = candidate["threshold_used"]
        accepted = score >= threshold_used
        return [
            {
                "candidate_code": candidate["candidate_code"],
                "candidate_display": candidate["candidate_display"],
                "score": score,
                "threshold_used": threshold_used,
                "accepted": accepted,
                "rejection_reason": None if accepted else "below_threshold",
            }
        ]

    def _lookup_candidate(self, normalized_label: str, specimen_context: str, language_id: str) -> dict | None:
        for analyte in _load_launch_scope_metadata()["analytes"]:
            aliases = analyte["aliases"]
            if normalized_label not in aliases:
                continue

            score = 0.99
            if analyte["panel_key"] == "glycemia" and specimen_context not in {"serum", "plasma", "blood", ""}:
                score = 0.95
            if analyte["canonical_label"] == "hba1c" and language_id not in {"en", ""}:
                score = min(score, 0.97)

            return {
                "candidate_code": analyte["candidate_code"],
                "candidate_display": analyte["candidate_display"],
                "threshold_used": analyte["threshold_used"],
                "score": score,
            }

        return None

    @staticmethod
    def _collect_abstention_reasons(candidates: list[dict]) -> list[str]:
        reasons = []
        for candidate in candidates:
            reason = candidate.get("rejection_reason")
            if reason and reason not in reasons:
                reasons.append(reason)
        return reasons


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
        aliases = {_normalize_metadata_text(canonical_label)}
        aliases.update(_normalize_metadata_text(alias) for alias in entry.get("aliases", []))
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
