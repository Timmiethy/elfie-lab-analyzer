"""Artifact renderer: patient and clinician artifact generation."""


class ArtifactRenderer:
    """Render patient artifact (Screen C) and clinician-share artifact (Screen F).

    Both derived from the same structured findings packet.
    """

    def render_patient(self, findings: list[dict], context: dict) -> dict:
        raise NotImplementedError

    def render_clinician(self, findings: list[dict], context: dict) -> dict:
        raise NotImplementedError
