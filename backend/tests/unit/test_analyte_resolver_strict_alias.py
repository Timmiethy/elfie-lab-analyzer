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
    hba1c_ngsp = resolver.resolve("HbA1c IFCC", context={"raw_unit": "%"})
    hba1c_ifcc = resolver.resolve("HbA1c IFCC", context={"raw_unit": "mmol/mol"})

    assert creatinine["support_state"] == "supported"
    assert creatinine["accepted_candidate"] is not None
    assert creatinine["accepted_candidate"]["candidate_code"] == "METRIC-0029"

    assert egfr["support_state"] == "supported"
    assert egfr["accepted_candidate"] is not None
    assert egfr["accepted_candidate"]["candidate_code"] == "METRIC-0030"

    # With explicit units the HbA1c candidates disambiguate deterministically.
    assert hba1c_ngsp["support_state"] == "supported"
    assert hba1c_ngsp["accepted_candidate"]["candidate_code"] == "METRIC-0063"
    assert hba1c_ifcc["support_state"] == "supported"
    assert hba1c_ifcc["accepted_candidate"]["candidate_code"] == "METRIC-0064"


def test_analyte_resolver_hba1c_requires_unit_disambiguation() -> None:
    """Without a unit, HbA1c is clinically ambiguous and must abstain."""

    resolver = AnalyteResolver()

    ambiguous = resolver.resolve("HbA1c")

    assert ambiguous["support_state"] == "unsupported"
    assert ambiguous["accepted_candidate"] is None
    codes = {c["candidate_code"] for c in ambiguous["candidates"]}
    assert codes == {"METRIC-0063", "METRIC-0064"}
    assert all(c["rejection_reason"] == "unit_required" for c in ambiguous["candidates"])


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


def test_analyte_resolver_keeps_single_letter_suffix_for_collision_safety() -> None:
    resolver = AnalyteResolver()

    resolved = resolver.resolve("Protein S")

    assert resolved["normalized_label"] == "protein s"
    assert resolved["support_state"] == "unsupported"


def test_analyte_resolver_returns_ambiguous_token_candidates(monkeypatch) -> None:
    resolver = AnalyteResolver()

    monkeypatch.setattr(
        "app.services.analyte_resolver._load_launch_scope_metadata",
        lambda: {
            "alias_index": {},
            "token_signature_index": {
                "alpha beta": [
                    {
                        "candidate_code": "METRIC-A",
                        "candidate_display": "Metric A",
                        "canonical_label": "metric a",
                        "threshold_used": 0.9,
                    },
                    {
                        "candidate_code": "METRIC-B",
                        "candidate_display": "Metric B",
                        "canonical_label": "metric b",
                        "threshold_used": 0.9,
                    },
                ]
            },
        },
    )

    resolved = resolver.resolve("Beta Alpha")

    assert resolved["support_state"] == "unsupported"
    assert resolved["accepted_candidate"] is None
    assert resolved["abstention_reasons"] == ["ambiguous_tokens"]
    assert {candidate["candidate_code"] for candidate in resolved["candidates"]} == {
        "METRIC-A",
        "METRIC-B",
    }
    assert all(
        candidate["rejection_reason"] == "ambiguous_tokens"
        for candidate in resolved["candidates"]
    )

