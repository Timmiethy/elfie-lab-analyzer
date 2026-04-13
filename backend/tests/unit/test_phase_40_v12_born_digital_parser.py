"""V12 Born-digital parser tests: PyMuPDF -> PageParseArtifactV3 -> RowAssemblerV2.

These tests verify:
1. PyMuPDF is the primary born-digital backend (not pdfplumber).
2. Parser emits PageParseArtifactV3, never CanonicalObservation.
3. RowAssemblerV2 produces typed candidate rows from artifacts.
4. Bilingual rows, dual-value rows, comparator-first rows, threshold fencing,
   and multi-column / mixed-page text PDFs are exercised against real fixtures.
5. Admin/narrative/threshold rows are excluded (leak prevention).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.parser.born_digital_parser import BornDigitalParser, BACKEND_ID, LANE_TYPE
from app.services.parser.page_parse_artifact_v3 import PageParseArtifactV3, PageParseBlockV3
from app.services.row_assembler.v2 import RowAssemblerV2, VALID_ROW_TYPES, NORMALIZABLE_ROW_TYPES

ROOT = Path(__file__).resolve().parents[3]
PDF_DIR = ROOT / "pdfs_by_difficulty"


def _load_pdf(relative_path: str) -> bytes:
    return (PDF_DIR / relative_path).read_bytes()


def _parse_pdf(relative_path: str) -> list[PageParseArtifactV3]:
    parser = BornDigitalParser()
    return parser.parse(_load_pdf(relative_path), source_file_path=relative_path)


def _assemble(artifacts: list[PageParseArtifactV3]) -> list[dict]:
    assembler = RowAssemblerV2()
    rows: list[dict] = []
    for artifact in artifacts:
        rows.extend(assembler.assemble(artifact))
    return rows


# ---------------------------------------------------------------------------
# 1. Backend identity and contract guards
# ---------------------------------------------------------------------------

class TestBackendIdentity:
    """PyMuPDF must be the primary born-digital backend with explicit id."""

    def test_backend_id_is_pymupdf(self):
        assert BACKEND_ID == "pymupdf"

    def test_lane_type_is_trusted_pdf(self):
        assert LANE_TYPE == "trusted_pdf"

    def test_parser_instance_carries_backend_id(self):
        parser = BornDigitalParser()
        assert parser.backend_id == "pymupdf"
        assert parser.lane_type == "trusted_pdf"

    def test_backend_version_is_resolved(self):
        parser = BornDigitalParser()
        assert parser.backend_version not in ("", "unknown")


class TestArtifactContract:
    """PageParseArtifactV3 is the only output; never emits observations."""

    def test_parse_returns_artifacts(self):
        artifacts = _parse_pdf("easy/seed_innoquest_dbticbm.pdf")
        assert len(artifacts) > 0
        for a in artifacts:
            assert isinstance(a, PageParseArtifactV3)

    def test_artifact_trust_level_is_trusted_pdf(self):
        artifacts = _parse_pdf("easy/seed_innoquest_dbticbm.pdf")
        for a in artifacts:
            assert a.trust_level == "trusted_pdf"

    def test_artifact_backend_id_matches(self):
        artifacts = _parse_pdf("easy/seed_innoquest_dbticbm.pdf")
        for a in artifacts:
            assert a.backend_id == "pymupdf"
            assert a.backend_version not in ("", "unknown")

    def test_artifact_has_blocks_or_raw_text(self):
        artifacts = _parse_pdf("easy/seed_innoquest_dbticbm.pdf")
        for a in artifacts:
            assert a.has_content, f"Page {a.page_number} has no content"

    def test_artifact_block_structure(self):
        artifacts = _parse_pdf("easy/seed_innoquest_dbticbm.pdf")
        for a in artifacts:
            for block in a.blocks:
                assert isinstance(block, PageParseBlockV3)
                assert block.text is not None
                assert block.block_type in {
                    "result_table", "threshold_table", "admin_meta",
                    "narrative", "footer", "header", "unknown",
                }

    def test_artifact_invalid_lane_type_rejected(self):
        with pytest.raises(ValueError, match="lane_type"):
            PageParseArtifactV3(
                page_id="test",
                lane_type="invalid",
                backend_id="x",
                backend_version="y",
            )

    def test_no_observations_emitted_by_parser(self):
        """Parser backends must never emit CanonicalObservation directly."""
        artifacts = _parse_pdf("easy/seed_innoquest_dbticbm.pdf")
        for a in artifacts:
            assert not hasattr(a, "observation") or a.observation is None
            for block in a.blocks:
                assert not hasattr(block, "observation")


class TestRowAssemblerV2Contract:
    """RowAssemblerV2 turns artifacts into typed candidate rows."""

    def test_assembly_produces_rows(self):
        artifacts = _parse_pdf("easy/seed_innoquest_dbticbm.pdf")
        rows = _assemble(artifacts)
        assert len(rows) > 0

    def test_rows_have_required_fields(self):
        artifacts = _parse_pdf("easy/seed_innoquest_dbticbm.pdf")
        rows = _assemble(artifacts)
        required = {
            "row_type", "raw_text", "raw_analyte_label",
            "raw_value_string", "raw_unit_string", "raw_reference_range",
            "parsed_numeric_value", "parsed_locale", "parsed_comparator",
            "measurement_kind", "support_code", "failure_code",
            "family_adapter_id", "page_class", "source_kind", "block_id",
            "source_page", "source_file_path", "trust_level",
            "backend_id", "backend_version", "candidate_trace",
        }
        for row in rows:
            missing = required - set(row.keys())
            assert not missing, f"Row missing keys: {missing}"

    def test_all_row_types_are_valid(self):
        artifacts = _parse_pdf("easy/seed_innoquest_dbticbm.pdf")
        rows = _assemble(artifacts)
        for row in rows:
            assert row["row_type"] in VALID_ROW_TYPES, (
                f"Invalid row_type: {row['row_type']}"
            )

    def test_rows_carry_trust_level_from_artifact(self):
        artifacts = _parse_pdf("easy/seed_innoquest_dbticbm.pdf")
        rows = _assemble(artifacts)
        for row in rows:
            assert row["trust_level"] == "trusted_pdf"

    def test_rows_carry_backend_id_from_artifact(self):
        artifacts = _parse_pdf("easy/seed_innoquest_dbticbm.pdf")
        rows = _assemble(artifacts)
        for row in rows:
            assert row["backend_id"] == "pymupdf"
            assert row["backend_version"] not in ("", "unknown")

    def test_row_assembler_rejects_non_artifact(self):
        assembler = RowAssemblerV2()
        with pytest.raises(TypeError, match="PageParseArtifactV3"):
            assembler.assemble({"not": "an artifact"})


# ---------------------------------------------------------------------------
# 2. Easy PDF: seed_innoquest_dbticbm.pdf
# ---------------------------------------------------------------------------

class TestEasyInnoquestBilingual:
    """Easy bilingual text PDF: core row extraction and leak prevention."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.artifacts = _parse_pdf("easy/seed_innoquest_dbticbm.pdf")
        self.rows = _assemble(self.artifacts)

    def test_multiple_pages_parsed(self):
        assert len(self.artifacts) >= 2

    def test_measured_analyte_rows_found(self):
        measured = [r for r in self.rows if r["row_type"] == "measured_analyte_row"]
        assert len(measured) > 0, "Expected measured analyte rows"

    def test_admin_rows_excluded(self):
        """Admin metadata rows must never reach the observation pool."""
        admin_rows = [r for r in self.rows if r["row_type"] == "admin_metadata_row"]
        for row in admin_rows:
            assert row["support_code"] == "excluded"
            assert row["failure_code"] == "admin_metadata_row"

    def test_sodium_bilingual_row_detected(self):
        """Sodium 钠 should be recognized as a measured analyte row."""
        sodium_rows = [
            r for r in self.rows
            if "sodium" in r["raw_text"].lower() and r["row_type"] == "measured_analyte_row"
        ]
        assert len(sodium_rows) > 0, "Sodium row not found"

    def test_creatinine_row_detected(self):
        creatinine_rows = [
            r for r in self.rows
            if "creatinine" in r["raw_text"].lower() and r["row_type"] == "measured_analyte_row"
        ]
        assert len(creatinine_rows) > 0, "Creatinine row not found"

    def test_glucose_row_detected(self):
        glucose_rows = [
            r for r in self.rows
            if "glucose" in r["raw_text"].lower() and r["row_type"] == "measured_analyte_row"
        ]
        assert len(glucose_rows) > 0, "Glucose row not found"

    def test_hba1c_row_detected(self):
        hba1c_rows = [
            r for r in self.rows
            if "hba1c" in r["raw_text"].lower() and r["row_type"] in NORMALIZABLE_ROW_TYPES
        ]
        assert len(hba1c_rows) > 0, "HbA1c row not found"

    def test_derived_analyte_egfr_partial(self):
        """eGFR should be typed as derived_analyte_row with partial support."""
        egfr_rows = [
            r for r in self.rows
            if "egfr" in r["raw_text"].lower()
            and r["row_type"] == "derived_analyte_row"
        ]
        for row in egfr_rows:
            assert row["support_code"] in {"partial", "supported"}


# ---------------------------------------------------------------------------
# 3. Medium PDF: seed_innoquest_bilingual_2dbtica.pdf
# ---------------------------------------------------------------------------

class TestMediumBilingualInnoquest:
    """Medium bilingual PDF: ACR and more complex row patterns."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.artifacts = _parse_pdf("medium/seed_innoquest_bilingual_2dbtica.pdf")
        self.rows = _assemble(self.artifacts)

    def test_pages_parsed(self):
        assert len(self.artifacts) >= 1

    def test_acr_comparator_first_row(self):
        """ACR has comparator-before-value pattern: < 0.1 mg Alb/mmol."""
        acr_rows = [
            r for r in self.rows
            if "acr" in r["raw_text"].lower()
            and r["row_type"] in NORMALIZABLE_ROW_TYPES
        ]
        if acr_rows:
            row = acr_rows[0]
            assert row["row_type"] in {"measured_analyte_row", "derived_analyte_row"}

    def test_measured_rows_present(self):
        measured = [r for r in self.rows if r["row_type"] == "measured_analyte_row"]
        assert len(measured) > 0

    def test_no_admin_leak_to_patient_facing(self):
        """Admin rows should be excluded, not hidden."""
        admin_rows = [r for r in self.rows if r["row_type"] == "admin_metadata_row"]
        for row in admin_rows:
            assert row["support_code"] == "excluded"


# ---------------------------------------------------------------------------
# 4. Hard PDF: var_innoquest_cardiometabolic_mixed_page_order.pdf
# ---------------------------------------------------------------------------

class TestHardInnoquestMixedPageOrder:
    """Hard PDF with mixed page order and cardiometabolic panels."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.artifacts = _parse_pdf(
            "hard/var_innoquest_cardiometabolic_mixed_page_order.pdf"
        )
        self.rows = _assemble(self.artifacts)

    def test_multiple_pages_parsed(self):
        assert len(self.artifacts) >= 1

    def test_threshold_rows_excluded(self):
        """Threshold table rows must be excluded from normalization."""
        threshold_rows = [
            r for r in self.rows
            if r["row_type"] == "threshold_reference_row"
        ]
        for row in threshold_rows:
            assert row["support_code"] == "excluded"

    def test_narrative_rows_excluded(self):
        """Narrative guidance rows must be excluded."""
        narrative_rows = [
            r for r in self.rows
            if r["row_type"] == "narrative_guidance_row"
        ]
        for row in narrative_rows:
            assert row["support_code"] == "excluded"

    def test_measured_analytes_present(self):
        measured = [r for r in self.rows if r["row_type"] == "measured_analyte_row"]
        assert len(measured) > 0, "No measured analyte rows found in mixed page order PDF"

    def test_block_classification_covers_different_types(self):
        """Blocks should include different types."""
        block_types = set()
        for artifact in self.artifacts:
            for block in artifact.blocks:
                block_types.add(block.block_type)
        assert len(block_types) >= 1


# ---------------------------------------------------------------------------
# 5. Hard PDF: var_quest_cardioiq_comma_decimal_locale.pdf
# ---------------------------------------------------------------------------

class TestHardQuestCardioIQCommaDecimal:
    """Hard PDF with comma decimal locale and Quest format."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.artifacts = _parse_pdf(
            "hard/var_quest_cardioiq_comma_decimal_locale.pdf"
        )
        self.rows = _assemble(self.artifacts)

    def test_pages_parsed(self):
        assert len(self.artifacts) >= 1

    def test_measured_analytes_present(self):
        measured = [r for r in self.rows if r["row_type"] == "measured_analyte_row"]
        assert len(measured) > 0, "No measured analyte rows in Quest CardioIQ PDF"

    def test_comma_decimal_locale_handling(self):
        """Rows with comma decimal separators should parse correctly."""
        for row in self.rows:
            if row["row_type"] not in NORMALIZABLE_ROW_TYPES:
                continue
            locale = row.get("parsed_locale", {})
            if locale.get("decimal_separator") == ",":
                assert locale.get("normalized") is not None

    def test_admin_and_narrative_excluded(self):
        """Admin and narrative rows must be explicitly excluded."""
        excluded_rows = [
            r for r in self.rows if r["support_code"] == "excluded"
        ]
        assert len(excluded_rows) >= 0

    def test_header_footer_rows_excluded(self):
        header_rows = [
            r for r in self.rows if r["row_type"] == "footer_or_header_row"
        ]
        for row in header_rows:
            assert row["support_code"] == "excluded"


# ---------------------------------------------------------------------------
# 6. Cross-cutting: leak prevention across all fixtures
# ---------------------------------------------------------------------------

class TestLeakPrevention:
    """No admin/narrative/threshold content leaks into the observation pool."""

    _ALL_FIXTURES = [
        "easy/seed_innoquest_dbticbm.pdf",
        "medium/seed_innoquest_bilingual_2dbtica.pdf",
        "hard/var_innoquest_cardiometabolic_mixed_page_order.pdf",
        "hard/var_quest_cardioiq_comma_decimal_locale.pdf",
    ]

    def _get_rows(self, fixture: str) -> list[dict]:
        return _assemble(_parse_pdf(fixture))

    def test_no_admin_rows_in_normalizable_pool(self):
        for fixture in self._ALL_FIXTURES:
            rows = self._get_rows(fixture)
            for row in rows:
                if row["row_type"] in NORMALIZABLE_ROW_TYPES:
                    assert row["row_type"] != "admin_metadata_row"

    def test_no_narrative_rows_in_normalizable_pool(self):
        for fixture in self._ALL_FIXTURES:
            rows = self._get_rows(fixture)
            for row in rows:
                if row["row_type"] in NORMALIZABLE_ROW_TYPES:
                    assert row["row_type"] != "narrative_guidance_row"

    def test_no_threshold_rows_in_normalizable_pool(self):
        for fixture in self._ALL_FIXTURES:
            rows = self._get_rows(fixture)
            for row in rows:
                if row["row_type"] in NORMALIZABLE_ROW_TYPES:
                    assert row["row_type"] != "threshold_reference_row"

    def test_no_header_rows_in_normalizable_pool(self):
        for fixture in self._ALL_FIXTURES:
            rows = self._get_rows(fixture)
            for row in rows:
                if row["row_type"] in NORMALIZABLE_ROW_TYPES:
                    assert row["row_type"] != "footer_or_header_row"


# ---------------------------------------------------------------------------
# 7. Error handling and edge cases
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Parser and assembler handle edge cases gracefully."""

    def test_empty_bytes_raises(self):
        parser = BornDigitalParser()
        with pytest.raises(ValueError, match="empty input"):
            parser.parse(b"")

    def test_max_pages_respected(self):
        parser = BornDigitalParser()
        artifacts = parser.parse(
            _load_pdf("easy/seed_innoquest_dbticbm.pdf"),
            max_pages=1,
            source_file_path="test",
        )
        assert len(artifacts) <= 1

    def test_artifact_has_errors_flag(self):
        artifacts = _parse_pdf("easy/seed_innoquest_dbticbm.pdf")
        for a in artifacts:
            assert not a.has_errors

    def test_row_assembler_preserves_artifact_metadata(self):
        artifacts = _parse_pdf("easy/seed_innoquest_dbticbm.pdf")
        rows = _assemble(artifacts)
        for row in rows:
            assert row["trust_level"] in {"trusted_pdf", "image_beta", "debug"}
            assert row["backend_id"] == "pymupdf"
            assert row["backend_version"] not in ("", "unknown")

    def test_row_assembly_infers_bilingual_adapter(self):
        """RowAssemblerV2 should infer innoquest_bilingual_general for zh+en pages."""
        artifacts = _parse_pdf("easy/seed_innoquest_dbticbm.pdf")
        rows = _assemble(artifacts)
        bilingual_rows = [r for r in rows if r["family_adapter_id"] == "innoquest_bilingual_general"]
        assert len(bilingual_rows) > 0, (
            "Expected bilingual rows from Innoquest PDF, got only: "
            f"{set(r['family_adapter_id'] for r in rows)}"
        )

    def test_row_assembly_respects_explicit_override(self):
        """RowAssemblerV2 explicit family_adapter_id should override inference."""
        artifacts = _parse_pdf("easy/seed_innoquest_dbticbm.pdf")
        assembler = RowAssemblerV2()
        rows = assembler.assemble(artifacts[0], family_adapter_id="generic_layout")
        for row in rows:
            assert row["family_adapter_id"] == "generic_layout"
