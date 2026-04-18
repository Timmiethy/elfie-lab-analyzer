import asyncio
import base64
import io
import json
import logging
import re
from collections.abc import Mapping
from typing import Any

import httpx
import pdfplumber
from pydantic import BaseModel, Field, ValidationError

from app.config import settings

logger = logging.getLogger(__name__)
_SENSITIVE_HEADER_KEYS = frozenset({"authorization", "x-api-key"})


def _redact(headers: Mapping[str, Any] | None) -> dict[str, str]:
    if headers is None:
        return {}

    redacted: dict[str, str] = {}
    for key, value in headers.items():
        if str(key).lower() in _SENSITIVE_HEADER_KEYS:
            continue
        redacted[str(key)] = str(value)
    return redacted


class VLMRow(BaseModel):
    """A structured row extracted by the VLM."""

    analyte_name: str | None = Field(default=None, description="The name of the test or analyte")
    value: str | None = Field(default=None, description="The measured value")
    unit: str | None = Field(default=None, description="The unit of measurement")
    reference_range_raw: str | None = Field(default=None, description="The reference range")
    row_bbox_ymin_xmin_ymax_xmax: list[int] = Field(
        default_factory=lambda: [0, 0, 0, 0],
        description="Bounding box for the entire visual row: [ymin, xmin, ymax, xmax]",
    )
    confidence_score: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Confidence score for this extraction, from 0 to 100",
    )
    source_page: int = Field(
        default=1,
        ge=1,
        description="1-indexed PDF page number the row was extracted from",
    )


class VLMResponse(BaseModel):
    """The expected structured response from the VLM."""

    rows: list[VLMRow]


class VLMGatewayError(Exception):
    """Base exception for VLM Gateway failures."""


class VLMParsingError(VLMGatewayError):
    """Raised when structured output parsing fails."""


class VLMAPIError(VLMGatewayError):
    """Raised when the VLM API call fails."""


def _parse_vlm_json(content: str) -> dict[str, Any]:
    """Parse VLM JSON with lenient recovery.

    The model occasionally emits JSON with unescaped inner quotes,
    trailing commas, or stray backticks. Try strict first; if that
    fails, apply common fixes and try again. Finally, fall back to
    extracting individual row objects by regex so a single malformed
    row does not drop all 20+ rows on a page.
    """
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    cleaned = content
    # Strip stray code fences.
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned.strip())
    cleaned = re.sub(r"```\s*$", "", cleaned)
    # Trailing commas before ] or }.
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Last-resort row harvesting: extract every top-level object that
    # contains an analyte_name key.
    rows: list[dict[str, Any]] = []
    for match in re.finditer(
        r"\{[^{}]*?\"analyte_name\"[^{}]*?\}",
        cleaned,
        flags=re.DOTALL,
    ):
        snippet = re.sub(r",\s*([}\]])", r"\1", match.group(0))
        try:
            rows.append(json.loads(snippet))
        except json.JSONDecodeError:
            continue
    if rows:
        return {"rows": rows}
    # Give up.
    raise json.JSONDecodeError("unrecoverable VLM JSON", content, 0)


def _enforce_single_image_payload(payload: dict[str, Any]) -> None:
    """Ensure exactly one image is attached for each VLM call."""

    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise VLMAPIError("Invalid VLM request payload: messages must be a non-empty list")

    first_message = messages[0]
    if not isinstance(first_message, dict):
        raise VLMAPIError("Invalid VLM request payload: first message must be an object")

    content = first_message.get("content")
    if not isinstance(content, list):
        raise VLMAPIError("Invalid VLM request payload: content must be a list")

    image_count = 0
    for item in content:
        if isinstance(item, dict) and item.get("type") == "image_url":
            image_count += 1

    if image_count != 1:
        raise VLMAPIError(
            "Invalid VLM request payload: exactly one image must be attached per call"
        )


async def process_image_with_qwen(file_bytes: bytes) -> list[VLMRow]:
    """
    Accepts raw file bytes (image or PDF) and returns validated structured rows.
    Fails closed on any API or parsing error.
    """
    images_formats = []

    # Check magic bytes for PDF
    if file_bytes.startswith(b"%PDF"):
        loop = asyncio.get_event_loop()

        def _render_pdf_sync(pdf_bytes: bytes) -> tuple[list[str], int]:
            """Render all pages to base64 JPEGs.

            Fast path uses pymupdf (fitz) with a thread pool sized by
            settings.pdf_render_concurrency — fitz is safe when each thread
            opens its own Document handle on the same in-memory bytes.
            Pdfplumber fallback stays serial (PIL/ghostscript not thread-safe).
            """
            from concurrent.futures import ThreadPoolExecutor

            images: list[str] = []
            total_bytes = 0

            # Fast path: pymupdf with parallel page rendering
            try:
                import pymupdf  # type: ignore

                # Probe page count + bounds with one handle.
                probe = pymupdf.open(stream=pdf_bytes, filetype="pdf")
                try:
                    page_count = probe.page_count
                    if page_count > settings.max_pdf_pages:
                        raise VLMParsingError("page_count_limit_exceeded")
                finally:
                    probe.close()

                zoom = max(1.0, settings.pdf_render_dpi / 72.0)

                def _render_one(page_index: int) -> bytes:
                    # Open per-thread handle — Document objects are not
                    # documented as thread-safe across threads.
                    d = pymupdf.open(stream=pdf_bytes, filetype="pdf")
                    try:
                        matrix = pymupdf.Matrix(zoom, zoom)
                        pix = d.load_page(page_index).get_pixmap(matrix=matrix, alpha=False)
                        return pix.tobytes("jpeg")
                    finally:
                        d.close()

                workers = max(1, int(settings.pdf_render_concurrency))
                rendered: list[bytes | None] = [None] * page_count
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    for i, jpeg_bytes in zip(
                        range(page_count),
                        ex.map(_render_one, range(page_count)),
                    ):
                        rendered[i] = jpeg_bytes

                for jpeg_bytes in rendered:
                    if jpeg_bytes is None:
                        continue
                    total_bytes += len(jpeg_bytes)
                    if total_bytes > settings.max_pdf_render_bytes:
                        raise VLMParsingError("pdf_render_bytes_limit_exceeded")
                    b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
                    images.append(f"data:image/jpeg;base64,{b64}")
                return images, total_bytes
            except VLMParsingError:
                raise
            except ImportError:
                pass
            except Exception as fitz_err:  # fall through to pdfplumber
                logger.warning(
                    "pymupdf render failed, falling back to pdfplumber: %s",
                    type(fitz_err).__name__,
                )

            # Fallback: pdfplumber (serial — not thread-safe)
            images = []
            total_bytes = 0
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                if len(pdf.pages) > settings.max_pdf_pages:
                    raise VLMParsingError("page_count_limit_exceeded")
                for page in pdf.pages:
                    rendered = page.to_image(resolution=settings.pdf_render_dpi)
                    with io.BytesIO() as buffer:
                        rendered.original.convert("RGB").save(buffer, format="JPEG")
                        jpeg_bytes = buffer.getvalue()
                    total_bytes += len(jpeg_bytes)
                    if total_bytes > settings.max_pdf_render_bytes:
                        raise VLMParsingError("pdf_render_bytes_limit_exceeded")
                    b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
                    images.append(f"data:image/jpeg;base64,{b64}")
            return images, total_bytes

        try:
            # Scale timeout with page count — 19 pages @ 96dpi takes ~20s on CPU.
            render_timeout = max(
                settings.pdf_render_timeout_s,
                settings.pdf_render_timeout_s * 3,
                60.0,
            )
            images_formats, _ = await asyncio.wait_for(
                loop.run_in_executor(None, _render_pdf_sync, file_bytes),
                timeout=render_timeout,
            )
        except TimeoutError as e:
            logger.error(
                "Failed to parse PDF bytes: error_type=TimeoutError timeout_s=%s",
                render_timeout,
            )
            raise VLMParsingError("pdf_render_timeout") from e
        except VLMParsingError:
            raise
        except Exception as e:
            logger.error("Failed to parse PDF bytes: error_type=%s msg=%s", type(e).__name__, e)
            raise VLMParsingError("Invalid PDF bytes") from e
    else:
        # Assume it's a valid image (JPEG/PNG/etc)
        base64_image = base64.b64encode(file_bytes).decode("utf-8")
        images_formats.append(f"data:image/jpeg;base64,{base64_image}")

    prompt = (
        "You are extracting every lab test result from a clinical laboratory report. "
        "The report may have multiple sections (Biochemistry, Liver enzymes, Lipid panel, "
        "Glucose, HbA1c, Urine, CBC, differential count, thyroid, iron studies, "
        "vitamins, electrophoresis, serology, urinalysis, etc.) and multiple pages. "
        "Extract EVERY analyte row that has a measured result, including numeric, "
        "comparator ('<0.1','>90'), textual ('Absent','Present (+)','Non Reactive', "
        "'Pale Yellow','Clear','Nil','1-2','Normochromic Normocytic'), ratio (e.g. 3.1), "
        "and qualitative rows. Emit one row per analyte — do NOT merge percentage and "
        "absolute-count pairs. "
        "For CBC: extract separately each of Hemoglobin, RBC Count, Hematocrit, MCV, "
        "MCH, MCHC, RDW-CV, WBC Count, Neutrophils (%), Lymphocytes (%), Eosinophils (%), "
        "Monocytes (%), Basophils (%), Absolute Neutrophil Count, Absolute Lymphocyte "
        "Count, Absolute Eosinophil Count, Absolute Monocyte Count, Absolute Basophil "
        "Count, Platelet Count, MPV, RBC Morphology, WBC Morphology, Platelets Morphology, "
        "Parasites, ESR. For lipid panel: Cholesterol, Triglyceride, HDL, Direct LDL, "
        "VLDL, CHOL/HDL Ratio, LDL/HDL Ratio. For biochemistry: Sodium, Potassium, "
        "Chloride, Urea (BUN), Blood Urea Nitrogen, Creatinine, eGFR, Uric Acid, "
        "Calcium, AST (SGOT), ALT (SGPT), ALP, GGT, Total Protein, Albumin, Globulin, "
        "A/G Ratio, Total Bilirubin, Direct/Conjugated Bilirubin, Indirect/Unconjugated "
        "Bilirubin, Delta Bilirubin. For glucose/HbA1c: Fasting Blood Sugar, Mean Blood "
        "Glucose, HbA1c (both % DCCT and mmol/mol IFCC channels separately). For thyroid: "
        "T3, T4, TSH. For iron: Iron, TIBC, Transferrin Saturation, Ferritin. For "
        "vitamins: Vitamin B12, 25(OH) Vitamin D, Folate. For special: PSA, IgE, "
        "Homocysteine. For electrophoresis: Hb A, Hb A2, Foetal Hb, P2 Peak, P3 Peak, "
        "F Concentration, A2 Concentration, Electrophoresis Interpretation. For "
        "urinalysis: Colour, Clarity, pH, Specific Gravity, Urine Glucose, Urine "
        "Protein, Bilirubin, Urobilinogen, Urine Ketone, Nitrite, Pus Cells, Red Cells, "
        "Epithelial Cells, Casts, Crystals, Amorphous Material. For serology: HIV, "
        "HBsAg, ABO Type, Rh(D) Type. For urine microalbumin: Microalbumin. "
        "Preserve the EXACT printed reference range as 'reference_range_raw' (copy "
        "multi-line category tables verbatim joined with '; ', e.g. 'Desirable: <200; "
        "Borderline: 200-239; High: >240'). If no reference range is printed for the "
        "row, use empty string. "
        "Do NOT extract: diagnostic interpretation tables (category definitions without "
        "patient values), footer/method/location text, collection timestamps. "
        "Return a JSON object with a single key 'rows' containing a list of objects. "
        "Each object must have: 'analyte_name' (the English name of the test as printed), "
        "'value' (the measured value as a string, preserving comparators '<0.1', textual "
        "results like 'Absent', H/L flags if printed), 'unit' (the measurement unit "
        "exactly as printed — '/cmm', '10^3/uL', 'fL', 'pg', 'g/dL', '%', 'ng/mL', "
        "'pg/mL', 'microIU/mL', 'mg/L', 'IU/mL', 'micromol/L', etc.), "
        "'reference_range_raw' (the printed reference range/category text for that row), "
        "'row_bbox_ymin_xmin_ymax_xmax' (array of 4 integers, use [0,0,0,0] if unknown), "
        "and 'confidence_score' (integer 0-100). "
        "Do not include policy, severity, or next-step logic. Only extract the data "
        "printed in the report."
    )

    headers = {
        "Authorization": f"Bearer {settings.qwen_api_key}",
        "Content-Type": "application/json",
    }

    all_rows: list[VLMRow] = []

    _MAX_RETRIES = 5
    _BASE_BACKOFF_S = 2.0

    # Concurrency cap — re-uses existing pdf_render_concurrency knob to keep
    # us comfortably under DashScope QPS. Hardcoded inter-page sleep removed;
    # the existing 429/5xx exponential backoff handles rate limits.
    sem = asyncio.Semaphore(max(1, int(settings.pdf_render_concurrency)))

    async def _process_page(page_index: int, img_data: str) -> list[VLMRow]:
        payload = {
            "model": settings.qwen_vl_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": img_data}},
                    ],
                }
            ],
            "response_format": {"type": "json_object"},
        }
        _enforce_single_image_payload(payload)

        response = None
        last_exc: Exception | None = None
        async with sem:
            for attempt in range(_MAX_RETRIES):
                try:
                    async with httpx.AsyncClient(timeout=120.0) as client:
                        response = await client.post(
                            f"{settings.qwen_base_url}/chat/completions",
                            headers=headers,
                            json=payload,
                        )
                        if response.status_code in (408, 425, 429, 500, 502, 503, 504):
                            raise httpx.HTTPStatusError(
                                f"transient_status_{response.status_code}",
                                request=response.request,
                                response=response,
                            )
                        response.raise_for_status()
                    last_exc = None
                    break
                except httpx.HTTPError as e:
                    last_exc = e
                    status_code = getattr(getattr(e, "response", None), "status_code", None)
                    if attempt < _MAX_RETRIES - 1 and status_code in (
                        408, 425, 429, 500, 502, 503, 504, None
                    ):
                        sleep_s = _BASE_BACKOFF_S * (2 ** attempt)
                        try:
                            ra = e.response.headers.get("retry-after") if e.response is not None else None
                            if ra:
                                sleep_s = max(sleep_s, float(ra))
                        except Exception:
                            pass
                        logger.warning(
                            "VLM retry page=%d attempt=%d/%d status=%s sleep=%.1fs",
                            page_index, attempt + 1, _MAX_RETRIES, status_code, sleep_s,
                        )
                        await asyncio.sleep(sleep_s)
                        continue
                    break

        if last_exc is not None:
            e = last_exc
            try:
                response_obj = e.response
            except Exception:
                response_obj = None
            try:
                request_obj = e.request
            except Exception:
                request_obj = None
            status_code = response_obj.status_code if response_obj is not None else None
            request_headers = _redact(request_obj.headers if request_obj is not None else None)
            logger.error(
                "VLM API request failed: error_type=%s status_code=%s request_headers=%s",
                type(e).__name__,
                status_code,
                request_headers,
            )
            raise VLMAPIError("Failed to communicate with Qwen VLM API") from e

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            parsed_data = _parse_vlm_json(content)
            validated_response = VLMResponse.model_validate(parsed_data)
            for row in validated_response.rows:
                row.source_page = page_index
            return list(validated_response.rows)
        except (KeyError, IndexError, json.JSONDecodeError, ValidationError) as e:
            # Don't abort the whole PDF on one bad page — log + skip.
            logger.warning(
                "vlm_page_parse_failed page=%d err=%s: skipping page",
                page_index, e,
            )
            return []

    # Run all pages concurrently (bounded by sem). Per-page exceptions other
    # than parse errors propagate — a single unrecoverable VLM failure is a
    # hard failure for the job (matches previous sequential semantics).
    tasks = [
        _process_page(i, img)
        for i, img in enumerate(images_formats, start=1)
    ]
    per_page_results = await asyncio.gather(*tasks)
    for rows in per_page_results:
        all_rows.extend(rows)

    # Filter out low-confidence extractions to reduce garbage downstream.
    min_conf = settings.min_vlm_confidence
    filtered = [row for row in all_rows if row.confidence_score >= min_conf]
    if len(filtered) < len(all_rows):
        logger.warning(
            "Dropped %d low-confidence rows (threshold=%d)",
            len(all_rows) - len(filtered),
            min_conf,
        )
    return filtered


async def generate_text_with_qwen(
    prompt: str, response_format: dict[str, Any] | None = None
) -> str:
    """Text-only completion endpoint for LLM text processing agents."""
    headers = {
        "Authorization": f"Bearer {settings.qwen_api_key}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "model": settings.qwen_model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if response_format:
        payload["response_format"] = response_format

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{settings.qwen_base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPError as e:
        try:
            response_obj = e.response
        except Exception:
            response_obj = None
        try:
            request_obj = e.request
        except Exception:
            request_obj = None
        status_code = response_obj.status_code if response_obj is not None else None
        request_headers = _redact(request_obj.headers if request_obj is not None else None)
        logger.error(
            "Text API request failed: error_type=%s status_code=%s request_headers=%s",
            type(e).__name__,
            status_code,
            request_headers,
        )
        raise VLMAPIError("Failed to communicate with Qwen Text API") from e

    try:
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        logger.error("Failed to parse text response: %s", e)
        raise VLMParsingError("Invalid output from Qwen Text API") from e
