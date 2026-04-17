"""Lineage bundle schema (blueprint section 0.2.6)."""

from uuid import UUID

from pydantic import BaseModel

CONTRACT_VERSION = "lineage-contract-v1"


class LineageBundleSchema(BaseModel):
    contract_version: str = CONTRACT_VERSION
    id: UUID
    job_id: UUID
    source_checksum: str
    parser_version: str
    ocr_version: str | None = None
    terminology_release: str
    mapping_threshold_config: dict
    unit_engine_version: str
    rule_pack_version: str
    severity_policy_version: str
    nextstep_policy_version: str
    template_version: str
    model_version: str | None = None
    build_commit: str | None = None
