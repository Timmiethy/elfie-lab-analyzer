import re

with open("app/workers/pipeline.py", encoding="utf-8") as f:
    content = f.read()

replacement = """    if lane_type == "structured":
        import json
        try:
            payload = json.loads(file_bytes)
        except json.JSONDecodeError:
            raise ValueError("invalid_json_payload")
            
        observations = payload.get("observations")
        return _validate_structured_observations(observations, document_id=job_uuid)"""

content = re.sub(
    r'    if lane_type == "structured":\s+import json\s+try:\s+payload = json\.loads\(file_bytes\)\s+except json\.JSONDecodeError:\s+raise ValueError\("invalid_json_payload"\)\s+observations = payload\.get\("observations"\)\s+if not isinstance\(observations, list\):\s+raise ValueError\("structured_observations_not_list"\)\s+for obs in observations:\s+if "source_page" not in obs or "raw_analyte_label" not in obs or "raw_value_string" not in obs:\s+raise ValueError\("structured_observation_missing_fields"\)\s+return observations',
    replacement,
    content,
    flags=re.MULTILINE,
)

with open("app/workers/pipeline.py", "w", encoding="utf-8") as f:
    f.write(content)
