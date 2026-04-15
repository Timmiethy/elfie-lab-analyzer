"""Image Beta Substrate using Qwen-VL for 2D Spatial Pipeline."""

from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from app.services.document_system.contracts import (
    PageParseArtifactV4,
    PageParseBlockV4,
    BlockRoleV1,
    PageKindV2,
    SourceSpanV1,
)

logger = logging.getLogger(__name__)

class ImageBetaSubstrate:
    """Substrate for Qwen-VL providing spatial bounding boxes for 2D clustering."""
    
    def __init__(self, api_key: str | None = None, model: str = "qwen-vl-max"):
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.base_url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.model = model

    def _encode_image(self, image_path: Path) -> str:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        ext = image_path.suffix.lower()
        mime = "image/jpeg" if ext in {".jpg", ".jpeg"} else "image/png"
        return f"data:{mime};base64,{b64}"

    def extract_page_blocks(self, image_path: Path, page_index: int = 1) -> PageParseArtifactV4:
        """Calls Qwen-VL to get bounding boxes and parses into PageParseBlockV4."""
        if not self.api_key:
            logger.warning("No Qwen-VL API key. Returning empty artifact.")
            return PageParseArtifactV4(page_number=page_index, backend_id="qwen-vl-spatial")
            
        try:
            from openai import OpenAI
        except ImportError:
            logger.warning("openai package missing. Returning empty artifact.")
            return PageParseArtifactV4(page_number=page_index, backend_id="qwen-vl-spatial")

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        data_url = self._encode_image(image_path)
        system_prompt = (
            "Analyze this document image and extract all text along with their bounding boxes. "
            "Return the result strictly as a JSON array of objects. "
            "Each object must have 'text' (the string content) and 'box' (an array of 4 integers: [x0, y0, x1, y1]). "
            "Do not include any other markdown or text outside the JSON array."
        )

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_url}},
                            {"type": "text", "text": "Extract text bounding boxes as JSON."}
                        ]
                    }
                ],
                temperature=0.0,
            )
            content = response.choices[0].message.content or "[]"
            
            # Strip markdown JSON fences if present
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            
            try:
                data = json.loads(content.strip())
            except json.JSONDecodeError:
                logger.error(f"Failed to parse Qwen-VL JSON output: {content}")
                data = []
            
            blocks = []
            raw_text_parts = []
            
            for i, item in enumerate(data):
                if not isinstance(item, dict) or "text" not in item or "box" not in item:
                    continue
                
                text = str(item["text"]).strip()
                if not text:
                    continue
                    
                box = item["box"]
                if not isinstance(box, list) or len(box) != 4:
                    continue
                
                try:
                    x0, y0, x1, y1 = [float(v) for v in box]
                except ValueError:
                    continue
                    
                span = SourceSpanV1(x0=x0, y0=y0, x1=x1, y1=y1)
                
                blocks.append(PageParseBlockV4(
                    block_id=f"qwen-{i}-{uuid.uuid4().hex[:8]}",
                    block_role=BlockRoleV1.UNKNOWN_BLOCK,
                    raw_text=text,
                    lines=[text],
                    bbox=span,
                    reading_order=i,
                    source_spans=[span]
                ))
                raw_text_parts.append(text)
            
            raw_text = "\n".join(raw_text_parts)
            text_extractability = 1.0 if len(raw_text) >= 100 else (0.5 if len(raw_text) > 0 else 0.0)
            
            return PageParseArtifactV4(
                page_id=f"{image_path}:page-{page_index}",
                page_number=page_index,
                backend_id="qwen-vl-spatial",
                lane_type="image_beta",
                text_extractability=text_extractability,
                blocks=blocks,
                raw_text=raw_text
            )

        except Exception as e:
            logger.error(f"Qwen-VL spatial extraction failed: {e}")
            return PageParseArtifactV4(page_number=page_index, backend_id="qwen-vl-spatial")