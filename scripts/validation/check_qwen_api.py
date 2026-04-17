from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402


def _build_probe_png_data_url(*, width: int = 16, height: int = 16) -> str:
    """Create a small valid PNG data URL that satisfies provider min-dimension limits."""

    if width <= 10 or height <= 10:
        raise ValueError("probe image width/height must be greater than 10")

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return (
            struct.pack(">I", len(data))
            + chunk_type
            + data
            + struct.pack(">I", crc)
        )

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw_row = b"\x00" + (b"\xff\xff\xff" * width)
    raw_image = raw_row * height
    idat = zlib.compress(raw_image)

    png_bytes = signature + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _parse_args() -> argparse.Namespace:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(
        description="Run Qwen API diagnostics for text and VLM endpoints."
    )
    parser.add_argument(
        "--base-url",
        default=settings.qwen_base_url,
        help="Qwen base URL (OpenAI-compatible endpoint root).",
    )
    parser.add_argument(
        "--api-key",
        default=settings.qwen_api_key,
        help="API key. Defaults to ELFIE_QWEN_API_KEY from environment.",
    )
    parser.add_argument(
        "--text-model",
        default=settings.qwen_model,
        help="Text model used for chat completion probe.",
    )
    parser.add_argument(
        "--vlm-model",
        default=settings.qwen_vl_model,
        help="Vision model used for image extraction probe.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="HTTP timeout per diagnostic request.",
    )
    parser.add_argument(
        "--skip-vlm",
        action="store_true",
        help="Skip VLM/image endpoint probe.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "artifacts" / "validation" / f"qwen_diagnostics_{timestamp}.json",
        help="Output path for diagnostics JSON report.",
    )
    parser.add_argument(
        "--require-success",
        action="store_true",
        help="Exit non-zero if any mandatory diagnostic check fails.",
    )
    return parser.parse_args()


def _masked_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"


def _json_or_text(response: httpx.Response) -> Any:
    try:
        return response.json()
    except json.JSONDecodeError:
        return {"raw_text": response.text[:2000]}


def _probe_models_endpoint(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    response = client.get(f"{base_url}/models", headers=headers)
    payload = _json_or_text(response)
    return {
        "status_code": response.status_code,
        "ok": response.status_code == 200,
        "payload": payload,
    }


def _probe_text_completion(
    client: httpx.Client,
    *,
    base_url: str,
    headers: dict[str, str],
    model: str,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": "Reply with exactly OK.",
            }
        ],
        "temperature": 0,
        "max_tokens": 8,
    }
    response = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
    parsed = _json_or_text(response)

    content = ""
    if isinstance(parsed, dict):
        choices = parsed.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = str(message.get("content", "")).strip()

    return {
        "status_code": response.status_code,
        "ok": response.status_code == 200 and bool(content),
        "response_text": content,
        "payload": parsed,
    }


def _probe_vlm_completion(
    client: httpx.Client,
    *,
    base_url: str,
    headers: dict[str, str],
    model: str,
) -> dict[str, Any]:
    data_url = _build_probe_png_data_url()
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Return a JSON object with key 'rows' and a list value.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                ],
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 256,
    }

    response = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
    parsed = _json_or_text(response)

    content = ""
    if isinstance(parsed, dict):
        choices = parsed.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = str(message.get("content", "")).strip()

    structured_ok = False
    parse_error = None
    if content:
        try:
            maybe_json = content
            if maybe_json.startswith("```json"):
                maybe_json = maybe_json[7:]
            if maybe_json.endswith("```"):
                maybe_json = maybe_json[:-3]
            parsed_content = json.loads(maybe_json.strip())
            structured_ok = isinstance(parsed_content, dict) and "rows" in parsed_content
        except json.JSONDecodeError as exc:
            parse_error = str(exc)

    return {
        "status_code": response.status_code,
        "ok": response.status_code == 200 and structured_ok,
        "response_text": content,
        "parse_error": parse_error,
        "payload": parsed,
    }


def main() -> int:
    args = _parse_args()
    base_url = args.base_url.rstrip("/")

    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "base_url": base_url,
        "text_model": args.text_model,
        "vlm_model": args.vlm_model,
        "skip_vlm": bool(args.skip_vlm),
        "checks": {},
        "summary": {},
    }

    api_key = str(args.api_key or "")
    config_check = {
        "api_key_present": bool(api_key),
        "api_key_masked": _masked_key(api_key),
        "base_url_present": bool(base_url),
        "text_model_present": bool(args.text_model),
        "vlm_model_present": bool(args.vlm_model),
    }
    report["checks"]["config"] = config_check

    mandatory_failures: list[str] = []
    warnings: list[str] = []

    if not api_key:
        mandatory_failures.append("missing_api_key")
    if not base_url:
        mandatory_failures.append("missing_base_url")

    if not mandatory_failures:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=args.timeout_seconds) as client:
                models_check = _probe_models_endpoint(client, base_url, headers)
                report["checks"]["models_endpoint"] = models_check
                if not models_check["ok"]:
                    warnings.append("models_endpoint_unavailable")

                text_check = _probe_text_completion(
                    client,
                    base_url=base_url,
                    headers=headers,
                    model=args.text_model,
                )
                report["checks"]["text_completion"] = text_check
                if not text_check["ok"]:
                    mandatory_failures.append("text_completion_failed")

                if args.skip_vlm:
                    report["checks"]["vlm_completion"] = {
                        "status": "skipped",
                        "reason": "--skip-vlm flag used",
                    }
                else:
                    vlm_check = _probe_vlm_completion(
                        client,
                        base_url=base_url,
                        headers=headers,
                        model=args.vlm_model,
                    )
                    report["checks"]["vlm_completion"] = vlm_check
                    if not vlm_check["ok"]:
                        mandatory_failures.append("vlm_completion_failed")

        except httpx.HTTPError as exc:
            mandatory_failures.append(f"http_error:{exc}")

    report["summary"] = {
        "ok": len(mandatory_failures) == 0,
        "mandatory_failures": mandatory_failures,
        "warnings": warnings,
    }

    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Wrote diagnostics report: {output_path}")
    print(f"Qwen diagnostics OK: {report['summary']['ok']}")
    if mandatory_failures:
        print("Mandatory failures:")
        for failure in mandatory_failures:
            print(f"- {failure}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")

    if args.require_success and mandatory_failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
