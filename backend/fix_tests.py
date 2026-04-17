import re

with open("tests/unit/test_phase_28_pipeline_refactor_guards.py", encoding="utf-8") as f:
    content = f.read()

# Fix image beta lane uses vlm backend once: update VLMRow attributes
content = re.sub(
    r'VLMRow\(\s*raw_text=".*?",\s*raw_analyte_label="Glucose",\s*raw_value_string="180",\s*raw_unit_string="mg/dL",\s*raw_reference_range="70-99",\s*\)',
    'VLMRow(analyte_name="Glucose", value="180", unit="mg/dL", reference_range_raw="70-99")',
    content,
    flags=re.MULTILINE,
)

# Fix structured lane missing fields test (remove raw_analyte_label)
content = re.sub(
    r'"raw_analyte_label": "Glucose",\s*"raw_value_string": "96",',
    '"raw_value_string": "96",',
    content,
    flags=re.MULTILINE,
)

with open("tests/unit/test_phase_28_pipeline_refactor_guards.py", "w", encoding="utf-8") as f:
    f.write(content)
