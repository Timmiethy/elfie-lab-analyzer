import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.vlm_gateway import (
    VLMAPIError,
    VLMParsingError,
    VLMRow,
    process_image_with_qwen,
)


@pytest.fixture
def image_bytes():
    return b"fake_image_bytes"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post", new_callable=AsyncMock)
async def test_process_image_with_qwen_success(mock_post, image_bytes):
    # Given a successful VLM API response with valid structured data
    mock_response_data = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "rows": [
                                {
                                    "raw_text": "Cholesterol 200 mg/dL",
                                    "analyte_name": "Cholesterol",
                                    "value": "200",
                                    "unit": "mg/dL",
                                    "reference_range_raw": "< 200",
                                }
                            ]
                        }
                    )
                }
            }
        ]
    }

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = mock_response_data
    mock_post.return_value = mock_response

    # When we process the image
    result = await process_image_with_qwen(image_bytes)

    # Then it returns a list of VLMRow objects
    assert len(result) == 1
    assert isinstance(result[0], VLMRow)
    assert result[0].analyte_name == "Cholesterol"
    assert result[0].value == "200"
    assert result[0].unit == "mg/dL"

    # And the outbound request always includes exactly one image attachment.
    _, call_kwargs = mock_post.await_args
    payload = call_kwargs["json"]
    content = payload["messages"][0]["content"]
    image_items = [item for item in content if item.get("type") == "image_url"]
    text_items = [item for item in content if item.get("type") == "text"]
    assert len(image_items) == 1
    assert len(text_items) == 1


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post", new_callable=AsyncMock)
async def test_process_image_with_qwen_api_failure(mock_post, image_bytes):
    # Given an API failure (e.g., 500 error)
    mock_post.side_effect = httpx.HTTPError("API error")

    # When we process the image, it fails closed with VLMAPIError
    with pytest.raises(VLMAPIError, match="Failed to communicate with Qwen VLM API"):
        await process_image_with_qwen(image_bytes)


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post", new_callable=AsyncMock)
async def test_process_image_with_qwen_parsing_failure(mock_post, image_bytes):
    # Given a successful API response but invalid content format
    mock_response_data = {"choices": [{"message": {"content": "Not a JSON"}}]}

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = mock_response_data
    mock_post.return_value = mock_response

    # When we process the image, it fails closed with VLMParsingError
    with pytest.raises(VLMParsingError, match="Invalid structured output from VLM"):
        await process_image_with_qwen(image_bytes)


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post", new_callable=AsyncMock)
async def test_process_image_with_qwen_schema_validation_failure(mock_post, image_bytes):
    # Given a successful API response but content missing required fields
    mock_response_data = {
        "choices": [{"message": {"content": json.dumps({"rows": "this should be a list"})}}]
    }

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = mock_response_data
    mock_post.return_value = mock_response

    # When we process the image, it fails closed with VLMParsingError
    # due to validation error
    with pytest.raises(VLMParsingError, match="Invalid structured output from VLM"):
        await process_image_with_qwen(image_bytes)
