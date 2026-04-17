import asyncio
import base64
import io
import json
import logging
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
        try:
            pdf = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: pdfplumber.open(io.BytesIO(file_bytes))),
                timeout=settings.pdf_render_timeout_s,
            )
            rendered_bytes = 0
            with pdf:
                if len(pdf.pages) > settings.max_pdf_pages:
                    raise VLMParsingError("page_count_limit_exceeded")
                semaphore = asyncio.Semaphore(max(1, settings.pdf_render_concurrency))
                bytes_lock = asyncio.Lock()

                async def _render_page(_page: Any) -> str:
                    nonlocal rendered_bytes

                    async with semaphore:
                        rendered = await asyncio.wait_for(
                            loop.run_in_executor(
                                None,
                                lambda p=_page: p.to_image(resolution=settings.pdf_render_dpi),
                            ),
                            timeout=settings.pdf_render_timeout_s,
                        )

                    with io.BytesIO() as buffer:
                        rendered.original.convert("RGB").save(buffer, format="JPEG")
                        jpeg_bytes = buffer.getvalue()

                    async with bytes_lock:
                        rendered_bytes += len(jpeg_bytes)
                        if rendered_bytes > settings.max_pdf_render_bytes:
                            raise VLMParsingError("pdf_render_bytes_limit_exceeded")

                    base64_image = base64.b64encode(jpeg_bytes).decode("utf-8")
                    return f"data:image/jpeg;base64,{base64_image}"

                page_tasks = [_render_page(page) for page in pdf.pages]
                images_formats.extend(await asyncio.gather(*page_tasks))
        except TimeoutError as e:
            logger.error(
                "Failed to parse PDF bytes: error_type=TimeoutError timeout_s=%s",
                settings.pdf_render_timeout_s,
            )
            raise VLMParsingError("pdf_render_timeout") from e
        except VLMParsingError:
            raise
        except Exception as e:
            logger.error("Failed to parse PDF bytes: error_type=%s", type(e).__name__)
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

    all_rows = []

    for page_index, img_data in enumerate(images_formats, start=1):
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

            parsed_data = json.loads(content)
            validated_response = VLMResponse.model_validate(parsed_data)
            for row in validated_response.rows:
                row.source_page = page_index
            all_rows.extend(validated_response.rows)
        except (KeyError, IndexError, json.JSONDecodeError, ValidationError) as e:
            logger.error("Failed to parse VLM response: %s", e)
            raise VLMParsingError("Invalid structured output from VLM") from e

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
