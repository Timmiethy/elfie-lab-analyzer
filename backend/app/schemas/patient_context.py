"""Patient context contract (blueprint section 3.5)."""

from pydantic import BaseModel


class PatientContext(BaseModel):
    birth_year: int | None = None
    age_years: float | None = None
    age_band: str | None = None
    sex: str | None = None
    pregnancy_status: bool | None = None
    metabolic_state: str | None = None
    weight_kg: float | None = None
    kidney_function_category: str | None = None
    preferred_language: str = "en"
    country: str | None = None
    region: str | None = None
    known_conditions: list[str] = []
    medication_classes: list[str] = []
