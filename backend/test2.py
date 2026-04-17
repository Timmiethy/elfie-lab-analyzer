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


byts = build_pdf(["Glucose 180 mg/dL", "UnknownTest 100 U/L"])
import pdf_inspector

print(pdf_inspector.process_pdf_bytes(byts))
