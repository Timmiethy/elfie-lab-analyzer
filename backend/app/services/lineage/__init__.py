"""Lineage logger: full provenance tracking (blueprint section 11.3)."""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, UUID, uuid5

_ADAPTER_VERSION_DEFAULT = "family-adapter-v1"
_ROW_ASSEMBLY_VERSION_DEFAULT = "row-assembly-v1"
_ROW_TYPE_RULE_SET_VERSION_DEFAULT = "row-type-rules-v1"
_FORMULA_VERSION_DEFAULT = "formula-v1"


def _coerce_uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _stable_payload(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class LineageLogger:
    def record(self, job_id: str, components: dict) -> dict:
        job_uuid = _coerce_uuid(job_id)
        payload = dict(components)
        lineage_id = uuid5(NAMESPACE_URL, f"lineage:{job_uuid}:{_stable_payload(payload)}")

        return {
            "id": lineage_id,
            "job_id": job_uuid,
            "source_checksum": payload.get("source_checksum", ""),
            "parser_backend": payload.get("parser_backend"),
            "parser_backend_version": payload.get("parser_backend_version"),
            "parser_version": payload.get("parser_version", ""),
            "adapter_version": payload.get(
                "adapter_version",
                payload.get("family_adapter_version", _ADAPTER_VERSION_DEFAULT),
            ),
            "family_adapter_version": payload.get(
                "family_adapter_version",
                payload.get("adapter_version", _ADAPTER_VERSION_DEFAULT),
            ),
            "row_assembly_version": payload.get(
                "row_assembly_version", _ROW_ASSEMBLY_VERSION_DEFAULT
            ),
            "row_type_rule_set_version": payload.get(
                "row_type_rule_set_version", _ROW_TYPE_RULE_SET_VERSION_DEFAULT
            ),
            "formula_version": payload.get(
                "formula_version", _FORMULA_VERSION_DEFAULT
            ),
            "ocr_version": payload.get("ocr_version"),
            "terminology_release": payload.get("terminology_release", ""),
            "mapping_threshold_config": dict(payload.get("mapping_threshold_config", {})),
            "unit_engine_version": payload.get("unit_engine_version", ""),
            "rule_pack_version": payload.get("rule_pack_version", ""),
            "severity_policy_version": payload.get("severity_policy_version", ""),
            "nextstep_policy_version": payload.get("nextstep_policy_version", ""),
            "template_version": payload.get("template_version", ""),
            "model_version": payload.get("model_version"),
            "build_commit": payload.get("build_commit"),
        }
