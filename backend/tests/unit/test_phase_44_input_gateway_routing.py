from __future__ import annotations

from io import BytesIO
from uuid import uuid4

from app.services.input_gateway import InputGateway


def _build_text_pdf(lines: list[str]) -> bytes:
    objects: list[bytes] = []
    next_object_number = 3

    content_lines = ["BT", "/F1 12 Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        escaped_line = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if index:
            content_lines.append("0 -18 Td")
        content_lines.append(f"({escaped_line}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode()

    page_object_number = next_object_number
    content_object_number = next_object_number + 1
    next_object_number += 2

    objects.append(
        f"{page_object_number} 0 obj\n"
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        f"/Resources << /Font << /F1 {next_object_number} 0 R >> >> "
        f"/Contents {content_object_number} 0 R >>\n"
        "endobj\n".encode()
    )
    objects.append(
        f"{content_object_number} 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode()
        + stream
        + b"\nendstream\nendobj\n"
    )

    font_object_number = next_object_number
    header_objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        (
            f"2 0 obj\n<< /Type /Pages /Count 1 /Kids [{page_object_number} 0 R] >>\n"
            "endobj\n"
        ).encode(),
    ]

    objects = header_objects + objects
    objects.append(
        (
            f"{font_object_number} 0 obj\n"
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"
            "endobj\n"
        ).encode()
    )

    buffer = BytesIO()
    buffer.write(f"%PDF-1.4\n%fixture:{uuid4()}\n".encode())
    offsets = [0]
    for obj in objects:
        offsets.append(buffer.tell())
        buffer.write(obj)

    xref_offset = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode())
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.write(f"{offset:010d} 00000 n \n".encode())
    buffer.write(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            "startxref\n"
            f"{xref_offset}\n"
            "%%EOF\n"
        ).encode()
    )
    return buffer.getvalue()


async def test_phase_44_input_gateway_emits_route_metadata_for_lab_pdf() -> None:
    gateway = InputGateway()
    payload = _build_text_pdf(["Glucose 180 mg/dL", "HbA1c 6.8 %"])

    result = await gateway.preflight(
        file_bytes=payload,
        filename="report.pdf",
        mime_type="application/pdf",
    )

    assert result["lane_type"] == "trusted_pdf"
    assert result["route_lane_type"] in {"trusted_pdf_lab", "composite_packet"}
    assert result["route_runtime_lane_type"] == "trusted_pdf"


async def test_phase_44_input_gateway_routes_non_lab_pdf_to_unsupported_runtime() -> None:
    gateway = InputGateway()
    payload = _build_text_pdf([
        "Ultrasound report",
        "Impression: normal liver echotexture",
        "Recommendation: follow up in 6 months",
    ])

    result = await gateway.preflight(
        file_bytes=payload,
        filename="ultrasound.pdf",
        mime_type="application/pdf",
    )

    assert result["route_runtime_lane_type"] == "unsupported"
    assert result["promotion_status"] in {"ready_unsupported", "ready"}
