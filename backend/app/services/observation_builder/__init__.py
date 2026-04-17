"""Provisional observation builder."""

from __future__ import annotations

import logging
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from app.schemas.observation import CONTRACT_VERSION, SupportState

_LOGGER = logging.getLogger(__name__)


class ObservationBuilder:
    """Build provisional observations from validated extracted rows.

    Creates canonical observation records with support state tracking.
    """

    def build(self, validated_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []

        for row in validated_rows:
            document_id = row.get("document_id")
            row_hash = row.get("row_hash")
            raw_analyte_label = row.get("raw_analyte_label")
            source_page = row.get("source_page")

            if not document_id:
                raise ValueError("validated row missing document_id")
            if not row_hash:
                raise ValueError("validated row missing row_hash")
            if not raw_analyte_label:
                raise ValueError("validated row missing raw_analyte_label")
            if not isinstance(source_page, int) or source_page < 1:
                raise ValueError("validated row has invalid source_page")

            document_uuid = document_id if isinstance(document_id, UUID) else UUID(str(document_id))
            observation_id = uuid5(NAMESPACE_URL, f"{document_uuid}:{row_hash}")

            parsed_numeric_value = _parse_numeric(row.get("parsed_numeric_value"))
            support_state = _derive_support_state(row)

            observation = {
                "contract_version": CONTRACT_VERSION,
                "id": observation_id,
                "document_id": document_uuid,
                "source_page": source_page,
                "row_hash": row_hash,
                "raw_analyte_label": str(raw_analyte_label).strip(),
                "raw_value_string": row.get("raw_value_string"),
                "raw_unit_string": row.get("raw_unit_string"),
                "raw_reference_range": row.get("raw_reference_range"),
                "parsed_numeric_value": parsed_numeric_value,
                "specimen_context": row.get("specimen_context"),
                "method_context": row.get("method_context"),
                "language_id": row.get("language_id"),
                "candidates": row.get("candidates") or [],
                "accepted_analyte_code": row.get("accepted_analyte_code"),
                "accepted_analyte_display": row.get("accepted_analyte_display"),
                "canonical_unit": row.get("canonical_unit"),
                "canonical_value": row.get("canonical_value"),
                "support_state": support_state,
                "suppression_reasons": row.get("suppression_reasons") or [],
            }
            observations.append(observation)

        _LOGGER.debug("built %d observations", len(observations))
        return observations


def _parse_numeric(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None


def _derive_support_state(row: dict[str, Any]) -> SupportState:
    if row.get("accepted_analyte_code"):
        return SupportState.SUPPORTED
    return SupportState.UNSUPPORTED
