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


async def test_wave21_innoquest_address_line_no_longer_leaks_to_not_assessed(
    api_client: AsyncClient,
) -> None:
    """Wave-21: The GRIBBLES IT DEPARTMENT / 14 JALAN 19/1 2ND FLR address
    line must no longer appear in patient not_assessed after the
    `_LOCATION_HINTS` expansion."""
    upload_payload = await _upload_corpus_pdf(api_client, "easy/seed_innoquest_dbticbm.pdf")
    job_id = upload_payload["job_id"]

    patient = await _patient_artifact(api_client, job_id)

    address_markers = (
        "gribbles it department",
        "14 jalan 19/1",
        "2nd flr",
    )
    assert not any(
        marker in item.raw_label.lower()
        for item in patient.not_assessed
        for marker in address_markers
    ), (
        f"Address line still leaks to not_assessed: "
        f"{[item.raw_label for item in patient.not_assessed if any(m in item.raw_label.lower() for m in address_markers)]}"
    )


async def test_wave22_innoquest_threshold_labels_blocked_in_resolver() -> None:
    """V12: Threshold/risk labels like 'Intermediate' must NOT leak as partial
    observations through the analyte resolver."""
    from app.services.analyte_resolver import AnalyteResolver

    resolver = AnalyteResolver()
    threshold_labels = [
        "Intermediate",
        "Low CV Risk",
        "High CV Risk",
        "Risk Cut Off Low",
    ]
    for label in threshold_labels:
        result = resolver.resolve(
            label,
            context={
                "family_adapter_id": "innoquest_bilingual_general",
                "specimen_context": "serum",
                "language_id": "en",
            },
        )
        assert result["support_state"] == "unsupported", f"{label} should be unsupported"
        assert result["failure_code"] == "threshold_category", f"{label} failure_code mismatch"


async def test_wave22_nmol_l_unit_classifies_correctly() -> None:
    """V12: nmol/L should classify as molar_concentration."""
    from app.services.ucum import UcumEngine

    engine = UcumEngine()
    assert engine.classify_unit_family("nmol/L") == "molar_concentration"
    assert engine.classify_unit_family("pg/mL") == "mass_concentration"
    assert engine.classify_unit_family("B/A") == "ratio"


async def test_wave22_innoquest_analyte_resolver_accepts_new_analytes() -> None:
    """V12: New Innoquest analytes should resolve with correct units."""
    from app.services.analyte_resolver import AnalyteResolver

    resolver = AnalyteResolver()

    cases = [
        # (label, unit, context)
        ("Lipoprotein(a)", "nmol/L", {"specimen_context": "serum", "language_id": "en"}),
        ("Apolipoprotein A1", "g/L", {"specimen_context": "serum", "language_id": "en"}),
        ("Apolipoprotein B", "g/L", {"specimen_context": "serum", "language_id": "en"}),
        ("Serum Insulin", "uIU/mL", {"specimen_context": "serum", "language_id": "en"}),
        ("GGT", "U/L", {"specimen_context": "serum", "language_id": "en"}),
    ]
    for label, unit, ctx in cases:
        result = resolver.resolve(label, context={**ctx, "family_adapter_id": "innoquest_bilingual_general"})
        assert result["support_state"] == "supported", f"{label} not supported: {result['failure_code']}"


async def test_wave23_innoquest_noisy_labels_and_troponin_paths_resolve() -> None:
    """V12: noisy section-prefixed labels must still resolve to launch-scope
    analytes when they carry valid measurements."""
    from app.services.analyte_resolver import AnalyteResolver

    resolver = AnalyteResolver()
    cases = [
        ("Electrolytes Sodium", "2951-2", "mmol/L"),
        ("SERUM/PLASMA GLUCOSE Glucose 葡萄糖", "2345-7", "mmol/L"),
        ("Apolipoprotein A 载脂蛋白 A", "15232-1", "g/L"),
        ("Apolipoprotein B/A ratio 载脂蛋白 B/A", "55884-4", ""),
        ("Test Name In Range Out Of Range Reference Range Lab VITAMIN D,25-OH,TOTAL,IA", "62292-8", "ng/mL"),
        ("Troponin hs-cTnT", "6598-7", "ng/L"),
        ("NT-ProBNP", "33762-6", "pg"),
    ]

    for raw_label, expected_code, raw_unit in cases:
        result = resolver.resolve(
            raw_label,
            context={
                "family_adapter_id": "innoquest_bilingual_general",
                "specimen_context": "serum",
                "language_id": "en",
                "raw_unit_string": raw_unit,
            },
        )
        accepted = result.get("accepted_candidate")
        assert accepted is not None, (
            f"{raw_label!r} should resolve, got failure={result['failure_code']}"
        )
        assert accepted["candidate_code"] == expected_code, (
            f"{raw_label!r} resolved to {accepted['candidate_code']}, expected {expected_code}"
        )


async def test_wave2_innoquest_mixed_bilingual_labels_resolve() -> None:
    """V12 wave-2: Mixed bilingual and garbled-encoding labels from DBTICRP
    must resolve to their canonical analytes through label rewrites."""
    from app.services.analyte_resolver import AnalyteResolver

    resolver = AnalyteResolver()

    # Mixed bilingual forms that go through bilingual translation + rewrite
    mixed_cases = [
        # (raw_label, expected_canonical_code, unit)
        # v12: real fixture-backed Unicode forms (not mojibake)
        ("Lipoprotein(a) 脂蛋白 a", "13386-7", "nmol/L"),
        ("Total Chol 总胆固醇", "2093-3", "mmol/L"),
    ]
    for raw_label, expected_code, unit in mixed_cases:
        result = resolver.resolve(
            raw_label,
            context={
                "family_adapter_id": "innoquest_bilingual_general",
                "specimen_context": "serum",
                "language_id": "en",
                "raw_unit_string": unit,
            },
        )
        assert result["support_state"] == "supported", (
            f"{raw_label!r} must be supported: {result['failure_code']}"
        )
        accepted = result.get("accepted_candidate")
        assert accepted is not None, f"{raw_label!r} must resolve to a candidate"
        assert accepted["candidate_code"] == expected_code, (
            f"{raw_label!r} resolved to {accepted['candidate_code']}, expected {expected_code}"
        )

    # Chinese-only labels that translate via bilingual dict
    chinese_cases = [
        ("载脂蛋白 A", "15232-1", "g/L"),
        ("载脂蛋白 B", "18768-1", "g/L"),
        ("总胆红素", "1975-2", "umol/L"),
    ]
    for raw_label, expected_code, unit in chinese_cases:
        result = resolver.resolve(
            raw_label,
            context={
                "family_adapter_id": "innoquest_bilingual_general",
                "specimen_context": "serum",
                "language_id": "en",
                "raw_unit_string": unit,
            },
        )
        assert result["support_state"] == "supported", (
            f"{raw_label!r} must be supported: {result['failure_code']}"
        )
        accepted = result.get("accepted_candidate")
        assert accepted is not None, f"{raw_label!r} must resolve to a candidate"
        assert accepted["candidate_code"] == expected_code, (
            f"{raw_label!r} resolved to {accepted['candidate_code']}, expected {expected_code}"
        )


async def test_wave2_non_hdl_mmol_l_unit_compatibility() -> None:
    """V12 wave-2: Non-HDL in mmol/L must be unit-compatible (molar_concentration)."""
    from app.services.analyte_resolver import AnalyteResolver

    resolver = AnalyteResolver()
    result = resolver.resolve(
        "Non-HDL",
        context={
            "family_adapter_id": "innoquest_bilingual_general",
            "specimen_context": "serum",
            "language_id": "en",
            "raw_unit_string": "mmol/L",
        },
    )
    assert result["support_state"] == "supported", (
        f"Non-HDL mmol/L must be supported: {result['failure_code']}"
    )


async def test_wave2_threshold_fragments_blocked_in_resolver() -> None:
    """V12 wave-2: Additional threshold/risk table fragments from DBTICRP
    must NOT survive as pseudo-lab candidates."""
    from app.services.analyte_resolver import AnalyteResolver

    resolver = AnalyteResolver()
    threshold_labels = [
        "Moderate CV Risk <2.6",
        "Very High CV Risk <=1.4",
        "Risk Cut Off Low",
        "Atherogenic Low",
        "Recurrent CV events",
        "AIP",
        "Biochem.",
    ]
    for label in threshold_labels:
        result = resolver.resolve(
            label,
            context={
                "family_adapter_id": "innoquest_bilingual_general",
                "specimen_context": "serum",
                "language_id": "en",
            },
        )
        assert result["support_state"] == "unsupported", (
            f"{label!r} should be unsupported, got {result['support_state']}"
        )
        assert result["failure_code"] == "threshold_category", (
            f"{label!r} failure_code mismatch: {result['failure_code']}"
        )


async def test_wave4_innoquest_triglyceride_bilingual_label_resolves() -> None:
    """V12 wave-4: 'Triglyceride 三酸甘油酯' must resolve to the repo's
    triglycerides candidate
    with supported state under mmol/L after bilingual normalization."""
    from app.services.analyte_resolver import AnalyteResolver

    resolver = AnalyteResolver()
    result = resolver.resolve(
        "Triglyceride 三酸甘油酯",
        context={
            "family_adapter_id": "innoquest_bilingual_general",
            "specimen_context": "serum",
            "language_id": "en",
            "raw_unit_string": "mmol/L",
        },
    )
    assert result["support_state"] == "supported", (
        f"Triglyceride 三酸甘油酯 should be supported: {result['failure_code']}"
    )
    accepted = result.get("accepted_candidate")
    assert accepted is not None
    assert accepted["candidate_code"] == "2571-8", (
        f"Expected 2571-8, got {accepted['candidate_code']}"
    )


async def test_wave4_innoquest_apolipoprotein_a1_bilingual_label_resolves() -> None:
    """V12 wave-4: 'Apolipoprotein A1 载脂蛋白 A1' must resolve to 15232-1
    with supported state under g/L."""
    from app.services.analyte_resolver import AnalyteResolver

    resolver = AnalyteResolver()
    result = resolver.resolve(
        "Apolipoprotein A1 载脂蛋白 A1",
        context={
            "family_adapter_id": "innoquest_bilingual_general",
            "specimen_context": "serum",
            "language_id": "en",
            "raw_unit_string": "g/L",
        },
    )
    assert result["support_state"] == "supported", (
        f"Apolipoprotein A1 载脂蛋白 A1 should be supported: {result['failure_code']}"
    )
    accepted = result.get("accepted_candidate")
    assert accepted is not None
    assert accepted["candidate_code"] == "15232-1", (
        f"Expected 15232-1, got {accepted['candidate_code']}"
    )


async def test_wave4_innoquest_total_bilirubin_chinese_label_resolves() -> None:
    """V12 wave-4: '总红胆素' must resolve to 1975-2
    with supported state under umol/L."""
    from app.services.analyte_resolver import AnalyteResolver

    resolver = AnalyteResolver()
    result = resolver.resolve(
        "总红胆素",
        context={
            "family_adapter_id": "innoquest_bilingual_general",
            "specimen_context": "serum",
            "language_id": "en",
            "raw_unit_string": "umol/L",
        },
    )
    assert result["support_state"] == "supported", (
        f"总红胆素 should be supported: {result['failure_code']}"
    )
    accepted = result.get("accepted_candidate")
    assert accepted is not None
    assert accepted["candidate_code"] == "1975-2", (
        f"Expected 1975-2, got {accepted['candidate_code']}"
    )


async def test_wave24_innoquest_apolipoprotein_ratio_unit_aware_rewrite_resolves() -> None:
    """V12 wave-24: DBTICRP rows with compact Chinese apolipoprotein labels
    and B/A unit channels should resolve to ApoB/ApoA1 ratio."""
    from app.services.analyte_resolver import AnalyteResolver

    resolver = AnalyteResolver()
    result = resolver.resolve(
        "载脂蛋白",
        context={
            "family_adapter_id": "innoquest_bilingual_general",
            "specimen_context": "serum",
            "language_id": "en",
            "raw_unit_string": "B/A",
        },
    )
    assert result["support_state"] == "supported", (
        f"载脂蛋白 with B/A unit should be supported: {result['failure_code']}"
    )
    accepted = result.get("accepted_candidate")
    assert accepted is not None
    assert accepted["candidate_code"] == "55884-4", (
        f"Expected 55884-4, got {accepted['candidate_code']}"
    )


async def test_wave24_sterling_core_label_rewrites_resolve() -> None:
    """V12 wave-24: Sterling packet residual labels should resolve after
    lexical rewrites so core supported coverage is retained."""
    from app.services.analyte_resolver import AnalyteResolver

    resolver = AnalyteResolver()
    cases = [
        ("Mean Blood Glucose", "mg/dL", "Glucose"),
        ("Urine Glucose", "", "Glucose"),
        ("Urine Protein", "", "Total Protein"),
        ("Microalbumin (per urine volume)", "mg/L", "Urine Albumin"),
    ]

    for raw_label, raw_unit, expected_display in cases:
        result = resolver.resolve(
            raw_label,
            context={
                "family_adapter_id": "generic_layout",
                "specimen_context": "urine",
                "language_id": "en",
                "raw_unit_string": raw_unit,
            },
        )
        assert result["support_state"] == "supported", (
            f"{raw_label!r} should be supported: {result['failure_code']}"
        )
        accepted = result.get("accepted_candidate")
        assert accepted is not None
        assert accepted["candidate_display"] == expected_display


# ---------------------------------------------------------------------------
# v12 parser threshold-comparator leak pre-emption tests
# ---------------------------------------------------------------------------


async def test_v12_parser_threshold_comparator_rows_blocked_before_measurement() -> None:
    """V12: Innoquest threshold/risk-table rows with comparators must NOT
    reach measured_analyte_row classification in classify_candidate_text."""
    from app.services.parser import classify_candidate_text

    threshold_rows = [
        "Intermediate",
        "Moderate CV Risk <2.6",
        "Very High CV Risk <=1.4",
        "Low CV Risk",
        "High CV Risk",
        "Cut Off Low",
        "Cut Off High",
        "Risk Cut Off Low",
        "Recurrent CV events",
    ]
    for raw in threshold_rows:
        result = classify_candidate_text(
            raw,
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["row_type"] != "measured_analyte_row", (
            f"{raw!r} should not classify as measured_analyte_row"
        )
        assert result["support_code"] == "excluded", (
            f"{raw!r} should be excluded, got {result['support_code']}"
        )


# ---------------------------------------------------------------------------
# v12: RowAssemblerV2 residual leak family — excluded label-only groups
# must NOT be prepended into the next value-bearing group
# ---------------------------------------------------------------------------


async def test_v12_row_assembler_excluded_label_groups_not_merged_into_next_value_group() -> None:
    """V12: RowAssemblerV2._group_lines_into_measurements must drop excluded
    label-only groups (e.g. "High", "Low", "within", "Total Men") instead of
    blindly prepending them into the next value-bearing measurement group.

    The residual DBTICRP leak family:
    High, Low, within, Total Men, /HDL-c ratio Women, LDL-c/HDL-c Men,
    Castelli II Women, Cholesterol /HDL-c ratio Women,
    Ratio Castelli II Women, Clin Chem Lab Med, REF. RANGES SPECIAL
    CHEMISTRY SPECIMEN SERUM NT-ProBNP.

    When these appear as consecutive label-only lines in a result_table /
    unknown block, the merge loop used to prepend them into the next
    value-bearing group, which then reclassified the merged text as a
    measurement candidate.
    """
    from app.services.row_assembler.v2 import RowAssemblerV2

    assembler = RowAssemblerV2()

    # Simulate a residual DBTICRP leak block: excluded label-only lines
    # followed by a value-bearing line for a real analyte.
    lines = [
        "High",
        "Low",
        "within",
        "Total Men",
        "LDL-c/HDL-c Men",
        "Cholesterol",  # real analyte label
        "4.2",  # value
        "mmol/L",  # unit
    ]

    groups = assembler._group_lines_into_measurements(
        lines,
        family_adapter_id="innoquest_bilingual_general",
        page_class="analyte_table_page",
    )

    # The excluded label-only lines must NOT be prepended into the value group.
    # We expect at most one group with the real analyte (Cholesterol 4.2 mmol/L).
    from app.services.row_assembler.v2 import _is_value_bearing_line

    value_groups = [
        g for g in groups
        if any(_is_value_bearing_line(ln) for ln in g)
    ]

    # There should be exactly one value group (the real analyte)
    assert len(value_groups) == 1, (
        f"Expected exactly 1 value group, got {len(value_groups)}: {groups}"
    )

    # The value group must NOT start with excluded labels like "High" or "Low"
    first_group = value_groups[0]
    for excluded_label in ("High", "Low", "within", "Total Men", "LDL-c/HDL-c Men"):
        assert excluded_label not in first_group, (
            f"Excluded label {excluded_label!r} leaked into value group: {first_group}"
        )


async def test_v12_row_assembler_excluded_label_groups_dropped_not_merged() -> None:
    """V12: When a block contains ONLY excluded label-only lines with no
    value-bearing group following them, they must be dropped entirely."""
    from app.services.row_assembler.v2 import RowAssemblerV2

    assembler = RowAssemblerV2()

    lines = [
        "High",
        "Low",
        "within",
        "Total Men",
    ]

    groups = assembler._group_lines_into_measurements(
        lines,
        family_adapter_id="innoquest_bilingual_general",
        page_class="analyte_table_page",
    )

    # All groups should be dropped since none contain value-bearing lines
    # and there is no next value group to merge into
    assert len(groups) == 0, (
        f"Expected 0 groups for all-excluded labels, got {groups}"
    )


def _value_bearing_in_group(group: list[str]) -> bool:
    """Return True if any line in a group is value-bearing."""
    from app.services.row_assembler.v2 import _is_value_bearing_line
    return any(_is_value_bearing_line(ln) for ln in group)
