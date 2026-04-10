"""Panel reconstructor: group observations into clinical panels."""

from __future__ import annotations

from functools import lru_cache

from app.services.analyte_resolver import _load_launch_scope_metadata


class PanelReconstructor:
    """Group related observations into panels (e.g., lipid panel, renal panel)."""

    def reconstruct(self, observations: list[dict]) -> list[dict]:
        panel_groups: dict[str, list[dict]] = {}

        for observation in observations:
            panel_key = self._panel_key(observation)
            panel_groups.setdefault(panel_key, []).append(observation)

        reconstructed = []
        for panel_key, grouped_observations in panel_groups.items():
            reconstructed.append(
                {
                    "panel_key": panel_key,
                    "panel_display": self._panel_display(panel_key),
                    "observation_ids": [observation.get("id") for observation in grouped_observations if observation.get("id") is not None],
                    "observation_count": len(grouped_observations),
                    "support_state": self._panel_support_state(grouped_observations),
                    "observations": grouped_observations,
                }
            )

        return reconstructed

    @staticmethod
    def _panel_key(observation: dict) -> str:
        analyte_code = str(observation.get("accepted_analyte_code") or "").strip()
        analyte_label = str(observation.get("raw_analyte_label") or "").strip().lower()
        specimen_context = str(observation.get("specimen_context") or "").strip().lower()

        metadata = _load_panel_metadata()
        if analyte_code in metadata["codes_by_panel"].get("glycemia", set()) or analyte_label in metadata["aliases_by_panel"].get("glycemia", set()):
            return "glycemia"
        if analyte_code in metadata["codes_by_panel"].get("lipid", set()) or analyte_label in metadata["aliases_by_panel"].get("lipid", set()):
            return "lipid"
        if analyte_code in metadata["codes_by_panel"].get("kidney", set()) or analyte_label in metadata["aliases_by_panel"].get("kidney", set()):
            return "kidney"
        return "unclassified"

    @staticmethod
    def _panel_display(panel_key: str) -> str:
        return {
            "glycemia": "Glycemia Panel",
            "lipid": "Lipid Panel",
            "kidney": "Kidney Function Panel",
            "unclassified": "Unclassified Panel",
        }.get(panel_key, "Unclassified Panel")

    @staticmethod
    def _panel_support_state(grouped_observations: list[dict]) -> str:
        support_states = {str(observation.get("support_state") or "").lower() for observation in grouped_observations}
        if support_states == {"supported"}:
            return "supported"
        if "supported" in support_states:
            return "partial"
        return "unsupported"


@lru_cache(maxsize=1)
def _load_panel_metadata() -> dict:
    metadata = _load_launch_scope_metadata()
    panel_aliases: dict[str, set[str]] = {"glycemia": set(), "lipid": set(), "kidney": set()}
    panel_codes: dict[str, set[str]] = {"glycemia": set(), "lipid": set(), "kidney": set()}

    for analyte in metadata.get("analytes", []):
        panel_key = analyte.get("panel_key") or ""
        if panel_key not in panel_aliases:
            continue
        panel_aliases[panel_key].add(analyte["canonical_label"])
        panel_aliases[panel_key].update(analyte.get("aliases", set()))
        if analyte.get("candidate_code"):
            panel_codes[panel_key].add(analyte["candidate_code"])

    return {
        "aliases_by_panel": panel_aliases,
        "codes_by_panel": panel_codes,
    }
