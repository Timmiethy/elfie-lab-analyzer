"""Extended test: real OCR variations from diverse lab reports."""

import pytest
from app.services.analyte_resolver import AnalyteResolver


class TestAnalyteResolverOCRVariations:
    """Test actual OCR input variations that break current system."""

    @pytest.fixture
    def resolver(self):
        return AnalyteResolver()

    # Hematology variations (WBC, RBC, Hemoglobin, etc.)
    @pytest.mark.parametrize("raw_label", [
        "WBC",  # Already supported
        "wbc count",  # OCR: "WBC Count"
        "white blood cell",  # Full name
        "white blood cell count",  # Full expanded
        "wbc/ul",  # With unit stripped
        "wbc- 10^3/ul",  # With complex unit
    ])
    def test_wbc_variations(self, resolver, raw_label):
        """WBC should support all common variations."""
        result = resolver.resolve(raw_label)
        assert result["support_state"] == "supported", f"Failed: {raw_label}"
        assert result["accepted_candidate"]["candidate_code"] == "METRIC-0001"

    @pytest.mark.parametrize("raw_label", [
        "RBC",
        "rbc count",
        "red blood cell",
        "red blood cell count",
        "rbc /ul",
    ])
    def test_rbc_variations(self, resolver, raw_label):
        """RBC should support all common variations."""
        result = resolver.resolve(raw_label)
        assert result["support_state"] == "supported", f"Failed: {raw_label}"
        assert result["accepted_candidate"]["candidate_code"] == "METRIC-0002"

    # Hemoglobin/HbA1c (tricky: same base word)
    @pytest.mark.parametrize("raw_label", [
        "Hemoglobin",
        "hemoglobin (g/dl)",
        "Hb",
        "HGB",
    ])
    def test_hemoglobin_variations(self, resolver, raw_label):
        """Generic Hemoglobin (not A1c) should resolve."""
        result = resolver.resolve(raw_label)
        assert result["support_state"] == "supported", f"Failed: {raw_label}"
        # Should be METRIC-0003, not HbA1c
        assert result["accepted_candidate"]["candidate_code"] == "METRIC-0003"

    @pytest.mark.parametrize("raw_label", [
        "HbA1c",
        "HBA1C",
        "hba1c",
        "Hemoglobin A1c",
        "Hemoglobin A1C",
        "HB A1C",
        "Hb A1c",
        "A1C",  # OCR: sometimes just the A1C part
        "HbA1C (NGSP)",  # With calibration
        "HbA1c NGSP %",  # With unit
        "HbA1C DCCT",
        "HbA1c IFCC",
        "HbA1C mmol/mol",  # IFCC unit
    ])
    def test_hba1c_variations(self, resolver, raw_label):
        """HbA1c variants all resolve to METRIC-0063/0064."""
        result = resolver.resolve(raw_label)
        assert result["support_state"] == "supported", f"Failed: {raw_label}"
        assert result["accepted_candidate"]["candidate_code"] in ("METRIC-0063", "METRIC-0064")

    # Electrolytes (Sodium, Potassium, Chloride)
    @pytest.mark.parametrize("raw_label", [
        "Sodium",
        "Na",
        "Na+",
        "Sodium (Na)",
        "Na (mmol/L)",
        "Serum sodium",
    ])
    def test_sodium_variations(self, resolver, raw_label):
        """Sodium should resolve even from shorthand 'Na'."""
        result = resolver.resolve(raw_label)
        assert result["support_state"] == "supported", f"Failed: {raw_label}"
        assert result["accepted_candidate"]["candidate_code"] == "METRIC-0020"

    @pytest.mark.parametrize("raw_label", [
        "Potassium",
        "K",
        "K+",
        "Potassium (K)",
        "K (mmol/L)",
        "Serum potassium",
    ])
    def test_potassium_variations(self, resolver, raw_label):
        """Potassium should resolve from shorthand 'K'."""
        result = resolver.resolve(raw_label)
        assert result["support_state"] == "supported", f"Failed: {raw_label}"
        assert result["accepted_candidate"]["candidate_code"] == "METRIC-0021"

    # Renal function
    @pytest.mark.parametrize("raw_label", [
        "Creatinine",
        "Creat",
        "Crea",
        "CREAT.",
        "Creatinine (mg/dL)",
        "S. Creatinine",
        "Serum Creatinine",
    ])
    def test_creatinine_variations(self, resolver, raw_label):
        """Creatinine variants."""
        result = resolver.resolve(raw_label)
        assert result["support_state"] == "supported", f"Failed: {raw_label}"
        assert result["accepted_candidate"]["candidate_code"] == "METRIC-0029"

    @pytest.mark.parametrize("raw_label", [
        "eGFR",
        "eGFR (CKD-EPI)",
        "eGFR ckd epi",
        "eGFR CKD-EPI",
        "Estimated GFR",
        "Estimated Glomerular Filtration Rate",
        "GFR",  # Shorthand
        "eGFR (ml/min)",
        "eGFR calc",
        "eGFR (calculated)",
    ])
    def test_egfr_variations(self, resolver, raw_label):
        """eGFR variants."""
        result = resolver.resolve(raw_label)
        assert result["support_state"] == "supported", f"Failed: {raw_label}"
        assert result["accepted_candidate"]["candidate_code"] == "METRIC-0030"

    # Glucose
    @pytest.mark.parametrize("raw_label", [
        "Glucose",
        "Glucose, Fasting",
        "Fasting Glucose",
        "Blood Glucose",
        "Glucose (fasting)",
        "Glucose-fasting",
        "Fasting Blood Glucose",
        "FBS",  # Fasting blood sugar
        "Glucose (mg/dL)",
    ])
    def test_glucose_variations(self, resolver, raw_label):
        """Fasting glucose variants."""
        result = resolver.resolve(raw_label)
        assert result["support_state"] == "supported", f"Failed: {raw_label}"
        assert result["accepted_candidate"]["candidate_code"] == "METRIC-0019"

    # Lipid profile
    @pytest.mark.parametrize("raw_label", [
        "Total Cholesterol",
        "Cholesterol, Total",
        "Cholesterol Total",
        "Total Chol",
        "CHOL",  # Shorthand
        "Total Cholesterol (mg/dL)",
    ])
    def test_total_cholesterol_variations(self, resolver, raw_label):
        """Total cholesterol variants."""
        result = resolver.resolve(raw_label)
        assert result["support_state"] == "supported", f"Failed: {raw_label}"
        assert result["accepted_candidate"]["candidate_code"] == "METRIC-0051"

    @pytest.mark.parametrize("raw_label", [
        "LDL",
        "LDL-C",
        "LDL-Cholesterol",
        "Low Density Lipoprotein",
        "Low Density Lipoprotein Cholesterol",
        "LDL (calc)",
        "LDL (calculated)",
        "LDL cholesterol (calc)",
    ])
    def test_ldl_variations(self, resolver, raw_label):
        """LDL variants."""
        result = resolver.resolve(raw_label)
        assert result["support_state"] == "supported", f"Failed: {raw_label}"
        assert result["accepted_candidate"]["candidate_code"] == "METRIC-0053"

    @pytest.mark.parametrize("raw_label", [
        "HDL",
        "HDL-C",
        "HDL-Cholesterol",
        "High Density Lipoprotein",
        "High Density Lipoprotein Cholesterol",
    ])
    def test_hdl_variations(self, resolver, raw_label):
        """HDL variants."""
        result = resolver.resolve(raw_label)
        assert result["support_state"] == "supported", f"Failed: {raw_label}"
        assert result["accepted_candidate"]["candidate_code"] == "METRIC-0052"

    @pytest.mark.parametrize("raw_label", [
        "Triglycerides",
        "Triglyceride",
        "Trig",
        "TRIG",
        "Triglycerides (mg/dL)",
    ])
    def test_triglycerides_variations(self, resolver, raw_label):
        """Triglycerides variants."""
        result = resolver.resolve(raw_label)
        assert result["support_state"] == "supported", f"Failed: {raw_label}"
        assert result["accepted_candidate"]["candidate_code"] == "METRIC-0054"

    # Liver function
    @pytest.mark.parametrize("raw_label", [
        "ALT",
        "SGPT",
        "Alanine Aminotransferase",
        "ALT (SGPT)",
        "ALT/SGPT",  # Slash format
    ])
    def test_alt_variations(self, resolver, raw_label):
        """ALT variants."""
        result = resolver.resolve(raw_label)
        assert result["support_state"] == "supported", f"Failed: {raw_label}"
        # ALT is METRIC-0040

    @pytest.mark.parametrize("raw_label", [
        "AST",
        "SGOT",
        "Aspartate Aminotransferase",
        "AST (SGOT)",
        "AST/SGOT",  # Slash format
    ])
    def test_ast_variations(self, resolver, raw_label):
        """AST variants."""
        result = resolver.resolve(raw_label)
        assert result["support_state"] == "supported", f"Failed: {raw_label}"
        # AST is METRIC-0039
