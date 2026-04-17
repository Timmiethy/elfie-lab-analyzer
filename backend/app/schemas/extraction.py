from pydantic import BaseModel, Field


class BBox(BaseModel):
    x_min: float = Field(..., ge=0.0)
    y_min: float = Field(..., ge=0.0)
    x_max: float = Field(..., ge=0.0)
    y_max: float = Field(..., ge=0.0)


class ExtractedMeasurement(BaseModel):
    name: str
    value: float
    unit: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    bbox: BBox | None = None


class FlatExtractionSchema(BaseModel):
    measurements: list[ExtractedMeasurement]
