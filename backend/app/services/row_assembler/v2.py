"""Row assembler v2.

Owns conversion from PageParseArtifactV3 into typed candidate row dicts
for the downstream extraction-QA and normalization funnel.

Design rules (v12 §4.4 + §6.1):
1. Fence admin_meta, narrative, footer, header, and threshold_table blocks
   BEFORE analyte mapping. Only result_table and unknown blocks produce
   candidate analyte rows.
2. Reuse the proven row grammar from backend/app/services/parser/__init__.py
   (classify_candidate_text, parse_measurement_text) — do NOT invent a new
   normalization grammar here.
3. Every row carries the v11 downstream contract fields plus v12 parser
   lineage metadata.
4. No parser backend emits observations directly; this module produces
   candidate rows that ExtractionQA then validates.
5. v12: The page-level candidate path calls the EXACT legacy
   ``_iter_candidates(...)`` helper — no clone.
6. v12: Arbitration is block-local and score-based, not global
   substring/length pruning.
"""

from __future__ import annotations

import re
from hashlib import sha256
from typing import Any

from app.services.parser import (
    _contains_value_token,
    _normalize_text,
    classify_candidate_text,
    parse_measurement_text,
)

# Valid row types for the v12 pipeline — aligned with v11 row grammar
VALID_ROW_TYPES = {
    "measured_analyte_row",
    "derived_analyte_row",
    "qualitative_result_row",
    "admin_metadata_row",
    "threshold_reference_row",
    "narrative_guidance_row",
    "header_footer_row",
    "test_request_row",
    "unparsed_row",
    "footer_or_header_row",
}

# Row types that can continue into normalization / analyte resolution
NORMALIZABLE_ROW_TYPES = {
    "measured_analyte_row",
    "derived_analyte_row",
    "qualitative_result_row",
}

# Blocks that must be fenced BEFORE any analyte mapping
FENCED_BLOCK_TYPES = {
    "admin_meta",
    "narrative",
    "footer",
    "header",
    "threshold_table",
}

# ---------------------------------------------------------------------------
# v12 module-level helpers for line classification in the grouping routine
# ---------------------------------------------------------------------------

# Known section-heading keywords that should be stripped when they appear as
# the first token of a multi-line result_table / unknown block.
_SECTION_HEADING_KEYWORDS = {
    "biochemistry",
    "haematology",
    "hematology",
    "urinalysis",
    "microbiology",
    "serology",
    "chemistry",
    "special chemistry",
    "special chemistry specimen",
    "endocrinology",
    "immunology",
    "coagulation",
    "full blood count",
    "full blood picture",
    "fbc",
    "fbp",
    "liver function",
    "lft",
    "renal function",
    "rft",
    "lipid profile",
    "thyroid",
    "hormone",
    "tumour marker",
    "tumor marker",
    "iron studies",
    "electrolytes",
    "urea electrolytes",
    "uec",
    "cbc",
    "cbc diff",
    "differential",
    "diff count",
    "blood culture",
    "sensitivity",
    "culture",
    "results",
    "laboratory results",
    "comment(s)",
    "comments",
    "remark(s)",
    "remarks",
    "interpretation",
    "clinical note",
    "clinical notes",
    "clinical comment",
    "narrative",
    "page",
    "ref.",
    "ref. ranges",
    "reference ranges",
    "diagnostic values",
}


def _looks_like_unit_substance(line: str) -> bool:
    """Return True if the line looks like a unit-with-substance continuation.

    v12 wave-2: lines like ``mg Alb/mmol``, ``g/L``, ``IU/mL`` that carry
    a measurement unit but also a substance qualifier are treated as unit
    continuations, not label lines.

    v12 wave-6: all-uppercase two-word analyte labels like ``BAND NEUTROPHILS``
    are NOT treated as unit continuations.
    """
    stripped = line.strip()
    if not stripped:
        return False
    # Already caught by _looks_like_unit_only for single-token units
    if len(stripped.split()) == 1:
        return False
    # Common pattern: unit prefix + optional substance + optional /unit
    # Examples: "mg Alb/mmol", "g/L", "mg/dL", "U/L", "IU/L", "mmol/L"
    if re.match(r"^[a-zA-Z]+(?:\s+[A-Za-z]+)?/[a-zA-Z0-9/]+$", stripped):
        return True
    # Single unit with a space-separated qualifier
    if re.match(r"^[a-zA-Z]+\s+[a-zA-Z/]+$", stripped):
        tokens = stripped.split()
        if len(tokens) == 2 and len(tokens[0]) <= 4:
            # v12 wave-6: reject all-uppercase two-word analyte labels
            # like "BAND NEUTROPHILS" — these are analyte names, not units.
            if tokens[0].isupper() and tokens[1].isupper():
                return False
            return True
    return False


def _is_qualitative_value_line(line: str) -> bool:
    """Return True if the line is a qualitative lab value like NEGATIVE, DNR.

    v12 wave-2: qualitative result words should be treated as value-bearing
    for grouping purposes so they flush preceding labels into a row.
    """
    stripped = line.strip().lower()
    if not stripped:
        return False
    # Known qualitative result keywords
    if stripped in _QUALITATIVE_VALUE_WORDS:
        return True
    # Common color/appearance qualifiers in urinalysis
    color_words = {
        "yellow", "amber", "straw", "colorless", "dark", "light",
        "clear", "hazy", "cloudy", "turbid", "smoky",
    }
    if stripped in color_words:
        return True
    # Single-word uppercase tokens in lab context that are likely values
    if len(stripped.split()) == 1 and len(stripped) > 1:
        if stripped in {"trace", "rare", "few", "moderate", "many",
                        "none", "normal", "abnormal", "present", "absent",
                        "detected", "not detected", "reactive", "non-reactive"}:
            return True
    return False


_COMPARATOR_RE = re.compile(r"^(?:<|>|<=|>=|≤|≥)\s*\d")
_NUMERIC_TOKEN_RE = re.compile(r"(?:^|\s)(?:<|>|<=|>=|≤|≥)?\s*\d[\d,.]*(?:\.\d+)?(?:\s|$)")
_UNIT_RE = re.compile(
    r"^(?:"
    r"[%°]"
    r"|[a-zA-Zµμ]+/[a-zA-Z0-9µμ/]+"
    r"|[a-zA-Z]{1,4}\d*[²³]?"
    r"|[a-zA-Z]+\s*[²³]+"
    r")$"
)
_REF_RANGE_RE = re.compile(r"^[\(\[]?\d[\d,.]*\s*[-–]\s*\d[\d,.]*[\)\]]?$")
_REF_RANGE_COMPARATOR_RE = re.compile(r"^\(\s*<\s*\d", re.I)
_FLAG_WORDS = {"high", "low", "normal", "abnormal", "h", "l", "n", "a"}
_SINGLE_FLAG_RE = re.compile(r"^[HLA*\!]$", re.I)
_SAMPLE_INDEX_RE = re.compile(r"^\d{1,2}$")
_UNIT_SUPERSCRIPT_FRAGMENT_RE = re.compile(
    r"(\d+(?:\.\d+)?[a-zA-Zµμ]+)\s([²³0-9])(?=\s|$|[,;/])"
)
_QUALITATIVE_VALUE_WORDS = {
    "dnr",
    "ldnr",
    "oor",
    "negative",
    "positive",
    "present",
    "absent",
    "yes",
    "no",
}


def _collapse_unit_superscript_artifacts(text: str) -> str:
    """Collapse only genuine unit superscript extraction artifacts.

    This intentionally fixes fragments like ``1.73m 2`` -> ``1.73m2``
    without mutating analyte/value boundaries such as ``CD 8`` or
    ``WESTERGREN 6``.
    """
    return _UNIT_SUPERSCRIPT_FRAGMENT_RE.sub(r"\1\2", text)


def _contains_value_token_for_heading(text: str) -> bool:
    """Check if a line contains a measurement value token (for heading detection)."""
    from app.services.parser import _locate_value_token as _parser_locate_value

    tokens = text.split()
    if not tokens:
        return False
    idx, raw_value, _, _, _ = _parser_locate_value(tokens)
    return idx is not None and raw_value is not None


def _is_value_bearing_line(line: str) -> bool:
    """Return True if the line contains a value token.

    v12 wave-6: embedded-numeric-label guard.  Multi-word analyte labels
    like ``Abs. CD 8 Suppressor`` or ``Alpha 2 Macroglobulin`` must NOT be
    treated as value-bearing just because they contain a numeral token.
    """
    tokens = line.split()
    if not tokens:
        return False

    # Direct check: comparator + number at start
    if _COMPARATOR_RE.match(line):
        return True

    # v12 wave-6: embedded-numeric-label guard.
    # If the line has 3+ tokens and a majority are alpha (not digits), treat
    # numerals as label-embedded unless one numeric token is a real measured
    # value (>99) or comparator-prefixed.
    alpha_count = sum(1 for t in tokens if re.match(r"^[a-zA-Z]+$", t))
    numeric_tokens = [
        t for t in tokens
        if re.match(r"^(?:<|>|<=|>=|≤|≥)?\d[.,\d]*$", t)
    ]
    if alpha_count >= 2 and numeric_tokens and len(tokens) >= 3:
        for nt in numeric_tokens:
            stripped = nt.lstrip("<>=≤≥")
            try:
                val = float(stripped.replace(",", "."))
                if val > 99:
                    return True  # e.g. CD 8 Suppressor 1024
            except ValueError:
                pass
            if re.match(r"^(?:<|>|<=|>=|≤|≥)", nt):
                return True  # comparator-prefixed
        return False  # embedded label number like "CD 8" or "Alpha 2"

    # Any token that is a numeric value (possibly with comparator prefix)
    for token in tokens:
        cleaned = token.strip("()[]")
        if re.match(r"^(?:<|>|<=|>=|≤|≥)?\d[.,\d]*(?:\.\d+)?$", cleaned):
            return True

    return bool(_NUMERIC_TOKEN_RE.search(line))


def _looks_like_unit_only(line: str) -> bool:
    """Return True if the line is a pure unit like ``mmol/L``, ``mg/dL``, ``%``.

    v12 repair: a line that also carries a label or a value token is NOT
    unit-only, even if it happens to contain characters like ``%`` or ``/``.
    ``HbA1c 6.8 %`` and ``ACR < 0.1 mg Alb/mmol`` must NOT match here.

    v12 wave-6: short alpha-with-slash tokens like ``/uL`` are treated as
    unit continuations so they do not get classified as standalone labels.
    """
    stripped = _collapse_unit_superscript_artifacts(line.strip())
    lower = stripped.lower()
    if not stripped:
        return False

    # v12: if the line contains a digit or a value token, it is not unit-only
    if re.search(r"\d", stripped):
        return False

    # v12 wave-6: bare slash-alpha tokens like /uL are unit continuations
    if re.match(r"^/[a-zA-Z]+$", stripped):
        return True

    # v12: if the line has multiple whitespace-separated tokens, it is likely
    # not a pure unit (pure units are single tokens or compound units with
    # embedded slashes/superscripts but no spaces).
    if len(stripped.split()) > 1:
        return False

    # Pure short tokens without digits are units
    if re.match(r"^[a-z]{1,3}$", lower):
        return True
    if re.match(r"^[a-z]{1,3}/[a-z]+", lower):
        return True
    return bool(_UNIT_RE.match(stripped))


def _is_reference_range_fragment(line: str) -> bool:
    """Return True if the line looks like a reference range fragment."""
    stripped = line.strip()
    if _REF_RANGE_RE.match(stripped):
        return True
    if _REF_RANGE_COMPARATOR_RE.match(stripped):
        return True
    # Handle "< OR = 20" style reference fragments
    if re.match(r"^<\s*OR\s*=\s*\d", stripped, re.I):
        return True
    return False


def _is_ref_range_with_unit(line: str) -> bool:
    """Return True if the line is a reference range followed by a unit or suffix.

    v12 wave-3: detects lines like ``98-110 mmol/L``, ``20-32 mmol/L``,
    ``< OR = 20 mm/h``, ``1.0-2.5 (calc)`` that are continuations of the
    current measurement row, not standalone value-bearing lines.
    """
    stripped = line.strip()
    if not stripped:
        return False
    # Range with unit suffix: "98-110 mmol/L", "20-32 mg/dL"
    if re.match(r"^\d[\d,.]*\s*[-–]\s*\d[\d,.]*\s+[a-zA-Zµμ/]", stripped):
        return True
    # Range with parenthetical suffix: "1.0-2.5 (calc)", "4.0-6.0 (fasting)"
    if re.match(r"^\d[\d,.]*\s*[-–]\s*\d[\d,.]*\s+\(", stripped):
        return True
    # Comparator range with unit: "< OR = 20 mm/h"
    if re.match(r"^<\s*OR\s*=\s*\d[\d,.]*\s+[a-zA-Zµμ/]", stripped, re.I):
        return True
    return False


def _is_numeric_fraction_with_unit(line: str) -> bool:
    """Return True if the line is a numeric fraction/ratio followed by a unit.

    v12 wave-3: detects lines like ``0 /100 WBC``, ``< 5 /hpf`` that are
    measurement continuations, not standalone value-bearing lines.
    """
    stripped = line.strip()
    if not stripped:
        return False
    # Pattern: digit(s) + optional comparator + / + digit(s) + space + alpha
    # e.g. "0 /100 WBC", "< 5 /hpf", "1 /20 RBC"
    if re.match(r"^(?:<|>|<=|>=)?\s*\d+\s*/\s*\d+\s+[a-zA-Zµμ]", stripped):
        return True
    return False


def _is_flag_or_status_token(line: str) -> bool:
    """Return True if the line is a flag or status word."""
    stripped = line.strip()
    if stripped.lower() in _FLAG_WORDS:
        return True
    if _SINGLE_FLAG_RE.match(stripped):
        return True
    return False


def _is_sample_index_token(line: str) -> bool:
    """Return True if the line is a short sample-index number."""
    stripped = line.strip()
    if not _SAMPLE_INDEX_RE.match(stripped):
        return False
    val = int(stripped)
    return val <= 99


class RowAssemblerV2:
    """Assemble typed candidate rows from PageParseArtifactV3 artifacts.

    v12 key change: ``_page_level_candidates`` delegates to the exact
    legacy ``_iter_candidates`` from ``app.services.parser`` — no cloned
    geometry / table / text logic lives here.
    """

    def assemble(
        self,
        artifact: Any,  # PageParseArtifactV3
        *,
        family_adapter_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Convert a single PageParseArtifactV3 into candidate row dicts."""
        from app.services.parser.page_parse_artifact_v3 import PageParseArtifactV3

        if not isinstance(artifact, PageParseArtifactV3):
            raise TypeError(
                f"RowAssemblerV2.assemble expects PageParseArtifactV3, "
                f"got {type(artifact).__name__}"
            )

        effective_adapter_id = family_adapter_id or self._infer_family_adapter_id(artifact)
        rows: list[dict[str, Any]] = []
        page_class = self._infer_page_class(artifact)

        # ---- Pass 1: Fenced blocks (always block-level) ----
        for block in artifact.blocks:
            block_type = block.block_type
            block_lines = block.lines if block.lines else [block.text]

            if block_type in FENCED_BLOCK_TYPES:
                for line_text in block_lines:
                    line_text = line_text.strip()
                    if not line_text:
                        continue
                    row = self._fenced_row(
                        raw_text=line_text,
                        block_type=block_type,
                        artifact=artifact,
                        page_class=page_class,
                        family_adapter_id=effective_adapter_id,
                        block_id=block.block_id,
                    )
                    rows.append(row)

        # ---- Pass 2: Hybrid candidate recovery ----
        candidate_blocks = [
            block
            for block in artifact.blocks
            if block.block_type not in FENCED_BLOCK_TYPES
        ]

        # Pass 2a: page-level candidates via EXACT legacy _iter_candidates
        page_level_rows, recovered_texts = self._page_level_candidates(
            artifact,
            page_class=page_class,
            family_adapter_id=effective_adapter_id,
        )
        rows.extend(page_level_rows)

        # Pass 2b: block-level fallback for vertical / unknown blocks
        block_fallback = self._block_fallback_candidates(
            candidate_blocks,
            page_class=page_class,
            family_adapter_id=effective_adapter_id,
            artifact=artifact,
            already_recovered_texts=recovered_texts,
        )
        rows.extend(block_fallback)

        # Safety net: if nothing recovered but raw_text exists, fall back
        if not rows and artifact.raw_text.strip():
            for line_idx, line_text in enumerate(artifact.raw_text.splitlines()):
                line_text = line_text.strip()
                if not line_text:
                    continue
                classification = classify_candidate_text(
                    line_text,
                    page_class=page_class,
                    family_adapter_id=effective_adapter_id,
                )
                row = self._candidate_row(
                    raw_text=line_text,
                    classification=classification,
                    artifact=artifact,
                    page_class=page_class,
                    family_adapter_id=effective_adapter_id,
                    block_id=f"page-{artifact.page_number}:raw-{line_idx:03d}",
                    segment_index=line_idx + 1,
                )
                rows.append(row)

        # ---- Pass 3: Block-local candidate arbitration ----
        rows = self._arbitrate_candidates(rows, artifact)

        return rows

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_family_adapter_id(artifact: Any) -> str:
        """Infer a family adapter ID from artifact metadata when none is passed."""
        languages = getattr(artifact, "language_candidates", None) or []
        if "zh" in languages and "en" in languages:
            return "innoquest_bilingual_general"
        return "generic_layout"

    def _infer_page_class(self, artifact: Any) -> str:
        """Infer the v11 page_class from the v12 page_kind."""
        kind = getattr(artifact, "page_kind", "unknown") or "unknown"
        mapping = {
            "lab_results": "analyte_table_page",
            "threshold_table": "threshold_page",
            "admin_meta": "admin_page",
            "narrative": "narrative_page",
            "footer": "header_footer_page",
            "unknown": "mixed_page",
        }
        return mapping.get(kind, "mixed_page")

    def _fenced_row(
        self,
        raw_text: str,
        block_type: str,
        artifact: Any,
        page_class: str,
        family_adapter_id: str,
        block_id: str,
    ) -> dict[str, Any]:
        """Build an excluded/fenced row from a non-result block."""
        block_type_to_row_type = {
            "admin_meta": "admin_metadata_row",
            "narrative": "narrative_guidance_row",
            "footer": "header_footer_row",
            "header": "header_footer_row",
            "threshold_table": "threshold_reference_row",
        }
        row_type = block_type_to_row_type.get(block_type, "unparsed_row")
        failure_code = row_type

        classification = classify_candidate_text(
            raw_text,
            page_class=page_class,
            family_adapter_id=family_adapter_id,
        )
        if classification["row_type"] != "unparsed_row":
            row_type = classification["row_type"]
            failure_code = classification.get("failure_code") or row_type

        raw_analyte_label = raw_text.split()[0] if raw_text.split() else raw_text

        return {
            "document_id": getattr(artifact, "page_id", ""),
            "source_page": artifact.page_number,
            "block_id": block_id,
            "row_hash": self._row_hash(artifact, raw_text, row_type),
            "raw_text": raw_text,
            "raw_analyte_label": raw_analyte_label,
            "raw_value_string": None,
            "raw_unit_string": None,
            "raw_reference_range": None,
            "parsed_numeric_value": None,
            "parsed_locale": {
                "decimal_separator": None,
                "thousands_separator": None,
                "normalized": None,
            },
            "parsed_comparator": None,
            "row_type": row_type,
            "measurement_kind": None,
            "support_code": "excluded",
            "failure_code": failure_code,
            "family_adapter_id": family_adapter_id,
            "page_class": page_class,
            "source_kind": "block",
            "source_bounds": None,
            "candidate_trace": {
                "page_number": artifact.page_number,
                "block_id": block_id,
                "segment_index": 0,
                "page_class": page_class,
                "family_adapter_id": family_adapter_id,
                "source_kind": "block",
                "block_type": block_type,
            },
            "source_observation_ids": [],
            "secondary_result": None,
            "extraction_confidence": 0.0,
            "source_file_path": getattr(artifact, "source_file_path", ""),
            "trust_level": getattr(artifact, "trust_level", artifact.lane_type),
            "backend_id": artifact.backend_id,
            "backend_version": artifact.backend_version,
            "parser_backend": artifact.backend_id.split("-")[0] if "-" in artifact.backend_id else artifact.backend_id,
            "parser_backend_version": artifact.backend_version,
            "row_assembly_version": "row-assembly-v2",
        }

    def _candidate_row(
        self,
        raw_text: str,
        classification: dict[str, Any],
        artifact: Any,
        page_class: str,
        family_adapter_id: str,
        block_id: str,
        segment_index: int,
    ) -> dict[str, Any]:
        """Build a candidate row via the v11 parse_measurement_text grammar."""
        # v12 wave-4: normalize unit fragments like ``mL/min/1.73m 2`` to
        # ``mL/min/1.73m2`` before parsing, so the superscript isn't silently
        # truncated by the parser.
        raw_text = self._normalize_unit_superscript_fragments(raw_text)

        parsed = parse_measurement_text(
            raw_text,
            page_class=page_class,
            family_adapter_id=family_adapter_id,
            source_kind="block",
            page_number=artifact.page_number,
            block_id=block_id,
            segment_index=segment_index,
        )

        raw_analyte_label = parsed.get("raw_analyte_label") or (
            raw_text.split()[0] if raw_text.split() else raw_text
        )

        row_type = parsed["row_type"]
        support_code = parsed.get("support_code", "supported")
        failure_code = parsed.get("failure_code")

        return {
            "document_id": getattr(artifact, "page_id", ""),
            "source_page": artifact.page_number,
            "block_id": block_id,
            "row_hash": self._row_hash(artifact, raw_text, row_type),
            "raw_text": raw_text,
            "raw_analyte_label": raw_analyte_label,
            "raw_value_string": parsed.get("raw_value_string"),
            "raw_unit_string": parsed.get("raw_unit_string"),
            "raw_reference_range": parsed.get("raw_reference_range"),
            "parsed_numeric_value": parsed.get("parsed_numeric_value"),
            "parsed_locale": parsed.get("parsed_locale", {}),
            "parsed_comparator": parsed.get("parsed_comparator"),
            "row_type": row_type,
            "measurement_kind": parsed.get("measurement_kind"),
            "support_code": support_code,
            "failure_code": failure_code,
            "family_adapter_id": family_adapter_id,
            "page_class": page_class,
            "source_kind": "block",
            "source_bounds": parsed.get("source_bounds"),
            "candidate_trace": {
                "page_number": artifact.page_number,
                "block_id": block_id,
                "segment_index": segment_index,
                "page_class": page_class,
                "family_adapter_id": family_adapter_id,
                "source_kind": "block",
            },
            "source_observation_ids": parsed.get("source_observation_ids", []),
            "secondary_result": parsed.get("secondary_result"),
            "extraction_confidence": parsed.get("extraction_confidence", 0.0),
            "source_file_path": getattr(artifact, "source_file_path", ""),
            "trust_level": getattr(artifact, "trust_level", artifact.lane_type),
            "backend_id": artifact.backend_id,
            "backend_version": artifact.backend_version,
            "parser_backend": artifact.backend_id.split("-")[0] if "-" in artifact.backend_id else artifact.backend_id,
            "parser_backend_version": artifact.backend_version,
            "row_assembly_version": "row-assembly-v2",
        }

    # ------------------------------------------------------------------
    # v12: page-level candidates via EXACT legacy _iter_candidates
    # ------------------------------------------------------------------

    def _page_level_candidates(
        self,
        artifact: Any,
        *,
        page_class: str,
        family_adapter_id: str,
    ) -> tuple[list[dict[str, Any]], set[str]]:
        """Run the exact legacy ``_iter_candidates`` over artifact data.

        No clone: the geometry banding, table iteration, and text-line
        pending-label merge all live in ``app.services.parser._iter_candidates``.
        We only adapt the PyMuPDF word/table metadata into the shapes the
        legacy helper expects and materialise its yields into V2 row dicts.
        """
        from app.services.parser import (
            GenericLayoutAdapter,
            InnoquestBilingualGeneralAdapter,
            _iter_candidates,
        )

        words_data = artifact.metadata.get("words") if hasattr(artifact, "metadata") else None
        tables_data = artifact.metadata.get("tables") if hasattr(artifact, "metadata") else None
        raw_text = getattr(artifact, "raw_text", "")

        # Adapt PyMuPDF words to the legacy shape (list of dicts with
        # text/x0/y0/x1/y1/top/bottom keys).
        words = self._adapt_pymupdf_words(words_data) if words_data else []

        # Adapt PyMuPDF tables to the legacy shape: list[list[list[str|None]]]
        tables = self._adapt_pymupdf_tables(tables_data) if tables_data else []

        # Select the exact same adapter the legacy path would pick.
        if family_adapter_id == "innoquest_bilingual_general":
            legacy_adapter: GenericLayoutAdapter = InnoquestBilingualGeneralAdapter()
        else:
            legacy_adapter = GenericLayoutAdapter()

        rows: list[dict[str, Any]] = []
        recovered_texts: set[str] = set()

        for source_kind, candidate_text, bounds, block_id, segment_index in _iter_candidates(
            raw_text,
            words,
            tables,
            page_number=artifact.page_number,
            page_class=page_class,
            adapter=legacy_adapter,
        ):
            classification = classify_candidate_text(
                candidate_text,
                page_class=page_class,
                family_adapter_id=legacy_adapter.family_adapter_id,
            )
            if classification["row_type"] == "unparsed_row":
                continue
            norm = _normalize_text(candidate_text)
            row = self._candidate_row(
                raw_text=candidate_text,
                classification=classification,
                artifact=artifact,
                page_class=page_class,
                family_adapter_id=legacy_adapter.family_adapter_id,
                block_id=block_id,
                segment_index=segment_index,
            )
            if row["row_type"] == "unparsed_row":
                continue
            norm_label = self._normalize_raw_label(
                candidate_text,
                {"raw_analyte_label": row.get("raw_analyte_label", "")},
            )
            if norm_label:
                row["raw_analyte_label"] = norm_label
            row["_source_kind"] = source_kind
            if bounds is not None:
                row["source_bounds"] = bounds
            rows.append(row)
            recovered_texts.add(norm)

        return rows, recovered_texts

    @staticmethod
    def _adapt_pymupdf_words(words_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Adapt PyMuPDF word metadata to the legacy iterator shape."""
        adapted: list[dict[str, Any]] = []
        for w in words_data:
            adapted.append({
                "text": str(w.get("text", "")),
                "x0": float(w.get("x0", 0)),
                "y0": float(w.get("y0", 0)),
                "x1": float(w.get("x1", 0)),
                "y1": float(w.get("y1", 0)),
                "top": float(w.get("y0", 0)),
                "bottom": float(w.get("y1", 0)),
                "block_no": int(w.get("block_no", 0)),
            })
        return adapted

    @staticmethod
    def _adapt_pymupdf_tables(tables_data: list[dict[str, Any]]) -> list[list[list[str | None]]]:
        """Adapt PyMuPDF table metadata to the legacy shape."""
        adapted: list[list[list[str | None]]] = []
        for table_info in tables_data:
            table_rows = table_info.get("rows", []) if isinstance(table_info, dict) else table_info
            adapted.append(table_rows)
        return adapted

    # ------------------------------------------------------------------
    # v12: grouped block-line recovery (replaces whole-block merge)
    # ------------------------------------------------------------------

    def _block_fallback_candidates(
        self,
        blocks: list[Any],
        *,
        page_class: str,
        family_adapter_id: str,
        artifact: Any,
        already_recovered_texts: set[str],
    ) -> list[dict[str, Any]]:
        """Supplement page-level rows with grouped block-line recovery.

        v12 fix: instead of merging entire blocks into one giant candidate,
        split multi-line result_table and unknown blocks into measurement-sized
        candidate groups.  Each group becomes one candidate row.

        v12 wave-6: single-line block fallback is now allowed when page-level
        recovery is absent or unparsed, so locale-comma single-line blocks
        like "Glucose 5,6 mg/dL" survive recovery.
        """
        rows: list[dict[str, Any]] = []

        for block in blocks:
            block_lines = block.lines if block.lines else [block.text]
            clean_lines = [ln.strip() for ln in block_lines if ln.strip()]

            # v12 wave-7: allow single-line block fallback candidates when the
            # line is value-bearing.  We rely on recovered_texts dedupe rather
            # than page-level-presence heuristics, so locale-comma single-line
            # results like "Glucose 5,6 mg/dL" survive even when page-level
            # recovery produced other rows on the same page.
            if len(clean_lines) == 0:
                continue

            # v12: Strip heading if present (for result_table / unknown blocks)
            if block.block_type in ("result_table", "unknown"):
                effective_lines = self._strip_heading_if_present(clean_lines, family_adapter_id)
            else:
                effective_lines = clean_lines

            if not effective_lines:
                continue

            # v12: Group lines into measurement-sized candidates
            # Each group should represent one measurement row
            groups = self._group_lines_into_measurements(effective_lines, family_adapter_id, page_class)

            for group_idx, group_lines in enumerate(groups, start=1):
                if not group_lines:
                    continue

                # v12 wave-7: collapse adjacent duplicate labels inside each group
                # BEFORE joining candidate_text.  This prevents LabTestingAPI rows
                # like "SED RATE BY MODIFIED WESTERGREN SED RATE BY MODIFIED WESTERGREN 6"
                # from ever reaching the parser.
                group_lines = self._collapse_group_duplicate_labels(group_lines)

                candidate_text = " ".join(group_lines)
                norm_candidate = _normalize_text(candidate_text)

                if norm_candidate in already_recovered_texts:
                    continue

                classification = classify_candidate_text(
                    candidate_text,
                    page_class=page_class,
                    family_adapter_id=family_adapter_id,
                )

                # v12 wave-7: normalize the raw label for immunology and LabTesting
                # resolver compatibility (CD 8 spacing, BASOPHILS P, MAGNESIUM RBC).
                norm_label = self._normalize_raw_label(candidate_text, classification)
                if norm_label:
                    classification = dict(classification)
                    classification["raw_analyte_label"] = norm_label

                if classification["row_type"] in NORMALIZABLE_ROW_TYPES:
                    row = self._candidate_row(
                        raw_text=candidate_text,
                        classification=classification,
                        artifact=artifact,
                        page_class=page_class,
                        family_adapter_id=family_adapter_id,
                        block_id=block.block_id,
                        segment_index=group_idx,
                    )
                    row_norm_label = self._normalize_raw_label(
                        candidate_text,
                        {"raw_analyte_label": row.get("raw_analyte_label", "")},
                    )
                    if row_norm_label:
                        row["raw_analyte_label"] = row_norm_label
                    elif norm_label:
                        row["raw_analyte_label"] = norm_label
                    row["_source_kind"] = "block_fallback"
                    row["_is_heading_stripped"] = len(effective_lines) < len(clean_lines)
                    rows.append(row)
                    already_recovered_texts.add(norm_candidate)

        return rows

    def _group_lines_into_measurements(
        self,
        lines: list[str],
        family_adapter_id: str,
        page_class: str = "mixed_page",
    ) -> list[list[str]]:
        """Group lines into measurement-sized candidate groups.

        v12 fix: correctly handles
        - consecutive label-only lines before the first value
        - comparator-first value lines like ``< 0.1``
        - secondary value/unit tails like ``33 mmol/mol``
        - status/flag/sample-index continuations (``NORMAL``, ``HIGH``, ``01``)
        - multi-word analyte labels with embedded numerals (e.g. ``Abs. CD 8 Suppressor``)

        Strategy:
        1. Accumulate non-value lines (labels) until the first value-bearing
           line is encountered.
        2. A line is value-bearing if it contains a numeric token OR starts
           with a comparator (``< > <= >= ≤ ≥``) followed by a number.
        3. Once a group already has a primary value, a new standalone
           numeric token is treated as a *secondary* value *only* when it
           is immediately followed by a unit line; otherwise it starts a
           new group.
        4. Continuation lines — units, reference ranges, flags/status words,
           and short sample-index numbers — are appended to the current
           group rather than splitting it.
        5. Label-only lines that appear after a complete group flush the
           current group and start a new pending-label group.
        6. v12 wave-5: ``_is_value_bearing_line`` must NOT be tripped by
           multi-word label tokens that contain numerals (e.g. ``CD 8``) —
           a line like ``Abs. CD 8 Suppressor 1024 High /uL 109-897`` must
           be recognized as one measurement, not split at ``8``.
        """
        groups: list[list[str]] = []
        current_group: list[str] = []
        has_primary_value = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            is_value = _is_value_bearing_line(stripped) or _is_qualitative_value_line(stripped)
            continuation_info = self._classify_continuation(stripped)

            # v12 wave-4: sample-index tokens must NOT fire as continuation
            # before a primary value exists. A 1-2 digit numeric like "28" is
            # almost certainly a lab value in that context, not a sample number.
            if continuation_info == "sample_index" and not has_primary_value:
                continuation_info = None
                # Re-evaluate: if it is a bare numeric, treat it as value-bearing
                if re.match(r"^\d{1,2}$", stripped):
                    is_value = True

            # v12 wave-5: If we have no primary value yet, a line that
            # contains a numeric token but ALSO looks like a multi-word label
            # (e.g. "Abs. CD 8 Suppressor 1024 High /uL 109-897") must be
            # treated as the full measurement, not split.  The key signal is
            # that the line has BOTH alpha tokens and value tokens.
            if is_value and not has_primary_value and continuation_info is None:
                # Check if this line looks like a complete measurement:
                # it has an alpha prefix AND a value AND a trailing unit/range
                if self._is_complete_measurement_line(stripped):
                    current_group.append(stripped)
                    has_primary_value = True
                elif has_primary_value:
                    # Start a fresh group for the new measurement
                    groups.append(current_group)
                    current_group = [stripped]
                    has_primary_value = True
                else:
                    # First value-bearing line: attach accumulated labels
                    current_group.append(stripped)
                    has_primary_value = True
            elif continuation_info is not None:
                # Continuation line — append to current group if one exists.
                if current_group:
                    current_group.append(stripped)
                else:
                    # Orphan continuation — start a group but don't mark as value
                    current_group = [stripped]
                    has_primary_value = False
            else:
                # Label-only or noise line
                if has_primary_value and current_group:
                    # Flush the completed measurement group
                    groups.append(current_group)
                    current_group = [stripped]
                    has_primary_value = False
                else:
                    # Accumulate label lines
                    current_group.append(stripped)
                    has_primary_value = False

        # Flush remaining group
        if current_group:
            groups.append(current_group)

        # --- Post-process: merge label-only groups into the NEXT value group ---
        # v12 repair: only merge label-only groups when there IS a next value group
        # AND the label-only group is not exclusively excluded (e.g. threshold /
        # risk-table fragments like "High", "Low", "within", "Total Men").
        # Excluded label-only groups are dropped rather than prepended into the
        # next value-bearing measurement group.
        merged: list[list[str]] = []
        for idx, group in enumerate(groups):
            group_has_value = any(_is_value_bearing_line(ln) for ln in group)
            if not group_has_value:
                # Label-only group: look ahead for a next value-bearing group
                next_value_idx = None
                for j in range(idx + 1, len(groups)):
                    if any(_is_value_bearing_line(ln) for ln in groups[j]):
                        next_value_idx = j
                        break
                if next_value_idx is not None:
                    # v12: skip excluded label-only groups — they must NOT be
                    # blindly prepended into the next value-bearing group, which
                    # would reclassify the merged text as a measurement candidate.
                    if self._all_lines_excluded(group, family_adapter_id, page_class):
                        continue
                    groups[next_value_idx] = group + groups[next_value_idx]
                # If no next value group, drop the trailing label-only group
            else:
                merged.append(group)

        # --- Post-process: attach secondary value+unit to preceding group ---
        final: list[list[str]] = []
        for group in merged:
            if _looks_like_unit_only(group[0]) and final:
                # Standalone unit line — attach to previous group
                final[-1].extend(group)
            else:
                final.append(group)

        return final

    @staticmethod
    def _is_complete_measurement_line(line: str) -> bool:
        """Return True if a single line looks like a complete measurement.

        v12 wave-5: used to avoid splitting multi-word measurement rows
        like ``Abs. CD 8 Suppressor 1024 High /uL 109-897`` during line
        grouping.  A complete measurement line has:
        - at least 3 tokens
        - at least one alpha-only token that is NOT a unit/flag
        - at least one numeric value token
        - at least one unit-like or reference-range-like token
        """
        tokens = line.split()
        if len(tokens) < 3:
            return False
        has_alpha_label = False
        has_value = False
        has_unit_or_range = False
        for t in tokens:
            if _is_value_bearing_line(t):
                has_value = True
            elif re.match(r"^[a-zA-Z]+(?:\.[a-zA-Z]+)*$", t) and not _looks_like_unit_only(t):
                has_alpha_label = True
            elif _looks_like_unit_only(t) or _is_reference_range_fragment(t) or _is_ref_range_with_unit(t):
                has_unit_or_range = True
            elif _is_flag_or_status_token(t):
                has_unit_or_range = True
        return has_alpha_label and has_value and (has_unit_or_range or len(tokens) >= 4)

    def _all_lines_excluded(
        self,
        lines: list[str],
        family_adapter_id: str,
        page_class: str,
    ) -> bool:
        """Return True if every line in a label-only group classifies as excluded.

        v12: prevents threshold/risk-table fragments like "High", "Low",
        "within", "Total Men" from being blindly prepended into the next
        value-bearing group during the merge step of
        _group_lines_into_measurements.
        """
        if not lines:
            return False
        for line in lines:
            classification = classify_candidate_text(
                line,
                page_class=page_class,
                family_adapter_id=family_adapter_id,
            )
            if classification.get("support_code") != "excluded":
                return False
        return True

    def _classify_continuation(self, line: str) -> str | None:
        """Return the continuation kind, or None if the line is not a continuation.

        Returns one of:
        - ``"unit"`` — a pure unit line like ``mmol/L``, ``mg/dL``, ``%``
        - ``"ref_range"`` — a reference range fragment like ``(135-145)``
        - ``"flag"`` — a flag/status word like ``NORMAL``, ``HIGH``, ``LOW``, ``H``, ``L``
        - ``"sample_index"`` — a short numeric sample index like ``01``, ``02``, ``03``
        - ``None`` — not a continuation (label or value)
        """
        stripped = line.strip()
        if not stripped:
            return None

        # Unit-only lines
        if _looks_like_unit_only(stripped):
            return "unit"

        # Unit-with-substance continuations like "mg Alb/mmol"
        if _looks_like_unit_substance(stripped):
            return "unit"

        # v12 wave-3: reference ranges with units / parenthetical suffixes
        # must be caught BEFORE generic ref_range so they continue the row
        # e.g. "98-110 mmol/L", "< OR = 20 mm/h", "1.0-2.5 (calc)"
        if _is_ref_range_with_unit(stripped):
            return "ref_range"

        # Reference range fragments like (135-145), [4.0-6.4], (< 3.5)
        if _is_reference_range_fragment(stripped):
            return "ref_range"

        # Numeric fraction with unit like "0 /100 WBC"
        if _is_numeric_fraction_with_unit(stripped):
            return "ref_range"

        # Flag/status words
        if _is_flag_or_status_token(stripped):
            return "flag"

        # Short sample-index numbers (1-2 digits, typically at end of LabTestingAPI rows)
        if _is_sample_index_token(stripped):
            return "sample_index"

        return None

    def _collapse_group_duplicate_labels(
        self,
        group_lines: list[str],
    ) -> list[str]:
        """v12 wave-7: collapse adjacent duplicate label tokens inside a grouped
        candidate BEFORE the candidate_text join.

        Handles LabTestingAPI patterns like::

            SED RATE BY MODIFIED WESTERGREN, SED RATE BY MODIFIED WESTERGREN, 6, ...
            MAGNESIUM, RBC, MAGNESIUM, RBC, 4.3, ...

        by detecting repeated label prefixes and keeping only one copy.
        """
        if len(group_lines) < 2:
            return group_lines

        collapsed: list[str] = []
        i = 0
        while i < len(group_lines):
            line = group_lines[i]
            # Check if the next line is a near-duplicate of this label.
            # We normalise: strip punctuation, lowercase, and compare.
            normalised = re.sub(r"[^a-z0-9]", "", line.lower())
            if i + 1 < len(group_lines):
                next_normalised = re.sub(r"[^a-z0-9]", "", group_lines[i + 1].lower())
                if next_normalised and normalised and next_normalised == normalised:
                    # Duplicate label detected — skip the duplicate
                    collapsed.append(line)
                    i += 2
                    continue
            collapsed.append(line)
            i += 1

        # Second pass: collapse within a single line that has repeated label parts.
        # e.g. "SED RATE BY MODIFIED WESTERGREN SED RATE BY MODIFIED WESTERGREN 6"
        result: list[str] = []
        for line in collapsed:
            # Try to detect a repeated label prefix in the joined text.
            # Pattern: a long alpha sequence appears twice at the start.
            tokens = line.split()
            if len(tokens) >= 6:
                # Try splitting tokens at various prefix lengths and look for repetition
                for prefix_len in range(2, min(len(tokens) // 2 + 1, 8)):
                    prefix = tokens[:prefix_len]
                    prefix_text = " ".join(prefix).lower()
                    rest = tokens[prefix_len:]
                    rest_text = " ".join(rest).lower()
                    if prefix_text in rest_text and all(
                        t.replace(",", "").replace(".", "").isalpha() or t.isdigit()
                        for t in prefix
                    ):
                        # Found a repeated label prefix — keep just one copy
                        line = " ".join(prefix + rest)
                        break
            result.append(line)
        return result

    def _normalize_raw_label(
        self,
        candidate_text: str,
        classification: dict[str, Any],
    ) -> str | None:
        """v12 wave-7: rewrite the raw label for immunology and LabTesting resolver
        compatibility.  This runs AFTER classification but BEFORE the row dict is
        built so the resolver sees the canonical form.

        Known rewrites:
        - ``Abs. CD8 Suppressor`` → ``Abs. CD 8 Suppressor``
        - ``Absolute CD8 Suppressor`` → ``Absolute CD 8 Suppressor``
        - ``Absolute CD4 Helper`` → ``Absolute CD 4 Helper``
        - ``CD8`` → ``CD 8`` / ``CD4`` → ``CD 4`` (in immunology context)
        - LabTesting: when the row context indicates a percentage differential,
          ensure ``BASOPHILS`` gets the ``P`` suffix for resolver lookup
        - LabTesting: ``MAGNESIUM, RBC`` → ``MAGNESIUM RBC`` (remove comma for resolver)
        """
        raw_label = classification.get("raw_analyte_label", "")
        if not raw_label:
            return None

        lower = raw_label.lower().strip()

        # Immunology CD4 / CD8 spacing — ensure space between CD and digit
        # This is critical for the analyte resolver which expects "CD 4" / "CD 8".
        fixed = re.sub(r"\bcd(\d+)\b", r"CD \1", raw_label, flags=re.IGNORECASE)

        # LabTesting expects the historical RBMC spelling for resolver parity.
        fixed = re.sub(r"magnesium\s*,?\s*rbc\b", "MAGNESIUM RBMC", fixed, flags=re.IGNORECASE)

        # If the raw text looks like a differential percentage row and the label
        # is BASOPHILS, ensure it gets the "P" suffix the resolver expects.
        # This is detected by the presence of a % unit in the candidate text.
        if "basophil" in lower and "%" in candidate_text:
            if "basophils p" not in lower and "basophil p" not in lower:
                fixed = re.sub(
                    r"\bbasophils?\b", "BASOPHILS P", fixed, count=1, flags=re.IGNORECASE
                )

        # If nothing changed, return None so the caller knows to keep the original.
        if fixed == raw_label:
            return None

        return fixed

    def _is_measurement_continuation(self, line: str) -> bool:
        """Check if a line looks like a measurement continuation.

        Continuation lines include:
        - Unit-only lines (e.g., "mmol/L", "mg/dL")
        - Reference range fragments (e.g., "(135-145)")
        - Note/flag fragments (e.g., "H", "L", "*")
        """
        stripped = line.strip()
        if not stripped:
            return False

        # Check for unit patterns
        unit_patterns = (
            r"^[a-zA-Z°%µμ/]+$",  # Pure units like mmol/L, mg/dL, %
            r"^[a-zA-Z/]+\s*[²³]+$",  # Units with superscripts like m2
            r"^[a-zA-Z/]+\d+[a-zA-Z/]*$",  # Units with numbers like 1.73m2
        )
        for pattern in unit_patterns:
            if re.match(pattern, stripped):
                return True

        # Check for reference range fragments
        if re.match(r"^[\(\[]?\d[\d,.]*\s*[-–]\s*\d[\d,.]*[\)\]]?$", stripped):
            return True

        # Check for flag-only lines
        if re.match(r"^[HLA*\!]+$", stripped.upper()):
            return True

        return False

    # ------------------------------------------------------------------
    # v12 heading stripping (used by block fallback)
    # ------------------------------------------------------------------

    def _strip_heading_if_present(
        self,
        lines: list[str],
        family_adapter_id: str,
    ) -> list[str]:
        """Strip a heading/panel title from the first line if it looks like one.

        v12 repair: do NOT strip single-word lines like ``ACR`` or ``CRP`` that
        are valid analyte-first labels.  Only strip lines that are genuine panel
        headings: multi-word, predominantly uppercase, and *without* a value token.
        """
        if len(lines) < 2:
            return list(lines)

        first = lines[0]
        tokens = first.split()
        if len(tokens) > 5:
            return list(lines)

        # v12: single-token lines are almost never headings — they are analyte
        # labels like ``ACR``, ``CRP``, ``HbA1c``.  Never strip them UNLESS
        # they match a known section-heading keyword (e.g. ``BIOCHEMISTRY``).
        if len(tokens) == 1:
            first_lower = first.strip().lower()
            if first_lower in _SECTION_HEADING_KEYWORDS:
                return lines[1:]
            return list(lines)

        has_value = _contains_value_token_for_heading(first)

        alpha_tokens = [t for t in tokens if any(c.isalpha() for c in t)]
        if alpha_tokens and not has_value:
            caps_ratio = sum(1 for t in alpha_tokens if t.isupper()) / len(alpha_tokens)
            if caps_ratio >= 0.5:
                return lines[1:]

        if len(tokens) <= 4 and not has_value:
            if len(first) > 15 and any(c.isupper() for c in first):
                return lines[1:]

        return list(lines)

    # ------------------------------------------------------------------
    # v12: BLOCK-LOCAL candidate arbitration (not global)
    # ------------------------------------------------------------------

    def _arbitrate_candidates(
        self,
        rows: list[dict[str, Any]],
        artifact: Any,
    ) -> list[dict[str, Any]]:
        """Block-local arbitration: score candidates within each analyte family
        and prune only true shadow rows.

        Rules:
        1. Value-bearing beats label-only.
        2. Clean analyte text beats panel/header-prefixed analyte text.
        3. Dual-unit / fuller unit context beats truncated context.
        4. A merged fallback row is suppressed when page-level recovery
           already produced 2+ complete measurement rows for the same block.

        v12 wave-6: replace length-only page-vs-block dominance with
        cleanliness-aware suppression.  Cleaner overlapping measured rows
        (no heading-prefix contamination, not derived_observation_unbound,
        not duplicate-label rows) beat heading-prefixed REF. RANGES /
        Diagnostic Values / SAMPLE shadows.
        """
        if not rows:
            return rows

        # Separate page-level (from _iter_candidates) from block fallback
        page_level: list[dict[str, Any]] = []
        block_fallback: list[dict[str, Any]] = []
        fenced: list[dict[str, Any]] = []

        for row in rows:
            source_kind = row.get("_source_kind", "")
            if source_kind == "block_fallback":
                block_fallback.append(row)
            elif source_kind in ("geometry", "table", "text", "block"):
                page_level.append(row)
            else:
                # Fenced rows (admin, narrative, etc.) — keep as-is
                fenced.append(row)

        # v12 wave-12: restructured early-return so overlap clustering and
        # cleanliness suppression ALWAYS run for normalizable page-level
        # candidates.  The previous guard returned before overlap clustering
        # when block_fallback was empty, allowing threshold-shadow rows like
        # the HbA1c category table row to survive unfiltered.
        if not block_fallback:
            # Skip block-fallback-specific suppression, but still run
            # overlap clustering on page-level normalizable candidates.
            final_page, final_block, used = self._overlap_cluster(
                page_level,
                [],
                normalizable_row_types=NORMALIZABLE_ROW_TYPES,
            )
            final_rows = final_page + final_block + fenced
            final_rows = self._deduplicate_adjacent_labels(final_rows)
            return self._strip_arbitration_metadata(final_rows)

        # --- v12 wave-6: Cleanliness-aware page-vs-block suppression ---
        # Instead of simple length-based dominance, score page-level rows
        # and block-fallback rows by cleanliness.  Rows with heading-prefix
        # contamination, derived_observation_unbound status, or duplicate
        # labels are suppressed in favour of cleaner measured rows.
        page_complete = [r for r in page_level if r["row_type"] in NORMALIZABLE_ROW_TYPES]

        # v12 wave-6: heading-prefix contamination patterns
        _HEADING_PREFIX_KEYWORDS = {
            "ref", "ref.", "ranges", "special", "chemistry", "specimen",
            "whole", "blood", "serum", "plasma", "urine", "diagnostic",
            "values", "of", "in", "adults", "ngsp", "ifcc",
        }
        _SAMPLE_SHADOW_WORDS = {"sample"}
        _REF_RANGE_SHADOW_WORDS = {"ref.", "ranges", "reference"}

        def _cleanliness_score(row: dict[str, Any]) -> tuple[int, int, int]:
            """Higher cleanliness = better.  Tuple is compared ascending
            so we can use min() to find the cleanest row."""
            raw_text = (row.get("raw_text") or "").lower()
            raw_label = (row.get("raw_analyte_label") or "").lower()
            combined = f"{raw_label} {raw_text}"

            # Penalties (lower score = more penalties = worse cleanliness)
            heading_penalty = 0
            for kw in _HEADING_PREFIX_KEYWORDS:
                if kw in combined:
                    heading_penalty += 1

            sample_penalty = 1 if any(w in combined for w in _SAMPLE_SHADOW_WORDS) else 0
            ref_range_penalty = 1 if any(w in combined for w in _REF_RANGE_SHADOW_WORDS) else 0

            # v12 wave-6: derived_observation_unbound label-row penalty
            support_code = row.get("support_code", "")
            failure_code = row.get("failure_code") or ""
            derived_penalty = 0
            if "derived_observation_unbound" in failure_code or "derived_observation_unbound" in support_code:
                derived_penalty = 1

            has_value = 1 if row.get("raw_value_string") else 0
            return (
                has_value,  # Prefer rows with values
                heading_penalty + sample_penalty + ref_range_penalty + derived_penalty,  # Lower contamination
                len(row.get("raw_text") or ""),  # Tie-break: longer text
            )

        # --- Determine which blocks have strong page-level coverage ---
        page_by_block: dict[str, list[dict]] = {}
        for r in page_complete:
            bid = r.get("block_id", "")
            page_by_block.setdefault(bid, []).append(r)

        blocks_with_strong_page_coverage: set[str] = set()
        for bid, prs in page_by_block.items():
            values = sum(1 for r in prs if r.get("raw_value_string") is not None)
            if len(prs) >= 2 and values >= 2:
                blocks_with_strong_page_coverage.add(bid)

        # --- Suppress page-level label-only shadows for analytes where a
        #     block-fallback row carries a measured value.
        block_value_analytes: set[str] = set()
        for br in block_fallback:
            if br.get("raw_value_string") is not None:
                br_label = (br.get("raw_analyte_label") or "").strip()
                key = br_label.split()[0].lower() if br_label else ""
                if key:
                    block_value_analytes.add(key)

        if block_value_analytes:
            filtered_page: list[dict[str, Any]] = []
            for pr in page_level:
                if pr.get("raw_value_string") is not None:
                    filtered_page.append(pr)
                    continue
                pr_label = (pr.get("raw_analyte_label") or "").strip()
                pr_key = pr_label.split()[0].lower() if pr_label else ""
                if pr_key in block_value_analytes:
                    continue  # suppressed: block has measured value for this analyte
                filtered_page.append(pr)
            page_level = filtered_page

        # --- Suppress threshold-shadow fallback rows for analytes that
        #     already have a clean measured value in page-level rows.
        page_value_analytes: set[str] = set()
        for pr in page_level:
            if pr.get("raw_value_string") is not None:
                pr_label = (pr.get("raw_analyte_label") or "").strip()
                key = pr_label.split()[0].lower() if pr_label else ""
                if key:
                    page_value_analytes.add(key)

        if page_value_analytes:
            filtered_block: list[dict[str, Any]] = []
            for br in block_fallback:
                if br.get("raw_value_string") is None:
                    # No value — check for threshold-shadow / heading-prefixed contamination
                    br_label = (br.get("raw_analyte_label", "") or "").strip()
                    br_key = br_label.split()[0].lower() if br_label else ""
                    if br_key in page_value_analytes:
                        # This is a threshold-shadow or heading-shadow for an analyte
                        # that already has a measured value — suppress it.
                        continue
                    # v12 wave-5: also suppress if label is heavily heading-contaminated
                    if br_label:
                        label_words = set(br_label.lower().split())
                        heading_overlap = label_words & _HEADING_PREFIX_KEYWORDS
                        if len(heading_overlap) >= 3 and br_key in page_value_analytes:
                            continue
                filtered_block.append(br)
            block_fallback = filtered_block

        # --- v12 wave-7: Containment-based overlap suppression ---
        # Replace wave-6 key-based logic with explicit overlap-by-text/label
        # containment plus cleanliness scoring.  A cleaner overlapping measured
        # row suppresses dirty REF. RANGES / Diagnostic Values / SAMPLE /
        # derived_observation_unbound shadows even when the first tokens differ.

        _SHADOW_PATTERNS = {
            "ref. ranges", "reference ranges", "diagnostic values",
            "normal", "ifg", "prediabetes", "adults",
            "ngsp", "ifcc", "sample report", "sample",
        }

        def _core_analyte_label(row: dict[str, Any]) -> str:
            """Extract a normalized analyte label for overlap comparison.

            v12 wave-9: the normalization regex preserves CJK characters
            (U+4E00–U+9FFF) and common CJK punctuation so that bilingual
            labels like ``HbA1c 葡萄糖血红蛋白`` do not lose their CJK
            identity.  This lets the suffix/containment overlap check fire
            when a Chinese-only row (``葡萄糖血红蛋白``) coexists with
            its bilingual counterpart.
            """
            raw_label = (row.get("raw_analyte_label") or "").strip()
            # Preserve ASCII digits, lowercase Latin, and CJK characters
            # along with common CJK punctuation.
            normalized = re.sub(
                r"[^a-z0-9\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+",
                " ",
                raw_label.lower(),
            ).strip()
            if not normalized:
                normalized = raw_label.lower().strip()
            if not normalized:
                return ""
            for shadow in sorted(_SHADOW_PATTERNS, key=len, reverse=True):
                shadow_norm = re.sub(r"[^a-z0-9]+", " ", shadow.lower()).strip()
                if shadow_norm and normalized.startswith(f"{shadow_norm} "):
                    normalized = normalized[len(shadow_norm):].strip()
                    break
            # v12 wave-9: if ASCII+CJK normalization still emptied the
            # label (unexpected, but defensive), fall back to the full
            # non-ASCII label so overlap comparison never gets an empty key.
            if not normalized and raw_label.strip():
                return raw_label.strip().lower()
            return normalized

        def _rows_overlap(
            a: dict[str, Any],
            b: dict[str, Any],
        ) -> bool:
            """Return True if two rows refer to the same analyte by text containment."""
            a_text = (a.get("raw_text") or "").lower()
            b_text = (b.get("raw_text") or "").lower()
            a_label = _core_analyte_label(a)
            b_label = _core_analyte_label(b)

            # Direct label match
            if a_label and b_label and a_label == b_label:
                return True

            # Containment: one row's label is inside the other's text
            if a_label and len(a_label) >= 2 and a_label in b_text:
                return True
            if b_label and len(b_label) >= 2 and b_label in a_text:
                return True

            # ACR special: "acr" matches "albumin and creatinine ratio (acr)"
            a_full = (a.get("raw_analyte_label") or "").lower()
            b_full = (b.get("raw_analyte_label") or "").lower()
            if a_label == "acr" and ("albumin" in b_full or "creatinine" in b_full):
                return True
            if b_label == "acr" and ("albumin" in a_full or "creatinine" in a_full):
                return True

            # HbA1c special: "hba1c" matches "hba1c" anywhere
            if "hba1c" in a_text and "hba1c" in b_text:
                return True

            return False

        def _cleanliness_score_v2(row: dict[str, Any]) -> tuple[int, int, int, int]:
            """Score cleanliness — higher is cleaner."""
            raw_text = (row.get("raw_text") or "").lower()
            raw_label = (row.get("raw_analyte_label") or "").lower()
            combined = f"{raw_label} {raw_text}"
            token_set = set(re.findall(r"[a-z0-9\u4e00-\u9fff\u3000-\u303f\ufeff-\uffef]+", combined))
            score = 0

            # Has value = +10
            if row.get("raw_value_string"):
                score += 10

            if row.get("raw_unit_string"):
                score += 4
            if row.get("raw_reference_range"):
                score += 2

            # Shadow penalties
            has_value = 1 if row.get("raw_value_string") else 0
            heading_penalty = 0
            for kw in _HEADING_PREFIX_KEYWORDS:
                kw_tokens = [token for token in re.findall(r"[a-z0-9]+", kw.lower()) if token]
                if kw_tokens and all(token in token_set for token in kw_tokens):
                    heading_penalty += len(kw_tokens)
            sample_penalty = 3 if "sample" in token_set else 0
            ref_range_penalty = 1 if any(
                all(token in token_set for token in re.findall(r"[a-z0-9]+", word.lower()))
                for word in _REF_RANGE_SHADOW_WORDS
            ) else 0
            derived_penalty = 0
            fc = row.get("failure_code") or ""
            sc = row.get("support_code") or ""
            if "derived_observation_unbound" in fc or "derived_observation_unbound" in sc:
                derived_penalty = 5

            score -= (heading_penalty + sample_penalty + ref_range_penalty + derived_penalty)

            # Clean analyte-only labels get a bonus
            if has_value and heading_penalty == 0 and sample_penalty == 0 and ref_range_penalty == 0:
                score += 5

            return (
                score,
                1 if row.get("raw_unit_string") else 0,
                1 if row.get("raw_reference_range") else 0,
                len(row.get("raw_text") or ""),
            )

        # Collect all normalizable rows from both pools
        all_candidates = [r for r in page_level + block_fallback if r["row_type"] in NORMALIZABLE_ROW_TYPES]

        # Group candidates into overlap clusters
        used: set[int] = set()
        survivors: list[dict[str, Any]] = []

        for i, candidate in enumerate(all_candidates):
            if i in used:
                continue

            cluster = [candidate]
            cluster_scores = [_cleanliness_score_v2(candidate)]
            cluster_indices = [i]

            for j in range(i + 1, len(all_candidates)):
                if j in used:
                    continue
                other = all_candidates[j]
                # v12 wave-14: transitive overlap — check against ANY cluster member,
                # not just the seed.  This prevents a threshold-shadow row from
                # escaping suppression by overlapping only with an intermediate
                # contaminated row that itself overlaps with the seed.
                if any(_rows_overlap(member, other) for member in cluster):
                    cluster.append(other)
                    cluster_scores.append(_cleanliness_score_v2(other))
                    cluster_indices.append(j)

            # Keep the cleanest candidate in the cluster
            best_idx = cluster_scores.index(max(cluster_scores))
            survivors.append(cluster[best_idx])
            used.update(cluster_indices)

        # Rebuild page_level and block_fallback from survivors
        final_page = [r for r in page_level if r["row_type"] not in NORMALIZABLE_ROW_TYPES]
        final_block = [r for r in block_fallback if r["row_type"] not in NORMALIZABLE_ROW_TYPES]

        for s in survivors:
            # Check if this survivor came from page_level or block_fallback originally
            if s.get("_source_kind") in ("geometry", "table", "text", "block"):
                final_page.append(s)
            else:
                final_block.append(s)

        # --- Deduplicate adjacent label rows (v12 wave-6: mechanic 5) ---
        # Collapse duplicated adjacent label lines before returning final rows.
        final_rows = final_page + final_block + fenced
        final_rows = self._deduplicate_adjacent_labels(final_rows)

        return self._strip_arbitration_metadata(final_rows)

    # ------------------------------------------------------------------
    # v12 wave-12: extracted overlap-clustering so it can run even when
    # block_fallback is empty (the page-level-only path).
    # ------------------------------------------------------------------

    def _overlap_cluster(
        self,
        page_level: list[dict[str, Any]],
        block_fallback: list[dict[str, Any]],
        *,
        normalizable_row_types: set[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[int]]:
        """Run containment-based overlap clustering on combined candidates.

        Returns ``(final_page, final_block, used_indices)`` so callers can
        optionally chain further suppression logic.
        """
        _SHADOW_PATTERNS = {
            "ref. ranges", "reference ranges", "diagnostic values",
            "normal", "ifg", "prediabetes", "adults",
            "ngsp", "ifcc", "sample report", "sample",
        }
        _HEADING_PREFIX_KEYWORDS = {
            "ref", "ref.", "ranges", "special", "chemistry", "specimen",
            "whole", "blood", "serum", "plasma", "urine", "diagnostic",
            "values", "of", "in", "adults", "ngsp", "ifcc",
        }
        _REF_RANGE_SHADOW_WORDS = {"ref.", "ranges", "reference"}

        def _core_analyte_label(row: dict[str, Any]) -> str:
            raw_label = (row.get("raw_analyte_label") or "").strip()
            normalized = re.sub(
                r"[^a-z0-9\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+",
                " ",
                raw_label.lower(),
            ).strip()
            if not normalized:
                normalized = raw_label.lower().strip()
            if not normalized:
                return ""
            for shadow in sorted(_SHADOW_PATTERNS, key=len, reverse=True):
                shadow_norm = re.sub(r"[^a-z0-9]+", " ", shadow.lower()).strip()
                if shadow_norm and normalized.startswith(f"{shadow_norm} "):
                    normalized = normalized[len(shadow_norm):].strip()
                    break
            if not normalized and raw_label.strip():
                return raw_label.strip().lower()
            return normalized

        def _rows_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
            a_text = (a.get("raw_text") or "").lower()
            b_text = (b.get("raw_text") or "").lower()
            a_label = _core_analyte_label(a)
            b_label = _core_analyte_label(b)
            if a_label and b_label and a_label == b_label:
                return True
            if a_label and len(a_label) >= 2 and a_label in b_text:
                return True
            if b_label and len(b_label) >= 2 and b_label in a_text:
                return True
            a_full = (a.get("raw_analyte_label") or "").lower()
            b_full = (b.get("raw_analyte_label") or "").lower()
            if a_label == "acr" and ("albumin" in b_full or "creatinine" in b_full):
                return True
            if b_label == "acr" and ("albumin" in a_full or "creatinine" in a_full):
                return True
            if "hba1c" in a_text and "hba1c" in b_text:
                return True
            return False

        def _cleanliness_score_v2(row: dict[str, Any]) -> tuple[int, int, int, int]:
            raw_text = (row.get("raw_text") or "").lower()
            raw_label = (row.get("raw_analyte_label") or "").lower()
            combined = f"{raw_label} {raw_text}"
            token_set = set(re.findall(r"[a-z0-9\u4e00-\u9fff\u3000-\u303f\ufeff-\uffef]+", combined))
            score = 0
            if row.get("raw_value_string"):
                score += 10
            if row.get("raw_unit_string"):
                score += 4
            if row.get("raw_reference_range"):
                score += 2
            has_value = 1 if row.get("raw_value_string") else 0
            heading_penalty = 0
            for kw in _HEADING_PREFIX_KEYWORDS:
                kw_tokens = [token for token in re.findall(r"[a-z0-9]+", kw.lower()) if token]
                if kw_tokens and all(token in token_set for token in kw_tokens):
                    heading_penalty += len(kw_tokens)
            sample_penalty = 3 if "sample" in token_set else 0
            ref_range_penalty = 1 if any(
                all(token in token_set for token in re.findall(r"[a-z0-9]+", word.lower()))
                for word in _REF_RANGE_SHADOW_WORDS
            ) else 0
            derived_penalty = 0
            fc = row.get("failure_code") or ""
            sc = row.get("support_code") or ""
            if "derived_observation_unbound" in fc or "derived_observation_unbound" in sc:
                derived_penalty = 5
            score -= (heading_penalty + sample_penalty + ref_range_penalty + derived_penalty)
            if has_value and heading_penalty == 0 and sample_penalty == 0 and ref_range_penalty == 0:
                score += 5
            return (
                score,
                1 if row.get("raw_unit_string") else 0,
                1 if row.get("raw_reference_range") else 0,
                len(row.get("raw_text") or ""),
            )

        all_candidates = [r for r in page_level + block_fallback if r["row_type"] in normalizable_row_types]

        used: set[int] = set()
        survivors: list[dict[str, Any]] = []

        for i, candidate in enumerate(all_candidates):
            if i in used:
                continue
            cluster = [candidate]
            cluster_scores = [_cleanliness_score_v2(candidate)]
            cluster_indices = [i]
            for j in range(i + 1, len(all_candidates)):
                if j in used:
                    continue
                other = all_candidates[j]
                # v12 wave-14: transitive overlap — check against ANY cluster member,
                # not just the seed.  This prevents a threshold-shadow row from
                # escaping suppression by overlapping only with an intermediate
                # contaminated row that itself overlaps with the seed.
                if any(_rows_overlap(member, other) for member in cluster):
                    cluster.append(other)
                    cluster_scores.append(_cleanliness_score_v2(other))
                    cluster_indices.append(j)
            best_idx = cluster_scores.index(max(cluster_scores))
            survivors.append(cluster[best_idx])
            used.update(cluster_indices)

        final_page = [r for r in page_level if r["row_type"] not in normalizable_row_types]
        final_block = [r for r in block_fallback if r["row_type"] not in normalizable_row_types]

        for s in survivors:
            if s.get("_source_kind") in ("geometry", "table", "text", "block"):
                final_page.append(s)
            else:
                final_block.append(s)

        return final_page, final_block, used

    def _deduplicate_adjacent_labels(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse duplicated adjacent label rows so analytes like SED RATE
        and MAGNESIUM RBC do not repeat their label twice.

        v12 wave-6: when two adjacent rows share the same normalized analyte
        label and only one carries a value, merge them into a single row
        with the value.  If both carry values, keep the cleaner one.
        """
        if len(rows) <= 1:
            return rows

        result: list[dict[str, Any]] = []
        i = 0
        while i < len(rows):
            current = rows[i]
            current_label = (current.get("raw_analyte_label") or "").strip().lower()
            if not current_label or i == len(rows) - 1:
                result.append(current)
                i += 1
                continue

            # Look at next row
            next_row = rows[i + 1]
            next_label = (next_row.get("raw_analyte_label") or "").strip().lower()

            if current_label == next_label:
                # Same analyte — deduplicate
                current_has_value = current.get("raw_value_string") is not None
                next_has_value = next_row.get("raw_value_string") is not None

                if not current_has_value and next_has_value:
                    # Next row has the value — keep it instead of current
                    result.append(next_row)
                elif current_has_value and not next_has_value:
                    # Current has the value — keep current
                    result.append(current)
                elif current_has_value and next_has_value:
                    # Both have values — keep the one with cleaner text
                    current_text = current.get("raw_text") or ""
                    next_text = next_row.get("raw_text") or ""
                    if len(next_text) > len(current_text):
                        result.append(next_row)
                    else:
                        result.append(current)
                else:
                    # Neither has value — keep the first one
                    result.append(current)
                i += 2  # Skip both rows (we merged them)
            else:
                result.append(current)
                i += 1

        return result

    @staticmethod
    def _candidate_score(row: dict[str, Any]) -> tuple[int, int, int]:
        """Score a block-fallback candidate for arbitration.

        Higher is better:
        - value-bearing (has raw_value_string) → +10
        - longer unit context (raw_unit_string not None) → +5
        - longer text (more context) → +len(text)
        """
        has_value = 10 if row.get("raw_value_string") is not None else 0
        has_unit = 5 if row.get("raw_unit_string") is not None else 0
        text_len = len(row.get("raw_text", ""))
        return (has_value, has_unit, text_len)

    @staticmethod
    def _strip_arbitration_metadata(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove internal arbitration metadata from final rows."""
        for row in rows:
            row.pop("_source_kind", None)
            row.pop("_is_heading_stripped", None)
        return rows

    # ------------------------------------------------------------------
    # Hash utility
    # ------------------------------------------------------------------

    @staticmethod
    def _row_hash(artifact: Any, raw_text: str, row_type: str) -> str:
        """Compute a stable hash for deduplication."""
        page_id = getattr(artifact, "page_id", f"page-{artifact.page_number}")
        return sha256(
            f"{page_id}:{row_type}:{raw_text}".encode("utf-8")
        ).hexdigest()

    # ------------------------------------------------------------------
    # v12 wave-4: unit fragment and threshold-shadow helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_unit_superscript_fragments(text: str) -> str:
        """Collapse a space before a trailing digit that is a superscript artifact.

        Fixes cases like ``mL/min/1.73m 2`` → ``mL/min/1.73m2`` that arise
        when PDF text extraction splits a unit's superscript into a separate
        token.
        """
        return _collapse_unit_superscript_artifacts(text)
