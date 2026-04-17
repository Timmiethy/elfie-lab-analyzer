with open("app/services/input_gateway/__init__.py", encoding="utf-8") as f:
    text = f.read()

replacement = """        if extension == ".json":
            lane_type = "structured"
        elif extension == ".pdf":
            try:
                import pdf_inspector
                result = pdf_inspector.process_pdf_bytes(file_bytes)
                if result.pdf_type == "text":
                    lane_type = "trusted_pdf"
                else:
                    lane_type = "image_beta" # Send scanned/mixed to minerU/VLM
            except Exception:
                lane_type = "trusted_pdf"
        else:"""

text = text.replace(
    '        if extension == ".json":\n            lane_type = "structured"\n        elif extension == ".pdf":\n            lane_type = "trusted_pdf"\n        else:',
    replacement,
)

with open("app/services/input_gateway/__init__.py", "w", encoding="utf-8") as f:
    f.write(text)
