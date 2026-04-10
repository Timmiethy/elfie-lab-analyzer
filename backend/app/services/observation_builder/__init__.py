"""Provisional observation builder."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid5

from app.schemas.observation import SupportState


class ObservationBuilder:
    """Build provisional observations from validated extracted rows.

    Creates canonical observation records with support state tracking.
    """

    def build(self, validated_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []

        for row in validated_rows:
            normalized_row = deepcopy(row)
            document_id = normalized_row.get("document_id")
            row_hash = normalized_row.get("row_hash")

            if not document_id:
                raise ValueError("validated row missing document_id")
            if not row_hash:
                raise ValueError("validated row missing row_hash")
            if not normalized_row.get("raw_analyte_label"):
                raise ValueError("validated row missing raw_analyte_label")

            document_uuid = document_id if isinstance(document_id, UUID) else UUID(str(document_id))
            observation_id = uuid5(NAMESPACE_URL, f"{document_uuid}:{row_hash}")

            observation = {
                "id": observation_id,
                "document_id": document_uuid,
                "source_page": normalized_row["source_page"],
                "row_hash": row_hash,
                "raw_analyte_label": str(normalized_row["raw_analyte_label"]).strip(),
                "raw_value_string": normalized_row.get("raw_value_string"),
                "raw_unit_string": normalized_row.get("raw_unit_string"),
                "raw_reference_range": normalized_row.get("raw_reference_range"),
                "parsed_numeric_value": normalized_row.get("parsed_numeric_value"),
                "specimen_context": normalized_row.get("specimen_context"),
                "method_context": normalized_row.get("method_context"),
                "language_id": normalized_row.get("language_id"),
                "candidates": normalized_row.get("candidates", []),
                "accepted_analyte_code": normalized_row.get("accepted_analyte_code"),
                "accepted_analyte_display": normalized_row.get("accepted_analyte_display"),
                "canonical_unit": normalized_row.get("canonical_unit"),
                "canonical_value": normalized_row.get("canonical_value"),
                "support_state": SupportState.SUPPORTED,
                "suppression_reasons": normalized_row.get("suppression_reasons", []),
            }
            observations.append(observation)

        return observations
