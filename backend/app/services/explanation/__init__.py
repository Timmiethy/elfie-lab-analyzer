"""Explanation adapter: bounded Qwen output (blueprint section 3.11).

Input: structured findings only. No raw source document context.
Output: headline, finding bullets, paragraph, next-step sentence, disclaimer.
Falls back to deterministic templates on failure.
"""


class ExplanationAdapter:
    async def generate(self, findings: list[dict], language: str) -> dict:
        raise NotImplementedError
