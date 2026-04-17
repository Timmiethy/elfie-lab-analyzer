import re

with open("app/workers/pipeline.py", encoding="utf-8") as f:
    content = f.read()

# Find the call to _build_render_context
# and add render_context['trust_status'] override for image_beta
replacement = """            render_context = _build_render_context(
                job_uuid,
                patient_context["language_id"],
                normalized_observations,
                findings,
                comparable_history,
            )

            if selected_lane == "image_beta":
                render_context["trust_status"] = TrustStatus.NON_TRUSTED_BETA
"""

content = re.sub(
    r'            render_context = _build_render_context\(\s+job_uuid,\s+patient_context\["language_id"\],\s+normalized_observations,\s+findings,\s+comparable_history,\s+\)',
    replacement,
    content,
    flags=re.MULTILINE,
)

with open("app/workers/pipeline.py", "w", encoding="utf-8") as f:
    f.write(content)
