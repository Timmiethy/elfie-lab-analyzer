"""Metric resolver: demographic-appropriate reference profile selection (blueprint section 3.7)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.schemas.metric import MetricDefinition, ReferenceProfile
from app.schemas.patient_context import PatientContext
from app.services.data_paths import resolve_data_file

_LOGGER = logging.getLogger(__name__)


class MetricResolver:
    """Resolve metric definitions and select appropriate reference profiles.

    Loads core_metrics catalog and implements deterministic profile selection
    based on patient demographics (age, sex, pregnancy status).
    """

    def __init__(self, catalog_path: Path | None = None):
        if catalog_path is None:
            catalog_path = resolve_data_file(
                __file__,
                "metric_definitions",
                "core_metrics.json",
            )

        self.metrics: dict[str, MetricDefinition] = {}
        self._lookup: dict[str, MetricDefinition] = {}
        if catalog_path.exists():
            try:
                with open(catalog_path, encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for m in data:
                            if not isinstance(m, dict):
                                continue
                            metric_def = MetricDefinition(**m)
                            self.metrics[metric_def.metric_id] = metric_def
                            self._lookup[metric_def.metric_id.lower()] = metric_def
                            self._lookup[metric_def.canonical_name.lower().strip()] = metric_def
                            for loinc in metric_def.loinc_candidates:
                                self._lookup[loinc.lower().strip()] = metric_def
                            for alias in metric_def.aliases:
                                self._lookup[alias.lower().strip()] = metric_def
            except (json.JSONDecodeError, ValueError):
                pass

        # Bridge launch_scope_analyte_aliases canonical_labels -> core_metrics metric_id.
        # core_metrics.json uses "METRIC-00NN" (capital, dash, 4-digit zero-pad); earlier
        # code here wrote "metric_0NN" which silently missed every lookup and caused every
        # finding to fall through to suppression_active=True / severity_class=SX.
        hack_mapping = {
            "fasting glucose": "METRIC-0019",
            "hba1c": "METRIC-0063",
            "total cholesterol": "METRIC-0051",
            "ldl-c": "METRIC-0053",
            "hdl-c": "METRIC-0052",
            "triglycerides": "METRIC-0054",
            "creatinine": "METRIC-0029",
            "egfr": "METRIC-0030",
        }

        alias_path = resolve_data_file(
            __file__,
            "alias_tables",
            "launch_scope_analyte_aliases.json",
        )
        if alias_path.exists():
            try:
                with open(alias_path, encoding="utf-8") as f:
                    aliases_data = json.load(f)
                    for a in aliases_data.get("analytes", []):
                        canonical = a.get("canonical_label", "").lower()
                        target_metric_id = hack_mapping.get(canonical)
                        if target_metric_id and target_metric_id in self.metrics:
                            target_metric = self.metrics[target_metric_id]
                            self._lookup[canonical] = target_metric
                            for code in a.get("codes", []):
                                self._lookup[code.lower().strip()] = target_metric
                            for alias in a.get("aliases", []):
                                self._lookup[alias.lower().strip()] = target_metric
                        elif target_metric_id:
                            _LOGGER.warning(
                                "metric_resolver_hack_mapping_miss canonical=%s target=%s "
                                "(available_count=%d)",
                                canonical,
                                target_metric_id,
                                len(self.metrics),
                            )
            except Exception:
                pass

        _LOGGER.info(
            "metric_resolver_loaded metrics=%d lookup_keys=%d "
            "has_triglycerides=%s has_hba1c=%s has_creatinine=%s has_egfr=%s",
            len(self.metrics),
            len(self._lookup),
            "triglycerides" in self._lookup,
            "hba1c" in self._lookup,
            "creatinine" in self._lookup,
            "egfr" in self._lookup,
        )

    def resolve_profile(
        self, metric_id: str, patient_context: PatientContext
    ) -> ReferenceProfile | None:
        """Select demographic-appropriate reference profile with deterministic precedence.

        Deterministic precedence rules:
        1. Only profiles matching patient demographics are considered.
        2. Profiles are sorted by priority (lowest number first).
        3. If priorities are equal, profiles with more specific filters take precedence.
        4. If multiple profiles have equal highest precedence, it returns None (abstain).

        Returns None if no match is found or if selection is ambiguous.
        """
        metric = self._lookup.get((metric_id or "").lower().strip())
        if not metric:
            return None

        matching_profiles = [
            p for p in metric.default_reference_profiles if self._matches(p, patient_context)
        ]

        if not matching_profiles:
            return None

        # Sort by priority (ascending) then by specificity (descending)
        # Lower priority number = higher precedence (0 is highest)
        # Higher specificity score = higher precedence
        matching_profiles.sort(key=lambda p: (p.priority, -self._get_specificity(p)))

        # Ambiguity check: multiple profiles with same priority and specificity
        if len(matching_profiles) > 1:
            best = matching_profiles[0]
            next_best = matching_profiles[1]
            if best.priority == next_best.priority and self._get_specificity(
                best
            ) == self._get_specificity(next_best):
                # Ambiguous selection: abstain behavior
                return None

        return matching_profiles[0]

    def _matches(self, profile: ReferenceProfile, patient: PatientContext) -> bool:
        """Check if profile applies to patient demographics."""
        applies = profile.applies_to

        # Sex filter
        if applies.sex is not None:
            if patient.sex not in applies.sex:
                return False

        # Age filters
        if applies.age_low is not None or applies.age_high is not None:
            if patient.age_years is None:
                return False
            if applies.age_low is not None and patient.age_years < applies.age_low:
                return False
            if applies.age_high is not None and patient.age_years > applies.age_high:
                return False

        # Pregnancy filter
        if applies.pregnancy is not None:
            if patient.pregnancy_status != applies.pregnancy:
                return False

        return True

    def _get_specificity(self, profile: ReferenceProfile) -> int:
        """Calculate specificity score (number of non-null demographic filters)."""
        applies = profile.applies_to
        score = 0
        if applies.sex is not None:
            score += 1
        if applies.age_low is not None:
            score += 1
        if applies.age_high is not None:
            score += 1
        if applies.pregnancy is not None:
            score += 1
        return score
