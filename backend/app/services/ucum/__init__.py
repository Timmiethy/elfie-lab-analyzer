"""UCUM validation and canonical unit conversion."""

from __future__ import annotations

from typing import Any

_SUPPORTED_UNITS = {
    "mg/dl": "mg/dL",
    "g/dl": "g/dL",
    "%": "%",
    "mcg/dl": "mcg/dL",
    "mmol/l": "mmol/L",
    "mmol/mol": "mmol/mol",
    "umol/l": "umol/L",
    "g/l": "g/L",
    "mg/l": "mg/L",
    "ng/l": "ng/L",
    "ng/ml": "ng/mL",
    "u/l": "U/L",
    "iu/l": "U/L",
    "miu/l": "mIU/L",
    "uiu/ml": "uIU/mL",
    "ml/min/1.73 m2": "mL/min/1.73 m2",
    "ml/min/1.73m2": "mL/min/1.73 m2",
    "ml/min/1.73 m^2": "mL/min/1.73 m2",
    "ml/min/1.73 m²": "mL/min/1.73 m2",
    "mg alb/mmol": "mg Alb/mmol",
    "mg alb/g": "mg Alb/g",
    "mg/g": "mg/g",
    "mg/g creatinine": "mg/g creatinine",
    "mg alb/g cr": "mg Alb/g Cr",
    "x10e3/ul": "x10E3/uL",
    "x10^3/ul": "x10E3/uL",
    "x10e6/ul": "x10E6/uL",
    "x10^6/ul": "x10E6/uL",
    "x10^3/µl": "x10E3/uL",
    "x10^3/μl": "x10E3/uL",
    "x10^6/µl": "x10E6/uL",
    "x10^6/μl": "x10E6/uL",
    "x10e9/l": "x10E9/L",
    "thousand/ul": "x10E3/uL",
    "thoursand/ul": "x10E3/uL",
    "million/ul": "x10E6/uL",
    "cells/ul": "/uL",
    "/ul": "/uL",
    "/µl": "/uL",
    "/μl": "/uL",
    "/l": "/L",
    "fl": "fL",
    "pg": "pg",
    "kg": "kg",
    "cm": "cm",
    "kg/sqm": "kg/sqm",
    "mm/h": "mm/h",
    "meq/l": "mEq/L",
    "mmol/liter": "mmol/L",
    "mg/dliter": "mg/dL",
    "g/dliter": "g/dL",
    "mmol/1": "mmol/L",
    "mg/1": "mg/dL",
    "g/1": "g/dL",
    "u/1": "U/L",
    "units/l": "U/L",
    "i.u./l": "U/L",
    "i.u./ml": "IU/mL",
    "mu/ml": "mU/mL",
}
_UNIT_FAMILY_BY_CANONICAL = {
    "mg/dL": "mass_concentration",
    "g/dL": "mass_concentration",
    "mcg/dL": "mass_concentration",
    "%": "ratio",
    "mmol/mol": "hba1c",
    "mmol/L": "molar_concentration",
    "umol/L": "molar_concentration",
    "g/L": "mass_concentration",
    "mg/L": "mass_concentration",
    "ng/L": "mass_concentration",
    "ng/mL": "mass_concentration",
    "U/L": "enzyme_activity",
    "mIU/L": "enzyme_activity",
    "uIU/mL": "enzyme_activity",
    "mL/min/1.73 m2": "filtration_rate",
    "mg Alb/mmol": "ratio",
    "mg Alb/g": "ratio",
    "mg/g": "ratio",
    "mg/g creatinine": "ratio",
    "mg Alb/g Cr": "ratio",
    "x10E3/uL": "cell_count",
    "x10E6/uL": "cell_count",
    "x10E9/L": "cell_count",
    "/uL": "cell_count",
    "/uL": "cell_count",
    "/L": "cell_count",
    "fL": "volume",
    "pg": "mass",
    "kg": "mass",
    "cm": "length",
    "kg/sqm": "derived_index",
    "mEq/L": "molar_concentration",
    "IU/mL": "enzyme_activity",
    "mU/mL": "enzyme_activity",
    "mm/h": "sedimentation_rate",
}


class UcumEngine:
    """Validate and convert units to canonical UCUM form.

    Unsafe unit false-accept target is zero.
    """

    def validate_and_convert(self, value: float, from_unit: str, to_unit: str) -> dict:
        canonical_from = self._normalize_unit(from_unit)
        canonical_to = self._normalize_unit(to_unit)

        if canonical_from not in self._supported_units():
            raise ValueError(f"unsupported unit: {from_unit}")
        if canonical_to not in self._supported_units():
            raise ValueError(f"unsupported target unit: {to_unit}")

        if canonical_from != canonical_to:
            raise ValueError(f"unsupported conversion: {from_unit} -> {to_unit}")

        canonical_unit = self._supported_units()[canonical_from]
        return {
            "original_value": value,
            "original_unit": from_unit,
            "canonical_value": value,
            "canonical_unit": canonical_unit,
            "conversion_applied": False,
            "unit_family": self.classify_unit_family(from_unit),
            "engine_version": "ucum-v1",
            "normalization_version": "ucum-v2",
        }

    def normalize_result_channel(self, result: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(result)
        raw_unit = normalized.get("unit")
        normalized_value = normalized.get("normalized_numeric_value")

        if raw_unit in (None, ""):
            normalized.update(
                {
                    "canonical_unit": None,
                    "canonical_value": normalized_value,
                    "unit_family": "unitless",
                    "unit_status": "unit_optional",
                    "engine_version": "ucum-v1",
                    "normalization_version": "ucum-v2",
                }
            )
            return normalized

        canonical_key = self._normalize_unit(raw_unit)
        if canonical_key not in self._supported_units():
            raise ValueError(f"unsupported unit: {raw_unit}")

        canonical_unit = self._supported_units()[canonical_key]
        normalized.update(
            {
                "unit": raw_unit,
                "normalized_unit": canonical_unit,
                "canonical_unit": canonical_unit,
                "canonical_value": normalized_value,
                "unit_family": self.classify_unit_family(raw_unit),
                "unit_status": "supported",
                "engine_version": "ucum-v1",
                "normalization_version": "ucum-v2",
            }
        )
        return normalized

    def normalize_dual_unit_channels(
        self,
        primary_result: dict[str, Any],
        secondary_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        normalized_primary = self.normalize_result_channel(primary_result)
        normalized_secondary = None
        if secondary_result is not None:
            normalized_secondary = self.normalize_result_channel(secondary_result)

        support_code = "measured_result"
        failure_code = None
        if normalized_secondary is not None:
            support_code = "dual_unit_result"
            if normalized_secondary.get("unit_status") == "unsupported":
                support_code = "partial_result"
                failure_code = "unit_parse_fail"

        return {
            "primary_result": normalized_primary,
            "secondary_result": normalized_secondary,
            "support_code": support_code,
            "failure_code": failure_code,
            "canonical_value": normalized_primary.get("canonical_value"),
            "canonical_unit": normalized_primary.get("canonical_unit"),
            "dual_unit_supported": normalized_secondary is not None and failure_code is None,
            "engine_version": "ucum-v1",
            "normalization_version": "ucum-v2",
        }

    def classify_unit_family(self, unit: str | None) -> str:
        canonical_key = self._normalize_unit(unit or "")
        canonical_unit = self._supported_units().get(canonical_key)
        if canonical_unit is None:
            return "unknown"
        return _UNIT_FAMILY_BY_CANONICAL.get(canonical_unit, "unknown")

    @staticmethod
    def _normalize_unit(unit: str) -> str:
        normalized = " ".join(str(unit or "").strip().lower().split())
        normalized = normalized.replace("²", "2").replace("^2", "2")
        return normalized

    @staticmethod
    def _supported_units() -> dict[str, str]:
        return _SUPPORTED_UNITS
