"""Deterministic clinician-share PDF generation."""

from __future__ import annotations

from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID

from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas

from app.config import settings
from app.services.privacy import write_private_file

_PDF_FILENAME = "clinician_smoke_report.pdf"
_TITLE = "Clinician Smoke Report"
_AUTHOR = "Elfie Labs Analyzer"
_SUBJECT = "Clinician-share smoke readiness artifact"
_FONT = "Helvetica"
_BOLD_FONT = "Helvetica-Bold"
_HEADER_FONT_SIZE = 16
_SECTION_FONT_SIZE = 11
_BODY_FONT_SIZE = 9
_PAGE_WIDTH, _PAGE_HEIGHT = letter
_MARGIN = 54
_CONTENT_WIDTH = _PAGE_WIDTH - (_MARGIN * 2)
_LINE_LEADING = 12


def clinician_pdf_path(job_id: UUID | str) -> Path:
    return settings.artifact_store_path / "reports" / str(job_id) / _PDF_FILENAME


def clinician_pdf_route(job_id: UUID | str) -> str:
    return f"/api/artifacts/{job_id}/clinician/pdf"


def build_clinician_pdf_bytes(clinician_artifact: Mapping[str, Any]) -> bytes:
    buffer = BytesIO()
    canvas = Canvas(
        buffer,
        pagesize=letter,
        pageCompression=0,
        invariant=1,
    )
    canvas.setTitle(_TITLE)
    canvas.setAuthor(_AUTHOR)
    canvas.setSubject(_SUBJECT)
    canvas.setCreator(_AUTHOR)

    job_id = str(clinician_artifact.get("job_id", "unknown"))
    report_date = str(clinician_artifact.get("report_date", "unknown"))
    support_coverage = str(clinician_artifact.get("support_coverage", "unknown"))
    trust_status = str(clinician_artifact.get("trust_status", "unknown"))
    provenance_link = clinician_artifact.get("provenance_link")
    top_findings = list(clinician_artifact.get("top_findings") or [])
    not_assessed = list(clinician_artifact.get("not_assessed") or [])
    severity_classes = ", ".join(
        str(value) for value in clinician_artifact.get("severity_classes", [])
    )
    nextstep_classes = ", ".join(
        str(value) for value in clinician_artifact.get("nextstep_classes", [])
    )

    y = _PAGE_HEIGHT - _MARGIN
    y = _draw_text(
        canvas, _TITLE, x=_MARGIN, y=y, font_name=_BOLD_FONT, font_size=_HEADER_FONT_SIZE
    )
    y -= 6
    y = _draw_text(
        canvas,
        f"Job ID: {job_id}",
        x=_MARGIN,
        y=y,
        font_name=_FONT,
        font_size=_BODY_FONT_SIZE,
    )
    y = _draw_text(
        canvas,
        f"Report date: {report_date}",
        x=_MARGIN,
        y=y,
        font_name=_FONT,
        font_size=_BODY_FONT_SIZE,
    )

    y -= 4
    y = _draw_section_header(canvas, "Summary", y)
    y = _draw_text(canvas, f"Support coverage: {support_coverage}", x=_MARGIN, y=y)
    y = _draw_text(canvas, f"Trust status: {trust_status}", x=_MARGIN, y=y)
    y = _draw_text(canvas, f"Severity classes: {severity_classes or 'none'}", x=_MARGIN, y=y)
    y = _draw_text(canvas, f"Next-step classes: {nextstep_classes or 'none'}", x=_MARGIN, y=y)

    y -= 4
    y = _draw_section_header(canvas, "Top Findings", y)
    if top_findings:
        for index, finding in enumerate(top_findings, start=1):
            y = _draw_text(
                canvas,
                _format_finding(index, finding),
                x=_MARGIN + 8,
                y=y,
            )
    else:
        y = _draw_text(canvas, "- none", x=_MARGIN + 8, y=y)

    y -= 4
    y = _draw_section_header(canvas, "Not Assessed", y)
    if not_assessed:
        for item in not_assessed:
            y = _draw_text(
                canvas,
                _format_not_assessed(item),
                x=_MARGIN + 8,
                y=y,
            )
    else:
        y = _draw_text(canvas, "- none", x=_MARGIN + 8, y=y)

    y -= 4
    y = _draw_section_header(canvas, "Provenance", y)
    proof_pack_ref = f"/api/jobs/{job_id}/proof-pack"
    y = _draw_text(canvas, f"Proof pack: {proof_pack_ref}", x=_MARGIN, y=y)
    y = _draw_text(
        canvas,
        f"Provenance link: {provenance_link or 'not available'}",
        x=_MARGIN,
        y=y,
    )

    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def write_clinician_pdf(job_id: UUID | str, clinician_artifact: Mapping[str, Any]) -> Path:
    path = clinician_pdf_path(job_id)
    return write_private_file(path, build_clinician_pdf_bytes(clinician_artifact))


def ensure_clinician_pdf(
    job_id: UUID | str,
    clinician_artifact: Mapping[str, Any] | None = None,
) -> Path | None:
    path = clinician_pdf_path(job_id)
    if path.exists():
        return path
    if clinician_artifact is None:
        return None
    return write_clinician_pdf(job_id, clinician_artifact)


def _draw_section_header(canvas: Canvas, title: str, y: float) -> float:
    return _draw_text(
        canvas, title, x=_MARGIN, y=y, font_name=_BOLD_FONT, font_size=_SECTION_FONT_SIZE
    )


def _draw_text(
    canvas: Canvas,
    text: str,
    *,
    x: float,
    y: float,
    font_name: str = _FONT,
    font_size: int = _BODY_FONT_SIZE,
) -> float:
    wrapped_lines = simpleSplit(str(text), font_name, font_size, _CONTENT_WIDTH - (x - _MARGIN))
    for line in wrapped_lines or [""]:
        if y < _MARGIN:
            canvas.showPage()
            canvas.setTitle(_TITLE)
            canvas.setAuthor(_AUTHOR)
            canvas.setSubject(_SUBJECT)
            canvas.setCreator(_AUTHOR)
            y = _PAGE_HEIGHT - _MARGIN
            canvas.setFont(_BOLD_FONT, _HEADER_FONT_SIZE)
            canvas.drawString(_MARGIN, y, _TITLE)
            y -= 24
        canvas.setFont(font_name, font_size)
        canvas.drawString(x, y, line)
        y -= _LINE_LEADING if font_size <= _BODY_FONT_SIZE else max(_LINE_LEADING, font_size + 2)
    return y


def _format_finding(index: int, finding: Mapping[str, Any]) -> str:
    label = (
        finding.get("explanatory_scaffold_id")
        or finding.get("rule_id")
        or finding.get("finding_id")
        or "unknown finding"
    )
    severity = finding.get("severity_class", "unknown")
    nextstep = finding.get("nextstep_class", "unknown")
    threshold = finding.get("threshold_source", "unknown")
    return (
        f"- {index}. {label} | severity {severity} | next step {nextstep} | threshold {threshold}"
    )


def _format_not_assessed(item: Mapping[str, Any]) -> str:
    raw_label = item.get("raw_label", "unknown")
    reason = item.get("reason", "unknown")
    return f"- {raw_label} | reason {reason}"
