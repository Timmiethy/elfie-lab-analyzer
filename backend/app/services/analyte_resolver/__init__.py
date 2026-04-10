"""Analyte resolver: auditable hybrid mapping (blueprint section 3.7)."""


class AnalyteResolver:
    """Map raw analyte labels to terminology codes.

    Modes: deterministic lexical rules, optional empirical challenger.
    Never auto-accept below threshold. Every abstention reason stored.
    """

    def resolve(self, raw_label: str, context: dict) -> dict:
        raise NotImplementedError
