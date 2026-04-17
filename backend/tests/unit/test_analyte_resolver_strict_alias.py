"""Tests for the strict deterministic alias matching in AnalyteResolver."""

from __future__ import annotations

from app.services.analyte_resolver import AnalyteResolver


def test_analyte_resolver_strict_alias_match() -> None:
    resolver = AnalyteResolver()

    # Exact match for a common analyte
    resolved = resolver.resolve("Glucose")
    assert resolved["support_state"] == "supported"
    assert resolved["accepted_candidate"] is not None
    assert resolved["accepted_candidate"]["accepted"]
    assert resolved["accepted_candidate"]["score"] == 1.0
    assert resolved["accepted_candidate"]["threshold_used"] > 0.0

    # Unmatched / garbage
    resolved_unsupported = resolver.resolve("Unknown Random Analyte")
    assert resolved_unsupported["support_state"] == "unsupported"
    assert resolved_unsupported["accepted_candidate"] is None
    assert resolved_unsupported["abstention_reasons"] == ["unsupported_alias"]
    assert len(resolved_unsupported["candidates"]) == 1
    assert not resolved_unsupported["candidates"][0]["accepted"]
    assert resolved_unsupported["candidates"][0]["score"] == 0.0
    assert resolved_unsupported["candidates"][0]["threshold_used"] > 0.0
    assert resolved_unsupported["candidates"][0]["rejection_reason"] == "unsupported_alias"


def test_analyte_resolver_normalizes_multilingual_label_to_supported_alias() -> None:
    resolver = AnalyteResolver()

    resolved = resolver.resolve("Creatinine 肌酸酐")

    assert resolved["support_state"] == "supported"
    assert resolved["accepted_candidate"] is not None
    assert resolved["accepted_candidate"]["candidate_code"] == "METRIC-0029"


def test_analyte_resolver_no_fuzzy_matching() -> None:
    resolver = AnalyteResolver()

    # Strict matching should reject anything not exactly in the aliases
    resolved = resolver.resolve("HbA1c fuzzy")
    assert resolved["support_state"] == "unsupported"
    assert resolved["accepted_candidate"] is None


def test_analyte_resolver_supports_slash_alias_components() -> None:
    resolver = AnalyteResolver()

    resolved_ast = resolver.resolve("AST")
    resolved_sgpt = resolver.resolve("SGPT")

    assert resolved_ast["support_state"] == "supported"
    assert resolved_ast["accepted_candidate"] is not None
    assert resolved_ast["accepted_candidate"]["candidate_code"] == "METRIC-0039"

    assert resolved_sgpt["support_state"] == "supported"
    assert resolved_sgpt["accepted_candidate"] is not None
    assert resolved_sgpt["accepted_candidate"]["candidate_code"] == "METRIC-0040"


def test_analyte_resolver_supports_token_order_equivalent_labels() -> None:
    resolver = AnalyteResolver()

    resolved = resolver.resolve("Cholesterol Total")

    assert resolved["support_state"] == "supported"
    assert resolved["accepted_candidate"] is not None
    assert resolved["accepted_candidate"]["candidate_code"] == "METRIC-0051"


def test_analyte_resolver_supports_common_qualifier_suffixes() -> None:
    resolver = AnalyteResolver()

    creatinine = resolver.resolve("Creatinine S")
    egfr = resolver.resolve("eGFR CKD EPI")
    hba1c = resolver.resolve("HbA1c IFCC")

    assert creatinine["support_state"] == "supported"
    assert creatinine["accepted_candidate"] is not None
    assert creatinine["accepted_candidate"]["candidate_code"] == "METRIC-0029"

    assert egfr["support_state"] == "supported"
    assert egfr["accepted_candidate"] is not None
    assert egfr["accepted_candidate"]["candidate_code"] == "METRIC-0030"

    assert hba1c["support_state"] == "supported"
    assert hba1c["accepted_candidate"] is not None
    assert hba1c["accepted_candidate"]["candidate_code"] in {"METRIC-0063", "METRIC-0064"}


def test_analyte_resolver_prefers_exact_canonical_in_alias_collision() -> None:
    resolver = AnalyteResolver()

    resolved = resolver.resolve("Urine albumin")

    assert resolved["support_state"] == "supported"
    assert resolved["accepted_candidate"] is not None
    assert resolved["accepted_candidate"]["candidate_code"] == "METRIC-0119"


def test_analyte_resolver_empty_string() -> None:
    resolver = AnalyteResolver()

    resolved = resolver.resolve("")
    assert resolved["support_state"] == "unsupported"
    assert resolved["accepted_candidate"] is None
