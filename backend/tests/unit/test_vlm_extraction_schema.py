import pytest
from pydantic import ValidationError

from app.schemas.extraction import BBox, ExtractedMeasurement


def test_valid_extraction() -> None:
    data = {
        "name": "Glucose",
        "value": 100.0,
        "unit": "mg/dL",
        "confidence": 0.95,
        "bbox": {"x_min": 10.0, "y_min": 20.0, "x_max": 30.0, "y_max": 40.0},
    }
    meas = ExtractedMeasurement(**data)
    assert meas.name == "Glucose"
    assert meas.confidence == 0.95


def test_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        ExtractedMeasurement(name="Glucose", value=100.0, unit="mg/dL", confidence=1.5)


def test_invalid_bbox() -> None:
    with pytest.raises(ValidationError):
        BBox(x_min=-1.0, y_min=0.0, x_max=10.0, y_max=10.0)
