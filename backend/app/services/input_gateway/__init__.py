"""Input gateway: lane classification, file sanitization, and support scoring."""


class InputGateway:
    """Classify input into trusted PDF, image beta, or structured lane.

    Responsibilities (blueprint sections 3.2, 3.3):
    - File type whitelist enforcement
    - MIME/extension agreement check
    - Size and page count limits
    - Password-protected PDF rejection
    - Checksum computation
    - Duplicate detection
    - Lane assignment
    """

    async def classify(self, file_bytes: bytes, filename: str, mime_type: str) -> dict:
        raise NotImplementedError
