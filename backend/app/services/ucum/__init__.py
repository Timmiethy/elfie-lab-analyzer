"""UCUM validation and canonical unit conversion."""


class UcumEngine:
    """Validate and convert units to canonical UCUM form.

    Unsafe unit false-accept target is zero.
    """

    def validate_and_convert(self, value: float, from_unit: str, to_unit: str) -> dict:
        raise NotImplementedError
