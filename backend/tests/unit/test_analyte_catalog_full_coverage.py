from __future__ import annotations

import json

from app.services.analyte_resolver import AnalyteResolver
from app.services.data_paths import resolve_data_file


def _load_alias_labels() -> list[str]:
    alias_path = resolve_data_file(
        __file__,
        "alias_tables",
        "launch_scope_analyte_aliases.json",
    )
    payload = json.loads(alias_path.read_text(encoding="utf-8"))

    labels: list[str] = []
    for analyte in payload.get("analytes", []):
        if not isinstance(analyte, dict):
            continue
        labels.extend(
            [
                str(analyte.get("canonical_label") or ""),
                *[str(alias) for alias in analyte.get("aliases", [])],
                *[str(code) for code in analyte.get("codes", [])],
            ]
        )
    return [label.strip() for label in labels if label.strip()]


def _load_metric_labels() -> list[str]:
    metric_path = resolve_data_file(
        __file__,
        "metric_definitions",
        "core_metrics.json",
    )
    payload = json.loads(metric_path.read_text(encoding="utf-8"))

    labels: list[str] = []
    for metric in payload:
        if not isinstance(metric, dict):
            continue
        labels.extend(
            [
                str(metric.get("canonical_name") or ""),
                *[str(alias) for alias in metric.get("aliases", [])],
                str(metric.get("metric_id") or ""),
            ]
        )
    return [label.strip() for label in labels if label.strip()]


def _assert_supported(labels: list[str]) -> None:
    resolver = AnalyteResolver()

    unresolved: list[tuple[str, str | None, list[str]]] = []
    for label in sorted(set(labels)):
        resolved = resolver.resolve(label)
        accepted = resolved.get("accepted_candidate") or {}
        if resolved.get("support_state") != "supported" or not accepted.get("candidate_code"):
            unresolved.append(
                (
                    label,
                    resolved.get("support_state"),
                    list(resolved.get("abstention_reasons") or []),
                )
            )

    assert unresolved == []


def test_alias_catalog_labels_are_resolvable() -> None:
    _assert_supported(_load_alias_labels())


def test_metric_catalog_labels_are_resolvable() -> None:
    _assert_supported(_load_metric_labels())
