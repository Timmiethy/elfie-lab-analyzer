from __future__ import annotations

from io import BytesIO
from uuid import uuid4


def build_text_pdf(lines: list[str], *, pages: int = 1) -> bytes:
    objects: list[bytes] = []
    page_object_numbers: list[int] = []
    next_object_number = 3

    for _page_index in range(pages):
        content_lines = ["BT", "/F1 12 Tf", "72 720 Td"]
        for index, line in enumerate(lines):
            escaped_line = (
                line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            )
            if index:
                content_lines.append("0 -18 Td")
            content_lines.append(f"({escaped_line}) Tj")
        content_lines.append("ET")
        stream = "\n".join(content_lines).encode("utf-8")

        page_object_number = next_object_number
        content_object_number = next_object_number + 1
        next_object_number += 2
        page_object_numbers.append(page_object_number)

        objects.append(
            f"{page_object_number} 0 obj\n"
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {next_object_number} 0 R >> >> "
            f"/Contents {content_object_number} 0 R >>\n"
            "endobj\n".encode("utf-8")
        )
        objects.append(
            f"{content_object_number} 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode(
                "utf-8"
            )
            + stream
            + b"\nendstream\nendobj\n"
        )

    font_object_number = next_object_number
    kids = " ".join(f"{number} 0 R" for number in page_object_numbers)

    header_objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        f"2 0 obj\n<< /Type /Pages /Count {pages} /Kids [{kids}] >>\nendobj\n".encode(
            "utf-8"
        ),
    ]

    objects = header_objects + objects
    objects.append(
        f"{font_object_number} 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n".encode(
            "utf-8"
        )
    )

    buffer = BytesIO()
    buffer.write(f"%PDF-1.4\n%fixture:{uuid4()}\n".encode("utf-8"))
    offsets = [0]
    for obj in objects:
        offsets.append(buffer.tell())
        buffer.write(obj)

    xref_offset = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode("utf-8"))
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.write(f"{offset:010d} 00000 n \n".encode("utf-8"))
    buffer.write(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            "startxref\n"
            f"{xref_offset}\n"
            "%%EOF\n"
        ).encode("utf-8")
    )
    return buffer.getvalue()
