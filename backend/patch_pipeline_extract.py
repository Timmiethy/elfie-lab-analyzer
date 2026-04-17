import re

with open("app/workers/pipeline.py", encoding="utf-8") as f:
    text = f.read()

# Make sure imports exist
if "from app.services.mineru_adapter import MineruAdapter" not in text:
    text = "from app.services.mineru_adapter import MineruAdapter\n" + text
if "from app.services.lab_normalizer import LabNormalizer" not in text:
    text = "from app.services.lab_normalizer import LabNormalizer\n" + text

replacement = """    if lane_type == "structured":
        import json
        try:
            payload = json.loads(file_bytes)
        except json.JSONDecodeError:
            raise ValueError("invalid_json_payload")
            
        observations = payload.get("observations")
        return _validate_structured_observations(observations, document_id=job_uuid)

    adapter = MineruAdapter(mode="ocr" if lane_type == "image_beta" else "auto")
    mineru_output = await adapter.execute(file_bytes)
    
    if mineru_output.get("status") == "error":
        raise ValueError("mineru_pipeline_failed")
        
    return LabNormalizer().normalize(mineru_output["content"].get("blocks", []), document_id=job_uuid)
"""

regex = r'    if lane_type == "structured":.*?(?=\n\nasync def _persist_row_level)'
text = re.sub(regex, replacement, text, flags=re.DOTALL)

with open("app/workers/pipeline.py", "w", encoding="utf-8") as f:
    f.write(text)
