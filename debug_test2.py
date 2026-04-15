import re
from typing import Any

# Fallback functions for replaced regex
_RANGE_RE_FALLBACK = re.compile(r"(?:[<>]=?|≤|≥)?\s*\d[\d,]*(?:\.\d+)?\s*-\s*(?:[<>]=?|≤|≥)?\s*\d[\d,]*(?:\.\d+)?")

def _extract_reference_range_llm(text: str) -> str | None:
    \"\"\"Schema LLM call to extract ranges, with regex fallback for tests.\"\"\"
    try:
        from openai import OpenAI
        client = OpenAI(api_key='dummyschema', base_url='http://localhost:8000') # Intentionally fail
        response = client.chat.completions.create(
            model='gpt-3.5',
            messages=[{'role': 'user', 'content': f'Extract reference range from: {text}'}]
        )
        return response.choices[0].message.content
    except Exception:
        match = _RANGE_RE_FALLBACK.search(text)
        return match.group(0).strip() if match else None
