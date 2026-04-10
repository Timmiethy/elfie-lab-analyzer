"""Deterministic severity policy engine (blueprint section 3.9).

Classes: S0, S1, S2, S3, S4, SX.
Severity is NEVER inferred by an LLM. Assigned from closed policy tables only.
"""


class SeverityPolicyEngine:
    def assign(self, findings: list[dict], patient_context: dict) -> list[dict]:
        raise NotImplementedError
