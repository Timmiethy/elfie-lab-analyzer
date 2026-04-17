"""UCUM validation and canonical unit conversion."""

import re
from typing import Any

_UCUM_173_M2_RE = re.compile(r"\{1\.73[_ ]?m2\}", re.IGNORECASE)
_UCUM_WHITESPACE_RE = re.compile(r"\s+")


class UcumEngine:
    """Validate and convert units to canonical UCUM form.

    Unsafe unit false-accept target is zero.
    """

    MOLAR_WEIGHTS: dict[str, float] = {
        "glucose": 180.156,
        "cholesterol": 386.65,
        "triglycerides": 885.43,
        "calcium": 40.078,
        "creatinine": 113.12,
    }

    def validate_and_convert(
        self,
        value: float,
        from_unit: str,
        to_unit: str,
        analyte: str | None = None,
    ) -> dict[str, Any]:
        canonical_from = self._normalize_unit(from_unit)
        canonical_to = self._normalize_unit(to_unit)

        if canonical_from not in self._supported_units():
            raise ValueError(f"unsupported unit: {from_unit}")
        if canonical_to not in self._supported_units():
            raise ValueError(f"unsupported target unit: {to_unit}")

        if canonical_from != canonical_to:
            converted_value = self._attempt_molar_conversion(
                value, canonical_from, canonical_to, analyte
            )
            if converted_value is None:
                raise ValueError(f"unsupported conversion: {from_unit} -> {to_unit}")

            return {
                "original_value": value,
                "original_unit": from_unit,
                "canonical_value": converted_value,
                "canonical_unit": self._supported_units()[canonical_to],
                "conversion_applied": True,
                "engine_version": "ucum-v1",
            }

        return {
            "original_value": value,
            "original_unit": from_unit,
            "canonical_value": value,
            "canonical_unit": self._supported_units()[canonical_from],
            "conversion_applied": False,
            "engine_version": "ucum-v1",
        }

    def _attempt_molar_conversion(
        self,
        value: float,
        from_unit: str,
        to_unit: str,
        analyte: str | None,
    ) -> float | None:
        if not analyte:
            return None

        normalized_analyte = str(analyte).strip().lower()
        if normalized_analyte not in self.MOLAR_WEIGHTS:
            return None

        molar_mass = self.MOLAR_WEIGHTS[normalized_analyte]

        mass_factors: dict[str, float] = {
            "mg/dl": 0.01,
            "g/l": 1.0,
            "mg/l": 0.001,
        }
        molar_factors: dict[str, float] = {"mmol/l": 0.001, "umol/l": 0.000001}

        if from_unit in mass_factors and to_unit in molar_factors:
            g_per_l = value * mass_factors[from_unit]
            mol_per_l = g_per_l / molar_mass
            return round(mol_per_l / molar_factors[to_unit], 4)

        if from_unit in molar_factors and to_unit in mass_factors:
            mol_per_l_2 = value * molar_factors[from_unit]
            g_per_l_2 = mol_per_l_2 * molar_mass
            return round(g_per_l_2 / mass_factors[to_unit], 4)

        return None

    @staticmethod
    def _normalize_unit(unit: str) -> str:
        normalized = str(unit or "").strip().lower().replace("²", "2")
        normalized = _UCUM_173_M2_RE.sub("1.73 m2", normalized)
        normalized = _UCUM_WHITESPACE_RE.sub(" ", normalized)
        return normalized.strip()

    @staticmethod
    def _supported_units() -> dict[str, str]:
        return {
            "mg/dl": "mg/dL",
            "%": "%",
            "mmol/l": "mmol/L",
            "umol/l": "umol/L",
            "mmol/mol": "mmol/mol",
            "g/l": "g/L",
            "g/dl": "g/dL",
            "mg/l": "mg/L",
            "ng/ml": "ng/mL",
            "u/l": "U/L",
            "miu/l": "mIU/L",
            "ml/min/1.73 m2": "mL/min/{1.73_m2}",
            "ml/min/1.73m2": "mL/min/{1.73_m2}",
            "-": "1",
            "1": "1"
        }
