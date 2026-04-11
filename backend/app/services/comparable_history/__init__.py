"""Comparable history lookup and rendering helpers."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Observation


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _format_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return f"{float(value):g}"
    return str(value)


def _direction(current_value: float, previous_value: float) -> str:
    if current_value > previous_value:
        return "increased"
    if current_value < previous_value:
        return "decreased"
    return "similar"


def _observation_value(observation: dict | Observation) -> float | None:
    canonical_value = getattr(observation, "canonical_value", None)
    if canonical_value is None and isinstance(observation, dict):
        canonical_value = observation.get("canonical_value")

    parsed_numeric_value = getattr(observation, "parsed_numeric_value", None)
    if parsed_numeric_value is None and isinstance(observation, dict):
        parsed_numeric_value = observation.get("parsed_numeric_value")

    raw_value_string = getattr(observation, "raw_value_string", None)
    if raw_value_string is None and isinstance(observation, dict):
        raw_value_string = observation.get("raw_value_string")

    for candidate in (canonical_value, parsed_numeric_value, raw_value_string):
        if candidate in (None, ""):
            continue
        try:
            return float(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _observation_unit(observation: dict | Observation) -> str:
    for field_name in ("canonical_unit", "raw_unit_string"):
        value = getattr(observation, field_name, None)
        if value is None and isinstance(observation, dict):
            value = observation.get(field_name)
        normalized = _normalize_text(value)
        if normalized is not None:
            return normalized
    return ""


def _observation_analyte_display(observation: dict | Observation) -> str:
    for field_name in ("accepted_analyte_display", "raw_analyte_label"):
        value = getattr(observation, field_name, None)
        if value is None and isinstance(observation, dict):
            value = observation.get(field_name)
        normalized = _normalize_text(value)
        if normalized is not None:
            return normalized
    return "Unknown analyte"


def _observation_support_state(observation: dict | Observation) -> str:
    value = getattr(observation, "support_state", None)
    if value is None and isinstance(observation, dict):
        value = observation.get("support_state")
    if hasattr(value, "value"):
        value = value.value
    return str(value or "").lower()


class ComparableHistoryService:
    def __init__(self, session: AsyncSession | None) -> None:
        self.session = session

    async def build_for_artifact(
        self,
        *,
        job_id: UUID,
        observations: list[dict],
        report_date: str,
    ) -> dict | None:
        current_observation = self._select_current_observation(observations)
        if current_observation is None:
            return None

        prior_observation = await self._find_prior_comparable_observation(
            job_id,
            current_observation,
        )
        if prior_observation is None:
            return self._build_unavailable_card(
                current_observation,
                report_date=report_date,
            )

        return self._build_available_card(
            current_observation,
            prior_observation,
            report_date=report_date,
        )

    @staticmethod
    def _select_current_observation(observations: list[dict]) -> dict | None:
        for observation in observations:
            if _observation_support_state(observation) != "supported":
                continue
            if _observation_value(observation) is None:
                continue
            analyte_code = _normalize_text(observation.get("accepted_analyte_code"))
            analyte_display = _normalize_text(observation.get("accepted_analyte_display"))
            raw_label = _normalize_text(observation.get("raw_analyte_label"))
            if analyte_code or analyte_display or raw_label:
                return observation
        return None

    async def _find_prior_comparable_observation(
        self,
        job_id: UUID,
        current_observation: dict,
    ) -> Observation | None:
        if self.session is None or not callable(getattr(self.session, "execute", None)):
            return None

        analyte_code = _normalize_text(current_observation.get("accepted_analyte_code"))
        analyte_display = _normalize_text(current_observation.get("accepted_analyte_display"))
        raw_label = _normalize_text(current_observation.get("raw_analyte_label"))
        current_unit = _observation_unit(current_observation)
        specimen_context = _normalize_text(current_observation.get("specimen_context"))
        method_context = _normalize_text(current_observation.get("method_context"))

        stmt = (
            select(Observation)
            .where(Observation.job_id != job_id)
            .where(Observation.support_state == "supported")
            .order_by(Observation.created_at.desc(), Observation.id.desc())
        )

        if analyte_code is not None:
            stmt = stmt.where(Observation.accepted_analyte_code == analyte_code)
        elif analyte_display is not None:
            stmt = stmt.where(Observation.accepted_analyte_display == analyte_display)
        elif raw_label is not None:
            stmt = stmt.where(Observation.raw_analyte_label == raw_label)
        else:
            return None

        if current_unit:
            stmt = stmt.where(Observation.canonical_unit == current_unit)

        if specimen_context is not None:
            stmt = stmt.where(Observation.specimen_context == specimen_context)
        else:
            stmt = stmt.where(Observation.specimen_context.is_(None))

        if method_context is not None:
            stmt = stmt.where(Observation.method_context == method_context)
        else:
            stmt = stmt.where(Observation.method_context.is_(None))

        result = await self.session.execute(stmt.limit(1))
        return result.scalar_one_or_none()

    @staticmethod
    def _build_unavailable_card(
        current_observation: dict,
        *,
        report_date: str,
    ) -> dict:
        return {
            "analyte_display": _observation_analyte_display(current_observation),
            "current_value": _format_value(_observation_value(current_observation)),
            "current_unit": _observation_unit(current_observation),
            "previous_value": None,
            "previous_unit": None,
            "current_date": report_date,
            "previous_date": None,
            "direction": "trend_unavailable",
            "comparability_status": "unavailable",
        }

    @staticmethod
    def _build_available_card(
        current_observation: dict,
        prior_observation: Observation,
        *,
        report_date: str,
    ) -> dict:
        current_value = _observation_value(current_observation)
        prior_value = _observation_value(prior_observation)
        if current_value is None or prior_value is None:
            return ComparableHistoryService._build_unavailable_card(
                current_observation,
                report_date=report_date,
            )

        return {
            "analyte_display": _observation_analyte_display(current_observation),
            "current_value": _format_value(current_value),
            "current_unit": _observation_unit(current_observation),
            "previous_value": _format_value(prior_value),
            "previous_unit": _observation_unit(prior_observation),
            "current_date": report_date,
            "previous_date": prior_observation.created_at.date().isoformat(),
            "direction": _direction(current_value, prior_value),
            "comparability_status": "available",
        }
