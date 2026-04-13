from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings


_DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[4] / "data" / "family_configs" / "document_family_registry_v1.json"


@dataclass(frozen=True)
class FamilyConfigRegistry:
    contract_version: str
    version: str
    route_hints: dict[str, list[str]]
    page_kind_hints: dict[str, list[str]]
    block_role_hints: dict[str, list[str]]
    artifact_policy: dict[str, Any]

    @classmethod
    def load(cls, file_path: Path | None = None) -> "FamilyConfigRegistry":
        path = file_path or _resolve_registry_path()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            contract_version=str(payload.get("contract_version") or "family-config-registry-v1"),
            version=str(payload.get("version") or "unknown"),
            route_hints=_normalize_hint_map(payload.get("route_hints")),
            page_kind_hints=_normalize_hint_map(payload.get("page_kind_hints")),
            block_role_hints=_normalize_hint_map(payload.get("block_role_hints")),
            artifact_policy=dict(payload.get("artifact_policy") or {}),
        )

    def route_keywords(self, key: str) -> tuple[str, ...]:
        return tuple(self.route_hints.get(key, []))

    def page_keywords(self, key: str) -> tuple[str, ...]:
        return tuple(self.page_kind_hints.get(key, []))

    def block_keywords(self, key: str) -> tuple[str, ...]:
        return tuple(self.block_role_hints.get(key, []))

    def visible_unsupported_categories(self) -> dict[str, str]:
        category_map = self.artifact_policy.get("visible_unsupported_categories")
        if isinstance(category_map, dict):
            return {
                str(key): str(value)
                for key, value in category_map.items()
            }
        return {}

    def hidden_markers(self) -> tuple[str, ...]:
        markers = self.artifact_policy.get("hidden_markers")
        if isinstance(markers, list):
            return tuple(str(marker).lower() for marker in markers)
        return ()


@lru_cache(maxsize=1)
def get_family_config_registry() -> FamilyConfigRegistry:
    return FamilyConfigRegistry.load()


def _resolve_registry_path() -> Path:
    configured = getattr(settings, "family_config_registry_path", None)
    if configured:
        path = Path(configured)
        if path.exists():
            return path
    return _DEFAULT_REGISTRY_PATH


def _normalize_hint_map(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for key, raw_items in value.items():
        if isinstance(raw_items, list):
            normalized[str(key)] = [
                str(item).strip().lower()
                for item in raw_items
                if str(item).strip()
            ]
        else:
            normalized[str(key)] = []
    return normalized
