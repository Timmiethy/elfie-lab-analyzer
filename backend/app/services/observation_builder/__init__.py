"""Provisional observation builder."""


class ObservationBuilder:
    """Build provisional observations from validated extracted rows.

    Creates canonical observation records with support state tracking.
    """

    def build(self, validated_rows: list[dict]) -> list[dict]:
        raise NotImplementedError
