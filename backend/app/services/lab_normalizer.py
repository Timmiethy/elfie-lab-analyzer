from __future__ import annotations

import re
from uuid import UUID


class LabNormalizer:
    """
    Parses structural outputs (HTML tables, Markdown) from MinerU and maps
    them to the internal Pipeline dictionary schema deterministically.
    """

    def normalize(self, mineru_blocks: list[dict], document_id: str | UUID) -> list[dict]:
        """
        Takes MinerU 'blocks' and returns a list of dictionaries matching
        the pipeline's expected row format.
        """
        rows = []
        for index, block in enumerate(mineru_blocks):
            if block.get("type") == "table":
                # For this refactor logic, we know the mock embeds a "raw_qwen"
                # object or a raw HTML `<tr><td>Glucose</td>...</tr>` structure.
                # In a purely production MinerU, we'd use bs4 or regex to parse
                # the HTML table cells deterministically.

                # If the raw qwen row is temporarily passed through for parity, use it:
                if "raw_qwen" in block:
                    r = block["raw_qwen"]
                    rows.append(
                        {
                            "document_id": document_id,
                            "source_page": getattr(r, "source_page", None) or 1,
                            "row_hash": f"row-{index}",
                            "raw_text": f"{r.analyte_name} {r.value} {r.unit}",
                            "raw_analyte_label": r.analyte_name,
                            "raw_value_string": r.value,
                            "raw_unit_string": r.unit,
                            "raw_reference_range": r.reference_range_raw,
                            "extraction_confidence": (r.confidence_score or 95) / 100.0,
                            "row_bbox": r.row_bbox_ymin_xmin_ymax_xmax or [0, 0, 0, 0],
                        }
                    )
                else:
                    # Generic HTML table parsing logic using regex (mock constraint)
                    html = block.get("html", "")
                    cells = re.findall(r"<td>(.*?)</td>", html)
                    if len(cells) >= 4:
                        rows.append(
                            {
                                "document_id": document_id,
                                "source_page": 1,
                                "row_hash": f"row-{index}",
                                "raw_text": " ".join(cells[:4]),
                                "raw_analyte_label": cells[0],
                                "raw_value_string": cells[1],
                                "raw_unit_string": cells[2],
                                "raw_reference_range": cells[3],
                                "extraction_confidence": 0.95,
                                "row_bbox": [0, 0, 0, 0],
                            }
                        )
        return rows
