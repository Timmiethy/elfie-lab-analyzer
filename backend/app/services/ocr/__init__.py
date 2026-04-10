"""Image beta lane: docTR + Surya OCR adapter."""


class OcrAdapter:
    """OCR pipeline for image beta lane.

    Uses docTR for text recognition and Surya for layout assistance.
    Preview-only unless downstream gates match trusted lane.
    """

    async def extract(self, image_bytes: bytes) -> list[dict]:
        raise NotImplementedError
