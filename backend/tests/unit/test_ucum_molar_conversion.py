import pytest

from app.services.ucum import UcumEngine


def test_molar_conversion_mass_to_molar() -> None:
    engine = UcumEngine()
    res = engine.validate_and_convert(180.156, "mg/dL", "mmol/L", analyte="glucose")
    assert res["canonical_value"] == 10.0
    assert res["canonical_unit"] == "mmol/L"


def test_molar_conversion_molar_to_mass() -> None:
    engine = UcumEngine()
    res = engine.validate_and_convert(5.0, "mmol/L", "mg/dL", analyte="cholesterol")
    assert res["canonical_value"] == 193.325
    assert res["canonical_unit"] == "mg/dL"


def test_missing_analyte_fails() -> None:
    engine = UcumEngine()
    with pytest.raises(ValueError, match="unsupported conversion"):
        engine.validate_and_convert(100.0, "mg/dL", "mmol/L", analyte="unknown_analyte")


def test_no_analyte_fails_when_conversion_needed() -> None:
    engine = UcumEngine()
    with pytest.raises(ValueError, match="unsupported conversion"):
        engine.validate_and_convert(100.0, "mg/dL", "mmol/L")


def test_same_unit_does_not_require_analyte() -> None:
    engine = UcumEngine()
    res = engine.validate_and_convert(100.0, "mg/dL", "mg/dL")
    assert res["canonical_value"] == 100.0
    assert res["canonical_unit"] == "mg/dL"
