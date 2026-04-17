from __future__ import annotations

import logging
from typing import Literal

from app.services.vlm_gateway import process_image_with_qwen

logger = logging.getLogger(__name__)


class MineruAdapter:
    """
    Adapter for opendatalab/MinerU to handle document parsing execution.
    Initially, this wraps the core execution backend of MinerU for
    text-based, OCR, or auto routing modes.
    """

    def __init__(self, mode: Literal["auto", "txt", "ocr"] = "auto"):
        self.mode = mode

    async def execute(self, pdf_bytes: bytes) -> dict:
        """
        Executes the MinerU pipeline for a given document.
        Args:
            pdf_bytes: Raw bytes of the PDF.
        Returns:
            A simplified parsed structure representing MinerU output.
        """
        logger.info(f"miner_u_executing mode={self.mode} source_bytes={len(pdf_bytes)}")
        # MOCK/STUB: In a real environment, we'd invoke the `magic_pdf` API
        # which splits pages into regions. Here, we forward the raw bytes
        # directly to Qwen2.5-VL to simulate a region-level recognizer call.

        try:
            qwen_rows = await process_image_with_qwen(pdf_bytes)
            return {
                "mode": self.mode,
                "status": "success",
                "content": {
                    "blocks": [
                        {
                            "type": "table",
                            "html": f"<tr><td>{r.analyte_name}</td><td>{r.value}</td><td>{r.unit}</td><td>{r.reference_range_raw}</td></tr>",
                            "raw_qwen": r,
                        }
                        for r in qwen_rows
                    ]
                },
            }
        except Exception as e:
            logger.error(f"MinerU execute failed: {e}")
            return {
                "mode": self.mode,
                "status": "error",
                "error_message": str(e),
                "content": {"blocks": []},
            }
