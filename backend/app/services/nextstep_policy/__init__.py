"""Deterministic next-step policy engine (blueprint section 3.10).

Classes: A0, A1, A2, A3, A4, AX.
Next-step is closed-table, not generated.
"""


class NextStepPolicyEngine:
    def assign(self, findings: list[dict], patient_context: dict) -> list[dict]:
        raise NotImplementedError
