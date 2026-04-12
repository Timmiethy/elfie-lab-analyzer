from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.models.tables import ExtractedRow, Observation
from app.schemas.artifact import PatientArtifactSchema, UnsupportedReason
from app.workers.pipeline import _JOB_RUNS
from tests.integration.helpers import reset_integration_db

pytestmark = pytest.mark.asyncio

ROOT = Path(__file__).resolve().parents[3]
CORPUS_ROOT = ROOT / "pdfs_by_difficulty"


def _build_text_pdf(lines: list[str], *, pages: int = 1) -> bytes:
    objects: list[bytes] = []
    page_object_numbers: list[int] = []
    next_object_number = 3

    for _page_index in range(pages):
        content_lines = ["BT", "/F1 12 Tf", "72 720 Td"]
        for index, line in enumerate(lines):
            escaped_line = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
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
            f"{content_object_number} 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("utf-8")
            + stream
            + b"\nendstream\nendobj\n"
        )

    font_object_number = next_object_number
    kids = " ".join(f"{number} 0 R" for number in page_object_numbers)

    header_objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        f"2 0 obj\n<< /Type /Pages /Count {pages} /Kids [{kids}] >>\nendobj\n".encode("utf-8"),
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


def _load_corpus_pdf(relative_path: str) -> bytes:
    return (CORPUS_ROOT / relative_path).read_bytes()


async def _upload_corpus_pdf(api_client: AsyncClient, relative_path: str) -> dict:
    response = await api_client.post(
        "/api/upload",
        files={
            "file": (
                Path(relative_path).name,
                _load_corpus_pdf(relative_path),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 200, response.text
    return response.json()


async def _patient_artifact(api_client: AsyncClient, job_id: str) -> PatientArtifactSchema:
    response = await api_client.get(f"/api/artifacts/{job_id}/patient")
    assert response.status_code == 200, response.text
    return PatientArtifactSchema.model_validate(response.json())


async def _observations_for_job(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: str,
) -> list[Observation]:
    async with session_factory() as session:
        result = await session.execute(select(Observation).where(Observation.job_id == job_id))
        return list(result.scalars())


async def _extracted_rows_for_job(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: str,
) -> list[ExtractedRow]:
    async with session_factory() as session:
        result = await session.execute(select(ExtractedRow).where(ExtractedRow.job_id == job_id))
        return list(result.scalars())


@pytest_asyncio.fixture(autouse=True)
async def runtime_isolation(
    tmp_path: Path,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await reset_integration_db(db_session_factory)

    _JOB_RUNS.clear()
    original_artifact_store_path = settings.artifact_store_path
    original_image_beta_enabled = settings.image_beta_enabled
    settings.artifact_store_path = tmp_path / "artifacts"
    settings.image_beta_enabled = False
    try:
        yield
    finally:
        _JOB_RUNS.clear()
        settings.artifact_store_path = original_artifact_store_path
        settings.image_beta_enabled = original_image_beta_enabled


async def test_admin_rows_never_enter_observation_pool(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    upload_payload = await _upload_corpus_pdf(api_client, "easy/seed_innoquest_dbticbm.pdf")
    job_id = upload_payload["job_id"]

    patient = await _patient_artifact(api_client, job_id)
    observations = await _observations_for_job(db_session_factory, job_id)

    admin_labels = {"DOB", "Ref", "Collected", "Report Printed"}
    observed_labels = {obs.raw_analyte_label for obs in observations}
    not_assessed_labels = {item.raw_label for item in patient.not_assessed}

    assert admin_labels.isdisjoint(observed_labels)
    assert admin_labels.isdisjoint(not_assessed_labels)


async def test_threshold_table_rows_never_surface_as_unassessed_labs(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    upload_payload = await _upload_corpus_pdf(api_client, "easy/seed_innoquest_dbticbm.pdf")
    job_id = upload_payload["job_id"]

    patient = await _patient_artifact(api_client, job_id)
    observations = await _observations_for_job(db_session_factory, job_id)

    threshold_markers = ("Normal", "IFG (Prediabetes)", "KDIGO", "Tests Requested")
    observed_labels = [obs.raw_analyte_label for obs in observations]
    not_assessed_labels = [item.raw_label for item in patient.not_assessed]

    assert not any(
        marker.lower() in label.lower()
        for marker in threshold_markers
        for label in observed_labels
    )
    assert not any(
        marker.lower() in label.lower()
        for marker in threshold_markers
        for label in not_assessed_labels
    )


async def test_innoquest_bilingual_row_merge_sodium(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    upload_payload = await _upload_corpus_pdf(api_client, "easy/seed_innoquest_dbticbm.pdf")
    job_id = upload_payload["job_id"]

    extracted_rows = await _extracted_rows_for_job(db_session_factory, job_id)
    observations = await _observations_for_job(db_session_factory, job_id)

    sodium_rows = [
        row for row in extracted_rows if "Sodium" in row.raw_text or "钠" in row.raw_text
    ]
    supported_sodium = [obs for obs in observations if obs.accepted_analyte_display == "Sodium"]

    assert len(sodium_rows) == 1
    assert "Sodium" in sodium_rows[0].raw_text
    assert "钠" in sodium_rows[0].raw_text
    assert len(supported_sodium) == 1
    assert supported_sodium[0].support_state == "supported"


async def test_innoquest_hba1c_dual_unit_result(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    upload_payload = await _upload_corpus_pdf(api_client, "medium/seed_innoquest_dbticrp.pdf")
    job_id = upload_payload["job_id"]

    extracted_rows = await _extracted_rows_for_job(db_session_factory, job_id)
    observations = await _observations_for_job(db_session_factory, job_id)

    hba1c_rows = [row for row in extracted_rows if "HbA1c" in row.raw_text]
    supported_hba1c = [obs for obs in observations if obs.accepted_analyte_display == "HbA1c"]

    assert len(hba1c_rows) == 1
    assert "%" in hba1c_rows[0].raw_text
    assert "mmol/mol" in hba1c_rows[0].raw_text
    assert len(supported_hba1c) == 1
    assert supported_hba1c[0].support_state == "supported"


async def test_innoquest_acr_comparator_first_value(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    upload_payload = await _upload_corpus_pdf(api_client, "easy/seed_innoquest_dbticbm.pdf")
    job_id = upload_payload["job_id"]

    extracted_rows = await _extracted_rows_for_job(db_session_factory, job_id)
    observations = await _observations_for_job(db_session_factory, job_id)

    acr_rows = [row for row in extracted_rows if "ACR" in row.raw_text or "mg Alb/mmol" in row.raw_text]
    acr_observation = next((obs for obs in observations if obs.accepted_analyte_display == "ACR"), None)

    assert len(acr_rows) == 1
    assert "<" in acr_rows[0].raw_text
    assert "mg Alb/mmol" in acr_rows[0].raw_text
    assert acr_observation is not None
    assert acr_observation.raw_value_string is not None
    assert acr_observation.raw_value_string.startswith("<")


async def test_egfr_row_kept_and_guideline_note_rejected(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    upload_payload = await _upload_corpus_pdf(api_client, "easy/seed_innoquest_dbticbm.pdf")
    job_id = upload_payload["job_id"]

    patient = await _patient_artifact(api_client, job_id)
    observations = await _observations_for_job(db_session_factory, job_id)

    assert any(obs.accepted_analyte_display == "eGFR" for obs in observations)
    assert not any("KDIGO" in item.raw_label or "guideline" in item.raw_label.lower() for item in patient.not_assessed)


async def test_patient_artifact_never_shows_DOB_as_unassessed_lab(
    api_client: AsyncClient,
) -> None:
    upload_payload = await _upload_corpus_pdf(api_client, "easy/seed_innoquest_dbticbm.pdf")
    job_id = upload_payload["job_id"]

    patient = await _patient_artifact(api_client, job_id)

    assert all(item.raw_label not in {"DOB", "Ref"} for item in patient.not_assessed)


async def test_generic_insufficient_support_forbidden(
    api_client: AsyncClient,
) -> None:
    upload_payload = await _upload_corpus_pdf(api_client, "easy/seed_innoquest_dbticbm.pdf")
    job_id = upload_payload["job_id"]

    patient = await _patient_artifact(api_client, job_id)

    allowed_reasons = {reason.value for reason in UnsupportedReason}
    for item in patient.not_assessed:
        assert item.reason in allowed_reasons, (
            f"not_assessed item {item.raw_label!r} uses forbidden reason {item.reason!r}; "
            "v11 requires typed failure codes, not catch-all 'insufficient_support'"
        )
        assert item.reason != "insufficient_support", (
            f"not_assessed item {item.raw_label!r} still uses catch-all 'insufficient_support'"
        )


async def test_locale_decimal_comma_parser(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    pdf_bytes = _build_text_pdf(["Glucose 5,6 mg/dL"])
    response = await api_client.post(
        "/api/upload",
        files={"file": ("locale-comma.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]

    observations = await _observations_for_job(db_session_factory, job_id)
    glucose = next(
        (
            obs
            for obs in observations
            if obs.raw_analyte_label == "Glucose" and obs.accepted_analyte_display is not None
        ),
        None,
    )

    assert glucose is not None
    assert glucose.raw_value_string == "5,6"
    assert glucose.parsed_numeric_value == 5.6


async def test_derived_observation_requires_source_links(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    upload_payload = await _upload_corpus_pdf(api_client, "easy/seed_innoquest_dbticbm.pdf")
    job_id = upload_payload["job_id"]

    observations = await _observations_for_job(db_session_factory, job_id)
    derived = next((obs for obs in observations if obs.accepted_analyte_display == "eGFR"), None)

    assert derived is not None
    assert hasattr(derived, "source_observation_ids"), "v11 derived observations must expose source_observation_ids"


async def test_labcorp_cd4_cd8_sample_reaches_fully_supported_patient_artifact(
    api_client: AsyncClient,
) -> None:
    upload_payload = await _upload_corpus_pdf(api_client, "easy/seed_labcorp_cd4_cd8_sample.pdf")
    job_id = upload_payload["job_id"]

    patient = await _patient_artifact(api_client, job_id)

    assert patient.support_banner.value == "fully_supported"
    assert not any(
        marker in item.raw_label.lower()
        for item in patient.not_assessed
        for marker in ("all rights reserved", "date entered", "absolute cd")
    )


async def test_quest_diabetes_panel_excludes_vitals_and_note_hybrids(
    api_client: AsyncClient,
) -> None:
    upload_payload = await _upload_corpus_pdf(api_client, "easy/seed_quest_diabetes_risk_panel_sample.pdf")
    job_id = upload_payload["job_id"]

    patient = await _patient_artifact(api_client, job_id)

    assert patient.support_banner.value == "fully_supported"
    assert not any(
        marker in item.raw_label.lower()
        for item in patient.not_assessed
        for marker in ("height feet", "height inches", "calculated bmi", "note 4", "diabetes and")
    )


async def test_labtestingapi_value_bearing_rows_stop_leaking_once_supported(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    upload_payload = await _upload_corpus_pdf(api_client, "easy/seed_labtestingapi_sample_report.pdf")
    job_id = upload_payload["job_id"]

    patient = await _patient_artifact(api_client, job_id)
    observations = await _observations_for_job(db_session_factory, job_id)

    recovered_labels = {
        "ABSOLUTE NEUTROPHILS",
        "ABSOLUTE EOSINOPHILS",
        "ABSOLUTE BASOPHILS",
        "BASOPHILS P",
        "MAGNESIUM RBMC",
        "LYMPHOCYTES",
        "SED RATE BY MODIFIED WESTERGREN",
    }
    not_assessed_labels = {item.raw_label for item in patient.not_assessed}
    supported_labels = {
        obs.raw_analyte_label for obs in observations if str(obs.support_state) == "supported"
    }

    assert recovered_labels.isdisjoint(not_assessed_labels)
    assert recovered_labels <= supported_labels
