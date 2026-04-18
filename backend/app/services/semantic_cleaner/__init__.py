"""Pre-processing semantic cleaner for extracting true lab rows and normalizing names."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from typing import Any

from app.config import settings
from app.services.data_paths import resolve_data_file
from app.services.vlm_gateway import VLMAPIError, VLMParsingError, generate_text_with_qwen

logger = logging.getLogger(__name__)

_LLM_BATCH_SIZE = 15
_LLM_RETRY_ATTEMPTS = 3
_LLM_RETRY_BACKOFF_S = 2.0
_TRAILING_FLAG_RE = re.compile(r"\s+[HL]$", re.IGNORECASE)

_CONTEXT_TOKENS = {
    "blood",
    "level",
    "levels",
    "plasma",
    "reference",
    "result",
    "results",
    "serum",
    "specimen",
    "test",
    "tests",
    "unit",
    "units",
    "value",
}

_TRAILING_QUALIFIER_TOKENS = {
    "s",
    "p",
    "u",
    "wb",
    "ifcc",
    "dcct",
    "epi",
    "ckd",
    "calc",
    "calculated",
}

_NOISE_PREFIXES = (
    "ref :",
    "dob :",
    "ic no",
    "collected :",
    "referred :",
    "report printed :",
    "source:",
)

_NOISE_MARKERS = (
    "clinical practice guidelines",
    "courier run",
    "kdigo",
    "not valid for pregnant",
    "ward : lab no",
)

_NOISE_LABELS = {
    "<",
    "<=",
    ">",
    ">=",
    "collected",
    "dob",
    "normal",
    "referred",
    "ref",
    "report printed",
    "source",
}

_ADDRESS_FRAGMENT_RE = re.compile(r"\b(city|state|st|zip|jalan|petaling|sel)\b", re.IGNORECASE)
_DATE_TOKEN_RE = re.compile(r"^\d{1,4}[/-]\d{1,2}(?:[/-]\d{1,4})?$")
_TIME_TOKEN_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")
_LIKELY_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")


def _ascii_fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(
        char for char in normalized if not unicodedata.combining(char) and ord(char) < 128
    )


def _normalize_analyte_shortcuts(value: str) -> str:
    normalized = re.sub(r"\bhaemoglobin\s*a\s*1\s*c\b", "hba1c", value)
    normalized = re.sub(r"\bhemoglobin\s*a\s*1\s*c\b", "hba1c", normalized)
    normalized = re.sub(r"\bhb\s*a\s*1\s*c\b", "hba1c", normalized)
    normalized = re.sub(r"\ba\s*1\s*c\b", "hba1c", normalized)
    normalized = re.sub(
        r"\bestimated\s+glomerular\s+filtration\s+rate\b",
        "egfr",
        normalized,
    )
    normalized = re.sub(r"\be\s*gfr\b", "egfr", normalized)
    normalized = re.sub(
        r"\blow\s+density\s+lipoprotein\s+cholesterol\b",
        "ldl c",
        normalized,
    )
    normalized = re.sub(
        r"\bhigh\s+density\s+lipoprotein\s+cholesterol\b",
        "hdl c",
        normalized,
    )
    normalized = re.sub(r"\bldl\s+cholesterol\b", "ldl c", normalized)
    normalized = re.sub(r"\bhdl\s+cholesterol\b", "hdl c", normalized)
    normalized = re.sub(r"\begfr\s+ckd\s+epi\b", "egfr", normalized)
    normalized = re.sub(r"\begfr\s+epi\b", "egfr", normalized)
    normalized = re.sub(r"\bhba1c\s+ifcc\b", "hba1c", normalized)
    normalized = re.sub(r"\bhba1c\s+dcct\b", "hba1c", normalized)
    return normalized


class SemanticCleaner:
    def __init__(self) -> None:
        self._canonical_names, self._alias_to_canonical = self._load_alias_mapping()
        if not self._canonical_names:
            self._canonical_names = self._load_core_metric_names()

    def _load_alias_mapping(self) -> tuple[list[str], dict[str, str]]:
        alias_path = resolve_data_file(
            __file__,
            "alias_tables",
            "launch_scope_analyte_aliases.json",
        )

        canonical_names: list[str] = []
        alias_to_canonical: dict[str, str] = {}
        try:
            payload = json.loads(alias_path.read_text(encoding="utf-8"))
            raw_analytes = payload.get("analytes", [])
            if not isinstance(raw_analytes, list):
                return [], {}

            for analyte in raw_analytes:
                if not isinstance(analyte, dict):
                    continue

                canonical = self._normalize_label(analyte.get("canonical_label", ""))
                if not canonical:
                    continue

                canonical_names.append(canonical)
                alias_to_canonical[canonical] = canonical

                for alias in analyte.get("aliases", []):
                    normalized_alias = self._normalize_label(alias)
                    if normalized_alias:
                        alias_to_canonical[normalized_alias] = canonical

                for code in analyte.get("codes", []):
                    normalized_code = self._normalize_label(code)
                    if normalized_code:
                        alias_to_canonical[normalized_code] = canonical

            # Preserve insertion order while deduplicating.
            unique_names = list(dict.fromkeys(canonical_names))
            return unique_names, alias_to_canonical
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("Failed to load launch alias mapping for semantic cleaner: %s", exc)
            return [], {}

    def _load_core_metric_names(self) -> list[str]:
        metrics_path = resolve_data_file(
            __file__,
            "metric_definitions",
            "core_metrics.json",
        )
        try:
            payload = json.loads(metrics_path.read_text(encoding="utf-8"))
            names = [
                self._normalize_label(m.get("canonical_name", ""))
                for m in payload
                if isinstance(m, dict)
            ]
            return [name for name in names if name]
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("Failed to load core_metrics for semantic cleaner: %s", exc)
            return []

    async def clean(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter noise rows deterministically and normalize labels with LLM."""
        if not rows:
            return []

        # We want to normalize all valid rows against the canonical lists.
        # First deterministic filter.
        cleaned_rows: list[dict[str, Any]] = []
        unresolved_rows: list[tuple[int, dict[str, Any]]] = []

        for index, source_row in enumerate(rows):
            row = dict(source_row)
            raw_text = str(row.get("raw_text") or "")
            raw_label = str(row.get("raw_analyte_label") or "")

            if self._is_noise_text(raw_text) or self._is_noise_label(raw_label):
                continue

            canonical = self._map_to_canonical(raw_label)
            if canonical:
                row["raw_analyte_label"] = canonical
                cleaned_rows.append(row)
                continue

            if not self._looks_like_measurement(row) and not self._looks_like_analyte_label(
                raw_label
            ):
                continue

            normalized_label = self._normalize_label(raw_label)
            if not normalized_label or not self._looks_like_analyte_label(normalized_label):
                continue

            unresolved_rows.append((index, row))

        if not unresolved_rows:
            return cleaned_rows

        if not settings.qwen_api_key:
            logger.debug("Skipping semantic cleaner LLM pass: Qwen API key is not configured")
            for _, r in unresolved_rows:
                cleaned_rows.append(r)
            return cleaned_rows

        # Batch unresolved rows to keep per-call latency low and parallelize.
        batches = [
            unresolved_rows[i : i + _LLM_BATCH_SIZE]
            for i in range(0, len(unresolved_rows), _LLM_BATCH_SIZE)
        ]
        batch_results = await asyncio.gather(
            *(self._resolve_batch(batch) for batch in batches),
            return_exceptions=False,
        )
        combined: dict[int, dict[str, Any]] = {}
        for result_map in batch_results:
            combined.update(result_map)

        for index, row in unresolved_rows:
            llm_output = combined.get(index)
            if llm_output is None:
                # LLM failed for this row — keep raw so downstream can still try
                cleaned_rows.append(row)
                continue
            if not bool(llm_output.get("is_valid_result", False)):
                continue
            normalized_name = str(llm_output.get("normalized_analyte_name") or "").strip()
            if normalized_name:
                row["raw_analyte_label"] = self._coerce_label(normalized_name)
            cleaned_rows.append(row)
        return cleaned_rows

    async def _resolve_batch(
        self, batch: list[tuple[int, dict[str, Any]]]
    ) -> dict[int, dict[str, Any]]:
        """Run LLM pass on a batch with retry + backoff. Returns empty dict on failure."""
        prompt_rows = [
            {
                "index": index,
                "raw_text": row.get("raw_text", ""),
                "raw_analyte_label": row.get("raw_analyte_label", ""),
                "raw_value_string": row.get("raw_value_string", ""),
                "raw_unit_string": row.get("raw_unit_string", ""),
            }
            for index, row in batch
        ]
        canonical_hint = ", ".join(self._canonical_names) or "(canonical list unavailable)"
        prompt = (
            "ROLE: You are a clinical laboratory data normalizer. Your output drives a patient-"
            "facing health report; precision matters more than recall.\n\n"
            "INPUT: A batch of rows extracted from one or more lab reports. Each row has a raw "
            "label (the printed analyte name, possibly bilingual, abbreviated, OCR-noisy, or "
            "padded with method/specimen qualifiers), a raw value, a raw unit, and the surrounding "
            "raw line text.\n\n"
            "TASK PER ROW:\n"
            "1. CLASSIFY: Decide whether this row reports a measured laboratory analyte result.\n"
            "   - Set is_valid_result=true ONLY if the row clearly carries a result for a clinical "
            "lab analyte (numeric, ratio, comparator like '<0.1' or '>90', enumerated qualitative "
            "like 'Positive'/'Negative'/'Reactive'/'Non Reactive'/'Absent'/'Present (+)'/"
            "'Trace'/'Nil'/'Pale Yellow'/'Clear'/'Normochromic Normocytic', or descriptive "
            "morphology rows that ARE the analyte's reported result).\n"
            "   - Set is_valid_result=false for ANY of: report headers, lab/clinic name, address, "
            "phone, fax, accession/specimen ID, patient demographics, doctor/physician name, "
            "collection or report timestamps, page numbers, footers, methodology disclaimers, "
            "interpretation tables that list category cutoffs (e.g. 'Desirable: <200; Borderline: "
            "200-239'), reference-range legends without a measured value, signatures, "
            "advertisements, regulatory text, or duplicate trace lines from instrument output.\n\n"
            "2. NORMALIZE NAME (only when valid): Produce 'normalized_analyte_name' as the "
            "canonical English clinical name.\n"
            "   - Translate non-English labels (Vietnamese, Chinese, Spanish, French, Portuguese, "
            "Indonesian, Malay, Thai, Hindi, etc.) to standard English clinical terminology. "
            "Examples: 'Cholestérol total' -> 'Total Cholesterol'; "
            "'血红蛋白' -> 'Hemoglobin'; 'Glucose à jeun' -> 'Glucose, fasting'; "
            "'Hồng cầu' -> 'Red Blood Cell Count'; 'Đường huyết lúc đói' -> 'Glucose, fasting'.\n"
            "   - Strip method/specimen suffixes that don't change identity: 'IFCC', 'DCCT', "
            "'CKD-EPI', 'serum', 'plasma', 'whole blood', 'calc', 'calculated', 'enzymatic', "
            "'kinetic', '(S)', '(P)', '(WB)'.\n"
            "   - Expand standard abbreviations: BUN -> Blood Urea Nitrogen; AST/SGOT -> AST; "
            "ALT/SGPT -> ALT; HbA1c (% DCCT) and HbA1c (mmol/mol IFCC) BOTH stay as 'HbA1c' "
            "(units distinguish them downstream).\n"
            "   - Differentiate percentage vs absolute count differentials (e.g. 'Neutrophils' "
            "for percentage row vs 'Absolute Neutrophil Count' for /uL row) by inspecting the "
            "raw_unit_string.\n"
            "   - PREFER an exact match against the canonical list when one exists; otherwise "
            "emit the standard English name a clinician would write. Casing should be Title Case.\n"
            "   - Never invent an analyte not present in the input; never copy patient names or "
            "PHI into normalized_analyte_name.\n\n"
            "3. UNCERTAIN: If you cannot confidently identify the analyte (gibberish, severe OCR "
            "corruption, ambiguous), set is_valid_result=false rather than guessing. Garbage in "
            "the patient artifact is worse than a missed row.\n\n"
            f"CANONICAL LIST (prefer these names verbatim): {canonical_hint}\n\n"
            "OUTPUT FORMAT: Return a JSON object with a single key 'results' whose value is a "
            "list of objects. Each object MUST contain exactly these keys:\n"
            "  - index: integer matching the input row index\n"
            "  - is_valid_result: boolean\n"
            "  - normalized_analyte_name: string (canonical English name) or null when "
            "is_valid_result is false\n"
            "Do not include explanation, commentary, code fences, or extra keys.\n\n"
            f"INPUT ROWS:\n{json.dumps(prompt_rows, ensure_ascii=False, indent=2)}"
        )

        last_exc: Exception | None = None
        for attempt in range(1, _LLM_RETRY_ATTEMPTS + 1):
            try:
                response_text = await generate_text_with_qwen(
                    prompt, response_format={"type": "json_object"}
                )
                return self._parse_llm_results(response_text)
            except (VLMAPIError, VLMParsingError, json.JSONDecodeError) as exc:
                last_exc = exc
                if attempt < _LLM_RETRY_ATTEMPTS:
                    backoff = _LLM_RETRY_BACKOFF_S * attempt
                    logger.warning(
                        "Semantic cleaner batch attempt %d/%d failed (%s); retry in %.1fs",
                        attempt,
                        _LLM_RETRY_ATTEMPTS,
                        exc,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
        logger.error(
            "Semantic cleaner batch failed after %d attempts, passing rows through unmodified: %s",
            _LLM_RETRY_ATTEMPTS,
            last_exc,
        )
        return {}

    def _parse_llm_results(self, response_text: str) -> dict[int, dict[str, Any]]:
        cleaned_response = response_text.strip()
        # Strip code fences the model sometimes emits despite json_object mode.
        cleaned_response = re.sub(r"^```(?:json)?\s*", "", cleaned_response)
        cleaned_response = re.sub(r"```\s*$", "", cleaned_response)
        # Strip trailing commas.
        cleaned_response = re.sub(r",\s*([}\]])", r"\1", cleaned_response)

        try:
            payload = json.loads(cleaned_response)
        except json.JSONDecodeError:
            # Regex-harvest individual result objects so one malformed row
            # does not drop the entire batch.
            items: list[dict[str, Any]] = []
            for match in re.finditer(
                r"\{[^{}]*?\"index\"[^{}]*?\}",
                cleaned_response,
                flags=re.DOTALL,
            ):
                snippet = re.sub(r",\s*([}\]])", r"\1", match.group(0))
                try:
                    items.append(json.loads(snippet))
                except json.JSONDecodeError:
                    continue
            if not items:
                return {}
            payload = {"results": items}

        results = payload.get("results")
        if not isinstance(results, list):
            # Some models wrap under 'data' or omit the key.
            results = payload if isinstance(payload, list) else []

        parsed_results: dict[int, dict[str, Any]] = {}
        for item in results:
            if not isinstance(item, dict) or "index" not in item:
                continue
            try:
                parsed_results[int(item["index"])] = item
            except (TypeError, ValueError):
                continue
        return parsed_results

    def _normalize_label(self, value: object) -> str:
        raw_text = str(value or "").strip().lower()
        if not raw_text:
            return ""

        # Strip trailing H/L flag (high/low) before alias match
        raw_text = _TRAILING_FLAG_RE.sub("", raw_text).strip()

        folded = _ascii_fold(raw_text)
        normalized = re.sub(r"[^a-z0-9%]+", " ", folded)
        normalized = _normalize_analyte_shortcuts(normalized)
        tokens = [token for token in normalized.split() if token and token not in _CONTEXT_TOKENS]
        while len(tokens) > 1 and tokens[-1] in _TRAILING_QUALIFIER_TOKENS:
            tokens.pop()
        return " ".join(tokens)

    def _looks_like_analyte_label(self, label: str) -> bool:
        normalized = self._normalize_label(label)
        if not normalized:
            return False
        if normalized in _NOISE_LABELS:
            return False
        if normalized.isdigit() or _LIKELY_YEAR_RE.match(normalized):
            return False
        return bool(re.search(r"[a-z]", normalized))

    def _looks_like_measurement(self, row: dict[str, Any]) -> bool:
        parsed_numeric_value = row.get("parsed_numeric_value")
        if isinstance(parsed_numeric_value, (int, float)):
            return True

        raw_value = str(row.get("raw_value_string") or "").strip()
        if raw_value and not self._is_date_or_time_token(raw_value):
            if re.search(r"\d", raw_value):
                return True

        raw_text = str(row.get("raw_text") or "")
        if re.search(r"\d", raw_text) and re.search(r"[a-zA-Z%/\\]", raw_text):
            return True

        return False

    def _is_noise_text(self, text: str) -> bool:
        lowered = text.strip().lower()
        if not lowered:
            return True

        if any(lowered.startswith(prefix) for prefix in _NOISE_PREFIXES):
            return True

        if any(marker in lowered for marker in _NOISE_MARKERS):
            return True

        if _ADDRESS_FRAGMENT_RE.search(lowered):
            return True

        if lowered in {"reference range", "result units", "test result"}:
            return True

        if re.match(r"^(normal|ifg\s*\(prediabetes\)|dm\s*[><=])\b", lowered):
            return True

        return False

    def _is_noise_label(self, label: str) -> bool:
        normalized = self._normalize_label(label)
        if not normalized:
            return True

        if normalized in _NOISE_LABELS:
            return True

        if normalized.startswith(("dob", "ic no", "report printed", "ref", "source")):
            return True

        if any(marker in normalized for marker in ("kdigo", "guideline", "courier run")):
            return True

        return False

    def _is_date_or_time_token(self, token: str) -> bool:
        compact = token.strip().strip(",;:")
        return bool(_DATE_TOKEN_RE.match(compact) or _TIME_TOKEN_RE.match(compact))

    def _map_to_canonical(self, label: str) -> str | None:
        normalized = self._normalize_label(label)
        if not normalized:
            return None
        return self._alias_to_canonical.get(normalized)

    def _coerce_label(self, label: str) -> str:
        canonical = self._map_to_canonical(label)
        if canonical:
            return canonical
        return str(label).strip()
