"""Provisional observation builder."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from app.schemas.observation import CONTRACT_VERSION, SupportState
from app.services.ucum import UcumEngine

_LOGGER = logging.getLogger(__name__)
_NORMALIZATION_CONTRACT_VERSION = "observation-contract-v2"
_EXCLUDED_ROW_TYPES = {
    "admin_metadata_row",
    "threshold_table_row",
    "narrative_row",
    "header_row",
    "footer_row",
    "test_request_row",
}
_RESULT_ROW_TYPES = {"measured_analyte_row", "derived_analyte_row"}
_ROW_TYPE_ALIASES = {
    "admin": "admin_metadata_row",
    "administrative": "admin_metadata_row",
    "threshold": "threshold_table_row",
    "threshold_table": "threshold_table_row",
    "narrative": "narrative_row",
    "header": "header_row",
    "footer": "footer_row",
    "test_request": "test_request_row",
    "measured": "measured_analyte_row",
    "result": "measured_analyte_row",
    "derived": "derived_analyte_row",
}
_ROW_TYPE_TO_MEASUREMENT_KIND = {
    "measured_analyte_row": "direct_measurement",
    "derived_analyte_row": "derived_measurement",
    "threshold_table_row": "threshold_reference",
    "admin_metadata_row": "narrative_context",
    "narrative_row": "narrative_context",
    "header_row": "narrative_context",
    "footer_row": "narrative_context",
    "test_request_row": "narrative_context",
}
_ROW_TYPE_TO_FAILURE_CODE = {
    "admin_metadata_row": "admin_metadata_row",
    "threshold_table_row": "threshold_table_row",
    "narrative_row": "narrative_row",
    "header_row": "footer_or_header_row",
    "footer_row": "footer_or_header_row",
    "test_request_row": "admin_metadata_row",
}
_COMPARATOR_PATTERN = re.compile(r"^(?P<comparator><=|>=|<|>|≤|≥)\s*(?P<value>.+)$")
_NUMERIC_FRAGMENT_PATTERN = re.compile(r"[-+]?\d[\d.,\s\u00a0]*")


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

            row_type = _normalize_row_type(row)
            measurement_kind = _measurement_kind_for_row_type(row_type)
            source_observation_ids = _normalize_identifier_list(row.get("source_observation_ids"))
            derived_formula_id = _normalize_identifier(row.get("derived_formula_id"))
            family_adapter_id = _normalize_identifier(row.get("family_adapter_id"))

            parsed_numeric_value = _parse_numeric(row.get("parsed_numeric_value"))
            primary_result = _build_result_channel(
                raw_value=row.get("raw_value_string"),
                raw_unit=row.get("raw_unit_string"),
                fallback_numeric=parsed_numeric_value,
            )
            reference_range = _parse_reference_range(row.get("raw_reference_range"))
            secondary_result = _build_secondary_result(row)

            ucum_engine = UcumEngine()
            primary_unit_status = "unit_optional"
            secondary_unit_status = "unit_optional"
            canonical_unit = None
            canonical_value = None

            if primary_result is not None:
                try:
                    primary_result = ucum_engine.normalize_result_channel(primary_result)
                    primary_unit_status = str(primary_result.get("unit_status") or "supported")
                    canonical_unit = primary_result.get("canonical_unit")
                    canonical_value = primary_result.get("canonical_value")
                    parsed_numeric_value = primary_result.get("normalized_numeric_value")
                except ValueError as exc:
                    primary_unit_status = "unsupported"
                    primary_result["unit_status"] = "unsupported"
                    primary_result["unit_error"] = str(exc)

            if secondary_result is not None:
                try:
                    secondary_result = ucum_engine.normalize_result_channel(secondary_result)
                    secondary_unit_status = str(secondary_result.get("unit_status") or "supported")
                except ValueError as exc:
                    secondary_unit_status = "unsupported"
                    secondary_result["unit_status"] = "unsupported"
                    secondary_result["unit_error"] = str(exc)

            candidate_trace = _normalize_candidate_trace(row.get("candidate_trace"))
            if not candidate_trace and row.get("candidates"):
                candidate_trace = [
                    {
                        "stage": "resolver_candidates",
                        "status": "present",
                        "detail": _json_safe(row.get("candidates")),
                    }
                ]

            support_code, failure_code, support_state, eligible_for_pool = _derive_support_outcome(
                row_type=row_type,
                primary_result=primary_result,
                secondary_result=secondary_result,
                parsed_numeric_value=parsed_numeric_value,
                raw_value_string=row.get("raw_value_string"),
                accepted_analyte_code=row.get("accepted_analyte_code"),
                source_observation_ids=source_observation_ids,
                primary_unit_status=primary_unit_status,
                secondary_unit_status=secondary_unit_status,
            )

            observation = {
                "contract_version": CONTRACT_VERSION,
                "normalization_contract_version": _NORMALIZATION_CONTRACT_VERSION,
                "id": observation_id,
                "document_id": document_uuid,
                "source_page": source_page,
                "row_hash": row_hash,
                "raw_analyte_label": str(raw_analyte_label).strip(),
                "row_type": row_type,
                "measurement_kind": measurement_kind,
                "eligible_for_observation_pool": eligible_for_pool,
                "support_code": support_code,
                "failure_code": failure_code,
                "raw_value_string": row.get("raw_value_string"),
                "raw_unit_string": row.get("raw_unit_string"),
                "raw_reference_range": row.get("raw_reference_range"),
                "reference_range": reference_range,
                "parsed_numeric_value": parsed_numeric_value,
                "parsed_locale": _compact_locale_descriptor(
                    primary_result["parse_locale"] if primary_result else None
                ),
                "parsed_comparator": primary_result["normalized_comparator"] if primary_result else None,
                "primary_result": primary_result,
                "secondary_result": secondary_result,
                "specimen_context": row.get("specimen_context"),
                "method_context": row.get("method_context"),
                "language_id": row.get("language_id"),
                "family_adapter_id": family_adapter_id,
                "candidate_trace": candidate_trace,
                "source_observation_ids": source_observation_ids,
                "derived_formula_id": derived_formula_id,
                "candidates": row.get("candidates") or [],
                "accepted_analyte_code": row.get("accepted_analyte_code"),
                "accepted_analyte_display": row.get("accepted_analyte_display"),
                "canonical_unit": canonical_unit,
                "canonical_value": canonical_value,
                "support_state": support_state,
                "suppression_reasons": row.get("suppression_reasons") or [],
            }
            observations.append(observation)

        _LOGGER.debug("built %d observations", len(observations))
        return observations


def _normalize_row_type(row: dict[str, Any]) -> str:
    raw_row_type = _normalize_identifier(row.get("row_type"))
    if not raw_row_type:
        if row.get("derived_formula_id") or row.get("source_observation_ids"):
            return "derived_analyte_row"
        return "measured_analyte_row"
    return _ROW_TYPE_ALIASES.get(raw_row_type, raw_row_type)


def _measurement_kind_for_row_type(row_type: str) -> str:
    return _ROW_TYPE_TO_MEASUREMENT_KIND.get(row_type, "direct_measurement")


def _derive_support_outcome(
    *,
    row_type: str,
    primary_result: dict[str, Any] | None,
    secondary_result: dict[str, Any] | None,
    parsed_numeric_value: float | None,
    raw_value_string: Any,
    accepted_analyte_code: Any,
    source_observation_ids: list[str],
    primary_unit_status: str,
    secondary_unit_status: str,
) -> tuple[str, str | None, str, bool]:
    if row_type in _EXCLUDED_ROW_TYPES:
        failure_code = _ROW_TYPE_TO_FAILURE_CODE[row_type]
        return row_type, failure_code, SupportState.UNSUPPORTED.value, False

    if row_type == "derived_analyte_row" and not source_observation_ids:
        return "derived_observation_unbound", "derived_observation_unbound", SupportState.UNSUPPORTED.value, False

    if primary_unit_status == "unsupported" or secondary_unit_status == "unsupported":
        return "partial_result", "unit_parse_fail", SupportState.PARTIAL.value, True

    if parsed_numeric_value is None and raw_value_string not in (None, ""):
        return "partial_result", "unreadable_value", SupportState.PARTIAL.value, row_type in _RESULT_ROW_TYPES

    if accepted_analyte_code:
        if row_type == "derived_analyte_row":
            return "derived_result", None, SupportState.SUPPORTED.value, True
        if secondary_result is not None:
            return "dual_unit_result", None, SupportState.SUPPORTED.value, True
        return "measured_result", None, SupportState.SUPPORTED.value, True

    if row_type == "derived_analyte_row":
        return "partial_result", "unsupported_family", SupportState.PARTIAL.value, True

    return "partial_result", "unsupported_family", SupportState.PARTIAL.value, row_type in _RESULT_ROW_TYPES


def _build_result_channel(
    *,
    raw_value: Any,
    raw_unit: Any,
    fallback_numeric: Any,
) -> dict[str, Any] | None:
    if raw_value in (None, "") and fallback_numeric is None and raw_unit in (None, ""):
        return None

    parsed = _parse_value_expression(raw_value, fallback_numeric=fallback_numeric)
    result = {
        "raw_token_string": parsed["raw_token_string"],
        "raw_value": parsed["raw_token_string"],
        "normalized_comparator": parsed["normalized_comparator"],
        "comparator": parsed["normalized_comparator"],
        "normalized_numeric_value": parsed["normalized_numeric_value"],
        "numeric_value": parsed["normalized_numeric_value"],
        "unit": _normalize_identifier(raw_unit),
        "parse_locale": parsed["parse_locale"],
        "locale": _compact_locale_descriptor(parsed["parse_locale"]),
        "value_channel": "primary_result",
        "parse_confidence": parsed["parse_confidence"],
        "canonical_unit": None,
        "canonical_value": parsed["normalized_numeric_value"],
        "unit_status": "unit_optional" if raw_unit in (None, "") else "pending",
    }
    return result


def _build_secondary_result(row: dict[str, Any]) -> dict[str, Any] | None:
    raw_value = row.get("secondary_raw_value_string")
    if raw_value in (None, ""):
        raw_value = row.get("raw_secondary_value_string")

    raw_unit = row.get("secondary_raw_unit_string")
    if raw_unit in (None, ""):
        raw_unit = row.get("raw_secondary_unit_string")

    if raw_value in (None, "") and raw_unit in (None, ""):
        secondary_result = row.get("secondary_result")
        if isinstance(secondary_result, dict) and secondary_result:
            if "unit" in secondary_result or "normalized_numeric_value" in secondary_result:
                return dict(secondary_result)
            return {
                "raw_token_string": secondary_result.get("raw_value_string"),
                "raw_value": secondary_result.get("raw_value_string"),
                "normalized_comparator": secondary_result.get("parsed_comparator"),
                "comparator": secondary_result.get("parsed_comparator"),
                "normalized_numeric_value": _parse_numeric(
                    secondary_result.get("parsed_numeric_value")
                ),
                "numeric_value": _parse_numeric(
                    secondary_result.get("parsed_numeric_value")
                ),
                "unit": _normalize_identifier(secondary_result.get("raw_unit_string")),
                "parse_locale": secondary_result.get("parsed_locale")
                or _locale_descriptor(None),
                "locale": _compact_locale_descriptor(
                    secondary_result.get("parsed_locale") or _locale_descriptor(None)
                ),
                "value_channel": "secondary_result",
                "parse_confidence": 1.0
                if secondary_result.get("parsed_numeric_value") is not None
                else 0.0,
                "canonical_unit": None,
                "canonical_value": _parse_numeric(
                    secondary_result.get("parsed_numeric_value")
                ),
                "unit_status": "unit_optional"
                if secondary_result.get("raw_unit_string") in (None, "")
                else "pending",
            }
        return None

    parsed = _parse_value_expression(raw_value, fallback_numeric=row.get("secondary_parsed_numeric_value"))
    return {
        "raw_token_string": parsed["raw_token_string"],
        "raw_value": parsed["raw_token_string"],
        "normalized_comparator": parsed["normalized_comparator"],
        "comparator": parsed["normalized_comparator"],
        "normalized_numeric_value": parsed["normalized_numeric_value"],
        "numeric_value": parsed["normalized_numeric_value"],
        "unit": _normalize_identifier(raw_unit),
        "parse_locale": parsed["parse_locale"],
        "locale": _compact_locale_descriptor(parsed["parse_locale"]),
        "value_channel": "secondary_result",
        "parse_confidence": parsed["parse_confidence"],
        "canonical_unit": None,
        "canonical_value": parsed["normalized_numeric_value"],
        "unit_status": "unit_optional" if raw_unit in (None, "") else "pending",
    }


def _parse_value_expression(value: Any, *, fallback_numeric: Any | None = None) -> dict[str, Any]:
    raw_text = "" if value is None else str(value).strip()
    if not raw_text and fallback_numeric is None:
        return {
            "raw_token_string": None,
            "normalized_comparator": None,
            "normalized_numeric_value": None,
            "parse_locale": _locale_descriptor(None),
            "parse_confidence": 0.0,
        }

    comparator, stripped_value = _split_comparator(raw_text)
    numeric_fragment = _extract_numeric_fragment(stripped_value or raw_text)
    numeric_value, locale = _parse_numeric_fragment(numeric_fragment)

    if numeric_value is None and fallback_numeric is not None:
        numeric_value = _parse_numeric(fallback_numeric)
        if numeric_value is not None and not locale:
            locale = _locale_descriptor(".")

    return {
        "raw_token_string": raw_text or (None if fallback_numeric is None else str(fallback_numeric)),
        "normalized_comparator": comparator,
        "normalized_numeric_value": numeric_value,
        "parse_locale": locale or _locale_descriptor(None),
        "parse_confidence": 1.0 if numeric_value is not None else 0.0,
    }


def _parse_reference_range(value: Any) -> dict[str, Any] | None:
    if value in (None, ""):
        return None

    raw_text = str(value).strip()
    comparator, stripped_value = _split_comparator(raw_text)
    numeric_fragment = _extract_numeric_fragment(stripped_value or raw_text)
    numeric_value, locale = _parse_numeric_fragment(numeric_fragment)

    if comparator and numeric_value is not None:
        return {
            "raw_token_string": raw_text,
            "normalized_comparator": comparator,
            "normalized_numeric_value": numeric_value,
            "parse_locale": locale or _locale_descriptor(None),
        }

    if "-" in raw_text and not raw_text.lstrip().startswith("-"):
        lower_raw, upper_raw = raw_text.split("-", 1)
        lower_value, lower_locale = _parse_numeric_fragment(_extract_numeric_fragment(lower_raw))
        upper_value, upper_locale = _parse_numeric_fragment(_extract_numeric_fragment(upper_raw))
        return {
            "raw_token_string": raw_text,
            "normalized_comparator": "range",
            "lower_bound": lower_value,
            "upper_bound": upper_value,
            "parse_locale": lower_locale or upper_locale or _locale_descriptor(None),
        }

    return {
        "raw_token_string": raw_text,
        "normalized_comparator": comparator,
        "normalized_numeric_value": numeric_value,
        "parse_locale": locale or _locale_descriptor(None),
    }


def _parse_numeric(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return _parse_numeric_text(str(value))


def _parse_numeric_fragment(fragment: str | None) -> tuple[float | None, dict[str, Any]]:
    if not fragment:
        return None, _locale_descriptor(None)

    _, numeric_fragment = _split_comparator(str(fragment))
    normalized, locale = _normalize_numeric_text(numeric_fragment)
    if not normalized:
        return None, locale

    try:
        return float(normalized), locale
    except ValueError:
        return None, locale


def _parse_numeric_text(raw_text: str) -> float | None:
    fragment = _extract_numeric_fragment(raw_text)
    numeric_value, _ = _parse_numeric_fragment(fragment)
    return numeric_value


def _extract_numeric_fragment(raw_text: str) -> str | None:
    if not raw_text:
        return None

    match = _NUMERIC_FRAGMENT_PATTERN.search(raw_text)
    if match is None:
        return None
    return match.group(0).strip()


def _split_comparator(raw_text: str) -> tuple[str | None, str]:
    match = _COMPARATOR_PATTERN.match(raw_text or "")
    if match is None:
        return None, raw_text
    comparator = match.group("comparator")
    normalized_comparator = {
        "≤": "<=",
        "≥": ">=",
    }.get(comparator, comparator)
    return normalized_comparator, match.group("value").strip()


def _normalize_numeric_text(fragment: str) -> tuple[str, dict[str, Any]]:
    text = str(fragment or "").strip()
    if not text:
        return "", _locale_descriptor(None)

    text = text.replace("\u00a0", "").replace(" ", "")
    decimal_separator, thousands_separator = _infer_separators(text)
    locale = _locale_descriptor(decimal_separator, thousands_separator)
    if thousands_separator:
        text = text.replace(thousands_separator, "")
    if decimal_separator == ",":
        text = text.replace(",", ".")
    text = text.replace("−", "-")
    return text, locale


def _infer_separators(text: str) -> tuple[str | None, str | None]:
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            return ",", "."
        return ".", ","

    if "," in text:
        if re.fullmatch(r"\d{1,3}(,\d{3})+", text):
            return ".", ","
        return ",", None

    if "." in text:
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", text):
            return ",", "."
        return ".", None

    return ".", None


def _locale_descriptor(
    decimal_separator: str | None,
    thousands_separator: str | None = None,
) -> dict[str, Any]:
    if decimal_separator is None:
        return {
            "decimal_separator": None,
            "thousands_separator": None,
        }
    return {
        "decimal_separator": decimal_separator,
        "thousands_separator": thousands_separator,
    }


def _compact_locale_descriptor(locale: Any) -> str | None:
    if not isinstance(locale, dict):
        rendered = str(locale or "").strip()
        return rendered or None

    decimal_separator = str(locale.get("decimal_separator") or "").strip()
    thousands_separator = str(locale.get("thousands_separator") or "").strip()
    normalized = str(locale.get("normalized") or "").strip()

    parts: list[str] = []
    if decimal_separator == ",":
        parts.append("decimal_comma")
    elif decimal_separator == ".":
        parts.append("decimal_dot")
    if thousands_separator == ",":
        parts.append("thousands_comma")
    elif thousands_separator == ".":
        parts.append("thousands_dot")
    if normalized:
        parts.append("normalized")
    return "+".join(parts) or None


def _normalize_identifier(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if not text:
        return None
    return " ".join(text.split())


def _normalize_identifier_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return [identifier for identifier in (_normalize_identifier(item) for item in value) if identifier]
    normalized = _normalize_identifier(value)
    return [normalized] if normalized else []


def _normalize_candidate_trace(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, dict):
        return [{str(key): _json_safe(item) for key, item in value.items()}]
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        return [{"stage": "candidate_trace", "status": "present", "detail": _json_safe(value)}]
    trace: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            trace.append({str(key): _json_safe(item_value) for key, item_value in item.items()})
        else:
            trace.append({"stage": "candidate_trace", "status": "present", "detail": _json_safe(item)})
    return trace


def _json_safe(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value
