"""Deterministic rule engine (blueprint section 3.8)."""


class RuleEngine:
    """Fire deterministic rules against observations.

    Priority packs: glycemia/diabetes, lipids/cardiovascular, kidney function.
    Every rule yields: finding_id, threshold_source, severity candidate, nextstep candidate.
    """

    def evaluate(self, observations: list[dict], patient_context: dict) -> list[dict]:
        raise NotImplementedError
