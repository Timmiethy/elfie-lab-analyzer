"""UCUM validation and canonical unit conversion."""


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
            "engine_version": "ucum-v1",
        }

    @staticmethod
    def _normalize_unit(unit: str) -> str:
        return " ".join(str(unit or "").strip().lower().split())

    @staticmethod
    def _supported_units() -> dict[str, str]:
        return {
            "mg/dl": "mg/dL",
            "%": "%",
            "mmol/l": "mmol/L",
            "g/l": "g/L",
            "mg/l": "mg/L",
            "ng/ml": "ng/mL",
            "u/l": "U/L",
            "miu/l": "mIU/L",
            "ml/min/1.73 m2": "mL/min/1.73 m2",
            "ml/min/1.73m2": "mL/min/1.73 m2",
        }
