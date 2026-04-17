import asyncio

from app.services.vlm_gateway import VLMRow
from app.workers.pipeline import PipelineOrchestrator


def mock_qwen(file_bytes):
    return [
        VLMRow(
            analyte_name="Glucose",
            value="180",
            unit="mg/dL",
            reference_range_raw="70-99",
            confidence_score=99,
        ),
        VLMRow(
            analyte_name="HbA1c",
            value="6.8",
            unit="%",
            reference_range_raw="<5.7",
            confidence_score=98,
        ),
    ]


import app.workers.pipeline as pm


async def async_mock(*a, **kw):
    return mock_qwen(*a, **kw)


pm.process_image_with_qwen = async_mock

import io

from reportlab.pdfgen import canvas


def build_pdf(lines):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer)
    y = 800
    for line in lines:
        c.drawString(100, y, line)
        y -= 20
    c.save()
    return buffer.getvalue()


async def main():
    byts = build_pdf(["Glucose 180 mg/dL", "HbA1c 6.8 %"])
    p = PipelineOrchestrator()
    res = await p.run(
        "test-job",
        file_bytes=byts,
        db_session=None,
        lane_type="trusted_pdf",
        source_checksum="fake",
    )
    import pprint

    pprint.pprint(res["patient_artifact"])


asyncio.run(main())
