with open("d:/elfie-lab-analyzer/backend/app/workers/pipeline.py") as f:
    code = f.read()

old_extract_def = """async def _extract_rows(
    job_uuid: UUID,
    *,
    file_bytes: bytes | None,
) -> list[dict]:
    if file_bytes is None:
        return _seed_extracted_rows(job_uuid)

    rows = await process_image_with_qwen(file_bytes)"""

new_extract_def = """async def _extract_rows(
    job_uuid: UUID,
    *,
    file_bytes: bytes | None,
    lane_type: str | None = None,
) -> list[dict]:
    if file_bytes is None:
        return _seed_extracted_rows(job_uuid)

    if lane_type == "structured":
        import json
        try:
            payload = json.loads(file_bytes)
        except json.JSONDecodeError:
            raise ValueError("invalid_json_payload")
            
        observations = payload.get("observations")
        if not isinstance(observations, list):
            raise ValueError("structured_observations_not_list")
            
        for obs in observations:
            if "source_page" not in obs or "raw_analyte_label" not in obs or "raw_value_string" not in obs:
                raise ValueError("structured_observation_missing_fields")
        return observations

    rows = await process_image_with_qwen(file_bytes)"""

code = code.replace(old_extract_def, new_extract_def)

# Update call site too
old_call = """            extracted_rows = await _extract_rows(
                job_uuid,
                file_bytes=file_bytes,
            )"""

new_call = """            extracted_rows = await _extract_rows(
                job_uuid,
                file_bytes=file_bytes,
                lane_type=selected_lane,
            )"""

code = code.replace(old_call, new_call)

with open("d:/elfie-lab-analyzer/backend/app/workers/pipeline.py", "w") as f:
    f.write(code)
