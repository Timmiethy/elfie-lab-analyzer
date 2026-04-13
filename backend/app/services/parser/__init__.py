"""Trusted PDF parser using pdfplumber for machine-generated PDFs."""

from __future__ import annotations

import re
from hashlib import sha256
from io import BytesIO
from statistics import median
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import pdfplumber

PARSER_VERSION = "trusted-pdf-v11-row-core"
_PAGE_RE = re.compile(r"^page\s*\d+(?:\s*(?:of|/)\s*\d+)?$", re.I)
_DATE_RE = re.compile(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_RANGE_RE = re.compile(r"(?:[<>]=?|≤|≥)?\s*\d[\d,]*(?:\.\d+)?\s*-\s*(?:[<>]=?|≤|≥)?\s*\d[\d,]*(?:\.\d+)?")
_NUM_RE = re.compile(r"^(?P<cmp><=|>=|<|>|≤|≥)?(?P<num>\d[\d,]*(?:\.\d+)?)(?P<suffix>[^\d\s].*)?$")
_FLAGGED_RE = re.compile(r"^(?P<flag>[A-Za-z])(?P<num>\d[\d,]*(?:\.\d+)?)(?P<suffix>[^\d\s].*)?$")
_FOOTNOTE_SUFFIX_RE = re.compile(r"^(?:[0-9]{1,2})$")
_FLAG_WORDS = {
    "high",
    "low",
    "normal",
    "abnormal",
    "h",
    "l",
    "n",
    "a",
    "hh",
    "ll",
    "critical",
    "flag",
    "normeal",
    "dnr",
    "ldnr",
    "oor",
}
_NOTE_WORDS = {"see", "note", "notes", "comment", "comments"}
_ANNOTATION_WORDS = {"calc", "calculated"}
_REFERENCE_FILLER_WORDS = {"or", "="}
_REFERENCE_ONLY_PREFIXES = ("reference range", "reference interval", "ref range", "normal range", "desirable range")
_VITALS_HINTS = (
    "height feet",
    "height inches",
    "weight",
    "blood pressure",
    "systolic",
    "diastolic",
    "body mass index",
    "calculated bmi",
    " bmi",
    "pulse",
    "heart rate",
    "respiratory rate",
    "temperature",
)
_LOCATION_HINTS = ("room ", " floor", "ward ", " flr", " flr.", " jalan ")
_UNIT_PREFIX_CANONICAL = {
    "%": "%",
    "mg/dl": "mg/dL",
    "g/dl": "g/dL",
    "mmol/l": "mmol/L",
    "umol/l": "umol/L",
    "miu/l": "mIU/L",
    "uiu/ml": "uIU/mL",
    "iu/l": "IU/L",
    "u/l": "U/L",
    "mcg/dl": "mcg/dL",
    "ng/ml": "ng/mL",
    "mg/l": "mg/L",
    "g/l": "g/L",
    "/ul": "/uL",
    "/µl": "/uL",
    "/μl": "/uL",
    "x10e3/ul": "x10E3/uL",
    "x10e6/ul": "x10E6/uL",
    "x10e9/l": "x10E9/L",
    "mm/h": "mm/h",
    "fl": "fL",
    "pg": "pg",
}
_UNIT_PREFIX_RE = re.compile(
    r"^(?P<prefix>%|mg/dl|g/dl|mmol/l|umol/l|miu/l|uiu/ml|iu/l|u/l|mcg/dl|ng/ml|mg/l|g/l|/ul|/µl|/μl|x10e3/ul|x10e6/ul|x10e9/l|mm/h|fl|pg)(?:\b|$)",
    re.I,
)

ADMIN_HINTS = (
    "ref :", "dob :", "age :", "collected :", "referred :", "report printed :",
    "date of collection", "date collected", "time of collection", "registration on", "approved on",
    "printed on", "lab no", "passport no", "sample information", "sample report",
    "client information", "patient details", "doctor details", "process at",
    "ref. id", "ref. by", "status : final", "location :", "sample type",
    "collection on", "collected on", "ward :", "name :", "specimen collected",
    "ur :", "sex/age", "icon legend", "legend :",
    # Labcorp / Quest / LabTestingAPI admin patterns
    "requisition", "received :", "reported :", "reported:", "received:",
    "copy sent to", "client #", "attn:",
    "ordering physician", "ordering provider", "ordering facility",
    "accession", "mrn :", "account no", "report status",
    "npi :", "license", "medical director", "pathologist",
    "signed by", "authorized by", "electronic signature",
    "performed by", "tested by", "analyzed by",
    "client id", "client name", "facility name",
    "report to", "send to", "address", "phone",
    "fax :", "email :", "website",
    "test date", "received date", "received on",
    "result date", "reported on", "final result",
    "specimen source", "specimen type", "specimen volume",
    "fasting status", "fasting :", "fasting state",
    "gender :", "race :", "ethnicity :",
    "patient name", "patient dob", "patient age",
    "patient id", "patient mrn", "patient account",
    "ordering date", "referring physician", "requesting doctor",
    "performing lab", "laboratory address", "lab director",
    "clia number", "cap number", "certified under clia",
    "methodology :", "instrument :", "platform :",
    "collection method", "collection time", "draw time",
    "date entered",
    # Quest / LabTestingAPI / Quest Diagnostics branding and headers
    "tcv quest diagnostics", "quest diagnostics", "labcorp", "labtestingapi",
    "nsdb testing", "this report has been prepared for", "laboratory services",
    "laboratory data", "lab results", "laboratory testing",
)
NARRATIVE_HINTS = (
    "note:", "recommend", "interpret", "guideline", "guidelines", "should be interpreted",
    "clinical presentation", "source:", "not valid for", "result should be",
    "kfre", "risk calculation", "risk estimate", "based upon", "for the purpose of screening",
    "desirable range", "higher than", "higher for people", "consistent with the",
    "therapeutic", "for patients", "for diabetic patients", "goal of", "indicates that", "may have",
    "approximate", "et al", "jama.", "jama ",
    "value between", "value of", "a value", "for someone with", "for someone who",
    "if you have", "if your", "talk to your", "see your", "discuss with",
    "this test", "this report", "this result", "these results",
    "a value between", "an a1c value",
)
THRESHOLD_HINTS = (
    "normal", "ifg", "prediabetes", "dm", "t2dm", "target range", "reference interval",
    "risk category", "biological ref", "ref. interval", "cut-off", "cut off", "optimal",
    "moderate", "high", "low", "very high", "n/a", "levels",
    "kdigo", "underweight", "overweight", "obese",
    "none seen", "not seen", "rare", "occasional", "few", "moderate", "many", "numerous",
    "squamous epithelial", "renal epithelial", "transitional epithelial",
    "hyaline casts", "granular casts", "waxy casts", "rbc casts", "wbc casts",
    "bacteria", "yeast", "crystals", "mucus", "amorphous",
)
_THRESHOLD_LABELS = {
    "normal",
    "ifg",
    "prediabetes",
    "diabetes",
    "dm",
    "t2dm",
    "glucose levels",
    "hba1c levels",
    "deficiency",
    "insufficiency",
    "sufficiency",
    "optimal",
}
_BMI_CATEGORY_LABELS = {
    "underweight",
    "overweight",
    "obese",
    "obese class i",
    "obese class ii",
    "obese class iii",
}
_TEST_REQUEST_HINTS = (
    "tests requested",
    "multiple biochem analysis",
    "albumin/creatinine ratio, multiple biochem analysis",
    "ordered items",
)
DERIVED_HINTS = (
    "egfr", "acr", "albumin creatinine ratio", "body mass index", "bmi", "fibrotest",
    "actitest", "steatotest",
)
HEADER_HINTS = (
    "laboratory report",
    "analytes results units ref. ranges",
    "page ",
    "complete blood count",
    "blood group",
    "all rights reserved",
    "enterprise report version",
    "if you have received this document in error",
)
INNOQUEST_HINTS = ("dbticbm", "dbtic1dm", "dbticcm", "dbticrp", "general screening", "special chemistry", "hba1c", "igf-1", "cortisol studies")
VALUE_WORDS = {"positive", "negative", "detected", "not detected", "reactive", "nonreactive", "normal", "abnormal", "present", "absent", "trace", "none"}
DERIVED_SOURCE_REQUIRED = {"egfr", "acr", "albumin creatinine ratio", "body mass index"}
NOISE_WORDS = {"analyte", "comment", "comments", "date", "flag", "method", "patient", "range", "reference", "report", "result", "results", "specimen", "test", "unit", "units", "value"}
UNIT_HINTS = ("mg/dl", "g/dl", "g/l", "mg/l", "mmol/l", "umol/l", "nmol/l", "pmol/l", "u/l", "iu/l", "ml/min", "kg/sqm", "/cmm", "pg", "fl", "kg", "cm", "mm", "ml", "%")


class TrustedPdfParser:
    """Trusted PDF parser using the v12 PyMuPDF-backed parser substrate.

    The public ``parse`` signature is unchanged for backwards compatibility.
    Internally it now uses BornDigitalParser + RowAssemblerV2 instead of
    pdfplumber-first extraction.  pdfplumber is still imported for debug
    helpers but is NOT used as the primary trusted extraction path.
    """

    async def parse(self, file_bytes: bytes, *, max_pages: int | None = None) -> list[dict[str, Any]]:
        return _parse_trusted_pdf_v12(file_bytes, max_pages=max_pages)


class GenericLayoutAdapter:
    family_adapter_id = "generic_layout"

    def supports_page(self, page_text: str) -> bool:
        return True


class InnoquestBilingualGeneralAdapter(GenericLayoutAdapter):
    family_adapter_id = "innoquest_bilingual_general"

    def supports_page(self, page_text: str) -> bool:
        lowered = page_text.lower()
        return bool(_CJK_RE.search(page_text) or any(hint in lowered for hint in INNOQUEST_HINTS) or "analytes results units ref. ranges" in lowered)


ADAPTERS = (InnoquestBilingualGeneralAdapter(), GenericLayoutAdapter())


def classify_candidate_text(
    raw_text: str,
    *,
    page_class: str = "unknown",
    family_adapter_id: str = "generic_layout",
) -> dict[str, Any]:
    text = _normalize_text(raw_text)
    lower = text.lower()
    if not text:
        return _classification("unparsed_row", None, "excluded", "empty_or_noise", page_class, family_adapter_id, True)
    if _is_header_footer(lower):
        return _classification("header_footer_row", None, "excluded", "header_footer_row", page_class, family_adapter_id, True)
    if _is_noise_line(text):
        return _classification("unparsed_row", None, "excluded", "empty_or_noise", page_class, family_adapter_id, True)
    if _is_admin(lower):
        return _classification("admin_metadata_row", None, "excluded", "admin_metadata_row", page_class, family_adapter_id, True)
    if _is_location_line(lower) or _is_vitals_or_body_metrics(lower):
        return _classification("admin_metadata_row", None, "excluded", "admin_metadata_row", page_class, family_adapter_id, True)
    if _is_test_request_like(text, lower):
        return _classification("test_request_row", None, "excluded", "test_request_row", page_class, family_adapter_id, True)
    if _is_narrative(text, lower):
        return _classification("narrative_guidance_row", None, "excluded", "narrative_guidance_row", page_class, family_adapter_id, True)
    if _is_threshold_measurement_label(text, lower):
        return _classification("threshold_reference_row", "reference_table", "excluded", "threshold_table_row", page_class, family_adapter_id, True)
    if _is_reference_only_line(lower):
        return _classification("threshold_reference_row", "reference_table", "excluded", "threshold_reference_row", page_class, family_adapter_id, True)
    if _is_threshold_comparator_row(text, lower):
        return _classification("threshold_reference_row", "reference_table", "excluded", "threshold_comparator_row", page_class, family_adapter_id, True)
    if _looks_like_measurement(text):
        if _is_acr_measurement(lower) or _is_reported_derived_measurement(lower):
            return _classification("measured_analyte_row", "numeric", "supported", None, page_class, family_adapter_id, False)
        if _is_derived(lower):
            # v12 wave-20: _looks_like_measurement already proved the row
            # carries a real value token.  Value-bearing derived rows are
            # supported; only label-only derived rows get the unbound penalty
            # (handled by the later _is_derived branch when
            # _looks_like_measurement returns False).
            return _classification("derived_analyte_row", "derived", "supported", None, page_class, family_adapter_id, False)
        return _classification("measured_analyte_row", "dual_unit" if _looks_dual_unit(text) else "numeric", "supported", None, page_class, family_adapter_id, False)
    if _is_threshold(text, lower):
        return _classification("threshold_reference_row", "reference_table", "excluded", "threshold_reference_row", page_class, family_adapter_id, True)
    if _is_derived(lower):
        if _is_derived_label_only(lower):
            failure = "derived_observation_unbound" if family_adapter_id in {"innoquest_bilingual_general"} or any(h in lower for h in DERIVED_SOURCE_REQUIRED) else None
            return _classification("derived_analyte_row", "derived", "partial" if failure else "supported", failure, page_class, family_adapter_id, False)
        failure = "derived_observation_unbound" if family_adapter_id in {"innoquest_bilingual_general"} or any(h in lower for h in DERIVED_SOURCE_REQUIRED) else None
        return _classification("derived_analyte_row", "derived", "partial" if failure else "supported", failure, page_class, family_adapter_id, False)
    if _looks_like_categorical(text):
        return _classification("measured_analyte_row", "categorical", "supported", None, page_class, family_adapter_id, False)
    return _classification("unparsed_row", None, "excluded", "unparsed_row", page_class, family_adapter_id, True)


def parse_numeric_token(token: str) -> tuple[float | None, dict[str, Any]]:
    normalized, locale = _normalize_numeric_string(token)
    if normalized is None:
        return None, locale
    try:
        return float(normalized), locale
    except ValueError:
        return None, locale


def parse_measurement_text(
    raw_text: str,
    *,
    page_class: str = "unknown",
    family_adapter_id: str = "generic_layout",
    source_kind: str = "text",
    page_number: int = 1,
    block_id: str | None = None,
    segment_index: int = 0,
    source_bounds: dict[str, float] | None = None,
) -> dict[str, Any]:
    classification = classify_candidate_text(raw_text, page_class=page_class, family_adapter_id=family_adapter_id)
    return _parse_candidate_payload(
        raw_text,
        classification=classification,
        source_kind=source_kind,
        page_number=page_number,
        block_id=block_id or f"page-{page_number}:block-{segment_index:03d}",
        segment_index=segment_index,
        source_bounds=source_bounds,
    )


def _parse_measurement_text(
    raw_text: str,
    *,
    page_class: str = "unknown",
    family_adapter_id: str = "generic_layout",
    source_kind: str = "text",
    page_number: int = 1,
    block_id: str | None = None,
    segment_index: int = 0,
    source_bounds: dict[str, float] | None = None,
) -> dict[str, Any]:
    return parse_measurement_text(
        raw_text,
        page_class=page_class,
        family_adapter_id=family_adapter_id,
        source_kind=source_kind,
        page_number=page_number,
        block_id=block_id,
        segment_index=segment_index,
        source_bounds=source_bounds,
    )


def _parse_trusted_pdf(file_bytes: bytes, *, max_pages: int | None = None) -> list[dict[str, Any]]:
    if not file_bytes:
        raise ValueError("unsupported_pdf: empty input")

    checksum = sha256(file_bytes).hexdigest()
    document_id = uuid5(NAMESPACE_URL, f"trusted-pdf:{checksum}")
    rows: list[dict[str, Any]] = []
    seen_rows: set[str] = set()
    saw_text = False

    try:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            if not pdf.pages:
                raise ValueError("unsupported_pdf: empty PDF")
            if max_pages is not None and len(pdf.pages) > max_pages:
                raise ValueError(f"page_count_limit_exceeded:{len(pdf.pages)}>{max_pages}")

            for page_number, page in enumerate(pdf.pages, start=1):
                page_rows, has_text = _extract_page_rows(page, page_number=page_number)
                saw_text = saw_text or has_text
                for row in page_rows:
                    row_hash = sha256(
                        f"{page_number}:{row['row_type']}:{row['raw_text']}".encode("utf-8")
                    ).hexdigest()
                    if row_hash in seen_rows:
                        continue
                    seen_rows.add(row_hash)
                    rows.append(_materialize_row(row, document_id=document_id, checksum=checksum, page_number=page_number))
    except ValueError:
        raise
    except Exception as exc:  # pragma: no cover
        raise ValueError("unsupported_pdf: unable to open or read PDF") from exc

    if rows:
        return rows
    if not saw_text:
        raise ValueError("unsupported_pdf: no embedded text found")
    raise ValueError("unsupported_pdf: no parsable rows found")


def _extract_page_rows(page: Any, *, page_number: int) -> tuple[list[dict[str, Any]], bool]:
    text = _safe_extract_text(page)
    words = _safe_extract_words(page)
    tables = _safe_extract_tables(page)
    page_class = _classify_page(text, words, tables)
    adapter = _select_adapter(text)
    rows: list[dict[str, Any]] = []
    has_text = bool(text or words or tables)

    for source_kind, raw_text, bounds, block_id, segment_index in _iter_candidates(text, words, tables, page_number=page_number, page_class=page_class, adapter=adapter):
        rows.append(
            _parse_measurement_text(
                raw_text,
                page_class=page_class,
                family_adapter_id=adapter.family_adapter_id,
                source_kind=source_kind,
                page_number=page_number,
                block_id=block_id,
                segment_index=segment_index,
                source_bounds=bounds,
            )
        )

    return rows, has_text


def _iter_candidates(
    text: str,
    words: list[dict[str, Any]],
    tables: list[list[list[str | None]]],
    *,
    page_number: int,
    page_class: str,
    adapter: GenericLayoutAdapter,
):
    if words:
        for band_index, band in enumerate(_cluster_words(words), start=1):
            for segment_index, segment in enumerate(_split_band(band["words"]), start=1):
                raw_text = _normalize_text(" ".join(word["text"] for word in segment["words"]))
                if raw_text:
                    yield "geometry", raw_text, segment["bounds"], f"page-{page_number}:band-{band_index:03d}", segment_index
    if tables:
        for table_index, table in enumerate(tables, start=1):
            for row_index, row in enumerate(table, start=1):
                raw_text = _join_texts(*[cell for cell in row if cell])
                if raw_text:
                    yield "table", raw_text, None, f"page-{page_number}:table-{table_index:03d}", row_index
    if text:
        pending_label: str | None = None
        for line_index, raw_line in enumerate(text.splitlines(), start=1):
            line = _normalize_text(raw_line)
            if not line or _is_noise_line(line):
                pending_label = None
                continue
            candidate = parse_measurement_text(line, page_class=page_class, family_adapter_id=adapter.family_adapter_id, source_kind="text", page_number=page_number, block_id=f"page-{page_number}:line-{line_index:03d}", segment_index=1)
            if candidate["row_type"] != "unparsed_row":
                yield "text", line, None, f"page-{page_number}:line-{line_index:03d}", 1
                pending_label = None
                continue
            if pending_label is not None:
                merged = _normalize_text(f"{pending_label} {line}")
                merged_candidate = parse_measurement_text(merged, page_class=page_class, family_adapter_id=adapter.family_adapter_id, source_kind="text", page_number=page_number, block_id=f"page-{page_number}:line-{line_index:03d}", segment_index=1)
                if merged_candidate["row_type"] != "unparsed_row":
                    yield "text", merged, None, f"page-{page_number}:line-{line_index:03d}", 1
                    pending_label = None
                    continue
            pending_label = None if _contains_value_token(line) else _join_texts(pending_label, line)


def _parse_candidate_payload(
    raw_text: str,
    *,
    classification: dict[str, Any],
    source_kind: str,
    page_number: int,
    block_id: str,
    segment_index: int,
    source_bounds: dict[str, float] | None,
) -> dict[str, Any]:
    text = _normalize_text(raw_text)
    fields = _parse_value_fields(text, row_type=classification["row_type"])
    failure_code = classification["failure_code"]
    support_code = classification["support_code"]
    source_observation_ids = fields["source_observation_ids"]
    if classification["row_type"] == "derived_analyte_row" and not source_observation_ids:
        # v12 wave-20: if the classifier already set failure_code=None and
        # support_code="supported" (meaning the row is value-bearing), do not
        # downgrade it to partial.  Only apply the unbound fallback when the
        # classifier itself flagged the row as unbound.
        if classification["failure_code"] is None:
            # The classifier decided this derived row is supported (value-bearing).
            # Keep the classifier's decision.
            pass
        else:
            failure_code = failure_code or "derived_observation_unbound"
            support_code = "partial"

    return {
        "parser_version": PARSER_VERSION,
        "raw_text": text,
        "raw_analyte_label": fields["raw_analyte_label"],
        "raw_value_string": fields["raw_value_string"],
        "raw_unit_string": fields["raw_unit_string"],
        "raw_reference_range": fields["raw_reference_range"],
        "parsed_numeric_value": fields["parsed_numeric_value"],
        "parsed_locale": fields["parsed_locale"],
        "parsed_comparator": fields["parsed_comparator"],
        "row_type": classification["row_type"],
        "measurement_kind": classification["measurement_kind"],
        "support_code": support_code,
        "failure_code": failure_code,
        "family_adapter_id": classification["family_adapter_id"],
        "page_class": classification["page_class"],
        "source_kind": source_kind,
        "block_id": block_id,
        "source_bounds": source_bounds,
        "candidate_trace": {
            "page_number": page_number,
            "block_id": block_id,
            "segment_index": segment_index,
            "page_class": classification["page_class"],
            "family_adapter_id": classification["family_adapter_id"],
            "source_kind": source_kind,
        },
        "source_observation_ids": source_observation_ids,
        "secondary_result": fields["secondary_result"],
        "extraction_confidence": fields["extraction_confidence"],
    }


def _parse_value_fields(raw_text: str, *, row_type: str) -> dict[str, Any]:
    if row_type in {"header_footer_row", "admin_metadata_row", "narrative_guidance_row", "threshold_reference_row"}:
        return {
            "raw_analyte_label": _label_from_text(raw_text),
            "raw_value_string": None,
            "raw_unit_string": None,
            "raw_reference_range": _extract_reference_range(raw_text),
            "parsed_numeric_value": None,
            "parsed_locale": {"decimal_separator": None, "thousands_separator": None, "normalized": None},
            "parsed_comparator": None,
            "secondary_result": None,
            "source_observation_ids": [],
            "extraction_confidence": 0.0,
        }

    tokens = raw_text.split()
    index, raw_value_string, parsed_numeric_value, comparator, locale = _locate_value_token(tokens)
    if index is None or raw_value_string is None:
        return _parse_categorical_value_fields(tokens, raw_text)

    label = _normalize_label_tokens(tokens[:index]) or _label_from_text(raw_text)
    tail_start = index + 1
    if (
        comparator is not None
        and index < len(tokens)
        and tokens[index] in {"<", ">", "<=", ">=", "≤", "≥"}
    ):
        tail_start = index + 2
    tail = tokens[tail_start:]
    raw_unit_string, raw_reference_range, secondary_result = _split_measurement_tail(tail)
    if raw_unit_string is None:
        raw_unit_string = _infer_inline_unit(raw_value_string)
    if not raw_reference_range:
        raw_reference_range = _extract_reference_range(raw_text)
    return {
        "raw_analyte_label": label,
        "raw_value_string": raw_value_string,
        "raw_unit_string": raw_unit_string,
        "raw_reference_range": raw_reference_range,
        "parsed_numeric_value": parsed_numeric_value,
        "parsed_locale": locale,
        "parsed_comparator": comparator,
        "secondary_result": secondary_result,
        "source_observation_ids": [],
        "extraction_confidence": 0.98,
    }


def _parse_categorical_value_fields(tokens: list[str], raw_text: str) -> dict[str, Any]:
    label = _normalize_text(" ".join(tokens[:-1])) if len(tokens) > 1 else _normalize_text(tokens[0] if tokens else "")
    return {
        "raw_analyte_label": label or _label_from_text(raw_text),
        "raw_value_string": _normalize_text(tokens[-1]) if tokens else None,
        "raw_unit_string": _normalize_text(" ".join(tokens[1:])) if len(tokens) > 1 else None,
        "raw_reference_range": _extract_reference_range(raw_text),
        "parsed_numeric_value": None,
        "parsed_locale": {"decimal_separator": None, "thousands_separator": None, "normalized": None},
        "parsed_comparator": None,
        "secondary_result": None,
        "source_observation_ids": [],
        "extraction_confidence": 0.84,
    }


def _split_measurement_tail(tokens: list[str]) -> tuple[str | None, str | None, dict[str, Any] | None]:
    if not tokens:
        return None, None, None
    unit_tokens: list[str] = []
    reference_tokens: list[str] = []
    secondary: dict[str, Any] | None = None
    for idx, token in enumerate(tokens):
        clean = _clean_token(token)
        if not clean:
            continue
        if _starts_note_expression(tokens, idx):
            break
        if _is_annotation_token(clean) or _is_flag_token(clean):
            continue
        if _is_reference_token(clean) or _starts_reference_expression(tokens, idx):
            reference_tokens = tokens[idx:]
            break
        if secondary is None and _looks_like_secondary_value(tokens, idx):
            value, locale = parse_numeric_token(clean)
            if value is not None:
                secondary = {
                    "raw_value_string": clean,
                    "parsed_numeric_value": value,
                    "raw_unit_string": None,
                    "parsed_locale": locale,
                }
                continue
        if secondary is not None and secondary["raw_unit_string"] is None and _looks_like_unit_token(clean):
            secondary["raw_unit_string"] = _normalize_text(clean)
            continue
        if _looks_like_unit_token(clean):
            unit_tokens.append(clean)
            continue
        unit_tokens.append(token)
    raw_unit_string = _normalize_measurement_unit_string(_normalize_text(" ".join(unit_tokens)) or None)
    if raw_unit_string is None and reference_tokens:
        raw_unit_string = _normalize_measurement_unit_string(_extract_unit_from_reference_tokens(reference_tokens))
    reference_range = _normalize_reference_range(reference_tokens)
    if secondary is not None and secondary.get("raw_unit_string") is None:
        secondary = None
    return raw_unit_string, reference_range, secondary


def _locate_value_token(tokens: list[str]) -> tuple[int | None, str | None, float | None, str | None, dict[str, Any]]:
    candidates: list[tuple[int, str, float, str | None, dict[str, Any]]] = []
    empty_locale = {
        "decimal_separator": None,
        "thousands_separator": None,
        "normalized": None,
    }

    for idx, token in enumerate(tokens):
        parsed = _split_value_token(token)
        if parsed[0] is not None and parsed[1] is not None:
            candidates.append((idx, parsed[0], parsed[1], parsed[2], parsed[3]))
        if token in {"<", ">", "<=", ">=", "≤", "≥"} and idx + 1 < len(tokens):
            parsed = _split_value_token(f"{token}{tokens[idx + 1]}")
            if parsed[0] is not None and parsed[1] is not None:
                candidates.append((idx, parsed[0], parsed[1], parsed[2], parsed[3]))

    if not candidates:
        return None, None, None, None, empty_locale

    inline_unit_candidates = [
        candidate for candidate in candidates if _infer_inline_unit(candidate[1]) is not None
    ]
    if inline_unit_candidates:
        return min(inline_unit_candidates, key=lambda candidate: candidate[0])

    def candidate_score(
        candidate: tuple[int, str, float, str | None, dict[str, Any]],
    ) -> tuple[int, int]:
        idx, raw_value_string, _, comparator, _ = candidate
        score = 0
        plain_numeric_before = any(
            other_idx < idx
            and other_comparator is None
            and not re.fullmatch(r"0\d+", _clean_token(other_value))
            for other_idx, other_value, _, other_comparator, _ in candidates
        )
        if _infer_inline_unit(raw_value_string):
            score += 6
        if re.fullmatch(r"0\d+", _clean_token(raw_value_string)):
            score -= 4
        if comparator is not None:
            score += 1
            if plain_numeric_before:
                score -= 7
            else:
                score += 5
        if idx > 0 and _starts_reference_expression(tokens, idx) and plain_numeric_before:
            score -= 4

        next_idx = idx + 1
        if comparator is not None and idx < len(tokens) and tokens[idx] in {"<", ">", "<=", ">=", "≤", "≥"}:
            next_idx = idx + 2
        saw_later_value = False
        while next_idx < len(tokens):
            clean = _clean_token(tokens[next_idx])
            if not clean:
                next_idx += 1
                continue
            if _starts_note_expression(tokens, next_idx):
                break
            if _is_annotation_token(clean):
                next_idx += 1
                continue
            if _is_flag_token(clean):
                score += 1
                next_idx += 1
                continue
            if _starts_reference_expression(tokens, next_idx):
                score += 6
                break
            parsed = _split_value_token(clean)
            if parsed[0] is not None:
                saw_later_value = True
                break
            if _looks_like_unit_token(clean):
                score += 5
                break
            next_idx += 1

        if saw_later_value:
            score -= 3
        if "." in raw_value_string or "," in raw_value_string:
            score += 1
        return score, idx

    best = max(candidates, key=candidate_score)
    return best


def _split_value_token(token: str) -> tuple[str | None, float | None, str | None, dict[str, Any]]:
    clean = _clean_token(token)
    if not clean or re.search(r"\d[\d,]*(?:\.\d+)?\s*-\s*\d[\d,]*(?:\.\d+)?", clean):
        return None, None, None, {"decimal_separator": None, "thousands_separator": None, "normalized": None}
    if _looks_like_unit_token(clean) and not re.match(r"^(?:<=|>=|<|>|≤|≥)?\d", clean):
        return None, None, None, {"decimal_separator": None, "thousands_separator": None, "normalized": None}
    flagged = _FLAGGED_RE.match(clean)
    if flagged and flagged.group("flag").upper() in {"H", "L", "A"}:
        suffix = flagged.group("suffix") or ""
        if suffix and re.match(r"^[A-Za-z]", suffix):
            return None, None, None, {"decimal_separator": None, "thousands_separator": None, "normalized": None}
        normalized, locale = _normalize_numeric_string(flagged.group("num"))
        return (clean, float(normalized), flagged.group("flag"), locale) if normalized is not None else (None, None, None, locale)
    match = _NUM_RE.match(clean)
    if not match:
        return None, None, None, {"decimal_separator": None, "thousands_separator": None, "normalized": None}
    normalized, locale = _normalize_numeric_string(match.group("num"))
    return (clean, float(normalized), match.group("cmp"), locale) if normalized is not None else (None, None, None, locale)


def _normalize_numeric_string(value: str) -> tuple[str | None, dict[str, Any]]:
    cleaned = _normalize_text(value).replace(" ", "").replace("'", "")
    locale = {"decimal_separator": None, "thousands_separator": None, "normalized": cleaned or None}
    if not cleaned:
        return None, locale
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            locale.update({"decimal_separator": ",", "thousands_separator": "."})
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            locale.update({"decimal_separator": ".", "thousands_separator": ","})
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        left, right = cleaned.rsplit(",", 1)
        if len(right) == 3 and left.isdigit():
            locale["thousands_separator"] = ","
            cleaned = left + right
        else:
            locale["decimal_separator"] = ","
            cleaned = cleaned.replace(",", ".")
    elif "." in cleaned:
        left, right = cleaned.rsplit(".", 1)
        if len(right) == 3 and left.isdigit():
            locale["thousands_separator"] = "."
            cleaned = left + right
        else:
            locale["decimal_separator"] = "."
    try:
        float(cleaned)
    except ValueError:
        return None, locale
    locale["normalized"] = cleaned
    return cleaned, locale


def _extract_reference_range(text: str) -> str | None:
    matches = [
        _normalize_text(match.group(0)).strip("()")
        for match in re.finditer(r"(?:[<>]=?|≤|≥)\s*\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s*-\s*\d[\d,]*(?:\.\d+)?", text)
    ]
    if not matches:
        return None
    return matches[-1]


def _is_reference_token(token: str) -> bool:
    cleaned = _clean_token(token)
    return bool(
        re.match(r"^(?:[<>]=?|≤|≥)\s*\d", cleaned)
        or re.search(r"\d[\d,]*(?:\.\d+)?\s*-\s*\d[\d,]*(?:\.\d+)?", cleaned)
    )


def _classify_page(text: str, words: list[dict[str, Any]], tables: list[list[list[str | None]]]) -> str:
    lower = text.lower()
    if any(hint in lower for hint in HEADER_HINTS) and not _contains_analyte_signals(lower, words, tables):
        return "header_footer_page"
    if any(hint in lower for hint in THRESHOLD_HINTS) and _count_ranges(lower) >= 2:
        return "threshold_page"
    if any(hint in lower for hint in NARRATIVE_HINTS):
        return "narrative_page"
    if _CJK_RE.search(text) or any(hint in lower for hint in INNOQUEST_HINTS):
        return "analyte_table_page"
    if _contains_analyte_signals(lower, words, tables):
        return "mixed_page"
    return "admin_page"


def _contains_analyte_signals(lower: str, words: list[dict[str, Any]], tables: list[list[list[str | None]]]) -> bool:
    analyte_words = ("analyte", "result", "reference", "hba1c", "glucose", "hemoglobin", "cholesterol", "creatinine", "urea", "sodium", "potassium", "wbc", "platelet")
    if any(word in lower for word in analyte_words):
        return True
    if len(words) > 20:
        return True
    table_text = " ".join(_normalize_text(cell or "") for table in tables for row in table for cell in row).lower()
    return any(word in table_text for word in analyte_words)


def _is_header_footer(lower: str) -> bool:
    return lower.startswith("page ") or lower.startswith("laboratory report") or any(hint in lower for hint in HEADER_HINTS)


def _is_noise_line(text: str) -> bool:
    lower = text.lower().strip()
    if not lower:
        return True
    if _PAGE_RE.match(lower) or lower in {"reference range", "test result", "result units"}:
        return True
    tokens = {re.sub(r"[^\w%/.-]", "", token.lower()) for token in lower.split()}
    tokens = {token for token in tokens if token}
    return bool(tokens and tokens <= NOISE_WORDS)


def _is_admin(lower: str) -> bool:
    normalized = lower.replace(" :", ":").replace(": ", ":")
    return _looks_like_date_or_time(lower) or any(
        hint in lower or hint.replace(" :", ":").replace(": ", ":") in normalized
        for hint in ADMIN_HINTS
    )


def _is_narrative(text: str, lower: str) -> bool:
    if any(hint in lower for hint in NARRATIVE_HINTS):
        return True
    if lower.startswith("code "):
        return True
    if lower.startswith("note ") or lower.startswith("see note "):
        return True
    if _contains_value_token(text):
        return False
    return len(lower.split()) >= 7 and lower.endswith((".", ")"))


def _is_threshold(text: str, lower: str) -> bool:
    if _count_ranges(lower) >= 2:
        return True
    if any(hint in lower for hint in THRESHOLD_HINTS):
        return True
    return bool(re.search(r"\b[a-d]:\s", lower) or "reference interval" in lower or "biological ref. interval" in lower)


def _is_derived(lower: str) -> bool:
    return any(hint in lower for hint in DERIVED_HINTS)


def _is_test_request_like(text: str, lower: str) -> bool:
    if any(hint in lower for hint in _TEST_REQUEST_HINTS):
        return True
    return text.count(",") >= 2 and "analysis" in lower


def _is_reference_only_line(lower: str) -> bool:
    if any(lower.startswith(prefix) for prefix in _REFERENCE_ONLY_PREFIXES):
        return True
    return bool(re.search(r"\b[a-d]:\s", lower))


def _is_vitals_or_body_metrics(lower: str) -> bool:
    # v12: word-boundary matching so hints like "weight" do not match inside
    # BMI category labels like "overweight", allowing those rows to reach
    # threshold_reference_row classification instead of admin_metadata_row.
    if any(re.search(r"\b" + re.escape(hint) + r"\b", lower) for hint in _VITALS_HINTS):
        return True
    if re.search(r"\bheight\b", lower) and re.search(r"\bweight\b", lower):
        return True
    if re.match(r"^bp\b", lower):
        return True
    return False


def _is_location_line(lower: str) -> bool:
    if "date entered" in lower:
        return True
    if "room" in lower and "floor" in lower:
        return True
    return any(hint in lower for hint in _LOCATION_HINTS) and any(ch.isdigit() for ch in lower)


def _is_threshold_measurement_label(text: str, lower: str) -> bool:
    if any(lower.startswith(label) for label in _THRESHOLD_LABELS) and (
        _count_ranges(lower) >= 1
        or any(hint in lower for hint in UNIT_HINTS)
        or any(ch.isdigit() for ch in lower)
    ):
        return True
    if any(lower.startswith(label) for label in _BMI_CATEGORY_LABELS) and (
        _count_ranges(lower) >= 1
        or any(ch.isdigit() for ch in lower)
        or any(symbol in lower for symbol in {"<", ">", "≤", "≥"})
    ):
        return True
    tokens = text.split()
    index, raw_value_string, _, _, _ = _locate_value_token(tokens)
    if index is None or raw_value_string is None or index == 0:
        return False
    label = " ".join(_clean_token(token).lower() for token in tokens[:index]).strip()
    return label in _THRESHOLD_LABELS


def _is_threshold_comparator_row(text: str, lower: str) -> bool:
    """v12: Catch threshold/risk-table rows with comparators before measurement classification.

    Rows like "Intermediate", "Moderate CV Risk <2.6", "Very High CV Risk <=1.4"
    contain comparators or numeric cutoffs that make ``_looks_like_measurement``
    return True, causing them to leak as measured_analyte_row or unit_parse_fail.

    This function detects the combination of threshold/risk keywords with
    comparator symbols or cutoff-like numeric suffixes.
    """
    if any(ch in text for ch in "<>≤≥"):
        # Has a comparator symbol - check if the text carries risk/threshold
        # vocabulary rather than a real analyte measurement.
        if any(hint in lower for hint in ("risk", "cv risk", "cut off", "atherogenic")):
            return True
        if any(hint in lower for hint in ("intermediate", "recurrent cv events", "biochem", "aip")):
            return True
    # Label-only threshold rows that are standalone category names
    standalone_categories = {"intermediate", "low", "high", "very high", "very low", "borderline",
                             "atherogenic low", "atherogenic high"}
    tokens = lower.split()
    if lower.strip() in standalone_categories:
        return True
    # Multi-word risk categories without comparators but with threshold semantics
    if "cv risk" in lower or "cardiovascular risk" in lower:
        return True
    if any(hint in lower for hint in ("cut off low", "cut off high", "risk cut off")):
        return True
    return False


def _looks_like_measurement(text: str) -> bool:
    lower = text.lower()
    if _is_admin(lower) or _is_narrative(text, lower) or _is_reference_only_line(lower):
        return False
    tokens = text.split()
    if not tokens or re.match(r"^[\d<>=≤≥]", tokens[0]):
        return False
    index, raw_value_string, _, _, _ = _locate_value_token(tokens)
    if index is None or raw_value_string is None or index == 0:
        return False
    if "%" in raw_value_string or any(ch in raw_value_string for ch in "<>≤≥"):
        return True
    tail = tokens[index + 1 :]
    if not tail:
        return False
    if any(_is_reference_token(token) for token in tail):
        return True
    if any("/" in token or "%" in token or any(hint in token.lower() for hint in UNIT_HINTS) for token in tail):
        return True
    compact_tail = [_clean_token(token) for token in tail[:2] if _clean_token(token)]
    clean_value = _clean_token(raw_value_string)
    if (
        len(tail) <= 2
        and compact_tail
        and not re.fullmatch(r"(19|20)\d{2}", clean_value)
        and all(re.fullmatch(r"[A-Za-z][A-Za-z0-9._%-]{0,3}", token) for token in compact_tail)
    ):
        return True
    return False


def _looks_dual_unit(text: str) -> bool:
    lower = text.lower()
    return bool(re.search(r"\d+\s*%\s*\d", lower) or re.search(r"\b\d+(?:\.\d+)?\s+mmol/mol\b", lower))


def _looks_like_categorical(text: str) -> bool:
    lower = text.lower()
    return not _looks_like_measurement(text) and not _is_admin(lower) and not _is_narrative(text, lower) and any(word in lower for word in VALUE_WORDS)


def _looks_like_date_or_time(text: str) -> bool:
    return bool(_DATE_RE.match(text) or _TIME_RE.match(text))


def _count_ranges(text: str) -> int:
    return len(_RANGE_RE.findall(text)) + sum(1 for token in text.split() if token in {"<", ">", "<=", ">=", "≤", "≥"})


def _clean_token(token: str) -> str:
    return token.strip().strip(",;:").strip("()[]{}")


def _normalize_label_tokens(tokens: list[str]) -> str:
    cleaned_tokens = [_clean_token(token) for token in tokens if _clean_token(token)]
    while cleaned_tokens and _FOOTNOTE_SUFFIX_RE.fullmatch(cleaned_tokens[-1]):
        cleaned_tokens.pop()
    return _normalize_text(" ".join(cleaned_tokens))


def _infer_inline_unit(raw_value_string: str | None) -> str | None:
    if raw_value_string is None:
        return None
    if raw_value_string.endswith("%"):
        return "%"
    return None


def _starts_reference_expression(tokens: list[str], index: int) -> bool:
    clean = _clean_token(tokens[index])
    if _is_reference_token(clean):
        return True
    if clean in {"<", ">", "<=", ">=", "≤", "≥"} and index + 1 < len(tokens):
        next_idx = index + 1
        while next_idx < len(tokens):
            next_clean = _clean_token(tokens[next_idx]).lower()
            if not next_clean:
                next_idx += 1
                continue
            if next_clean in _REFERENCE_FILLER_WORDS:
                next_idx += 1
                continue
            return parse_numeric_token(next_clean)[0] is not None
    if parse_numeric_token(clean)[0] is not None and index + 2 < len(tokens):
        middle = _clean_token(tokens[index + 1])
        next_clean = _clean_token(tokens[index + 2])
        if middle in {"-", "–", "to"} and parse_numeric_token(next_clean)[0] is not None:
            return True
    if parse_numeric_token(clean)[0] is not None and index + 1 < len(tokens):
        next_clean = _clean_token(tokens[index + 1])
        if next_clean.startswith("-") and parse_numeric_token(next_clean[1:])[0] is not None:
            return True
    return False


def _looks_like_unit_token(token: str) -> bool:
    lower = _clean_token(token).lower()
    if not lower:
        return False
    if "/" in lower or "%" in lower:
        return True
    return any(hint in lower for hint in UNIT_HINTS)


def _is_flag_token(token: str) -> bool:
    clean = _clean_token(token).lower().rstrip(".:")
    if clean in _FLAG_WORDS:
        return True
    return any(clean.endswith(word) and len(clean) - len(word) <= 2 for word in {"high", "low", "normal", "abnormal"})


def _is_annotation_token(token: str) -> bool:
    return _clean_token(token).lower().rstrip(".") in _ANNOTATION_WORDS


def _starts_note_expression(tokens: list[str], index: int) -> bool:
    clean = _clean_token(tokens[index]).lower().rstrip(".:")
    if clean in _NOTE_WORDS:
        return True
    if clean == "see" and index + 1 < len(tokens):
        next_clean = _clean_token(tokens[index + 1]).lower().rstrip(".:")
        return next_clean.startswith("note")
    return clean.startswith("note")


def _looks_like_secondary_value(tokens: list[str], index: int) -> bool:
    clean = _clean_token(tokens[index])
    value, _ = parse_numeric_token(clean)
    if value is None or index + 1 >= len(tokens):
        return False
    next_clean = _clean_token(tokens[index + 1])
    return bool(next_clean) and _looks_like_unit_token(next_clean)


def _extract_unit_from_reference_tokens(tokens: list[str]) -> str | None:
    seen_reference_value = False
    for idx, token in enumerate(tokens):
        clean = _clean_token(token)
        if not clean:
            continue
        if _starts_note_expression(tokens, idx):
            break
        if _is_annotation_token(clean) or _is_flag_token(clean):
            continue
        if (
            not seen_reference_value
            and (
                clean in {"<", ">", "<=", ">=", "≤", "≥"}
                or parse_numeric_token(clean)[0] is not None
                or _is_reference_token(clean)
            )
        ):
            seen_reference_value = True
            continue
        if seen_reference_value and _looks_like_unit_token(clean):
            return _normalize_text(clean)
    return None


def _normalize_measurement_unit_string(raw_unit_string: str | None) -> str | None:
    normalized = _normalize_text(raw_unit_string)
    if not normalized:
        return None
    tokens = normalized.split()
    while tokens and _FOOTNOTE_SUFFIX_RE.fullmatch(tokens[-1]):
        tokens.pop()
    if not tokens:
        return None
    normalized = " ".join(tokens)
    lower = normalized.lower()
    if lower in {"normal", "normeal", "abnormal", "dnr", "ldnr", "oor"}:
        return None
    if lower.startswith("% not estab"):
        return "%"
    if lower in {"% o", "% 0"}:
        return "%"
    match = _UNIT_PREFIX_RE.match(lower)
    if match:
        return _UNIT_PREFIX_CANONICAL[match.group("prefix").lower()]
    return normalized


def _normalize_reference_range(tokens: list[str]) -> str | None:
    if not tokens:
        return None
    trimmed_tokens: list[str] = []
    for idx, token in enumerate(tokens):
        clean = _clean_token(token)
        if not clean:
            continue
        if _starts_note_expression(tokens, idx):
            break
        if _is_annotation_token(clean):
            continue
        trimmed_tokens.append(clean)
    while trimmed_tokens and _FOOTNOTE_SUFFIX_RE.fullmatch(trimmed_tokens[-1]):
        trimmed_tokens.pop()
    return _normalize_text(" ".join(trimmed_tokens)).strip("()") or None


def _is_acr_measurement(lower: str) -> bool:
    return "acr" in lower or "albumin/creatinine ratio" in lower


def _is_reported_derived_measurement(lower: str) -> bool:
    return "egfr" in lower


def _is_derived_label_only(lower: str) -> bool:
    return lower in {"egfr", "e-gfr", "estimated glomerular filtration rate"}


def _contains_value_token(text: str) -> bool:
    tokens = _normalize_text(text).split()
    return _locate_value_token(tokens)[0] is not None


def _select_adapter(text: str) -> GenericLayoutAdapter:
    for adapter in ADAPTERS:
        if adapter.supports_page(text):
            return adapter
    return ADAPTERS[-1]


def _safe_extract_tables(page: Any) -> list[list[list[str | None]]]:
    try:
        tables = page.extract_tables() or []
    except Exception:
        return []
    normalized: list[list[list[str | None]]] = []
    for table in tables:
        if not table:
            continue
        rows: list[list[str | None]] = []
        for row in table:
            if not row:
                continue
            normalized_row = [None if cell is None else _normalize_text(str(cell)) for cell in row]
            if any(normalized_row):
                rows.append(normalized_row)
        if rows:
            normalized.append(rows)
    return normalized


def _safe_extract_text(page: Any) -> str:
    try:
        text = page.extract_text() or ""
    except Exception:
        return ""
    return "\n".join(
        line
        for line in (_normalize_text(raw_line) for raw_line in str(text).splitlines())
        if line
    )


def _safe_extract_words(page: Any) -> list[dict[str, Any]]:
    try:
        words = page.extract_words() or []
    except Exception:
        return []
    normalized: list[dict[str, Any]] = []
    for word in words:
        text = _normalize_text(str(word.get("text") or ""))
        if text:
            normalized.append({"text": text, "x0": float(word.get("x0") or 0.0), "x1": float(word.get("x1") or 0.0), "top": float(word.get("top") or 0.0), "bottom": float(word.get("bottom") or 0.0)})
    return normalized


def _cluster_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(words, key=lambda word: (word["top"], word["x0"]))
    bands: list[list[dict[str, Any]]] = []
    band: list[dict[str, Any]] = [ordered[0]]
    current_top = ordered[0]["top"]
    for word in ordered[1:]:
        if abs(word["top"] - current_top) <= 3.0:
            band.append(word)
            current_top = median([current_top, word["top"]])
        else:
            bands.append(band)
            band = [word]
            current_top = word["top"]
    bands.append(band)
    return [{"words": band, "bounds": {"x0": min(w["x0"] for w in band), "x1": max(w["x1"] for w in band), "top": min(w["top"] for w in band), "bottom": max(w["bottom"] for w in band)}} for band in bands]


def _split_band(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not words:
        return []
    ordered = sorted(words, key=lambda word: word["x0"])
    widths = [max(1.0, word["x1"] - word["x0"]) for word in ordered]
    split_gap = max(28.0, (median(widths) if widths else 12.0) * 4.5)
    segments: list[list[dict[str, Any]]] = []
    segment = [ordered[0]]
    prev = ordered[0]
    for word in ordered[1:]:
        if word["x0"] - prev["x1"] > split_gap:
            segments.append(segment)
            segment = [word]
        else:
            segment.append(word)
        prev = word
    segments.append(segment)
    return [{"words": segment, "bounds": {"x0": min(w["x0"] for w in segment), "x1": max(w["x1"] for w in segment), "top": min(w["top"] for w in segment), "bottom": max(w["bottom"] for w in segment)}} for segment in segments]


def _materialize_row(parsed_row: dict[str, Any], *, document_id: UUID, checksum: str, page_number: int) -> dict[str, Any]:
    row_hash = sha256(
        f"{checksum}:{page_number}:{parsed_row['row_type']}:{parsed_row['raw_text']}".encode("utf-8")
    ).hexdigest()
    return {
        "parser_version": PARSER_VERSION,
        "document_id": document_id,
        "source_page": page_number,
        "block_id": parsed_row["block_id"],
        "row_hash": row_hash,
        "raw_text": parsed_row["raw_text"],
        "raw_analyte_label": parsed_row["raw_analyte_label"],
        "raw_value_string": parsed_row["raw_value_string"],
        "raw_unit_string": parsed_row["raw_unit_string"],
        "raw_reference_range": parsed_row["raw_reference_range"],
        "parsed_numeric_value": parsed_row["parsed_numeric_value"],
        "parsed_locale": parsed_row["parsed_locale"],
        "parsed_comparator": parsed_row["parsed_comparator"],
        "row_type": parsed_row["row_type"],
        "measurement_kind": parsed_row["measurement_kind"],
        "support_code": parsed_row["support_code"],
        "failure_code": parsed_row["failure_code"],
        "family_adapter_id": parsed_row["family_adapter_id"],
        "page_class": parsed_row["page_class"],
        "source_kind": parsed_row["source_kind"],
        "source_bounds": parsed_row["source_bounds"],
        "candidate_trace": parsed_row["candidate_trace"],
        "source_observation_ids": parsed_row["source_observation_ids"],
        "secondary_result": parsed_row["secondary_result"],
        "extraction_confidence": parsed_row["extraction_confidence"],
    }


def _classification(row_type: str, measurement_kind: str | None, support_code: str, failure_code: str | None, page_class: str, family_adapter_id: str, is_excluded: bool) -> dict[str, Any]:
    return {"row_type": row_type, "measurement_kind": measurement_kind, "support_code": support_code, "failure_code": failure_code, "page_class": page_class, "family_adapter_id": family_adapter_id, "is_excluded": is_excluded}


def _label_from_text(raw_text: str) -> str:
    tokens = _normalize_text(raw_text).split()
    if not tokens:
        return ""
    index, _, _, _, _ = _locate_value_token(tokens)
    return _normalize_text(" ".join(tokens[:index])) if index is not None else _normalize_text(tokens[0])


def _join_texts(*values: str | None) -> str | None:
    parts = [_normalize_text(value) for value in values if _normalize_text(value)]
    return " ".join(parts) if parts else None


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value).split()).strip() if value is not None else ""


# ---------------------------------------------------------------------------
# v12 trusted parser bridge: BornDigitalParser -> RowAssemblerV2 -> rows
# ---------------------------------------------------------------------------

def _parse_trusted_pdf_v12(
    file_bytes: bytes,
    *,
    max_pages: int | None = None,
) -> list[dict[str, Any]]:
    """V12 trusted PDF parse using the PyMuPDF-backed BornDigitalParser.

    This replaces the pdfplumber-first ``_parse_trusted_pdf`` as the primary
    extraction path while preserving the existing downstream row contract.
    pdfplumber is no longer used for row extraction in this function.

    Pipeline:
        file_bytes -> BornDigitalParser -> PageParseArtifactV3[]
        PageParseArtifactV3 -> RowAssemblerV2 -> candidate row dicts
        candidate row dicts -> dedup + materialize -> final row dicts
    """
    if not file_bytes:
        raise ValueError("unsupported_pdf: empty input")

    checksum = sha256(file_bytes).hexdigest()
    document_id = uuid5(NAMESPACE_URL, f"trusted-pdf:{checksum}")

    from app.services.parser.born_digital_parser import BornDigitalParser
    from app.services.row_assembler.v2 import RowAssemblerV2

    bd_parser = BornDigitalParser()
    assembler = RowAssemblerV2()

    artifacts = bd_parser.parse(file_bytes, max_pages=max_pages)

    rows: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    for artifact in artifacts:
        family_adapter_id = _select_adapter(artifact.raw_text).family_adapter_id
        artifact_rows = assembler.assemble(artifact, family_adapter_id=family_adapter_id)
        for row in artifact_rows:
            row_hash = sha256(
                f"{checksum}:{row['source_page']}:{row['row_type']}:{row['raw_text']}".encode("utf-8")
            ).hexdigest()
            if row_hash in seen_hashes:
                continue
            seen_hashes.add(row_hash)
            rows.append(_materialize_v12_row(row, document_id=document_id, checksum=checksum))

    if rows:
        return rows

    # Safety valve for rare parse misses.
    return _parse_trusted_pdf(file_bytes, max_pages=max_pages)


def _page_class_from_v4_kind(page_kind: str) -> str:
    mapping = {
        "lab_results": "analyte_table_page",
        "threshold_reference": "threshold_page",
        "admin_metadata": "admin_page",
        "narrative_guidance": "narrative_page",
        "interpreted_summary": "narrative_page",
        "non_lab_medical": "narrative_page",
        "footer_header": "header_footer_page",
    }
    return mapping.get(str(page_kind), "mixed_page")


def _materialize_v12_row(
    assembled_row: dict[str, Any],
    *,
    document_id: UUID,
    checksum: str,
) -> dict[str, Any]:
    """Materialize a RowAssemblerV2 output into the downstream row contract.

    This adds document_id, a stable row_hash, and v12 parser lineage fields
    that downstream consumers (ExtractionQA, ObservationBuilder) expect.
    """
    from app.services.parser.born_digital_parser import BACKEND_ID, BACKEND_VERSION

    row_type = assembled_row.get("row_type", "unparsed_row")
    raw_text = assembled_row.get("raw_text", "")
    source_page = assembled_row.get("source_page", 1)

    row_hash = sha256(
        f"{checksum}:{source_page}:{row_type}:{raw_text}".encode("utf-8")
    ).hexdigest()

    # Use the artifact's backend metadata when present; fall back to module constants.
    parser_backend = assembled_row.get("parser_backend", BACKEND_ID)
    parser_backend_version = assembled_row.get("parser_backend_version", BACKEND_VERSION)

    return {
        "document_id": document_id,
        "source_page": source_page,
        "block_id": assembled_row.get("block_id", ""),
        "row_hash": row_hash,
        "raw_text": raw_text,
        "raw_analyte_label": assembled_row.get("raw_analyte_label", ""),
        "raw_value_string": assembled_row.get("raw_value_string"),
        "raw_unit_string": assembled_row.get("raw_unit_string"),
        "raw_reference_range": assembled_row.get("raw_reference_range"),
        "parsed_numeric_value": assembled_row.get("parsed_numeric_value"),
        "parsed_locale": assembled_row.get("parsed_locale", {}),
        "parsed_comparator": assembled_row.get("parsed_comparator"),
        "row_type": row_type,
        "measurement_kind": assembled_row.get("measurement_kind"),
        "support_code": assembled_row.get("support_code", "excluded"),
        "failure_code": assembled_row.get("failure_code"),
        "family_adapter_id": assembled_row.get("family_adapter_id", "generic_layout"),
        "page_class": assembled_row.get("page_class", "unknown"),
        "source_kind": assembled_row.get("source_kind", "block"),
        "source_bounds": assembled_row.get("source_bounds"),
        "candidate_trace": assembled_row.get("candidate_trace", {}),
        "source_observation_ids": assembled_row.get("source_observation_ids", []),
        "secondary_result": assembled_row.get("secondary_result"),
        "extraction_confidence": assembled_row.get("extraction_confidence", 0.0),
        # v12 parser lineage
        "parser_backend": parser_backend,
        "parser_backend_version": parser_backend_version,
        "row_assembly_version": assembled_row.get("row_assembly_version", "row-assembly-v2"),
    }
